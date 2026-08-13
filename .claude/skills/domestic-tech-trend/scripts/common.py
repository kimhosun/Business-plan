"""국내기술개발 동향 조사 스크립트 공통 유틸."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# Windows 콘솔(cp949)에서 한글 로그가 깨지지 않게 한다.
try:
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# 문단 출처 마커: [S01:p12:3]  =  출처ID : 위치 : 위치 내 문단번호
CITE_RE = re.compile(r"\[([A-Z]\d{2,3}):([^\]\s:]+):(\d+)\]")

SOURCES_NAME = "sources.yaml"
MANIFEST_NAME = "manifest.json"


def load_sources(root: Path) -> dict:
    """<root>/sources.yaml 을 읽는다."""
    path = root / SOURCES_NAME
    if not path.exists():
        raise SystemExit(f"[!] {path} 가 없습니다. 먼저 조사 계획(sources.yaml)을 작성하세요.")
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        raise SystemExit("[!] PyYAML 이 필요합니다: python -m pip install PyYAML")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or "sources" not in data:
        raise SystemExit(f"[!] {path} 형식 오류: 최상위에 'sources:' 목록이 있어야 합니다.")
    seen = set()
    for i, s in enumerate(data["sources"]):
        sid = s.get("id")
        if not sid:
            raise SystemExit(f"[!] sources[{i}] 에 id 가 없습니다.")
        if sid in seen:
            raise SystemExit(f"[!] 중복 id: {sid}")
        seen.add(sid)
    return data


def load_manifest(root: Path) -> dict:
    path = root / "raw" / MANIFEST_NAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(root: Path, manifest: dict) -> None:
    path = root / "raw" / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def slugify(text: str, maxlen: int = 40) -> str:
    """파일명용 슬러그. 한글은 살리고 경로에 위험한 문자만 제거한다."""
    text = unicodedata.normalize("NFC", text or "").strip()
    text = re.sub(r"[\/:*?\"<>|\r\n\t]+", " ", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text[:maxlen] or "untitled"


def norm_ws(text: str) -> str:
    """블록 내부 줄바꿈을 공백으로 접고 공백을 정규화한다."""
    text = text.replace("­", "")          # soft hyphen
    text = re.sub(r"-\n(?=[A-Za-z])", "", text)  # 영문 하이픈 줄바꿈 결합
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"[ \t ]+", " ", text)
    return text.strip()


def is_noise(text: str) -> bool:
    """페이지번호·구분선 등 본문이 아닌 조각."""
    t = text.strip()
    if len(t) < 2:
        return True
    if re.fullmatch(r"[-–—_=·•\.\s]+", t):
        return True
    if re.fullmatch(r"[-–—\s\(\[]*\d{1,4}[-–—\s\)\]]*", t):  # 쪽번호
        return True
    return False
