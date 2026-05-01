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
    def evaluate(data: Optional[dict], link_cfg: dict, baseline: Optional[dict] = None) -> str:
        if data is None:
            return STATUS_DOWN
        if data.get("median_rtt") is None:
            return STATUS_DOWN

        rtt  = data["median_rtt"]
        loss = data["loss_pct"]

        # Determine thresholds
        crit_loss = link_cfg.get("crit_loss", 20)
        warn_loss = link_cfg.get("warn_loss", 5)
        
        if baseline:
            crit_rtt = baseline.get("crit_rtt", link_cfg.get("crit_rtt", 80))
            warn_rtt = baseline.get("warn_rtt", link_cfg.get("warn_rtt", 30))
        else:
            crit_rtt = link_cfg.get("crit_rtt", 80)
            warn_rtt = link_cfg.get("warn_rtt", 30)

        if loss >= crit_loss:
            return STATUS_CRIT
        if rtt >= crit_rtt:
            return STATUS_CRIT
        if loss >= warn_loss:
            return STATUS_WARN
        if rtt >= warn_rtt:
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
    def build_alert(link_cfg, data, status, prev_status, downtime=None, baseline=None):
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        emoji = STATUS_EMOJI.get(status, "⚪")
        prev_emoji = STATUS_EMOJI.get(prev_status, "⚪")
        label = link_cfg["label"]

        if (status == STATUS_OK
                and prev_status in (STATUS_WARN, STATUS_CRIT, STATUS_DOWN, STATUS_FLAPPING)):
            header = f"{emoji} <b>[RECOVERED] {label}</b>"
        else:
            header = f"{emoji} <b>[{status}] {label}</b>"

        def pad(text, length=12):
            return text.ljust(length)

        if status == STATUS_DOWN:
            detail = "❌ Tidak ada data — link down / RRD kosong"
        elif status == STATUS_FLAPPING:
            detail = "⚠️ Link tidak stabil (flapping) — alert di-suppress sementara"
        elif data:
            rtt    = data.get("median_rtt", "N/A")
            loss   = data.get("loss_pct", "N/A")
            jitter = data.get("jitter")
            
            w_rtt = link_cfg.get('warn_rtt')
            c_rtt = link_cfg.get('crit_rtt')
            if baseline:
                w_rtt = baseline.get('warn_rtt', w_rtt)
                c_rtt = baseline.get('crit_rtt', c_rtt)

            detail = (
                f"📊 <code>{pad('RTT Median')} :</code> <b>{rtt} ms</b> <i>(warn: {w_rtt}, crit: {c_rtt})</i>\n"
                f"📉 <code>{pad('Packet Loss')} :</code> <b>{loss}%</b> <i>(warn: {link_cfg.get('warn_loss')}, crit: {link_cfg.get('crit_loss')})</i>"
            )
            if baseline:
                detail += f"\n🤖 <i>Dynamic Baseline Active (Avg: {baseline.get('mean')} ms)</i>"

                detail += f"\n📐 <code>{pad('Jitter')} :</code> <b>{jitter} ms</b>"
        else:
            detail = "⚠️ Data tidak tersedia"

        downtime_line = ""
        if downtime and status == STATUS_OK:
            dur = AlertBuilder._format_duration(downtime)
            downtime_line = f"\n⏱️ <code>{pad('Durasi')} :</code> <b>{dur}</b>"

        transition = f"{prev_emoji}{prev_status} → {emoji}{status}"

        return (
            f"{header}\n"
            f"─────────────────────\n"
            f"{detail}{downtime_line}\n"
            f"🔄 <code>{pad('Status')} :</code> {transition}\n"
            f"🕐 <code>{pad('Waktu')} :</code> {ts}"
        )

    @staticmethod
    def build_summary_alert(alerts: List[dict]) -> str:
        """Build a single summary message for batched alerts."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = len(alerts)
        
        lines = [
            f"⚠️ <b>[MULTIPLE STATUS CHANGES]</b>",
            f"─────────────────────",
            f"Terdeteksi <b>{count}</b> link berubah status dalam cycle ini:",
            ""
        ]
        
        for alert in alerts:
            label = alert["label"]
            status = alert["status"]
            prev_status = alert["prev_status"]
            emoji = STATUS_EMOJI.get(status, "⚪")
            lines.append(f"  {emoji} <code>{label}</code> : {prev_status} → <b>{status}</b>")
            
        lines.append("")
        lines.append("<i>Catatan: Grafik tidak dikirim untuk mencegah spam.</i>")
        lines.append(f"🕐 Waktu: {ts}")
        
        return "\n".join(lines)

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
