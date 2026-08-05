from __future__ import annotations
import argparse, asyncio, logging, sys
from datetime import datetime, timedelta

import httpx

from .config import load_config
from .client import SiteClient
from .clocksync import ClockSync
from .rotation import Rotation
from .grabber import run as grab_run
from .safety import reconcile
from . import notify

log = logging.getLogger("jxgrab")


def resolve_book_date(spec: str, today: datetime) -> tuple[str, str]:
    if spec in ("today",):
        d = today
    elif spec in ("tomorrow",):
        d = today + timedelta(days=1)
    else:
        d = datetime.strptime(spec, "%Y-%m-%d")
    s = d.strftime("%Y-%m-%d")
    return s, s


def _today_at(server_now: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return server_now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


async def run_grab(config_path: str, target: str | None) -> dict:
    cfg = load_config(config_path)
    rotation = Rotation(cfg)
    log.info("config: profiles=%s book_dates=%s release_time=%s quota=%d webhooks=%d auto_cancel_extras=%s",
             [p.name for p in cfg.profiles], [p.book_date for p in cfg.profiles],
             cfg.timing.release_time, cfg.rotation.weekly_quota,
             len(cfg.webhooks), cfg.safety.auto_cancel_extras)
    log.info("rotation state: %s", rotation.state)
    profiles = cfg.profiles

    if target:
        profiles = [p for p in profiles if p.name == target or p.id == target]
        if not profiles:
            raise SystemExit(f"no profile matching --target {target}")
        chosen = profiles[0]
    else:
        chosen = rotation.pick_profile(cfg.profiles)
        if chosen is None:
            log.warning("all profiles exhausted their weekly quota; skipping")
            await _notify(cfg, "抢号跳过", "本周所有 profile 额度已用完", "warning")
            return {"success": False, "reason": "quota_exhausted"}

    day, daytime = resolve_book_date(chosen.book_date, datetime.now())

    async with SiteClient(cfg.base_url) as client:
        cs = ClockSync(client)
        await cs.calibrate({"doc_id": chosen.doc_id, "openid": chosen.openid})

        fire_at = _today_at(cs.server_now(), cfg.timing.release_time)
        if cs.server_now() >= fire_at + timedelta(seconds=1):
            log.error("started after release time %s (server now %s); firing immediately",
                      cfg.timing.release_time, cs.server_now().isoformat())
        else:
            await cs.sleep_until(fire_at - timedelta(seconds=cfg.timing.pre_poll_seconds))

        log.info("firing grab: profile=%s daytime=%s server_now=%s",
                 chosen.name, daytime, cs.server_now().isoformat())
        result = await grab_run(client, chosen, day, daytime, cfg.timing)

        safety_log: list[str] = []
        if result.success:
            rotation.mark_booked(cfg.profiles, chosen)
            safety_log = await reconcile(client, chosen, chosen.count, day,
                                         keep_sch_id=str(result.slot.sch_id) if result.slot else None)

    log.info("RESULT success=%s profile=%s code=%s slot=%s attempts=%s dur=%sms msg=%r safety=%s",
             result.success, chosen.name, result.code,
             result.slot.work_begin if result.slot else None,
             result.attempts, result.duration_ms, result.message, safety_log)
    title = "抢号成功" if result.success else "抢号失败"
    body = (f"{chosen.name} | {result.slot.work_begin if result.slot else '-'}\n"
            f"code={result.code} attempts={result.attempts} dur={result.duration_ms}ms\n"
            f"{result.message}\n" + "\n".join(safety_log))
    await _notify(cfg, title, body, "active" if result.success else "timeSensitive")
    return {"success": result.success, "profile": chosen.name,
            "code": result.code, "slot": result.slot.work_begin if result.slot else None,
            "safety": safety_log}


async def _notify(cfg, title, body, level):
    if not cfg.webhooks:
        log.info("notify (no webhook configured): %s | %s", title, body)
        return
    async with httpx.AsyncClient() as hc:
        channels = notify.build(cfg.webhooks, hc)
        results = await notify.notify_all(channels, title, body, level)
        for ch, res in zip(channels, results):
            if res.exception is not None:
                log.warning("webhook %s failed: %r", ch.params.get("type") or ch.params, res.exception)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("jxgrab").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # silence per-request INFO noise
    ap = argparse.ArgumentParser(prog="jxgrab")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--target", default=None, help="profile name or id; skip rotation")
    args = ap.parse_args(argv)
    out = asyncio.run(run_grab(args.config, args.target))
    return 0 if out["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
