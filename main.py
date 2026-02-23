import json
import logging
import os

import anthropic
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
FIREFLIES_API_KEY = os.environ["FIREFLIES_API_KEY"]

FIREFLIES_GRAPHQL_URL = "https://api.fireflies.ai/graphql"
FIREFLIES_TRANSCRIPT_QUERY = """
query Transcript($transcriptId: String!) {
  transcript(id: $transcriptId) {
    title
    participants
    sentences {
      speaker_name
      text
    }
  }
}
"""

CHANNEL_MAP = {
    "[ONLINE] murmo - Weekly Marketing Sync": "C08MHTH29BR",
    "［ONLINE］Chamadhi US Weekly": "C08S4GS02RG",
    "[ONLINE] weekly mtg - Reina": "C09G09ZT8F7",
    "BE SEKIRARA LOUNGE - Hanano 定例": "C0A9T9MBNBW",
    "SEKIRARA / Chamadhi weekly": "C09KSKV8T6C",
    "SEKIRARA weekly with Hinano": "C0A8SCR85V2",
    "default": "C0AG7SAK8MR",
}

SUMMARY_PROMPT = """\
以下は会議の文字起こしです。日本語で以下の3セクションに分けて簡潔にまとめてください。
出力はSlackに投稿するため、以下のフォーマットルールを厳守してください：
- 見出しには # や ## を使わない
- 太字には **ではなく** *テキスト* を使う（Slack mrkdwn形式）
- 箇条書きは「• 」（中黒＋半角スペース）で始める
- セクション間は空行1行で区切る

以下の形式で出力してください：

:memo: *会議サマリー*
• 要約1
• 要約2

:white_check_mark: *決定事項*
• 決定事項1（なければ「特になし」）

:arrow_forward: *ネクストアクション*
• 【担当者名】対応内容（なければ「特になし」）

---
会議タイトル: {title}
参加者: {participants}

文字起こし:
{transcript}
"""


def fetch_transcript(meeting_id):
    """Fireflies GraphQL APIから文字起こしを取得する。"""
    resp = requests.post(
        FIREFLIES_GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {FIREFLIES_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "query": FIREFLIES_TRANSCRIPT_QUERY,
            "variables": {"transcriptId": meeting_id},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Fireflies API error: {data['errors']}")
    return data["data"]["transcript"]


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
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":calendar: {title}", "emoji": True},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        },
    ]
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={
            "channel": channel,
            "text": f"{title}\n\n{summary}",
            "blocks": blocks,
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


@app.route("/webhook/fireflies", methods=["POST"])
def webhook_fireflies():
    payload = request.get_json(force=True)
    app.logger.info("Fireflies webhook payload: %s", json.dumps(payload, ensure_ascii=False))

    meeting_id = payload.get("meetingId")
    if not meeting_id:
        return jsonify({"error": "meetingId is missing"}), 400

    transcript_data = fetch_transcript(meeting_id)
    app.logger.info("Fireflies transcript data: %s", json.dumps(transcript_data, ensure_ascii=False))

    title = transcript_data.get("title", "無題の会議")
    participants = transcript_data.get("participants") or []
    sentences = transcript_data.get("sentences") or []
    transcript = "\n".join(
        f"{s.get('speaker_name', '不明')}: {s.get('text', '')}" for s in sentences
    )

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
