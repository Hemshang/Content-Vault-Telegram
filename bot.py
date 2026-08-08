import os
import asyncio
import httpx

from fastapi import FastAPI, Request, HTTPException


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]

PUBLIC_CHANNEL_ID = os.environ["PUBLIC_CHANNEL_ID"]

PRIVATE_CHANNEL_ID = os.environ["PRIVATE_CHANNEL_ID"]

OWNER_ID = int(os.environ["OWNER_ID"])

PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")

WEBHOOK_SECRET = os.environ.get(
    "WEBHOOK_SECRET",
    "change-this-secret"
)

DELETE_AFTER = int(
    os.environ.get("DELETE_AFTER_SECONDS", "300")
)


# Telegram API
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()


# =========================================================
# TELEGRAM API HELPER
# =========================================================

async def telegram(method, payload=None):

    async with httpx.AsyncClient(timeout=60) as client:

        response = await client.post(
            f"{API}/{method}",
            json=payload or {}
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get(
                    "description",
                    "Telegram API error"
                )
            )

        return data["result"]


# =========================================================
# SET WEBHOOK WHEN SERVER STARTS
# =========================================================

@app.on_event("startup")
async def startup():

    await telegram(
        "setWebhook",
        {
            "url": f"{PUBLIC_URL}/webhook",

            "secret_token": WEBHOOK_SECRET,

            "allowed_updates": [
                "message",
                "callback_query",
                "channel_post"
            ]
        }
    )

    print("Webhook configured successfully.")


# =========================================================
# DELETE USER VIDEO AFTER 5 MINUTES
# =========================================================

async def delete_later(
    chat_id,
    message_id
):

    await asyncio.sleep(DELETE_AFTER)

    try:

        await telegram(
            "deleteMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id
            }
        )

        print(
            f"Deleted message {message_id}"
        )

    except Exception as error:

        print(
            "Delete error:",
            error
        )


# =========================================================
# QUALITY BUTTONS
# =========================================================

def make_keyboard(message_ids):

    labels = [
        "480P",
        "720P",
        "1080P",
        "4K"
    ]

    buttons = []

    for label, message_id in zip(
        labels,
        message_ids
    ):

        if message_id and message_id != "-":

            buttons.append(
                {
                    "text": label,
                    "callback_data":
                        f"get:{message_id}"
                }
            )


    # 2 buttons per row

    rows = []

    for i in range(0, len(buttons), 2):

        rows.append(
            buttons[i:i + 2]
        )


    return {
        "inline_keyboard": rows
    }


# =========================================================
# COPY VIDEO FROM PRIVATE CHANNEL
# =========================================================

async def send_video_to_user(
    user_id,
    source_message_id,
    callback_query_id
):

    # Remove Telegram's loading spinner

    await telegram(
        "answerCallbackQuery",
        {
            "callback_query_id":
                callback_query_id,

            "text":
                "Fetching video..."
        }
    )


    # Copy the message from private channel

    sent_message = await telegram(
        "copyMessage",
        {
            "chat_id":
                user_id,

            "from_chat_id":
                PRIVATE_CHANNEL_ID,

            "message_id":
                int(source_message_id),

            "protect_content":
                True
        }
    )


    new_message_id = (
        sent_message["message_id"]
    )


    # Schedule deletion after 5 minutes

    asyncio.create_task(
        delete_later(
            user_id,
            new_message_id
        )
    )


# =========================================================
# HOME PAGE / HEALTH CHECK
# =========================================================

@app.get("/")
async def home():

    return {
        "status": "running"
    }


# =========================================================
# WEBHOOK
# =========================================================

@app.post("/webhook")
async def webhook(request: Request):

    # Security check

    supplied_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if supplied_secret != WEBHOOK_SECRET:

        raise HTTPException(
            status_code=403,
            detail="Forbidden"
        )


    update = await request.json()


    # =====================================================
    # CALLBACK BUTTON
    # =====================================================

    if "callback_query" in update:

        query = update["callback_query"]

        data = query.get(
            "data",
            ""
        )


        if data.startswith("get:"):

            source_message_id = (
                data.split(":", 1)[1]
            )

            user_id = query["from"]["id"]


            await send_video_to_user(
                user_id,
                source_message_id,
                query["id"]
            )


        return {
            "ok": True
        }


    # =====================================================
    # NORMAL PRIVATE MESSAGE
    # =====================================================

    if "message" in update:

        message = update["message"]

        user = message.get(
            "from",
            {}
        )

        user_id = user.get(
            "id"
        )

        text = message.get(
            "text",
            ""
        )


        # -------------------------------------------------
        # /start
        # -------------------------------------------------

        if text.startswith("/start"):

            await telegram(
                "sendMessage",
                {
                    "chat_id":
                        user_id,

                    "text":
                        "Bot is working.\n\n"
                        "Use the buttons in the public channel."
                }
            )


        # -------------------------------------------------
        # /help
        # -------------------------------------------------

        elif text.startswith("/help"):

            await telegram(
                "sendMessage",
                {
                    "chat_id":
                        user_id,

                    "text":
                        "Available commands:\n\n"
                        "/start\n"
                        "/help\n"
                        "/myid\n"
                        "/publish"
                }
            )


        # -------------------------------------------------
        # /myid
        # -------------------------------------------------

        elif text.startswith("/myid"):

            await telegram(
                "sendMessage",
                {
                    "chat_id":
                        user_id,

                    "text":
                        f"Your Telegram ID:\n{user_id}"
                }
            )


        # -------------------------------------------------
        # /publish
        # -------------------------------------------------

        elif text.startswith("/publish"):

            # Only owner can publish

            if user_id != OWNER_ID:

                await telegram(
                    "sendMessage",
                    {
                        "chat_id":
                            user_id,

                        "text":
                            "You are not authorized."
                    }
                )

                return {
                    "ok": True
                }


            # Poster must be replied to

            replied = message.get(
                "reply_to_message"
            )


            if not replied:

                await telegram(
                    "sendMessage",
                    {
                        "chat_id":
                            user_id,

                        "text":
                            "Reply /publish to a poster photo."
                    }
                )

                return {
                    "ok": True
                }


            if "photo" not in replied:

                await telegram(
                    "sendMessage",
                    {
                        "chat_id":
                            user_id,

                        "text":
                            "The replied message must contain a photo."
                    }
                )

                return {
                    "ok": True
                }


            # ------------------------------------------------
            # Parse:
            #
            # /publish Title | 101 | 102 | 103 | 104
            # ------------------------------------------------

            command = text[
                len("/publish"):
            ].strip()


            parts = [
                item.strip()
                for item in command.split("|")
            ]


            if len(parts) != 5:

                await telegram(
                    "sendMessage",
                    {
                        "chat_id":
                            user_id,

                        "text":
                            "Correct format:\n\n"
                            "/publish Title | "
                            "480_ID | "
                            "720_ID | "
                            "1080_ID | "
                            "4K_ID"
                    }
                )

                return {
                    "ok": True
                }


            title = parts[0]

            message_ids = parts[1:]


            # Highest resolution Telegram photo

            poster_file_id = (
                replied["photo"][-1]["file_id"]
            )


            # ------------------------------------------------
            # Publish to public channel
            # ------------------------------------------------

            await telegram(
                "sendPhoto",
                {
                    "chat_id":
                        PUBLIC_CHANNEL_ID,

                    "photo":
                        poster_file_id,

                    "caption":
                        title,

                    "reply_markup":
                        make_keyboard(
                            message_ids
                        )
                }
            )


            await telegram(
                "sendMessage",
                {
                    "chat_id":
                        user_id,

                    "text":
                        "✅ Published successfully."
                }
            )


    # =====================================================
    # CHANNEL POST
    # =====================================================

    if "channel_post" in update:

        channel_post = update[
            "channel_post"
        ]

        channel = channel_post[
            "chat"
        ]

        message_id = channel_post[
            "message_id"
        ]

        print(
            "CHANNEL POST:"
        )

        print(
            "Channel:",
            channel["id"]
        )

        print(
            "Message ID:",
            message_id
        )


    return {
        "ok": True
    }