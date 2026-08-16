"""
LINE自動返信ボット - お父さん向け
認知症のお父様からの繰り返しの質問に、家族の代わりに優しく返答するボットです。
"""

import os
import re
import traceback
from datetime import datetime, timedelta, timezone
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

JST = timezone(timedelta(hours=9))

def get_next_okazu_delivery_date():
    base_date = datetime(2026, 7, 22, tzinfo=JST)
    today = datetime.now(JST)
    days_diff = (today - base_date).days
    if days_diff < 0:
        return base_date
    cycles_passed = days_diff // 28
    check_date = base_date + timedelta(days=cycles_passed * 28)
    if check_date.date() == today.date():
        return check_date
    next_date = base_date + timedelta(days=(cycles_passed + 1) * 28)
    return next_date


QA_PATTERNS = [
    {
        "id": "okazu",
        "keywords": ["おかず", "オカズ", "惣菜", "そうざい", "配達", "届く", "届け", "食事"],
        "patterns": [r"おかず", r"オカズ", r"惣菜", r"そうざい", r"シリーズ", r"配達", r"届[くけ]"],
        "response_func": lambda: (
            f"おかずシリーズは4週間ごとの水曜日に届くよ！\n"
            f"次の配達日は {get_next_okazu_delivery_date().strftime('%m月%d日（水）')} だよ。\n"
            f"届いたら冷凍庫に入れてね"
        ),
    },
    {
        "id": "license",
        "keywords": ["免許", "免許証", "運転免許", "身分証", "身分証明"],
        "patterns": [r"免許", r"身分証", r"運転"],
        "response": "免許証は身分証明書に切り替えたよ！今度会うときに渡すから安心してね",
    },
    {
        "id": "nomura",
        "keywords": ["野村", "証券", "のむら"],
        "patterns": [r"野村", r"のむら"],
        "response": "野村のカードの件だけど、お父さんが何回も電話したから、\n野村から直接ご家族で保管してくださいってお願いされたんだよ。\nあとネットに切り替わってるから、今度一緒に来店しようね",
    },
    {
        "id": "money_manage",
        "keywords": ["管理", "勝手に", "お金管理"],
        "patterns": [r"(勝手|かって).{0,5}(管理|お金|金)", r"(なんで|なぜ|どうして).{0,5}(管理|お金|金)", r"お?金.{0,3}管理"],
        "response": "お医者さんから認知症の診断が出たから、\nお医者さんの指示で家族が管理することになったんだよ。\n心配しないで大丈夫だよ。",
    },
    {
        "id": "fight",
        "keywords": ["喧嘩", "けんか", "ケンカ", "怒って", "無視", "返事ない", "返信ない", "既読"],
        "patterns": [r"(喧嘩|けんか|ケンカ)", r"怒って", r"無視", r"(返事|返信).{0,3}(ない|無い|くれない)", r"既読"],
        "response": "喧嘩なんてしてないよ！安心して\nみんな仕事で忙しいから日中はLINE返せないだけだよ。\n夜になったら見るからね！",
    },
    {
        "id": "payment",
        "keywords": ["支払", "引き落とし", "引落", "請求", "払い", "光熱費", "家賃", "電気", "ガス", "水道"],
        "patterns": [r"支払", r"引き?落", r"請求", r"(光熱費|家賃|電気|ガス|水道|電話)", r"払[いえう]", r"どうなって"],
        "response": "支払い関係は全部自動引き落としに変更したから、\nすべて大丈夫だよ！心配しないでね\n何も手続きしなくてOKだよ。",
    },
]


def find_matching_response(text):
    text_normalized = text.strip().lower()
    for qa in QA_PATTERNS:
        for keyword in qa["keywords"]:
            if keyword.lower() in text_normalized:
                if "response_func" in qa:
                    return qa["response_func"]()
                return qa["response"]
    for qa in QA_PATTERNS:
        for pattern in qa["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                if "response_func" in qa:
                    return qa["response_func"]()
                return qa["response"]
    return None


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error handling webhook: {e}")
        app.logger.error(traceback.format_exc())
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_text = event.message.text
        response = find_matching_response(user_text)
        if response:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response)],
                    )
                )
    except Exception as e:
        app.logger.error(f"Error in handle_message: {e}")
        app.logger.error(traceback.format_exc())


@app.route("/", methods=["GET"])
def health_check():
    return "LINE Bot is running!"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
