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

def test_rank_matches_hhmm_priority_against_hhmmss_slots():
    # site returns work_begin as "HH:MM:SS"; priorities written as "HH:MM"
    slots = parse([
        {"sch_id": 1, "work_begin": "11:00:00"},
        {"sch_id": 2, "work_begin": "11:30:00"},
    ])
    ranked = rank_by_priority(slots, ["11:30", "11:00"])
    assert ranked[0].sch_id == "2"
    assert ranked[1].sch_id == "1"
