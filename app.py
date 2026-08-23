import os
import json
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")

MEMORY_FILE = "memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
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
    return jsonify(load_memory())

@app.route("/memory", methods=["POST"])
def add_memory():
    key = request.json.get("key")
    value = request.json.get("value")
    memory = load_memory()
    memory[key] = value
    save_memory(memory)
    return jsonify({"status": "saved"})

if __name__ == "__main__":
    app.run(debug=True)
