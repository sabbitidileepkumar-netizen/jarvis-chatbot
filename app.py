import os
import json
import base64
import uuid
import requests

from datetime import timedelta, datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google import genai
from google.genai import types

# =========================================================
# J.A.R.V.I.S BACKEND
# =========================================================

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.permanent_session_lifetime = timedelta(days=30)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID")
JSONBIN_MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")

REDIRECT_URI = (
    "https://jarvis-chatbot-yaoh.onrender.com/auth/callback"
)

MODEL_NAME = "gemini-3.1-flash-lite"

JSONBIN_URL = (
    f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    if JSONBIN_BIN_ID
    else None
)

HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": JSONBIN_MASTER_KEY or ""
}

# Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# STORAGE
# =========================================================

def load_all_data():
    """Load the complete JSONBin database."""

    if not JSONBIN_URL or not JSONBIN_MASTER_KEY:
        return {}

    try:
        response = requests.get(
            f"{JSONBIN_URL}/latest",
            headers=HEADERS,
            timeout=8
        )

        response.raise_for_status()

        data = response.json()

        return data.get("record", {})

    except Exception as e:
        print("JSONBIN LOAD ERROR:", e)
        return {}


def save_all_data(data):
    """Save complete database to JSONBin."""

    if not JSONBIN_URL or not JSONBIN_MASTER_KEY:
        return False

    try:
        response = requests.put(
            JSONBIN_URL,
            headers=HEADERS,
            json=data,
            timeout=8
        )

        response.raise_for_status()

        return True

    except Exception as e:
        print("JSONBIN SAVE ERROR:", e)
        return False


# =========================================================
# USER
# =========================================================

def get_user_id():
    """
    Get authenticated user's Google ID.

    We intentionally use the Flask session instead of trusting
    user IDs supplied by the browser.
    """

    user = session.get("user")

    if not user:
        return None

    return user.get("id")


def get_user_record(all_data, uid):
    """Get or create a user's database record."""

    if uid not in all_data:

        all_data[uid] = {
            "memory": {},
            "personality": "",
            "conversations": {}
        }

    record = all_data[uid]

    record.setdefault("memory", {})
    record.setdefault("personality", "")
    record.setdefault("conversations", {})

    return record


# =========================================================
# MEMORY
# =========================================================

def load_memory():

    uid = get_user_id()

    if not uid:
        return {}

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    return record["memory"]


def save_memory(memory_data):

    uid = get_user_id()

    if not uid:
        return False

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    record["memory"] = memory_data

    return save_all_data(all_data)


# =========================================================
# PERSONALITY
# =========================================================

def load_personality():

    uid = get_user_id()

    if not uid:
        return ""

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    return record["personality"]


def save_personality(text):

    uid = get_user_id()

    if not uid:
        return False

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    record["personality"] = text

    return save_all_data(all_data)


# =========================================================
# CONVERSATIONS
# =========================================================

def list_conversations():

    uid = get_user_id()

    if not uid:
        return []

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    conversations = record["conversations"]

    result = []

    for cid, conversation in conversations.items():

        result.append({
            "id": cid,
            "title": conversation.get(
                "title",
                "New chat"
            ),
            "created_at": conversation.get(
                "created_at",
                ""
            ),
            "updated_at": conversation.get(
                "updated_at",
                conversation.get("created_at", "")
            )
        })

    result.sort(
        key=lambda x: x["updated_at"],
        reverse=True
    )

    return result


def get_conversation(conv_id):

    uid = get_user_id()

    if not uid or not conv_id:
        return None

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    return record["conversations"].get(conv_id)


def create_conversation():

    uid = get_user_id()

    if not uid:
        return None

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    conv_id = str(uuid.uuid4())[:8]

    now = datetime.utcnow().isoformat()

    record["conversations"][conv_id] = {

        "title": "New chat",

        "created_at": now,

        "updated_at": now,

        "messages": []
    }

    if not save_all_data(all_data):
        return None

    return conv_id


def save_conversation_messages(
    conv_id,
    messages,
    title=None
):

    uid = get_user_id()

    if not uid:
        return False

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    if conv_id not in record["conversations"]:

        now = datetime.utcnow().isoformat()

        record["conversations"][conv_id] = {

            "title": title or "New chat",

            "created_at": now,

            "updated_at": now,

            "messages": []
        }

    conversation = record["conversations"][conv_id]

    conversation["messages"] = messages

    conversation["updated_at"] = datetime.utcnow().isoformat()

    if title:
        conversation["title"] = title

    return save_all_data(all_data)


def delete_conversation(conv_id):

    uid = get_user_id()

    if not uid:
        return False

    all_data = load_all_data()

    record = get_user_record(all_data, uid)

    if conv_id in record["conversations"]:

        del record["conversations"][conv_id]

        return save_all_data(all_data)

    return False


# =========================================================
# AUTHENTICATION
# =========================================================

@app.route("/")
def home():

    return render_template("index.html")


@app.route("/login")
def login():

    google_auth_url = (

        "https://accounts.google.com/o/oauth2/v2/auth"

        f"?client_id={GOOGLE_CLIENT_ID}"

        f"&redirect_uri={REDIRECT_URI}"

        "&response_type=code"

        "&scope=openid%20email%20profile"

        "&access_type=offline"

    )

    return redirect(google_auth_url)


@app.route("/auth/callback")
def auth_callback():

    code = request.args.get("code")

    if not code:
        return "Login failed: no authorization code.", 400

    try:

        token_response = requests.post(

            "https://oauth2.googleapis.com/token",

            data={

                "code": code,

                "client_id": GOOGLE_CLIENT_ID,

                "client_secret": GOOGLE_CLIENT_SECRET,

                "redirect_uri": REDIRECT_URI,

                "grant_type": "authorization_code"
            },

            timeout=10
        )

        token_response.raise_for_status()

        token_data = token_response.json()

        access_token = token_data.get("access_token")

        if not access_token:

            return "Login failed: access token missing.", 400

        user_response = requests.get(

            "https://www.googleapis.com/oauth2/v2/userinfo",

            headers={
                "Authorization":
                f"Bearer {access_token}"
            },

            timeout=10
        )

        user_response.raise_for_status()

        userinfo = user_response.json()

        session["user"] = {

            "id": userinfo.get("id"),

            "name": userinfo.get(
                "name",
                "USER"
            ),

            "email": userinfo.get(
                "email",
                ""
            ),

            "picture": userinfo.get(
                "picture",
                ""
            )
        }

        session.permanent = True

        return redirect(url_for("home"))

    except Exception as e:

        print("GOOGLE LOGIN ERROR:", e)

        return (
            "Google authentication failed. "
            "Please try again.",
            500
        )


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("home"))


@app.route("/me")
def me():

    user = session.get("user")

    if not user:

        return jsonify({
            "logged_in": False
        })

    return jsonify({

        "logged_in": True,

        "user": {

            "id": user.get("id"),

            "name": user.get(
                "name",
                "USER"
            ),

            "email": user.get(
                "email",
                ""
            ),

            "picture": user.get(
                "picture",
                ""
            )
        }
    })


# =========================================================
# AI CONTEXT
# =========================================================

def build_context(
    conv_id,
    memory,
    personality
):

    conversation = (
        get_conversation(conv_id)
        if conv_id
        else None
    )

    history = []

    if conversation:

        history = conversation.get(
            "messages",
            []
        )

    parts = []

    # Personality
    if personality:

        parts.append(
            "SYSTEM PERSONALITY / INSTRUCTIONS:\n"
            + personality
        )

    # Memory
    if memory:

        memory_lines = []

        for key, value in memory.items():

            memory_lines.append(
                f"{key}: {value}"
            )

        parts.append(
            "USER MEMORY:\n"
            + "\n".join(memory_lines)
        )

    # Conversation
    if history:

        history_text = []

        for message in history:

            role = message.get(
                "role",
                "user"
            )

            content = message.get(
                "content",
                ""
            )

            history_text.append(
                f"{role}: {content}"
            )

        parts.append(
            "CONVERSATION HISTORY:\n"
            + "\n".join(history_text)
        )

    return "\n\n".join(parts), history


# =========================================================
# CHAT
# =========================================================

@app.route("/chat", methods=["POST"])
def chat():

    if not get_user_id():

        return jsonify({
            "reply": "Please log in first."
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    user_message = (
        data.get("message", "")
        .strip()
    )

    conv_id = data.get(
        "conversation_id"
    )

    image_base64 = data.get(
        "image"
    )

    if not user_message and not image_base64:

        return jsonify({
            "reply": "Please enter a message."
        }), 400

    # Create conversation
    if not conv_id:

        conv_id = create_conversation()

        if not conv_id:

            return jsonify({
                "reply":
                "Unable to create conversation."
            }), 500

    # Verify conversation belongs to user
    conversation = get_conversation(
        conv_id
    )

    if conversation is None:

        return jsonify({
            "reply":
            "Conversation not found."
        }), 404

    memory = load_memory()

    personality = load_personality()

    context, history = build_context(

        conv_id,

        memory,

        personality
    )

    # Build user prompt
    user_content = user_message

    if image_base64:

        user_content += (
            "\n[User attached an image]"
        )

    history_for_ai = history + [

        {
            "role": "user",
            "content": user_content
        }

    ]

    conversation_text = "\n".join(

        f"{m['role']}: {m['content']}"

        for m in history_for_ai

    )

    final_prompt = ""

    if context:

        final_prompt += context + "\n\n"

    final_prompt += conversation_text

    try:

        contents = [final_prompt]

        # Image support
        if image_base64:

            try:

                header, encoded = (
                    image_base64.split(",", 1)
                )

                image_bytes = base64.b64decode(
                    encoded
                )

                mime_type = "image/jpeg"

                if "image/png" in header:
                    mime_type = "image/png"

                elif "image/webp" in header:
                    mime_type = "image/webp"

                elif "image/gif" in header:
                    mime_type = "image/gif"

                contents.append(

                    types.Part.from_bytes(

                        data=image_bytes,

                        mime_type=mime_type
                    )
                )

            except Exception as image_error:

                print(
                    "IMAGE ERROR:",
                    image_error
                )

        response = client.models.generate_content(

            model=MODEL_NAME,

            contents=contents
        )

        reply = (
            response.text
            if response.text
            else "I received your request."
        )

    except Exception as e:

        print("GEMINI ERROR:", e)

        reply = (
            "⚠ J.A.R.V.I.S connection error. "
            "Please try again."
        )

    # Save conversation
    history.append({

        "role": "user",

        "content": user_message
    })

    history.append({

        "role": "assistant",

        "content": reply
    })

    # Keep latest 40 messages
    history = history[-40:]

    title = None

    conversation = get_conversation(
        conv_id
    )

    if (

        conversation

        and conversation.get("title")
        == "New chat"

        and user_message
    ):

        title = user_message[:40]

        if len(user_message) > 40:
            title += "..."

    save_conversation_messages(

        conv_id,

        history,

        title
    )

    return jsonify({

        "reply": reply,

        "conversation_id": conv_id
    })


# =========================================================
# REGENERATE
# =========================================================

@app.route("/regenerate", methods=["POST"])
def regenerate():

    if not get_user_id():

        return jsonify({
            "reply":
            "Please log in first."
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    conv_id = data.get(
        "conversation_id"
    )

    if not conv_id:

        return jsonify({
            "reply":
            "No conversation selected."
        }), 400

    conversation = get_conversation(
        conv_id
    )

    if not conversation:

        return jsonify({
            "reply":
            "Conversation not found."
        }), 404

    history = conversation.get(
        "messages",
        []
    )

    if not history:

        return jsonify({
            "reply":
            "Nothing to regenerate."
        }), 400

    # Remove previous assistant response
    if history[-1]["role"] == "assistant":

        history = history[:-1]

    memory = load_memory()

    personality = load_personality()

    parts = []

    if personality:

        parts.append(
            "SYSTEM INSTRUCTIONS:\n"
            + personality
        )

    if memory:

        memory_text = "\n".join(

            f"{k}: {v}"

            for k, v in memory.items()

        )

        parts.append(
            "USER MEMORY:\n"
            + memory_text
        )

    history_text = "\n".join(

        f"{m['role']}: {m['content']}"

        for m in history

    )

    parts.append(
        "CONVERSATION:\n"
        + history_text
    )

    prompt = "\n\n".join(parts)

    try:

        response = client.models.generate_content(

            model=MODEL_NAME,

            contents=[prompt]
        )

        reply = response.text

    except Exception as e:

        print(
            "REGENERATE ERROR:",
            e
        )

        return jsonify({
            "reply":
            "⚠ Unable to regenerate response."
        }), 500

    history.append({

        "role": "assistant",

        "content": reply
    })

    save_conversation_messages(

        conv_id,

        history[-40:]
    )

    return jsonify({

        "reply": reply,

        "conversation_id": conv_id
    })


# =========================================================
# CONVERSATIONS API
# =========================================================

@app.route(
    "/conversations",
    methods=["GET"]
)
def get_conversations():

    if not get_user_id():

        return jsonify([])

    return jsonify(
        list_conversations()
    )


@app.route(
    "/conversations/new",
    methods=["POST"]
)
def new_conversation():

    if not get_user_id():

        return jsonify({
            "error":
            "not logged in"
        }), 401

    conv_id = create_conversation()

    return jsonify({

        "conversation_id":
        conv_id
    })


@app.route(
    "/conversations/<conv_id>",
    methods=["GET"]
)
def get_conversation_route(
    conv_id
):

    if not get_user_id():

        return jsonify({
            "error":
            "not logged in"
        }), 401

    conversation = get_conversation(
        conv_id
    )

    if not conversation:

        return jsonify({
            "error":
            "not found"
        }), 404

    return jsonify(
        conversation
    )


@app.route(
    "/conversations/<conv_id>",
    methods=["DELETE"]
)
def delete_conversation_route(
    conv_id
):

    if not get_user_id():

        return jsonify({
            "error":
            "not logged in"
        }), 401

    delete_conversation(
        conv_id
    )

    return jsonify({
        "status":
        "deleted"
    })


# =========================================================
# MEMORY API
# =========================================================

@app.route(
    "/memory",
    methods=["GET"]
)
def get_memory():

    if not get_user_id():

        return jsonify({})

    return jsonify(
        load_memory()
    )


@app.route(
    "/memory",
    methods=["POST"]
)
def add_memory():

    if not get_user_id():

        return jsonify({
            "status":
            "not logged in"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    key = str(
        data.get("key", "")
    ).strip()

    value = str(
        data.get("value", "")
    ).strip()

    if not key or not value:

        return jsonify({
            "status":
            "invalid",
            "message":
            "Key and value are required."
        }), 400

    memory = load_memory()

    memory[key] = value

    save_memory(memory)

    return jsonify({
        "status":
        "saved"
    })


# =========================================================
# PERSONALITY API
# =========================================================

@app.route(
    "/personality",
    methods=["GET"]
)
def get_personality():

    if not get_user_id():

        return jsonify({
            "personality":
            ""
        })

    return jsonify({

        "personality":
        load_personality()
    })


@app.route(
    "/personality",
    methods=["POST"]
)
def set_personality():

    if not get_user_id():

        return jsonify({
            "status":
            "not logged in"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    text = str(
        data.get(
            "personality",
            ""
        )
    ).strip()

    save_personality(text)

    return jsonify({
        "status":
        "saved"
    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/ping")
def ping():

    return jsonify({

        "status": "awake",

        "jarvis": "online",

        "model": MODEL_NAME
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                5000
            )
        ),
        debug=False
    )
