"""
Alert Builder & Status Evaluator — format alert messages and evaluate link health.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, List

from . import APP_NAME, VERSION
from .constants import (
    STATUS_OK, STATUS_WARN, STATUS_CRIT, STATUS_DOWN,
    STATUS_FLAPPING, STATUS_UNKNOWN, STATUS_EMOJI,
)


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

        if loss >= link_cfg.get("crit_loss", 20):
            return STATUS_CRIT
        if rtt >= link_cfg.get("crit_rtt", 80):
            return STATUS_CRIT
        if loss >= link_cfg.get("warn_loss", 5):
            return STATUS_WARN
        if rtt >= link_cfg.get("warn_rtt", 30):
            return STATUS_WARN

        jitter = data.get("jitter")
        if jitter is not None:
            cj = link_cfg.get("crit_jitter")
            wj = link_cfg.get("warn_jitter")
            if cj is not None and jitter >= cj:
                return STATUS_CRIT
            if wj is not None and jitter >= wj:
                return STATUS_WARN

        return STATUS_OK


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
    def build_alert(link_cfg, data, status, prev_status, downtime=None):
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        emoji = STATUS_EMOJI.get(status, "⚪")
        prev_emoji = STATUS_EMOJI.get(prev_status, "⚪")
        label = link_cfg["label"]

        if (status == STATUS_OK
                and prev_status in (STATUS_WARN, STATUS_CRIT, STATUS_DOWN, STATUS_FLAPPING)):
            header = f"{emoji} <b>[RECOVERED] {label}</b>"
        else:
            header = f"{emoji} <b>[{status}] {label}</b>"

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
