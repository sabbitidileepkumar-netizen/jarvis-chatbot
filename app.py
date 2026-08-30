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

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.permanent_session_lifetime = timedelta(days=30)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID")
JSONBIN_MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")

REDIRECT_URI = "https://jarvis-chatbot-yaoh.onrender.com/auth/callback"
MODEL_NAME = "gemini-3.1-flash-lite"

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}" if JSONBIN_BIN_ID else None
HEADERS = {"Content-Type": "application/json", "X-Master-Key": JSONBIN_MASTER_KEY or ""}

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------- Storage ----------

def load_all_data():
    if not JSONBIN_URL or not JSONBIN_MASTER_KEY:
        return {}
    try:
        r = requests.get(f"{JSONBIN_URL}/latest", headers=HEADERS, timeout=8)
        r.raise_for_status()
        return r.json().get("record", {})
    except Exception as e:
        print("JSONBIN LOAD ERROR:", e)
        return {}

def save_all_data(data):
    if not JSONBIN_URL or not JSONBIN_MASTER_KEY:
        return False
    try:
        r = requests.put(JSONBIN_URL, headers=HEADERS, json=data, timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print("JSONBIN SAVE ERROR:", e)
        return False


# ---------- User ----------

def get_user_id():
    user = session.get("user")
    return user.get("id") if user else None

def get_user_record(all_data, uid):
    if uid not in all_data:
        all_data[uid] = {"memory": {}, "personality": "", "conversations": {}}
    record = all_data[uid]
    record.setdefault("memory", {})
    record.setdefault("personality", "")
    record.setdefault("conversations", {})
    return record


# ---------- Memory ----------

def load_memory():
    uid = get_user_id()
    if not uid:
        return {}
    return get_user_record(load_all_data(), uid)["memory"]

def save_memory(memory_data):
    uid = get_user_id()
    if not uid:
        return False
    all_data = load_all_data()
    get_user_record(all_data, uid)["memory"] = memory_data
    return save_all_data(all_data)

def delete_memory_key(key):
    uid = get_user_id()
    if not uid:
        return False
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    if key in record["memory"]:
        del record["memory"][key]
        return save_all_data(all_data)
    return False


# ---------- Personality ----------

def load_personality():
    uid = get_user_id()
    if not uid:
        return ""
    return get_user_record(load_all_data(), uid)["personality"]

def save_personality(text):
    uid = get_user_id()
    if not uid:
        return False
    all_data = load_all_data()
    get_user_record(all_data, uid)["personality"] = text
    return save_all_data(all_data)


# ---------- Conversations ----------

def list_conversations():
    uid = get_user_id()
    if not uid:
        return []
    convs = get_user_record(load_all_data(), uid)["conversations"]
    result = [{
        "id": cid,
        "title": c.get("title", "New chat"),
        "created_at": c.get("created_at", ""),
        "updated_at": c.get("updated_at", c.get("created_at", ""))
    } for cid, c in convs.items()]
    result.sort(key=lambda x: x["updated_at"], reverse=True)
    return result

def get_conversation(conv_id):
    uid = get_user_id()
    if not uid or not conv_id:
        return None
    return get_user_record(load_all_data(), uid)["conversations"].get(conv_id)

def create_conversation():
    uid = get_user_id()
    if not uid:
        return None
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    conv_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    record["conversations"][conv_id] = {"title": "New chat", "created_at": now, "updated_at": now, "messages": []}
    if not save_all_data(all_data):
        return None
    return conv_id

def save_conversation_messages(conv_id, messages, title=None):
    uid = get_user_id()
    if not uid:
        return False
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    if conv_id not in record["conversations"]:
        now = datetime.utcnow().isoformat()
        record["conversations"][conv_id] = {"title": title or "New chat", "created_at": now, "updated_at": now, "messages": []}
    conv = record["conversations"][conv_id]
    conv["messages"] = messages
    conv["updated_at"] = datetime.utcnow().isoformat()
    if title:
        conv["title"] = title
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


# ---------- Auth ----------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login")
def login():
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code&scope=openid%20email%20profile&access_type=offline"
    )
    return redirect(url)

@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return "Login failed: no authorization code.", 400
    try:
        token_res = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"
        }, timeout=10)
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        if not access_token:
            return "Login failed: access token missing.", 400

        user_res = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                 headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        user_res.raise_for_status()
        info = user_res.json()

        session["user"] = {
            "id": info.get("id"), "name": info.get("name", "USER"),
            "email": info.get("email", ""), "picture": info.get("picture", "")
        }
        session.permanent = True
        return redirect(url_for("home"))
    except Exception as e:
        print("GOOGLE LOGIN ERROR:", e)
        return "Google authentication failed. Please try again.", 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/me")
def me():
    user = session.get("user")
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": {
        "id": user.get("id"), "name": user.get("name", "USER"),
        "email": user.get("email", ""), "picture": user.get("picture", "")
    }})


# ---------- AI context ----------

def build_context(conv_id, memory, personality):
    conversation = get_conversation(conv_id) if conv_id else None
    history = conversation.get("messages", []) if conversation else []
    parts = []
    if personality:
        parts.append("SYSTEM PERSONALITY / INSTRUCTIONS:\n" + personality)
    if memory:
        parts.append("USER MEMORY:\n" + "\n".join(f"{k}: {v}" for k, v in memory.items()))
    if history:
        parts.append("CONVERSATION HISTORY:\n" + "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in history))
    return "\n\n".join(parts), history


# ---------- Chat ----------

@app.route("/chat", methods=["POST"])
def chat():
    if not get_user_id():
        return jsonify({"reply": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    conv_id = data.get("conversation_id")
    image_base64 = data.get("image")

    if not user_message and not image_base64:
        return jsonify({"reply": "Please enter a message."}), 400

    if not conv_id:
        conv_id = create_conversation()
        if not conv_id:
            return jsonify({"reply": "Unable to create conversation."}), 500

    if get_conversation(conv_id) is None:
        return jsonify({"reply": "Conversation not found."}), 404

    memory = load_memory()
    personality = load_personality()
    context, history = build_context(conv_id, memory, personality)

    user_content = user_message + ("\n[User attached an image]" if image_base64 else "")
    history_for_ai = history + [{"role": "user", "content": user_content}]
    conversation_text = "\n".join(f"{m['role']}: {m['content']}" for m in history_for_ai)
    final_prompt = (context + "\n\n" if context else "") + conversation_text

    try:
        contents = [final_prompt]
        if image_base64:
            try:
                header, encoded = image_base64.split(",", 1)
                image_bytes = base64.b64decode(encoded)
                mime_type = "image/jpeg"
                if "image/png" in header: mime_type = "image/png"
                elif "image/webp" in header: mime_type = "image/webp"
                elif "image/gif" in header: mime_type = "image/gif"
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
            except Exception as ie:
                print("IMAGE ERROR:", ie)

        response = client.models.generate_content(model=MODEL_NAME, contents=contents)
        reply = response.text if response.text else "I received your request."
    except Exception as e:
        print("GEMINI ERROR:", e)
        reply = "⚠ J.A.R.V.I.S connection error. Please try again."

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply})
    history = history[-40:]

    title = None
    conv = get_conversation(conv_id)
    if conv and conv.get("title") == "New chat" and user_message:
        title = user_message[:40] + ("..." if len(user_message) > 40 else "")

    save_conversation_messages(conv_id, history, title)
    return jsonify({"reply": reply, "conversation_id": conv_id})


@app.route("/regenerate", methods=["POST"])
def regenerate():
    if not get_user_id():
        return jsonify({"reply": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    conv_id = data.get("conversation_id")
    if not conv_id:
        return jsonify({"reply": "No conversation selected."}), 400

    conversation = get_conversation(conv_id)
    if not conversation:
        return jsonify({"reply": "Conversation not found."}), 404

    history = conversation.get("messages", [])
    if not history:
        return jsonify({"reply": "Nothing to regenerate."}), 400

    if history[-1]["role"] == "assistant":
        history = history[:-1]

    memory = load_memory()
    personality = load_personality()
    parts = []
    if personality:
        parts.append("SYSTEM INSTRUCTIONS:\n" + personality)
    if memory:
        parts.append("USER MEMORY:\n" + "\n".join(f"{k}: {v}" for k, v in memory.items()))
    parts.append("CONVERSATION:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in history))
    prompt = "\n\n".join(parts)

    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt])
        reply = response.text
    except Exception as e:
        print("REGENERATE ERROR:", e)
        return jsonify({"reply": "⚠ Unable to regenerate response."}), 500

    history.append({"role": "assistant", "content": reply})
    save_conversation_messages(conv_id, history[-40:])
    return jsonify({"reply": reply, "conversation_id": conv_id})


# ---------- Conversations API ----------

@app.route("/conversations", methods=["GET"])
def get_conversations():
    if not get_user_id():
        return jsonify([])
    return jsonify(list_conversations())

@app.route("/conversations/new", methods=["POST"])
def new_conversation():
    if not get_user_id():
        return jsonify({"error": "not logged in"}), 401
    return jsonify({"conversation_id": create_conversation()})

@app.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation_route(conv_id):
    if not get_user_id():
        return jsonify({"error": "not logged in"}), 401
    conv = get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "not found"}), 404
    return jsonify(conv)

@app.route("/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation_route(conv_id):
    if not get_user_id():
        return jsonify({"error": "not logged in"}), 401
    delete_conversation(conv_id)
    return jsonify({"status": "deleted"})


# ---------- Memory API ----------

@app.route("/memory", methods=["GET"])
def get_memory():
    if not get_user_id():
        return jsonify({})
    return jsonify(load_memory())

@app.route("/memory", methods=["POST"])
def add_memory():
    if not get_user_id():
        return jsonify({"status": "not logged in"}), 401
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    value = str(data.get("value", "")).strip()
    if not key or not value:
        return jsonify({"status": "invalid", "message": "Key and value are required."}), 400
    memory = load_memory()
    memory[key] = value
    save_memory(memory)
    return jsonify({"status": "saved"})

@app.route("/memory/<path:key>", methods=["DELETE"])
def delete_memory_route(key):
    if not get_user_id():
        return jsonify({"status": "not logged in"}), 401
    delete_memory_key(key)
    return jsonify({"status": "deleted"})


# ---------- Personality API ----------

@app.route("/personality", methods=["GET"])
def get_personality():
    if not get_user_id():
        return jsonify({"personality": ""})
    return jsonify({"personality": load_personality()})

@app.route("/personality", methods=["POST"])
def set_personality():
    if not get_user_id():
        return jsonify({"status": "not logged in"}), 401
    data = request.get_json(silent=True) or {}
    save_personality(str(data.get("personality", "")).strip())
    return jsonify({"status": "saved"})


# ---------- Health ----------

@app.route("/ping")
def ping():
    return jsonify({"status": "awake", "jarvis": "online", "model": MODEL_NAME})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
