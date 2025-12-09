# FX Swap Bot (AI-Powered Carry Trade System)

GPT-5世代のAIを活用し、FXのスワップポイント（金利差益）運用を自動化するトレーディングボットです。  
GMOコインの外国為替FX APIを利用し、**「スワップ収益（インカム）を主軸にしつつ、相場急変（為替差損）リスクを抑える」**ことを目的に設計されています。

> 注意：本ツールは利益を保証しません。市場急変・スリッページ・API障害等により損失が発生し得ます。

---

## 🚀 特徴 (v1.0.0)

### 1) スワップ運用に最適化した「運用型ボット」
- **キャリートレード（スワップ獲得）主軸**：短期の値幅取りではなく、スワップを取りに行く前提で設計。
- **リスクオフ判定（急変回避）**：ニュース・市場指標・口座状態を材料に、危険度が高い局面は **HOLD** を優先。
- **運用を前提にした監査性**：後から「いつ・何が理由で・何をしたか」を追えるように設計（監査ログ）。

### 2) AI主導の戦略判断（ただし安全制約の下）
- AIが市場データとニュースを分析し、BUY/SELL/HOLD を提案します。
- **AIは「提案者」**であり、最終の実行可否は RiskManager の安全装置が優先します（不確実ならHOLD）。

### 3) GMOコイン特化（取引・決済・署名の癖に対応）
- GMOコイン 外国為替FX API（Private/Public）に対応。
- 決済パラメータ（`settlePosition` 等）や署名仕様に対応。

### 4) 実運用のための安全装置（Safety Firstは“運用プロセス”）
> Safety Firstは「理想」ではなく「手順と事故対応まで含む運用プロセス」です。

- **二段ロック方式（実弾誤爆防止）**  
  設定ファイル（`enable_live_trading: true`） + 環境変数（`LIVE_TRADING_ARMED=YES`）が揃わない限り、実弾発注しません。
- **最大1ポジション強制（事故防止）**  
  初期運用向けに「最大1ポジション」を強制し、ピラミッディング事故を防止。
- **Fail-Fast（異常時は止まる）**  
  決済漏れ・API異常・安全ブロック等の異常時は速やかに停止し、人間介入へ。
- **No-Retry on Private POST（誤発注事故ゼロの要）**  
  タイムアウト時の二重発注を避けるため、**Private POST（発注/決済）を自動リトライしない**設計。
- **Kill Switch**  
  危険時はAI判断を無視して強制停止・決済。
- **APIレート制限対応**  
  GMO APIの制限を遵守するレート制限・バックオフ（GET中心）。

---

## 📦 必要要件
- Python 3.14+
- GMOコイン APIキー（API Key / Secret Key）
- OpenAI APIキー
- Tavily APIキー（Web検索用）
- Discord Webhook URL（通知用）

---

## ⚙️ セットアップ

### 1) インストール
```bash
git clone https://github.com/your-repo/fx-swap-bot.git
cd fx-swap-bot

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
# または pyproject.toml を使用する場合
pip install .
