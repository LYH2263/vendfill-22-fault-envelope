"""前端说明全文镜像必须与后端真源逐字一致，防止只改一处导致漂移判定失真。"""
import re
from pathlib import Path

from app.services import errors

FRONTEND_ERRORS_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "errors.ts"


def test_frontend_mirror_file_exists():
    assert FRONTEND_ERRORS_TS.exists(), FRONTEND_ERRORS_TS


def test_frontend_canonical_templates_match_backend():
    text = FRONTEND_ERRORS_TS.read_text(encoding="utf-8")
    for code, template in errors.DETAIL_FULL.items():
        m = re.search(rf"\b{re.escape(code)}\s*:\s*\n?\s*'([^']*)'", text)
        assert m, f"前端镜像缺少原因码 {code}"
        assert m.group(1) == template, f"原因码 {code} 的前端镜像与后端真源不一致"


def test_frontend_mirror_has_no_extra_business_codes():
    text = FRONTEND_ERRORS_TS.read_text(encoding="utf-8")
    block = text.split("CANONICAL_DETAIL", 1)[1]
    mirrored = set(re.findall(r"^\s*([a-z_]+)\s*:", block, flags=re.M))
    mirrored = {c for c in mirrored if c in errors.ALL_CODES}
    assert mirrored == set(errors.DETAIL_FULL.keys())
