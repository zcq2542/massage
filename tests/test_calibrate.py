import httpx, respx
from jxgrab.config import Profile
from jxgrab.calibrate import probe

BASE = "http://www.jingxin-jk.com:825"

@respx.mock
async def test_probe_is_readonly_no_saverecord():
    respx.post(f"{BASE}/InSurHome/GetServerTime").mock(return_value=httpx.Response(200, json="2026-07-27 20:00:00"))
    respx.get(f"{BASE}/InSurHome/getTimeConfig").mock(return_value=httpx.Response(200, json={"setting_time": "[]"}))
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=[
        {"sch_id": 1, "work_begin": "20:30", "work_end": "21:00"}]))
    save_route = respx.post(f"{BASE}/InSurHome/SaveRecord")
    from jxgrab.client import SiteClient
    p = Profile(name="张三", openid="1", phone="13800138000", doc_id="22")
    async with SiteClient(BASE) as c:
        report = await probe(c, p, "2026-07-27", "2026-07-27")
    assert report["server_time"] == "2026-07-27 20:00:00"
    assert report["schedule_count"] == 1
    assert report["first_slot"]["work_begin"] == "20:30"
    assert save_route.call_count == 0  # never submits
