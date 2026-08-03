from __future__ import annotations
import asyncio, logging, time
from dataclasses import dataclass

from .slots import Slot, parse, rank_by_priority

log = logging.getLogger("jxgrab")

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


def _err_body(e: BaseException) -> str:
    """Best-effort response body from an httpx error (for diagnostics)."""
    resp = getattr(e, "response", None)
    return (resp.text[:300] if hasattr(resp, "text") else "")


async def _poll_once(client, q: dict):
    try:
        return await client.get_schedule(q)
    except Exception as e:  # noqa: BLE001
        log.debug("get_schedule error daytime=%s: %r %s", q.get("daytime"), e, _err_body(e))
        return None


async def _first_nonempty_schedule(client, q: dict, timing):
    deadline = time.monotonic() + timing.total_timeout_s
    interval = timing.poll_interval_ms / 1000
    saw_ok = False
    rounds = 0
    while time.monotonic() < deadline:
        rounds += 1
        results = await asyncio.gather(*[asyncio.create_task(_poll_once(client, q))
                                        for _ in range(timing.poll_concurrency)])
        for r in results:
            if r is None:
                continue
            saw_ok = True
            if r:
                return r
        await asyncio.sleep(interval)
    log.warning("poll exhausted after %d rounds / %ds (saw_ok=%s)", rounds, timing.total_timeout_s, saw_ok)
    return "transport_error" if not saw_ok else "no_slots"


async def run(client, profile, day: str, daytime: str, timing) -> GrabResult:
    start = time.monotonic()
    base_q = {"doc_id": profile.doc_id, "openid": profile.openid, "day": day, "daytime": daytime}

    raw = await _first_nonempty_schedule(client, base_q, timing)
    duration = int((time.monotonic() - start) * 1000)
    if raw == "transport_error":
        log.error("abort: site unreachable (all polls errored) after %dms", duration)
        return GrabResult(False, duration_ms=duration,
                          message="timeout: site unreachable (all polls errored)")
    if not isinstance(raw, list) or not raw:
        log.warning("abort: no slots for daytime=%s after %dms", daytime, duration)
        return GrabResult(False, duration_ms=duration, message="timeout: no slots released")

    ranked = rank_by_priority(parse(raw), profile.slot_priorities)
    log.info("found %d slot(s) for %s in %dms; try order=%s",
             len(ranked), daytime, duration, [s.work_begin for s in ranked])

    result = GrabResult(False, duration_ms=duration)
    fired: set[str] = set()
    for slot in ranked:
        if slot.sch_id in fired:
            continue
        fired.add(slot.sch_id)
        result.attempts += 1
        q = {**base_q, "name": profile.name, "phone": profile.phone,
             "record_number": profile.count, "sch_id": slot.sch_id}
        log.debug("SaveRecord request sch_id=%s q=%s", slot.sch_id, q)
        try:
            resp = await client.save_record(q)
        except Exception as e:  # noqa: BLE001
            log.warning("SaveRecord sch_id=%s exception: %r body=%s", slot.sch_id, e, _err_body(e))
            result.message = f"save_record error: {e!r}"
            continue
        log.debug("SaveRecord sch_id=%s resp=%s", slot.sch_id, resp)
        code = str(resp.get("code", ""))
        result.code = code
        if is_success_code(code):
            result.success = True
            result.slot = slot
            result.message = "ok"
            log.info("SaveRecord SUCCESS sch_id=%s code=%s slot=%s~%s",
                     slot.sch_id, code, slot.work_begin, slot.work_end)
            break
        if code in _TERMINAL_FAIL:
            result.message = f"terminal code {code} (mes={resp.get('mes')})"
            log.info("SaveRecord TERMINAL sch_id=%s code=%s mes=%s", slot.sch_id, code, resp.get("mes"))
            break
        log.info("SaveRecord sch_id=%s code=%s -> trying next priority", slot.sch_id, code)
        # code == "-2" (slot taken) or unknown → try next priority slot

    result.duration_ms = int((time.monotonic() - start) * 1000)
    if not result.success and not result.message:
        result.message = f"all {result.attempts} attempt(s) returned non-success code (last={result.code})"
    return result
