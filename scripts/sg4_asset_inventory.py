#!/usr/bin/env python3
"""SG4 / WP4.5 asset-rights inventory (offline, deterministic apart from first_commit).

Walks the source tree, finds every artwork/font/theme/recipe asset, hashes it and
attaches the declared licence, origin, generator and rights red flags described in
docs/sg4-asset-rights-audit.md.  The result is docs/evidence/sg4/asset-inventory.json.

    python3 scripts/sg4_asset_inventory.py            # regenerate the JSON
    python3 scripts/sg4_asset_inventory.py --check    # exit 1 if it is stale

This is audit *preparation*.  It never asserts that rights were verified; the
``rights_independently_verified`` field in macrice/de/pack.py and
macrice/de/creator_release.py stays False until the repository owner signs off.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/evidence/sg4/asset-inventory.json"
REPRODUCTION = ROOT / "docs/evidence/sg4/generator-reproduction.json"
SCHEMA = 1

ASSET_EXT = frozenset((
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".icns", ".bmp", ".tif", ".tiff",
    ".avif", ".xpm", ".xbm", ".cur", ".ttf", ".otf", ".ttc", ".woff", ".woff2", ".pcf", ".bdf",
    ".ogg", ".oga", ".wav", ".mp3", ".flac", ".webm", ".mp4"))
SKIP_DIRS = frozenset((".git", "target", "__pycache__", "node_modules", ".claude", ".venv"))
SKIP_PREFIXES = ("docs/evidence/local-ci/",)
TEXT_EXT = frozenset((".py", ".rs", ".json", ".sh", ".css", ".toml", ".md", ".in", ".desktop", ".conf"))

SELF_REFERENCES = frozenset(("scripts/sg4_asset_inventory.py", "tests/test_sg4_asset_inventory.py"))
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
REPO_LICENCE = "MIT (repo-wide LICENSE; no per-asset licence declaration)"
PROPRIETARY_FONT_NAMES = re.compile(
    r"Tahoma|Segoe|Trebuchet|Lucida|Frutiger|Roboto|Google Sans|Helvetica|San Francisco|SF Pro|"
    r"Verdana|Arial|Calibri|Consolas|Inter\b")

FLAGS = {
    "RF01": ("high", "Lookalike of a proprietary OS logo",
             "Four-pane perspective window mark / wallpaper emblem evokes the Windows 10 logo; "
             "AGENTS.md forbids copying proprietary logos.",
             "Replace the four-pane mark with an unmistakably original penguin/bowl mark, or record "
             "an explicit owner risk acceptance."),
    "RF02": ("medium", "Composition modelled on a proprietary default wallpaper",
             "Light-beam hero composition modelled on the Windows 10 default wallpaper.",
             "Owner visual comparison; redraw the beam geometry or accept the risk in writing."),
    "RF03": ("high", "Likely lookalike of a proprietary wallpaper, source undocumented",
             "Photographic green-hill / blue-sky / cloud scene evoking Windows XP 'Bliss'; no generator "
             "produces these bytes and no author, tool or prompt is recorded.",
             "Owner to confirm provenance and generation records, or replace with a clearly original scene."),
    "RF04": ("medium", "Raster artwork with undocumented origin",
             "Hand-reviewed raster not reproduced by any in-repo generator and not named in "
             "CONTRIBUTORS.md.",
             "Record author/tool, generation prompt and terms of use, or replace."),
    "RF05": ("medium", "AI-generated artwork: no per-file record",
             "CONTRIBUTORS.md says it was generated with OpenAI image tools; prompts, date, account "
             "terms and any style reference are not recorded. AI output may not carry copyright, and "
             "the 'Aero Seven' names/Frutiger-Aero look imitate Windows 7 era artwork.",
             "Archive prompts and generation records, confirm the tool terms allow MIT redistribution, "
             "and confirm no proprietary reference image was supplied."),
    "RF06": ("medium", "Third-party brand palette in a logo",
             "2x2 rounded squares in the exact Google brand colours (#4285f4 #ea4335 #fbbc04 #34a853).",
             "Recolour to a RiceBowl palette or replace the mark."),
    "RF07": ("medium", "Bundled font bytes not matched to an upstream release",
             "Internal version string is Liberation Sans 2.1.5 (OFL-1.1) but the sha256 differs from "
             "Debian fonts-liberation's file of the same version; unmodified status (OFL reserved font "
             "name 'Liberation') is therefore unverified.",
             "Compare against the upstream 2.1.5 release tarball; if modified, rename or replace."),
    "RF08": ("medium", "OFL notice not confirmed in packaged builds",
             "The font is embedded in the native binary via include_bytes!, but the Debian build "
             "scripts install no copyright/licence file for it.",
             "Ship assets/fonts/LiberationSans-LICENSE.txt in every package that embeds the font."),
    "RF09": ("low", "Tracked bytes differ from generator output",
             "The in-repo generator rebuilds this file with different bytes, so the tracked version was "
             "edited by hand or by an earlier generator revision and is not reproducible.",
             "Owner accepts hand edits as original or re-commits generator output."),
    "RF10": ("medium", "Documentation capture of OS-imitating UI",
             "Real screenshot containing flagged wallpapers/logos and third-party application UI "
             "(Thunar, GTK widgets, system fonts). Not a runtime asset.",
             "Resolve the flags on the artwork shown; confirm screenshots are acceptable to publish."),
    "RF11": ("low", "Penguin mascot resembles Tux",
             "Linux penguin artwork is declared original, but Tux (Larry Ewing) is a licensed work.",
             "Owner confirms the drawings are independent, or adds Tux attribution."),
    "RF12": ("low", "macOS-styled glyph or tile",
             "Rounded-tile Control-Center style icon in Apple's system blue (#0a84ff); filename names macOS.",
             "Owner visual comparison against Apple artwork; rename if needed."),
    "RF13": ("info", "Proprietary font names referenced",
             "CSS names proprietary families (e.g. Tahoma, Segoe UI) only as fallbacks; no such font "
             "file is shipped.",
             "None required beyond confirming no proprietary font is bundled."),
    "RF14": ("low", "Bundled recipe carries no provenance block",
             "Bundled example/default recipe has no author, licence or origin field; it references "
             "wallpapers and the bundled font by name.",
             "Attach provenance when the recipe is published as a RicePack."),
}

# (rice id used in docs, theme dirs) ------------------------------------------------------------
THEME_RICE = {
    "RiceHub-Aero": "aero", "RiceHub-Chrome": "chromeos", "RiceHub-Chrome-Icons": "chromeos",
    "RiceHub-Classic": "winclassic", "RiceHub-Classic-Icons": "winclassic",
    "RiceHub-Frutiger": "frutiger", "RiceHub-Frutiger-Icons": "frutiger",
    "RiceHub-Luna": "winxp", "RiceHub-Luna-Icons": "winxp",
    "RiceHub-Ten-Dark": "windows10", "RiceHub-Ten-Light": "windows10",
    "RiceHub-Ten-Penguin": "windows10",
}
STATUS_RICE = {"winxp": "winxp", "windows10": "windows10", "winclassic": "winclassic",
               "frutiger": "frutiger", "chromeos": "chromeos", "aero": "aero"}
WALLPAPER_RICE = {
    "aero-seven-blue": "aero", "aero-seven-night": "aero", "aurora-day": "macos-aurora",
    "aurora-night": "macos-aurora", "chrome-pastel": "chromeos", "classic-teal": "winclassic",
    "frutiger-future": "frutiger", "luna-hills": "winxp", "ten-blue": "windows10",
    "ten-midnight": "windows10",
}
AI_WALLPAPERS = frozenset(("aurora-day", "aurora-night", "aero-seven-blue", "aero-seven-night"))
UNDOCUMENTED_WALLPAPERS = frozenset(("luna-hills", "frutiger-future"))
PENGUIN_SVGS = frozenset((
    "assets/aero-penguin.svg", "assets/ten-start.svg", "assets/macrice-symbolic.svg",
    "assets/ricebowl-classic-start.svg", "assets/ricebowl-xp-user.svg",
    "assets/windows10-bloom.svg", "components/macmenu/assets/macmenu-penguin.svg",
    "components/macmenu/assets/macmenu-penguin-ink.svg", "components/macmenu/assets/macmenu-app.svg"))

GENERATOR_FOR_DIR = (  # (path prefix, generator) - documentation of the intended owner script
    ("assets/themes/RiceHub-Aero/", "scripts/build_aero_assets.py"),
    ("assets/icons/RiceHub-Aero/", "scripts/build_aero_assets.py"),
    ("assets/themes/RiceHub-Chrome/", "scripts/build_chrome_assets.py"),
    ("assets/themes/RiceHub-Ten-", "scripts/build_ten_assets.py"),
    ("assets/icons/RiceHub-Ten-Penguin/", "scripts/build_ten_assets.py"),
    ("assets/themes/RiceHub-", "scripts/build_heritage_assets.py"),
    ("assets/icons/RiceHub-", "scripts/build_heritage_assets.py"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_asset(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    suffix = os.path.splitext(name)[1].lower()
    if suffix in ASSET_EXT:
        return True
    if rel.startswith("assets/") and (name in ("themerc", "gtk.css") or suffix == ".theme"):
        return True
    return rel in ("macrice/de/resources/waybar/style.css", "assets/fonts/LiberationSans-LICENSE.txt") or (
        rel.startswith(("examples/wayland/", "macrice/de/resources/recipes/")) and suffix == ".json")


def discover(root: Path = ROOT) -> list[str]:
    """Every shipped/referenced asset path (POSIX, repo-relative), sorted. Needs no VCS metadata."""
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_base = Path(base).relative_to(root).as_posix()
        for name in sorted(files):
            rel = name if rel_base == "." else f"{rel_base}/{name}"
            if any(rel.startswith(prefix) for prefix in SKIP_PREFIXES):
                continue
            if _is_asset(rel):
                found.append(rel)
    return sorted(found)


def _text_index(root: Path, assets: set[str]) -> dict[str, set[str]]:
    """basename -> files that mention it (static references only; dynamic f-string names are not seen)."""
    pattern = re.compile(r"[A-Za-z0-9_.+-]+\.(?:png|svg|jpg|jpeg|webp|ttf|theme)\b")
    stems = {rel.rsplit("/", 1)[-1] for rel in assets}
    index: dict[str, set[str]] = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_base = Path(base).relative_to(root).as_posix()
        for name in files:
            if os.path.splitext(name)[1] not in TEXT_EXT:
                continue
            rel = name if rel_base == "." else f"{rel_base}/{name}"
            if (rel in assets or rel.startswith(SKIP_PREFIXES) or rel.startswith("docs/evidence/")
                    or rel in SELF_REFERENCES):
                continue
            try:
                text = (Path(base) / name).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for hit in {m.group(0) for m in pattern.finditer(text)}:
                if hit in stems:
                    index.setdefault(hit, set()).add(rel)
            # Wallpapers are also referenced by stem in recipes ("wallpaper": "luna-hills").
            for stem in WALLPAPER_RICE:
                if stem in text:
                    index.setdefault(stem + ".jpg", set()).add(rel)
    return index


def _reproduction() -> dict[str, dict]:
    try:
        return json.loads(REPRODUCTION.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        return {}


def _first_commits(root: Path) -> dict[str, str]:
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--name-only", "--format=%x00%h %ad", "--date=short"],
            cwd=root, capture_output=True, text=True, check=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    first: dict[str, str] = {}
    for block in out.split("\x00")[1:]:  # newest first; later (older) entries overwrite
        header, _, names = block.partition("\n")
        for name in names.split("\n"):
            if name.strip():
                first[name.strip()] = header.strip()
    return first


def classify(rel: str, root: Path, repro: dict[str, dict]) -> dict:
    """Return category, licence, origin, rices, generator and flag ids for one asset."""
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")
    info = {"category": "uncategorised", "declared_licence": REPO_LICENCE,
            "origin": "unknown (uncategorised path; classify in scripts/sg4_asset_inventory.py)",
            "rices": [], "flags": []}
    flags: list[str] = info["flags"]
    own = "original project asset (CONTRIBUTORS.md / RICEHUB.md state RiceBowl bundles no Microsoft or Apple artwork)"

    if rel == "assets/fonts/LiberationSans-Regular.ttf":
        info.update(category="font", declared_licence="OFL-1.1 (assets/fonts/LiberationSans-LICENSE.txt)",
                    origin="third-party: Liberation Sans 2.1.5, (c) Google/Red Hat; embedded in riceplate-wayland via include_bytes!",
                    rices=["all native-Wayland rices (builtin font)"])
        flags += ["RF07", "RF08"]
    elif rel == "assets/fonts/LiberationSans-LICENSE.txt":
        info.update(category="font-licence", declared_licence="OFL-1.1 text (Debian copyright format)",
                    origin="third-party licence text for Liberation Sans")
    elif parts[:2] == ["assets", "wallpapers"]:
        stem = name.rsplit(".", 1)[0]
        info.update(category="wallpaper", rices=[WALLPAPER_RICE.get(stem, "unknown")])
        if stem in AI_WALLPAPERS:
            info["origin"] = "ai-generated: OpenAI image tools (per CONTRIBUTORS.md); no prompt record"
            flags.append("RF05")
        elif stem in UNDOCUMENTED_WALLPAPERS:
            info["origin"] = "unknown raster: hand-reviewed file, not reproduced by any generator; not named in CONTRIBUTORS.md"
            flags.append("RF04")
            if stem == "luna-hills":
                flags.append("RF03")
        elif stem in ("ten-blue", "ten-midnight"):
            info["origin"] = "generated in-repo (Pillow; four-pane light motif plus penguin)"
            flags.append("RF01")
            flags.append("RF02")
        else:
            info["origin"] = "generated in-repo (Pillow; flat/gradient)"
    elif parts[:2] == ["assets", "hub-previews"]:
        info.update(category="preview-image", rices=[name.rsplit(".", 1)[0]],
                    origin="derived: scripts/refresh_hub_previews.sh downscales screenshots/current/<rice>-start.webp")
        flags.append("RF10")
    elif parts[:2] == ["assets", "themes"]:
        theme = parts[2]
        kind = ("window-chrome" if "xfwm4" in parts and name.endswith(".png")
                else "gtk-theme" if name == "gtk.css" else "theme-config")
        info.update(category=kind, rices=[THEME_RICE.get(theme, theme)], origin=own)
        if name == "gtk.css" and PROPRIETARY_FONT_NAMES.search((root / rel).read_text(encoding="utf-8", errors="ignore")):
            flags.append("RF13")
    elif parts[:2] == ["assets", "icons"]:
        theme = parts[2]
        info.update(category="icon" if name.endswith(".svg") else "icon-theme-config",
                    rices=[THEME_RICE.get(theme, theme)], origin=own)
    elif parts[:2] == ["assets", "status"]:
        info.update(category="status-icon", rices=[STATUS_RICE.get(parts[2], parts[2])], origin=own)
    elif parts[:2] == ["assets", "plank-themes"]:
        info.update(category="dock-theme", rices=["macOS (MacRice)" if "MacRice" in parts[2] else "aero/windows10"],
                    origin="original key-file values in Plank theme format (Plank itself is GPL-3.0 and not vendored)")
    elif len(parts) == 2 and parts[0] == "assets" and name.endswith(".svg"):
        info.update(category="logo-or-mark", origin=own)
        info["rices"] = [{"ten-start.svg": "windows10", "windows10-bloom.svg": "windows10",
                          "aero-penguin.svg": "aero", "ricebowl-xp-start.svg": "winxp",
                          "ricebowl-xp-user.svg": "winxp", "ricebowl-classic-start.svg": "winclassic",
                          "ricebowl-chrome-start.svg": "chromeos",
                          "ricebowl-frutiger-start.svg": "frutiger"}.get(name, "all (RiceBowl/MacRice mark)")]
        if rel == "assets/ten-start.svg":
            flags.append("RF01")
        if rel == "assets/windows10-bloom.svg":
            flags.append("RF02")
        if rel == "assets/ricebowl-chrome-start.svg":
            flags.append("RF06")
    elif parts[0] == "components" and "assets" in parts:
        info.update(category="component-icon", rices=["macOS (MacRice)"], origin=own)
        if name == "macos-control-center.svg":
            flags.append("RF12")
    elif rel.startswith(("screenshots/", "components/")) and "screenshots" in parts:
        info.update(category="documentation-capture",
                    origin="captured: real GTK/X11 or labwc+RicePlate screenshot of the running desktop")
        flags.append("RF10")
    elif rel == "macrice/de/resources/waybar/style.css":
        info.update(category="theme-config", rices=["legacy waybar session"], origin=own)
    elif rel.startswith(("examples/wayland/", "macrice/de/resources/recipes/")):
        info.update(category="recipe-pack", origin="original project-authored recipe JSON")
        flags.append("RF14")
        text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        info["rices"] = sorted({r for w, r in WALLPAPER_RICE.items() if f'"{w}"' in text}) or ["all"]

    if rel in PENGUIN_SVGS:
        flags.append("RF11")

    generated_by = None
    for prefix, script in GENERATOR_FOR_DIR:
        if rel.startswith(prefix) and info["category"] in ("window-chrome", "gtk-theme", "theme-config", "icon", "icon-theme-config"):
            generated_by = script
            break
    if rel.startswith("assets/icons/RiceHub-Luna-Icons/scalable/apps/ricehub-luna-"):
        generated_by = "scripts/build_luna_control_icons.py"
    if rel == "assets/wallpapers/chrome-pastel.jpg":
        generated_by = "scripts/build_chrome_assets.py"
    if rel in ("assets/wallpapers/ten-blue.jpg", "assets/wallpapers/ten-midnight.jpg"):
        generated_by = "scripts/build_ten_assets.py"
    if rel == "assets/wallpapers/classic-teal.jpg":
        generated_by = "scripts/build_heritage_assets.py"
    entry = repro.get(rel)
    reproduces = None
    if entry:
        generated_by = " + ".join(entry["scripts"])
        reproduces = bool(entry["reproduces_tracked_bytes"])
        if not reproduces:
            flags.append("RF09")
    elif generated_by and info["category"] in ("icon", "window-chrome", "gtk-theme", "theme-config", "icon-theme-config"):
        # intended owner script exists but the file was not written by any run: hand-curated/protected
        generated_by = None
    info["generated_by"] = generated_by
    info["generator_reproduces_tracked_bytes"] = reproduces
    info["flags"] = sorted(set(flags), key=lambda f: (SEVERITY_ORDER[FLAGS[f][0]], f))
    return info


def build(root: Path = ROOT, *, with_git: bool = True) -> dict:
    paths = discover(root)
    repro = _reproduction()
    index = _text_index(root, set(paths))
    first = _first_commits(root) if with_git else {}
    assets = []
    for rel in paths:
        path = root / rel
        info = classify(rel, root, repro)
        users = sorted(index.get(rel.rsplit("/", 1)[-1], ()))[:12]
        assets.append({
            "path": rel, "sha256": sha256_file(path), "size": path.stat().st_size,
            "category": info["category"], "rices": info["rices"], "users": users,
            "declared_licence": info["declared_licence"], "origin": info["origin"],
            "generated_by": info["generated_by"],
            "generator_reproduces_tracked_bytes": info["generator_reproduces_tracked_bytes"],
            "flags": info["flags"], "first_commit": first.get(rel),
        })
    by_cat: dict[str, int] = {}
    by_flag: dict[str, int] = {}
    for item in assets:
        by_cat[item["category"]] = by_cat.get(item["category"], 0) + 1
        for flag in item["flags"]:
            by_flag[flag] = by_flag.get(flag, 0) + 1
    return {
        "schema": SCHEMA,
        "purpose": "WP4.5 rights-audit inventory prepared for owner sign-off; not a rights verification.",
        "audit_status": "prepared-awaiting-owner-signoff",
        "generator": "scripts/sg4_asset_inventory.py",
        "counts": {"total": len(assets), "by_category": dict(sorted(by_cat.items())),
                   "by_flag": dict(sorted(by_flag.items())),
                   "flagged_files": sum(1 for a in assets if a["flags"])},
        "flag_catalogue": {k: {"severity": v[0], "title": v[1], "detail": v[2], "recommended_action": v[3]}
                           for k, v in FLAGS.items()},
        "external_references": EXTERNAL_REFERENCES,
        "assets": assets,
    }


EXTERNAL_REFERENCES = [
    {"name": "font8x8 0.3.1 (crates.io)", "kind": "bitmap font data compiled into riceplate-native",
     "licence": "MIT (crate); glyph data credited as IBM VGA public domain",
     "source": "components/riceplate-wayland/Cargo.toml, src/text_render.rs", "shipped_as_file": False,
     "note": "Not vendored; fetched by Cargo. Owner confirms the public-domain glyph credit."},
    {"name": "fontdue 0.9.4, rustybuzz 0.20.1 (crates.io)", "kind": "text rasteriser/shaper (code only)",
     "licence": "MIT OR Apache-2.0 OR Zlib / MIT", "source": "components/riceplate-wayland/Cargo.toml",
     "shipped_as_file": False, "note": "Code dependencies; no font data."},
    {"name": "DejaVu Sans / Sans Mono, WenQuanYi Micro Hei, Lohit Devanagari", "kind": "system fonts read at runtime",
     "licence": "distribution-provided (Bitstream Vera/DejaVu, Apache-2.0/GPLv3, OFL-1.1)",
     "source": "components/riceplate-wayland/src/style_art.rs, native_shaping.rs",
     "shipped_as_file": False, "note": "Loaded from /usr/share/fonts only when present; not redistributed."},
    {"name": "status-notifier 0.1.1 (vendored patch)", "kind": "code only",
     "licence": "MIT", "source": "components/riceplate-wayland/vendor/status-notifier/",
     "shipped_as_file": True, "note": "No artwork."},
    {"name": "Plank dock", "kind": "external program (not vendored)", "licence": "GPL-3.0",
     "source": "components/plank/README.md", "shipped_as_file": False,
     "note": "assets/plank-themes only hold key-file values."},
]


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed JSON is stale")
    parser.add_argument("--output", type=Path, default=INVENTORY)
    args = parser.parse_args(argv)
    data = build()
    if args.check:
        try:
            current = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("inventory missing or unreadable", file=sys.stderr)
            return 1
        strip = lambda d: [{k: v for k, v in a.items() if k not in ("first_commit", "users")}
                           for a in d["assets"]]
        if strip(current) != strip(data):
            print("asset inventory is stale; run scripts/sg4_asset_inventory.py", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(data), encoding="utf-8")
    print(f"wrote {args.output.relative_to(ROOT)}: {data['counts']['total']} assets, "
          f"{data['counts']['flagged_files']} flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
