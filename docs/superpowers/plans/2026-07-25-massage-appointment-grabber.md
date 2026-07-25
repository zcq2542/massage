# 按摩预约抢号程序 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个 Python 异步抢号程序，每周一/三 20:00 准点放号时，按优先级自动抢预约时段、填表提交，并通过 webhook 通知结果。

**Architecture:** 直接调用站点后端 API（同源 `http://www.jingxin-jk.com:825`），不驱动浏览器。核心是"并发轮询 GetSchedule → 按优先级顺序 SaveRecord → -2 回退"的抢号引擎，配合服务器对时、profile 轮换、防重复预约、webhook 通知。模块化，每个文件单一职责，可独立测试。

**Tech Stack:** Python 3.10+、httpx（异步 HTTP）、PyYAML（配置）、pytest + pytest-asyncio + respx（测试）。

## Global Constraints

- **Python ≥ 3.10**（用 `from __future__ import annotations` 支持新 typing 语法；代码未用任何 3.11+ 独有特性）。
- **目标站点**：`http://www.jingxin-jk.com:825`，API 同源。
- **接口契约**（从站点 JS 逆向确认，写代码必须照此）：
  - `POST /InSurHome/GetServerTime`，body=JSON(orderListQuery)，返回 Date 可解析的服务器时间。
  - `GET /InSurHome/getTimeConfig`，query。
  - `GET /InSurHome/GetSchedule`，query；返回时段数组，**只含有余位的时段**。
  - `POST /InSurHome/SaveRecord`，**query**（非 body）；返回 `{code, mes?}`。
  - `GET /InSurHome/getUserInfo` / `GET /InSurHome/gethistory`，query。
  - `POST /InSurHome/cancelRecord`，query。
- **参数对象 `orderListQuery`**：`doc_id`、`openid`、`day`(`YYYY-MM-DD`)、`daytime`(`YYYY-MM-DD`)、`name`、`phone`、`record_number`(预约人数)、`sch_id`(选中时段)。
- **SaveRecord 返回码**：成功 = `code > "0"`（字符串比较，镜像 JS）；`-1`=间隔不足、`-2`=时段已被抢、`-3`=手机号错、`-4`=本周额度满。`mes` 字段在某些错误码携带附加数字。
- **请求头**：带浏览器 `User-Agent`、`Referer: <base_url>/`、`Origin: <base_url>`。
- **配置文件**：`config.example.yaml` 入库；真实 `config.yaml` 与 `state.json` 已 gitignore，不入库。
- **TDD**：每个模块先写失败测试，再实现，再通过，再提交。**频繁提交**。

## File Structure

```
jxgrab/
  __init__.py
  config.py        # 配置 dataclass + YAML 加载 + 校验
  client.py        # httpx 异步站点客户端（7 个接口）
  clocksync.py     # 服务器对时 + 精确 sleep_until
  slots.py         # 时段解析 + 优先级排序
  rotation.py      # profile 轮换 + 每周额度状态（state.json）
  notify.py        # webhook：Bark / DingTalk / ServerChan
  grabber.py       # 抢号引擎核心
  safety.py        # 误抢检测 + cancelRecord 兜底
  calibrate.py     # 只读标定 CLI
  main.py          # 入口 CLI，编排全部
config.example.yaml
pyproject.toml
tests/
  conftest.py
  test_config.py test_client.py test_clocksync.py test_slots.py
  test_rotation.py test_notify.py test_grabber.py test_safety.py
README.md          # 部署说明（cron、config）
```

依赖顺序：config → client → {clocksync, slots, rotation, notify}（并行）→ grabber → safety → {calibrate, main}。

---

### Task 1: 项目骨架 + 配置层

**Files:**
- Create: `pyproject.toml`
- Create: `jxgrab/__init__.py`
- Create: `jxgrab/config.py`
- Create: `config.example.yaml`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Config`、`Profile`、`Timing`、`Rotation`、`Safety`、`Webhook` dataclass；`load_config(path) -> Config`；`Profile.id` 属性（`f"{doc_id}:{openid}:{phone}"`）。

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "jxgrab"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["httpx>=0.27", "PyYAML>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "respx>=0.21"]

[project.scripts]
jxgrab = "jxgrab.main:main"
jxgrab-calibrate = "jxgrab.calibrate:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 写 `jxgrab/__init__.py`（空包标记）**

```python
"""jingxin massage appointment grabber."""
```

- [ ] **Step 3: 写 `config.example.yaml`**

```yaml
base_url: http://www.jingxin-jk.com:825
# 通知渠道：列表，可配 0~N 个，notify 向全部推送。
webhooks:
  - type: bark
    url: https://api.day.app/XXXXXXXX
  - type: dingtalk
    webhook: https://oapi.dingtalk.com/robot/send?access_token=XXXXXXXX
    secret: SECXXXXXXXX
  - type: serverchan
    sendkey: SCTXXXXXXXX
timing:
  start_lead_seconds: 60
  pre_poll_seconds: 1.0
  poll_interval_ms: 50
  poll_concurrency: 8
  fire_concurrency: 3
  total_timeout_s: 30.0
rotation:
  enabled: true
  weekly_quota: 1
  state_file: state.json
safety:
  dedup: true
  auto_cancel_extras: true
profiles:
  - name: 张三
    openid: "1"
    phone: "13800138000"
    count: 1
    doc_id: "22"
    slot_priorities: ["20:30", "21:00", "21:30"]
    book_date: tomorrow        # today | tomorrow | YYYY-MM-DD
  - name: 李四
    openid: "2"
    phone: "13900139000"
    count: 1
    doc_id: "22"
    slot_priorities: ["20:30"]
    book_date: tomorrow
```

- [ ] **Step 4: 写失败测试 `tests/test_config.py`**

```python
from pathlib import Path
from jxgrab.config import load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"

def test_load_example_config():
    cfg = load_config(EXAMPLE)
    assert cfg.base_url == "http://www.jingxin-jk.com:825"
    assert len(cfg.profiles) == 2
    p = cfg.profiles[0]
    assert p.name == "张三"
    assert p.openid == "1"
    assert p.phone == "13800138000"
    assert p.doc_id == "22"
    assert p.slot_priorities == ["20:30", "21:00", "21:30"]
    assert p.book_date == "tomorrow"

def test_profile_id_is_stable_key():
    cfg = load_config(EXAMPLE)
    p = cfg.profiles[0]
    assert p.id == "22:1:13800138000"

def test_defaults_applied():
    cfg = load_config(EXAMPLE)
    assert cfg.timing.poll_concurrency == 8
    assert cfg.rotation.weekly_quota == 1
    assert cfg.safety.auto_cancel_extras is True

def test_webhooks_parsed():
    cfg = load_config(EXAMPLE)
    types = [w.type for w in cfg.webhooks]
    assert types == ["bark", "dingtalk", "serverchan"]
    assert cfg.webhooks[1].params["secret"] == "SECXXXXXXXX"
```

- [ ] **Step 5: 写 `tests/conftest.py`（空，预留 fixture 位置）**

```python
# shared pytest fixtures can go here
```

- [ ] **Step 6: 实现 `jxgrab/config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class Webhook:
    type: str
    params: dict = field(default_factory=dict)


@dataclass
class Profile:
    name: str
    openid: str
    phone: str
    count: int = 1
    doc_id: str = "22"
    slot_priorities: list[str] = field(default_factory=list)
    book_date: str = "tomorrow"  # "today" | "tomorrow" | "YYYY-MM-DD"

    @property
    def id(self) -> str:
        return f"{self.doc_id}:{self.openid}:{self.phone}"


@dataclass
class Timing:
    start_lead_seconds: int = 60
    pre_poll_seconds: float = 1.0
    poll_interval_ms: int = 50
    poll_concurrency: int = 8
    fire_concurrency: int = 3
    total_timeout_s: float = 30.0


@dataclass
class Rotation:
    enabled: bool = True
    weekly_quota: int = 1
    state_file: str = "state.json"


@dataclass
class Safety:
    dedup: bool = True
    auto_cancel_extras: bool = True


@dataclass
class Config:
    base_url: str
    profiles: list[Profile]
    webhooks: list[Webhook] = field(default_factory=list)
    timing: Timing = field(default_factory=Timing)
    rotation: Rotation = field(default_factory=Rotation)
    safety: Safety = field(default_factory=Safety)


def _sub(raw: dict, cls):
    return cls(**{k: raw[k] for k in raw if k in cls.__dataclass_fields__})


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = [Profile(**p) for p in raw.get("profiles", [])]
    webhooks = [Webhook(type=w["type"], params={k: v for k, v in w.items() if k != "type"})
                for w in raw.get("webhooks", [])]
    return Config(
        base_url=raw["base_url"],
        profiles=profiles,
        webhooks=webhooks,
        timing=_sub(raw.get("timing", {}), Timing),
        rotation=_sub(raw.get("rotation", {}), Rotation),
        safety=_sub(raw.get("safety", {}), Safety),
    )
```

- [ ] **Step 7: 装依赖并跑测试**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 8: 提交**

```bash
git add pyproject.toml jxgrab/__init__.py jxgrab/config.py config.example.yaml tests/conftest.py tests/test_config.py
git commit -m "feat: project scaffold + config layer"
```

---

### Task 2: 站点 HTTP 客户端 `client.py`

**Files:**
- Create: `jxgrab/client.py`
- Create: `tests/test_client.py`

**Interfaces:**
- Consumes: `Config.base_url`。
- Produces: `SiteClient(base_url, timeout)`；async 方法 `get_server_time(q)->datetime`、`get_time_config(q)`、`get_schedule(q)->list`、`save_record(q)->dict`、`get_user_info(q)`、`get_history(q)`、`cancel_record(q)->dict`；`aclose()`；async context manager。模块级 `parse_server_time(v)->datetime`。

- [ ] **Step 1: 写失败测试 `tests/test_client.py`**

```python
import httpx
import respx
import pytest
from datetime import datetime
from jxgrab.client import SiteClient, parse_server_time

BASE = "http://www.jingxin-jk.com:825"

def test_parse_server_time_string():
    assert parse_server_time("2026-07-27 20:00:00") == datetime(2026, 7, 27, 20, 0, 0)

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_client.py -v`
Expected: FAIL（`jxgrab.client` 不存在）。

- [ ] **Step 3: 实现 `jxgrab/client.py`**

```python
from __future__ import annotations
from datetime import datetime
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
        s = v.strip()
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
        r = await self._c.post("/InSurHome/GetServerTime", json=q)
        r.raise_for_status()
        return parse_server_time(r.json())

    async def get_time_config(self, q: dict):
        r = await self._c.get("/InSurHome/getTimeConfig", params=q)
        r.raise_for_status()
        return r.json()

    async def get_schedule(self, q: dict) -> list:
        r = await self._c.get("/InSurHome/GetSchedule", params=q)
        r.raise_for_status()
        data = r.json()
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_client.py -v`
Expected: 8 passed.

- [ ] **Step 5: 提交**

```bash
git add jxgrab/client.py tests/test_client.py
git commit -m "feat: site HTTP client (7 endpoints, browser headers)"
```

---

### Task 3: 对时 `clocksync.py`

**Files:**
- Create: `jxgrab/clocksync.py`
- Create: `tests/test_clocksync.py`

**Interfaces:**
- Consumes: `SiteClient.get_server_time`。
- Produces: `ClockSync(client)`；`async calibrate(q, samples=5)->float`（返回偏移秒）；`server_now()->datetime`；`async sleep_until(target: datetime)`。

- [ ] **Step 1: 写失败测试 `tests/test_clocksync.py`**

```python
import time as _time
from datetime import datetime
from unittest.mock import AsyncMock
from jxgrab.clocksync import ClockSync

async def test_calibrate_makes_server_now_track_skew():
    # offset's raw value mixes wall vs monotonic epochs; test the OUTCOME:
    # after calibrate, server_now() reflects the server's skew vs local.
    ahead = 10.0
    client = AsyncMock()
    client.get_server_time.return_value = datetime.fromtimestamp(_time.time() + ahead)
    cs = ClockSync(client)
    await cs.calibrate({}, samples=3)
    expected = _time.time() + ahead
    assert abs(cs.server_now().timestamp() - expected) < 0.5

async def test_calibrate_uses_median_ignoring_outlier():
    base = _time.time()
    client = AsyncMock()
    # two samples at +5s, one outlier at +100s → median stays near +5
    client.get_server_time.side_effect = [
        datetime.fromtimestamp(base + 5),
        datetime.fromtimestamp(base + 100),
        datetime.fromtimestamp(base + 5),
    ]
    cs = ClockSync(client)
    await cs.calibrate({}, samples=3)
    expected = _time.time() + 5
    assert abs(cs.server_now().timestamp() - expected) < 1.0

async def test_sleep_until_returns_immediately_if_past():
    client = AsyncMock()
    cs = ClockSync(client)
    cs.offset = 0.0
    past = datetime(2000, 1, 1)
    await cs.sleep_until(past)  # should not block
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_clocksync.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `jxgrab/clocksync.py`**

```python
from __future__ import annotations
import asyncio, time, statistics
from datetime import datetime


class ClockSync:
    def __init__(self, client):
        self.client = client
        self.offset = 0.0  # server_epoch - local_monotonic_epoch

    async def calibrate(self, q: dict, samples: int = 5) -> float:
        offs: list[float] = []
        for _ in range(samples):
            t0 = time.monotonic()
            st = await self.client.get_server_time(q)
            t1 = time.monotonic()
            # assume network symmetric: server time corresponds to local midpoint
            offs.append(st.timestamp() - (t0 + t1) / 2)
        self.offset = statistics.median(offs)
        return self.offset

    def server_now(self) -> datetime:
        return datetime.fromtimestamp(time.monotonic() + self.offset)

    async def sleep_until(self, target: datetime) -> None:
        """Sleep until server time reaches `target`. Coarse asyncio.sleep for
        the bulk, busy-wait the final 50 ms for precision."""
        while True:
            remaining = (target - self.server_now()).total_seconds()
            if remaining <= 0:
                return
            if remaining > 0.1:
                await asyncio.sleep(remaining - 0.05)
            else:
                # tight spin for the last sliver
                while (target - self.server_now()).total_seconds() > 0:
                    pass
                return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_clocksync.py -v`
Expected: 3 passed.

- [ ] **Step 5: 提交**

```bash
git add jxgrab/clocksync.py tests/test_clocksync.py
git commit -m "feat: server clock sync + precise sleep_until"
```

---

### Task 4: 时段解析与排序 `slots.py`

**Files:**
- Create: `jxgrab/slots.py`
- Create: `tests/test_slots.py`

**Interfaces:**
- Produces: `Slot` dataclass（`sch_id`、`work_begin`、`work_end`、`raw`）；`parse(raw)->list[Slot]`；`rank_by_priority(slots, priorities)->list[Slot]`。

- [ ] **Step 1: 写失败测试 `tests/test_slots.py`**

```python
from jxgrab.slots import Slot, parse, rank_by_priority

RAW = [
    {"sch_id": 1, "work_begin": "21:00", "work_end": "21:30"},
    {"sch_id": 2, "work_begin": "20:30", "work_end": "21:00"},
    {"sch_id": 3, "work_begin": "22:00", "work_end": "22:30"},
]

def test_parse_normalizes():
    slots = parse(RAW)
    assert len(slots) == 3
    assert isinstance(slots[0], Slot)
    assert slots[0].sch_id == "1"
    assert slots[0].work_begin == "20:30" or slots[0].sch_id == "1"

def test_parse_empty_and_none():
    assert parse(None) == []
    assert parse([]) == []

def test_rank_matched_first_in_priority_order():
    slots = parse(RAW)
    ranked = rank_by_priority(slots, ["20:30", "21:00"])
    assert ranked[0].work_begin == "20:30"
    assert ranked[1].work_begin == "21:00"

def test_rank_unmatched_appended_by_time():
    slots = parse(RAW)
    ranked = rank_by_priority(slots, ["20:30"])
    assert ranked[0].work_begin == "20:30"
    # 21:00 before 22:00 (time order) in the tail
    assert ranked[1].work_begin == "21:00"
    assert ranked[2].work_begin == "22:00"

def test_rank_no_priorities_keeps_time_order():
    slots = parse(RAW)
    ranked = rank_by_priority(slots, [])
    assert [s.work_begin for s in ranked] == ["20:30", "21:00", "22:00"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_slots.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/slots.py`**

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Slot:
    sch_id: str
    work_begin: str
    work_end: str
    raw: dict


def parse(raw) -> list[Slot]:
    out: list[Slot] = []
    for item in (raw or []):
        out.append(Slot(
            sch_id=str(item.get("sch_id", "")),
            work_begin=str(item.get("work_begin", "")),
            work_end=str(item.get("work_end", "")),
            raw=item,
        ))
    return out


def rank_by_priority(slots: list[Slot], priorities: list[str]) -> list[Slot]:
    prio = {p: i for i, p in enumerate(priorities)}
    matched = [s for s in slots if s.work_begin in prio]
    matched.sort(key=lambda s: prio[s.work_begin])
    rest = sorted([s for s in slots if s.work_begin not in prio], key=lambda s: s.work_begin)
    return matched + rest
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_slots.py -v`
Expected: 5 passed.

- [ ] **Step 5: 提交**

```bash
git add jxgrab/slots.py tests/test_slots.py
git commit -m "feat: slot parsing + priority ranking"
```

---

### Task 5: profile 轮换 `rotation.py`

**Files:**
- Create: `jxgrab/rotation.py`
- Create: `tests/test_rotation.py`

**Interfaces:**
- Consumes: `Config.rotation`、`Config.profiles`、`Profile.id`。
- Produces: `Rotation(config)`；`pick_profile(profiles)->Profile|None`；`mark_booked(profiles, profile)`；读写 `state.json`。

- [ ] **Step 1: 写失败测试 `tests/test_rotation.py`**

```python
import json
from pathlib import Path
from unittest.mock import patch
from datetime import date
from jxgrab.config import Profile
from jxgrab.rotation import Rotation, iso_week

def _profiles():
    return [
        Profile(name="A", openid="1", phone="111", doc_id="22"),
        Profile(name="B", openid="2", phone="222", doc_id="22"),
    ]

def _cfg_with_state(tmp_path, state_file):
    from jxgrab.config import Config, RotationCfg
    # build a minimal config-like object exposing .rotation
    class R:
        enabled = True; weekly_quota = 1; state_file = str(tmp_path / state_file)
    class Cfg:
        rotation = R()
    return Cfg()

def test_pick_first_eligible(tmp_path):
    cfg = _cfg_with_state(tmp_path, "s.json")
    r = Rotation(cfg)
    p = r.pick_profile(_profiles())
    assert p.name == "A"

def test_skip_exhausted_pick_next(tmp_path):
    cfg = _cfg_with_state(tmp_path, "s.json")
    r = Rotation(cfg)
    ps = _profiles()
    r.mark_booked(ps, ps[0])  # A used up this week
    assert r.pick_profile(ps).name == "B"

def test_all_exhausted_returns_none(tmp_path):
    cfg = _cfg_with_state(tmp_path, "s.json")
    r = Rotation(cfg)
    ps = _profiles()
    r.mark_booked(ps, ps[0])
    r.mark_booked(ps, ps[1])
    assert r.pick_profile(ps) is None

def test_new_week_resets_usage(tmp_path):
    cfg = _cfg_with_state(tmp_path, "s.json")
    r = Rotation(cfg)
    ps = _profiles()
    r.mark_booked(ps, ps[0])
    # simulate state from last week
    r.state["week"] = "1999-W01"
    assert r.pick_profile(ps).name == "A"  # reset → A eligible again

def test_disabled_returns_first(tmp_path):
    class R:
        enabled = False; weekly_quota = 1; state_file = str(tmp_path/"s.json")
    class Cfg:
        rotation = R()
    r = Rotation(Cfg())
    assert r.pick_profile(_profiles()).name == "A"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_rotation.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/rotation.py`**

```python
from __future__ import annotations
import json
from pathlib import Path
from datetime import date


def iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


class Rotation:
    def __init__(self, config):
        self.cfg = config.rotation
        self.path = Path(self.cfg.state_file)
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"week": iso_week(date.today()), "rotation_index": 0, "used": {}}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _reset_if_new_week(self) -> None:
        w = iso_week(date.today())
        if self.state.get("week") != w:
            self.state["week"] = w
            self.state["used"] = {}

    def pick_profile(self, profiles: list):
        if not profiles:
            return None
        if not self.cfg.enabled:
            return profiles[0]
        self._reset_if_new_week()
        n = len(profiles)
        for i in range(n):
            idx = (self.state["rotation_index"] + i) % n
            p = profiles[idx]
            if self.state["used"].get(p.id, 0) < self.cfg.weekly_quota:
                self.state["rotation_index"] = idx
                self._save()
                return p
        return None

    def mark_booked(self, profiles: list, profile) -> None:
        self._reset_if_new_week()
        self.state["used"][profile.id] = self.state["used"].get(profile.id, 0) + 1
        if profiles:
            self.state["rotation_index"] = (self.state["rotation_index"] + 1) % len(profiles)
        self._save()
```

> **注：** 测试里内联构造了一个只暴露 `.rotation` 的假 cfg；生产代码直接传 `load_config()` 拿到的 `Config` 对象——其 `.rotation` 是 `jxgrab.config.Rotation` 实例，字段（`enabled/weekly_quota/state_file`）完全匹配，无需任何适配。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_rotation.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add jxgrab/rotation.py tests/test_rotation.py
git commit -m "feat: profile auto-rotation with weekly quota state"
```

---

### Task 6: webhook 通知 `notify.py`

**Files:**
- Create: `jxgrab/notify.py`
- Create: `tests/test_notify.py`

**Interfaces:**
- Consumes: `Config.webhooks`（`Webhook.type` + `Webhook.params`）。
- Produces: `Webhook` 基类 + `BarkWebhook`/`DingTalkWebhook`/`ServerChanWebhook`；`build(webhooks, http_client)->list`；`async notify_all(channels, title, body, level)`。模块级 `dingtalk_sign(secret, timestamp_ms)`。

- [ ] **Step 1: 写失败测试 `tests/test_notify.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_notify.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/notify.py`**

```python
from __future__ import annotations
import asyncio, hmac, hashlib, base64, urllib.parse, time
import httpx


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
        resp = await self.http.post(url, data={"title": title, "desp": body}, timeout=5.0)
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
            return None
        except Exception as e:  # noqa: BLE001
            last = e
    return last


async def notify_all(channels: list, title: str, body: str, level: str = "active") -> list:
    return await asyncio.gather(*[_send_with_retry(c, title, body, level) for c in channels])
```

> **说明：** `notify_all` 返回每通道的异常（None 表示成功），调用方据此汇总。`gather` 默认不把异常抛出（被 `_send_with_retry` 吞成返回值），单通道失败不影响其他。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_notify.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add jxgrab/notify.py tests/test_notify.py
git commit -m "feat: bark/dingtalk/serverchan webhook notify with retry"
```

---

### Task 7: 抢号引擎 `grabber.py`

**Files:**
- Create: `jxgrab/grabber.py`
- Create: `tests/test_grabber.py`

**Interfaces:**
- Consumes: `SiteClient`、`slots.parse`、`slots.rank_by_priority`、`Profile`、`Timing`。
- Produces: `GrabResult` dataclass；`async run(client, profile, day, daytime, timing)->GrabResult`；`is_success_code(code)->bool`。

- [ ] **Step 1: 写失败测试 `tests/test_grabber.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_grabber.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/grabber.py`**

```python
from __future__ import annotations
import asyncio, time
from dataclasses import dataclass

from .slots import Slot, parse, rank_by_priority

_TERMINAL_FAIL = {"-1", "-3", "-4"}


def is_success_code(code: str) -> bool:
    # Mirror site JS: success when code > "0" (string compare). Known negatives
    # ("-1".."-4") all sort below "0", so this excludes them.
    return bool(code) and code > "0"


@dataclass
class GrabResult:
    success: bool
    slot: Slot | None = None
    code: str | None = None
    attempts: int = 0
    duration_ms: int = 0
    message: str = ""


async def _poll_once(client, q: dict) -> list:
    try:
        return await client.get_schedule(q)
    except Exception:
        return []


async def _first_nonempty_schedule(client, q: dict, timing) -> list:
    deadline = time.monotonic() + timing.total_timeout_s
    interval = timing.poll_interval_ms / 1000
    while time.monotonic() < deadline:
        tasks = [asyncio.create_task(_poll_once(client, q)) for _ in range(timing.poll_concurrency)]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                return r
        await asyncio.sleep(interval)
    return []


async def run(client, profile, day: str, daytime: str, timing) -> GrabResult:
    start = time.monotonic()
    base_q = {"doc_id": profile.doc_id, "openid": profile.openid, "day": day, "daytime": daytime}

    raw = await _first_nonempty_schedule(client, base_q, timing)
    duration = int((time.monotonic() - start) * 1000)
    if not raw:
        return GrabResult(False, duration_ms=duration, message="timeout: no slots released")

    ranked = rank_by_priority(parse(raw), profile.slot_priorities)
    result = GrabResult(False, duration_ms=duration)

    fired: set[str] = set()
    for slot in ranked:
        if slot.sch_id in fired:
            continue
        fired.add(slot.sch_id)
        result.attempts += 1
        q = {**base_q, "name": profile.name, "phone": profile.phone,
             "record_number": profile.count, "sch_id": slot.sch_id}
        try:
            resp = await client.save_record(q)
        except Exception as e:  # noqa: BLE001
            result.message = f"save_record error: {e!r}"
            continue
        code = str(resp.get("code", ""))
        result.code = code
        if is_success_code(code):
            result.success = True
            result.slot = slot
            result.message = "ok"
            break
        if code in _TERMINAL_FAIL:
            result.message = f"terminal code {code} (mes={resp.get('mes')})"
            break
        # code == "-2" or unknown → try next priority slot
    result.duration_ms = int((time.monotonic() - start) * 1000)
    return result
```

> **设计说明（与 spec §3 策略 C 的对应）：** 轮询阶段是并发的（速度）；**发射阶段是按优先级顺序 await**（安全）。spec 里"流水线发射"的本意是"尽快提交"，而最快且正确的做法就是拿到时段后立即对最高优先级发一次 SaveRecord（单 RTT）。只有收到 `-2` 才回退下一个——而是否回退必须等响应才知道，所以无法"盲并发"多发（多发会同时抢到多个时段=重复预约）。因此顺序发射既是最快也是唯一不引入重复预约的形态；spec 的 `cancelRecord` 兜底（Task 8）仍保留作残余风险的安全网。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_grabber.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add jxgrab/grabber.py tests/test_grabber.py
git commit -m "feat: grab engine (concurrent poll + priority fire + -2 fallback)"
```

---

### Task 8: 误抢兜底 `safety.py`

**Files:**
- Create: `jxgrab/safety.py`
- Create: `tests/test_safety.py`

**Interfaces:**
- Consumes: `SiteClient.get_history`、`SiteClient.cancel_record`、`Profile`、`Config.safety`。
- Produces: `async reconcile(client, profile, expected_count, day)->list[str]`（操作日志，空表示无需撤销）。

- [ ] **Step 1: 写失败测试 `tests/test_safety.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_safety.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/safety.py`**

```python
from __future__ import annotations
from .config import Safety


def _record_id(rec) -> str:
    for k in ("record_id", "id", "rec_id"):
        if rec.get(k):
            return str(rec[k])
    return ""


async def reconcile(client, profile, expected_count: int, day: str,
                    safety: Safety | None = None) -> list[str]:
    """If today's bookings exceed expected_count, cancel the extras (keep earliest)."""
    safety = safety or Safety()
    if not safety.auto_cancel_extras:
        return []
    q = {"doc_id": profile.doc_id, "openid": profile.openid, "day": day}
    try:
        history = await client.get_history(q)
    except Exception:
        return ["safety: get_history failed, skipping reconcile"]
    if not isinstance(history, list):
        return []
    if len(history) <= expected_count:
        return []
    log: list[str] = []
    extras = history[expected_count:]  # keep first `expected_count`, cancel rest
    for rec in extras:
        rid = _record_id(rec)
        if not rid:
            continue
        try:
            await client.cancel_record({**q, "record_id": rid})
            log.append(f"safety: cancelled extra record {rid}")
        except Exception as e:  # noqa: BLE001
            log.append(f"safety: cancel {rid} failed: {e!r}")
    return log
```

> **注：** `get_history` 的返回结构与 `cancelRecord` 的确切参数是标定检查项（见第 11 节未知项）。本实现按最常见形态（records 数组 + `record_id`）写，标定后若有出入只改此文件。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_safety.py -v`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add jxgrab/safety.py tests/test_safety.py
git commit -m "feat: safety reconcile (cancel accidental extra bookings)"
```

---

### Task 9: 只读标定工具 `calibrate.py`

**Files:**
- Create: `jxgrab/calibrate.py`
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `SiteClient.get_server_time`/`get_time_config`/`get_schedule`、`load_config`、`clocksync`。
- Produces: `async probe(client, profile, day, daytime)->dict`（抓取到的真实响应摘要）；`main(argv)`（CLI）。

- [ ] **Step 1: 写失败测试 `tests/test_calibrate.py`**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_calibrate.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/calibrate.py`**

```python
from __future__ import annotations
import argparse, asyncio, json, sys
from datetime import datetime, timedelta

from .config import load_config
from .client import SiteClient


async def probe(client: SiteClient, profile, day: str, daytime: str) -> dict:
    q = {"doc_id": profile.doc_id, "openid": profile.openid, "day": day, "daytime": daytime}
    report: dict = {"profile": profile.name, "day": day}
    try:
        st = await client.get_server_time(q)
        report["server_time"] = st.strftime("%Y-%m-%d %H:%M:%S")
        report["server_time_raw_note"] = "confirm exact response shape vs parse_server_time"
    except Exception as e:  # noqa: BLE001
        report["server_time_error"] = repr(e)
    try:
        report["time_config"] = await client.get_time_config(q)
    except Exception as e:  # noqa: BLE001
        report["time_config_error"] = repr(e)
    try:
        sched = await client.get_schedule(q)
        report["schedule_count"] = len(sched)
        report["first_slot"] = sched[0] if sched else None
        report["slot_fields"] = list(sched[0].keys()) if sched else []
    except Exception as e:  # noqa: BLE001
        report["schedule_error"] = repr(e)
    return report


def _candidate_dates(today: datetime) -> list[tuple[str, str]]:
    days = [today, today + timedelta(days=1), today + timedelta(days=2)]
    return [(d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")) for d in days]


async def run(config_path: str, doc_id: str | None) -> list[dict]:
    cfg = load_config(config_path)
    async with SiteClient(cfg.base_url, timeout=6.0) as client:
        # use first profile for probing (or derive a synthetic one by doc_id)
        profiles = cfg.profiles or []
        if doc_id and not profiles:
            from .config import Profile
            profiles = [Profile(name="(probe)", openid="1", phone="13800000000", doc_id=doc_id)]
        today = datetime.now()
        reports = []
        for p in profiles[:1]:
            for day, daytime in _candidate_dates(today):
                r = await probe(client, p, day, daytime)
                reports.append(r)
        return reports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="read-only calibration probe (never submits)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--doc-id", default=None)
    args = ap.parse_args(argv)
    reports = asyncio.run(run(args.config, args.doc_id))
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_calibrate.py -v`
Expected: 1 passed。

- [ ] **Step 5: 提交**

```bash
git add jxgrab/calibrate.py tests/test_calibrate.py
git commit -m "feat: read-only calibration probe CLI"
```

---

### Task 10: 入口 `main.py`

**Files:**
- Create: `jxgrab/main.py`
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: 全部上层模块。
- Produces: `async run_grab(config_path, target)->dict`；`main(argv)->int`。

- [ ] **Step 1: 写失败测试 `tests/test_main.py`**

```python
import httpx, respx, json
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from jxgrab.main import run_grab

BASE = "http://www.jingxin-jk.com:825"
EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"

@respx.mock
async def test_run_grab_success_marks_booked_and_notifies(tmp_path, monkeypatch):
    # point state file into tmp
    import yaml
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw["rotation"]["state_file"] = str(tmp_path / "state.json")
    raw["webhooks"] = []  # no real webhook
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    respx.post(f"{BASE}/InSurHome/GetServerTime").mock(return_value=httpx.Response(200, json="2026-07-27 19:59:55"))
    respx.get(f"{BASE}/InSurHome/GetSchedule").mock(return_value=httpx.Response(200, json=[
        {"sch_id": 1, "work_begin": "20:30", "work_end": "21:00"}]))
    respx.post(f"{BASE}/InSurHome/SaveRecord").mock(return_value=httpx.Response(200, json={"code": "1"}))
    respx.get(f"{BASE}/InSurHome/gethistory").mock(return_value=httpx.Response(200, json=[
        {"record_id": "r1"}]))

    # skip the real clock wait
    async def fake_sleep_until(self, target):
        return None
    monkeypatch.setattr("jxgrab.clocksync.ClockSync.sleep_until", fake_sleep_until)

    result = await run_grab(str(cfg_path), target=None)
    assert result["success"] is True
    assert result["profile"] == "张三"
    # rotation state persisted a booking
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["used"]["22:1:13800138000"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_main.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `jxgrab/main.py`**

```python
from __future__ import annotations
import argparse, asyncio, logging, sys
from datetime import datetime, timedelta

import httpx

from .config import load_config
from .client import SiteClient
from .clocksync import ClockSync
from .rotation import Rotation
from .grabber import run as grab_run
from .safety import reconcile
from . import notify

log = logging.getLogger("jxgrab")


def resolve_book_date(spec: str, today: datetime) -> tuple[str, str]:
    if spec in ("today",):
        d = today
    elif spec in ("tomorrow",):
        d = today + timedelta(days=1)
    else:
        d = datetime.strptime(spec, "%Y-%m-%d")
    s = d.strftime("%Y-%m-%d")
    return s, s


async def run_grab(config_path: str, target: str | None) -> dict:
    cfg = load_config(config_path)
    rotation = Rotation(cfg)
    profiles = cfg.profiles

    if target:
        profiles = [p for p in profiles if p.name == target or p.id == target]
        if not profiles:
            raise SystemExit(f"no profile matching --target {target}")
        chosen = profiles[0]
    else:
        chosen = rotation.pick_profile(cfg.profiles)
        if chosen is None:
            log.warning("all profiles exhausted their weekly quota; skipping")
            await _notify(cfg, "抢号跳过", "本周所有 profile 额度已用完", "warning")
            return {"success": False, "reason": "quota_exhausted"}

    day, daytime = resolve_book_date(chosen.book_date, datetime.now())

    async with SiteClient(cfg.base_url) as client:
        cs = ClockSync(client)
        await cs.calibrate({"doc_id": chosen.doc_id, "openid": chosen.openid})

        fire_at = cs.server_now().replace(second=0, microsecond=0) + timedelta(minutes=1)
        # When triggered at 19:59 by cron, fire_at ≈ 20:00:00 server time.
        await cs.sleep_until(fire_at - timedelta(seconds=cfg.timing.pre_poll_seconds))

        result = await grab_run(client, chosen, day, daytime, cfg.timing)

        safety_log: list[str] = []
        if result.success:
            rotation.mark_booked(cfg.profiles, chosen)
            safety_log = await reconcile(client, chosen, chosen.count, day)

    title = "抢号成功" if result.success else "抢号失败"
    body = (f"{chosen.name} | {result.slot.work_begin if result.slot else '-'}\n"
            f"code={result.code} attempts={result.attempts} dur={result.duration_ms}ms\n"
            f"{result.message}\n" + "\n".join(safety_log))
    await _notify(cfg, title, body, "active" if result.success else "timeSensitive")
    return {"success": result.success, "profile": chosen.name,
            "code": result.code, "slot": result.slot.work_begin if result.slot else None,
            "safety": safety_log}


async def _notify(cfg, title, body, level):
    if not cfg.webhooks:
        log.info("notify (no webhook configured): %s | %s", title, body)
        return
    async with httpx.AsyncClient() as hc:
        channels = notify.build(cfg.webhooks, hc)
        errs = await notify.notify_all(channels, title, body, level)
        for ch, e in zip(channels, errs):
            if e:
                log.warning("webhook %s failed: %r", ch.params.get("type") or ch.params, e)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="jxgrab")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--target", default=None, help="profile name or id; skip rotation")
    args = ap.parse_args(argv)
    out = asyncio.run(run_grab(args.config, args.target))
    return 0 if out["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

> **关于 `fire_at`：** 假设 cron 在 19:59 触发、对时后 `server_now()` 约为 19:59:5x。`fire_at = server_now().replace(second=0)+1min`，即把秒清零后 +1 分钟 → 落在下一个整点（20:00:00）。这是稳健的对齐方式，不依赖本地时钟绝对准确。若 cron 触发更早（如 19:50），需调大 lead；当前 cron 配 `59 19`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_main.py -v`
Expected: 1 passed。

- [ ] **Step 5: 跑全量测试**

Run: `pytest -v`
Expected: 全部 passed。

- [ ] **Step 6: 提交**

```bash
git add jxgrab/main.py tests/test_main.py
git commit -m "feat: main entrypoint wiring clocksync+rotation+grab+safety+notify"
```

---

### Task 11: 部署文档 + cron

**Files:**
- Create: `README.md`
- Create: `deploy/jxgrab.cron`

**Interfaces:** 无代码接口；交付部署说明。

- [ ] **Step 1: 写 `deploy/jxgrab.cron`**

```cron
# 每周一、三 19:59 触发（留 ~60s 给对时与精确等待）
59 19 * * 1,3  /opt/jxgrab/venv/bin/python /opt/jxgrab/main.py --config /opt/jxgrab/config.yaml >> /var/log/jxgrab.log 2>&1
```

- [ ] **Step 2: 写 `README.md`**

````markdown
# jxgrab — 按摩预约抢号

每周一、三 20:00 自动抢 jingxin 预约。

## 安装
```bash
git clone <repo> /opt/jxgrab && cd /opt/jxgrab
python3 -m venv venv && . venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml   # 填真实信息（gitignore，不入库）
```

## 标定（上线前必跑一次）
在真实的周一/三 19:55–20:05 之间运行，**只读，不会预约**：
```bash
python -m jxgrab.calibrate --config config.yaml
```
确认报告中的 `server_time` 解析、`slot_fields`、`schedule_count` 与设计一致；结果记入 `docs/calibration-YYYY-MM-DD.md`。

## 试运行（只读，不抢号）
```bash
python -m jxgrab.calibrate --config config.yaml
```

## 手动抢一次（跳过 cron）
```bash
python -m jxgrab --config config.yaml --target 张三
```

## 定时
```bash
crontab deploy/jxgrab.cron
```
确保服务器时区正确（`timedatectl`）。每周一、三 20:00 自动抢。

## 测试
```bash
pytest -v
```
````

- [ ] **Step 3: 提交**

```bash
git add README.md deploy/jxgrab.cron
git commit -m "docs: deployment guide + cron schedule"
```

---

## 上线后（非本计划编码任务，提醒）

1. **先标定**：跑 `calibrate.py`，把第 11 节未知项的实测结果回填到 `config.yaml`（尤其确认 `book_date` 该用 today/tomorrow/具体日期）与（必要时）`client.py`/`safety.py` 的解析。
2. **首周真跑观察日志**：第一次 cron 跑完看 `/var/log/jxgrab.log` 与 webhook 通知，确认 `code`、`slot`、`duration_ms`、safety 是否如预期。
3. **盲打升级（可选）**：若连两周都"差一点"抢到、且标定确认 `sch_id` 跨周稳定，再追加一个 Task 做 T=0 盲打优化（YAGNI，暂不实现）。
