"""
Configuration loader with YAML + .env + environment variable override support.

Priority: .env file → OS env vars → config.yaml defaults
"""

import os
import sys
from typing import Optional, List

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip3 install PyYAML")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    # Graceful fallback — .env support is optional
    def load_dotenv(*args, **kwargs):
        pass


class Config:
    """Load, validate, and provide access to YAML configuration with .env support."""

    # ── Environment variable → config path mapping ────────────────
    # Format: ENV_KEY → (yaml_section, yaml_key[, type_cast])
    ENV_MAP = {
        "SMOKE_TG_TOKEN":        ("telegram", "bot_token"),
        "SMOKE_TG_CHAT_ID":      ("telegram", "chat_id"),
        "SMOKE_TG_THREAD_ID":    ("telegram", "message_thread_id", int),
        "SMOKE_RRD_BASE_PATH":   ("smokeping", "rrd_base_path"),
        "SMOKE_CHECK_INTERVAL":  ("smokeping", "check_interval", int),
        "SMOKE_NUM_PROBES":      ("smokeping", "num_probes", int),
        "SMOKE_GRAPH_ENABLED":   ("graph", "enabled", lambda v: v.lower() in ("true", "1", "yes")),
        "SMOKE_GRAPH_DURATION":  ("graph", "duration"),
        "SMOKE_GRAPH_WIDTH":     ("graph", "width", int),
        "SMOKE_GRAPH_HEIGHT":    ("graph", "height", int),
        "SMOKE_GRAPH_TEMP_DIR":  ("graph", "temp_dir"),
        "SMOKE_STATE_FILE":      ("state_file",),
        "SMOKE_LOG_FILE":        ("logging", "file"),
        "SMOKE_LOG_MAX_SIZE_MB": ("logging", "max_size_mb", int),
        "SMOKE_LOG_BACKUP_COUNT":("logging", "backup_count", int),
        "SMOKE_HEARTBEAT_ENABLED": ("heartbeat", "enabled", lambda v: v.lower() in ("true", "1", "yes")),
        "SMOKE_HEARTBEAT_TIME":  ("heartbeat", "time"),
    }

    def __init__(self, config_path: str, env_file: Optional[str] = None):
        self.config_path = config_path

        # Load .env file (if exists)
        env_path = env_file or os.path.join(os.path.dirname(config_path) or ".", ".env")
        load_dotenv(env_path)

        self._raw = self._load(config_path)
        self._apply_env_overrides()
        self._validate()

    # ── YAML Loading ──────────────────────────────────────────────
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

    # ── Environment Override ──────────────────────────────────────
    def _apply_env_overrides(self):
        """Override config values from environment variables (.env or OS env)."""
        for env_key, path_spec in self.ENV_MAP.items():
            val = os.environ.get(env_key)
            if val is None:
                continue

            # Determine type cast
            type_cast = None
            if len(path_spec) == 3:
                *yaml_path, type_cast = path_spec
            elif len(path_spec) == 1:
                yaml_path = list(path_spec)
            else:
                yaml_path = list(path_spec)

            # Cast value
            if type_cast:
                try:
                    val = type_cast(val)
                except (ValueError, TypeError):
                    continue

            # Apply to nested dict
            if len(yaml_path) == 1:
                # Top-level key (e.g., state_file)
                self._raw[yaml_path[0]] = val
            elif len(yaml_path) == 2:
                section, key = yaml_path
                self._raw.setdefault(section, {})[key] = val

    # ── Validation ────────────────────────────────────────────────
    def _validate(self):
        """Validate all required configuration fields."""
        errors = []

        # — Telegram
        tg = self._raw.get("telegram", {})
        if not tg.get("bot_token") or tg["bot_token"] == "YOUR_BOT_TOKEN":
            errors.append(
                "telegram.bot_token belum diisi.\n"
                "    Set via .env: SMOKE_TG_TOKEN=your_token"
            )
        if not tg.get("chat_id") or str(tg["chat_id"]) == "YOUR_CHAT_ID":
            errors.append(
                "telegram.chat_id belum diisi.\n"
                "    Set via .env: SMOKE_TG_CHAT_ID=your_chat_id"
            )

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
            print(f"  Config : {self.config_path}")
            print(f"  .env   : Set environment variables atau edit .env file")
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
    def telegram_listen_commands(self) -> bool:
        return self._raw.get("telegram", {}).get("listen_commands", True)

    @property
    def telegram_allowed_chat_ids(self) -> List[str]:
        raw_ids = self._raw.get("telegram", {}).get("allowed_chat_ids") or []
        # Convert to list of strings
        return [str(chat_id) for chat_id in raw_ids]

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

    def alert_delay(self, status: str) -> int:
        """Returns the delay in seconds for a specific status (warn, crit, down, ok). Default 0."""
        delays = self._raw.get("alerts", {}).get("delay", {})
        # Jika user menggunakan format lama (angka langsung), return angka tersebut untuk semua non-ok
        if isinstance(delays, int):
            return delays if status != "ok" else 0
        return int(delays.get(status.lower(), 0))

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
