"""sources.yaml 의 URL 목록을 raw/ 로 내려받고 raw/manifest.json 에 기록한다.

사용:
    python fetch.py --dir research/<주제>
    python fetch.py --dir research/<주제> --only S03,S07 --force

- 이미 받은 파일은 건너뛴다(멱등). --force 로 다시 받는다.
- 실패해도 계속 진행하고 manifest 에 status 를 남긴다(부분 성공 허용).
- 로그인·동적 렌더링이 필요한 사이트는 실패로 남는다 → 수동 저장 후
  sources.yaml 의 해당 항목에 `local: raw/파일명` 을 적어두면 to_md.py 가 그걸 쓴다.
"""
from __future__ import annotations

import argparse
import hashlib
import mimetypes
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_manifest, load_sources, save_manifest, slugify  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
EXT_BY_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "application/haansofthwp": ".hwp",
    "application/x-hwp": ".hwp",
    "application/hwp+zip": ".hwpx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def _ctx() -> ssl.SSLContext:
    # 국내 공공기관 사이트는 인증서 체인이 불완전한 경우가 잦다.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download(url: str, timeout: int = 60, retries: int = 2) -> tuple[bytes, str, str]:
    """(본문, content-type, 최종URL) 반환."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "*/*",
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                return r.read(), (r.headers.get("Content-Type") or ""), r.geturl()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def pick_ext(ctype: str, url: str, body: bytes) -> str:
    if body[:5] == b"%PDF-":
        return ".pdf"
    if body[:2] == b"PK" and url.lower().endswith(".hwpx"):
        return ".hwpx"
    base = (ctype or "").split(";")[0].strip().lower()
    if base in EXT_BY_TYPE:
        return EXT_BY_TYPE[base]
    for ext in (".pdf", ".hwpx", ".hwp", ".html", ".htm", ".txt", ".xlsx", ".xls"):
        if url.lower().split("?")[0].endswith(ext):
            return ".html" if ext == ".htm" else ext
    return mimetypes.guess_extension(base) or ".bin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="조사 폴더(sources.yaml 이 있는 곳)")
    ap.add_argument("--only", default="", help="쉼표로 구분한 출처 id 만 처리")
    ap.add_argument("--force", action="store_true", help="이미 받은 것도 다시 받는다")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    root = Path(args.dir).resolve()
    data = load_sources(root)
    manifest = load_manifest(root)
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    ok = fail = skip = 0

    for src in data["sources"]:
        sid = src["id"]
        if only and sid not in only:
            continue

        # 수동 저장분: sources.yaml 의 local: 을 그대로 채택
        local = src.get("local")
        if local:
            p = (root / local) if not Path(local).is_absolute() else Path(local)
            if p.exists():
                body = p.read_bytes()
                manifest[sid] = {
                    "id": sid,
                    "title": src.get("title", ""),
                    "url": src.get("url", ""),
                    "file": str(p.relative_to(root)).replace("\\", "/"),
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                    "status": "manual",
                }
                print(f"  {sid}  수동파일 채택  {p.name}")
                ok += 1
                continue
            print(f"  {sid}  [!] local 경로 없음: {p}")

        prev = manifest.get(sid, {})
        if not args.force and prev.get("status") in ("ok", "manual"):
            f = root / prev.get("file", "")
            if f.exists():
                print(f"  {sid}  건너뜀(이미 받음)  {f.name}")
                skip += 1
                continue

        url = src.get("url")
        if not url:
            print(f"  {sid}  [!] url 없음 — 건너뜀")
            manifest[sid] = {"id": sid, "status": "no-url", "title": src.get("title", "")}
            fail += 1
            continue

        print(f"  {sid}  받는 중 … {url[:90]}")
        try:
            body, ctype, final_url = download(url, timeout=args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"  {sid}  [!] 실패: {type(e).__name__}: {e}")
            manifest[sid] = {
                "id": sid,
                "title": src.get("title", ""),
                "url": url,
                "status": f"error:{type(e).__name__}",
                "error": str(e)[:300],
                "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
            fail += 1
            continue

        ext = pick_ext(ctype, final_url, body)
        name = f"{sid}_{slugify(src.get('title') or sid)}{ext}"
        (raw / name).write_bytes(body)
        manifest[sid] = {
            "id": sid,
            "title": src.get("title", ""),
            "publisher": src.get("publisher", ""),
            "year": src.get("year", ""),
            "kind": src.get("kind", ""),
            "url": url,
            "final_url": final_url,
            "content_type": ctype,
            "file": f"raw/{name}",
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "status": "ok",
        }
        print(f"        저장  raw/{name}  ({len(body):,} bytes)")
        ok += 1

    save_manifest(root, manifest)
    print(f"\n완료: 성공 {ok} · 건너뜀 {skip} · 실패 {fail}   → {root/'raw'/'manifest.json'}")
    if fail:
        print("실패분은 브라우저로 직접 저장 후 sources.yaml 에 `local: raw/<파일명>` 을 적고 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
