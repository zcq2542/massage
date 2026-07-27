from __future__ import annotations
from datetime import datetime
from json import dumps, loads
import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def parse_server_time(v) -> datetime:
    """Defensively parse GetServerTime response. Site returns a Date-parseable
    JSON value (string, epoch ms, or {server_Time: ...}). Confirmed exact shape
    is a calibration checkpoint; this parser covers the plausible forms.
    Returns naive datetimes in the server's local wall time."""
    if isinstance(v, (int, float)):
        secs = v / 1000 if abs(v) > 1e12 else v
        return datetime.fromtimestamp(secs)
    if isinstance(v, str):
        # Site returns the timestamp double-quoted (e.g. '"2026-07-27 19:43:40"');
        # strip whitespace and any surrounding quotes before parsing.
        s = v.strip().strip('"').strip("'").strip()
        if s.isdigit():
            return parse_server_time(int(s))
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    if isinstance(v, dict):
        for k in ("server_Time", "time", "now", "data"):
            if k in v:
                return parse_server_time(v[k])
    raise ValueError(f"unparseable server time: {v!r}")


class SiteClient:
    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = base_url
        self._c = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": UA, "Referer": base_url + "/", "Origin": base_url},
        )

    async def aclose(self):
        await self._c.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def get_server_time(self, q: dict) -> datetime:
        # JS uses data:e (axios serializes with standard spacing); send the body
        # as application/json with the spaced form the server/site expects.
        r = await self._c.post(
            "/InSurHome/GetServerTime",
            content=dumps(q).encode(),
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return parse_server_time(r.json())

    async def get_time_config(self, q: dict):
        r = await self._c.get("/InSurHome/getTimeConfig", params=q)
        r.raise_for_status()
        return r.json()

    async def get_schedule_raw(self, q: dict):
        r = await self._c.get("/InSurHome/GetSchedule", params=q)
        r.raise_for_status()
        data = r.json()
        # Site returns the slot array as a JSON-encoded string ("[{...}]");
        # decode once more so callers get the list. Guard so plain strings /
        # empty bodies don't crash (get_schedule coerces non-lists to []).
        if isinstance(data, str) and data.strip().startswith(("[", "{")):
            try:
                data = loads(data)
            except ValueError:
                pass
        return data

    async def get_schedule(self, q: dict) -> list:
        data = await self.get_schedule_raw(q)
        return data if isinstance(data, list) else []

    async def save_record(self, q: dict) -> dict:
        r = await self._c.post("/InSurHome/SaveRecord", params=q)
        r.raise_for_status()
        return r.json()

    async def get_user_info(self, q: dict):
        r = await self._c.get("/InSurHome/getUserInfo", params=q)
        r.raise_for_status()
        return r.json()

    async def get_history(self, q: dict):
        r = await self._c.get("/InSurHome/gethistory", params=q)
        r.raise_for_status()
        return r.json()

    async def cancel_record(self, q: dict) -> dict:
        r = await self._c.post("/InSurHome/cancelRecord", params=q)
        r.raise_for_status()
        return r.json()
