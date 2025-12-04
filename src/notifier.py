# src/notifier.py
import logging
import json
import requests
import os

logger = logging.getLogger(__name__)

class Notifier:
    """
    システム通知クラス (Discord版)
    環境変数 DISCORD_WEBHOOK_URL が設定されている場合に通知を送信する。
    """
    def __init__(self):
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    def send(self, message: str, level: str = "INFO"):
        """
        通知を送信する
        Args:
            message (str): 通知内容
            level (str): INFO, WARNING, CRITICAL
        """
        # 1. ログに出す
        log_msg = f"[NOTIFICATION] {message}"
        if level == "CRITICAL":
            logger.critical(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # 2. Discordに送る
        if self.webhook_url:
            self._send_discord(message, level)

    def _send_discord(self, text: str, level: str):
        try:
            # 色設定 (Decimal値) Green/Yellow/Red
            color = 3066993 
            title = "ℹ️ Info"
            
            if level == "WARNING":
                color = 16776960
                title = "⚠️ Warning"
            elif level == "CRITICAL":
                color = 15158332
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