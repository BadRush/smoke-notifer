"""
SmokePing Monitor — main monitoring loop with flapping detection and heartbeat.
"""

import os
import sys
import time
import signal
import logging
import argparse
from datetime import datetime
from typing import Optional

from . import APP_NAME, VERSION
from .config import Config
from .state import StateManager
from .rrd import RRDReader
from .graph import GraphGenerator
from .telegram import TelegramNotifier
from .alerts import AlertBuilder, StatusEvaluator
from .commands import CommandListener
from .constants import (
    STATUS_OK, STATUS_WARN, STATUS_CRIT, STATUS_DOWN,
    STATUS_FLAPPING, STATUS_UNKNOWN, STATUS_UNREACHABLE,
)
from .logging_setup import setup_logging

log = logging.getLogger("smoke-notifier")


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

    # ── Get Effective Status (Pass 2) ─────────────────────────────
    def _get_effective_status(self, label: str, raw_statuses: dict, visited: set = None) -> str:
        if visited is None:
            visited = set()
        
        if label in visited:
            return raw_statuses.get(label, STATUS_UNKNOWN)
            
        visited.add(label)
        
        raw_status = raw_statuses.get(label, STATUS_UNKNOWN)
        
        # Temukan konfigurasi link ini
        link_cfg = next((l for l in self.config.links if l["label"] == label), None)
        if not link_cfg:
            return raw_status
            
        depends_on = link_cfg.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
            
        for parent_label in depends_on:
            parent_eff_status = self._get_effective_status(parent_label, raw_statuses, visited)
            if parent_eff_status in (STATUS_WARN, STATUS_CRIT, STATUS_DOWN, STATUS_FLAPPING, STATUS_UNREACHABLE):
                return STATUS_UNREACHABLE
                
        return raw_status

    # ── Process Link State (Pass 3) ───────────────────────────────
    def _process_link_state(self, link_cfg: dict, data: Optional[dict], status: str):
        label = link_cfg["label"]
        prev_state  = self.state.get(label)
        prev_status = prev_state.get("status", STATUS_UNKNOWN)
        pending_status = prev_state.get("pending_status")
        pending_since = prev_state.get("pending_since")
        now = datetime.now()
        now_iso = now.isoformat()

        # Maintenance Check (silent drop)
        if self.state.is_maintenance(label):
            self.state.update(label, status, now_iso)
            return

        # ── First run: set initial state ──────────────────────────
        if prev_status == STATUS_UNKNOWN:
            log.info(f"  ↳ Initial state: {status}")
            self.state.update(label, status, now_iso)
            if status not in (STATUS_OK, STATUS_UNREACHABLE):
                msg = self.builder.build_alert(link_cfg, data, status, STATUS_OK)
                if not self.dry_run:
                    graph_path = self.grapher.generate(link_cfg)
                    self.notifier.send_alert(
                        msg, graph_path, chat_id=link_cfg.get("chat_id"),
                        thread_id=link_cfg.get("message_thread_id")
                    )
                    if graph_path:
                        self.grapher.cleanup(graph_path)
                    self.state.record_alert(label, now_iso)
                else:
                    log.info("  [DRY-RUN] Would send initial alert")
            return

        # ── No change → skip ─────────────────────────────────────
        if status == prev_status:
            if pending_status is not None:
                self.state.update_soft_status(label, None, now_iso)
            self.state.update(label, status, now_iso)
            return

        # ── Soft State / Delay Logic ──────────────────────────────
        delay_sec = self.config.alert_delay(status)
        if status in (STATUS_UNREACHABLE, STATUS_FLAPPING):
            delay_sec = 0  # Internal statuses transition immediately

        if delay_sec > 0:
            if status == pending_status:
                try:
                    since = datetime.fromisoformat(pending_since)
                    elapsed = (now - since).total_seconds()
                except (ValueError, TypeError):
                    elapsed = 0
                
                if elapsed < delay_sec:
                    # Masih dalam masa tunggu
                    self.state.update_soft_status(label, status, pending_since)
                    return
            else:
                # Baru memasuki status non-OK/perubahan status
                log.info(f"{label:30s} | SOFT STATE | {prev_status} → {status} (Waiting {delay_sec}s)")
                self.state.update_soft_status(label, status, now_iso)
                return

        # ── Hard State Transition ─────────────────────────────────
        # Logging
        if data and data.get("median_rtt") is not None:
            jit = f" | Jitter: {data['jitter']} ms" if data.get("jitter") else ""
            log.info(
                f"{label:30s} | HARD STATE | RTT: {data['median_rtt']:>8} ms | "
                f"Loss: {data['loss_pct']:>5}%{jit} | "
                f"{prev_status} → {status}"
            )
        else:
            if status == STATUS_UNREACHABLE:
                log.info(f"{label:30s} | PARENT DOWN | {prev_status} → {status}")
            else:
                log.info(f"{label:30s} | HARD STATE | {prev_status} → {status}")

        chat_id = str(link_cfg.get("chat_id")) if link_cfg.get("chat_id") else None
        thread_id = int(link_cfg.get("message_thread_id")) if link_cfg.get("message_thread_id") else None

        # Build inline keyboard if needed
        reply_markup = None
        if self.config.telegram_listen_commands and status in (STATUS_DOWN, STATUS_WARN, STATUS_CRIT):
            short_lbl = label[:40]
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "📉 Graph 6h", "callback_data": f"g:6h:{short_lbl}"},
                        {"text": "📉 Graph 24h", "callback_data": f"g:24h:{short_lbl}"}
                    ],
                    [
                        {"text": "🔇 Mute 1h", "callback_data": f"m:1h:{short_lbl}"},
                        {"text": "❌ Tutup", "callback_data": "dismiss"}
                    ]
                ]
            }

        # ── Dependency Suppressions ──────────────────────────────
        if status == STATUS_UNREACHABLE:
            log.info(f"  ↳ {label}: Parent link issue — suppressing alert (UNREACHABLE)")
            self.state.update(label, status, now_iso)
            return

        if prev_status == STATUS_UNREACHABLE and status == STATUS_OK:
            log.info(f"  ↳ {label}: Parent recovered & link is OK — silent recovery")
            self.state.update(label, status, now_iso)
            return

        # ── Flapping Check ───────────────────────────────────────
        if self.state.is_flapping(
            label, self.config.flapping_max_changes, self.config.flapping_window
        ):
            if prev_status != STATUS_FLAPPING:
                log.warning(f"  ↳ {label}: FLAPPING detected — suppressing")
                msg = self.builder.build_alert(link_cfg, data, STATUS_FLAPPING, prev_status)
                if not self.dry_run:
                    self.notifier.send_message(msg, chat_id=chat_id, thread_id=thread_id)
                    self.state.record_alert(label, now_iso)
                self.state.update(label, STATUS_FLAPPING, now_iso)
            return

        if self.state.in_cooldown(label, self.config.flapping_cooldown):
            log.debug(f"  ↳ {label}: In cooldown — alert deferred")
            self.state.update(label, status, now_iso)
            return

        # ── Send Alert ───────────────────────────────────────────
        downtime = None
        if status == STATUS_OK:
            downtime = self.state.get_downtime(label)

        msg = self.builder.build_alert(link_cfg, data, status, prev_status, downtime)

        if self.dry_run:
            log.info(f"  [DRY-RUN] Would send:\n{msg}")
        else:
            graph_path = self.grapher.generate(link_cfg)
            self.notifier.send_alert(
                msg, graph_path, chat_id=chat_id,
                thread_id=thread_id, reply_markup=reply_markup
            )
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

        if not self.dry_run:
            if not self.notifier.test_connection():
                log.error("Cannot connect to Telegram — check bot_token")
                sys.exit(1)

        listener = None
        if not self.dry_run and self.config.telegram_listen_commands:
            listener = CommandListener(self.config, self.state, self.notifier, self.grapher)
            listener.start()

        while self._running:
            try:
                # Pass 1: Fetch raw data and evaluate raw status
                raw_data = {}
                raw_statuses = {}
                for link_cfg in self.config.links:
                    if not self._running:
                        break
                        
                    label = link_cfg["label"]
                    rrd_file = os.path.join(self.config.rrd_base_path, link_cfg["rrd_path"])
                    num_probes = link_cfg.get("num_probes", self.config.default_num_probes)
                    
                    data = RRDReader.fetch(rrd_file, num_probes)
                    status = self.evaluator.evaluate(data, link_cfg)
                    
                    raw_data[label] = data
                    raw_statuses[label] = status

                # Pass 2 & 3: Resolve dependencies & process states
                if self._running:
                    for link_cfg in self.config.links:
                        label = link_cfg["label"]
                        data = raw_data[label]
                        effective_status = self._get_effective_status(label, raw_statuses)
                        
                        self._process_link_state(link_cfg, data, effective_status)

                if self._running:
                    self._check_heartbeat()

            except Exception as e:
                log.error(f"Error in main loop: {e}", exc_info=True)

            for _ in range(self.config.check_interval):
                if not self._running:
                    break
                time.sleep(1)

        if listener:
            listener.stop()
            listener.join(timeout=2)

        self.state.save()
        log.info(f"{APP_NAME} stopped gracefully")


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
        "--env-file",
        default=None,
        help="Path to .env file (default: same directory as config)",
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
    config = Config(args.config, env_file=args.env_file)
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
