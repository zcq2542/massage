import httpx, respx, hmac, hashlib, base64, urllib.parse
from jxgrab.notify import BarkWebhook, DingTalkWebhook, ServerChanWebhook, dingtalk_sign, build, notify_all

def test_dingtalk_sign_matches_spec():
    secret = "SECTEST"
    ts = 1700000000000
    string_to_sign = f"{ts}\n{secret}"
    expect = urllib.parse.quote_plus(base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()))
    assert dingtalk_sign(secret, ts) == expect

@respx.mock
async def test_bark_post_json():
    route = respx.post("https://api.day.app/KEY").mock(return_value=httpx.Response(200, json={"code": 200}))
    async with httpx.AsyncClient() as hc:
        ch = BarkWebhook({"url": "https://api.day.app/KEY"}, hc)
        await ch.send("hi", "body", "active")
    req = respx.calls[0].request
    import json as _j
    payload = _j.loads(req.content)
    assert payload["title"] == "hi" and payload["body"] == "body"

@respx.mock
async def test_dingtalk_appends_sign_when_secret():
    route = respx.post("https://oapi.dingtalk.com/robot/send").mock(
        return_value=httpx.Response(200, json={"errcode": 0}))
    async with httpx.AsyncClient() as hc:
        ch = DingTalkWebhook(
            {"webhook": "https://oapi.dingtalk.com/robot/send?access_token=T", "secret": "SECS"},
            hc)
        await ch.send("t", "b", "warning")
    url = str(respx.calls[0].request.url)
    assert "timestamp=" in url and "sign=" in url
    from urllib.parse import parse_qs, unquote_plus
    q = parse_qs(respx.calls[0].request.url.query.decode())
    ts = int(q["timestamp"][0])
    # parse_qs URL-decodes query values; unquote the recomputed sign to match
    assert q["sign"][0] == unquote_plus(dingtalk_sign("SECS", ts))

@respx.mock
async def test_serverchan_posts_sendkey():
    route = respx.post("https://sctapi.ftqq.com/SCKEY.send").mock(
        return_value=httpx.Response(200, json={"code": 0}))
    async with httpx.AsyncClient() as hc:
        ch = ServerChanWebhook({"sendkey": "SCKEY"}, hc)
        await ch.send("t", "b", "active")
    import json as _j
    payload = _j.loads(respx.calls[0].request.content)
    assert payload["title"] == "t" and payload["desp"] == "b"

@respx.mock
async def test_notify_all_fans_out_and_isolates_failures():
    respx.post("https://api.day.app/K").mock(return_value=httpx.Response(500))
    respx.post("https://sctapi.ftqq.com/SC.send").mock(return_value=httpx.Response(200, json={"code": 0}))
    from jxgrab.config import Webhook
    async with httpx.AsyncClient() as hc:
        channels = build([Webhook("bark", {"url": "https://api.day.app/K"}),
                          Webhook("serverchan", {"sendkey": "SC"})], hc)
        results = await notify_all(channels, "t", "b", "active")
    # one failed, one ok; neither raised
    assert len(results) == 2
    assert any(r.exception for r in results) and any(not r.exception for r in results)


@respx.mock
async def test_send_with_retry_retries_then_succeeds():
    route = respx.post("https://api.day.app/K").mock(side_effect=[
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json={"code": 200}),
    ])
    from jxgrab.config import Webhook
    async with httpx.AsyncClient() as hc:
        channels = build([Webhook("bark", {"url": "https://api.day.app/K"})], hc)
        results = await notify_all(channels, "t", "b", "active")
    assert route.call_count == 3                 # 1 initial + 2 retries
    assert results[0].exception is None          # 3rd attempt succeeded
