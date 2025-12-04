# src/adapters/gmo_broker.py
import time
import hmac
import hashlib
import json
import logging
import requests
import yaml
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

from src.interfaces import BrokerClient
from src.models import MarketSnapshot, PositionSummary, AiAction

logger = logging.getLogger(__name__)

DEFAULT_FX_PUBLIC_URL = 'https://forex-api.coin.z.com/public'
DEFAULT_FX_PRIVATE_URL = 'https://forex-api.coin.z.com/private'

class GmoBrokerClient(BrokerClient):
    def __init__(self, config: dict, secrets: dict):
        self.config = config
        
        # Live Flag Check
        yaml_live_flag = config.get("enable_live_trading", False)
        import os
        env_live_armed = os.getenv("LIVE_TRADING_ARMED", "NO") == "YES"
        
        if yaml_live_flag and env_live_armed:
            self.enable_live_trading = True
            logger.warning("!!! LIVE TRADING FULLY ARMED & ENABLED !!! Real orders WILL be sent.")
        else:
            self.enable_live_trading = False
            logger.info("Live trading disabled. Orders will be MOCKED.")

        gmo_secrets = secrets.get('gmo', {})
        self.api_key = gmo_secrets.get('api_key')
        self.api_secret = gmo_secrets.get('api_secret')
        
        self.public_url = gmo_secrets.get('base_url_public', DEFAULT_FX_PUBLIC_URL)
        self.private_url = gmo_secrets.get('base_url_private', DEFAULT_FX_PRIVATE_URL)
        self.timeout = 10

        # Swap Settings
        swap_conf: dict = config.get("manual_swap_settings", {})
        self.swap_updated_at = swap_conf.get("updated_at", "2000-01-01")
        self.swap_overrides = swap_conf.get("overrides", {})
        
        self._check_swap_freshness()

    def _check_swap_freshness(self):
        try:
            updated_date = datetime.strptime(self.swap_updated_at, "%Y-%m-%d")
            days_diff = (datetime.now() - updated_date).days
            if days_diff > 14:
                logger.critical(f"CRITICAL: Swap settings are too old ({days_diff} days).")
            elif days_diff > 7:
                logger.warning(f"WARNING: Swap settings are {days_diff} days old.")
        except ValueError:
            logger.error("Invalid date format in manual_swap_settings.updated_at")

    def _get_header(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise ValueError("API Key/Secret required for Private API.")

        timestamp = str(int(time.time() * 1000))
        # GMO仕様: GETの場合 body は空文字で署名する
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
                # Privateリクエストは必ず署名ヘッダを付与する
                if method == "POST" and params:
                    body_str = json.dumps(params)
                
                # GETの場合、GMO仕様ではクエリパラメータ(?symbol=...)は署名対象外。
                # path(=endpoint) と body="" で署名を作成する。
                headers = self._get_header(method, endpoint, body_str)
            
            if method == "GET":
                # paramsはrequests側でURLクエリとして付与される
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            else:
                response = requests.post(url, data=body_str, headers=headers, timeout=self.timeout)

            response.raise_for_status()
            data = response.json()

            if data.get("status") != 0:
                messages = data.get("messages", [])
                # ★修正: message ではなく message_string を取得する
                error_code = messages[0].get("message_code") if messages else "UNKNOWN"
                error_msg = messages[0].get("message_string") if messages else "Unknown Error"
                raise Exception(f"GMO API Error [{error_code}]: {error_msg}")

            return data.get("data")

        except Exception as e:
            logger.error(f"Request Failed ({endpoint}): {e}")
            raise

    # --- BrokerClient Impl ---

    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        data = self._request("GET", "/v1/ticker", params={"symbol": pair}, private=False)
        item = next((d for d in data if d["symbol"] == pair), None)

        if item is None:
            raise ValueError(f"[MarketData] Ticker data for symbol '{pair}' not found in API response.")

        overrides = self.swap_overrides.get(pair, {})
        swap_l = float(overrides.get("long", 0.0))
        swap_s = float(overrides.get("short", 0.0))
        
        if swap_l != 0.0 or swap_s != 0.0:
            logger.info(f"[MarketData] Swap Override for {pair}: L={swap_l}/S={swap_s}")

        return MarketSnapshot(
            pair=item["symbol"],
            timestamp=datetime.now(timezone.utc),
            bid=float(item["bid"]),
            ask=float(item["ask"]),
            swap_long_per_day=swap_l,
            swap_short_per_day=swap_s,
            realized_vol_24h=None
        )

    def get_positions(self) -> List[PositionSummary]:
        """
        全保有建玉サマリーを取得
        修正: symbol指定なしでエラーになる場合は、configのtarget_pairsをループして取得
        """
        all_positions = []
        target_pairs = self.config.get("target_pairs", ["MXN_JPY"])

        for pair in target_pairs:
            try:
                # ★修正: symbolを指定してリクエスト
                data = self._request("GET", "/v1/positionSummary", params={"symbol": pair}, private=True)
                
                if not data or "list" not in data:
                    continue

                for item in data["list"]:
                    side = "LONG" if item["side"] == "BUY" else "SHORT"
                    amt = float(item["sumOpenSize"])
                    if amt <= 0: continue
                    
                    pnl = float(item.get("lossGain", 0.0)) + float(item.get("totalSwap", 0.0))
                    all_positions.append(PositionSummary(
                        pair=item["symbol"], side=side, amount=amt,
                        avg_entry_price=float(item["averagePositionRate"]),
                        current_price=0.0, unrealized_pnl=pnl, leverage=25.0
                    ))
            except Exception as e:
                logger.error(f"Failed to fetch positions for {pair}: {e}")
                # 一つのペアで失敗しても他は続ける
                continue
                
        return all_positions

    def get_account_state(self) -> Any:
        data = self._request("GET", "/v1/account/assets", private=True)
        equity = float(data.get("equity", data.get("netAssets", 0.0)))
        used = float(data.get("margin", 0.0))
        try:
            ratio = float(str(data.get("marginRatio", "0"))) / 100.0
        except:
            ratio = 9.99
        return {"balance": equity, "margin_used": used, "leverage_max": 25.0, "margin_maintain_pct": ratio}

    def place_order(self, decision: AiAction) -> Any:
        if not decision.units or decision.units <= 0:
            logger.warning("Order units invalid. Skipping.")
            return {"status": "SKIPPED"}

        params = {
            "symbol": decision.target_pair,
            "side": "BUY" if decision.action == "BUY" else "SELL",
            "executionType": "MARKET",
            "size": str(int(decision.units))
        }
        logger.info(f"[GMO] Sending Order: {params}")
        
        if self.enable_live_trading:
            return self._request("POST", "/v1/order", params=params, private=True)
        else:
            return {"status": "MOCK_SENT", "id": "mock_id"}

    def close_position(self, pair: str, amount: Optional[float] = None) -> Any:
        logger.info(f"[GMO] Closing all positions for {pair}...")
        
        try:
            data = self._request("GET", "/v1/openPositions", params={"symbol": pair}, private=True)
        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            return {"status": "FAILED_FETCH"}

        if not data or "list" not in data or len(data["list"]) == 0:
            logger.info("No open positions found.")
            return {"status": "NO_POSITIONS"}

        results = []
        for i, pos in enumerate(data["list"]):
            if i > 0: time.sleep(1.2)
            
            close_params = {
                "executionType": "MARKET",
                "symbol": pair,
                "side": "SELL" if pos["side"] == "BUY" else "BUY",
                "settlePosition": [{"positionId": pos["positionId"], "size": str(pos["size"])}]
            }
            
            try:
                if self.enable_live_trading:
                    res = self._request("POST", "/v1/closeOrder", params=close_params, private=True)
                    results.append(res)
                else:
                    results.append({"status": "MOCK_CLOSED"})
            except Exception as e:
                logger.error(f"Close failed {pos['positionId']}: {e}")
                results.append({"error": str(e)})

        if self.enable_live_trading:
            time.sleep(1.0)
            check = self._request("GET", "/v1/openPositions", params={"symbol": pair}, private=True)
            if len(check.get("list", [])) > 0:
                logger.critical("⚠️ Partial Failure: Positions remain!")
                return {"status": "PARTIAL_FAILURE", "details": results}

        return {"status": "CLOSED_ALL", "details": results}
    