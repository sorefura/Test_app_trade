# src/ai_client.py
import os
import logging
from typing import Optional
from pathlib import Path

from openai import OpenAI, APIConnectionError, RateLimitError
from pydantic import ValidationError

from src.models import AiInputPayload, AiOutputPayload

logger = logging.getLogger(__name__)

class GPTClient:
    """
    OpenAI APIと通信し、市場分析結果を取得するクライアント。
    Structured Outputsを使用し、厳密な型定義に基づいたJSONレスポンスを保証する。
    """

    def __init__(self, 
                 api_key: str, 
                 model_name: str = "gpt-5.1", 
                 prompt_path: str = "config/system_prompt.txt"):
        """
        GPTClientを初期化する。

        Args:
            api_key (str): OpenAI APIキー
            model_name (str): デフォルトで使用するモデル名
            prompt_path (str): システムプロンプトファイルのパス
        """
        if not api_key:
            raise ValueError("API Key is required for GPTClient.")
            
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name
        self.system_prompt_template = self._load_system_prompt(prompt_path)
        
        logger.info(f"GPTClient initialized with default model: {self.model_name}")

    def _load_system_prompt(self, path: str) -> str:
        """
        外部ファイルからシステムプロンプトを読み込む。

        Args:
            path (str): ファイルパス

        Returns:
            str: プロンプト内容
        """
        try:
            return Path(path).read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.error(f"Failed to load system prompt from {path}: {e}")
            return "You are a professional FX trader. Analyze the input and output JSON for {pair}."

    def analyze(self, payload: AiInputPayload, model: Optional[str] = None) -> AiOutputPayload:
        """
        市場データをAIに送信し、売買判断を取得する。

        Args:
            payload (AiInputPayload): 分析対象データ
            model (Optional[str]): 使用するモデル（指定がなければデフォルト）

        Returns:
            AiOutputPayload: 分析結果

        Raises:
            APIConnectionError: ネットワークエラー
            ValidationError: レスポンス形式エラー
        """
        target_model = model if model else self.model_name
        current_pair = payload.market.pair
        
        try:
            system_prompt = self.system_prompt_template.format(pair=current_pair)
        except Exception:
            system_prompt = self.system_prompt_template.replace("{pair}", current_pair)

        logger.info(f"Sending analysis request to AI ({target_model}) for {current_pair}. Request ID: {payload.request_id}")

        try:
            completion = self.client.beta.chat.completions.parse(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload.model_dump_json()},
                ],
                response_format=AiOutputPayload,
            )

            result: AiOutputPayload = completion.choices[0].message.parsed
            
            if not result:
                raise ValueError("Received empty response from AI model.")

            logger.info(f"AI Analysis completed. Action: {result.decision.action}, Confidence: {result.decision.confidence}")
            return result

        except (APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API Network Error: {e}")
            raise
        except ValidationError as e:
            logger.error(f"AI Response Validation Error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in AI analysis: {e}")
            raise
    