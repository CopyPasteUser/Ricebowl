"""User-local installer that delegates to each component's tested installer."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .environment import bin_home, data_home


COMPONENTS = ("macmenu", "control-center", "macbar")
MANAGED_MARKER = ".macrice-managed"
REVISION_MARKER = ".macrice-revision"
LAUNCHER_MARKER = "# Managed by MacRice XFCE"
DESKTOP_MARKER = "X-MacRice-Managed=true"
HUB_LAUNCHER_MARKER = "# Managed by RiceHub XFCE"
HUB_DESKTOP_MARKER = "X-RiceHub-Managed=true"
FAST_TOGGLE_MARKER = "# Managed by RiceHub fast keyboard toggles"
RICEBOWL_LAUNCHER_MARKER = "# Managed by RiceBowl XFCE"
RICEBOWL_DESKTOP_MARKER = "X-RiceBowl-Managed=true"
CREATOR_DESKTOP_MARKER = "X-RiceBowl-Creator-Managed=true"


class InstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallOptions:
    dry_run: bool = False
    no_start: bool = False
    bar_autostart: bool = False


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _check_layout(source: Path) -> None:
    from .heritage import PROFILES
    required = (
        "macrice/cli.py",
        "macrice/gui.py",
        "macrice/hub.py",
        "macrice/hub_catalog.py",
        "macrice/hub_art.py",
        "macrice/rice_windows.py",
        "macrice/window_geometry.py",
        "macrice/display_guard.py",
        "macrice/display_layout.py",
        "macrice/windows7_proto.py",
        "macrice/aero.py",
        "macrice/aero_shell.py",
        "macrice/aero_windows.py",
        "macrice/heritage.py",
        "macrice/heritage_shell.py",
        "macrice/plank.py",
        "macrice/rice.py",
        "macrice/asset_upgrade.py",
        "macrice/hardware_status.py",
        "macrice/riceware_cli.py",
        "macrice/riceware/__init__.py",
        "macrice/de/__init__.py",
        "macrice/de/diagnostics.py",
        "macrice/de/session.py",
        "macrice/de/display_restore.py",
        "macrice/de/notification_prefs.py",
        "macrice/de/resources/labwc/rc.xml",
        "macrice/de/resources/labwc/menu.xml",
        "macrice/de/recipes.py",
        "macrice/de/resources/recipes/classic.json",
        "macrice/de/resources/recipes/chrome.json",
        "macrice/de/resources/labwc/autostart",
        "macrice/de/resources/labwc/shutdown",
        "macrice/de/resources/waybar/config.jsonc",
        "macrice/de/resources/waybar/style.css",
        "macrice/de/resources/mako.conf",
        "macrice/riceware/spice.py",
        "macrice/riceware/pop.py",
        "macrice/riceware/plate.py",
        "macrice/riceware/plate_preview.py",
        "macrice/riceware/file_drop.py",
        "macrice/riceware/dnd_gtk.py",
        "macrice/riceware/wine.py",
        "macrice/riceware/wine_apps.py",
        "macrice/riceware/worker.py",
        "macrice/riceware/profiles.py",
        "macrice/riceware/packs.py",
        "macrice/riceware/pack_import.py",
        "RICEPACK_SPEC.md",
        "RICEWARE_FOUNDATIONS.md",
        "RICEWARE_MIGRATION_GUIDE.md",
        "RICEPLATE_DESKTOP_ROADMAP.md",
        "RICE_ECOSYSTEM_ROADMAP.md",
        "RICEBOWL_DE_ROADMAP.md",
        "WAYLAND_SESSION.md",
        "RICE_WINDOWS_ROADMAP.md",
        "macrice/preview.py",
        "macrice/thunar.py",
        "macrice/performance.py",
        "components/plank/README.md",
        "assets/plank-themes/MacRice-Frost-Glass/dock.theme",
        "assets/plank-themes/MacRice-Obsidian-Glass/dock.theme",
        "assets/wallpapers/aurora-night.jpg",
        "assets/wallpapers/aurora-day.jpg",
        "assets/wallpapers/aero-seven-blue.jpg",
        "assets/wallpapers/aero-seven-night.jpg",
        "assets/aero-penguin.svg",
        "assets/themes/RiceHub-Aero/gtk-3.0/gtk.css",
        "assets/themes/RiceHub-Aero/xfwm4/themerc",
        "assets/themes/RiceHub-Aero/xfwm4/close-active.png",
        "assets/icons/RiceHub-Aero/index.theme",
        "assets/icons/RiceHub-Aero/scalable/apps/start-here.svg",
        "assets/plank-themes/RiceHub-Aero-Glass/dock.theme",
        "components/macmenu/scripts/install_user.py",
        "components/control-center/install.sh",
        "components/macbar/install.sh",
        "launcher.py",
        "assets/macrice-symbolic.svg",
        "assets/ricehub-symbolic.svg",
        "assets/ricebowl-symbolic.svg",
        "assets/trusted-ricehub-assets.json",
        "assets/trusted-ricebowl-luna-091.json",
        "assets/trusted-ricebowl-aero-before-redesign.json",
        "assets/status/winxp/battery-50.svg",
        "assets/ricebowl-xp-start.svg",
        "assets/ricebowl-xp-user.svg",
        "assets/ricebowl-classic-start.svg",
        "assets/ricebowl-chrome-start.svg",
        "assets/ricebowl-frutiger-start.svg",
    ) + tuple(asset for profile in PROFILES.values() for asset in (
        f"assets/themes/{profile.theme}/gtk-3.0/gtk.css",
        f"assets/themes/{profile.theme}/xfwm4/themerc",
        f"assets/icons/{profile.icon_theme}/index.theme",
        f"assets/wallpapers/{profile.wallpaper}"))
    missing = [path for path in required if not (source / path).is_file()]
    if missing:
        raise InstallationError("Incomplete suite bundle: " + ", ".join(missing))


def _check_existing(target: Path) -> None:
    if target.is_symlink() or (target.exists() and not (target / MANAGED_MARKER).is_file()):
        raise InstallationError(f"Unmanaged installation at {target}; nothing replaced.")
    if target.exists() and target.stat().st_uid != os.getuid():
        raise InstallationError(f"Installation owned by another user: {target}")


def _check_system_package() -> None:
    if not shutil.which("dpkg-query"):
        return
    proc = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", "xfce-macmenu"],
        capture_output=True, text=True, timeout=3, check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip() == "install ok installed":
        raise InstallationError(
            "A system-wide xfce-macmenu DEB is installed. The suite will not "
            "remove packages or request sudo automatically. Run "
            "'sudo apt remove xfce-macmenu' yourself if you choose the user-local installer."
        )


def plan(source: Path, options: InstallOptions) -> list[tuple[str, list[str]]]:
    components = source / "components"
    return [
        (
            "MacMenu",
            ["/usr/bin/python3", str(components / "macmenu/scripts/install_user.py"),
             *(["--dry-run"] if options.dry_run else [])],
        ),
        (
            "Control Center",
            ["bash", str(components / "control-center/install.sh"),
             "--no-start" if options.no_start or options.dry_run else "--start-hidden"],
        ),
        (
            "MacBar",
            ["sh", str(components / "macbar/install.sh"),
             *(["--autostart"] if options.bar_autostart and not options.dry_run else [])],
        ),
    ]


def _copy_bundle(source: Path, stage: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {".git", "__pycache__", ".venv"}
                or name.endswith((".pyc", ".pyo"))}

    for folder in ("macrice", "components", "assets", "examples"):
        shutil.copytree(source / folder, stage / folder, ignore=ignore)
    for file in ("launcher.py", "README.md", "LICENSE", "ROADMAP.md", "RICE.md",
                 "RICEHUB.md", "RICEBOWL.md", "RICE_ECOSYSTEM_ROADMAP.md",
                 "RICEBOWL_DE_ROADMAP.md",
                 "WAYLAND_SESSION.md",
                 "RICE_WINDOWS_ROADMAP.md", "RICEWARE_FOUNDATIONS.md",
                 "RICEPACK_SPEC.md",
                 "RICEWARE_MIGRATION_GUIDE.md",
        "XFCE_RESOURCE_BOUNDARIES.md",
        "RICEPLATE_DESKTOP_ROADMAP.md",
                 "CONTRIBUTORS.md"):
        shutil.copy2(source / file, stage / file)
    (stage / MANAGED_MARKER).write_text("Managed by MacRice XFCE\n", encoding="ascii")
    # A staged Git archive has an explicit pinned revision. A regular checkout
    # can only claim its HEAD if no local edits changed the installed content.
    marker = source / REVISION_MARKER
    revision = None
    if marker.is_file() and not marker.is_symlink():
        revision = marker.read_text(encoding="ascii").strip()
    elif (source / ".git").is_dir() and not (source / ".git").is_symlink():
        try:
            status = subprocess.run(["git", "-C", str(source), "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=15, check=False)
            if status.returncode == 0 and not status.stdout:
                head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                      capture_output=True, text=True, timeout=15, check=False)
                if head.returncode == 0:
                    revision = head.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if revision and len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
        (stage / REVISION_MARKER).write_text(revision + "\n", encoding="ascii")


def _install_manager(source: Path) -> Path:
    data = data_home()
    target = data / "macrice"
    _check_existing(target)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".macrice-stage-", dir=data))
    prior = None
    try:
        _copy_bundle(source, stage)
        if target.exists():
            archive = data / "macrice-versions"
            archive.mkdir(mode=0o700, parents=True, exist_ok=True)
            prior = archive / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            os.replace(target, prior)
        try:
            os.replace(stage, target)
        except Exception:
            if prior is not None:
                os.replace(prior, target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def _write_entrypoints(installed: Path) -> None:
    binaries = bin_home()
    applications = data_home() / "applications"
    binaries.mkdir(mode=0o755, parents=True, exist_ok=True)
    applications.mkdir(mode=0o755, parents=True, exist_ok=True)

    launcher = binaries / "macrice"
    desktop = applications / "macrice.desktop"
    _check_entrypoints()
    content = '#!/bin/sh\n' + LAUNCHER_MARKER + '\nexec /usr/bin/python3 "' + str(installed / "launcher.py") + '" "$@"\n'
    _atomic_write(launcher, content, 0o755)

    desktop_content = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        "Name=MacRice Settings\nComment=Manage the macOS-inspired XFCE desktop\n"
        f'Exec="{launcher}" gui\n'
        f"Icon={installed / 'assets/macrice-symbolic.svg'}\n"
        "Terminal=false\nCategories=Settings;Utility;\nStartupNotify=true\n"
        f"{DESKTOP_MARKER}\n"
    )
    _atomic_write(desktop, desktop_content, 0o644)

    hub_launcher = binaries / "ricehub"
    hub_desktop = applications / "ricehub.desktop"
    hub_content = (
        '#!/bin/sh\n' + HUB_LAUNCHER_MARKER + '\n'
        + 'exec /usr/bin/python3 "' + str(installed / "launcher.py") + '" hub "$@"\n'
    )
    _atomic_write(hub_launcher, hub_content, 0o755)
    # New public name; keep the old aliases and on-disk state compatible.
    bowl_launcher = binaries / "ricebowl"
    bowl_content = (
        '#!/bin/sh\n' + RICEBOWL_LAUNCHER_MARKER + '\n'
        + 'case "${1:-}" in\n'
        + '  update) shift; if [ "$#" -eq 0 ]; then set -- check --refresh --preserve-checkout; fi\n'
        + '    exec /usr/bin/python3 "' + str(installed / "launcher.py") + '" update "$@" ;;\n'
        + '  de) exec /usr/bin/python3 "' + str(installed / "launcher.py") + '" "$@" ;;\n'
        + '  creator) exec /usr/bin/python3 "' + str(installed / "launcher.py") + '" "$@" ;;\n'
        + '  *) exec /usr/bin/python3 "' + str(installed / "launcher.py") + '" hub "$@" ;;\n'
        + 'esac\n'
    )
    _atomic_write(bowl_launcher, bowl_content, 0o755)
    fast_launcher = binaries / "ricehub-toggle"
    from .heritage import PROFILES
    heritage_commands = "".join(
        f"  {key}-{action}) app=io.github.copypasteuser.RiceHub.{key.title()}Shell; "
        f"action={'toggle-menu' if action == 'menu' else 'toggle-control'}; "
        f"profile={key}-shell; fallback={'--toggle-menu' if action == 'menu' else '--control'} ;;\n"
        for key in PROFILES for action in ("menu", "control")
    )
    fast_content = (
        "#!/bin/sh\n" + FAST_TOGGLE_MARKER + "\n"
        "[ \"$#\" -eq 1 ] || exit 2\n"
        "case \"$1\" in\n"
        "  aero-menu) app=io.github.copypasteuser.RiceHub.AeroShell; action=toggle-menu; profile=aero-shell; fallback=--toggle-menu ;;\n"
        "  aero-control) app=io.github.copypasteuser.RiceHub.AeroShell; action=toggle-control; profile=aero-shell; fallback=--control ;;\n"
        "  ten-menu) app=io.github.copypasteuser.RiceHub.TenShell; action=toggle-menu; profile=windows10-shell; fallback=--toggle-menu ;;\n"
        "  ten-control) app=io.github.copypasteuser.RiceHub.TenShell; action=toggle-control; profile=windows10-shell; fallback=--actions ;;\n"
        + heritage_commands
        + "  *) exit 2 ;;\n"
        "esac\n"
        "if command -v gapplication >/dev/null 2>&1; then\n"
        "  gapplication action \"$app\" \"$action\" >/dev/null 2>&1 && exit 0\n"
        "fi\n"
        f"exec {shlex.quote(str(launcher))} \"$profile\" \"$fallback\"\n"
    )
    _atomic_write(fast_launcher, fast_content, 0o755)
    hub_desktop_content = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        "Name=RiceBowl (legacy launcher)\nComment=Compatibility shortcut for the RiceBowl desktop manager\n"
        f'Exec="{hub_launcher}"\n'
        f"Icon={installed / 'assets/ricebowl-symbolic.svg'}\n"
        "Terminal=false\nCategories=Settings;Utility;\nStartupNotify=true\n"
        f"{HUB_DESKTOP_MARKER}\n"
    )
    # Preserve the legacy shortcut for compatibility without duplicate menu items.
    hub_desktop_content = hub_desktop_content.replace("StartupNotify=true\n",
                                                      "StartupNotify=true\nNoDisplay=true\n")
    _atomic_write(hub_desktop, hub_desktop_content, 0o644)
    bowl_desktop = applications / "ricebowl.desktop"
    bowl_desktop_content = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        "Name=RiceBowl\nComment=Explore and manage complete XFCE desktop styles\n"
        f'Exec="{bowl_launcher}"\n'
        f"Icon={installed / 'assets/ricebowl-symbolic.svg'}\n"
        "Terminal=false\nCategories=Settings;Utility;\nStartupNotify=true\n"
        f"{RICEBOWL_DESKTOP_MARKER}\n"
    )
    _atomic_write(bowl_desktop, bowl_desktop_content, 0o644)
    creator_desktop = applications / "ricebowl-creator.desktop"
    creator_desktop_content = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\n"
        "Name=Rice Creator (experimental)\n"
        "Comment=Create and preview safe offline Wayland rice drafts\n"
        f'Exec="{bowl_launcher}" creator\n'
        f"Icon={installed / 'assets/ricebowl-symbolic.svg'}\n"
        "Terminal=false\nCategories=Graphics;Utility;\nStartupNotify=true\n"
        f"{CREATOR_DESKTOP_MARKER}\n"
    )
    _atomic_write(creator_desktop, creator_desktop_content, 0o644)


def _check_entrypoints() -> None:
    """Never replace another application's command or desktop entry."""
    candidates = (
        (bin_home() / "macrice", LAUNCHER_MARKER),
        (data_home() / "applications/macrice.desktop", DESKTOP_MARKER),
        (bin_home() / "ricehub", HUB_LAUNCHER_MARKER),
        (bin_home() / "ricehub-toggle", FAST_TOGGLE_MARKER),
        (bin_home() / "ricebowl", RICEBOWL_LAUNCHER_MARKER),
        (data_home() / "applications/ricebowl.desktop", RICEBOWL_DESKTOP_MARKER),
        (data_home() / "applications/ricehub.desktop", HUB_DESKTOP_MARKER),
        (data_home() / "applications/ricebowl-creator.desktop", CREATOR_DESKTOP_MARKER),
    )
    for path, marker in candidates:
        if path.is_symlink() or (path.exists() and (
            not path.is_file() or marker not in path.read_text(encoding="utf-8", errors="replace")
        )):
            raise InstallationError(f"Unmanaged file at {path}; nothing replaced.")


def _atomic_write(target: Path, content: str, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".macrice-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(options: InstallOptions, source: Path | None = None, output=print) -> Path | None:
    if os.geteuid() == 0:
        raise InstallationError("Run as your normal desktop user, never with sudo.")
    source = source or project_root()
    _check_layout(source)
    _check_existing(data_home() / "macrice")
    _check_entrypoints()
    _check_system_package()

    commands = plan(source, options)
    if options.dry_run:
        output("Dry run: no files or XFCE settings will be changed.")
        output("Plank, XFCE themes, icons and the XFCE Panel stay untouched.")
        for name, argv in commands:
            output(f"  {name}: {' '.join(argv)}")
        from .plank import installed as plank_installed
        output("  Plank: " + ("existing system dock detected; preserved" if plank_installed()
                             else "not installed; optionally use 'sudo apt install plank'"))
        return None

    # The bundle is kept installed for later GUI-driven repairs. Each component
    # then uses its own battle-tested user-local upgrade and backup procedure.
    installed = _install_manager(source)
    for name, _ in commands:
        argv = dict(plan(installed, options))[name]
        output(f"Installing {name}...")
        try:
            result = subprocess.run(
                argv, cwd=installed / "components" /
                {"MacMenu": "macmenu", "Control Center": "control-center", "MacBar": "macbar"}[name],
                capture_output=True, text=True, timeout=90, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallationError(f"{name} did not finish: {exc}") from exc
        if result.returncode:
            # Show a bounded relevant error without dumping user-specific logs.
            detail = (result.stderr or result.stdout).strip()[-900:]
            raise InstallationError(f"{name} installation stopped: {detail}")
        output(f"  {name}: installed")

    _write_entrypoints(installed)
    from .plank import installed as plank_installed
    if plank_installed():
        output("Plank: existing dock detected; no changes to its settings or launchers.")
    else:
        output("Plank: not installed. Optional on Mint: sudo apt install plank")
    output("RiceBowl installed. Run 'ricebowl' (ricehub remains compatible).")
    output("The original MacRice manager remains available via 'macrice gui'.")
    output("The XFCE Panel was not replaced. No theme or icon was changed.")
    return installed
