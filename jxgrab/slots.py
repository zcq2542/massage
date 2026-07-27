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
    # Site returns work_begin as "HH:MM:SS"; allow priorities to be "HH:MM".
    def _hhmm(t: str) -> str:
        return (t or "")[:5]
    prio = {_hhmm(p): i for i, p in enumerate(priorities)}
    matched = [s for s in slots if _hhmm(s.work_begin) in prio]
    matched.sort(key=lambda s: prio[_hhmm(s.work_begin)])
    rest = sorted([s for s in slots if _hhmm(s.work_begin) not in prio], key=lambda s: s.work_begin)
    return matched + rest
