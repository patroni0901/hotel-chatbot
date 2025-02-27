from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import openai
import sqlite3
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config["SECRET_KEY"] = "supersecretkey"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Setup Login Manager
login_manager = LoginManager()
login_manager.init_app(app)

openai.api_key = os.getenv("OPENAI_API_KEY")
DB_NAME = "chatbot.db"

# ✅ Ensure Database Tables Exist
def initialize_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # ✅ Ensure agents table exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # ✅ Ensure conversations table exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            latest_message TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            assigned_agent TEXT DEFAULT NULL
        )
    ''')

    # ✅ Check if messages table exists with the correct columns
    c.execute("PRAGMA table_info(messages)")
    existing_columns = [row[1] for row in c.fetchall()]

    if "conversation_id" not in existing_columns:
        print("⚠️ Fixing messages table: Adding missing conversation_id column.")
        
        # Drop the old messages table if it doesn't have conversation_id
        c.execute("DROP TABLE IF EXISTS messages")
        
        # Create the correct messages table
        c.execute('''
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user TEXT NOT NULL,
                message TEXT NOT NULL,
                sender TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        ''')
        conn.commit()
        print("✅ Fixed messages table.")

    conn.close()


initialize_database()

# ✅ Add Test Conversations on Startup
def add_test_conversations():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Check if there are already existing conversations
    c.execute("SELECT COUNT(*) FROM conversations")
    existing_convos = c.fetchone()[0]

    if existing_convos == 0:
        print("🔹 No conversations found. Adding test conversations...")
        
        # Insert fake conversations
        test_conversations = [
            ("john_doe", "Hey, I need help with a bet."),
            ("jane_smith", "How do I withdraw my winnings?"),
            ("mark_taylor", "What are the odds for tonight’s game?"),
        ]

        convo_ids = []
        for username, message in test_conversations:
            c.execute("INSERT INTO conversations (username, latest_message) VALUES (?, ?)", (username, message))
            convo_ids.append(c.lastrowid)

        # Insert test messages into the chat
        test_messages = [
            (convo_ids[0], "john_doe", "Hey, I need help with a bet.", "user"),
            (convo_ids[0], "AI", "Sure! What do you need help with?", "ai"),
            (convo_ids[1], "jane_smith", "How do I withdraw my winnings?", "user"),
            (convo_ids[1], "AI", "You can withdraw via Sinpe Móvil.", "ai"),
            (convo_ids[2], "mark_taylor", "What are the odds for tonight’s game?", "user"),
            (convo_ids[2], "AI", "Let me check the latest odds for you.", "ai"),
        ]

        for convo_id, user, message, sender in test_messages:
            c.execute("INSERT INTO messages (conversation_id, user, message, sender) VALUES (?, ?, ?, ?)", 
                      (convo_id, user, message, sender))

        conn.commit()
        print("✅ Test conversations added.")

    conn.close()

# Run the function on startup
add_test_conversations()

# ✅ Define User Class for Login
class Agent(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

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

# ✅ Agent Login API
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"message": "Missing username or password"}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username FROM agents WHERE username = ? AND password = ?", (username, password))
    agent = c.fetchone()
    conn.close()

    if agent:
        return jsonify({"message": "Login successful", "agent": agent[1]})
    return jsonify({"message": "Invalid credentials"}), 401

# ✅ Logout API
@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out successfully"})

# ✅ Fetch Conversations
@app.route("/conversations", methods=["GET"])
def get_conversations():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, username, latest_message FROM conversations ORDER BY last_updated DESC")
    conversations = [{"id": row[0], "username": row[1], "latest_message": row[2]} for row in c.fetchall()]
    conn.close()
    return jsonify(conversations)

# ✅ Fetch Chat Messages for a Conversation
@app.route("/messages", methods=["GET"])
def get_messages():
    convo_id = request.args.get("conversation_id")

    if not convo_id:
        return jsonify({"error": "Missing conversation ID"}), 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT message, sender, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC", (convo_id,))
    
    messages = [{"message": row[0], "sender": row[1], "timestamp": row[2]} for row in c.fetchall()]
    conn.close()

    return jsonify(messages)

# ✅ AI Chat API
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    convo_id = data.get("conversation_id")
    user_message = data.get("message")

    if not convo_id or not user_message:
        return jsonify({"error": "Missing required fields"}), 400

    log_message(convo_id, "User", user_message, "user")

    # AI Response
    ai_reply = f"AI Response to: {user_message}"  # Simulating AI for now
    log_message(convo_id, "AI", ai_reply, "ai")

    socketio.emit("new_message", {"conversation_id": convo_id, "message": ai_reply, "sender": "ai"})
    return jsonify({"reply": ai_reply})

# ✅ Serve the Dashboard
@app.route("/")
def index():
    return render_template("dashboard.html")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
