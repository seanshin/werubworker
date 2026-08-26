"""Schedule이 UI로 내보내는 일정 서술.

`human()`이 영어 한 줄뿐이라 GUI가 한국어 화면에 영어 문장을 그대로 찍고 있었다.
`security_score`에 `status_code`를 더한 것과 같은 처방 — 산문을 원하는 쪽(에이전트·Slack
봇)에는 영어 라벨을 그대로 주고, 직접 문장을 만들 쪽(GUI)에는 조각을 함께 준다.
"""

import pytest

from coworker.automation.models import Schedule


def cron(expr: str) -> Schedule:
    return Schedule(kind="cron", cron=expr)


def test_서술이_cron_모양을_구조로_가른다():
    assert cron("10 17 * * *").describe() == {"kind": "daily", "hour": 17, "minute": 10}
    assert cron("0 9 * * 1").describe() == {"kind": "weekly", "hour": 9, "minute": 0, "dow": 1}
    assert cron("30 8 15 * *").describe() == {"kind": "monthly", "hour": 8, "minute": 30, "dom": 15}
    assert Schedule(kind="once", fire_at="2026-09-01T10:00").describe() == {
        "kind": "once",
        "fire_at": "2026-09-01T10:00",
    }


@pytest.mark.parametrize("expr", ["*/5 * * * *", "0 9 1-5 * *", "bogus", ""])
def test_다룰_수_없는_cron은_raw로_넘긴다(expr):
    """범위·스텝은 이 네 모양에 안 들어간다 — 클라이언트가 cron을 그대로 보여준다."""
    d = cron(expr).describe()
    assert d["kind"] == "raw"
    assert d["cron"] == (expr or "?")


@pytest.mark.parametrize(
    "dow,name",
    [(0, "Sunday"), (1, "Monday"), (2, "Tuesday"), (3, "Wednesday"),
     (4, "Thursday"), (5, "Friday"), (6, "Saturday"), (7, "Sunday")],
)
def test_요일_라벨이_cron_규약을_따른다(dow, name):
    """cron은 0=일요일이다. 예전에는 표 인덱스를 그대로 써서 라벨이 하루씩 밀려 있었다 —
    croniter가 도는 실제 발화는 맞았으므로 "매주 월요일" 자동화가 "Every Tuesday"였다."""
    assert cron(f"0 9 * * {dow}").human() == f"Every {name} at ~9:00 AM"


def test_영어_라벨은_그대로_남는다():
    """에이전트와 Slack 봇이 이 문장을 읽는다 — 구조를 더하면서 문구를 바꾸지 않았다."""
    assert cron("10 17 * * *").human() == "Every day at ~5:10 PM"
    assert cron("30 8 15 * *").human() == "Monthly on day 15 at ~8:30 AM"
    assert cron("*/5 * * * *").human() == "*/5 * * * *"


def test_public이_구조를_함께_싣는다():
    from coworker.automation.models import ScheduledTask

    task = ScheduledTask(title="T", instructions="", schedule=cron("0 9 * * 1"), workspace="/tmp/w")
    pub = task.public()
    assert pub["schedule"] == "Every Monday at ~9:00 AM"   # 사람이 읽는 문구는 유지
    assert pub["schedule_desc"] == {"kind": "weekly", "hour": 9, "minute": 0, "dow": 1}
