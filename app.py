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

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")
app.permanent_session_lifetime = timedelta(days=30)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "https://jarvis-chatbot-yaoh.onrender.com/auth/callback"

JSONBIN_BIN_ID = "6a8bb82cf5f4af5e293a6142"
JSONBIN_MASTER_KEY = "$2a$10$USpdPdaDuf1swL5yn4gfVuSwm3RKdGREGLxEZ6VHtmbyPnyn6VBT2"
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"

HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": JSONBIN_MASTER_KEY
}

MODEL_NAME = "gemini-3.1-flash-lite"

# ---------- Storage helpers ----------

def load_all_data():
    try:
        response = requests.get(f"{JSONBIN_URL}/latest", headers=HEADERS, timeout=5)
        data = response.json()
        return data.get("record", {})
    except Exception:
        return {}

def save_all_data(data):
    try:
        requests.put(JSONBIN_URL, headers=HEADERS, json=data, timeout=5)
    except Exception:
        pass

def get_user_id():
    header_id = request.headers.get("X-User-Id")
    if header_id:
        return header_id
    return session.get("user", {}).get("id")

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
    all_data = load_all_data()
    return get_user_record(all_data, uid)["memory"]

def save_memory(memory_data):
    uid = get_user_id()
    if not uid:
        return
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    record["memory"] = memory_data
    save_all_data(all_data)

# ---------- Personality ----------

def load_personality():
    uid = get_user_id()
    if not uid:
        return ""
    all_data = load_all_data()
    return get_user_record(all_data, uid)["personality"]

def save_personality(text):
    uid = get_user_id()
    if not uid:
        return
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    record["personality"] = text
    save_all_data(all_data)

# ---------- Conversations ----------

def list_conversations():
    uid = get_user_id()
    if not uid:
        return []
    all_data = load_all_data()
    convs = get_user_record(all_data, uid)["conversations"]
    result = []
    for cid, c in convs.items():
        result.append({
            "id": cid,
            "title": c.get("title", "New chat"),
            "created_at": c.get("created_at", "")
        })
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result

def get_conversation(conv_id):
    uid = get_user_id()
    if not uid:
        return None
    all_data = load_all_data()
    convs = get_user_record(all_data, uid)["conversations"]
    return convs.get(conv_id)

def create_conversation():
    uid = get_user_id()
    if not uid:
        return None
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    conv_id = str(uuid.uuid4())[:8]
    record["conversations"][conv_id] = {
        "title": "New chat",
        "created_at": datetime.utcnow().isoformat(),
        "messages": []
    }
    save_all_data(all_data)
    return conv_id

def save_conversation_messages(conv_id, messages, title=None):
    uid = get_user_id()
    if not uid:
        return
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    if conv_id not in record["conversations"]:
        record["conversations"][conv_id] = {
            "title": title or "New chat",
            "created_at": datetime.utcnow().isoformat(),
            "messages": []
        }
    record["conversations"][conv_id]["messages"] = messages
    if title:
        record["conversations"][conv_id]["title"] = title
    save_all_data(all_data)

def delete_conversation(conv_id):
    uid = get_user_id()
    if not uid:
        return
    all_data = load_all_data()
    record = get_user_record(all_data, uid)
    if conv_id in record["conversations"]:
        del record["conversations"][conv_id]
        save_all_data(all_data)

# ---------- Auth ----------

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
        return "Login failed: no code returned", 400

    token_res = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    })
    token_data = token_res.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return "Login failed: no access token", 400

    userinfo_res = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    userinfo = userinfo_res.json()

    session["user"] = {
        "id": userinfo.get("id"),
        "name": userinfo.get("name"),
        "email": userinfo.get("email"),
        "picture": userinfo.get("picture")
    }
    session.permanent = True

    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/me")
def me():
    header_id = request.headers.get("X-User-Id")
    if header_id:
        return jsonify({
            "logged_in": True,
            "user": {
                "id": header_id,
                "name": request.headers.get("X-User-Name", "USER"),
                "picture": request.headers.get("X-User-Picture", "")
            }
        })
    user = session.get("user")
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": user})

# ---------- Chat ----------

def build_context(conv_id, memory, personality):
    conv = get_conversation(conv_id) if conv_id else None
    history = conv["messages"] if conv else []

    parts = []
    if personality:
        parts.append(f"Instructions for how you should behave:\n{personality}\n")
    if memory:
        memory_text = "\n".join(f"{k}: {v}" for k, v in memory.items())
        parts.append(f"Known facts about the user:\n{memory_text}\n")
    parts.append("\n".join(f"{h['role']}: {h['content']}" for h in history))
    return "\n".join(parts), history

@app.route("/chat", methods=["POST"])
def chat():
    if not get_user_id():
        return jsonify({"reply": "Please log in first."}), 401

    data = request.json or {}
    user_message = data.get("message", "")
    conv_id = data.get("conversation_id")
    image_base64 = data.get("image")

    if not conv_id:
        conv_id = create_conversation()

    memory = load_memory()
    personality = load_personality()
    context, history = build_context(conv_id, memory, personality)

    history.append({"role": "user", "content": user_message})
    context += f"\nuser: {user_message}"

    try:
        contents = [context]
        if image_base64:
            image_bytes = base64.b64decode(image_base64.split(",")[-1])
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents
        )
        reply = response.text
    except Exception as e:
        reply = "Error: " + str(e)

    history.append({"role": "assistant", "content": reply})

    title = None
    conv = get_conversation(conv_id)
    if conv and conv.get("title") == "New chat" and len(history) >= 2:
        title = user_message[:40] + ("..." if len(user_message) > 40 else "")

    save_conversation_messages(conv_id, history[-40:], title=title)

    return jsonify({"reply": reply, "conversation_id": conv_id})

@app.route("/regenerate", methods=["POST"])
def regenerate():
    if not get_user_id():
        return jsonify({"reply": "Please log in first."}), 401

    data = request.json or {}
    conv_id = data.get("conversation_id")
    if not conv_id:
        return jsonify({"reply": "No conversation to regenerate."}), 400

    memory = load_memory()
    personality = load_personality()
    conv = get_conversation(conv_id)
    if not conv or not conv["messages"]:
        return jsonify({"reply": "Nothing to regenerate."}), 400

    history = conv["messages"]
    if history[-1]["role"] == "assistant":
        history = history[:-1]

    context, _ = build_context(conv_id, memory, personality)

    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=context)
        reply = response.text
    except Exception as e:
        reply = "Error: " + str(e)

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
    conv_id = create_conversation()
    return jsonify({"conversation_id": conv_id})

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
    key = request.json.get("key")
    value = request.json.get("value")
    memory = load_memory()
    memory[key] = value
    save_memory(memory)
    return jsonify({"status": "saved"})

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
    text = request.json.get("personality", "")
    save_personality(text)
    return jsonify({"status": "saved"})

# ---------- Misc ----------

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "awake"})

if __name__ == "__main__":
    app.run(debug=True)
