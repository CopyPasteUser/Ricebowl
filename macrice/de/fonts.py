"""Read-only Fontconfig inventory for the optional native RicePlate font picker.

Only importable TrueType faces are advertised. Font selection never changes
system fonts or the active desktop; Creator copies a chosen face into its
existing content-addressed private asset collection after user confirmation.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import style_assets


class FontCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class FontFace:
    family: str
    style: str
    path: Path


def installed_fonts() -> list[FontFace]:
    """Enumerate bounded, safe local faces without loading their font data."""
    try:
        result = subprocess.run(
            ["fc-list", "-f", "%{family}\t%{style}\t%{file}\n"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise FontCatalogError("Fontconfig font inventory is unavailable") from exc
    if len(result.stdout) > 2_000_000:
        raise FontCatalogError("Fontconfig inventory exceeds safe size limit")

    faces: set[FontFace] = set()
    for line in result.stdout.splitlines()[:8192]:
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        families, styles, filename = fields
        path = Path(filename)
        if not style_assets.importable_font_source(path):
            continue
        style = styles.split(",", 1)[0].strip() or "Regular"
        for family in families.split(",")[:4]:
            family = family.strip()
            if (not family or len(family) > 80 or len(style) > 60
                    or any(ord(char) < 32 for char in family + style)):
                continue
            faces.add(FontFace(family, style, path))
    return sorted(faces, key=lambda face: (face.family.casefold(), face.style.casefold(),
                                           str(face.path)))


def choose_font(family: str, style: str = "Regular") -> FontFace:
    """Resolve an exact installed family/style; never silently choose another face."""
    if not family or len(family) > 80 or not style or len(style) > 60:
        raise FontCatalogError("Choose a named installed font family and style")
    candidates = [face for face in installed_fonts() if face.family.casefold() == family.casefold()]
    normalized = style.casefold().replace(" ", "").replace("-", "")
    aliases = ({"regular", "book", "roman", "normal"} if normalized in
               {"regular", "book", "roman", "normal"} else {normalized})
    for face in candidates:
        if face.style.casefold().replace(" ", "").replace("-", "") in aliases:
            return face
    raise FontCatalogError("Selected family/style has no importable TrueType face (1 MiB limit)")
