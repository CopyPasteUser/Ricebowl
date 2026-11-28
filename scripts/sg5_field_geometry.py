#!/usr/bin/env python3
"""Print the painted geometry of a native Luna Run/Rename field capture.

Helper for the SG5 compositor smoke. Input: a grim crop of the whole text
field (its 2px grey frame included, 306x32 at the dialog's field origin).
Output (one line, field-local x columns): ``ink_left ink_right caret``.

- caret: the first of the two adjacent columns that are exactly the caret
  colour over the caret's full 16 rows (glyph strokes never fill that run).
- ink: the extent of every other non-white pixel inside the white interior.

Prints ``none`` for a missing caret or missing ink. Never prints pixel data.
"""
import sys

from PIL import Image

CARET = (0x10, 0x28, 0x49)
CARET_ROWS = range(9, 25)  # the 16-row caret band, field-local
WHITE = (255, 255, 255)


def geometry(path: str):
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixel = image.load()
    solid = [x for x in range(width) if all(pixel[x, y] == CARET for y in CARET_ROWS)]
    caret = next((x for x in solid if x + 1 in solid), None)
    skip = {caret, caret + 1} if caret is not None else set()
    ink = [x for x in range(3, width - 3) if x not in skip
           and any(pixel[x, y] != WHITE for y in range(3, height - 3))]
    return (ink[0], ink[-1]) if ink else (None, None), caret


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: sg5_field_geometry.py FIELD.png", file=sys.stderr)
        return 2
    (left, right), caret = geometry(argv[1])
    print(" ".join("none" if value is None else str(value) for value in (left, right, caret)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
