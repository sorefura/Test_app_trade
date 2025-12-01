import time
import hmac
import hashlib
import json
import logging
import requests
import yaml
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List

from src.interfaces import BrokerClient
from src.models import MarketSnapshot, PositionSummary, AiAction

logger = logging.getLogger(__name__)

# GMOコイン 外国為替FX API エンドポイント
DEFAULT_FX_PUBLIC_URL = 'https://forex-api.coin.z.com/public'
DEFAULT_FX_PRIVATE_URL = 'https://forex-api.coin.z.com/private'

class GmoBrokerClient(BrokerClient):
    """
    GMOコイン 外国為替FX API を利用するブローカークライアント。
    """

    def __init__(self, config: dict, secrets: dict):
        self.config = config
        
        # ライブ取引フラグ (YAML設定)
        yaml_live_flag = config.get("enable_live_trading", False)
        
        # ★追加: 環境変数による二段ロック (GPT運用条件)
        # 環境変数 LIVE_TRADING_ARMED="YES" がセットされていないと発注しない
        import os
        env_live_armed = os.getenv("LIVE_TRADING_ARMED", "NO") == "YES"
        
        if yaml_live_flag and env_live_armed:
            self.enable_live_trading = True
            logger.warning("!!! LIVE TRADING FULLY ARMED & ENABLED !!! Real orders WILL be sent.")
        else:
            self.enable_live_trading = False
            if yaml_live_flag and not env_live_armed:
                logger.warning("Live trading is set in YAML but disarmed by env var. Orders will be MOCKED.")
            else:
                logger.info("Live trading disabled. Orders will be MOCKED.")

        gmo_secrets = secrets.get('gmo', {})
        self.api_key = gmo_secrets.get('api_key')
        self.api_secret = gmo_secrets.get('api_secret')
        
        self.public_url = gmo_secrets.get('base_url_public', DEFAULT_FX_PUBLIC_URL)
        self.private_url = gmo_secrets.get('base_url_private', DEFAULT_FX_PRIVATE_URL)
        
        self.timeout = 10

        swap_conf: dict = config.get("manual_swap_settings", {})
        self.swap_updated_at = swap_conf.get("updated_at", "2000-01-01")
        self.swap_overrides = swap_conf.get("overrides", {})
        
        self._check_swap_freshness()
        self.swap_overrides = config.get("manual_swap_overrides", {})

    def _check_swap_freshness(self):
        """スワップ設定の鮮度を確認する"""
        try:
            updated_date = datetime.strptime(self.swap_updated_at, "%Y-%m-%d")
            days_diff = (datetime.now() - updated_date).days
            
            if days_diff > 14:
                logger.critical(f"CRITICAL: Swap settings are too old ({days_diff} days). Trading may be unsafe.")
            elif days_diff > 7:
                logger.warning(f"WARNING: Swap settings are {days_diff} days old. Please update settings.yaml.")
        except ValueError:
            logger.error("Invalid date format in manual_swap_settings.updated_at")

    def _get_header(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise ValueError("API Key and Secret are required for Private API calls.")

        timestamp = str(int(time.time() * 1000))
        text = timestamp + method + path + body
        
        sign = hmac.new(
            bytes(self.api_secret.encode('ascii')),
            bytes(text.encode('ascii')),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "API-KEY": self.api_key,
            "API-TIMESTAMP": timestamp,
            "API-SIGN": sign
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        
        return headers

    def _request(self, method: str, endpoint: str, params: dict = None, private: bool = False) -> Any:
        base_url = self.private_url if private else self.public_url
        url = base_url + endpoint
        
        try:
            headers = {}
            body_str = ""
            
            if private:
                if method == "POST" and params:
                    body_str = json.dumps(params)
                headers = self._get_header(method, endpoint, body_str)
            
            if method == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            else:
                response = requests.post(url, data=body_str, headers=headers, timeout=self.timeout)

            response.raise_for_status()
            data = response.json()

            if data.get("status") != 0:
                messages = data.get("messages", [])
                error_info = messages[0] if messages else {"message": "Unknown Error"}
                raise Exception(f"GMO API Error [{error_info.get('error_code')}]: {error_info.get('message')}")

            return data.get("data")

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error ({url}): {e}")
            if e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"GMO Request Failed ({url}): {e}")
            raise

    # --- BrokerClient Protocol Implementation ---

    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        endpoint = "/v1/ticker"
        params = {"symbol": pair}
        data = self._request("GET", endpoint, params=params, private=False)
        
        if not data or len(data) == 0:
            raise ValueError(f"No ticker data returned for {pair}")

        item = [d for d in data if d['symbol'] == pair][0]
        
        overrides = self.swap_overrides.get(pair, {})
        swap_long = float(overrides.get("long", 0.0))
        swap_short = float(overrides.get("short", 0.0))

        if swap_long != 0.0 or swap_short != 0.0:
            logger.info(f"[MarketData] Using Manual Swap Override for {pair}: L={swap_long}/S={swap_short}")

        return MarketSnapshot(
            pair=item["symbol"],
            timestamp=datetime.now(timezone.utc),
            bid=float(item["bid"]),
            ask=float(item["ask"]),
            swap_long_per_day=swap_long,
            swap_short_per_day=swap_short,
            realized_vol_24h=None
        )

    def get_positions(self) -> List[PositionSummary]:
        """
        全保有建玉サマリーを取得
        """
        endpoint = "/v1/positionSummary"
        data = self._request("GET", endpoint, params={}, private=True)
        
        positions = []
        if not data or "list" not in data:
            return []

        for item in data["list"]:
            side = "LONG" if item["side"] == "BUY" else "SHORT"
            amount = float(item["sumOpenSize"])
            
            if amount <= 0:
                continue

            pnl = float(item.get("lossGain", 0.0)) + float(item.get("totalSwap", 0.0))

            positions.append(PositionSummary(
                pair=item["symbol"],
                side=side,
                amount=amount,
                avg_entry_price=float(item["averagePositionRate"]),
                current_price=0.0,
                unrealized_pnl=pnl,
                leverage=25.0 
            ))
            
        return positions

    def get_account_state(self) -> Any:
        endpoint = "/v1/account/assets"
        data = self._request("GET", endpoint, private=True)
        
        equity = float(data.get("equity", data.get("netAssets", 0.0)))
        used = float(data.get("margin", 0.0))
        
        try:
            ratio_str = str(data.get("marginRatio", "0"))
            margin_ratio_pct = float(ratio_str) / 100.0
        except:
            margin_ratio_pct = 9.99

        return {
            "balance": equity,
            "margin_used": used,
            "leverage_max": 25.0,
            "margin_maintain_pct": margin_ratio_pct
        }

    def place_order(self, decision: AiAction) -> Any:
        if not decision.units or decision.units <= 0:
            logger.warning("Order units not specified or 0. Skipping.")
            return {"status": "SKIPPED_ZERO_UNITS"}

        endpoint = "/v1/order"
        side = "BUY" if decision.action == "BUY" else "SELL"
        
        params = {
            "symbol": decision.target_pair,
            "side": side,
            "executionType": "MARKET",
            "size": str(int(decision.units))
        }

        logger.info(f"[GMO] Prepare Order: {params}")
        
        if self.enable_live_trading:
            logger.info(">>> SENDING REAL ORDER TO GMO COIN <<<")
            return self._request("POST", endpoint, params=params, private=True)
        else:
            logger.warning("[MOCK] Live trading is DISABLED. Order NOT sent.")
            return {"status": "MOCK_SENT", "id": "mock_id_999", "params": params}

    def close_position(self, position_id: str, amount: Optional[float] = None) -> Any:
        """
        決済注文 (Retry, Backoff, Double-Check 対応版)
        修正: symbolパラメータ追加、settlePosition形式への対応
        """
        pair = position_id  # position_id引数には通貨ペア(MXN_JPY等)が入ってくる
        logger.info(f"[GMO] Closing all positions for {pair}...")

        max_retries = 3
        
        # 1. 建玉一覧を取得
        try:
            endpoint_list = "/v1/openPositions"
            params = {"symbol": pair}
            data = self._request("GET", endpoint_list, params=params, private=True)
        except Exception as e:
            logger.error(f"Failed to fetch open positions: {e}")
            return {"status": "FAILED_FETCH"}

        if not data or "list" not in data or len(data["list"]) == 0:
            logger.info(f"[GMO] No open positions found for {pair}.")
            return {"status": "NO_POSITIONS"}

        results = []
        endpoint_close = "/v1/closeOrder"
        
        # 2. 建玉ごとに決済
        for i, position in enumerate(data["list"]):
            if i > 0: time.sleep(1.2) # レート制限

            # 決済方向 (建玉の逆)
            closing_side = "SELL" if position["side"] == "BUY" else "BUY"

            # ★修正箇所: パラメータの構成を変更
            close_params = {
                "executionType": "MARKET",
                "symbol": pair,  # <--- ★必須: symbolを追加
                "side": closing_side,
                # 建玉指定決済のため settlePosition を使用
                "settlePosition": [
                    {
                        "positionId": position["positionId"],
                        "size": str(position["size"])
                    }
                ]
            }

            for attempt in range(max_retries + 1):
                try:
                    logger.info(f"[GMO] Closing Pos {position['positionId']} ({closing_side} {position['size']}) - Attempt {attempt+1}")
                    if self.enable_live_trading:
                        # settlePositionは辞書型リストなので、JSONダンプが必要な場合があるが
                        # _requestメソッド内で json.dumps しているなら辞書のままでOK
                        res = self._request("POST", endpoint_close, params=close_params, private=True)
                        results.append(res)
                    else:
                        logger.warning(f"[MOCK] Closing Pos {position['positionId']}")
                        results.append({"id": position["positionId"], "status": "MOCK_CLOSED"})
                    break
                except Exception as e:
                    logger.error(f"Failed to close position {position.get('positionId')}: {e}")
                    if attempt < max_retries:
                        time.sleep(1.0 * (2 ** attempt))
                    else:
                        logger.critical(f"Gave up closing position {position.get('positionId')}")
                        results.append({"error": str(e)})

        # 3. ダブルチェック (実残確認)
        if self.enable_live_trading:
            logger.info("[GMO] Verifying closure (Double Check)...")
            time.sleep(1.0)
            try:
                check_data = self._request("GET", endpoint_list, params=params, private=True)
                remaining_count = len(check_data.get("list", []))
                if remaining_count > 0:
                     logger.critical(f"⚠️ DANGER: {remaining_count} positions still remain after close attempt!")
                     return {"status": "PARTIAL_FAILURE_REMAINING", "details": results}
                else:
                     logger.info("[GMO] Verification Passed: All positions closed.")
            except Exception as e:
                logger.warning(f"Verification failed (API error): {e}")

        return {"status": "CLOSED_ALL", "details": results}
    