#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""hwp2hwpx.py -- convert .hwp -> .hwpx using pyhwpx (Hancom COM).

CLI:
  python hwp2hwpx.py convert --in <path.hwp|.hwpx> --out <path.hwpx>

Behavior:
  - If --in already ends .hwpx: copy to --out and print "already hwpx, copied".
  - Else: drive Hancom via pyhwpx to save-as HWPX.
  - Prints a JSON-ish result line. Exits nonzero on failure.
"""
import argparse
import json
import os
import shutil
import sys
import time


def convert(in_path: str, out_path: str) -> int:
    in_abs = os.path.abspath(in_path)
    out_abs = os.path.abspath(out_path)

    if not os.path.exists(in_abs):
        print(json.dumps({"error": "input not found", "in": in_abs}, ensure_ascii=False))
        return 2

    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)

    t0 = time.time()

    if in_abs.lower().endswith(".hwpx"):
        shutil.copy(in_abs, out_abs)
        elapsed = round(time.time() - t0, 3)
        size = os.path.getsize(out_abs)
        print("already hwpx, copied")
        print(json.dumps(
            {"converted": True, "out": out_abs, "size": size, "elapsed": elapsed},
            ensure_ascii=False))
        return 0

    h = None
    try:
        from pyhwpx import Hwp
        h = Hwp(visible=False)
        h.open(in_abs)
        ok = h.save_as(out_abs, format="HWPX")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "in": in_abs, "out": out_abs},
                         ensure_ascii=False))
        try:
            if h is not None:
                h.quit()
        except Exception:  # noqa: BLE001
            pass
        return 1
    else:
        try:
            h.quit()
        except Exception:  # noqa: BLE001
            pass

    if not ok or not os.path.exists(out_abs):
        print(json.dumps({"error": "save_as failed", "ok": bool(ok), "out": out_abs},
                         ensure_ascii=False))
        return 1

    elapsed = round(time.time() - t0, 3)
    size = os.path.getsize(out_abs)
    print(json.dumps(
        {"converted": True, "out": out_abs, "size": size, "elapsed": elapsed},
        ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hwp2hwpx",
                                 description="Convert .hwp -> .hwpx via pyhwpx (Hancom COM).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert a .hwp/.hwpx file to .hwpx")
    c.add_argument("--in", dest="in_path", required=True, help="input .hwp or .hwpx path")
    c.add_argument("--out", dest="out_path", required=True, help="output .hwpx path")
    args = ap.parse_args(argv)

    if args.cmd == "convert":
        return convert(args.in_path, args.out_path)
    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
