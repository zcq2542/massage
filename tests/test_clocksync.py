import time as _time
from datetime import datetime, timedelta
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
    # derive "past" from server_now() so it's genuinely past regardless of
    # the offset/epoch (offset=0 → monotonic epoch ~1970, not wall clock)
    past = cs.server_now() - timedelta(seconds=10)
    await cs.sleep_until(past)  # should not block
