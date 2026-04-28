"""
State Manager — persistent link status tracking across restarts.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

from .constants import STATUS_UNKNOWN

log = logging.getLogger("smoke-notifier")


class StateManager:
    """Track per-link status with JSON persistence."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self._state: Dict[str, dict] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────
    def _load(self):
        if os.path.isfile(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                log.info(f"State loaded: {len(self._state)} links from {self.state_file}")
            except (json.JSONDecodeError, IOError) as e:
                log.warning(f"Could not load state file, starting fresh: {e}")
                self._state = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log.error(f"Failed to save state: {e}")

    # ── Accessors ─────────────────────────────────────────────────
    def _default_state(self) -> dict:
        return {
            "status": STATUS_UNKNOWN,
            "last_change": None,
            "last_alert": None,
            "last_check": None,
            "changes": [],
        }

    def get(self, label: str) -> dict:
        return self._state.get(label, self._default_state())

    def get_all(self) -> Dict[str, dict]:
        return dict(self._state)

    def update(self, label: str, status: str, now_iso: str):
        """Update link status. Tracks state changes for flapping detection."""
        current = self.get(label)

        if current["status"] != status:
            changes = current.get("changes", [])
            changes.append(now_iso)
            changes = changes[-10:]  # keep last 10 transitions
            current["changes"] = changes
            current["last_change"] = now_iso
            current["status"] = status

        current["last_check"] = now_iso
        self._state[label] = current
        self.save()

    def record_alert(self, label: str, now_iso: str):
        if label in self._state:
            self._state[label]["last_alert"] = now_iso
            self.save()

    # ── Flapping & Cooldown ───────────────────────────────────────
    def is_flapping(self, label: str, max_changes: int, window_sec: int) -> bool:
        changes = self.get(label).get("changes", [])
        if len(changes) < max_changes:
            return False
        now = datetime.now()
        recent = []
        for ts in changes:
            try:
                dt = datetime.fromisoformat(ts)
                if (now - dt).total_seconds() < window_sec:
                    recent.append(dt)
            except (ValueError, TypeError):
                continue
        return len(recent) >= max_changes

    def in_cooldown(self, label: str, cooldown_sec: int) -> bool:
        last = self.get(label).get("last_alert")
        if not last:
            return False
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            return elapsed < cooldown_sec
        except (ValueError, TypeError):
            return False

    def get_downtime(self, label: str) -> Optional[timedelta]:
        last_change = self.get(label).get("last_change")
        if not last_change:
            return None
        try:
            return datetime.now() - datetime.fromisoformat(last_change)
        except (ValueError, TypeError):
            return None

    # ── Maintenance Mode ──────────────────────────────────────────
    def set_maintenance(self, label: str, duration_sec: int):
        """Set maintenance window. Use label='_global_' for all."""
        current = self.get(label) if label != "_global_" else self._state.setdefault("_global_", {})
        if duration_sec <= 0:
            current.pop("maintenance_until", None)
        else:
            expiry = datetime.now() + timedelta(seconds=duration_sec)
            current["maintenance_until"] = expiry.isoformat()

        self._state[label] = current
        self.save()

    def is_maintenance(self, label: str) -> bool:
        """Check if link (or global) is actively muted."""
        for target in ("_global_", label):
            m_until = self._state.get(target, {}).get("maintenance_until")
            if m_until:
                try:
                    expiry = datetime.fromisoformat(m_until)
                    if datetime.now() < expiry:
                        return True
                    else:
                        # Auto cleanup expired
                        self._state[target].pop("maintenance_until")
                except (ValueError, TypeError):
                    pass
        return False
