import httpx
import respx
import pytest
from datetime import datetime
from jxgrab.client import SiteClient, parse_server_time

BASE = "http://www.jingxin-jk.com:825"

def test_parse_server_time_string():
    assert parse_server_time("2026-07-27 20:00:00") == datetime(2026, 7, 27, 20, 0, 0)

def test_parse_server_time_quoted_string():
    # live site returns the value double-quoted
    assert parse_server_time('"2026-07-27 19:43:40"') == datetime(2026, 7, 27, 19, 43, 40)

def test_parse_server_time_epoch_ms():
    from datetime import datetime
    # epoch ms → naive local datetime (mirrors datetime.fromtimestamp)
    assert parse_server_time(1700000000000) == datetime.fromtimestamp(1700000000.0)

def test_parse_server_time_dict():
    assert parse_server_time({"server_Time": "2026-07-27 20:00:00"}) == datetime(2026, 7, 27, 20, 0, 0)

def test_parse_server_time_raises():
    with pytest.raises(ValueError):
        parse_server_time("nonsense")

@respx.mock
async def test_get_server_time_post_with_body():
    route = respx.post(f"{BASE}/InSurHome/GetServerTime").mock(
        return_value=httpx.Response(200, json="2026-07-27 20:00:00"))
    async with SiteClient(BASE) as c:
        dt = await c.get_server_time({"doc_id": "22", "openid": "1"})
    assert dt == datetime(2026, 7, 27, 20, 0, 0)
    assert route.called
    # body must be JSON (data:e in JS), not query
    sent = respx.calls[0].request
    assert sent.content == b'{"doc_id": "22", "openid": "1"}'

@respx.mock
async def test_get_schedule_returns_list():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(
        return_value=httpx.Response(200, json=[{"sch_id": 5, "work_begin": "20:30"}]))
    async with SiteClient(BASE) as c:
        out = await c.get_schedule({"doc_id": "22"})
    assert out == [{"sch_id": 5, "work_begin": "20:30"}]

@respx.mock
async def test_get_schedule_empty_when_not_list():
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=""))
    async with SiteClient(BASE) as c:
        assert await c.get_schedule({}) == []

@respx.mock
async def test_save_record_uses_query_not_body():
    route = respx.post(f"{BASE}/InSurHome/SaveRecord").mock(
        return_value=httpx.Response(200, json={"code": "1"}))
    async with SiteClient(BASE) as c:
        resp = await c.save_record({"sch_id": "5", "name": "x"})
    assert resp == {"code": "1"}
    req = respx.calls[0].request
    assert req.url.params["sch_id"] == "5"
    assert req.url.params["name"] == "x"
    assert req.content == b""

@respx.mock
async def test_headers_include_browser_fingerprint():
    respx.post(f"{BASE}/InSurHome/GetServerTime").mock(
        return_value=httpx.Response(200, json="2026-07-27 20:00:00"))
    async with SiteClient(BASE) as c:
        await c.get_server_time({})
    h = respx.calls[0].request.headers
    assert "Mozilla" in h["user-agent"]
    assert h["referer"].startswith(BASE)
    assert h["origin"] == BASE
