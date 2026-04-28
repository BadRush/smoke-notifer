"""
Telegram Notifier — send alerts with retry & rate limiting.
"""

import os
import sys
import json
import time
import logging
from typing import Optional, List

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip3 install requests")
    sys.exit(1)

log = logging.getLogger("smoke-notifier")


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
    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        thread_id: Optional[int] = None,
        reply_markup: Optional[dict] = None
    ) -> bool:
        if not self._rate_ok():
            log.warning("Telegram rate limit hit — message queued/skipped")
            return False

        target_chat = chat_id or self.chat_id
        target_thread = thread_id if thread_id is not None else self.thread_id

        for attempt in range(1, self.max_retries + 1):
            try:
                payload = {
                    "chat_id":    target_chat,
                    "text":       text,
                    "parse_mode": "HTML",
                }
                if target_thread is not None:
                    payload["message_thread_id"] = target_thread
                if reply_markup is not None:
                    payload["reply_markup"] = reply_markup

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

    def send_photo(
        self,
        photo_path: str,
        caption: str = "",
        chat_id: Optional[str] = None,
        thread_id: Optional[int] = None,
        reply_markup: Optional[dict] = None
    ) -> bool:
        if not self._rate_ok():
            log.warning("Telegram rate limit hit — photo skipped")
            return False

        caption = self._truncate(caption, self.MAX_CAPTION)
        target_chat = chat_id or self.chat_id
        target_thread = thread_id if thread_id is not None else self.thread_id

        for attempt in range(1, self.max_retries + 1):
            try:
                form_data = {
                    "chat_id":    target_chat,
                    "caption":    caption,
                    "parse_mode": "HTML",
                }
                if target_thread is not None:
                    form_data["message_thread_id"] = target_thread

                # Optional JSON payload stringified for multipart/form-data
                if reply_markup is not None:
                    form_data["reply_markup"] = json.dumps(reply_markup)

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

    def send_alert(
        self,
        message: str,
        graph_path: Optional[str] = None,
        chat_id: Optional[str] = None,
        thread_id: Optional[int] = None,
        reply_markup: Optional[dict] = None
    ) -> bool:
        """Send alert: photo+caption if graph available, text otherwise."""
        if graph_path and os.path.isfile(graph_path):
            return self.send_photo(
                graph_path,
                caption=message,
                chat_id=chat_id,
                thread_id=thread_id,
                reply_markup=reply_markup
            )
        return self.send_message(
            message,
            chat_id=chat_id,
            thread_id=thread_id,
            reply_markup=reply_markup
        )

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
