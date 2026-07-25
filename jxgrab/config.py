from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class Webhook:
    type: str
    params: dict = field(default_factory=dict)


@dataclass
class Profile:
    name: str
    openid: str
    phone: str
    count: int = 1
    doc_id: str = "22"
    slot_priorities: list[str] = field(default_factory=list)
    book_date: str = "tomorrow"  # "today" | "tomorrow" | "YYYY-MM-DD"

    @property
    def id(self) -> str:
        return f"{self.doc_id}:{self.openid}:{self.phone}"


@dataclass
class Timing:
    start_lead_seconds: int = 60
    pre_poll_seconds: float = 1.0
    poll_interval_ms: int = 50
    poll_concurrency: int = 8
    fire_concurrency: int = 3
    total_timeout_s: float = 30.0


@dataclass
class Rotation:
    enabled: bool = True
    weekly_quota: int = 1
    state_file: str = "state.json"


@dataclass
class Safety:
    dedup: bool = True
    auto_cancel_extras: bool = True


@dataclass
class Config:
    base_url: str
    profiles: list[Profile]
    webhooks: list[Webhook] = field(default_factory=list)
    timing: Timing = field(default_factory=Timing)
    rotation: Rotation = field(default_factory=Rotation)
    safety: Safety = field(default_factory=Safety)


def _sub(raw: dict, cls):
    return cls(**{k: raw[k] for k in raw if k in cls.__dataclass_fields__})


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = [Profile(**p) for p in raw.get("profiles", [])]
    webhooks = [Webhook(type=w["type"], params={k: v for k, v in w.items() if k != "type"})
                for w in raw.get("webhooks", [])]
    return Config(
        base_url=raw["base_url"],
        profiles=profiles,
        webhooks=webhooks,
        timing=_sub(raw.get("timing", {}), Timing),
        rotation=_sub(raw.get("rotation", {}), Rotation),
        safety=_sub(raw.get("safety", {}), Safety),
    )
