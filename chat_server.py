import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask import Response
import openai
import psycopg2
from psycopg2.extras import DictCursor
import os
import requests
import json
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from tasks import process_whatsapp_message
from datetime import datetime, timezone
import time
import logging
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "supersecretkey")
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    ping_timeout=120,
    ping_interval=30,
    logger=True,
    engineio_logger=True
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    logger.error("⚠️ OPENAI_API_KEY not set in environment variables")
    raise ValueError("OPENAI_API_KEY not set")

# Google Calendar setup with Service Account
GOOGLE_SERVICE_ACCOUNT_KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
if not GOOGLE_SERVICE_ACCOUNT_KEY:
    logger.error("⚠️ GOOGLE_SERVICE_ACCOUNT_KEY not set in environment variables")
    raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY not set")

try:
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
except json.JSONDecodeError as e:
    logger.error(f"⚠️ Invalid GOOGLE_SERVICE_ACCOUNT_KEY format: {e}")
    raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY must be a valid JSON string")

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)
service = build('calendar', 'v3', credentials=credentials)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("⚠️ TELEGRAM_BOT_TOKEN not set in environment variables")
    raise ValueError("TELEGRAM_BOT_TOKEN not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_API_URL = "https://graph.instagram.com/v20.0"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

if not TWILIO_ACCOUNT_SID:
    logger.error("⚠️ TWILIO_ACCOUNT_SID not set in environment variables")
    raise ValueError("TWILIO_ACCOUNT_SID not set")
if not TWILIO_AUTH_TOKEN:
    logger.error("⚠️ TWILIO_AUTH_TOKEN not set in environment variables")
    raise ValueError("TWILIO_AUTH_TOKEN not set")
if not TWILIO_WHATSAPP_NUMBER:
    logger.error("⚠️ TWILIO_WHATSAPP_NUMBER not set in environment variables")
    raise ValueError("TWILIO_WHATSAPP_NUMBER not set")

WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", None)
WHATSAPP_API_URL = "https://api.whatsapp.com"

# Load or define the Q&A reference document
try:
    with open("qa_reference.txt", "r") as file:
        TRAINING_DOCUMENT = file.read()
    logger.info("✅ Loaded Q&A reference document")
except FileNotFoundError:
    TRAINING_DOCUMENT = """
    **Amapola Resort Chatbot Training Document**

    You are a friendly and professional chatbot for Amapola Resort, a luxury beachfront hotel. Your role is to assist guests with inquiries, help with bookings, and provide information about the resort’s services and amenities. Below is a set of common questions and answers to guide your responses. Always maintain conversation context, ask follow-up questions to clarify user intent, and provide helpful, concise answers. If a query is too complex or requires human assistance (e.g., specific booking modifications, complaints, or detailed itinerary planning), escalate to a human by saying: "I’m sorry, that’s a bit complex for me to handle. Let me get a human to assist you."

    **Business Information**
    - **Location**: Amapola Resort, 123 Ocean Drive, Sunny Beach, FL 33160
    - **Check-In/Check-Out**: Check-in at 3:00 PM, Check-out at 11:00 AM
    - **Room Types**:
      - Standard Room: $150/night, 2 guests, 1 queen bed
      - Deluxe Room: $250/night, 4 guests, 2 queen beds, ocean view
      - Suite: $400/night, 4 guests, 1 king bed, living area, oceanfront balcony
    - **Amenities**:
      - Beachfront access, outdoor pool, spa, gym, on-site restaurant (Amapola Bistro), free Wi-Fi, parking ($20/day)
    - **Activities**:
      - Snorkeling ($50/person), kayak rentals ($30/hour), sunset cruises ($100/person)
    - **Policies**:
      - Cancellation: Free cancellation up to 48 hours before arrival
      - Pets: Not allowed
      - Children: Kids under 12 stay free with an adult

    **Common Q&A**

    Q: What are your room rates?
    A: We offer several room types:
    - Standard Room: $150/night for 2 guests
    - Deluxe Room: $250/night for 4 guests, with an ocean view
    - Suite: $400/night for 4 guests, with an oceanfront balcony
    Would you like to book a room, or do you have questions about a specific room type?

    Q: How do I book a room?
    A: I can help you start the booking process! Please let me know:
    1. Your preferred dates (e.g., check-in and check-out dates)
    2. The number of guests
    3. Your preferred room type (Standard, Deluxe, or Suite)
    For example, you can say: "I’d like a Deluxe Room for 2 guests from March 10 to March 15." Once I have this information, I’ll check availability and guide you through the next steps. If you’d prefer to speak with a human to finalize your booking, let me know!

    Q: What is the check-in time?
    A: Check-in at Amapola Resort is at 3:00 PM, and check-out is at 11:00 AM. If you need an early check-in or late check-out, I can check availability for you—just let me know your dates!

    Q: Do you have a pool?
    A: Yes, we have a beautiful outdoor pool with beachfront views! It’s open from 8:00 AM to 8:00 PM daily. We also have a spa and gym if you’re interested in other amenities. Would you like to know more?

    Q: Can I bring my pet?
    A: I’m sorry, but pets are not allowed at Amapola Resort. If you need recommendations for pet-friendly accommodations nearby, I can help you find some options!

    Q: What activities do you offer?
    A: We have a variety of activities for our guests:
    - Snorkeling: $50 per person
    - Kayak rentals: $30 per hour
    - Sunset cruises: $100 per person
    Would you like to book an activity, or do you have questions about any of these?

    Q: What are the cancellation policies?
    A: You can cancel your reservation for free up to 48 hours before your arrival. After that, you may be charged for the first night. If you need to modify or cancel a booking, I can get a human to assist you with the details.

    Q: Do you have a restaurant?
    A: Yes, Amapola Bistro is our on-site restaurant, serving breakfast, lunch, and dinner with a focus on fresh seafood and local flavors. It’s open from 7:00 AM to 10:00 PM. Would you like to make a reservation or see the menu?

    **Conversational Guidelines**
    - Always greet new users with: "Thank you for contacting us."
    - For follow-up messages, do not repeat the greeting. Instead, respond based on the context of the conversation.
    - Ask clarifying questions if the user’s intent is unclear (e.g., "Could you tell me your preferred dates for booking?").
    - Use a friendly and professional tone, and keep responses concise (under 150 tokens, as set by max_tokens).
    - If the user asks multiple questions in one message, address each question systematically.
    - If the user provides partial information (e.g., "I want to book a room"), ask for missing details (e.g., dates, number of guests, room type).
    - If a query is ambiguous, ask for clarification (e.g., "Did you mean you’d like to book a room, or are you asking about our rates?").
    - Escalate to a human for complex requests, such as modifying an existing booking, handling complaints, or providing detailed recommendations.
    """
    logger.warning("⚠️ qa_reference.txt not found, using default training document")

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
        return conn
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        raise Exception(f"Failed to connect to database: {e}")

def release_db_connection(conn):
    if conn:
        try:
            conn.close()
            logger.info("✅ Database connection closed")
        except Exception as e:
            logger.error(f"❌ Failed to close database connection: {e}")

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()

        # Check if tables exist before creating them
        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'conversations'
            )
        """)
        conversations_table_exists = c.fetchone()[0]

        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'messages'
            )
        """)
        messages_table_exists = c.fetchone()[0]

        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'agents'
            )
        """)
        agents_table_exists = c.fetchone()[0]

        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'settings'
            )
        """)
        settings_table_exists = c.fetchone()[0]

        # Create tables only if they don't exist
        if not conversations_table_exists:
            c.execute('''CREATE TABLE conversations (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                assigned_agent TEXT,
                ai_enabled INTEGER DEFAULT 1,
                booking_intent INTEGER DEFAULT 0,
                handoff_notified INTEGER DEFAULT 0,
                visible_in_conversations INTEGER DEFAULT 1,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            logger.info("Created conversations table")

        if not messages_table_exists:
            c.execute('''CREATE TABLE messages (
                id SERIAL PRIMARY KEY,
                convo_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                message TEXT NOT NULL,
                sender TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (convo_id) REFERENCES conversations (id)
            )''')
            logger.info("Created messages table")

        if not agents_table_exists:
            c.execute('''CREATE TABLE agents (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )''')
            logger.info("Created agents table")

        if not settings_table_exists:
            c.execute('''CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            logger.info("Created settings table")
        else:
            # Migration: Add last_updated column if it doesn't exist
            c.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'settings' AND column_name = 'last_updated'
                )
            """)
            last_updated_exists = c.fetchone()[0]
            if not last_updated_exists:
                c.execute("ALTER TABLE settings ADD COLUMN last_updated TEXT DEFAULT CURRENT_TIMESTAMP")
                logger.info("Added last_updated column to settings table")

        # Seed initial data (only if tables are empty)
        c.execute("SELECT COUNT(*) FROM settings")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO settings (key, value, last_updated) VALUES (%s, %s, %s) ON CONFLICT (key) DO NOTHING",
                      ('ai_enabled', '1', datetime.now(timezone.utc).isoformat()))
            logger.info("Inserted default settings")

        c.execute("SELECT COUNT(*) FROM agents")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO agents (username, password) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
                      ('admin', 'password123'))
            logger.info("Inserted default admin user")

        c.execute("SELECT COUNT(*) FROM conversations WHERE channel = %s", ('whatsapp',))
        if c.fetchone()[0] == 0:
            logger.info("ℹ️ Inserting test conversations")
            test_timestamp1 = "2025-03-22T00:00:00Z"
            c.execute(
                "INSERT INTO conversations (username, chat_id, channel, assigned_agent, ai_enabled, booking_intent, last_updated) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                ('TestUser1', '123456789', 'whatsapp', None, 1, 0, test_timestamp1)
            )
            convo_id1 = c.fetchone()['id']
            c.execute(
                "INSERT INTO messages (convo_id, username, message, sender, timestamp) VALUES (%s, %s, %s, %s, %s)",
                (convo_id1, 'TestUser1', 'Hello, I need help!', 'user', test_timestamp1)
            )
            test_timestamp2 = "2025-03-22T00:00:01Z"
            c.execute(
                "INSERT INTO conversations (username, chat_id, channel, assigned_agent, ai_enabled, booking_intent, last_updated) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                ('TestUser2', '987654321', 'whatsapp', None, 1, 0, test_timestamp2)
            )
            convo_id2 = c.fetchone()['id']
            c.execute(
                "INSERT INTO messages (convo_id, username, message, sender, timestamp) VALUES (%s, %s, %s, %s, %s)",
                (convo_id2, 'TestUser2', 'Can I book a room?', 'user', test_timestamp2)
            )
            logger.info("Inserted test conversations")

        conn.commit()
        logger.info("✅ Database initialized")
        
# Add test conversations (for development purposes)
def add_test_conversations():
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM conversations WHERE channel = %s", ('test',))
            count = c.fetchone()['count']
            if count == 0:
                for i in range(1, 6):
                    c.execute(
                        "INSERT INTO conversations (username, chat_id, channel, ai_enabled, visible_in_conversations, last_updated) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (f"test_user_{i}", f"test_chat_{i}", "test", 1, 0, datetime.now().isoformat())
                    )
                    convo_id = c.fetchone()['id']
                    c.execute(
                        "INSERT INTO messages (convo_id, username, sender, message, timestamp) VALUES (%s, %s, %s, %s, %s)",
                        (convo_id, f"test_user_{i}", "user", f"Test message {i}", datetime.now().isoformat())
                    )
                conn.commit()
                logger.info("✅ Added test conversations")
            else:
                logger.info("✅ Test conversations already exist, skipping insertion")
    except Exception as e:
        logger.error(f"❌ Error adding test conversations: {e}")
        raise

# Initialize database and add test conversations
init_db()
add_test_conversations()

def log_message(convo_id, username, message, sender):
    try:
        timestamp = datetime.now(timezone.utc).isoformat()  # Use ISO format with UTC
        logger.info(f"Attempting to log message for convo_id {convo_id}: {message} (Sender: {sender}, Timestamp: {timestamp})")
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO messages (convo_id, username, message, sender, timestamp) "
                "VALUES (%s, %s, %s, %s, %s)",
                (convo_id, username, message, sender, timestamp)
            )
            conn.commit()
            logger.info(f"✅ Logged message for convo_id {convo_id}: {message} (Sender: {sender})")
        return timestamp  # Return the timestamp for use in emissions
    except Exception as e:
        logger.error(f"❌ Failed to log message for convo_id {convo_id}: {str(e)}")
        raise

class Agent(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(agent_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM agents WHERE id = %s", (agent_id,))
        agent = c.fetchone()
        if agent:
            return Agent(agent['id'], agent['username'])
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user.is_authenticated:
            return redirect(request.args.get("next", "/conversations"))
        return render_template("login.html")
    try:
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            logger.error("❌ Missing username or password in /login request")
            return jsonify({"message": "Missing username or password"}), 400
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, username FROM agents WHERE username = %s AND password = %s",
                (username, password)
            )
            agent = c.fetchone()
            if agent:
                agent_obj = Agent(agent['id'], agent['username'])
                login_user(agent_obj)
                logger.info(f"✅ Login successful for agent: {agent['username']}")
                next_page = request.args.get("next", "/conversations")
                return jsonify({"message": "Login successful", "agent": agent['username'], "redirect": next_page})
            logger.error("❌ Invalid credentials in /login request")
            return jsonify({"message": "Invalid credentials"}), 401
    except Exception as e:
        logger.error(f"❌ Error in /login: {e}")
        return jsonify({"error": "Failed to login"}), 500

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    try:
        username = current_user.username
        logout_user()
        logger.info(f"✅ Logout successful for agent: {username}")
        return jsonify({"message": "Logged out successfully"})
    except Exception as e:
        logger.error(f"❌ Error in /logout: {e}")
        return jsonify({"error": "Failed to logout"}), 500

@app.route("/check-auth", methods=["GET"])
def check_auth():
    try:
        return jsonify({
            "is_authenticated": current_user.is_authenticated,
            "agent": current_user.username if current_user.is_authenticated else None
        })
    except Exception as e:
        logger.error(f"❌ Error in /check-auth: {e}")
        return jsonify({"error": "Failed to check authentication"}), 500

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "GET":
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT key, value, last_updated FROM settings")
                settings = {row['key']: {'value': row['value'], 'last_updated': row['last_updated']} for row in c.fetchall()}
                return jsonify({key: val['value'] for key, val in settings.items()})
        except Exception as e:
            logger.error(f"❌ Error fetching settings: {str(e)}")
            return jsonify({"error": "Failed to fetch settings"}), 500

    elif request.method == "POST":
        try:
            data = request.get_json()
            key = data.get("key")
            value = data.get("value")
            if not key or value is None:
                return jsonify({"error": "Missing key or value"}), 400

            current_timestamp = datetime.now(timezone.utc).isoformat()
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO settings (key, value, last_updated) VALUES (%s, %s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = %s, last_updated = %s",
                    (key, value, current_timestamp, value, current_timestamp)
                )
                conn.commit()
                socketio.emit("settings_updated", {key: value})
                return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"❌ Error updating settings: {str(e)}")
            return jsonify({"error": "Failed to update settings"}), 500

# Page Endpoints
@app.route("/live-messages/")
@login_required
def live_messages_page():
    try:
        return render_template("live-messages.html")
    except Exception as e:
        logger.error(f"❌ Error rendering live-messages page: {e}")
        return jsonify({"error": "Failed to load live-messages page"}), 500

@app.route("/")
def index():
    try:
        return render_template("dashboard.html")
    except Exception as e:
        logger.error(f"❌ Error rendering dashboard page: {e}")
        return jsonify({"error": "Failed to load dashboard page"}), 500

@app.route("/conversations", methods=["GET"])
@login_required
def get_conversations():
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, username, channel, assigned_agent FROM conversations WHERE visible_in_conversations = 1 ORDER BY last_updated DESC"
            )
            conversations = [{"id": row["id"], "username": row["username"], "channel": row["channel"], "assigned_agent": row["assigned_agent"]} for row in c.fetchall()]
            return jsonify(conversations)
    except Exception as e:
        logger.error(f"❌ Error in /conversations: {e}")
        return jsonify({"error": "Failed to fetch conversations"}), 500

@app.route("/handoff", methods=["POST"])
@login_required
def handoff():
    try:
        data = request.get_json()
        convo_id = data.get("conversation_id")
        if not convo_id:
            return jsonify({"error": "Missing conversation_id"}), 400
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE conversations SET assigned_agent = %s, ai_enabled = 0, last_updated = %s WHERE id = %s",
                (current_user.username, datetime.now().isoformat(), convo_id)
            )
            conn.commit()
        socketio.emit("refresh_conversations", {"conversation_id": convo_id})
        return jsonify({"message": "Conversation assigned successfully"})
    except Exception as e:
        logger.error(f"❌ Error in /handoff: {e}")
        return jsonify({"error": "Failed to assign conversation"}), 500

@app.route("/handback-to-ai", methods=["POST"])
@login_required
def handback_to_ai():
    try:
        data = request.get_json()
        convo_id = data.get("conversation_id")
        if not convo_id:
            return jsonify({"error": "Missing conversation_id"}), 400
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE conversations SET assigned_agent = NULL, ai_enabled = 1, last_updated = %s WHERE id = %s",
                (datetime.now().isoformat(), convo_id)
            )
            conn.commit()
        socketio.emit("refresh_conversations", {"conversation_id": convo_id})
        return jsonify({"message": "Conversation handed back to AI"})
    except Exception as e:
        logger.error(f"❌ Error in /handback-to-ai: {e}")
        return jsonify({"error": "Failed to hand back to AI"}), 500

@app.route("/check-visibility", methods=["GET"])
@login_required
def check_visibility():
    try:
        convo_id = request.args.get("conversation_id")
        if not convo_id:
            return jsonify({"error": "Missing conversation_id"}), 400
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT visible_in_conversations FROM conversations WHERE id = %s",
                (convo_id,)
            )
            result = c.fetchone()
            return jsonify({"visible": bool(result["visible_in_conversations"])})
    except Exception as e:
        logger.error(f"❌ Error in /check-visibility: {e}")
        return jsonify({"error": "Failed to check visibility"}), 500

@app.route("/all-whatsapp-messages", methods=["GET"])
@login_required
def get_all_whatsapp_messages():
    try:
        logger.info("Fetching all WhatsApp conversations")
        with get_db_connection() as conn:
            c = conn.cursor()
            logger.info("Executing query to fetch conversations")
            c.execute(
                "SELECT id, chat_id, username, last_updated "
                "FROM conversations "
                "WHERE channel = 'whatsapp' "
                "ORDER BY last_updated DESC"
            )
            conversations = c.fetchall()
            logger.info(f"Found {len(conversations)} conversations: {[(c[0], c[1]) for c in conversations]}")
            result = [
                {
                    "convo_id": convo["id"],
                    "chat_id": convo["chat_id"],
                    "username": convo["username"],
                    "last_updated": convo["last_updated"]
                }
                for convo in conversations
            ]
            logger.info("Returning conversations response")
            return jsonify({"conversations": result})
    except Exception as e:
        logger.error(f"Error fetching all WhatsApp messages: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to fetch conversations"}), 500
    finally:
        release_db_connection(conn)

@app.route("/messages/<int:convo_id>", methods=["GET"])
@login_required
def get_messages_for_conversation(convo_id):
    logger.info(f"Fetching messages for convo_id {convo_id}")
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            # Fetch conversation details
            c.execute(
                "SELECT username FROM conversations WHERE id = %s",
                (convo_id,)
            )
            convo = c.fetchone()
            if not convo:
                logger.error(f"❌ Conversation not found: {convo_id}")
                return jsonify({"error": "Conversation not found"}), 404

            # Fetch messages for the conversation
            c.execute(
                "SELECT message, sender, timestamp FROM messages WHERE convo_id = %s ORDER BY timestamp ASC",
                (convo_id,)
            )
            messages = c.fetchall()
            logger.info(f"✅ Fetched {len(messages)} messages for convo_id {convo_id}")

            return jsonify({
                "username": convo["username"],
                "messages": [
                    {"message": msg["message"], "sender": msg["sender"], "timestamp": msg["timestamp"]}
                    for msg in messages
                ]
            })
    except Exception as e:
        logger.error(f"❌ Error in /messages/{convo_id}: {str(e)}")
        return jsonify({"error": "Failed to fetch messages"}), 500
    finally:
        release_db_connection(conn)

# Messaging Helper Functions
def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    if not chat_id or not isinstance(chat_id, str):
        logger.error(f"❌ Invalid chat_id: {chat_id}")
        return False
    if not text or not isinstance(text, str):
        logger.error(f"❌ Invalid text: {text}")
        return False
    if len(text) > 4096:
        logger.error(f"❌ Text exceeds 4096 characters: {len(text)}")
        text = text[:4093] + "..."

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    headers = {"Content-Type": "application/json"}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"✅ Sent Telegram message to {chat_id}: {text}")
            time.sleep(0.5)
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ Telegram API error (Attempt {attempt + 1}/{max_retries}): {str(e)}, Response: {e.response.text}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Telegram request failed (Attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False
    logger.error(f"❌ Failed to send Telegram message after {max_retries} attempts")
    return False

def send_whatsapp_message(phone_number, text):
    try:
        if not TWILIO_WHATSAPP_NUMBER.startswith("whatsapp:"):
            logger.error(f"❌ TWILIO_WHATSAPP_NUMBER must start with 'whatsapp:': {TWILIO_WHATSAPP_NUMBER}")
            return False

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        if not phone_number.startswith("whatsapp:"):
            phone_number = f"whatsapp:{phone_number}"

        message = client.messages.create(
            body=text,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=phone_number
        )

        logger.info(f"✅ Sent WhatsApp message to {phone_number}: {text}, SID: {message.sid}")
        return True
    except TwilioRestException as e:
        logger.error(f"❌ Twilio error sending WhatsApp message: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Error sending WhatsApp message: {str(e)}")
        return False

def send_instagram_message(user_id, text):
    try:
        response = requests.post(
            f"{INSTAGRAM_API_URL}/me/messages?access_token={INSTAGRAM_ACCESS_TOKEN}",
            json={"recipient": {"id": user_id}, "message": {"text": text}}
        )
        response.raise_for_status()
        logger.info(f"✅ Sent Instagram message to {user_id}: {text}")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending Instagram message to {user_id}: {str(e)}")
        return False

def check_availability(check_in, check_out):
    logger.info(f"✅ Checking availability from {check_in} to {check_out}")
    try:
        current_date = check_in
        while current_date < check_out:
            start_time = current_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            end_time = (current_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'

            events_result = service.events().list(
                calendarId='a33289c61cf358216690e7cc203d116cec4c44075788fab3f2b200f5bbcd89cc@group.calendar.google.com',
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            if any(event.get('summary') == "Fully Booked" for event in events):
                return f"Sorry, the dates from {check_in.strftime('%B %d, %Y')} to {(check_out - timedelta(days=1)).strftime('%B %d, %Y')} are not available. We are fully booked on {current_date.strftime('%B %d, %Y')}."

            current_date += timedelta(days=1)

        return f"Yes, the dates from {check_in.strftime('%B %d, %Y')} to {(check_out - timedelta(days=1)).strftime('%B %d, %Y')} are available."
    except Exception as e:
        logger.error(f"❌ Google Calendar API error: {str(e)}")
        return "Sorry, I’m having trouble checking availability right now. I’ll connect you with a team member to assist you."

def ai_respond(message, convo_id):
    logger.info(f"✅ Generating AI response for convo_id {convo_id}: {message}")
    try:
        date_match = re.search(
            r'(?:are rooms available|availability|do you have any rooms|rooms available|what about|'
            r'¿hay habitaciones disponibles?|disponibilidad|¿tienen habitaciones?|habitaciones disponibles?|qué tal)?\s*'
            r'(?:from|on|de|el)?\s*'
            r'(?:(?:([A-Za-z]{3,9})\s+(\d{1,2}(?:st|nd|rd|th)?))|(?:(\d{1,2})\s*(?:de)?\s*([A-Za-z]{3,9})))'
            r'(?:\s*(?:to|a|al|until|hasta)?\s*'
            r'(?:(?:([A-Za-z]{3,9})\s+(\d{1,2}(?:st|nd|rd|th)?))|(?:(\d{1,2})\s*(?:de)?\s*([A-Za-z]{3,9}))))?',
            message.lower()
        )
        if date_match:
            month1_en, day1_en, day1_es, month1_es, month2_en, day2_en, day2_es, month2_es = date_match.groups()
            current_year = datetime.now().year
            spanish_to_english_months = {
                "enero": "January", "febrero": "February", "marzo": "March", "abril": "April",
                "mayo": "May", "junio": "June", "julio": "July", "agosto": "August",
                "septiembre": "September", "octubre": "October", "noviembre": "November", "diciembre": "December"
            }

            if month1_en and day1_en:
                check_in_str = f"{month1_en} {day1_en}"
                check_in_str = re.sub(r'(st|nd|rd|th)', '', check_in_str).strip()
                check_in = datetime.strptime(f"{check_in_str} {current_year}", '%B %d %Y')
            elif day1_es and month1_es:
                month1_en = spanish_to_english_months.get(month1_es.lower(), month1_es)
                check_in_str = f"{month1_en} {day1_es}"
                check_in = datetime.strptime(f"{check_in_str} {current_year}", '%B %d %Y')
            else:
                return "Sorry, I couldn’t understand the dates. Please use a format like 'March 20' or '20 de marzo'." if "sorry" in message.lower() else \
                       "Lo siento, no entendí las fechas. Por favor, usa un formato como '20 de marzo' o 'March 20'."

            if month2_en and day2_en:
                check_out_str = f"{month2_en} {day2_en}"
                check_out_str = re.sub(r'(st|nd|rd|th)', '', check_out_str).strip()
                check_out = datetime.strptime(f"{check_out_str} {current_year}", '%B %d %Y')
            elif day2_es and month2_es:
                month2_en = spanish_to_english_months.get(month2_es.lower(), month2_es)
                check_out_str = f"{month2_en} {day2_es}"
                check_out = datetime.strptime(f"{check_out_str} {current_year}", '%B %d %Y')
            else:
                check_out = check_in + timedelta(days=1)

            if check_out < check_in:
                check_out = check_out.replace(year=check_out.year + 1)

            if check_out <= check_in:
                return "The check-out date must be after the check-in date. Please provide a valid range." if "sorry" in message.lower() else \
                       "La fecha de salida debe ser posterior a la fecha de entrada. Por favor, proporciona un rango válido."

            availability = check_availability(check_in, check_out)
            if "are available" in availability.lower():
                booking_intent = f"{check_in.strftime('%Y-%m-%d')} to {check_out.strftime('%Y-%m-%d')}"
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute(
                        "UPDATE conversations SET booking_intent = %s WHERE id = %s",
                        (booking_intent, convo_id)
                    )
                    conn.commit()
                response = f"{availability}. Would you like to book?" if "sorry" in message.lower() else \
                           f"{availability.replace('are available', 'están disponibles')}. ¿Te gustaría reservar?"
            else:
                response = availability if "sorry" in message.lower() else \
                           availability.replace("are not available", "no están disponibles").replace("fully booked", "completamente reservado")
            return response

        is_spanish = any(spanish_word in message.lower() for spanish_word in ["reservar", "habitación", "disponibilidad"])
        if "book" in message.lower() or "booking" in message.lower() or "reservar" in message.lower():
            return "I’ll connect you with a team member to assist with your booking." if not is_spanish else \
                   "Te conectaré con un miembro del equipo para que te ayude con tu reserva."

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT message, sender, timestamp FROM messages WHERE convo_id = %s ORDER BY timestamp DESC LIMIT 10",
                (convo_id,)
            )
            messages = c.fetchall()
        conversation_history = [
            {"role": "system", "content": TRAINING_DOCUMENT + "\nYou are a hotel customer service and sales agent for Amapola Resort. Use the provided business information and Q&A to answer guest questions. Maintain conversation context. Detect the user's language (English or Spanish) based on their input and respond in the same language. If you don’t know the answer or the query is complex, respond with the appropriate escalation message in the user's language. Do not mention room types or pricing unless specifically asked."}
        ]
        for msg in messages:
            message_text, sender, timestamp = msg['message'], msg['sender'], msg['timestamp']
            role = "user" if sender == "user" else "assistant"
            conversation_history.append({"role": role, "content": message_text})
        conversation_history.append({"role": "user", "content": message})

        retry_attempts = 2
        for attempt in range(retry_attempts):
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    messages=conversation_history,
                    max_tokens=150
                )
                ai_reply = response.choices[0].message.content.strip()
                logger.info(f"✅ AI reply: {ai_reply}")
                if "sorry" in ai_reply.lower() or "lo siento" in ai_reply.lower():
                    return ai_reply
                return ai_reply
            except Exception as e:
                logger.error(f"❌ OpenAI error (Attempt {attempt + 1}): {str(e)}")
                if attempt == retry_attempts - 1:
                    return "I’m sorry, I’m having trouble processing your request right now. I’ll connect you with a team member to assist you." if not is_spanish else \
                           "Lo siento, tengo problemas para procesar tu solicitud ahora mismo. Te conectaré con un miembro del equipo para que te ayude."
                time.sleep(1)
                continue
    except Exception as e:
        logger.error(f"❌ Error in ai_respond for convo_id {convo_id}: {str(e)}")
        return "I’m sorry, I’m having trouble processing your request right now. I’ll connect you with a team member to assist you." if "sorry" in message.lower() else \
               "Lo siento, tengo problemas para procesar tu solicitud ahora mismo. Te conectaré con un miembro del equipo para que te ayude."

def detect_language(message, convo_id):
    spanish_keywords = ["hola", "gracias", "reservar", "habitación", "disponibilidad", "marzo", "abril"]
    if any(keyword in message.lower() for keyword in spanish_keywords):
        return "es"
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT message FROM messages WHERE convo_id = %s ORDER BY timestamp DESC LIMIT 5",
            (convo_id,)
        )
        messages = c.fetchall()
        for msg in messages:
            if any(keyword in msg['message'].lower() for keyword in spanish_keywords):
                return "es"
    
    return "en"

@app.route("/whatsapp", methods=["GET", "POST"])
def whatsapp():
    if request.method == "GET":
        return Response("Method not allowed", status=405)

    # Extract Twilio WhatsApp data
    form = request.form
    message_body = form.get("Body", "").strip()
    from_number = form.get("From", "")
    chat_id = from_number.replace("whatsapp:", "")
    if not message_body or not chat_id:
        logger.error("❌ Missing message body or chat_id in WhatsApp request")
        return Response("Missing required fields", status=400)

    # Log the user message timestamp immediately
    user_timestamp = datetime.now(timezone.utc).isoformat()

    # Offload processing to Celery
    process_whatsapp_message.delay(from_number, chat_id, message_body, user_timestamp)
    return Response("Message queued for processing", status=202)

# Socket.IO Event Handlers
@socketio.on("connect")
def handle_connect():
    logger.info("✅ Client connected to Socket.IO")
    emit("status", {"message": "Connected to server"})

@socketio.on("disconnect")
def handle_disconnect():
    logger.info("ℹ️ Client disconnected from Socket.IO")

@socketio.on("join_conversation")
def handle_join_conversation(data):
    logger.info(f"Received join_conversation data: {data}")
    convo_id = data.get("conversation_id")
    if not convo_id:
        logger.error("❌ Missing conversation_id in join_conversation event")
        emit("error", {"message": "Missing conversation ID"})
        return
    join_room(str(convo_id))
    logger.info(f"✅ Client joined conversation {convo_id}")
    emit("status", {"message": f"Joined conversation {convo_id}"})

@socketio.on("leave_conversation")
def handle_leave_conversation(data):
    convo_id = data.get("conversation_id")
    if not convo_id:
        logger.error("❌ Missing conversation_id in leave_conversation event")
        emit("error", {"message": "Missing conversation ID"})
        return
    leave_room(str(convo_id))
    logger.info(f"✅ Client left conversation room: {convo_id}")
    emit("status", {"message": f"Left conversation {convo_id}"})

@socketio.on("agent_message")
def handle_agent_message(data):
    try:
        convo_id = data.get("convo_id")
        message = data.get("message")
        channel = data.get("channel", "whatsapp")
        if not convo_id or not message:
            logger.error("❌ Missing convo_id or message in agent_message event")
            emit("error", {"message": "Missing required fields"})
            return

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT username, chat_id, channel FROM conversations WHERE id = %s",
                (convo_id,)
            )
            result = c.fetchone()
            if not result:
                logger.error(f"❌ Conversation not found: {convo_id}")
                emit("error", {"message": "Conversation not found"})
                return
            username, chat_id, convo_channel = result

        # Log the agent's message
        agent_timestamp = log_message(convo_id, username, message, "agent")

        # Emit to the UI
        emit("new_message", {
            "convo_id": convo_id,
            "message": message,
            "sender": "agent",
            "channel": convo_channel,
            "timestamp": agent_timestamp,
        }, room=str(convo_id))
        emit("live_message", {
            "convo_id": convo_id,
            "message": message,
            "sender": "agent",
            "chat_id": chat_id,
            "username": username,
            "timestamp": agent_timestamp,
        })

        # Send to WhatsApp
        if convo_channel == "whatsapp":
            if not chat_id:
                logger.error(f"❌ No chat_id found for convo_id {convo_id}")
                emit("error", {"convo_id": convo_id, "message": "Failed to send message to WhatsApp: No chat_id found", "channel": "whatsapp"})
                return
            if not send_whatsapp_message(chat_id, message):
                logger.error(f"❌ Failed to send agent message to WhatsApp for chat_id {chat_id}")
                emit("error", {"convo_id": convo_id, "message": "Failed to send message to WhatsApp", "channel": "whatsapp"})
                return

        # Update last_updated timestamp
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE conversations SET last_updated = %s WHERE id = %s",
                (agent_timestamp, convo_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Error in agent_message event: {str(e)}")
        emit("error", {"message": "Failed to process agent message"})

if __name__ == "__main__":
    try:
        logger.info("✅ Starting Flask-SocketIO server")
        socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {str(e)}")
        raise
