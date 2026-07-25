from __future__ import annotations
import json
from pathlib import Path
from datetime import date


def iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


class Rotation:
    def __init__(self, config):
        self.cfg = config.rotation
        self.path = Path(self.cfg.state_file)
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"week": iso_week(date.today()), "rotation_index": 0, "used": {}}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _reset_if_new_week(self) -> None:
        w = iso_week(date.today())
        if self.state.get("week") != w:
            self.state["week"] = w
            self.state["used"] = {}
            self.state["rotation_index"] = 0

    def pick_profile(self, profiles: list):
        if not profiles:
            return None
        if not self.cfg.enabled:
            return profiles[0]
        self._reset_if_new_week()
        n = len(profiles)
        for i in range(n):
            idx = (self.state["rotation_index"] + i) % n
            p = profiles[idx]
            if self.state["used"].get(p.id, 0) < self.cfg.weekly_quota:
                self.state["rotation_index"] = idx
                self._save()
                return p
        return None

    def mark_booked(self, profiles: list, profile) -> None:
        self._reset_if_new_week()
        self.state["used"][profile.id] = self.state["used"].get(profile.id, 0) + 1
        if profiles:
            self.state["rotation_index"] = (self.state["rotation_index"] + 1) % len(profiles)
        self._save()
