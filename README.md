# meet-minutes

Fireflies.ai の Webhook を受け取り、Claude API で会議サマリーを生成して Slack に投稿する Flask アプリ。

## Render へのデプロイ手順

### 1. GitHubリポジトリを用意

```bash
cd meet-minutes
git init
git add .
git commit -m "initial commit"
gh repo create meet-minutes --private --source=. --push
```

### 2. Render でサービスを作成

1. [Render Dashboard](https://dashboard.render.com/) にログイン
2. **New > Web Service** をクリック
3. GitHub リポジトリ `meet-minutes` を接続
4. 設定は `render.yaml` から自動で読み込まれる

### 3. 環境変数を設定

Render Dashboard の **Environment** タブで以下を設定：

| 変数名 | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic の API キー |
| `SLACK_BOT_TOKEN` | Slack Bot Token（`xoxb-...`） |
| `WEBHOOK_SECRET` | 任意のトークン文字列（Fireflies 側の Auth header と一致させる） |

### 4. Fireflies の Webhook を設定

1. [Fireflies Settings > Webhooks](https://app.fireflies.ai/integrations/custom/webhook) を開く
2. **Webhook URL**: `https://<your-render-app>.onrender.com/webhook/fireflies`
3. **Authorization**: `Bearer <WEBHOOK_SECRET と同じ値>`

### エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/health` | ヘルスチェック |
| `POST` | `/webhook/fireflies` | Fireflies Webhook 受信（Bearer トークン認証必須） |
