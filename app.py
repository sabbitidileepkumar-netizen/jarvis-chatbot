import os
import json
import requests
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from google import genai
from authlib.integrations.flask_client import OAuth

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

JSONBIN_BIN_ID = "6a8bb82cf5f4af5e293a6142"
JSONBIN_MASTER_KEY = os.getenv("JSONBIN_MASTER_KEY")
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"

HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": JSONBIN_MASTER_KEY
}

def load_memory():
    try:
        response = requests.get(f"{JSONBIN_URL}/latest", headers=HEADERS, timeout=5)
        data = response.json()
        return data.get("record", {})
    except Exception:
        return {}

def save_memory(memory_data):
    try:
        requests.put(JSONBIN_URL, headers=HEADERS, json=memory_data, timeout=5)
    except Exception:
        pass

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login")
def login():
    redirect_uri = "https://jarvis-chatbot-yaoh.onrender.com/auth/callback"
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
    session["user"] = user_info
    return f"Logged in as {user_info['email']}! <a href='/'>Go home</a>"

@app.route("/logout")
def logout():
    session.pop("user", None)
    return "Logged out. <a href='/'>Go home</a>"

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    history = session.get("history", [])
    memory = load_memory()

    history.append({"role": "user", "content": user_message})

    memory_text = "\n".join(f"{k}: {v}" for k, v in memory.items() if k != "status")
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
    return jsonify(load_memory())

@app.route("/memory", methods=["POST"])
def add_memory():
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
