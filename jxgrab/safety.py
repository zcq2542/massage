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
