# src/adapters/gmo_broker.py
import time
import hmac
import hashlib
import json
import logging
import requests
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

from src.interfaces import BrokerClient
from src.models import MarketSnapshot, PositionSummary, AiAction, BrokerResult

logger = logging.getLogger(__name__)

DEFAULT_FX_PUBLIC_URL = 'https://forex-api.coin.z.com/public'
DEFAULT_FX_PRIVATE_URL = 'https://forex-api.coin.z.com/private'

class GmoBrokerClient(BrokerClient):
    """
    GMOコイン FX API との通信を行うアダプタークラス。
    署名生成、レート制限、二段ロック（Safety Lock）などの機能を提供する。
    """
    
    def __init__(self, config: dict, secrets: dict):
        """
        クライアントを初期化する。

        Args:
            config (dict): アプリケーション設定
            secrets (dict): APIキー等の機密情報
        """
        self.config = config
        
        # 二段ロック確認: YAML設定と環境変数の両方が一致した場合のみ実弾取引を有効化
        yaml_live_flag = config.get("enable_live_trading", False)
        env_live_armed = os.getenv("LIVE_TRADING_ARMED", "NO") == "YES"
        
        if yaml_live_flag and env_live_armed:
            self.enable_live_trading = True
            logger.warning("!!! LIVE TRADING FULLY ARMED & ENABLED !!! Real orders WILL be sent.")
        else:
            self.enable_live_trading = False
            if yaml_live_flag and not env_live_armed:
                logger.warning("Live trading configured in YAML but BLOCKED by missing env var 'LIVE_TRADING_ARMED=YES'.")
            else:
                logger.info("Live trading disabled. Orders will be MOCKED (Dry-Run).")

        gmo_secrets = secrets.get('gmo', {})
        self.api_key = gmo_secrets.get('api_key')
        self.api_secret = gmo_secrets.get('api_secret')
        
        self.public_url = gmo_secrets.get('base_url_public', DEFAULT_FX_PUBLIC_URL)
        self.private_url = gmo_secrets.get('base_url_private', DEFAULT_FX_PRIVATE_URL)
        self.timeout = 10

        # スワップ設定のロード
        swap_conf: dict = config.get("manual_swap_settings", {})
        self.swap_updated_at = swap_conf.get("updated_at", "2000-01-01")
        self.swap_overrides = swap_conf.get("overrides", {})

        # レート制限用ロック (Private API 1 req/sec)
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._min_interval = 1.1  # 安全マージンを含む待機時間
        
        self._check_swap_freshness()

    def _check_swap_freshness(self) -> None:
        """手動スワップ設定の鮮度を確認し、古い場合に警告する。"""
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
        """
        GMO API用の署名ヘッダーを生成する。

        Args:
            method (str): HTTPメソッド (GET, POST)
            path (str): APIパス
            body (str): リクエストボディ

        Returns:
            Dict[str, str]: 署名済みヘッダー
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API Key/Secret required for Private API.")

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

    def _wait_for_rate_limit(self) -> None:
        """レート制限を遵守するため、必要に応じてスレッドをブロックする。"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                sleep_time = self._min_interval - elapsed
                time.sleep(sleep_time)
            self._last_request_time = time.time()

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None, private: bool = False) -> Any:
        """
        APIリクエストを実行する。レート制限、リトライ、エラーハンドリングを含む。

        Args:
            method (str): HTTPメソッド
            endpoint (str): APIエンドポイント
            params (Optional[dict]): パラメータ
            private (bool): Private APIか否か

        Returns:
            Any: レスポンスデータ

        Raises:
            Exception: APIエラーまたは通信エラー
        """
        # HTTP送信直前の最終安全ガード
        if method != "GET" and private:
            if not self.enable_live_trading:
                raise RuntimeError("Safety Block: Attempted Private POST without armed live trading.")
            if os.getenv("LIVE_TRADING_ARMED") != "YES":
                raise RuntimeError("Safety Block: LIVE_TRADING_ARMED is missing.")

        base_url = self.private_url if private else self.public_url
        url = base_url + endpoint
        
        max_retries = 5
        backoff = 0.5
        
        for attempt in range(max_retries):
            try:
                if private:
                    self._wait_for_rate_limit()

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
                    error_code = messages[0].get("message_code") if messages else "UNKNOWN"
                    error_msg = messages[0].get("message_string") if messages else "Unknown Error"
                    raise Exception(f"GMO API Error [{error_code}]: {error_msg}")

                return data.get("data")

            except (requests.Timeout, requests.ConnectionError) as e:
                logger.warning(f"Network Error ({attempt+1}/{max_retries}): {e}")
            except requests.HTTPError as e:
                if e.response.status_code in [429, 500, 502, 503, 504]:
                    logger.warning(f"HTTP Error {e.response.status_code} ({attempt+1}/{max_retries})")
                else:
                    raise
            except Exception as e:
                logger.error(f"Request Failed ({endpoint}): {e}")
                raise

            time.sleep(backoff)
            backoff *= 2.0

        raise Exception(f"Max retries exceeded for {endpoint}")

    def get_market_snapshot(self, pair: str) -> MarketSnapshot:
        """市場スナップショットを取得する。"""
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
        """全ポジションを取得する。"""
        all_positions = []
        target_pairs = self.config.get("target_pairs", ["MXN_JPY"])

        for pair in target_pairs:
            try:
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
                continue
                
        return all_positions

    def get_account_state(self) -> Any:
        """口座状態を取得する。"""
        data = self._request("GET", "/v1/account/assets", private=True)
        equity = float(data.get("equity", data.get("netAssets", 0.0)))
        used = float(data.get("margin", 0.0))
        try:
            ratio = float(str(data.get("marginRatio", "0"))) / 100.0
        except:
            ratio = 9.99
        return {"balance": equity, "margin_used": used, "leverage_max": 25.0, "margin_maintain_pct": ratio}

    def place_order(self, decision: AiAction) -> BrokerResult:
        """
        発注を実行する。Dry-Run時は送信せずステータスのみ返す。

        Args:
            decision (AiAction): AIの決定

        Returns:
            BrokerResult: 実行結果
        """
        if not decision.units or decision.units <= 0:
            return BrokerResult(status="HOLD", details={"reason": "Invalid units"})

        if not self.enable_live_trading:
            return BrokerResult(
                status="DRY_RUN_NOT_SENT",
                details={
                    "pair": decision.target_pair,
                    "action": decision.action,
                    "units": decision.units,
                    "msg": "Order skipped due to dry-run mode."
                }
            )

        params = {
            "symbol": decision.target_pair,
            "side": "BUY" if decision.action == "BUY" else "SELL",
            "executionType": "MARKET",
            "size": str(int(decision.units))
        }
        
        try:
            logger.info(f"[GMO] Sending Order: {params}")
            res = self._request("POST", "/v1/order", params=params, private=True)
            order_id = str(res.get("orderId", ""))
            return BrokerResult(
                status="EXECUTED",
                order_id=order_id,
                details={"raw": res}
            )

        except Exception as e:
            logger.error(f"Place Order Failed: {e}")
            return BrokerResult(
                status="ERROR",
                details={"error": str(e)}
            )

    def close_position(self, pair: str, amount: Optional[float] = None) -> BrokerResult:
        """
        ポジションを決済する。Dry-Run時は実際に決済せず、建玉確認のみ行う。

        Args:
            pair (str): 通貨ペア
            amount (Optional[float]): 数量

        Returns:
            BrokerResult: 決済結果
        """
        try:
            data = self._request("GET", "/v1/openPositions", params={"symbol": pair}, private=True)
        except Exception as e:
            return BrokerResult(status="ERROR", details={"error": f"Fetch positions failed: {e}"})

        pos_list = data.get("list", [])
        if not pos_list:
            return BrokerResult(status="CLOSED_ALL", details={"msg": "No positions to close."})

        # Dry-Run時の偽成功防止
        if not self.enable_live_trading:
            count = len(pos_list)
            return BrokerResult(
                status="DRY_RUN_NOT_CLOSED",
                details={
                    "remaining_count": count,
                    "msg": f"Found {count} positions but cannot close in dry-run mode."
                }
            )

        results = []
        partial_error = False

        for i, pos in enumerate(pos_list):
            if i > 0: time.sleep(1.1)
            
            close_params = {
                "executionType": "MARKET",
                "symbol": pair,
                "side": "SELL" if pos["side"] == "BUY" else "BUY",
                "settlePosition": [{"positionId": pos["positionId"], "size": str(pos["size"])}]
            }
            
            try:
                res = self._request("POST", "/v1/closeOrder", params=close_params, private=True)
                results.append(res)
            except Exception as e:
                logger.error(f"Close failed {pos['positionId']}: {e}")
                results.append({"error": str(e), "positionId": pos["positionId"]})
                partial_error = True

        # 決済後の残存確認
        time.sleep(1.0)
        try:
            check = self._request("GET", "/v1/openPositions", params={"symbol": pair}, private=True)
            remaining = check.get("list", [])
            
            if len(remaining) > 0:
                logger.critical(f"⚠️ Partial Failure: {len(remaining)} positions remain for {pair}!")
                return BrokerResult(
                    status="PARTIAL_FAILURE",
                    details={"results": results, "remaining_count": len(remaining)}
                )
        except Exception:
            pass 

        if partial_error:
             return BrokerResult(status="PARTIAL_FAILURE", details={"results": results})
             
        return BrokerResult(status="CLOSED_ALL", details={"results": results})