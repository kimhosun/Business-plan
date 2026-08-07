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


def _hancom_running() -> bool:
    """한컴(HwpObject)이 이미 실행 중인지 Running Object Table 로 확인한다.

    pyhwpx 의 부착(attach) 판정과 동일 기준(`!HwpObject.` 모니커)이라, True 면
    pyhwpx 도 그 인스턴스에 '붙는다'. 이 경우 자동화가 앱을 종료(Quit)하면 사용자가
    열어둔 한글/문서 창까지 닫히므로, 종료 대신 우리가 연 문서만 닫아야 한다.
    """
    try:
        import pythoncom  # pywin32 (pyhwpx 의존성)

        ctx = pythoncom.CreateBindCtx(0)
        rot = pythoncom.GetRunningObjectTable()
        for mon in rot.EnumRunning():
            try:
                name = mon.GetDisplayName(ctx, mon)
            except Exception:  # noqa: BLE001
                continue
            if name.startswith("!HwpObject."):
                return True
    except Exception:  # noqa: BLE001 - COM 미가용 등은 '실행 안 함'으로 간주
        pass
    return False


def _shutdown(h, pre_running: bool) -> None:
    """자동화 뒤처리.

    - pre_running(사용자가 한글을 이미 열어둠): 우리가 연 활성 '문서만' 닫는다
      (`close`). 앱과 사용자의 다른 창은 그대로 둔다.
    - 아니면(우리가 새로 띄움): 우리가 만든 인스턴스만 종료(`quit`)한다.
    """
    if h is None:
        return
    try:
        if pre_running:
            h.close(is_dirty=False)   # 활성 문서(=우리가 연 문서)만 닫음 — 앱 유지
        else:
            h.quit(save=False)        # 우리가 띄운 인스턴스만 종료
    except Exception:  # noqa: BLE001
        pass


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
    # 사용자가 한글을 이미 열어뒀는지(=우리가 그 인스턴스에 붙게 되는지) 먼저 판정.
    pre_running = _hancom_running()
    try:
        from pyhwpx import Hwp
        # 사용자 인스턴스에 붙을 땐 visible=True(그의 활성 창이 숨겨지지 않도록),
        # 우리가 새로 띄울 땐 visible=False(헤드리스, 창 팝업 없음).
        h = Hwp(visible=pre_running)
        h.open(in_abs)
        ok = h.save_as(out_abs, format="HWPX")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "in": in_abs, "out": out_abs},
                         ensure_ascii=False))
        _shutdown(h, pre_running)
        return 1
    else:
        _shutdown(h, pre_running)

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
