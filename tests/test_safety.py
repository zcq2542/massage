import httpx, respx
from jxgrab.config import Profile, Safety
from jxgrab.safety import reconcile

BASE = "http://www.jingxin-jk.com:825"

def _profile():
    return Profile(name="张三", openid="1", phone="13800138000", doc_id="22")

@respx.mock
async def test_no_action_when_within_expected():
    respx.get(f"{BASE}/InSurHome/gethistory").mock(return_value=httpx.Response(200, json=[
        {"record_id": "r1", "sch_id": "1"}]))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        log = await reconcile(c, _profile(), expected_count=1, day="2026-07-27")
    assert log == []

@respx.mock
async def test_cancels_extras_keeping_earliest():
    history = [{"record_id": "r1", "sch_id": "1"}, {"record_id": "r2", "sch_id": "2"}]
    respx.get(f"{BASE}/InSurHome/gethistory").mock(return_value=httpx.Response(200, json=history))
    cancel = respx.post(f"{BASE}/InSurHome/cancelRecord").mock(return_value=httpx.Response(200, json={"code": "1"}))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        log = await reconcile(c, _profile(), expected_count=1, day="2026-07-27")
    assert "r2" in "".join(log)
    assert cancel.call_count == 1

@respx.mock
async def test_disabled_does_nothing():
    respx.get(f"{BASE}/InSurHome/gethistory").mock(return_value=httpx.Response(200, json=[
        {"record_id": "r1"}, {"record_id": "r2"}]))
    from jxgrab.client import SiteClient
    async with SiteClient(BASE) as c:
        log = await reconcile(c, _profile(), expected_count=1, day="2026-07-27",
                              safety=Safety(auto_cancel_extras=False))
    assert log == []
