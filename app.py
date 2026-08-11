"""
LINE自動返信ボット - お父さん向け
認知症のお父様からの繰り返しの質問に、家族の代わりに優しく返答するボットです。
"""

import os
import re
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

app = Flask(__name__)

# 環境変数から設定を読み込み
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# ============================================================
# おかずシリーズの次回配達日を計算する関数
# 基準日: 2025年7月22日（水曜日）から4週間ごと
# ============================================================
def get_next_okazu_delivery_date():
    """7月22日を基準に4週間ごとの水曜日の次回配達日を返す"""
    base_date = datetime(2025, 7, 22)  # 基準日（水曜日）
    today = datetime.now()
    
    # 基準日から今日までの日数を計算
    days_diff = (today - base_date).days
    
    if days_diff < 0:
        # まだ基準日前なら基準日が次回
        return base_date
    
    # 4週間 = 28日ごとのサイクル
    cycles_passed = days_diff // 28
    next_date = base_date + timedelta(days=(cycles_passed + 1) * 28)
    
    # もし今日がちょうど配達日なら今日を返す
    check_date = base_date + timedelta(days=cycles_passed * 28)
    if check_date.date() == today.date():
        return check_date
    
    return next_date


# ============================================================
# 質問パターンと返答の定義
# ============================================================
QA_PATTERNS = [
    {
        "id": "okazu",
        "keywords": ["おかず", "オカズ", "惣菜", "そうざい", "配達", "届く", "届け", "食事", "ご飯届"],
        "patterns": [
            r"おかず",
            r"オカズ",
            r"惣菜",
            r"そうざい",
            r"シリーズ",
            r"配達",
            r"届[くけ]",
        ],
        "response_func": lambda: (
            f"おかずシリーズは4週間ごとの水曜日に届くよ！\n"
            f"次の配達日は {get_next_okazu_delivery_date().strftime('%m月%d日（水）')} だよ。\n"
            f"届いたら冷蔵庫に入れてね 😊"
        ),
    },
    {
        "id": "license",
        "keywords": ["免許", "免許証", "運転免許", "身分証", "身分証明"],
        "patterns": [
            r"免許",
            r"身分証",
            r"運転",
        ],
        "response": "免許証は身分証明書に切り替えたよ！今度会うときに渡すから安心してね 👍",
    },
    {
        "id": "money_none",
        "keywords": ["お金ない", "金ない", "金がない", "お金がない", "お金足りない", "金足りない", "金欠"],
        "patterns": [
            r"お?金.{0,3}(ない|無い|足り|なくな)",
            r"金欠",
            r"(お小遣い|おこづかい).{0,3}(ない|無い|足り)",
        ],
        "response": (
            "毎週月曜日に1万円郵送してるよ！\n"
            "届いたらメモしながら1週間で計画的に使ってね。\n"
            "月曜日にポスト確認してみて 📮"
        ),
    },
    {
        "id": "nomura",
        "keywords": ["野村", "カード", "証券", "のむら"],
        "patterns": [
            r"野村",
            r"のむら",
            r"(証券|しょうけん).{0,3}カード",
        ],
        "response": (
            "野村のカードの件だけど、お父さんが何回も電話したから、\n"
            "野村から直接「ご家族で保管してください」ってお願いされたんだよ。\n"
            "あとネットに切り替わってるから、今度一緒に来店しようね 🏦"
        ),
    },
    {
        "id": "money_manage",
        "keywords": ["管理", "勝手に", "なんで", "お金管理"],
        "patterns": [
            r"(勝手|かって).{0,5}(管理|お金|金)",
            r"(なんで|なぜ|どうして).{0,5}(管理|お金|金)",
            r"お?金.{0,3}管理",
        ],
        "response": (
            "お医者さんから認知症の診断が出たから、\n"
            "お医者さんの指示で家族が管理することになったんだよ。\n"
            "だから毎週月曜日に1万円郵送してるからね。\n"
            "心配しないで大丈夫だよ 😊"
        ),
    },
    {
        "id": "fight",
        "keywords": ["喧嘩", "けんか", "ケンカ", "怒って", "無視", "返事ない", "返信ない", "既読"],
        "patterns": [
            r"(喧嘩|けんか|ケンカ)",
            r"怒って",
            r"無視",
            r"(返事|返信|へんじ).{0,3}(ない|無い|くれない|こない)",
            r"既読スルー",
            r"既読",
        ],
        "response": (
            "喧嘩なんてしてないよ！安心して 😊\n"
            "みんな仕事で忙しいから日中はLINE返せないだけだよ。\n"
            "夜になったら見るからね！"
        ),
    },
    {
        "id": "send_money",
        "keywords": ["送って", "振り込", "振込", "いくらか", "お金送", "金送", "お金ちょうだい", "金くれ"],
        "patterns": [
            r"(送って|おくって|振り込|振込)",
            r"いくらか",
            r"(お?金|おかね).{0,3}(くれ|ちょうだい|頂戴|ほしい|欲しい)",
        ],
        "response": (
            "毎週月曜日に1万円送ってるよ！\n"
            "届いたらメモしながら計画的に1週間使ってね。\n"
            "月曜日にポスト見てみて 📮"
        ),
    },
    {
        "id": "payment",
        "keywords": ["支払", "引き落とし", "引落", "請求", "払い", "光熱費", "家賃", "電気", "ガス", "水道"],
        "patterns": [
            r"支払",
            r"引き?落",
            r"請求",
            r"(光熱費|家賃|電気|ガス|水道|電話)",
            r"払[いえう]",
            r"どうなって",
        ],
        "response": (
            "支払い関係は全部自動引き落としに変更したから、\n"
            "すべて大丈夫だよ！心配しないでね 👌\n"
            "何も手続きしなくてOKだよ。"
        ),
    },
]


def find_matching_response(text):
    """
    受信テキストに対してマッチする返答を探す。
    キーワードマッチング → 正規表現パターンマッチングの順で判定。
    """
    text_normalized = text.strip().lower()
    
    # まずキーワードで直接マッチを試みる
    for qa in QA_PATTERNS:
        for keyword in qa["keywords"]:
            if keyword.lower() in text_normalized:
                if "response_func" in qa:
                    return qa["response_func"]()
                return qa["response"]
    
    # 次に正規表現パターンでマッチを試みる
    for qa in QA_PATTERNS:
        for pattern in qa["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                if "response_func" in qa:
                    return qa["response_func"]()
                return qa["response"]
    
    # マッチしない場合はNoneを返す（応答しない）
    return None


# ============================================================
# Webhookエンドポイント
# ============================================================
@app.route("/callback", methods=["POST"])
def callback():
    """LINE Webhookのエンドポイント"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    
    app.logger.info("Request body: " + body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature")
        abort(400)
    
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """テキストメッセージを受信したときの処理"""
    user_text = event.message.text
    
    # マッチする返答を探す
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


# ============================================================
# ヘルスチェック用エンドポイント
# ============================================================
@app.route("/", methods=["GET"])
def health_check():
    """Renderのヘルスチェック用"""
    return "LINE Bot is running! 🤖"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
