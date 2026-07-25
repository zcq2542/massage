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
