"""security_score가 UI로 내보내는 status 계약.

status 값은 오래도록 한국어 문구("양호"/"위험")였고, GUI가 그걸 그대로 화면에 뿌리면서
그 문구로 색까지 판정했다 — 영어 UI에 한국어가 새어 나가고, 문구를 손대면 색이 깨졌다.
번역 가능한 status_code를 함께 실어 보내고, 사람이 읽는 status는 그대로 둔다
(Slack 봇과 에이전트가 그걸 읽는다).
"""

import pytest

from coworker.tools.security_scan import security_scan_tools

VALID_CODES = {"good", "caution", "risk", "active", "unverified", "unknown"}

STATUS_PAIRS = {
    "양호": "good",
    "주의": "caution",
    "위험": "risk",
    "활성": "active",
    "미확인": "unverified",
    "확인 불가": "unknown",
}


@pytest.fixture(scope="module")
def score():
    """실제 로컬 점검을 돌리므로 모듈당 한 번만 호출한다."""
    tools = security_scan_tools(None)
    fn = [t for t in tools if getattr(t, "__name__", "") == "security_score"]
    assert fn, "security_score 도구가 등록되지 않았다"
    return fn[0](server="")


def test_모든_항목이_번역가능한_status_code를_함께_낸다(score):
    assert score["ok"] is True
    categories = score["categories"]
    assert set(categories) == {"ssl", "ports", "firewall", "auth"}

    for name, cat in categories.items():
        assert "status_code" in cat, f"{name}에 status_code가 없다"
        assert cat["status_code"] in VALID_CODES, f"{name}: {cat['status_code']}"
        assert cat["status"], f"{name}에 status 문구가 없다"


def test_status_문구와_status_code가_짝을_이룬다(score):
    for name, cat in score["categories"].items():
        assert STATUS_PAIRS[cat["status"]] == cat["status_code"], f"{name}가 어긋난다: {cat}"
