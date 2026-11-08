#!/usr/bin/env python3
"""Offline diagnostics for genuine Wayland PNG captures.

This compatibility wrapper uses the same comparison engine as the installed
RiceBowl Creator CLI. It never launches or modifies the live desktop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from macrice.de.visual_qa import compare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--threshold", type=int, default=24)
    parser.add_argument("--tolerance-radius", type=int, default=0)
    parser.add_argument("--recipe", help="Validated bundled, imported or private rice recipe")
    parser.add_argument("--overlay", type=Path, help="New private PNG showing blended differences")
    parser.add_argument("--heatmap", type=Path, help="New private PNG highlighting RGB differences")
    parser.add_argument("--tolerant-heatmap", type=Path, help="New PNG of unexcused differences")
    parser.add_argument("--baseline", type=Path, help="Approved private visual regression policy")
    args = parser.parse_args(argv)
    try:
        report = compare(args.reference, args.actual,
                         threshold=args.threshold, recipe_token=args.recipe,
                         overlay=args.overlay, heatmap=args.heatmap,
                         tolerance_radius=args.tolerance_radius,
                         tolerant_heatmap=args.tolerant_heatmap, baseline=args.baseline)
        result = {"ok": report.get("baseline", {}).get("passed", True), **report}
    except ValueError as exc:
        result = {"ok": False, "error": {"code": "invalid_capture_or_recipe",
                                        "message": str(exc)}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else (3 if "baseline" in result else 2)


if __name__ == "__main__":
    sys.exit(main())
