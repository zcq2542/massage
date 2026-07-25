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
