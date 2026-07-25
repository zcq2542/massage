from __future__ import annotations
from .config import Safety


def _record_id(rec) -> str:
    for k in ("record_id", "id", "rec_id"):
        if rec.get(k):
            return str(rec[k])
    return ""


async def reconcile(client, profile, expected_count: int, day: str,
                    keep_sch_id: str | None = None,
                    safety: Safety | None = None) -> list[str]:
    """If today's bookings exceed expected_count, cancel the extras (keep earliest).

    Keeps by IDENTITY (history ordering is unverified — spec §11): never cancels
    the slot we just booked (``keep_sch_id``). Fills up to ``expected_count``
    from the rest, cancels the remainder.
    """
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

    # Keep by IDENTITY (history ordering is unverified — spec §11): never cancel
    # the slot we just booked. Protect keep_sch_id, fill up to expected_count
    # from the rest, cancel the remainder.
    protected = [r for r in history
                 if keep_sch_id is not None and isinstance(r, dict)
                 and str(r.get("sch_id", "")) == keep_sch_id]
    others = [r for r in history if r not in protected]
    slots_needed = max(0, expected_count - len(protected))
    cancel = others[slots_needed:]          # keep others[:slots_needed], cancel rest
    for rec in cancel:
        rid = _record_id(rec)
        if not rid:
            continue
        try:
            await client.cancel_record({**q, "record_id": rid})
            log.append(f"safety: cancelled extra record {rid}")
        except Exception as e:  # noqa: BLE001
            log.append(f"safety: cancel {rid} failed: {e!r}")
    return log
