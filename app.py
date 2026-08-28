import os
import json
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")
from datetime import timedelta
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
    return session.get("user", {}).get("id")

def load_memory():
    uid = get_user_id()
    if not uid:
        return {}
    all_data = load_all_data()
    return all_data.get(uid, {}).get("memory", {})

def save_memory(memory_data):
    uid = get_user_id()
    if not uid:
        return
    all_data = load_all_data()
    if uid not in all_data:
        all_data[uid] = {}
    all_data[uid]["memory"] = memory_data
    save_all_data(all_data)

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
    user = session.get("user")
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": user})

@app.route("/chat", methods=["POST"])
def chat():
    if not get_user_id():
        return jsonify({"reply": "Please log in first."}), 401

    user_message = request.json.get("message", "")
    history = session.get("history", [])
    memory = load_memory()

    history.append({"role": "user", "content": user_message})

    memory_text = "\n".join(f"{k}: {v}" for k, v in memory.items())
    context = f"Known facts about the user:\n{memory_text}\n\n"
    context += "\n".join(f"{h['role']}: {h['content']}" for h in history)

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=context
        )
        reply = response.text
    except Exception as e:
        reply = "Error: " + str(e)

    history.append({"role": "assistant", "content": reply})
    session["history"] = history[-20:]

    return jsonify({"reply": reply})

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

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "awake"})

if __name__ == "__main__":
    app.run(debug=True)
