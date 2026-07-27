from __future__ import annotations
import argparse, asyncio, json, sys
from datetime import datetime, timedelta

from .config import load_config
from .client import SiteClient


async def probe(client: SiteClient, profile, day: str, daytime: str) -> dict:
    q = {"doc_id": profile.doc_id, "openid": profile.openid, "day": day, "daytime": daytime}
    report: dict = {"profile": profile.name, "day": day}
    try:
        st = await client.get_server_time(q)
        report["server_time"] = st.strftime("%Y-%m-%d %H:%M:%S")
        report["server_time_raw_note"] = "confirm exact response shape vs parse_server_time"
    except Exception as e:  # noqa: BLE001
        report["server_time_error"] = repr(e)
    try:
        report["time_config"] = await client.get_time_config(q)
    except Exception as e:  # noqa: BLE001
        report["time_config_error"] = repr(e)
    try:
        raw = await client.get_schedule_raw(q)
        report["schedule_query"] = q
        report["schedule_raw"] = json.dumps(raw, ensure_ascii=False)[:1000]
        sched = raw if isinstance(raw, list) else []
        report["schedule_count"] = len(sched)
        report["first_slot"] = sched[0] if sched else None
        report["slot_fields"] = list(sched[0].keys()) if sched else []
    except Exception as e:  # noqa: BLE001
        report["schedule_error"] = repr(e)
    return report


def _candidate_dates(today: datetime) -> list[tuple[str, str]]:
    days = [today, today + timedelta(days=1), today + timedelta(days=2)]
    return [(d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d")) for d in days]


async def run(config_path: str, doc_id: str | None) -> list[dict]:
    cfg = load_config(config_path)
    async with SiteClient(cfg.base_url, timeout=6.0) as client:
        # use first profile for probing (or derive a synthetic one by doc_id)
        profiles = cfg.profiles or []
        if doc_id and not profiles:
            from .config import Profile
            profiles = [Profile(name="(probe)", openid="1", phone="13800000000", doc_id=doc_id)]
        today = datetime.now()
        reports = []
        for p in profiles[:1]:
            for day, daytime in _candidate_dates(today):
                r = await probe(client, p, day, daytime)
                reports.append(r)
        return reports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="read-only calibration probe (never submits)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--doc-id", default=None)
    args = ap.parse_args(argv)
    reports = asyncio.run(run(args.config, args.doc_id))
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
