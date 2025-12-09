# src/notifier.py
import logging
import json
import requests
import os

logger = logging.getLogger(__name__)

class Notifier:
    """
    システム通知を管理するクラス。
    主にDiscord Webhookを使用して、重要イベントやエラーを外部へ通知する。
    """

    def __init__(self):
        """
        Notifierを初期化する。DISCORD_WEBHOOK_URL環境変数を使用する。
        """
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def send(self, message: str, level: str = "INFO") -> None:
        """
        通知を送信する。

        Args:
            message (str): 通知本文
            level (str): 通知レベル ("INFO", "WARNING", "CRITICAL")
        """
        log_msg = f"[NOTIFICATION] {message}"
        if level == "CRITICAL":
            logger.critical(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        if self.webhook_url:
            self._send_discord(message, level)

    def _send_discord(self, text: str, level: str) -> None:
        """
        DiscordへWebhookリクエストを送信する。

        Args:
            text (str): メッセージ
            level (str): レベル
        """
        try:
            color = 3066993 # Green
            title = "ℹ️ Info"
            
            if level == "WARNING":
                color = 16776960 # Yellow
                title = "⚠️ Warning"
            elif level == "CRITICAL":
                color = 15158332 # Red
                title = "🚨 CRITICAL ERROR"

            payload = {
                "username": "FX Swap Bot",
                "embeds": [{
                    "title": title,
                    "description": text,
                    "color": color,
                    "footer": {"text": "Gemini FX Bot System"}
                }]
            }

            headers = {"Content-Type": "application/json"}
            requests.post(self.webhook_url, data=json.dumps(payload), headers=headers, timeout=5)

        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")

            