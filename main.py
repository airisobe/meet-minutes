import hmac
import os

import anthropic
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

CHANNEL_MAP = {
    "[ONLINE] murmo - Weekly Marketing Sync": "C08MHTH29BR",
    "［ONLINE］Chamadhi US Weekly": "C08S4GS02RG",
    "[ONLINE] weekly mtg - Reina": "C09G09ZT8F7",
    "default": "C0AG7SAK8MR",
}

SUMMARY_PROMPT = """\
以下は会議の文字起こしです。日本語で以下の3項目を簡潔にまとめてください。

## 会議サマリー
会議全体の要約を箇条書きで記載

## 決定事項
会議中に決定された事項を箇条書きで記載（なければ「特になし」）

## ネクストアクション
今後の対応事項を担当者とともに箇条書きで記載（なければ「特になし」）

---
会議タイトル: {title}
参加者: {participants}

文字起こし:
{transcript}
"""


def resolve_channel(title):
    """会議名（title）からSlackチャンネルを決定する。完全一致→部分一致→defaultの順。"""
    if title in CHANNEL_MAP:
        return CHANNEL_MAP[title]
    for key, channel in CHANNEL_MAP.items():
        if key == "default":
            continue
        if key in title or title in key:
            return channel
    return CHANNEL_MAP["default"]


def generate_summary(title, participants, transcript):
    """Claude APIで会議サマリーを生成する。"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    participant_names = ", ".join(
        p if isinstance(p, str) else p.get("displayName", p.get("name", p.get("email", "")))
        for p in participants
    )
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": SUMMARY_PROMPT.format(
                    title=title,
                    participants=participant_names,
                    transcript=transcript,
                ),
            }
        ],
    )
    return message.content[0].text


def post_to_slack(channel, title, summary):
    """Slack Bot Tokenでメッセージを投稿する。"""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={
            "channel": channel,
            "text": f"*{title}*\n\n{summary}",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error')}")
    return data


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def verify_token():
    """AuthorizationヘッダーのBearerトークンを検証する。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[len("Bearer "):]
    return hmac.compare_digest(token, WEBHOOK_SECRET)


@app.route("/webhook/fireflies", methods=["POST"])
def webhook_fireflies():
    if not verify_token():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(force=True)

    title = payload.get("title", "無題の会議")
    participants = payload.get("participants", [])
    transcript = payload.get("transcript", "")

    if not transcript:
        return jsonify({"error": "transcript is empty"}), 400

    channel = resolve_channel(title)
    if not channel:
        return jsonify({"error": "no matching channel found"}), 400

    summary = generate_summary(title, participants, transcript)
    post_to_slack(channel, title, summary)

    return jsonify({"status": "ok", "channel": channel})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
