#!/usr/bin/env python3
"""
smoke-notifier v1.0.0
SmokePing RRD Monitor → Telegram Alert with Graph

Monitors SmokePing RRD files, evaluates latency/loss/jitter thresholds,
and sends alerts with PNG graphs to Telegram.

Usage:
    python3 smokeping_monitor.py [--config CONFIG] [--dry-run] [--test]

Author : BadRush
License: MIT
"""

import os
import sys
import signal
import time
import json
import logging
import subprocess
import argparse
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, List

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip3 install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip3 install PyYAML")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════
VERSION = "1.0.0"
APP_NAME = "smoke-notifier"

STATUS_OK       = "OK"
STATUS_WARN     = "WARN"
STATUS_CRIT     = "CRIT"
STATUS_DOWN     = "DOWN"
STATUS_FLAPPING = "FLAPPING"
STATUS_UNKNOWN  = "UNKNOWN"

STATUS_EMOJI = {
    STATUS_OK:       "🟢",
    STATUS_WARN:     "🟡",
    STATUS_CRIT:     "🟠",
    STATUS_DOWN:     "🔴",
    STATUS_FLAPPING: "⚠️",
    STATUS_UNKNOWN:  "⚪",
}

log = logging.getLogger(APP_NAME)


# ═══════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════
class Config:
    """Load, validate, and provide access to YAML configuration."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._raw = self._load(config_path)
        self._apply_env_overrides()
        self._validate()

    def _load(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError("Config root must be a YAML mapping")
            return data
        except FileNotFoundError:
            print(f"ERROR: Config file not found: {path}")
            print(f"  → Copy config.example.yaml to {path} and edit it.")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"ERROR: Invalid YAML syntax in {path}:\n  {e}")
            sys.exit(1)

    def _apply_env_overrides(self):
        """Override sensitive values from environment variables."""
        env_token  = os.environ.get("SMOKE_TG_TOKEN")
        env_chat   = os.environ.get("SMOKE_TG_CHAT_ID")
        env_thread = os.environ.get("SMOKE_TG_THREAD_ID")
        if env_token:
            self._raw.setdefault("telegram", {})["bot_token"] = env_token
        if env_chat:
            self._raw.setdefault("telegram", {})["chat_id"] = env_chat
        if env_thread:
            self._raw.setdefault("telegram", {})["message_thread_id"] = int(env_thread)

    def _validate(self):
        """Validate all required configuration fields."""
        errors = []

        # — Telegram
        tg = self._raw.get("telegram", {})
        if not tg.get("bot_token") or tg["bot_token"] == "YOUR_BOT_TOKEN":
            errors.append("telegram.bot_token belum diisi")
        if not tg.get("chat_id") or str(tg["chat_id"]) == "YOUR_CHAT_ID":
            errors.append("telegram.chat_id belum diisi")

        # — SmokePing paths
        sp = self._raw.get("smokeping", {})
        rrd_base = sp.get("rrd_base_path", "/var/lib/smokeping")
        if not os.path.isdir(rrd_base):
            errors.append(
                f"smokeping.rrd_base_path tidak ditemukan: {rrd_base}"
            )

        # — Links
        links = self._raw.get("links", [])
        if not links:
            errors.append("Tidak ada link yang dikonfigurasi di 'links'")

        for i, link in enumerate(links):
            if not link.get("label"):
                errors.append(f"links[{i}]: 'label' harus diisi")
            if not link.get("rrd_path"):
                errors.append(f"links[{i}]: 'rrd_path' harus diisi")
            else:
                rrd_file = os.path.join(rrd_base, link["rrd_path"])
                if not os.path.isfile(rrd_file):
                    errors.append(
                        f"links[{i}] '{link.get('label', '?')}': "
                        f"RRD file tidak ditemukan: {rrd_file}"
                    )

        if errors:
            print("═" * 55)
            print(" CONFIG ERROR — Konfigurasi tidak valid:")
            print("═" * 55)
            for e in errors:
                print(f"  ✗ {e}")
            print()
            print(f"  Edit file: {self.config_path}")
            sys.exit(1)

    # ── Property shortcuts ────────────────────────────────────────
    @property
    def telegram_token(self) -> str:
        return self._raw["telegram"]["bot_token"]

    @property
    def telegram_chat_id(self) -> str:
        return str(self._raw["telegram"]["chat_id"])

    @property
    def telegram_thread_id(self) -> Optional[int]:
        """Telegram message_thread_id for group topics. None = General/default."""
        val = self._raw.get("telegram", {}).get("message_thread_id")
        return int(val) if val is not None else None

    @property
    def rrd_base_path(self) -> str:
        return self._raw.get("smokeping", {}).get("rrd_base_path", "/var/lib/smokeping")

    @property
    def check_interval(self) -> int:
        return int(self._raw.get("smokeping", {}).get("check_interval", 60))

    @property
    def default_num_probes(self) -> int:
        return int(self._raw.get("smokeping", {}).get("num_probes", 20))

    @property
    def links(self) -> List[dict]:
        return self._raw.get("links", [])

    @property
    def graph_enabled(self) -> bool:
        return self._raw.get("graph", {}).get("enabled", True)

    @property
    def graph_duration(self) -> str:
        return self._raw.get("graph", {}).get("duration", "3h")

    @property
    def graph_width(self) -> int:
        return int(self._raw.get("graph", {}).get("width", 800))

    @property
    def graph_height(self) -> int:
        return int(self._raw.get("graph", {}).get("height", 250))

    @property
    def graph_temp_dir(self) -> str:
        return self._raw.get("graph", {}).get("temp_dir", "/tmp/smoke-notifier")

    @property
    def flapping_cooldown(self) -> int:
        return int(self._raw.get("alerts", {}).get("flapping", {}).get("cooldown", 300))

    @property
    def flapping_max_changes(self) -> int:
        return int(self._raw.get("alerts", {}).get("flapping", {}).get("max_changes", 4))

    @property
    def flapping_window(self) -> int:
        return int(self._raw.get("alerts", {}).get("flapping", {}).get("window", 600))

    @property
    def rate_limit_per_minute(self) -> int:
        return int(self._raw.get("alerts", {}).get("rate_limit", {}).get("max_per_minute", 20))

    @property
    def heartbeat_enabled(self) -> bool:
        return self._raw.get("heartbeat", {}).get("enabled", True)

    @property
    def heartbeat_time(self) -> str:
        return self._raw.get("heartbeat", {}).get("time", "07:00")

    @property
    def heartbeat_graph_duration(self) -> str:
        return self._raw.get("heartbeat", {}).get("graph_duration", "24h")

    @property
    def log_file(self) -> str:
        return self._raw.get("logging", {}).get("file", "/opt/smoke-notifier/smoke-notifier.log")

    @property
    def log_max_size_mb(self) -> int:
        return int(self._raw.get("logging", {}).get("max_size_mb", 5))

    @property
    def log_backup_count(self) -> int:
        return int(self._raw.get("logging", {}).get("backup_count", 3))

    @property
    def state_file(self) -> str:
        return self._raw.get("state_file", "/opt/smoke-notifier/state.json")


# ═══════════════════════════════════════════════════════════════════
#  State Manager — persistent state across restarts
# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
#  RRD Reader — fetch data from SmokePing RRD files
# ═══════════════════════════════════════════════════════════════════
class RRDReader:
    """Read SmokePing RRD files via rrdtool CLI."""

    @staticmethod
    def fetch(rrd_file: str, num_probes: int = 20) -> Optional[dict]:
        """
        Fetch latest data from a SmokePing RRD file.

        SmokePing DS layout:
          - median : median RTT in seconds
          - loss   : number of lost packets (NOT percentage)
          - ping1..pingN : individual sorted probe RTTs in seconds

        Returns:
            {"median_rtt": float(ms), "loss_pct": float(%), "jitter": float(ms)}
            None on failure.
        """
        try:
            result = subprocess.run(
                [
                    "rrdtool", "fetch", rrd_file, "AVERAGE",
                    "--start", "-300", "--end", "now",
                ],
                capture_output=True, text=True, timeout=10,
            )

            if result.returncode != 0:
                log.error(f"rrdtool fetch error [{rrd_file}]: {result.stderr.strip()}")
                return None

            lines = result.stdout.strip().splitlines()
            if len(lines) < 3:
                log.warning(f"rrdtool returned too few lines for {rrd_file}")
                return None

            # Header line = DS names
            ds_names = lines[0].split()

            # Find last row with at least one non-NaN value
            data_rows = []
            for line in lines[2:]:
                stripped = line.strip()
                if not stripped or ":" not in stripped:
                    continue
                raw_vals = stripped.split(":")[1].strip().split()
                # Use .strip("-") to handle "-nan" values accurately
                if any(v.lower().strip("-") != "nan" for v in raw_vals):
                    data_rows.append(stripped)

            if not data_rows:
                log.warning(f"All NaN for {rrd_file} — link likely down")
                return {"median_rtt": None, "loss_pct": 100.0, "jitter": None}

            # Parse the most recent valid row
            last_row = data_rows[-1]
            raw_values = last_row.split(":")[1].strip().split()
            values: Dict[str, Optional[float]] = {}
            for name, val in zip(ds_names, raw_values):
                try:
                    # Strip leading sign for "nan" detection
                    is_nan = val.lower().strip("-") == "nan"
                    values[name] = float(val) if not is_nan else None
                except ValueError:
                    values[name] = None

            median_sec = values.get("median")
            loss_raw   = values.get("loss")

            if median_sec is None:
                return {"median_rtt": None, "loss_pct": 100.0, "jitter": None}

            median_ms = median_sec * 1000.0
            loss_pct  = (loss_raw / num_probes * 100.0) if loss_raw is not None else 0.0

            # Jitter = standard deviation of individual probe RTTs
            probe_ms = []
            for i in range(1, num_probes + 1):
                val = values.get(f"ping{i}")
                if val is not None and val > 0:
                    probe_ms.append(val * 1000.0)

            jitter = None
            if len(probe_ms) >= 2:
                mean = sum(probe_ms) / len(probe_ms)
                variance = sum((x - mean) ** 2 for x in probe_ms) / len(probe_ms)
                jitter = round(variance ** 0.5, 2)

            return {
                "median_rtt": round(median_ms, 2),
                "loss_pct":   round(loss_pct, 1),
                "jitter":     jitter,
            }

        except FileNotFoundError:
            log.error("rrdtool binary not found. Install: apt install rrdtool")
            return None
        except subprocess.TimeoutExpired:
            log.error(f"rrdtool fetch timeout for {rrd_file}")
            return None
        except Exception as e:
            log.error(f"Failed to read RRD {rrd_file}: {e}")
            return None


# ═══════════════════════════════════════════════════════════════════
#  Graph Generator — produce PNG graphs from RRD data
# ═══════════════════════════════════════════════════════════════════
class GraphGenerator:
    """Generate SmokePing-style PNG graphs via rrdtool graph."""

    DURATION_LABELS = {
        "1h":  "Last 1 Hour",
        "3h":  "Last 3 Hours",
        "6h":  "Last 6 Hours",
        "12h": "Last 12 Hours",
        "24h": "Last 24 Hours",
    }

    def __init__(self, config: Config):
        self.config = config
        os.makedirs(config.graph_temp_dir, exist_ok=True)

    def _safe_filename(self, label: str) -> str:
        safe = label.replace(" ", "_").replace("/", "-").replace("(", "").replace(")", "")
        return "".join(c for c in safe if c.isalnum() or c in "_-")

    def generate(self, link_cfg: dict, duration: str = None) -> Optional[str]:
        """
        Generate a PNG graph for a link.
        Returns: absolute path to PNG file, or None on failure.
        """
        if not self.config.graph_enabled:
            return None

        duration   = duration or self.config.graph_duration
        rrd_file   = os.path.join(self.config.rrd_base_path, link_cfg["rrd_path"])
        num_probes = link_cfg.get("num_probes", self.config.default_num_probes)
        warn_rtt   = link_cfg.get("warn_rtt", 30)
        crit_rtt   = link_cfg.get("crit_rtt", 80)

        safe_name = self._safe_filename(link_cfg["label"])
        png_path  = os.path.join(
            self.config.graph_temp_dir, f"{safe_name}_{duration}.png"
        )

        title = (
            f"{link_cfg['label']} — "
            f"{self.DURATION_LABELS.get(duration, duration)}"
        )

        # Build rrdtool graph command
        cmd = [
            "rrdtool", "graph", png_path,
            "--start", f"-{duration}",
            "--end", "now",
            "--width",  str(self.config.graph_width),
            "--height", str(self.config.graph_height),
            "--title",  title,
            "--vertical-label", "RTT (ms)",
            "--slope-mode",
            "--alt-autoscale-max",
            "--lower-limit", "0",
            "--rigid",
            # Dark theme colors
            "--color", "BACK#1a1a2e",
            "--color", "CANVAS#16213e",
            "--color", "FONT#e0e0e0",
            "--color", "GRID#333355",
            "--color", "MGRID#555577",
            "--color", "AXIS#888899",
            "--color", "ARROW#888899",
            "--font", "DEFAULT:9",
            "--font", "TITLE:11:Bold",
            "--border", "1",
            # Data definitions
            f"DEF:median_raw={rrd_file}:median:AVERAGE",
            f"DEF:loss_raw={rrd_file}:loss:AVERAGE",
            # Convert median from seconds to ms
            "CDEF:median_ms=median_raw,1000,*",
            # Convert loss from packet count to percentage
            f"CDEF:loss_pct=loss_raw,{num_probes},/,100,*",
            # Plot loss as semi-transparent red area
            "AREA:loss_pct#FF000050:Loss (%)\\n",
            # Plot RTT as green line
            "LINE2:median_ms#00CC00:RTT median (ms)\\n",
            # Threshold lines
            f"HRULE:{warn_rtt}#FFAA00:Warning  ({warn_rtt}ms):dashes=5,3",
            f"HRULE:{crit_rtt}#FF4444:Critical ({crit_rtt}ms)\\n:dashes=5,3",
            # Statistics
            "GPRINT:median_ms:LAST:  Current\\: %6.2lf ms",
            "GPRINT:median_ms:AVERAGE:  Avg\\: %6.2lf ms",
            "GPRINT:median_ms:MAX:  Max\\: %6.2lf ms\\n",
            "GPRINT:loss_pct:LAST:  Loss now\\: %5.1lf %%\\n",
            "COMMENT: \\n",
            f"COMMENT:  Generated by {APP_NAME} v{VERSION}\\r",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                log.error(f"rrdtool graph error: {result.stderr.strip()}")
                return None

            if os.path.isfile(png_path):
                log.debug(f"Graph generated: {png_path}")
                return png_path

            log.warning(f"Graph file not created: {png_path}")
            return None

        except FileNotFoundError:
            log.error("rrdtool binary not found for graph generation")
            return None
        except subprocess.TimeoutExpired:
            log.error("rrdtool graph timed out")
            return None
        except Exception as e:
            log.error(f"Graph generation failed: {e}")
            return None

    def cleanup(self, png_path: str):
        """Remove temporary PNG after sending."""
        try:
            if png_path and os.path.isfile(png_path):
                os.remove(png_path)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════
#  Telegram Notifier — send alerts with retry & rate limiting
# ═══════════════════════════════════════════════════════════════════
class TelegramNotifier:
    """Telegram Bot API wrapper with retries and rate limiting."""

    MAX_CAPTION = 1024  # Telegram caption limit

    def __init__(self, token: str, chat_id: str,
                 thread_id: Optional[int] = None,
                 max_retries: int = 3, rate_limit: int = 20):
        self.token       = token
        self.chat_id     = chat_id
        self.thread_id   = thread_id
        self.max_retries = max_retries
        self.rate_limit  = rate_limit
        self._send_times: List[float] = []
        self._base_url   = f"https://api.telegram.org/bot{token}"

    def _rate_ok(self) -> bool:
        now = time.time()
        self._send_times = [t for t in self._send_times if now - t < 60]
        return len(self._send_times) < self.rate_limit

    def _record(self):
        self._send_times.append(time.time())

    def _truncate(self, text: str, limit: int) -> str:
        """Truncate text to Telegram limit, preserving HTML tags."""
        if len(text) <= limit:
            return text
        return text[: limit - 20] + "\n\n<i>…truncated</i>"

    # ── Send methods ──────────────────────────────────────────────
    def send_message(self, text: str) -> bool:
        if not self._rate_ok():
            log.warning("Telegram rate limit hit — message queued/skipped")
            return False

        for attempt in range(1, self.max_retries + 1):
            try:
                payload = {
                    "chat_id":    self.chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                }
                if self.thread_id is not None:
                    payload["message_thread_id"] = self.thread_id
                r = requests.post(
                    f"{self._base_url}/sendMessage",
                    json=payload,
                    timeout=10,
                )
                r.raise_for_status()
                self._record()
                log.info("Telegram message sent")
                return True
            except Exception as e:
                delay = 2 ** attempt
                log.warning(
                    f"Telegram attempt {attempt}/{self.max_retries}: {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(delay)

        log.error("Telegram send_message failed after all retries")
        return False

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        if not self._rate_ok():
            log.warning("Telegram rate limit hit — photo skipped")
            return False

        caption = self._truncate(caption, self.MAX_CAPTION)

        for attempt in range(1, self.max_retries + 1):
            try:
                form_data = {
                    "chat_id":    self.chat_id,
                    "caption":    caption,
                    "parse_mode": "HTML",
                }
                if self.thread_id is not None:
                    form_data["message_thread_id"] = self.thread_id
                with open(photo_path, "rb") as photo_file:
                    r = requests.post(
                        f"{self._base_url}/sendPhoto",
                        data=form_data,
                        files={"photo": photo_file},
                        timeout=30,
                    )
                r.raise_for_status()
                self._record()
                log.info("Telegram photo sent")
                return True
            except Exception as e:
                delay = 2 ** attempt
                log.warning(
                    f"Telegram photo attempt {attempt}/{self.max_retries}: {e}"
                )
                if attempt < self.max_retries:
                    time.sleep(delay)

        log.error("Telegram photo failed — falling back to text")
        return self.send_message(caption)

    def send_alert(self, message: str, graph_path: Optional[str] = None) -> bool:
        """Send alert: photo+caption if graph available, text otherwise."""
        if graph_path and os.path.isfile(graph_path):
            return self.send_photo(graph_path, caption=message)
        return self.send_message(message)

    def test_connection(self) -> bool:
        """Verify bot token is valid."""
        try:
            r = requests.get(f"{self._base_url}/getMe", timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("ok"):
                bot_name = data["result"].get("username", "?")
                log.info(f"Telegram bot connected: @{bot_name}")
                return True
            return False
        except Exception as e:
            log.error(f"Telegram connection test failed: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════
#  Alert Builder — format alert messages with emoji & detail
# ═══════════════════════════════════════════════════════════════════
class AlertBuilder:
    """Build HTML-formatted alert messages for Telegram."""

    @staticmethod
    def _format_duration(td: timedelta) -> str:
        total = int(td.total_seconds())
        if total >= 86400:
            d, rem = divmod(total, 86400)
            h, rem = divmod(rem, 3600)
            m = rem // 60
            return f"{d}h {h}j {m}m"
        if total >= 3600:
            h, rem = divmod(total, 3600)
            m = rem // 60
            return f"{h}j {m}m"
        if total >= 60:
            return f"{total // 60} menit"
        return f"{total} detik"

    @staticmethod
    def build_alert(
        link_cfg: dict,
        data: Optional[dict],
        status: str,
        prev_status: str,
        downtime: Optional[timedelta] = None,
    ) -> str:
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        emoji = STATUS_EMOJI.get(status, "⚪")
        prev_emoji = STATUS_EMOJI.get(prev_status, "⚪")
        label = link_cfg["label"]

        # Header
        if (status == STATUS_OK
                and prev_status in (STATUS_WARN, STATUS_CRIT, STATUS_DOWN, STATUS_FLAPPING)):
            header = f"{emoji} <b>[RECOVERED] {label}</b>"
        else:
            header = f"{emoji} <b>[{status}] {label}</b>"

        # Detail body
        if status == STATUS_DOWN:
            detail = "❌ Tidak ada data — link down / RRD kosong"
        elif status == STATUS_FLAPPING:
            detail = "⚠️ Link tidak stabil (flapping) — alert di-suppress sementara"
        elif data:
            rtt    = data.get("median_rtt", "N/A")
            loss   = data.get("loss_pct", "N/A")
            jitter = data.get("jitter")
            detail = (
                f"📊 RTT Median : <b>{rtt} ms</b>  "
                f"(warn≥{link_cfg.get('warn_rtt')} / crit≥{link_cfg.get('crit_rtt')})\n"
                f"📉 Packet Loss: <b>{loss}%</b>   "
                f"(warn≥{link_cfg.get('warn_loss')}% / crit≥{link_cfg.get('crit_loss')}%)"
            )
            if jitter is not None:
                detail += f"\n📐 Jitter     : <b>{jitter} ms</b>"
                wj = link_cfg.get("warn_jitter")
                cj = link_cfg.get("crit_jitter")
                if wj or cj:
                    detail += f"  (warn≥{wj or '-'} / crit≥{cj or '-'})"
        else:
            detail = "⚠️ Data tidak tersedia"

        # Downtime for recovery
        downtime_line = ""
        if downtime and status == STATUS_OK:
            dur = AlertBuilder._format_duration(downtime)
            downtime_line = f"\n⏱️ Durasi     : <b>{dur}</b>"

        transition = f"{prev_emoji}{prev_status} → {emoji}{status}"

        return (
            f"{header}\n"
            f"─────────────────────\n"
            f"{detail}{downtime_line}\n"
            f"🔄 Status    : {transition}\n"
            f"🕐 Waktu     : {ts}"
        )

    @staticmethod
    def build_heartbeat(states: Dict[str, dict], links: List[dict]) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ok = sum(
            1 for l in links
            if states.get(l["label"], {}).get("status") == STATUS_OK
        )
        total = len(links)

        lines = [
            f"💓 <b>Daily Heartbeat — {APP_NAME} v{VERSION}</b>",
            "─────────────────────",
            f"📅 {ts}",
            "",
        ]

        for link in links:
            label  = link["label"]
            st     = states.get(label, {})
            status = st.get("status", STATUS_UNKNOWN)
            emoji  = STATUS_EMOJI.get(status, "⚪")
            lines.append(f"  {emoji} {label}: <b>{status}</b>")

        lines.append("")
        lines.append(f"📊 Summary: <b>{ok}/{total}</b> links OK")
        lines.append(f"🤖 {APP_NAME} v{VERSION} running")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  Status Evaluator
# ═══════════════════════════════════════════════════════════════════
class StatusEvaluator:
    """Evaluate link health from RRD metrics."""

    @staticmethod
    def evaluate(data: Optional[dict], link_cfg: dict) -> str:
        if data is None:
            return STATUS_DOWN
        if data.get("median_rtt") is None:
            return STATUS_DOWN

        rtt  = data["median_rtt"]
        loss = data["loss_pct"]

        # Critical
        if loss >= link_cfg.get("crit_loss", 20):
            return STATUS_CRIT
        if rtt >= link_cfg.get("crit_rtt", 80):
            return STATUS_CRIT

        # Warning
        if loss >= link_cfg.get("warn_loss", 5):
            return STATUS_WARN
        if rtt >= link_cfg.get("warn_rtt", 30):
            return STATUS_WARN

        # Jitter thresholds (optional)
        jitter = data.get("jitter")
        if jitter is not None:
            cj = link_cfg.get("crit_jitter")
            wj = link_cfg.get("warn_jitter")
            if cj is not None and jitter >= cj:
                return STATUS_CRIT
            if wj is not None and jitter >= wj:
                return STATUS_WARN

        return STATUS_OK


# ═══════════════════════════════════════════════════════════════════
#  Main Monitor
# ═══════════════════════════════════════════════════════════════════
class SmokePingMonitor:
    """Main monitoring loop with flapping detection and heartbeat."""

    def __init__(self, config: Config, dry_run: bool = False):
        self.config   = config
        self.dry_run  = dry_run
        self.state    = StateManager(config.state_file)
        self.notifier = TelegramNotifier(
            config.telegram_token,
            config.telegram_chat_id,
            thread_id=config.telegram_thread_id,
            rate_limit=config.rate_limit_per_minute,
        )
        self.grapher   = GraphGenerator(config)
        self.evaluator = StatusEvaluator()
        self.builder   = AlertBuilder()
        self._running  = True
        self._last_heartbeat_date: Optional[str] = None

    def stop(self, *_args):
        """Signal handler — graceful shutdown."""
        log.info("Shutdown signal received, finishing current cycle...")
        self._running = False

    # ── Check a single link ───────────────────────────────────────
    def _check_link(self, link_cfg: dict):
        label      = link_cfg["label"]
        rrd_file   = os.path.join(self.config.rrd_base_path, link_cfg["rrd_path"])
        num_probes = link_cfg.get("num_probes", self.config.default_num_probes)

        data   = RRDReader.fetch(rrd_file, num_probes)
        status = self.evaluator.evaluate(data, link_cfg)

        prev_state  = self.state.get(label)
        prev_status = prev_state.get("status", STATUS_UNKNOWN)
        now_iso     = datetime.now().isoformat()

        # Logging
        if data and data.get("median_rtt") is not None:
            jit = f" | Jitter: {data['jitter']} ms" if data.get("jitter") else ""
            log.info(
                f"{label:30s} | RTT: {data['median_rtt']:>8} ms | "
                f"Loss: {data['loss_pct']:>5}%{jit} | "
                f"{prev_status} → {status}"
            )
        else:
            log.info(f"{label:30s} | DOWN | {prev_status} → {status}")

        # ── First run: set initial state ──────────────────────────
        if prev_status == STATUS_UNKNOWN:
            log.info(f"  ↳ Initial state: {status}")
            self.state.update(label, status, now_iso)
            # Alert if first state is non-OK (important to know!)
            if status != STATUS_OK:
                msg = self.builder.build_alert(
                    link_cfg, data, status, STATUS_OK
                )
                if not self.dry_run:
                    graph_path = self.grapher.generate(link_cfg)
                    self.notifier.send_alert(msg, graph_path)
                    if graph_path:
                        self.grapher.cleanup(graph_path)
                    self.state.record_alert(label, now_iso)
                else:
                    log.info(f"  [DRY-RUN] Would send initial alert")
            return

        # ── No change → skip ─────────────────────────────────────
        if status == prev_status:
            self.state.update(label, status, now_iso)
            return

        # ── Status changed → evaluate alert ──────────────────────
        # Flapping check
        if self.state.is_flapping(
            label, self.config.flapping_max_changes, self.config.flapping_window
        ):
            if prev_status != STATUS_FLAPPING:
                log.warning(f"  ↳ {label}: FLAPPING detected — suppressing")
                msg = self.builder.build_alert(
                    link_cfg, data, STATUS_FLAPPING, prev_status
                )
                if not self.dry_run:
                    self.notifier.send_message(msg)
                    self.state.record_alert(label, now_iso)
                self.state.update(label, STATUS_FLAPPING, now_iso)
            return

        # Cooldown check
        if self.state.in_cooldown(label, self.config.flapping_cooldown):
            log.debug(f"  ↳ {label}: In cooldown — alert deferred")
            self.state.update(label, status, now_iso)
            return

        # Build alert
        downtime = None
        if status == STATUS_OK:
            downtime = self.state.get_downtime(label)

        msg = self.builder.build_alert(
            link_cfg, data, status, prev_status, downtime
        )

        if self.dry_run:
            log.info(f"  [DRY-RUN] Would send:\n{msg}")
        else:
            graph_path = self.grapher.generate(link_cfg)
            self.notifier.send_alert(msg, graph_path)
            if graph_path:
                self.grapher.cleanup(graph_path)
            self.state.record_alert(label, now_iso)

        self.state.update(label, status, now_iso)

    # ── Heartbeat ─────────────────────────────────────────────────
    def _check_heartbeat(self):
        if not self.config.heartbeat_enabled:
            return

        now   = datetime.now()
        today = now.strftime("%Y-%m-%d")

        if self._last_heartbeat_date == today:
            return

        try:
            hh, mm = map(int, self.config.heartbeat_time.split(":"))
        except ValueError:
            return

        if now.hour != hh or now.minute < mm:
            return

        self._last_heartbeat_date = today

        msg = self.builder.build_heartbeat(
            self.state.get_all(), self.config.links
        )

        if self.dry_run:
            log.info(f"[DRY-RUN] Heartbeat:\n{msg}")
            return

        self.notifier.send_message(msg)

        # Send 24h overview graphs
        for link_cfg in self.config.links:
            graph_path = self.grapher.generate(
                link_cfg, duration=self.config.heartbeat_graph_duration
            )
            if graph_path:
                caption = f"📊 24h Overview — {link_cfg['label']}"
                self.notifier.send_photo(graph_path, caption)
                self.grapher.cleanup(graph_path)
                time.sleep(1)  # pace Telegram API

        log.info("Daily heartbeat sent")

    # ── Main loop ─────────────────────────────────────────────────
    def run(self):
        log.info("=" * 55)
        log.info(f" {APP_NAME} v{VERSION} — starting")
        log.info(f" Links      : {len(self.config.links)}")
        log.info(f" Interval   : {self.config.check_interval}s")
        log.info(f" Graph      : {'ON' if self.config.graph_enabled else 'OFF'} ({self.config.graph_duration})")
        log.info(f" Heartbeat  : {self.config.heartbeat_time if self.config.heartbeat_enabled else 'OFF'}")
        if self.dry_run:
            log.info(" Mode       : DRY-RUN (no alerts sent)")
        log.info("=" * 55)

        # Test Telegram on startup
        if not self.dry_run:
            if not self.notifier.test_connection():
                log.error("Cannot connect to Telegram — check bot_token in config")
                sys.exit(1)

        # ── Loop ──────────────────────────────────────────────────
        while self._running:
            try:
                for link_cfg in self.config.links:
                    if not self._running:
                        break
                    self._check_link(link_cfg)

                self._check_heartbeat()

            except Exception as e:
                log.error(f"Error in main loop: {e}", exc_info=True)

            # Sleep in 1s increments for responsive shutdown
            for _ in range(self.config.check_interval):
                if not self._running:
                    break
                time.sleep(1)

        # Graceful exit
        self.state.save()
        log.info(f"{APP_NAME} stopped gracefully")


# ═══════════════════════════════════════════════════════════════════
#  Logging Setup
# ═══════════════════════════════════════════════════════════════════
def setup_logging(config: Config):
    fmt     = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    log_dir = os.path.dirname(config.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            config.log_file,
            maxBytes=config.log_max_size_mb * 1024 * 1024,
            backupCount=config.log_backup_count,
        ),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )


# ═══════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{VERSION} — SmokePing RRD Monitor → Telegram Alert"
    )
    parser.add_argument(
        "-c", "--config",
        default="/opt/smoke-notifier/config.yaml",
        help="Path to config file (default: /opt/smoke-notifier/config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run monitoring loop without sending Telegram alerts",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send test message to Telegram and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} v{VERSION}",
    )
    args = parser.parse_args()

    # Load config
    config = Config(args.config)
    setup_logging(config)

    # --test mode
    if args.test:
        notifier = TelegramNotifier(
            config.telegram_token, config.telegram_chat_id,
            thread_id=config.telegram_thread_id,
        )
        if notifier.test_connection():
            notifier.send_message(
                f"✅ <b>{APP_NAME} v{VERSION}</b>\n"
                f"─────────────────────\n"
                f"Test message berhasil!\n"
                f"Monitoring <b>{len(config.links)}</b> links.\n"
                f"Graph: {'✅' if config.graph_enabled else '❌'}\n"
                f"Heartbeat: {config.heartbeat_time if config.heartbeat_enabled else '❌'}"
            )
            print("✅ Test message sent to Telegram!")
        else:
            print("❌ Cannot connect to Telegram. Check bot_token.")
            sys.exit(1)
        return

    # Create monitor
    monitor = SmokePingMonitor(config, dry_run=args.dry_run)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, monitor.stop)
    signal.signal(signal.SIGINT,  monitor.stop)

    monitor.run()


if __name__ == "__main__":
    main()
