#!/usr/bin/env python3
"""Build original, reproducible GTK/XFWM, icon and wallpaper artwork.

Development-only dependency: Pillow. No downloaded OS textures or logos.
The generated assets are checked into the source distribution.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from build_ten_assets import ART, chrome, gtk
from ricebowl_artwork import write_generated_icon


ROOT = Path(__file__).resolve().parents[1]
W, H = 1920, 1080

PALETTES = {
    "Luna": {"background": "#e9f2ff", "surface": "#d1e6fd", "field": "#ffffff",
             "ink": "#123c79", "muted": "#5075a3", "edge": "#85a8da", "accent": "#2265cf",
             "inactive": (125, 161, 205), "active": (32, 94, 203)},
    "Classic": {"background": "#c0c0c0", "surface": "#c0c0c0", "field": "#ffffff",
                "ink": "#101010", "muted": "#4c4c4c", "edge": "#777777", "accent": "#000080",
                "inactive": (128, 128, 128), "active": (0, 0, 128)},
    "Chrome": {"background": "#f5f8fe", "surface": "#e9effb", "field": "#ffffff",
               "ink": "#293b57", "muted": "#5e759a", "edge": "#bfcfe4", "accent": "#4a7ed4",
               "inactive": (197, 209, 230), "active": (225, 236, 249)},
    "Frutiger": {"background": "#e5fff8", "surface": "#c0f3ee", "field": "#f9fffe",
                 "ink": "#0b4a68", "muted": "#32859b", "edge": "#7ec8cf", "accent": "#16aabf",
                 "inactive": (82, 179, 200), "active": (32, 161, 193)},
}


def _luna_chrome(destination: Path) -> None:
    """Original XP-inspired molded XFWM4 art; never embed Microsoft bitmaps."""
    frame = destination / "xfwm4"
    (frame / "themerc").write_text(
        "active_text_color=#ffffff\ninactive_text_color=#eff4ff\n"
        "button_offset=2\nbutton_spacing=1\nfull_width_title=true\n"
        "frame_border_top=0\nmaximized_offset=0\nshow_app_icon=true\n"
        "title_horizontal_offset=6\ntitle_vertical_offset_active=1\n"
        "title_vertical_offset_inactive=1\ntitle_shadow_active=true\n"
        "title_shadow_inactive=false\n",
        encoding="utf-8",
    )

    def gradient(width, height, upper, lower):
        image = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            t = y / max(1, height - 1)
            color = tuple(round(a * (1-t) + b*t) for a, b in zip(upper, lower)) + (255,)
            draw.line((0, y, width, y), fill=color)
        return image

    for state, upper, lower in (
        ("active", (74, 143, 239), (15, 65, 165)),
        ("inactive", (144, 181, 228), (93, 129, 191)),
    ):
        for number in range(1, 6):
            image = gradient(15, 32, upper, lower)
            draw = ImageDraw.Draw(image)
            draw.line((0, 0, 15, 0), fill=(163, 208, 255, 255), width=1)
            draw.line((0, 2, 15, 2), fill=(109, 169, 245, 150), width=1)
            image.save(frame / f"title-{number}-{state}.png")
        for side in ("top-left", "top-right"):
            image = gradient(6, 32, upper, lower)
            draw = ImageDraw.Draw(image)
            x = 0 if side == "top-left" else 5
            draw.line((x, 4, x, 31), fill=(4, 43, 135, 255), width=1)
            # Three transparent pixels evoke Luna's softly rounded top corners.
            px = image.load()
            for dy, n in ((0, 3), (1, 2), (2, 1)):
                for dx in range(n):
                    px[dx if side == "top-left" else 5-dx, dy] = (0, 0, 0, 0)
            image.save(frame / f"{side}-{state}.png")
        for side in ("left", "right"):
            image = Image.new("RGBA", (4, 8), (39, 97, 192, 255) if state == "active" else
                              (103, 139, 190, 255))
            draw = ImageDraw.Draw(image)
            draw.line((0 if side == "left" else 3, 0, 0 if side == "left" else 3, 8),
                      fill=(23, 66, 154, 255), width=1)
            image.save(frame / f"{side}-{state}.png")
        for part in ("bottom", "bottom-left", "bottom-right"):
            image = gradient(6, 5, lower, (8, 49, 144) if state == "active" else (74, 113, 178))
            image.save(frame / f"{part}-{state}.png")

    for button in ("close", "maximize", "hide", "menu", "shade", "stick"):
        for state in ("active", "inactive", "prelight", "pressed"):
            image = Image.new("RGBA", (27, 27), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            if button == "close":
                upper, lower = ((252, 137, 100), (182, 40, 25))
                if state == "prelight": upper, lower = ((255, 178, 137), (223, 56, 40))
            else:
                upper, lower = ((113, 170, 246), (25, 87, 190))
                if state == "prelight": upper, lower = ((158, 207, 255), (43, 120, 221))
            if state == "inactive":
                upper, lower = ((192, 207, 232), (122, 149, 199))
            if state == "pressed":
                upper, lower = lower, upper
            draw.rounded_rectangle((3, 3, 25, 24), radius=5, fill=lower,
                                   outline=(245, 250, 255, 230), width=1)
            for y in range(5, 15):
                t = (y-5)/10
                color = tuple(round(a*(1-t)+b*t) for a,b in zip(upper,lower))+(255,)
                draw.line((5,y,23,y), fill=color)
            symbol = (255, 255, 255, 255)
            if button == "close":
                draw.line((10, 10, 18, 18), fill=symbol, width=2)
                draw.line((18, 10, 10, 18), fill=symbol, width=2)
            elif button == "maximize":
                draw.rectangle((10, 10, 19, 18), outline=symbol, width=2)
                draw.line((10, 10, 19, 10), fill=symbol, width=2)
            elif button == "hide":
                draw.line((9, 18, 19, 18), fill=symbol, width=2)
            elif button == "menu":
                draw.rectangle((10, 10, 18, 18), outline=symbol, width=1)
            elif button == "shade":
                draw.polygon([(10, 15), (19, 15), (14, 10)], fill=symbol)
            else:
                draw.ellipse((12, 11, 17, 17), fill=symbol)
            image.save(frame / f"{button}-{state}.png")


def _luna_gtk(destination: Path) -> None:
    """Layer tactile Luna Blue GTK3 widgets over the base theme, including Thunar."""
    target = destination / "gtk-3.0/gtk.css"
    base = target.read_text(encoding="utf-8")
    if "/* Original RiceBowl Luna GTK3/Thunar chrome." in base:
        return
    target.write_text(base + """
/* Original RiceBowl Luna GTK3/Thunar chrome. Keep Linux widget semantics. */
window, dialog, .background, viewport { background-color: #ece9d8; color: #151515; }
button { background-image: linear-gradient(#ffffff, #e4ecf9 65%, #c4d6ed);
  border: 1px solid #7f9db9; border-radius: 3px; box-shadow: inset 0 1px #fff;
  color: #171717; padding: 4px 9px; }
button:hover { background-image: linear-gradient(#fff, #f5f8e5 60%, #f4d58d);
  border-color: #d59e37; }
button:active, button:checked { background-image: linear-gradient(#b9d5f5, #dceafc);
  color: #15387d; border-color: #316ac5; }
entry, spinbutton, combobox box.linked { background: #fff; color: #111;
  border: 1px solid #7f9db9; border-radius: 1px; padding: 3px; }
entry:focus { border-color: #316ac5; }
selection, :selected, row:selected, treeview.view:selected { background: #316ac5; color: #fff; }
menubar, menu, popover, .menu, .popup { background: #fff; color: #111;
  border: 1px solid #a1a1a1; }
menuitem:hover, modelbutton:hover { background: #316ac5; color: #fff; }
headerbar, .titlebar { background-image: linear-gradient(#5798ed, #1453b6);
  color: #fff; border: 1px solid #2154a0; box-shadow: inset 0 1px #91c6ff; }
toolbar { background-image: linear-gradient(#ffffff, #f3f1e6);
  color: #222; border-bottom: 1px solid #c6c4b4; }
toolbar button { border-color: transparent; background: transparent; box-shadow: none; }
toolbar button:hover { background: #fff5d9; border-color: #e3ad54; }
notebook header { background: #ece9d8; border-color: #a7bce1; }
notebook tab { background-image: linear-gradient(#e9eef9, #d2e2f6);
  border: 1px solid #94afd6; border-radius: 4px 4px 0 0; padding: 4px 12px; }
notebook tab:checked { background: #fff; color: #1b3c71; border-bottom: 1px solid #fff; }
scrollbar slider { background-image: linear-gradient(#e9f3ff, #8cb6ed);
  border: 1px solid #608fc5; border-radius: 2px; min-width: 11px; min-height: 11px; }
scrollbar trough { background: #e3edfa; }
progressbar progress, scale highlight { background-image: linear-gradient(#a6df71, #4da735);
  border: 1px solid #478b25; border-radius: 1px; }
tooltip { background: #fffcd9; color: #141414; border: 1px solid #8f8b7d; }
/* Thunar's real navigation/sidebar remains functional; style visible widgets. */
thunar toolbar, .thunar toolbar { background-image: linear-gradient(#fff, #e9e9db); }
thunar treeview.view, .thunar treeview.view { background: #fff; color: #242424; }
thunar treeview.view:selected, .thunar treeview.view:selected { background: #316ac5; color: #fff; }
thunar paned separator, .thunar paned separator { background: #acbed8; }
""", encoding="utf-8")


def _luna_fidelity_gtk(destination: Path) -> None:
    """Finish the Linux-owned Luna GTK controls; safely rerunnable."""
    target = destination / "gtk-3.0/gtk.css"
    existing = target.read_text(encoding="utf-8")
    marker = "/* RiceBowl Luna controls fidelity v2. */"
    if marker in existing:
        return
    target.write_text(existing + """
/* RiceBowl Luna controls fidelity v2. */
/* Use square early-2000s controls, consistent hover/focus and no Windows art. */
window, dialog, .background, viewport { background-color: #ece9d8; color: #1b1b1b; }
frame > border { border: 1px solid #a9a89b; border-radius: 1px; }
frame > label { color: #1e4b91; font-weight: bold; padding: 0 4px; }
button:focus { outline: 1px dotted #2c4b7e; outline-offset: -5px; }
button:disabled { background-image: linear-gradient(#f7f5ed, #deded4);
  color: #88877e; border-color: #b9b7ac; box-shadow: none; opacity: 1; }
checkbutton, radiobutton { color: #1a1a1a; padding: 3px 2px; }
checkbutton check, radiobutton radio { background-image: linear-gradient(#fff, #eaf1fa);
  border: 1px solid #7d9cbc; color: #124d91; min-width: 13px; min-height: 13px;
  border-radius: 1px; box-shadow: inset 0 1px #fff; }
radiobutton radio { border-radius: 9px; }
checkbutton:hover check, radiobutton:hover radio,
checkbutton:focus check, radiobutton:focus radio { border-color: #e4a143;
  background-image: linear-gradient(#fff, #fff4d5); }
checkbutton:disabled, radiobutton:disabled { color: #888; }
scale trough { background: #f9fafb; border: 1px solid #8a9eb7;
  border-radius: 2px; min-height: 7px; }
scale slider { background-image: linear-gradient(#fff, #c3d9f5);
  border: 1px solid #4979b6; border-radius: 3px; min-width: 13px; min-height: 16px; }
scale slider:hover { border-color: #dd9e3f;
  background-image: linear-gradient(#fffef2, #ecd49d); }
notebook > header > tabs > tab:focus { outline: 1px dotted #244f8b;
  outline-offset: -3px; }
menu { border-radius: 0; box-shadow: 2px 3px 4px rgba(35,43,56,.22); }
menuitem { padding: 3px 9px; min-height: 21px; }
menuitem:disabled { color: #858585; }
menuitem:focus { outline: 1px dotted #fff; outline-offset: -3px; }
separator { background: #b4b8c0; min-height: 1px; min-width: 1px; }
scrollbar slider { background-image: linear-gradient(#eaf5ff, #9dbfe5);
  border: 1px solid #6e98c6; border-radius: 1px; }
scrollbar slider:hover { background-image: linear-gradient(#fff5d9, #e8bf72);
  border-color: #b78433; }
treeview.view:focus { outline-color: #316ac5; }
tooltip { background: #fffbd0; border: 1px solid #7e796d; border-radius: 0;
  color: #181818; box-shadow: 1px 2px 3px rgba(0,0,0,.18); }
""", encoding="utf-8")


def _classic_chrome(destination: Path) -> None:
    """Draw authentic square 9x-era XFWM furniture from original pixels."""
    frame = destination / "xfwm4"
    (frame / "themerc").write_text(
        "active_text_color=#ffffff\ninactive_text_color=#444444\n"
        "button_offset=2\nbutton_spacing=2\nfull_width_title=true\n"
        "frame_border_top=0\nmaximized_offset=0\nshow_app_icon=true\n"
        "title_horizontal_offset=5\ntitle_vertical_offset_active=1\n"
        "title_vertical_offset_inactive=1\ntitle_shadow_active=false\n"
        "title_shadow_inactive=false\n", encoding="utf-8",
    )
    silver = (192, 192, 192, 255)
    white = (255, 255, 255, 255)
    dark = (64, 64, 64, 255)
    shadow = (128, 128, 128, 255)

    for state, color in (("active", (0, 0, 128, 255)),
                         ("inactive", (128, 128, 128, 255))):
        for number in range(1, 6):
            image = Image.new("RGBA", (12, 27), color)
            draw = ImageDraw.Draw(image)
            draw.line((0, 0, 11, 0), fill=white if state == "active" else silver)
            draw.line((0, 26, 11, 26), fill=dark)
            image.save(frame / f"title-{number}-{state}.png")
        for name in ("top-left", "top-right"):
            image = Image.new("RGBA", (5, 27), color)
            draw = ImageDraw.Draw(image)
            edge = 0 if name == "top-left" else 4
            draw.line((edge, 0, edge, 26), fill=white if name == "top-left" else dark)
            draw.line((0, 0, 4, 0), fill=white)
            image.save(frame / f"{name}-{state}.png")
        for name in ("left", "right"):
            image = Image.new("RGBA", (4, 7), silver)
            draw = ImageDraw.Draw(image)
            edge = 0 if name == "left" else 3
            draw.line((edge, 0, edge, 6), fill=white if name == "left" else dark)
            image.save(frame / f"{name}-{state}.png")
        for name in ("bottom", "bottom-left", "bottom-right"):
            image = Image.new("RGBA", (5, 4), silver)
            draw = ImageDraw.Draw(image)
            draw.line((0, 3, 4, 3), fill=dark)
            if name == "bottom-left":
                draw.line((0, 0, 0, 3), fill=white)
            elif name == "bottom-right":
                draw.line((4, 0, 4, 3), fill=dark)
            image.save(frame / f"{name}-{state}.png")

    for name in ("close", "maximize", "hide", "menu", "shade", "stick"):
        for state in ("active", "inactive", "prelight", "pressed"):
            image = Image.new("RGBA", (22, 22), silver)
            draw = ImageDraw.Draw(image)
            pressed = state == "pressed"
            draw.rectangle((0, 0, 21, 21), outline=dark if pressed else white)
            draw.line((1, 1, 20, 1), fill=shadow if pressed else white)
            draw.line((1, 1, 1, 20), fill=shadow if pressed else white)
            draw.line((1, 20, 20, 20), fill=white if pressed else shadow)
            draw.line((20, 1, 20, 20), fill=white if pressed else shadow)
            draw.line((1, 21, 21, 21), fill=white if pressed else dark)
            draw.line((21, 1, 21, 21), fill=white if pressed else dark)
            ink = (50, 50, 50, 255) if state == "inactive" else (0, 0, 0, 255)
            dx = dy = 1 if pressed else 0
            if name == "close":
                draw.line((7+dx, 7+dy, 14+dx, 14+dy), fill=ink, width=2)
                draw.line((14+dx, 7+dy, 7+dx, 14+dy), fill=ink, width=2)
            elif name == "maximize":
                draw.rectangle((6+dx, 6+dy, 15+dx, 15+dy), outline=ink, width=1)
                draw.line((7+dx, 7+dy, 14+dx, 7+dy), fill=ink, width=2)
            elif name == "hide":
                draw.line((6+dx, 15+dy, 15+dx, 15+dy), fill=ink, width=2)
            elif name == "menu":
                draw.rectangle((6+dx, 6+dy, 15+dx, 15+dy), outline=ink)
                draw.line((7+dx, 8+dy, 14+dx, 8+dy), fill=ink)
            elif name == "shade":
                draw.polygon([(6+dx, 13+dy), (15+dx, 13+dy), (10+dx, 8+dy)], fill=ink)
            else:
                draw.ellipse((8+dx, 8+dy, 13+dx, 13+dy), fill=ink)
            image.save(frame / f"{name}-{state}.png")


def _classic_gtk(destination: Path) -> None:
    """Extend genuine GTK/Thunar widgets with no glass, radius or gradient."""
    target = destination / "gtk-3.0/gtk.css"
    original = target.read_text(encoding="utf-8")
    marker = "/* RiceBowl Windows 98 Classic fidelity layer. */"
    if marker in original:
        original = original.split(marker, 1)[0].rstrip() + "\n"
    target.write_text(original + """
/* RiceBowl Windows 98 Classic fidelity layer. */
window, dialog, .background, viewport { background-color: #c0c0c0; color: #000; }
button, .button { background: #c0c0c0; color: #000; border-radius: 0;
  border-style: solid; border-width: 2px; border-top-color: #fff;
  border-left-color: #fff; border-bottom-color: #404040;
  border-right-color: #404040; padding: 3px 8px; box-shadow: none; }
button:hover { background: #d0d0d0; color: #000; }
button:active, button:checked { background: #c0c0c0; color: #000;
  border-top-color: #404040; border-left-color: #404040;
  border-bottom-color: #fff; border-right-color: #fff; }
button:focus { outline: 1px dotted #000; outline-offset: -5px; }
button:disabled { color: #808080; text-shadow: 1px 1px #fff; }
entry, spinbutton, textview, combobox box.linked { background: #fff; color: #000;
  border-style: solid; border-width: 2px; border-top-color: #808080;
  border-left-color: #808080; border-bottom-color: #fff;
  border-right-color: #fff; border-radius: 0; padding: 3px; }
entry:focus { border-top-color: #000080; border-left-color: #000080; }
selection, :selected, row:selected, treeview.view:selected { background: #000080; color: #fff; }
headerbar, .titlebar { background: #000080; color: #fff;
  border-radius: 0; border: 2px solid #c0c0c0; box-shadow: none; }
headerbar:backdrop, .titlebar:backdrop { background: #808080; color: #ddd; }
headerbar button { padding: 1px 4px; border-radius: 0; }
toolbar, menubar { background: #c0c0c0; color: #000;
  border-top: 1px solid #fff; border-bottom: 1px solid #808080; }
menu, popover, .menu, .popup { background: #c0c0c0; color: #000;
  border: 2px solid #808080; border-top-color: #fff;
  border-left-color: #fff; border-radius: 0; box-shadow: none; }
menuitem { padding: 2px 7px; min-height: 18px; }
menuitem:hover, modelbutton:hover { background: #000080; color: #fff; }
notebook header { background: #c0c0c0; border: 0; }
notebook tab { padding: 3px 9px; border-radius: 0; background: #c0c0c0;
  border: 2px solid #808080; border-top-color: #fff; border-left-color: #fff; }
notebook tab:checked { background: #d8d8d8; border-bottom-color: #d8d8d8; }
scrollbar trough { background: #c0c0c0; border: 1px solid #808080; border-radius: 0; }
scrollbar slider { background: #c0c0c0; border: 2px solid #808080;
  border-top-color: #fff; border-left-color: #fff;
  border-radius: 0; min-width: 12px; min-height: 12px; }
scrollbar slider:hover { background: #d1d1d1; }
scale trough, progressbar trough { background: #fff; border: 2px inset #808080; border-radius: 0; }
scale highlight, progressbar progress, switch:checked { background: #000080; border-radius: 0; }
tooltip { background: #ffffe1; color: #000; border: 1px solid #000; border-radius: 0; }
window.thunar toolbar, window.thunar menubar, window.thunar .location-bar {
  background: #c0c0c0; border-top: 2px solid #fff; border-bottom: 2px solid #808080; }
window.thunar .path-bar button, window.thunar toolbar button { padding: 2px 5px;
  border: 2px outset #fff; border-radius: 0; background: #c0c0c0; }
window.thunar .sidebar, window.thunar .shortcuts-pane { background: #c0c0c0;
  color: #000; border: 2px inset #fff; }
window.thunar treeview.view, window.thunar .standard-view { background: #fff;
  color: #000; border: 2px inset #fff; }
window.thunar treeview.view:selected, window.thunar .sidebar .view:selected {
  background: #000080; color: #fff; }
window.thunar statusbar { background: #c0c0c0; border-top: 2px outset #fff; }
""", encoding="utf-8")


def _classic_wallpaper() -> None:
    """Win98's familiar plain teal desktop, entirely original pixel artwork."""
    destination = ROOT / "assets/wallpapers/classic-teal.jpg"
    Image.new("RGB", (W, H), (0, 128, 128)).save(
        destination, "JPEG", quality=98, subsampling=0, optimize=True)


def _classic_icons() -> None:
    """Original VGA-era pixel geometry; no Microsoft bitmaps or icon packs."""
    base = ROOT / "assets/icons/RiceHub-Classic-Icons/scalable/apps"
    base.mkdir(parents=True, exist_ok=True)
    pixel = {
        "applications-other": (
            '<rect x="8" y="11" width="26" height="29" fill="#fff" stroke="#000" stroke-width="3"/>'
            '<rect x="28" y="24" width="26" height="29" fill="#c0c0c0" stroke="#000" stroke-width="3"/>'
            '<rect x="11" y="14" width="20" height="8" fill="#000080"/>'
            '<path d="M33 30h17v8H33Z" fill="#008080"/><path d="M33 43h17" stroke="#808080" stroke-width="3"/>'),
        "classic-control-panel": (
            '<path d="M11 13h42v39H11Z" fill="#fff" stroke="#000" stroke-width="3"/>'
            '<path d="M12 14h40v9H12Z" fill="#000080"/>'
            '<path d="M18 29h29M18 37h29M18 45h29" stroke="#808080" stroke-width="3"/>'
            '<circle cx="26" cy="29" r="4" fill="#c0c0c0" stroke="#000" stroke-width="2"/>'
            '<circle cx="38" cy="37" r="4" fill="#c0c0c0" stroke="#000" stroke-width="2"/>'),
        "edit-find": (
            '<rect x="9" y="9" width="42" height="43" fill="#c0c0c0" stroke="#000" stroke-width="3"/>'
            '<circle cx="29" cy="28" r="12" fill="#fff" stroke="#000080" stroke-width="5"/>'
            '<path d="M38 38l17 17" stroke="#000" stroke-width="7"/>'),
        "help-browser": (
            '<rect x="11" y="9" width="42" height="46" fill="#fdfdf0" stroke="#000" stroke-width="3"/>'
            '<rect x="14" y="12" width="36" height="8" fill="#000080"/>'
            '<path d="M24 30q1-8 9-8 10 0 8 9l-7 6v3" stroke="#000080" stroke-width="5" fill="none"/>'
            '<rect x="31" y="44" width="5" height="5" fill="#000080"/>'),
        "system-run": (
            '<rect x="6" y="10" width="52" height="44" fill="#c0c0c0" stroke="#000" stroke-width="3"/>'
            '<rect x="10" y="14" width="44" height="8" fill="#000080"/>'
            '<rect x="10" y="26" width="44" height="24" fill="#fff"/>'
            '<path d="M14 31l8 7-8 7M27 45h18" fill="none" stroke="#000" stroke-width="3"/>'),
        "system-shutdown": (
            '<rect x="9" y="12" width="46" height="39" fill="#c0c0c0" stroke="#000" stroke-width="3"/>'
            '<rect x="13" y="16" width="38" height="31" fill="#fff" stroke="#808080" stroke-width="2"/>'
            '<path d="M32 19v15M25 24a11 11 0 1 0 14 0" fill="none" stroke="#b00000" stroke-width="5"/>'),
    }
    for name, drawing in pixel.items():
        (base / f"{name}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<title>Original RiceBowl Classic {name}</title>' + drawing + '</svg>\n',
            encoding="utf-8")
    # A monochrome penguin in a square CRT: the Linux twist on the Win98 badge.
    symbol = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<title>RiceBowl Windows 98 Linux pixel penguin</title>'
        '<rect x="4" y="6" width="56" height="52" fill="#c0c0c0" stroke="#fff" stroke-width="3"/>'
        '<path d="M6 58h54V8" fill="none" stroke="#404040" stroke-width="3"/>'
        '<rect x="11" y="12" width="41" height="35" fill="#000"/>'
        '<rect x="14" y="15" width="35" height="29" fill="#008080"/>'
        '<path d="M26 36V26q0-12 8-12t8 12v10q6 6 0 8H25q-6-2 1-8" fill="#111"/>'
        '<path d="M29 30q0-8 5-8t5 8v8H29Z" fill="#fff"/>'
        '<rect x="31" y="24" width="2" height="3" fill="#000"/>'
        '<rect x="37" y="24" width="2" height="3" fill="#000"/>'
        '<path d="M32 30h6l-3 4" fill="#ffc343"/>'
        '<path d="M23 42h8M38 42h8" stroke="#ffc343" stroke-width="4"/>'
        '<path d="M24 53h18" stroke="#000" stroke-width="3"/>'
        '</svg>\n'
    )
    (ROOT / "assets/ricebowl-classic-start.svg").write_text(symbol, encoding="utf-8")
    for name in ("start-here", "xfce4-menu", "ricehub-start", "ricebowl-start"):
        (base / f"{name}.svg").write_text(symbol, encoding="utf-8")


def _frutiger_chrome(destination: Path) -> None:
    """Draw original pearl-and-lagoon XFWM artwork for Aqua World alone."""
    frame = destination / "xfwm4"
    (frame / "themerc").write_text(
        "active_text_color=#ffffff\ninactive_text_color=#e1fcfa\n"
        "button_offset=2\nbutton_spacing=2\nfull_width_title=true\n"
        "frame_border_top=0\nmaximized_offset=0\nshow_app_icon=true\n"
        "title_horizontal_offset=8\ntitle_vertical_offset_active=1\n"
        "title_vertical_offset_inactive=1\ntitle_shadow_active=true\n"
        "title_shadow_inactive=false\n", encoding="utf-8",
    )

    def gradient(width, height, upper, lower):
        canvas = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(canvas)
        for y in range(height):
            t = y / max(1, height - 1)
            col = tuple(round(a * (1 - t) + b * t) for a, b in zip(upper, lower))
            draw.line((0, y, width, y), fill=col + (255,))
        return canvas

    for state, top, bottom in (
        ("active", (118, 238, 230), (5, 114, 170)),
        ("inactive", (180, 235, 230), (77, 157, 176)),
    ):
        for number in range(1, 6):
            image = gradient(15, 32, top, bottom)
            draw = ImageDraw.Draw(image, "RGBA")
            draw.rectangle((0, 0, 14, 1), fill=(255, 255, 255, 230))
            draw.line((0, 13, 14, 13), fill=(240, 255, 255, 116))
            draw.line((0, 31, 14, 31), fill=(1, 83, 136, 225))
            image.save(frame / f"title-{number}-{state}.png")
        for side in ("top-left", "top-right"):
            image = gradient(8, 32, top, bottom)
            draw = ImageDraw.Draw(image, "RGBA")
            x = 0 if side == "top-left" else 7
            draw.line((x, 5, x, 31), fill=(12, 123, 153, 230))
            pixels = image.load()
            for y, cut in ((0, 4), (1, 3), (2, 2), (3, 1)):
                for d in range(cut):
                    pixels[d if side == "top-left" else 7-d, y] = (0, 0, 0, 0)
            image.save(frame / f"{side}-{state}.png")
        for side in ("left", "right"):
            image = gradient(5, 8, bottom, (7, 111, 145))
            draw = ImageDraw.Draw(image)
            x = 0 if side == "left" else 4
            draw.line((x, 0, x, 8), fill=(12, 92, 137, 255))
            image.save(frame / f"{side}-{state}.png")
        for part in ("bottom", "bottom-left", "bottom-right"):
            image = gradient(8, 6, bottom, (3, 91, 138))
            image.save(frame / f"{part}-{state}.png")

    for name in ("close", "maximize", "hide", "menu", "shade", "stick"):
        for state in ("active", "inactive", "prelight", "pressed"):
            if name == "close":
                top, bottom = (255, 169, 130), (208, 59, 56)
            elif name in ("shade", "stick"):
                top, bottom = (209, 255, 159), (61, 168, 96)
            else:
                top, bottom = (220, 255, 255), (28, 156, 200)
            if state == "inactive":
                top, bottom = (226, 245, 244), (120, 178, 192)
            elif state == "prelight":
                top = tuple(min(255, component + 26) for component in top)
            elif state == "pressed":
                top, bottom = bottom, top
            image = Image.new("RGBA", (27, 27), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image, "RGBA")
            draw.rounded_rectangle((2, 2, 25, 24), radius=10,
                                   fill=bottom + (255,), outline=(235, 255, 255, 255), width=1)
            for y in range(4, 15):
                t = (y - 4) / 11
                col = tuple(round(a * (1 - t) + b * t) for a, b in zip(top, bottom))
                draw.line((5, y, 22, y), fill=col + (255,))
            draw.arc((5, 3, 22, 18), 190, 350, fill=(255, 255, 255, 210), width=2)
            stroke = (255, 255, 255, 255)
            if name == "close":
                draw.line((10, 10, 18, 18), fill=stroke, width=2)
                draw.line((18, 10, 10, 18), fill=stroke, width=2)
            elif name == "maximize":
                draw.rectangle((9, 10, 18, 18), outline=stroke, width=2)
            elif name == "hide":
                draw.line((8, 18, 19, 18), fill=stroke, width=2)
            elif name == "menu":
                draw.ellipse((10, 10, 18, 18), outline=stroke, width=2)
            elif name == "shade":
                draw.polygon(((9, 16), (19, 16), (14, 10)), fill=stroke)
            else:
                draw.ellipse((11, 11, 17, 17), fill=stroke)
            image.save(frame / f"{name}-{state}.png")


def _frutiger_gtk(destination: Path) -> None:
    """Add scoped eco-glass GTK widgets without regenerating other rice themes."""
    target = destination / "gtk-3.0/gtk.css"
    css = target.read_text(encoding="utf-8")
    marker = "/* RiceBowl Aqua World 0.9: light-refracting Frutiger widgets. */"
    if marker in css:
        css = css[:css.index(marker)].rstrip() + "\n"
    target.write_text(css + """
/* RiceBowl Aqua World 0.9: light-refracting Frutiger widgets. */
window, dialog, .background, viewport { background-color: #e7fff8; color: #07506a; }
button { background-image: linear-gradient(#fff, #ecfff9 38%, #bcf2ed 51%, #84d6df);
  border: 1px solid #77c8d0; border-radius: 11px; color: #07506a;
  padding: 7px 11px; box-shadow: inset 0 1px #fff; }
button:hover { background-image: linear-gradient(#fff, #dfffed 40%, #a0efd6 55%, #57ccce);
  border-color: #2ca6bf; }
button:active, button:checked { background-image: linear-gradient(#efffd4, #b4ee68 50%, #72c943);
  border-color: #4baa5d; color: #124d62; }
button:focus { border-color: #127ba8; box-shadow: 0 0 3px #3bc3db; }
button:disabled { color: #4e8491; opacity: .66; }
entry, spinbutton, combobox box.linked { background: #faffff; color: #07506a;
  border: 1px solid #77c6d7; border-radius: 11px; padding: 7px 10px; }
entry:focus { border-color: #1588b4; box-shadow: 0 0 3px #70e5ed; }
selection, :selected, row:selected, treeview.view:selected { background: #9ce54b;
  color: #164e64; }
headerbar, .titlebar { background-image: linear-gradient(#e2ffff 0%, #9bf0e4 42%,
  #45b8cc 48%, #168baa 100%); color: #064b67; border-bottom: 2px solid #0e88a5;
  box-shadow: inset 0 1px #fff; }
headerbar button { border-radius: 12px; }
toolbar { background-image: linear-gradient(#f8ffff, #c3fff2 48%, #81d8e3);
  color: #07536d; border-bottom: 1px solid #75cbd7; }
menubar, menu, popover, .menu, .popup { background: #e6fff7; color: #07546b;
  border: 1px solid #7acecd; border-radius: 7px; }
menuitem:hover, modelbutton:hover { background: #b9f3ab; color: #14566a; }
notebook header { background: #dcfff3; border-color: #83d6db; }
notebook tab { background-image: linear-gradient(#f7ffff, #bdeee9); border: 1px solid #8dd5d8;
  border-radius: 12px 12px 0 0; padding: 7px 12px; }
notebook tab:checked { background: #fbffed; border-bottom: 2px solid #96df43; }
scrollbar trough { background: #c5f4ed; border-radius: 10px; }
scrollbar slider { background-image: linear-gradient(#f8ffff, #7ad9d9);
  border: 1px solid #5bb9c3; border-radius: 10px; min-width: 11px; min-height: 11px; }
scrollbar slider:hover { background: #7ae6ce; }
progressbar progress, scale highlight, switch:checked {
  background-image: linear-gradient(#e9ff9e, #81d947);
  border: 1px solid #5eae49; border-radius: 9px; }
tooltip { background: #fafff0; color: #0b566a; border: 1px solid #8fd4c4;
  border-radius: 6px; }
window.thunar menubar, window.thunar toolbar { background-image: linear-gradient(#fff,
  #d2fff1 38%, #8fe1e6); border-bottom: 2px solid #6bcbd5; }
window.thunar toolbar button { border-radius: 11px; box-shadow: inset 0 1px #fff; }
window.thunar .path-bar button, window.thunar .location-bar button {
  background-image: linear-gradient(#fff, #c6fff3 40%, #8cdee0);
  border: 1px solid #7bd2d2; border-radius: 15px; }
window.thunar .sidebar, window.thunar .shortcuts-pane {
  background-image: linear-gradient(to right, #e7fff3, #afe9e6);
  border-right: 2px solid #84d3d2; }
window.thunar .sidebar .view:selected, window.thunar treeview.view:selected {
  background: #a1ed43; color: #174960; }
window.thunar statusbar { background-image: linear-gradient(#effff5, #a5ecdf);
  color: #075f7d; border-top: 1px solid #83cfd0; }
/* Aqua World polish: the pane stays calm; pearl chrome carries the gloss.
   These are actual Thunar widgets, not an overlaid Explorer imitation. */
window.thunar menubar { background-image: linear-gradient(#fff, #e4fbf5);
  border-bottom: 1px solid #8dcbd2; padding: 2px 6px; }
window.thunar toolbar, window.thunar .location-bar {
  background-image: linear-gradient(#fff 0%, #eafffa 43%, #b7e8eb 46%, #c8f5f1);
  border-bottom: 1px solid #80c0d1; padding: 3px 6px; }
window.thunar toolbar button { background: transparent; border: 1px solid transparent;
  border-radius: 7px; box-shadow: none; padding: 4px 6px; }
window.thunar toolbar button:hover, window.thunar toolbar button:focus {
  background-image: linear-gradient(#fff, #b0efdd 48%, #7bdacb);
  border-color: #62bed0; }
window.thunar .path-bar { background-image: linear-gradient(#fff, #eafff9);
  border: 1px solid #83becb; border-radius: 10px; padding: 1px 3px; }
window.thunar .path-bar button, window.thunar .location-bar button {
  background: transparent; border: 1px solid transparent;
  border-radius: 7px; box-shadow: none; padding: 3px 7px; }
window.thunar .path-bar button:hover, window.thunar .location-bar button:hover {
  background-image: linear-gradient(#fff, #b5f0e1); border-color: #70bac8; }
window.thunar .sidebar, window.thunar .shortcuts-pane {
  background-image: linear-gradient(to right, #f4fff5, #e3faf3 68%, #c8f0e8);
  border-right: 1px solid #9eced0; }
window.thunar .sidebar .view, window.thunar .shortcuts-pane .view {
  background: transparent; color: #17586a; }
window.thunar .sidebar .view:selected, window.thunar .shortcuts-pane .view:selected {
  background-image: linear-gradient(#efffcf, #b5ea86); color: #205447; }
window.thunar .standard-view, window.thunar .standard-view .view,
window.thunar treeview.view, window.thunar iconview {
  background: #fbfffd; color: #204453; }
window.thunar .standard-view .view:selected, window.thunar treeview.view:selected {
  background: #b7ed88; color: #204d43; }
window.thunar statusbar {
  background-image: linear-gradient(#faffff, #dcf8ee 55%, #b8e9e4);
  color: #245c68; border-top: 1px solid #8dcad0; padding: 4px 8px; }
""", encoding="utf-8")


def _frutiger_thunar_icon() -> None:
    """Give XFCE's real Thunar desktop entry our existing glossy file icon.

    Thunar's GIcon is ``org.xfce.thunar``, not ``system-file-manager``;
    without this alias the launcher and taskbar fall back to an unrelated
    monotone GTK icon even when our Aqua folder assets are installed.
    """
    directory = ROOT / "assets/icons/RiceHub-Frutiger-Icons/scalable/apps"
    source = (directory / "system-file-manager.svg").read_text(encoding="utf-8")
    (directory / "org.xfce.thunar.svg").write_text(
        source.replace("system-file-manager</title>", "org.xfce.thunar</title>"),
        encoding="utf-8")


def _vertical(upper, lower):
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        t = y / (H - 1)
        draw.line((0, y, W, y), fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(upper, lower)))
    return image


def _save(image, name):
    destination = ROOT / "assets/wallpapers" / name
    # Each release ships hand-reviewed wallpaper artwork. Rebuilding the GTK
    # icons must never silently replace the selected full-resolution images.
    if not destination.exists():
        image.save(destination, "JPEG", quality=90, optimize=True)


def _luna():
    # Original terraced-hills scene from build_original_artwork.py (replaces the old
    # Bliss-like single-hill picture; see docs/sg4-asset-rights-audit.md RF03).
    from build_original_artwork import luna_hills
    _save(luna_hills(), "luna-hills.jpg")


def _classic():
    image = Image.new("RGB", (W, H), (0, 122, 121))
    draw = ImageDraw.Draw(image, "RGBA")
    for n in range(0, 1650, 21):
        draw.line((n, 0, n + 580, H), fill=(160, 220, 207, 9), width=2)
    draw.polygon([(W-550, 0), (W, 0), (W, H), (W-130, H)], fill=(31, 155, 150, 43))
    draw.rounded_rectangle((W-500, 160, W-150, 490), radius=5,
                           outline=(202, 249, 237, 30), width=9)
    _save(image, "classic-teal.jpg")


def _chrome():
    image = _vertical((230, 239, 253), (247, 231, 237))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse((-480, -620, 1260, 1030), fill=(138, 179, 246, 148))
    draw.ellipse((680, -300, 2440, 1450), fill=(244, 180, 210, 125))
    draw.ellipse((400, 330, 1450, 1410), fill=(218, 235, 255, 170))
    overlay = overlay.filter(ImageFilter.GaussianBlur(90))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    _save(image, "chrome-pastel.jpg")


def _frutiger():
    image = _vertical((45, 170, 219), (197, 254, 232))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((-540, 365, 1260, 1920), fill=(37, 166, 111, 255))
    draw.ellipse((720, 445, 2460, 1770), fill=(70, 201, 142, 255))
    draw.ellipse((-200, 560, 2010, 2100), fill=(98, 221, 141, 220))
    for x, y, r in ((310, 200, 140), (1410, 320, 228), (1040, 170, 66), (1730, 160, 84)):
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(222, 255, 255, 77),
                     outline=(242, 255, 255, 180), width=7)
        draw.ellipse((x-r//2, y-r//2, x+r//4, y+r//6), fill=(255, 255, 255, 55))
    for x in range(90, 1840, 190):
        y = int(785 + 40 * math.sin(x / 160))
        draw.arc((x, y-150, x+200, y+130), 180, 295, fill=(225, 255, 239, 100), width=8)
    _save(image.convert("RGB"), "frutiger-future.jpg")


def _icons(name, palette):
    base = ROOT / "assets/icons" / ("RiceHub-" + name + "-Icons")
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.theme").write_text(
        "[Icon Theme]\nName=RiceBowl " + name + " Icons\n"
        "Comment=Original RiceBowl themed icons; inherited Linux fallbacks\n"
        "Inherits=Adwaita,hicolor\nDirectories=scalable/apps,scalable/places\n"
        "[scalable/apps]\nSize=48\nType=Scalable\nMinSize=16\nMaxSize=128\n"
        "[scalable/places]\nSize=48\nType=Scalable\nMinSize=16\nMaxSize=128\n",
        encoding="utf-8",
    )
    for relative, artwork in ART.items():
        target = base / "scalable" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        artwork = artwork.replace("#0078d7", palette["accent"]).replace("#267bc3", palette["accent"])
        write_generated_icon(
            target, relative,
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            + artwork + '</svg>\n',
            heritage=True,
        )
    # Each historical desktop carries its own design-reviewed Start symbol.
    icon_names = {
        "Luna": "ricebowl-xp-start.svg",
        "Classic": "ricebowl-classic-start.svg",
        "Chrome": "ricebowl-chrome-start.svg",
        "Frutiger": "ricebowl-frutiger-start.svg",
    }
    logo = (ROOT / "assets" / icon_names[name]).read_text(encoding="utf-8")
    for filename in ("start-here", "xfce4-menu", "ricehub-start", "ricebowl-start"):
        (base / "scalable/apps" / f"{filename}.svg").write_text(logo, encoding="utf-8")


def main(*, luna_only: bool = False, frutiger_only: bool = False,
         classic_only: bool = False, chrome_only: bool = False):
    if sum((luna_only, frutiger_only, classic_only, chrome_only)) > 1:
        raise ValueError("Choose only one targeted art build")
    if chrome_only:
        from build_chrome_assets import main as build_chrome

        build_chrome()
        return
    if classic_only:
        # Never regenerate other rices or overwrite hand-curated Classic SVGs.
        path = ROOT / "assets/themes/RiceHub-Classic"
        _classic_chrome(path)
        _classic_gtk(path)
        _classic_wallpaper()
        _classic_icons()
        print("Refreshed original Windows 98 classic chrome, GTK and teal wallpaper")
        return
    if frutiger_only:
        # Preserve every other rice, the reviewed Frutiger wallpaper and all
        # hand-curated icons. Only redraw owned chrome and the Thunar app alias.
        path = ROOT / "assets/themes/RiceHub-Frutiger"
        _frutiger_chrome(path)
        _frutiger_gtk(path)
        _frutiger_thunar_icon()
        print("Refreshed Frutiger chrome, GTK and the native Thunar icon alias only")
        return
    for name, palette in PALETTES.items():
        if luna_only and name != "Luna":
            continue
        path = ROOT / "assets/themes" / ("RiceHub-" + name)
        if name == "Luna":
            # Preserve hand-reviewed GTK/Thunar rules present in shipped builds.
            if not (path / "gtk-3.0/gtk.css").exists():
                gtk(path, palette)
            _luna_chrome(path)
            _luna_gtk(path)
            _luna_fidelity_gtk(path)
        else:
            chrome(path, palette)
            gtk(path, palette)
        if not luna_only:
            _icons(name, palette)
    if luna_only:
        print("Refreshed original Luna window chrome and GTK styles only")
        return
    _luna()
    _classic()
    _chrome()
    _frutiger()
    # The dedicated Chrome art generator is the canonical owner of its
    # latest GTK/XFWM/wallpaper assets even during a full historical rebuild.
    from build_chrome_assets import main as build_chrome

    build_chrome()
    print("Generated four original XFCE window/GTK/icon themes and desktop wallpapers")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--luna-only", action="store_true",
                        help="Refresh just Luna XFWM and GTK, preserving reviewed other rices")
    parser.add_argument("--frutiger-only", action="store_true",
                        help="Refresh only the reviewed Frutiger XFWM and GTK glass styles")
    parser.add_argument("--classic-only", action="store_true",
                        help="Refresh only Windows 98 square XFWM, GTK and teal wallpaper")
    parser.add_argument("--chrome-only", action="store_true",
                        help="Refresh only ChromeOS Material You XFWM, GTK and wallpaper")
    arguments = parser.parse_args()
    main(luna_only=arguments.luna_only, frutiger_only=arguments.frutiger_only,
         classic_only=arguments.classic_only, chrome_only=arguments.chrome_only)
