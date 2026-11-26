#!/usr/bin/env python3
"""Exit 0 when two PNG captures are pixel-identical (`same`) or differ (`different`).

Helper for the SG5 compositor smokes. Only decoded RGB pixels are compared;
it never prints image content.
"""
import sys

from PIL import Image


def main(argv) -> int:
    if len(argv) != 4 or argv[3] not in ("same", "different"):
        print("usage: sg5_png_compare.py A.png B.png same|different", file=sys.stderr)
        return 2
    first, second = (Image.open(path).convert("RGB") for path in argv[1:3])
    identical = first.size == second.size and first.tobytes() == second.tobytes()
    return 0 if identical == (argv[3] == "same") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
