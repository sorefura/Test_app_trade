# FX Swap Bot (AI-Powered Carry Trade System)

GPT-5世代のAIを活用し、FXのスワップポイント（金利差益）運用を自動化するトレーディングボットです。
GMOコインの外貨ex APIを利用し、ファンダメンタルズ分析（Web検索含む）とテクニカル分析を組み合わせて、リスクを抑えながらスワップ益を最大化することを目指します。

## 🚀 特徴 (v1.0.0)

* **AI主導の戦略判断:**
    * `gpt-5-mini` (または `gpt-4o`) が市場データと最新ニュースを分析し、BUY/SELL/HOLD を判断。
    * **Tavily API** を利用したリアルタイムWeb検索により、最新の金利政策や要人発言を考慮。
* **堅牢なリスク管理 (Safety First):**
    * **二段ロック方式:** 設定ファイル + 環境変数の両方が揃わないと実弾発注しない安全設計。
    * **ポジション上限:** 初期運用向けに「最大1ポジション」を強制。ピラミッディング事故を防止。
    * **Kill Switch:** 証拠金維持率が悪化した場合、AI判断を無視して強制停止・決済。
    * **APIレート制限対応:** GMO APIの制限（1秒1回）を遵守するリトライ・バックオフ機能を実装。
* **GMOコイン特化:**
    * GMOコイン 外国為替FX API (Private/Public) に完全対応。
    * 特殊な決済パラメータ (`settlePosition`) や GET署名仕様に対応済み。

## 📦 必要要件

* Python 3.14+
* GMOコイン APIキー (API Key / Secret Key)
* OpenAI APIキー
* Tavily APIキー (Web検索用)
* Discord Webhook URL (通知用)

## ⚙️ セットアップ

### 1. インストール

```bash
# リポジトリのクローン
git clone [https://github.com/your-repo/fx-swap-bot.git](https://github.com/your-repo/fx-swap-bot.git)
cd fx-swap-bot

# 仮想環境の作成と有効化
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# 依存ライブラリのインストール
pip install -r requirements.txt
# または pyproject.toml を使用する場合
pip install .