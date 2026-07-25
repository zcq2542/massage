from __future__ import annotations
import asyncio, hmac, hashlib, base64, urllib.parse, time
from dataclasses import dataclass
from typing import Optional
import httpx


@dataclass
class NotifyResult:
    """Per-channel outcome of ``notify_all``; ``exception`` is None on success or the caught exception on failure."""
    exception: Optional[BaseException] = None


def dingtalk_sign(secret: str, timestamp_ms: int) -> str:
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


class Webhook:
    def __init__(self, params: dict, http: httpx.AsyncClient):
        self.params = params
        self.http = http

    async def send(self, title: str, body: str, level: str) -> None:
        raise NotImplementedError


class BarkWebhook(Webhook):
    async def send(self, title, body, level):
        payload = {"title": title, "body": body, "level": level}
        payload.update({k: v for k, v in self.params.items() if k in ("group", "icon", "sound")})
        resp = await self.http.post(self.params["url"], json=payload, timeout=5.0)
        resp.raise_for_status()


class DingTalkWebhook(Webhook):
    async def send(self, title, body, level):
        url = self.params["webhook"]
        if self.params.get("secret"):
            ts = int(time.time() * 1000)
            sign = dingtalk_sign(self.params["secret"], ts)
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={ts}&sign={sign}"
        payload = {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
        resp = await self.http.post(url, json=payload, timeout=5.0)
        resp.raise_for_status()


class ServerChanWebhook(Webhook):
    async def send(self, title, body, level):
        url = f"https://sctapi.ftqq.com/{self.params['sendkey']}.send"
        resp = await self.http.post(url, json={"title": title, "desp": body}, timeout=5.0)
        resp.raise_for_status()


_REGISTRY = {"bark": BarkWebhook, "dingtalk": DingTalkWebhook, "serverchan": ServerChanWebhook}


def build(webhooks: list, http: httpx.AsyncClient) -> list[Webhook]:
    out = []
    for w in webhooks:
        cls = _REGISTRY.get(w.type)
        if cls is None:
            raise ValueError(f"unknown webhook type: {w.type}")
        out.append(cls(w.params, http))
    return out


async def _send_with_retry(ch: Webhook, title, body, level, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            await ch.send(title, body, level)
            return NotifyResult(exception=None)
        except Exception as e:  # noqa: BLE001
            last = e
    return NotifyResult(exception=last)


async def notify_all(channels: list, title: str, body: str, level: str = "active") -> list[NotifyResult]:
    """Send a notification to every channel in parallel.

    Returns ``list[NotifyResult]`` (one per channel, in order). Callers detect
    failures with ``result.exception is not None``.
    """
    return await asyncio.gather(*[_send_with_retry(c, title, body, level) for c in channels])
