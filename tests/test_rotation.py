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

def _cfg_with_state(tmp_path, fname):
    # build a minimal config-like object exposing .rotation
    sf = str(tmp_path / fname)
    class R:
        enabled = True; weekly_quota = 1; state_file = sf
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
