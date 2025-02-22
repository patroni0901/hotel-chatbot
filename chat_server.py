from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import openai
import sqlite3
import os
from flask_login import LoginManager
from flask import send_file


app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Setup Login Manager
login_manager = LoginManager()
login_manager.init_app(app)

openai.api_key = os.getenv("OPENAI_API_KEY")
DB_NAME = "chatbot.db"

class Agent(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

# ✅ Load User Function
@login_manager.user_loader
def load_user(agent_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username FROM agents WHERE id = ?", (agent_id,))
    agent = c.fetchone()
    conn.close()
    if agent:
        return Agent(agent[0], agent[1])
    return None

# ✅ Agent Login API (Fixing the issue)
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    if "username" not in data or "password" not in data:
        return jsonify({"message": "Missing username or password"}), 400

    username = data["username"]
    password = data["password"]

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, username FROM agents WHERE username = ? AND password = ?", (username, password))
        agent = c.fetchone()
        conn.close()

        if agent:
            return jsonify({"message": "Login successful", "agent": agent[1]})
        else:
            return jsonify({"message": "Invalid credentials"}), 401
    except sqlite3.Error as e:
        return jsonify({"message": f"Database error: {str(e)}"}), 500


# ✅ Agent Logout API
@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out successfully"})

# ✅ Store message in database
def log_message(user, message, sender, channel, client_name=None, client_contact=None, stay_date=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""INSERT INTO messages (user, message, sender, channel, client_name, client_contact, stay_date)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
                 (user, message, sender, channel, client_name, client_contact, stay_date))
    conn.commit()
    conn.close()

# ✅ Chat API - AI + Human Handoff Detection
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    user_id = request.json.get("user_id", "Anonymous")
    channel = request.json.get("channel", "WhatsApp")  # Default to WhatsApp if not specified
    client_name = request.json.get("name")
    client_contact = request.json.get("contact")
    stay_date = request.json.get("stay_date")

    # Store user message
    log_message(user_id, user_message, "user", channel, client_name, client_contact, stay_date)

    # AI Response
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are John, a helpful casino assistant. Keep responses short and clear."},
            {"role": "user", "content": user_message},
        ],
    )

    ai_reply = response.choices[0].message["content"]

    # Store AI response
    log_message(user_id, ai_reply, "ai", channel)

    # Check for handoff trigger words
    handoff_trigger = any(word in user_message.lower() for word in ["human", "help me", "real person", "talk to an agent"])

    if handoff_trigger:
        socketio.emit("handoff", {"user": user_id, "message": "AI suggests human takeover!"})

    # Emit message to dashboard
    socketio.emit("new_message", {"user": user_id, "message": ai_reply, "sender": "ai", "channel": channel})

    return jsonify({"reply": ai_reply})

# ✅ Fetch Chat History API
@app.route("/messages", methods=["GET"])
@login_required
def get_messages():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user, message, sender, channel, client_name, client_contact, stay_date, timestamp FROM messages ORDER BY timestamp DESC LIMIT 50")
    messages = [{"user": row[0], "message": row[1], "sender": row[2], "channel": row[3],
                 "client_name": row[4], "client_contact": row[5], "stay_date": row[6], "timestamp": row[7]}
                for row in c.fetchall()]
    conn.close()
    return jsonify(messages)

# ✅ Handle Human Handoff
@app.route("/handoff", methods=["POST"])
@login_required
def handoff():
    data = request.json
    user_id = data["user_id"]
    agent_name = current_user.username

    # Store agent takeover message
    log_message(user_id, f"{agent_name} has taken over this conversation.", "agent", "manual")

    # Notify frontend of human handoff
    socketio.emit("handoff", {"user": user_id, "agent": agent_name})

    return jsonify({"message": "Handoff initiated"})

@app.route('/')
def index():
    return send_file('dashboard.html')


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
