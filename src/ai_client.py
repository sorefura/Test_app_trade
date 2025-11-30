# src/ai_client.py
import os
import logging
from typing import Optional
from pathlib import Path

from openai import OpenAI, APIConnectionError, RateLimitError
from pydantic import ValidationError

from src.models import AiInputPayload, AiOutputPayload, AiAction

logger = logging.getLogger(__name__)

class GPTClient:
    """
    OpenAI API (GPT-5.1等) と通信し、市場分析を行うクライアントクラス。
    Structured Outputs (Pydantic対応) を利用して、堅牢なJSONパースを実現する。
    """

    def __init__(self, 
                 api_key: str, 
                 model_name: str = "gpt-4o-mini", # デフォルト
                 prompt_path: str = "config/system_prompt.txt"):
        
        if not api_key:
            raise ValueError("API Key is required for GPTClient.")
            
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name
        # プロンプトテンプレートとして読み込む
        self.system_prompt_template = self._load_system_prompt(prompt_path)
        
        logger.info(f"GPTClient initialized with default model: {self.model_name}")

    def _load_system_prompt(self, path: str) -> str:
        """外部ファイルからシステムプロンプトを読み込む"""
        try:
            # ★重要: UTF-8指定
            return Path(path).read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.error(f"Failed to load system prompt from {path}: {e}")
            return "You are a professional FX trader. Analyze the input and output JSON for {pair}."

    def analyze(self, payload: AiInputPayload, model: Optional[str] = None) -> AiOutputPayload:
        """
        市場データをAIに送信し、売買判断を取得する。
        Args:
            payload: AIへの入力データ
            model: 使用するモデル名 (Noneの場合はinit時のデフォルトを使用)
        """
        target_model = model if model else self.model_name
        
        # ★修正: プロンプト内の {pair} を動的に置換
        # payload.market.pair には "MXN_JPY" などが入っている
        current_pair = payload.market.pair
        
        try:
            # formatメソッドで {pair} を置換
            system_prompt = self.system_prompt_template.format(pair=current_pair)
        except KeyError as e:
            # プロンプトファイルに変な {} が含まれていて置換失敗した場合のガード
            logger.warning(f"Prompt formatting failed ({e}). Using raw template.")
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
        