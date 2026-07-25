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
