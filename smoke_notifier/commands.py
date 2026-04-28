"""
Command Listener — Telegram Interactive Bot for NOC operations.
Handles /smokestatus, /smokemaint, /smoke commands and inline button callbacks.
"""

import re
import time
import logging
import threading
from typing import Optional, List

import requests

from .constants import STATUS_OK, STATUS_UNKNOWN, STATUS_EMOJI

log = logging.getLogger("smoke-notifier")


class CommandListener(threading.Thread):
    """Listens for Telegram commands and callback queries in a background thread."""

    def __init__(self, config, state, notifier, grapher):
        super().__init__(daemon=True)
        self.config = config
        self.state = state
        self.notifier = notifier
        self.grapher = grapher
        self._running = True
        self._offset = None
        self._allowed_chats = config.telegram_allowed_chat_ids

    def stop(self):
        self._running = False

    def run(self):
        if not self.config.telegram_listen_commands:
            log.info("Telegram Command Listener is DISABLED in config.")
            return

        log.info("Telegram Command Listener started.")
        url = f"{self.notifier._base_url}/getUpdates"

        while self._running:
            try:
                params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
                if self._offset is not None:
                    params["offset"] = self._offset

                r = requests.get(url, params=params, timeout=40)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for update in updates:
                            self._offset = update["update_id"] + 1
                            self._handle_update(update)
            except requests.exceptions.RequestException:
                pass  # ignore network timeouts
            except Exception as e:
                log.debug(f"getUpdates error: {e}")

            time.sleep(1)

    def _is_allowed(self, chat_id: str) -> bool:
        if not self._allowed_chats:
            return True
        return str(chat_id) in self._allowed_chats

    def _is_admin(self, user_id: str) -> bool:
        if not self.config.telegram_admin_users:
            return False
        return str(user_id) in self.config.telegram_admin_users

    def _handle_update(self, update: dict):
        if "message" in update and "text" in update["message"]:
            msg = update["message"]
            chat_id = str(msg["chat"]["id"])
            user_id = str(msg.get("from", {}).get("id", ""))
            is_admin = self._is_admin(user_id)
            
            if not is_admin and not self._is_allowed(chat_id):
                return
                
            thread_id = msg.get("message_thread_id")
            
            # Jika bot dikonfigurasi untuk thread tertentu, abaikan pesan dari luar thread tersebut
            if not is_admin and self.config.telegram_thread_id is not None:
                if thread_id != self.config.telegram_thread_id:
                    return
                    
            text = msg["text"].strip()
            self._handle_command(text, chat_id, thread_id)

        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = str(cb["message"]["chat"]["id"])
            user_id = str(cb.get("from", {}).get("id", ""))
            
            if not self._is_admin(user_id) and not self._is_allowed(chat_id):
                return
            self._handle_callback(cb)

    def _handle_command(self, text: str, chat_id: str, thread_id: Optional[int]):
        parts = text.split()
        if not parts:
            return

        cmd = parts[0].split('@')[0].lower()

        if cmd == "/smokestatus":
            self._cmd_status(chat_id, thread_id)
        elif cmd == "/smokemaint":
            self._cmd_maint(parts[1:], chat_id, thread_id)
        elif cmd == "/smoke":
            self._cmd_graph(parts[1:], chat_id, thread_id)

    def _cmd_status(self, chat_id: str, thread_id: Optional[int]):
        states = self.state.get_all()
        links = self.config.links

        from collections import defaultdict
        groups = defaultdict(list)

        for l in links:
            lbl = l["label"]
            r_path = l.get("rrd_path", "")
            
            # Extract the first folder name from rrd_path, or "General" if none
            parts = r_path.replace('\\', '/').split('/')
            folder = parts[0] if len(parts) > 1 else "General"
            
            st = states.get(lbl, {}).get("status", STATUS_UNKNOWN)
            m_str = " 🔇(Muted)" if self.state.is_maintenance(lbl) else ""
            
            if st == STATUS_OK:
                groups[folder].append(f" - 🟢 <code>{lbl}</code>{m_str}")
            else:
                emoji = STATUS_EMOJI.get(st, "⚪")
                # Insert at the top of the group so NON-OK links are visible first
                groups[folder].insert(0, f" - {emoji} <code>{lbl}</code>: <b>{st}</b>{m_str}")

        gl_mute = "\n🔇 <b>GLOBAL MAINTENANCE ACTIVE</b>\n" if self.state.is_maintenance("_global_") else ""

        msg = f"📊 <b>Smart Status Summary</b>\n{gl_mute}─────────────────────\n"
        
        for folder, lines in groups.items():
            msg += f"\n<b>📁 {folder}</b>\n"
            msg += "\n".join(lines) + "\n"

        self.notifier.send_message(msg, chat_id=chat_id, thread_id=thread_id)

    def _parse_duration(self, d_str: str) -> Optional[int]:
        match = re.match(r"^(\d+)([mhd])$", d_str.lower())
        if not match:
            return None
        val = int(match.group(1))
        unit = match.group(2)
        if unit == "m": return val * 60
        if unit == "h": return val * 3600
        if unit == "d": return val * 86400
        return None

    def _cmd_maint(self, args: List[str], chat_id: str, thread_id: Optional[int]):
        if not args:
            self.notifier.send_message(
                "❌ Format: `/smokemaint <durasi> [link]`\n"
                "Contoh: `/smokemaint 3h`\nMati: `/smokemaint off`",
                chat_id=chat_id, thread_id=thread_id
            )
            return

        time_str = args[0]
        label = " ".join(args[1:]) if len(args) > 1 else "_global_"

        if time_str.lower() == "off":
            self.state.set_maintenance(label, 0)
            target = "Global" if label == "_global_" else f"Link '{label}'"
            self.notifier.send_message(
                f"🔊 {target} maintenance dimatikan.",
                chat_id=chat_id, thread_id=thread_id
            )
            return

        sec = self._parse_duration(time_str)
        if not sec:
            self.notifier.send_message(
                "❌ Durasi tidak valid. Gunakan m/h/d (contoh: 30m, 1h).",
                chat_id=chat_id, thread_id=thread_id
            )
            return

        self.state.set_maintenance(label, sec)
        target = "Global" if label == "_global_" else f"Link '{label}'"
        self.notifier.send_message(
            f"🔇 {target} disenyapkan selama {time_str}.",
            chat_id=chat_id, thread_id=thread_id
        )

    def _cmd_graph(self, args: List[str], chat_id: str, thread_id: Optional[int]):
        if len(args) < 2:
            self.notifier.send_message(
                "❌ Format: `/smoke <durasi> <Nama Link>`\n"
                "Contoh: `/smoke 3h FS-TGL-YK`",
                chat_id=chat_id, thread_id=thread_id
            )
            return

        dur = args[0]
        label = " ".join(args[1:])

        link_cfg = next((l for l in self.config.links if l["label"] == label), None)
        if not link_cfg:
            self.notifier.send_message(
                f"❌ Link '{label}' tidak ditemukan di config.",
                chat_id=chat_id, thread_id=thread_id
            )
            return

        temp_cfg = link_cfg.copy()
        gpath = self.grapher.generate(temp_cfg, duration=dur)
        if gpath:
            self.notifier.send_photo(
                gpath, caption=f"📈 Graph {dur} untuk <b>{label}</b>",
                chat_id=chat_id, thread_id=thread_id
            )
            self.grapher.cleanup(gpath)
        else:
            self.notifier.send_message(
                "❌ Gagal membuat grafik.",
                chat_id=chat_id, thread_id=thread_id
            )

    def _handle_callback(self, cb: dict):
        cb_id = cb["id"]
        data = cb.get("data", "")
        msg = cb.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        msg_id = msg.get("message_id")

        if data == "dismiss":
            requests.post(
                f"{self.notifier._base_url}/answerCallbackQuery",
                json={"callback_query_id": cb_id}, timeout=5
            )
            requests.post(
                f"{self.notifier._base_url}/editMessageReplyMarkup",
                json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "reply_markup": {"inline_keyboard": []}
                }, timeout=5
            )
            return

        parts = data.split(":", 2)
        if len(parts) >= 3:
            action = parts[0]
            val = parts[1]
            short_lbl = parts[2]

            link_cfg = next(
                (l for l in self.config.links if l["label"].startswith(short_lbl)),
                None
            )
            if not link_cfg:
                requests.post(
                    f"{self.notifier._base_url}/answerCallbackQuery",
                    json={
                        "callback_query_id": cb_id,
                        "text": "❌ Link tidak dikenali",
                        "show_alert": True
                    }, timeout=5
                )
                return

            label = link_cfg["label"]

            if action == "m":
                sec = self._parse_duration(val)
                if sec:
                    self.state.set_maintenance(label, sec)
                    requests.post(
                        f"{self.notifier._base_url}/answerCallbackQuery",
                        json={
                            "callback_query_id": cb_id,
                            "text": f"🔇 {label} muted {val}"
                        }, timeout=5
                    )
                    # Hilangkan tombol setelah ditekan
                    requests.post(
                        f"{self.notifier._base_url}/editMessageReplyMarkup",
                        json={
                            "chat_id": chat_id, "message_id": msg_id,
                            "reply_markup": {"inline_keyboard": []}
                        }, timeout=5
                    )

            elif action == "g":
                requests.post(
                    f"{self.notifier._base_url}/answerCallbackQuery",
                    json={"callback_query_id": cb_id}, timeout=5
                )
                self._cmd_graph([val, label], chat_id, None)
