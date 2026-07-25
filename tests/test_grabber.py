import httpx, respx
from unittest.mock import AsyncMock
from jxgrab.config import Profile, Timing
from jxgrab.grabber import run, is_success_code, GrabResult

BASE = "http://www.jingxin-jk.com:825"
PSLOT = [{"sch_id": 1, "work_begin": "20:30", "work_end": "21:00"},
         {"sch_id": 2, "work_begin": "21:00", "work_end": "21:30"}]

def _profile():
    return Profile(name="张三", openid="1", phone="13800138000", count=1, doc_id="22",
                   slot_priorities=["20:30", "21:00"])

def test_success_code_mirrors_js():
    assert is_success_code("1") is True
    assert is_success_code("200") is True
    assert is_success_code("0") is False
    assert is_success_code("-2") is False
    assert is_success_code("") is False

@respx.mock
async def test_grabs_top_priority_slot():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=PSLOT))
    respx.post(f"{BASE}/InSurHome/SaveRecord").mock(return_value=httpx.Response(200, json={"code": "1"}))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        r = await run(c, _profile(), "2026-07-27", "2026-07-27", Timing(total_timeout_s=2))
    assert r.success is True
    assert r.slot.work_begin == "20:30"
    assert r.attempts == 1

@respx.mock
async def test_minus2_falls_back_to_next_priority():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=PSLOT))
    saves = [{"code": "-2"}, {"code": "1"}]
    def side_effect(request):
        return httpx.Response(200, json=saves.pop(0))
    respx.post(f"{BASE}/InSurHome/SaveRecord").mock(side_effect=side_effect)
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        r = await run(c, _profile(), "2026-07-27", "2026-07-27", Timing(total_timeout_s=2))
    assert r.success is True
    assert r.slot.work_begin == "21:00"
    assert r.attempts == 2

@respx.mock
async def test_minus4_is_terminal_failure():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=PSLOT))
    respx.post(f"{BASE}/InSurHome/SaveRecord").mock(return_value=httpx.Response(200, json={"code": "-4", "mes": "1"}))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        r = await run(c, _profile(), "2026-07-27", "2026-07-27", Timing(total_timeout_s=2))
    assert r.success is False
    assert r.code == "-4"

@respx.mock
async def test_timeout_when_no_slots():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=[]))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        r = await run(c, _profile(), "2026-07-27", "2026-07-27", Timing(total_timeout_s=1, poll_interval_ms=200))
    assert r.success is False
    assert "no slots" in r.message
