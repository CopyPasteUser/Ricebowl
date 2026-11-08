"""Command-line entrypoint shared by the launcher, installer and GTK manager."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import __version__
from .environment import bin_home, detect, installed_components
from .installer import InstallOptions, InstallationError, install
from .themes import PRESETS, apply_preset


COMMANDS = {
    "menu": ("macmenu", "--toggle"),
    "center": ("macos-control-center-toggle",),
    "bar": ("macbar",),
    "dock": ("plank",),
}


def open_component(name: str) -> None:
    if name == "dock":
        from .plank import open_dock
        open_dock()
        return
    args = COMMANDS[name]
    executable = bin_home() / args[0]
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise InstallationError(f"{name} is not installed; run 'macrice install' first.")
    subprocess.Popen(
        [str(executable), *args[1:]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, start_new_session=True,
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="macrice", description="Manage the macOS-inspired XFCE Rice Suite"
    )
    p.add_argument("--version", action="version", version=f"MacRice {__version__}")
    commands = p.add_subparsers(dest="command")
    commands.add_parser("gui", help="Open the native GTK settings manager")
    commands.add_parser("hub", help="Open RiceBowl: discover, apply and restore desktop rices")
    commands.add_parser("preview", help="Preview the complete desktop and apply or restore its Rice")
    aero = commands.add_parser("aero-shell", help="Run or toggle the Windows 7-inspired taskbar and Start menu")
    ten_shell = commands.add_parser("windows10-shell", help="Run or quit the Windows 10-inspired taskbar and Start menu")
    ten_shell.add_argument("--quit", action="store_true")
    ten_shell.add_argument("--toggle-menu", action="store_true")
    ten_shell.add_argument("--actions", action="store_true")
    aero.add_argument("--quit", action="store_true", help="Stop the resident Aero taskbar")
    aero.add_argument("--toggle-menu", action="store_true")
    aero.add_argument("--control", action="store_true", help="Toggle the Aero Control Panel")
    for key in ("winxp", "winclassic", "chromeos", "frutiger"):
        shell = commands.add_parser(f"{key}-shell", help=f"Run or toggle the {key} taskbar and launcher")
        shell.add_argument("--quit", action="store_true")
        shell.add_argument("--toggle-menu", action="store_true")
        shell.add_argument("--control", action="store_true")
        if key == "frutiger":
            trace = shell.add_mutually_exclusive_group()
            trace.add_argument("--trace-actions", action="store_true",
                               help="Record only fixed Frutiger UI click/outcome labels to a private bounded file")
            trace.add_argument("--trace-stop", action="store_true", help="Stop Frutiger UI evidence recording")
            trace.add_argument("--trace-path", action="store_true", help="Print evidence file location without running the shell")
    commands.add_parser("session-sync", help="Reconcile active rice after XFCE autostart")
    de = commands.add_parser("de", help="Inspect experimental RiceBowl Wayland desktop prerequisites")
    de.add_argument("action", choices=(
        "check", "start", "shell", "catalog", "creator-api", "review", "draft-edit", "visual-compare",
        "visual-baseline",
        "capture", "render", "creator-status", "creator-stage", "creator-rollback",
        "creator-live-status", "creator-live-apply", "creator-live-restore",
        "pack-export", "pack-inspect", "pack-import", "asset-import", "notifications", "notification-dismiss",
        "notification-invoke",
        "settings",
        "audio-devices", "audio-default",
        "recipes", "recipe-init", "recipe-import", "recipe-export", "recipe-current",
        "recipe-select", "recipe-restore", "taskotto-export"))
    de.add_argument("--json", action="store_true", help="Read-only machine-readable preflight")
    de.add_argument("--nested", action="store_true",
                    help="Explicitly test a separate labwc session inside an active desktop")
    de.add_argument("--recipe", help="RicePlate recipe: built-in/imported ID or an owner-private absolute JSON path")
    de.add_argument("--compare", help="Base recipe ID or owner-private absolute path for read-only de review")
    de.add_argument("--reference", type=Path, help="Reference PNG for de visual-compare")
    de.add_argument("--actual", type=Path, help="Real Wayland PNG capture for de visual-compare")
    de.add_argument("--overlay", type=Path, help="New private overlay PNG for de visual-compare")
    de.add_argument("--heatmap", type=Path, help="New private difference PNG for de visual-compare")
    de.add_argument("--threshold", type=int, help="Per-channel RGB threshold 0-255 for de visual-compare")
    de.add_argument("--tolerance-radius", type=int, choices=(0, 1, 2),
                    help="Two-way local rasterization tolerance in pixels for visual QA")
    de.add_argument("--tolerant-heatmap", type=Path,
                    help="New private PNG of differences remaining after tolerance")
    de.add_argument("--baseline", type=Path,
                    help="Approved private JSON baseline for de visual-compare")
    de.add_argument("--max-changed-ratio", type=float,
                    help="Maximum tolerated changed-pixel fraction for de visual-baseline")
    de.add_argument("--approve-reference", action="store_true",
                    help="Explicitly approve a reviewed reference image for de visual-baseline")
    de.add_argument("--edit", type=Path, help="Owner-controlled absolute JSON edit operations for de draft-edit")
    de.add_argument("--metadata", type=Path, help="Optional provenance JSON for de pack-export")
    de.add_argument("--package", type=Path, help="Absolute .ricepack file for de pack-inspect/import")
    de.add_argument("--asset", type=Path, help="Absolute owner-controlled .png file for de asset-import")
    de.add_argument("--notification-id", type=int,
                    help="One active notification ID for explicit dismissal/invocation")
    de.add_argument("--action-key", help="Exact current Mako action key for notification-invoke")
    de.add_argument("--device-kind", choices=("sink", "source"),
                    help="Playback sink or recording source for de audio-default")
    de.add_argument("--device-name", help="Exact reviewed audio device name for de audio-default")
    de.add_argument("--expect-current", help="Optional previous default for concurrency-safe audio selection")
    de.add_argument("--expect-sha256", help="Reviewed recipe SHA-256 for Creator stage/live apply")
    de.add_argument("--expect-active", help="Optional selection guard for Creator stage/rollback/live")
    de.add_argument("--panel", choices=("waybar", "native"), default="waybar",
                    help="Session panel (native RicePlate is experimental and falls back to Waybar)")
    de.add_argument("--base", choices=("classic", "chrome"),
                    help="Bundled base recipe for de recipe-init")
    de.add_argument("--schema-version", type=int, choices=tuple(range(1, 11)), default=1,
                    help="Recipe schema for de recipe-init (1 flat, 2 widths, 3 nested, 4 shell, 5 icons, 6 menu, 7 controls, 8 layout, 9 components)")
    de.add_argument("--id", help="Lowercase recipe identifier for de recipe-init")
    de.add_argument("--name", help="Human-readable recipe name for de recipe-init")
    de.add_argument("--output", type=Path, help="New absolute .json, .toml, .png or .ricepack output")
    de.add_argument("--width", type=int, help="Headless de render capture width (640–4096)")
    de.add_argument("--height", type=int, help="Headless de render capture height (480–2160)")
    de.add_argument("--scale", type=float, choices=(1, 1.25, 1.5, 2),
                    help="Headless de render scale factor")
    commands.add_parser("session-menu", help="Toggle the active rice's application menu")
    commands.add_parser("session-control", help="Toggle the active rice's control panel")
    commands.add_parser("session-keys-restore", help="Restore the previous Super/Right Control shortcuts")
    xp_desktop = commands.add_parser("winxp-desktop", help="Manage optional XP XFDesktop shortcuts safely")
    xp_desktop.add_argument("action", choices=("status", "install", "remove"))
    commands.add_parser("status", help="Show installed components and the detected appearance")
    commands.add_parser("inspect", help="Print a safe, read-only JSON appearance report")
    doctor = commands.add_parser("doctor", help="Run read-only RiceBowl/XFCE health checks")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable health results")
    from .riceware.profiles import PROFILE_FAMILIES
    doctor.add_argument("--style", choices=tuple(PROFILE_FAMILIES),
                        help="Also preflight the chosen rice's real assets and desktop settings")
    app_compat = commands.add_parser("app-compat", help="Inspect a window's theme compatibility without modifying apps")
    target = app_compat.add_mutually_exclusive_group(required=True)
    target.add_argument("--select", action="store_true", help="Select an X11 window with the pointer")
    target.add_argument("--window-id", metavar="HEX", help="Inspect an existing hexadecimal X11 window ID")
    app_compat.add_argument("--json", action="store_true", help="Print sanitized machine-readable results")
    updater = commands.add_parser("update", help="Inspect or explicitly install a verified fast-forward revision")
    updater.add_argument("action", choices=("check", "apply"))
    updater.add_argument("--source", type=Path, help="Trusted RiceBowl Git checkout (defaults to ~/RiceBowl)")
    updater.add_argument("--refresh", action="store_true", help="Fetch origin/main before checking")
    updater.add_argument("--yes", action="store_true", help="Confirm a staged update with recovery")
    updater.add_argument("--revision", help="Optional exact 40-digit revision from update check")
    updater.add_argument("--preserve-checkout", action="store_true",
                         help="Opt in to installing from official Git while leaving a dirty source tree unchanged")
    installer = commands.add_parser("install", help="Install or repair the three bundled apps; preserve Plank")
    installer.add_argument("--dry-run", action="store_true", help="Do not write or start anything")
    installer.add_argument("--no-start", action="store_true", help="Install without launching GTK")
    installer.add_argument("--bar-autostart", action="store_true", help="Add MacBar to login without stopping XFCE Panel")
    theme = commands.add_parser("theme", help="Apply a consistent theme to the three apps only")
    theme.add_argument("preset", choices=PRESETS)
    opener = commands.add_parser("open", help="Launch/toggle one component")
    opener.add_argument("component", choices=tuple(COMMANDS))
    dock = commands.add_parser("dock", help="Inspect the existing dock or open its native preferences")
    dock.add_argument("action", choices=("status", "preferences"))
    rice = commands.add_parser("rice", help="Plan, apply or restore the complete XFCE desktop Rice")
    rice.add_argument("action", choices=("plan", "apply", "restore", "repair-assets"))
    from .rice import STYLES
    rice.add_argument("style", nargs="?", choices=tuple(STYLES))
    profile = commands.add_parser("performance", help="Apply a Control Center resource profile")
    profile.add_argument("profile", choices=("light", "balanced", "visual", "report", "desktop"))
    profile.add_argument("--json", action="store_true", help="Machine-readable on-demand report")
    profile.add_argument("--samples", type=int, default=3, metavar="N",
                         help="Read 1–9 short CPU/PSS samples for report/desktop (default: 3)")
    from .riceware_cli import add_commands
    add_commands(commands)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "riceware":
            from .riceware_cli import run as run_riceware
            return run_riceware(args)
        if args.command == "de":
            if args.action != "review" and args.compare is not None:
                raise ValueError("--compare only applies to de review")
            if args.action != "draft-edit" and args.edit is not None:
                raise ValueError("--edit only applies to de draft-edit")
            if args.action != "pack-export" and args.metadata is not None:
                raise ValueError("--metadata only applies to de pack-export")
            if args.action not in ("pack-inspect", "pack-import") and args.package is not None:
                raise ValueError("--package only applies to de pack-inspect/import")
            if args.action != "asset-import" and args.asset is not None:
                raise ValueError("--asset only applies to de asset-import")
            if args.action not in ("notification-dismiss", "notification-invoke") and args.notification_id is not None:
                raise ValueError("--notification-id only applies to notification mutations")
            if args.action != "notification-invoke" and args.action_key is not None:
                raise ValueError("--action-key only applies to de notification-invoke")
            if args.action != "audio-default" and any(value is not None for value in
                    (args.device_kind, args.device_name, args.expect_current)):
                raise ValueError("Audio device mutation options only apply to de audio-default")
            if args.action not in ("creator-stage", "creator-live-apply") and args.expect_sha256 is not None:
                raise ValueError("--expect-sha256 only applies to Creator stage/live apply")
            if args.action not in ("creator-stage", "creator-rollback", "creator-live-apply",
                                   "creator-live-restore") and args.expect_active is not None:
                raise ValueError("--expect-active only applies to Creator selection changes")
            if args.action not in ("visual-compare", "visual-baseline") and any(
                    value is not None for value in (args.reference, args.threshold,
                                                    args.tolerance_radius)):
                raise ValueError("Visual QA options only apply to visual-compare/baseline")
            if args.action != "visual-compare" and any(value is not None for value in
                    (args.actual, args.overlay, args.heatmap, args.tolerant_heatmap,
                     args.baseline)):
                raise ValueError("Comparison options only apply to de visual-compare")
            if args.action != "visual-baseline" and (
                    args.max_changed_ratio is not None or args.approve_reference):
                raise ValueError("Approval options only apply to de visual-baseline")
            if args.action != "render" and any(value is not None for value in
                    (args.width, args.height, args.scale)):
                raise ValueError("--width, --height and --scale only apply to de render")
            if args.action != "recipe-init" and any((args.base, args.id, args.name)):
                raise ValueError("--base, --id and --name only apply to de recipe-init")
            if args.action != "recipe-init" and args.schema_version != 1:
                raise ValueError("--schema-version only applies to de recipe-init")
            if (args.action not in ("recipe-init", "recipe-export", "taskotto-export",
                                    "draft-edit", "capture", "render", "pack-export",
                                    "visual-baseline") and args.output):
                raise ValueError("--output is not supported by this de command")
            if args.action == "creator-api":
                if args.nested or args.recipe or args.panel != "waybar":
                    raise ValueError("de creator-api accepts only --json")
                from .de.creator_contract import describe_creator_api
                contract = describe_creator_api()
                if args.json:
                    print(json.dumps(contract, indent=2))
                else:
                    print(f"RiceBowl Creator API v{contract['api_version']} (offline, on demand)")
                    for item in contract["commands"]:
                        print(f"  {item['command']:18} {item['effect']}")
                return 0
            if args.action == "settings":
                if args.json or args.nested or args.recipe or args.panel != "waybar":
                    raise ValueError("de settings opens a window and takes no session options")
                from .de.settings import launch
                launch()
                return 0
            if args.action in ("notifications", "notification-dismiss", "notification-invoke"):
                if args.nested or args.recipe or args.panel != "waybar" or not args.json:
                    raise ValueError("RicePop notification commands require --json and no session options")
                if args.action != "notifications" and args.notification_id is None:
                    raise ValueError("Notification mutations require --notification-id")
                if args.action == "notification-invoke" and args.action_key is None:
                    raise ValueError("de notification-invoke requires --action-key")
                from .de.notifications import NotificationBridgeError, dismiss, inspect, invalid, invoke
                try:
                    if args.action == "notifications":
                        result = inspect()
                    elif args.action == "notification-dismiss":
                        result = dismiss(args.notification_id)
                    else:
                        result = invoke(args.notification_id, args.action_key)
                except NotificationBridgeError as error:
                    print(json.dumps(invalid(error,
                                             attempted_dismiss=args.action == "notification-dismiss",
                                             attempted_invoke=args.action == "notification-invoke"), indent=2))
                    return 2
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0
            if args.action in ("audio-devices", "audio-default"):
                if args.nested or args.recipe or args.panel != "waybar" or not args.json:
                    raise ValueError("RiceSpice audio commands require --json and no session options")
                if args.action == "audio-default" and not (args.device_kind and args.device_name):
                    raise ValueError("de audio-default requires --device-kind and --device-name")
                from .de.audio_devices import AudioDeviceError, inspect, invalid, set_default
                try:
                    result = (inspect() if args.action == "audio-devices" else
                              set_default(args.device_kind, args.device_name,
                                          expected_current=args.expect_current))
                except AudioDeviceError as error:
                    print(json.dumps(invalid(error), indent=2))
                    return 2
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0
            if args.action in ("creator-status", "creator-stage", "creator-rollback"):
                if args.nested or args.panel != "waybar":
                    raise ValueError("Creator selection does not start a desktop session")
                if (args.action == "creator-stage" and
                        (not args.recipe or not args.expect_sha256)):
                    raise ValueError("de creator-stage needs --recipe and --expect-sha256")
                if args.action != "creator-stage" and args.recipe:
                    raise ValueError("Only de creator-stage accepts --recipe")
                from .de.staging import StageError, invalid_stage, rollback, stage, status
                try:
                    if args.action == "creator-status":
                        result = status()
                    elif args.action == "creator-stage":
                        result = stage(args.recipe, args.expect_sha256,
                                       expected_active=args.expect_active)
                    else:
                        result = rollback(expected_active=args.expect_active)
                except StageError as exc:
                    if not args.json:
                        raise
                    print(json.dumps(invalid_stage(exc), indent=2))
                    return 2
                if args.json:
                    print(json.dumps(result, indent=2))
                elif args.action == "creator-status":
                    print(f"Next Wayland login: {result['next_session']}")
                    print(f"Reviewed semantic SHA256: {result['semantic_sha256']}")
                else:
                    print(f"Next Wayland login: {result['next_session']} (was: {result['previous']})")
                    print("Current desktop unchanged; one-step rollback remains available")
                return 0
            if args.action in ("creator-live-status", "creator-live-apply", "creator-live-restore"):
                if args.nested or args.panel != "waybar":
                    raise ValueError("Live Creator commands connect to the current Wayland session")
                if (args.action == "creator-live-apply" and
                        (not args.recipe or not args.expect_sha256)):
                    raise ValueError("creator-live-apply requires --recipe ID and --expect-sha256")
                if args.action != "creator-live-apply" and args.recipe:
                    raise ValueError("Only creator-live-apply accepts --recipe")
                from .de.live import LiveError, request
                action = args.action.removeprefix("creator-live-")
                try:
                    result = request(action, recipe=args.recipe, sha256=args.expect_sha256,
                                     expected=args.expect_active)
                except LiveError as exc:
                    result = {"version": 1, "ok": False, "error": {
                        "code": exc.code, "message": str(exc)}}
                if args.json:
                    print(json.dumps(result, indent=2))
                elif result["ok"]:
                    print(f"Active Wayland rice: {result['active']} (previous: "
                          f"{result['previous'] or 'none'})")
                else:
                    print(f"Live rice: {result['error']['message']}", file=sys.stderr)
                return 0 if result["ok"] else 2
            if args.action == "asset-import":
                if (args.nested or args.panel != "waybar" or not args.asset or args.recipe
                        or args.output or args.package):
                    raise ValueError("de asset-import requires --asset absolute.png only")
                from .de.assets import import_png, AssetError
                try:
                    asset_id, location = import_png(args.asset)
                except AssetError as exc:
                    if not args.json:
                        raise
                    print(json.dumps({"ok": False, "imported": False, "applied": False,
                                      "error": {"code": "invalid_asset", "message": str(exc)}}))
                    return 2
                result = {"ok": True, "imported": True, "applied": False,
                          "asset_id": asset_id, "private_path": str(location)}
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"Stored private wallpaper {asset_id}. Add this ID to a schema-v6 recipe.")
                return 0
            if args.action in ("pack-export", "pack-inspect", "pack-import"):
                if args.nested or args.panel != "waybar":
                    raise ValueError("RicePack tools do not start a desktop session")
                if args.action == "pack-export":
                    if not args.recipe or not args.output or args.package:
                        raise ValueError("de pack-export requires --recipe and --output")
                elif not args.package or args.recipe or args.output:
                    raise ValueError("de pack-inspect/import require --package")
                from .de.pack import PackError, export_pack, import_pack, inspect_pack, invalid_pack
                try:
                    if args.action == "pack-export":
                        result = export_pack(args.recipe, args.output, metadata=args.metadata)
                    elif args.action == "pack-inspect":
                        result = inspect_pack(args.package)
                    else:
                        result = import_pack(args.package)
                except PackError as exc:
                    if not args.json:
                        raise
                    print(json.dumps(invalid_pack(exc), indent=2))
                    return 2
                if args.json:
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                elif args.action == "pack-export":
                    print(f"Exported portable recipe {result['recipe_id']} to {args.output}")
                elif args.action == "pack-inspect":
                    print(f"Valid RicePack: {result['manifest']['recipe']['id']}")
                else:
                    print(f"Imported private recipe {result['recipe_id']}; next session unchanged")
                return 0
            if args.action == "recipe-init":
                if (args.json or args.nested or args.recipe or args.panel != "waybar"
                        or not args.id or not args.name or not args.output):
                    raise ValueError("de recipe-init needs --id, --name and --output; optionally --base")
                from .de.recipes import create_from_template
                result = create_from_template(source=args.base or "classic",
                                              destination=args.output,
                                              recipe_id=args.id, name=args.name,
                                              schema_version=args.schema_version)
                print(f"Created private RicePlate recipe {result.recipe_id}: {args.output}")
                print(f"Preview: ricebowl de start --nested --recipe {shlex.quote(str(args.output))}")
                return 0
            if args.action == "recipe-import":
                if (args.json or args.nested or args.panel != "waybar" or not args.recipe):
                    raise ValueError("de recipe-import requires --recipe /absolute/file.json")
                from .de.recipes import import_recipe
                result, path = import_recipe(Path(args.recipe))
                print(f"Imported {result.recipe_id} into {path} (not applied)")
                print(f"Preview: ricebowl de start --nested --recipe {result.recipe_id}")
                return 0
            if args.action == "recipe-export":
                if (args.json or args.nested or args.panel != "waybar"
                        or not args.recipe or not args.output):
                    raise ValueError("de recipe-export requires --recipe ID and --output /absolute/file.json")
                from .de.recipes import export_recipe
                result = export_recipe(args.recipe, args.output)
                print(f"Exported {result.recipe_id} to {args.output} (not applied)")
                return 0
            if args.action == "taskotto-export":
                if (args.json or args.nested or args.panel != "waybar"
                        or not args.recipe or not args.output):
                    raise ValueError("de taskotto-export requires --recipe ID and --output /absolute/file.toml")
                from .de.taskotto import export
                result = export(args.recipe, args.output)
                print(f"Exported Taskotto RicePack v1 from {result.recipe_id}: {args.output}")
                print(f"Launch: RICEBOWL_TASKOTTO_RICEPACK={shlex.quote(str(args.output))} taskotto")
                return 0
            if args.action in ("recipe-current", "recipe-select", "recipe-restore"):
                if (args.nested or args.panel != "waybar"
                        or (args.action != "recipe-current" and args.json)):
                    raise ValueError("Recipe selection accepts only --recipe (select) or --json (current)")
                from .de.recipes import change_selection, current_selection
                if args.action == "recipe-current":
                    if args.recipe:
                        raise ValueError("de recipe-current is read-only and takes no --recipe")
                    active, previous = current_selection()
                    if args.json:
                        print(json.dumps({"active": active, "previous": previous}, indent=2))
                    else:
                        print(f"Next Wayland rice: {active} (previous: {previous or 'none'})")
                elif args.action == "recipe-select":
                    if not args.recipe:
                        raise ValueError("de recipe-select requires --recipe ID")
                    active, previous = change_selection(args.recipe)
                    print(f"Next Wayland rice: {active} (was: {previous}); current session unchanged")
                else:
                    if args.recipe:
                        raise ValueError("de recipe-restore accepts no --recipe")
                    active, previous = change_selection(restore=True)
                    print(f"Restored next Wayland rice: {active} (was: {previous})")
                return 0
            if args.action == "start":
                if args.json:
                    raise ValueError("--json only applies to de check")
                from .de.session import start
                return start(nested=args.nested, recipe=args.recipe, panel=args.panel)
            if args.action == "shell":
                if args.json or args.nested or args.recipe or args.panel != "waybar":
                    raise ValueError("de shell does not accept --json, --nested, --recipe or --panel")
                from .de.session import shell
                return shell()
            if args.action == "catalog":
                if args.nested or args.recipe or args.panel != "waybar":
                    raise ValueError("de catalog is read-only and accepts only --json")
                from .de.catalog import describe, validate_catalog_contract
                validate_catalog_contract()
                catalog = describe()
                if args.json:
                    print(json.dumps(catalog, indent=2))
                else:
                    print(f"RiceBowl shell component catalog v{catalog['catalog_version']}")
                    print("Supported by the experimental native panel / Waybar fallback:")
                    for component in catalog["components"]:
                        print(f"  {component['id']:8} {component['native']:12} / {component['waybar']}")
                    print("Full desktop composition and screenshot-to-rice conversion: not available")
                return 0
            if args.action == "review":
                if args.nested or args.panel != "waybar" or not args.recipe:
                    raise ValueError("de review requires --recipe and accepts only --compare and --json")
                from .de.review import invalid_review, review
                from .de.recipes import RecipeError
                try:
                    report = review(args.recipe, args.compare)
                except RecipeError:
                    if not args.json:
                        raise
                    print(json.dumps(invalid_review(), indent=2))
                    return 2
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                else:
                    summary = report["summary"]
                    print(f"Valid panel recipe: {summary['id']} (schema v{summary['schema_version']})")
                    print(f"Semantic SHA256: {summary['semantic_sha256']}")
                    missing = summary["native_unavailable_widgets"]
                    if missing:
                        print("Still requires Waybar for: " + ", ".join(missing))
                    if report["comparison"] is not None:
                        changes = report["comparison"]["changes"]
                        print(f"Changes from {report['comparison']['base_id']}: {len(changes)}")
                        for change in changes:
                            print(f"  {change['path']}: {change['before']!r} -> {change['after']!r}")
                    print("Read-only review; no desktop changes. Use a nested preview to inspect it.")
                return 0
            if args.action == "visual-baseline":
                if (args.nested or args.panel != "waybar" or not args.approve_reference
                        or args.reference is None or not args.recipe or args.output is None):
                    raise ValueError("de visual-baseline needs --approve-reference, --reference, "
                                     "--recipe and --output")
                from .de.visual_qa import create_baseline
                try:
                    baseline = create_baseline(
                        args.reference, args.recipe, args.output,
                        threshold=24 if args.threshold is None else args.threshold,
                        tolerance_radius=1 if args.tolerance_radius is None else args.tolerance_radius,
                        max_changed_ratio=(0.01 if args.max_changed_ratio is None
                                           else args.max_changed_ratio))
                except ValueError:
                    if not args.json:
                        raise
                    print(json.dumps({"creator_contract_version": 2, "ok": False,
                                      "applied": False, "error": {
                                          "code": "invalid_baseline_input",
                                          "message": "Invalid or unsafe visual baseline input"}},
                                     indent=2))
                    return 2
                if args.json:
                    print(json.dumps({"creator_contract_version": 2, "ok": True,
                                      "applied": False, "baseline": baseline}, indent=2))
                else:
                    print(f"Approved private visual baseline: {args.output}")
                    print("No active session or rice selection changed")
                return 0
            if args.action == "visual-compare":
                if (args.nested or args.panel != "waybar" or args.reference is None
                        or args.actual is None):
                    raise ValueError("de visual-compare requires --reference and --actual")
                if args.baseline is not None and (args.threshold is not None
                                                  or args.tolerance_radius is not None):
                    raise ValueError("Approved baselines pin threshold and tolerance; omit overrides")
                from .de.visual_qa import compare
                try:
                    report = compare(args.reference, args.actual,
                                     threshold=24 if args.threshold is None else args.threshold,
                                     recipe_token=args.recipe, overlay=args.overlay,
                                     heatmap=args.heatmap,
                                     tolerance_radius=(0 if args.tolerance_radius is None
                                                       else args.tolerance_radius),
                                     tolerant_heatmap=args.tolerant_heatmap, baseline=args.baseline)
                except ValueError:
                    if not args.json:
                        raise
                    print(json.dumps({"creator_contract_version": 2, "ok": False,
                                      "applied": False, "error": {
                                          "code": "invalid_visual_input",
                                          "message": "Invalid or unsafe visual comparison input"}},
                                     indent=2))
                    return 2
                passed = report.get("baseline", {}).get("passed", True)
                if args.json:
                    print(json.dumps({"creator_contract_version": 2, "ok": passed,
                                      "applied": False, "visual_qa": report}, indent=2))
                else:
                    print(f"RGB difference: {report['mean_absolute_rgb_error']:.4f} mean error, "
                          f"{report['changed_pixel_ratio']:.2%} changed pixels")
                    if "layout_issues" in report:
                        print(f"Declared panel/icon layout issues: {len(report['layout_issues'])}")
                    if "tolerance" in report:
                        print("Tolerance-adjusted changes: "
                              f"{report['tolerance']['changed_pixel_ratio']:.2%}")
                    if "baseline" in report:
                        print(f"Approved baseline: {'PASS' if passed else 'REGRESSION'}")
                    for artifact in ("overlay", "heatmap", "tolerant_heatmap"):
                        if artifact in report:
                            print(f"Created private {artifact}: {report[artifact]}")
                    print("Read-only comparison; no desktop change or fidelity certification")
                return 0 if passed else 3
            if args.action == "capture":
                if args.nested or args.panel != "waybar" or args.recipe:
                    raise ValueError("de capture accepts only --output and --json")
                from .de.capture import CaptureError, capture
                try:
                    report = capture(args.output)
                except CaptureError as exc:
                    if not args.json:
                        raise
                    print(json.dumps({"creator_contract_version": 1, "ok": False,
                                      "error": {"code": exc.code, "message": str(exc)}},
                                     indent=2))
                    return 2
                if args.json:
                    print(json.dumps({"creator_contract_version": 1, "ok": True,
                                      "capture": report}, indent=2))
                else:
                    print(f"Captured current Wayland display: {report['path']} "
                          f"({report['width']}x{report['height']})")
                    print("The capture may contain private screen data; no desktop change was made")
                return 0
            if args.action == "render":
                if args.nested or args.panel != "waybar":
                    raise ValueError("de render accepts --recipe, --output, --width, --height, --scale and --json")
                from .de.render import DEFAULT_HEIGHT, DEFAULT_WIDTH, RenderError, render
                try:
                    report = render(args.recipe, args.output,
                                    width=DEFAULT_WIDTH if args.width is None else args.width,
                                    height=DEFAULT_HEIGHT if args.height is None else args.height,
                                    scale=1.0 if args.scale is None else args.scale)
                except RenderError as exc:
                    if not args.json:
                        raise
                    print(json.dumps({"creator_contract_version": 1, "ok": False,
                                      "error": {"code": exc.code, "message": str(exc)}},
                                     indent=2))
                    return 2
                if args.json:
                    print(json.dumps({"creator_contract_version": 1, "ok": True,
                                      "render": report}, indent=2))
                else:
                    print(f"Rendered {report['recipe']['id']} in isolated labwc: {report['output']['path']}")
                    print("No active desktop changes; visual and interaction fidelity are not certified")
                return 0
            if args.action == "draft-edit":
                if (args.nested or args.panel != "waybar" or not args.recipe
                        or not args.edit or not args.output):
                    raise ValueError("de draft-edit requires --recipe, --edit and --output")
                from .de.drafts import DraftError, create_edit, invalid_edit
                try:
                    result = create_edit(recipe_token=args.recipe, edit_source=args.edit,
                                         destination=args.output)
                except DraftError as exc:
                    if not args.json:
                        raise
                    print(json.dumps(invalid_edit(exc), indent=2))
                    return 2
                if args.json:
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    print(f"Created private draft for {result['recipe_id']} ({len(result['changes'])} changes)")
                    print(f"Review/preview: ricebowl de review --recipe {shlex.quote(str(args.output))}")
                    print("Not applied or selected; the original recipe remains unchanged")
                return 0
            if args.action == "recipes":
                if args.nested or args.panel != "waybar":
                    raise ValueError("de recipes accepts only --recipe and --json")
                from .de.recipes import BUILTINS, imported_recipes, load
                recipes = ([load(args.recipe)] if args.recipe else
                           [load(name) for name in BUILTINS]
                           + [item for item, _ in imported_recipes()])
                if args.json:
                    print(json.dumps([{"id": item.recipe_id, "name": item.name,
                                      "position": item.position, "height": item.height}
                                     for item in recipes], indent=2))
                else:
                    for item in recipes:
                        print(f"{item.recipe_id}: {item.name} ({item.position}, {item.height}px)")
                return 0
            if args.recipe or args.panel != "waybar":
                raise ValueError("--recipe and --panel only apply to de start")
            if args.nested:
                raise ValueError("--nested only applies to de start")
            from .de.diagnostics import inspect
            report = inspect()
            if args.json:
                print(json.dumps(report.as_dict(), indent=2))
            else:
                print(f"RiceBowl DE / labwc preflight (current session: {report.session_type})")
                for check in report.checks:
                    print(f"[{check.status.upper():8}] {check.label}: {check.detail}")
                print("Wayland preview: optional login session available; complete RiceBowl DE pending")
            return 0 if report.compositor_available else 1
        if args.command in (None, "gui"):
            from .gui import run
            return run()
        if args.command == "hub":
            from .hub import run
            return run()
        if args.command == "preview":
            from .preview import run
            return run()
        if args.command == "aero-shell":
            from .aero_shell import run
            suffix = ["--quit"] if args.quit else ["--control"] if args.control else ["--toggle-menu"] if args.toggle_menu else []
            return run(["ricehub-aero-shell", *suffix])
        if args.command == "windows10-shell":
            from .ten_shell import run
            suffix = ["--quit"] if args.quit else ["--actions"] if args.actions else ["--toggle-menu"] if args.toggle_menu else []
            return run(["ricehub-ten-shell", *suffix])
        if args.command in ("winxp-shell", "winclassic-shell", "chromeos-shell", "frutiger-shell"):
            from .aero_shell import run
            profile = args.command.removesuffix("-shell")
            if profile == "frutiger" and args.trace_path:
                from .interaction_trace import trace_path
                print(trace_path())
                return 0
            suffix = (["--trace-actions"] if profile == "frutiger" and args.trace_actions else
                      ["--trace-stop"] if profile == "frutiger" and args.trace_stop else
                      ["--quit"] if args.quit else ["--control"] if args.control else
                      ["--toggle-menu"] if args.toggle_menu else [])
            return run([f"ricehub-{profile}-shell", *suffix], profile=profile)
        if args.command in ("session-menu", "session-control"):
            from .session_shortcuts import dispatch
            dispatch("menu" if args.command == "session-menu" else "control")
            return 0
        if args.command == "session-keys-restore":
            from .session_shortcuts import restore_bindings
            for warning in restore_bindings():
                print("Shortcut warning:", warning, file=sys.stderr)
            return 0
        if args.command == "winxp-desktop":
            from .luna_desktop import desktop_path, manage

            changed, preserved = manage(args.action)
            print("XP desktop:", desktop_path())
            for name in changed:
                print(" ", "Installed" if args.action == "install" else "Removed", name)
            for name in preserved:
                print("  Preserved", name)
            if args.action == "status" and not preserved:
                print("  No XP shortcuts currently installed")
            return 0
        if args.command == "session-sync":
            from .shell_session import login_reconcile
            warnings = login_reconcile()
            for warning in warnings:
                print("Session warning:", warning, file=sys.stderr)
            return 1 if warnings else 0
        if args.command == "rice":
            from .rice import RiceError, apply as apply_rice, plan as plan_rice, restore as restore_rice
            if args.action == "restore":
                if args.style is not None:
                    raise RiceError("Restore takes no style argument")
                backup = restore_rice()
                print("Desktop restored from:", backup)
                from .rice import XfceBackend
                try:
                    theme = XfceBackend().get("xfconf", "xsettings", "/Net/ThemeName")
                    from .shell_session import sync_theme
                    for warning in sync_theme(theme):
                        print("Taskbar warning:", warning, file=sys.stderr)
                except (OSError, RuntimeError) as exc:
                    print("Taskbar warning:", exc, file=sys.stderr)
                skipped_file = backup / "skipped.json"
                if skipped_file.is_file():
                    skipped = json.loads(skipped_file.read_text(encoding="utf-8"))
                    print("Preserved newer edits (not overwritten):", ", ".join(skipped))
            elif args.style is None:
                raise RiceError("Choose night or day (example: macrice rice plan night)")
            elif args.action == "repair-assets":
                from .rice import repair_assets
                backups = repair_assets(args.style)
                print("RiceBowl asset repair complete. Original assets archived at:")
                for backup in backups:
                    print(" ", backup)
                print("Review these backups before deletion; now choose Apply rice.")
            elif args.action == "plan":
                changes, _, _, _ = plan_rice(args.style)
                number = sum(item["before"] != item["after"] for item in changes)
                print(f"{args.style.title()} Rice is available. {number} desktop settings would change.")
                print("Themes, icons, fonts and wallpaper were validated; this was read-only.")
            else:
                print("Rice applied; backup:", apply_rice(args.style))
                from .shell_session import install_login_reconciler
                try:
                    install_login_reconciler()
                except OSError as exc:
                    print("Session autostart warning:", exc, file=sys.stderr)
                from .shell_session import sync_theme
                from .rice import STYLES
                for warning in sync_theme(STYLES[args.style].gtk):
                    print("Taskbar warning:", warning, file=sys.stderr)
            return 0
        if args.command == "performance":
            from .performance import (apply_profile, desktop_session_report,
                                      measure_processes, summarize_samples)
            if args.profile in ("report", "desktop"):
                if not 1 <= args.samples <= 9:
                    raise ValueError("--samples must be between 1 and 9")
                desktop = args.profile == "desktop"
                samples = [measure_processes(include_desktop=True) if desktop else measure_processes()
                           for _ in range(args.samples)]
                result = desktop_session_report(samples) if desktop else summarize_samples(samples)
                if args.json:
                    print(json.dumps(result, indent=2))
                    return 0
                if not result["components"]:
                    print("No recognized XFCE/Wayland/RiceBowl processes found for this user." if desktop else
                          "No RiceBowl components or Plank processes found for this user.")
                for item in result["components"]:
                    pss = f"{item['pss_kib'] / 1024:.1f} MiB" if item["pss_kib"] is not None else "unavailable"
                    cpu = f"{item['cpu_percent']:.1f}%" if item["cpu_percent"] is not None else "unavailable"
                    threads = str(item["threads"]) if item["threads"] is not None else "unavailable"
                    role = f" [{item['role']}]" if desktop else ""
                    print(f"{item['name']}{role} (PID {item['pid']}): PSS {pss} · CPU {cpu} · Threads {threads}")
                if result["total_pss_kib"] is not None:
                    print(f"Sampled total PSS: {result['total_pss_kib'] / 1024:.1f} MiB"
                          + (" (partial)" if result["partial"] else ""))
                if desktop:
                    total = result["xfce_pss_kib"]
                    print("XFCE sampled PSS: " + (f"{total / 1024:.1f} MiB" if total is not None
                                                   else "unavailable"))
                    wayland = result["wayland_pss_kib"]
                    print("Wayland sampled PSS: " + (
                        f"{wayland / 1024:.1f} MiB" if wayland is not None else "unavailable"))
                    for warning in result["warnings"]:
                        print("Overlap warning:", warning)
                    print("Read-only inventory: core/shared services were not stopped.")
                    print(result["scope_note"])
            else:
                if args.json or args.samples != 3:
                    raise ValueError("--json and --samples apply only to performance report/desktop")
                print(f"Performance profile {args.profile} applied; backup:", apply_profile(args.profile))
            return 0
        if args.command == "inspect":
            print(json.dumps(detect().as_dict(), indent=2, ensure_ascii=False))
            return 0
        if args.command == "doctor":
            from .doctor import diagnose, summary
            checks = diagnose(style=args.style)
            if args.json:
                print(json.dumps({"checks": [item.as_dict() for item in checks],
                                  "summary": dict(zip(("ok", "warning", "info"), summary(checks)))},
                                 indent=2, ensure_ascii=False))
            else:
                for item in checks:
                    print(f"[{item.status.upper():7}] {item.message}")
                    if item.advice:
                        print("          " + item.advice)
                ok, warnings, optional = summary(checks)
                print(f"{ok} ready · {warnings} attention · {optional} optional")
            return 1 if any(item.status == "warning" for item in checks) else 0
        if args.command == "app-compat":
            from .app_compat import format_report, inspect_window
            report = inspect_window(window_id=args.window_id)
            print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else format_report(report))
            return 0
        if args.command == "update":
            from .updater import UpdateError, apply as apply_update, inspect as inspect_update
            if args.action == "apply":
                if not args.yes:
                    raise UpdateError("Use update check --refresh first, then update apply --yes")
                if args.revision and (len(args.revision) != 40 or any(
                        character not in "0123456789abcdefABCDEF" for character in args.revision)):
                    raise UpdateError("--revision must be a full Git commit SHA (40 hex digits)")
                plan = apply_update(source=args.source, expected_revision=args.revision,
                                    preserve_checkout=args.preserve_checkout)
                print("RiceBowl updated to " + plan.available[:12] if plan.needed else
                      "RiceBowl already up to date")
                if plan.changed:
                    print(f"Source checkout not advanced: {len(plan.changed)} local change(s) preserved in place.")
                print("Restart the manager to load the new code; your desktop rice was not switched.")
            else:
                plan = inspect_update(source=args.source, refresh=args.refresh,
                                      allow_dirty=args.preserve_checkout)
                print("Local revision: " + plan.current[:12])
                print("Installed:      " + (plan.installed[:12] if plan.installed else "unknown (legacy installation)"))
                print("Available:      " + plan.available)
                if plan.changed:
                    print(f"Local files:    {len(plan.changed)} changed; a preserve-mode install will not advance the checkout")
                print(f"New source commits: {plan.commits}" +
                      (" — run update apply --yes (optionally --revision SHA) after review" if plan.needed else
                       " — installed version current (cached; use --refresh to check GitHub)"))
            return 0
        if args.command == "status":
            print("MacRice " + __version__)
            for name, value in installed_components().items():
                print(f"  {name}: {'installed' if value else 'not installed'}")
            appearance = detect()
            print("  XFCE GTK theme:", appearance.gtk_theme or "not detected")
            print("  Icon theme:", appearance.icon_theme or "not detected")
            if appearance.plank_theme:
                print("  Plank theme:", appearance.plank_theme)
            return 0
        if args.command == "dock":
            from .plank import installed, open_dock, preferences
            if args.action == "preferences":
                print(open_dock(show_preferences=True))
            else:
                print("Plank:", "installed" if installed() else "not installed")
                print(json.dumps(preferences().__dict__, indent=2, ensure_ascii=False))
            return 0
        if args.command == "install":
            install(InstallOptions(args.dry_run, args.no_start, args.bar_autostart))
            return 0
        if args.command == "theme":
            backup = apply_preset(args.preset)
            print(f"Applied {args.preset} to MacMenu, Control Center and MacBar.")
            print("Backups:", backup)
            print("Running MacRice apps reload their theme automatically.")
            return 0
        if args.command == "open":
            open_component(args.component)
            return 0
    except (InstallationError, ValueError, OSError, RuntimeError) as exc:
        print("MacRice:", exc, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
