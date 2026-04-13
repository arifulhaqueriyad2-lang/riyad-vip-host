import os
import zipfile
import subprocess
import sys
import shutil
import asyncio
import logging
import time
import signal
import platform
import threading
import queue
from threading import Thread
from flask import Flask, jsonify
from telegram import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- [ᴄᴏɴꜰɪɢᴜʀᴀᴛɪᴏɴ] ---
TOKEN = os.environ.get('BOT_TOKEN', '8580370547:AAFHkqpu1ep7Gl6Erhqy6yci7MQ4vOjMK2Q')

# মাল্টি-এডমিন সিস্টেম: ৫টা এডমিন + ১টা ওনার = মোট ৬টা
ADMIN_IDS = [
    int(os.environ.get('ADMIN_ID_1', '8124942237')),  # প্রাইমারি এডমিন/ওনার
    int(os.environ.get('ADMIN_ID_2', '0')),
    int(os.environ.get('ADMIN_ID_3', '0')),
    int(os.environ.get('ADMIN_ID_4', '0')),
    int(os.environ.get('ADMIN_ID_5', '0')),
    int(os.environ.get('OWNER_ID', '8124942237')),  # ওনার আইডি
]
ADMIN_IDS = [aid for aid in ADMIN_IDS if aid != 0]  # শূন্য আইডি বাদ দাও

# প্রাইমারি এডমিনের তথ্য (Contact Owner এর জন্য)
PRIMARY_ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 8423357174
ADMIN_USERNAME = "@riyadcoder"
ADMIN_DISPLAY_NAME = "✨ 𝗥𝗜𝗬𝗔𝗗 𝗖𝗢𝗗𝗘𝗥 ✨"  # এখানে এডমিনের নাম পরিবর্তন করতে পারেন

# 🔴 চ্যানেল বাধ্যতামূলক সেটিংস - ডিজেবলড (খালি রাখুন)
REQUIRED_CHANNEL = "https://t.me/RIYAD_CODER_OFC"  # ← খালি রাখুন চ্যানেল চেক ডিজেবল করতে
REQUIRED_CHANNEL_ID = -1003870150321  # অথবা চ্যানেল আইডি (যেমন: -1001234567890)

BASE_DIR = os.path.join(os.getcwd(), "hosted_projects")
PORT = int(os.environ.get('PORT', 8080))

# ʟᴏɢɢɪɴɢ ꜱᴇᴛᴜᴘ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ᴄʀᴇᴀᴛᴇ ᴅɪʀᴇᴄᴛᴏʀɪᴇꜱ
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)

# --- [ɢʟᴏʙᴀʟ ᴅᴀᴛᴀ] ---
running_processes = {}
bot_locked = False
auto_restart_mode = False
user_upload_state = {}
project_owners = {}
recovery_enabled = True  # 𝗔𝗨𝗧𝗢 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬 ꜱᴡɪᴛᴄʜ
live_logs_enabled = True  # 🔴 লাইভ লগ অন/অফ সুইচ
user_log_sessions = {}  # 🔴 ইউজারদের লগ সেশন ট্র্যাক করার জন্য {user_id: {"project": name, "message_id": id, "active": True}}

# --- [PSUTIL CHECK] ---
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, system health will use basic info")

# --- [ᴀᴜᴛᴏ ᴘᴀᴄᴋᴀɢᴇ ɪɴꜱᴛᴀʟʟᴇʀ] ---
def auto_install_packages():
    """অটোমেটিক প্যাকেজ ইন্সটলার"""
    required_packages = [
        'flask', 'python-telegram-bot', 'psutil', 'aiohttp'
    ]
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            logger.info(f"✅ {package} already installed")
        except ImportError:
            logger.info(f"📦 Installing {package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
                logger.info(f"✅ {package} installed successfully")
            except Exception as e:
                logger.error(f"❌ Failed to install {package}: {e}")

# বট চালু হওয়ার সময় প্যাকেজ চেক করুন
auto_install_packages()

# --- [ʟᴏɢ ꜱᴛʀᴇᴀᴍᴇʀ ᴄʟᴀꜱꜱ] ---
class LogStreamer:
    """রিয়েল-টাইম লগ স্ট্রিমিং সিস্টেম"""
    
    def __init__(self):
        self.active_streams = {}  # {project_name: {"queue": Queue(), "subscribers": set()}}
        self.monitor_threads = {}
    
    def start_stream(self, project_name, process):
        """নতুন প্রজেক্টের লগ স্ট্রিম শুরু করুন"""
        if project_name in self.active_streams:
            return
        
        log_queue = queue.Queue()
        self.active_streams[project_name] = {
            "queue": log_queue,
            "subscribers": set(),
            "process": process,
            "last_lines": [],  # শেষ ৫০টা লাইন সংরক্ষণ করুন
            "running": True
        }
        
        # stdout থ্রেড
        stdout_thread = threading.Thread(
            target=self._read_output,
            args=(project_name, process.stdout, "stdout"),
            daemon=True
        )
        # stderr থ্রেড
        stderr_thread = threading.Thread(
            target=self._read_output,
            args=(project_name, process.stderr, "stderr"),
            daemon=True
        )
        
        stdout_thread.start()
        stderr_thread.start()
        
        self.monitor_threads[project_name] = (stdout_thread, stderr_thread)
        logger.info(f"📝 Log stream started for {project_name}")
    
    def _read_output(self, project_name, pipe, pipe_type):
        """পাইপ থেকে লগ পড়ুন এবং কিউতে রাখুন"""
        stream_data = self.active_streams.get(project_name)
        if not stream_data:
            return
        
        try:
            for line in iter(pipe.readline, ''):
                if not stream_data["running"]:
                    break
                
                timestamp = time.strftime("%H:%M:%S")
                log_entry = f"[{timestamp}] [{pipe_type.upper()}] {line.rstrip()}"
                
                # কিউতে যোগ করুন
                stream_data["queue"].put(log_entry)
                
                # শেষ ৫০টা লাইন সংরক্ষণ করুন
                stream_data["last_lines"].append(log_entry)
                if len(stream_data["last_lines"]) > 50:
                    stream_data["last_lines"].pop(0)
                
                # সাবস্ক্রাইবারদের পাঠান
                for user_id in list(stream_data["subscribers"]):
                    try:
                        if user_id in user_log_sessions and user_log_sessions[user_id]["active"]:
                            user_log_sessions[user_id]["buffer"].append(log_entry)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"Log read error for {project_name}: {e}")
        finally:
            pipe.close()
    
    def subscribe(self, project_name, user_id, chat_id, message_id):
        """ইউজারকে লগ স্ট্রিমে যোগ করুন"""
        if project_name not in self.active_streams:
            return False
        
        stream_data = self.active_streams[project_name]
        stream_data["subscribers"].add(user_id)
        
        user_log_sessions[user_id] = {
            "project": project_name,
            "chat_id": chat_id,
            "message_id": message_id,
            "buffer": list(stream_data["last_lines"]),  # আগের লগগুলো দেখান
            "active": True,
            "last_update": time.time()
        }
        return True
    
    def unsubscribe(self, user_id):
        """ইউজারকে লগ স্ট্রিম থেকে সরান"""
        if user_id in user_log_sessions:
            project_name = user_log_sessions[user_id]["project"]
            if project_name in self.active_streams:
                self.active_streams[project_name]["subscribers"].discard(user_id)
            user_log_sessions[user_id]["active"] = False
            return True
        return False
    
    def stop_stream(self, project_name):
        """প্রজেক্টের লগ স্ট্রিম বন্ধ করুন"""
        if project_name in self.active_streams:
            self.active_streams[project_name]["running"] = False
            if project_name in self.monitor_threads:
                for thread in self.monitor_threads[project_name]:
                    thread.join(timeout=2)
            del self.active_streams[project_name]
            if project_name in self.monitor_threads:
                del self.monitor_threads[project_name]
    
    def get_recent_logs(self, project_name, lines=20):
        """শেষ কিছু লাইন পান"""
        if project_name in self.active_streams:
            return self.active_streams[project_name]["last_lines"][-lines:]
        return []
    
    def is_streaming(self, project_name):
        """চেক করুন স্ট্রিম চলছে কিনা"""
        return project_name in self.active_streams and self.active_streams[project_name]["running"]

# গ্লোবাল লগ স্ট্রিমার ইনস্ট্যান্স
log_streamer = LogStreamer()

# --- [ʜᴇʟᴘᴇʀ ꜰᴜɴᴄᴛɪᴏɴ] ---
def is_admin(user_id):
    """চেক করে ইউজার এডমিন কিনা"""
    return user_id in ADMIN_IDS

# --- [ᴄʜᴀɴɴᴇʟ ᴍᴇᴍʙᴇʀꜱʜɪᴘ ᴄʜᴇᴄᴋ - ডিজেবলড] ---
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """চ্যানেল চেক ডিজেবলড - সবসময় True রিটার্ন করে"""
    return True  # 🔴 ডিজেবলড

async def require_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """চ্যানেল জয়েন বাধ্যতামূলক চেক - ডিজেবলড"""
    return True  # 🔴 ডিজেবলড - সবসময় True

# --- [ʟᴏᴀᴅɪɴɢ ᴀɴɪᴍᴀᴛɪᴏɴꜱ] ---
class Loading:
    @staticmethod
    def executing():
        return [
            "🌺 ᴇxᴇᴄᴜᴛɪɴɢ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "🌼 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▱▱▱▱▱▱▱▱▱] 10%",
            "🌻 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▱▱▱▱▱▱▱▱] 20%",
            "🌸 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▱▱▱▱▱▱▱] 30%",
            "🌹 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▱▱▱▱▱▱] 40%",
            "🍁 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▰▱▱▱▱▱] 50%",
            "🌿 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 60%",
            "🌳 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▰▰▰▱▱▱] 70%",
            "🌲 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▰▰▰▰▱▱] 80%",
            "🪷 ᴇxᴇᴄᴜᴛɪɴɗ: [▰▰▰▰▰▰▰▰▰▱] 90%",
            "✅ ᴄᴏᴍᴘʟᴇᴛᴇ: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def uploading():
        return [
            "🗳️ ᴜᴘʟᴏᴀᴅɪɴɗ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "🗳️ ᴜᴘʟᴏᴀᴅɪɴɗ: [▰▱▱▱▱▱▱▱▱▱] 25%",
            "🗳️ ᴜᴘʟᴏᴀᴅɪɴɗ: [▰▰▰▱▱▱▱▱▱▱] 50%",
            "🗳️ ᴜᴘʟᴏᴀᴅɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 75%",
            "✅ ᴜᴘʟᴏᴀᴅ ᴄᴏᴍᴘʟᴇᴛᴇ: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def installing():
        return [
            "📦 ɪɴꜱᴛᴀʟʟɪɴɗ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "📦 ɪɴꜱᴛᴀʟʟɪɴɗ: [▰▰▱▱▱▱▱▱▱▱] 20%",
            "📦 ɪɴꜱᴛᴀʟʟɪɴɗ: [▰▰▰▰▱▱▱▱▱▱] 40%",
            "📦 ɪɴꜱᴛᴀʟʟɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 60%",
            "📦 ɪɴꜱᴛᴀʟʟɪɴɗ: [▰▰▰▰▰▰▰▰▱▱] 80%",
            "✅ ɪɴꜱᴛᴀʟʟᴇᴅ: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def deleting():
        return [
            "🗑️ ᴅᴇʟᴇᴛɪɴɗ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "🗑️ ᴅᴇʟᴇᴛɪɴɗ: [▰▰▰▱▱▱▱▱▱▱] 30%",
            "🗑️ ᴅᴇʟᴇᴛɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 60%",
            "✅ 𝗗𝗘𝗟𝗘𝗧𝗘𝗗: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def restarting():
        return [
            "🇧🇩 ʀᴇꜱᴛᴀʀᴛɪɴɗ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "🇧🇷 ʀᴇꜱᴛᴀʀᴛɪɴɗ: [▰▰▱▱▱▱▱▱▱▱] 20%",
            "🇦🇷 ʀᴇꜱᴛᴀʀᴛɪɴɗ: [▰▰▰▰▱▱▱▱▱▱] 40%",
            "🇦🇨 ʀᴇꜱᴛᴀʀᴛɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 60%",
            "🇬🇵 ʀᴇꜱᴛᴀʀᴛɪɴɗ: [▰▰▰▰▰▰▰▰▱▱] 80%",
            "✅ ʀᴇꜱᴛᴀʀᴛᴇᴅ: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def recovering():
        return [
            "🔄 ʀᴇᴄᴏᴠᴇʀɪɴɗ: [▱▱▱▱▱▱▱▱▱▱] 0%",
            "🔄 ʀᴇᴄᴏᴠᴇʀɪɴɗ: [▰▰▰▱▱▱▱▱▱▱] 30%",
            "🔄 ʀᴇᴄᴏᴠᴇʀɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 60%",
            "✅ 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗘𝗗: [▰▰▰▰▰▰▰▰▰▰] 100%"
        ]
    
    @staticmethod
    def logs_on():
        return [
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▱▱▱▱▱▱▱▱▱▱] 𝗢𝗙𝗙",
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▱▱▱▱▱▱▱] ꜱᴛᴀʀᴛɪɴɗ...",
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▰▰▰▱▱▱▱] ᴄᴏɴɴᴇᴄᴛɪɴɗ...",
            "✅ 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▰▰▰▰▰▰▰] 𝗢𝗡𝗟𝗜𝗡𝗘"
        ]
    
    @staticmethod
    def logs_off():
        return [
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▰▰▰▰▰▰▰] 𝗢𝗡𝗟𝗜𝗡𝗘",
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▰▰▰▱▱▱▱] ᴅɪꜱᴄᴏɴɴᴇᴄᴛɪɴɗ...",
            "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▰▰▰▱▱▱▱▱▱▱] ᴄʟᴏꜱɪɴɗ...",
            "❌ 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: [▱▱▱▱▱▱▱▱▱▱] 𝗢𝗙𝗙"
        ]

# ʜᴇʟᴘᴇʀ ꜰᴜɴᴄᴛɪᴏɴ ꜰᴏʀ ʟᴏᴀᴅɪɴɗ ᴀɴɪᴍᴀᴛɪᴏɴ
async def animate(update, context, frames, delay=0.5, final_text=None):
    msg = await update.message.reply_text(frames[0]) if hasattr(update, 'message') else await update.edit_message_text(frames[0])
    for frame in frames[1:]:
        await asyncio.sleep(delay)
        try:
            msg = await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=frame)
        except:
            pass
    if final_text:
        await asyncio.sleep(0.3)
        try:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=final_text, parse_mode='Markdown')
        except:
            pass
    return msg

# --- [ꜰʟᴀꜱᴋ ᴡᴇʙ ꜱᴇʀᴠᴇʀ] ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "ᴀᴘᴏɴ ᴘʀᴇᴍɪᴜᴍ ʜᴏꜱᴛɪɴɗ ᴠ1",
        "projects": len(project_owners),
        "running": len([p for p in running_processes.values() if p.poll() is None]),
        "recovery": recovery_enabled,
        "live_logs": live_logs_enabled
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_web():
    app.run(host='0.0.0.0', port=PORT, debug=False)
# --- [ᴋᴇʏʙᴏᴀʀᴅ ꜱᴇᴛᴜᴘ] ---
def get_main_keyboard(user_id):
    lock_status = "🔓 𝗨𝗡𝗟𝗢𝗖𝗞 𝗦𝗬𝗦𝗧𝗘𝗠" if bot_locked else "🔒 𝗟𝗢𝗖𝗞 𝗦𝗬𝗦𝗧𝗘𝗠"
    restart_status = "🔄 𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 : 𝗢𝗙𝗙" if auto_restart_mode else "🔄 𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 : 𝗢𝗡"
    recovery_status = "🛡️ 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬 : 𝗢𝗙𝗙" if recovery_enabled else "🛡️ 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬 : 𝗢𝗡"
    # 🔴 লাইভ লগস স্ট্যাটাস বাটন
    logs_status = "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦 : 𝗢𝗙𝗙" if live_logs_enabled else "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦 : 𝗢𝗡"
    
    if is_admin(user_id):
        # এডমিন কিবোর্ড - শেষের ৪টা বাটন সিরিয়ালে (ডান-বাম)
        layout = [
            [KeyboardButton("🗳️ 𝗨𝗣𝗟𝗢𝗔𝗗 𝗠𝗔𝗡𝗔𝗚𝗘𝗥"), KeyboardButton("📮 𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥")],
            [KeyboardButton("🗑️ 𝗗𝗘𝗟𝗘𝗧𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥"), KeyboardButton("🏩 𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛")],
            [KeyboardButton("🌎 𝗦𝗘𝗥𝗩𝗘𝗥 𝗜𝗡𝗙𝗢"), KeyboardButton("📠 𝗖𝗢𝗡𝗧𝗔𝗖𝗧 𝗔𝗗𝗠𝗜𝗡")],
            [KeyboardButton(lock_status), KeyboardButton(restart_status)],  # সিরিয়াল ১
            [KeyboardButton(recovery_status), KeyboardButton("🎬 𝗣𝗥𝗢𝗝𝗘𝗖𝗧 𝗙𝗜𝗟𝗘")],  # সিরিয়াল ২
            [KeyboardButton(logs_status)]  # 🔴 লাইভ লগস বাটন - সবাই ব্যবহার করতে পারবে
        ]
    else:
        # নর্মাল ইউজার কিবোর্ড - লাইভ লগস সহ
        layout = [
            [KeyboardButton("🗳️ 𝗨𝗣𝗟𝗢𝗔𝗗 𝗠𝗔𝗡𝗔𝗚𝗘𝗥"), KeyboardButton("📮 𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥")],
            [KeyboardButton("🗑️ 𝗗𝗘𝗟𝗘𝗧𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥"), KeyboardButton("🏩 𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛")],
            [KeyboardButton("🌎 𝗦𝗘𝗥𝗩𝗘𝗥 𝗜𝗡𝗙𝗢"), KeyboardButton("📠 𝗖𝗢𝗡𝗧𝗔𝗖𝗧 𝗔𝗗𝗠𝗜𝗡")],
            [KeyboardButton(logs_status)]  # 🔴 লাইভ লগস বাটন - সবার জন্য
        ]
    return ReplyKeyboardMarkup(layout, resize_keyboard=True)

# --- [𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦 𝗩𝗜𝗘𝗪ᴇʀ ᴛᴀꜱᴋ] ---
async def log_viewer_task(context: ContextTypes.DEFAULT_TYPE):
    """ব্যাকগ্রাউন্ড টাস্ক যা ইউজারদের লগ মেসেজ আপডেট করে"""
    logger.info("📝 Log viewer task started")
    while True:
        try:
            if not live_logs_enabled:
                await asyncio.sleep(2)
                continue
            
            current_time = time.time()
            
            for user_id, session in list(user_log_sessions.items()):
                if not session["active"]:
                    continue
                
                # প্রতি ২ সেকেন্ডে আপডেট করুন
                if current_time - session["last_update"] < 2:
                    continue
                
                # বাফার থেকে লগ নিন
                logs = session["buffer"][-20:]  # শেষ ২০টা লাইন
                session["buffer"] = []  # বাফার ক্লিয়ার করুন
                
                if not logs and not session.get("has_content"):
                    continue
                
                # লগ ফরম্যাট করুন
                log_text = "\n".join(logs) if logs else "⏳ ওয়েটিং ফর লগস..."
                
                # টার্মিনাল স্টাইলে দেখান
                terminal_text = (
                    f"📺 **𝗟𝗜𝗩𝗘 𝗖𝗢𝗡𝗦𝗢𝗟ᴇ - {session['project']}**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"```\n"
                    f"{log_text[-3500:]}\n"  # টেলিগ্রাম লিমিটের জন্য
                    f"```\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 𝗢𝗡𝗟𝗜𝗡𝗘 | 🔄 𝗔𝗨𝗧𝗢-𝗨𝗣𝗗𝗔𝗧𝗘: 2ꜱ"
                )
                
                try:
                    await context.bot.edit_message_text(
                        chat_id=session["chat_id"],
                        message_id=session["message_id"],
                        text=terminal_text,
                        parse_mode='Markdown'
                    )
                    session["last_update"] = current_time
                    session["has_content"] = True
                except Exception as e:
                    # মেসেজ এডিট ফেইল হলে (অনেক দ্রুত আপডেট বা ডিলিট)
                    if "message is not modified" not in str(e).lower():
                        logger.debug(f"Log update error for user {user_id}: {e}")
                        if "message to edit not found" in str(e).lower():
                            session["active"] = False
            
            await asyncio.sleep(0.5)  # CPU ব্যবহার কমানোর জন্য
            
        except Exception as e:
            logger.error(f"Log viewer task error: {e}")
            await asyncio.sleep(2)

# --- [𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛 ꜰᴜɴᴄᴛɪᴏɴ] ---
async def get_system_health():
    """সিস্টেম হেলথ ডেটা সংগ্রহ করে"""
    try:
        if PSUTIL_AVAILABLE:
            # CPU ইনফো
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # RAM ইনফো
            ram = psutil.virtual_memory()
            ram_used_gb = ram.used / (1024**3)
            ram_total_gb = ram.total / (1024**3)
            ram_percent = ram.percent
            
            # ডিস্ক ইনফো
            disk = psutil.disk_usage('/')
            disk_used_gb = disk.used / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            disk_percent = disk.percent
            
            # বুট টাইম
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            
            return {
                "status": "ok",
                "cpu": f"{cpu_percent}%",
                "cpu_cores": cpu_count,
                "ram": f"{ram_percent}%",
                "ram_used": f"{ram_used_gb:.1f}GB",
                "ram_total": f"{ram_total_gb:.1f}GB",
                "disk": f"{disk_percent}%",
                "disk_used": f"{disk_used_gb:.1f}GB",
                "disk_total": f"{disk_total_gb:.1f}GB",
                "uptime": f"{int(uptime//3600)}h {int((uptime%3600)//60)}m"
            }
        else:
            # psutil না থাকলে বেসিক ইনফো
            return {
                "status": "basic",
                "platform": platform.system(),
                "machine": platform.machine(),
                "processor": platform.processor() or "Unknown",
                "python_version": platform.python_version()
            }
    except Exception as e:
        logger.error(f"System health error: {e}")
        return {"status": "error", "error": str(e)}

# --- [ᴄᴏʀᴇ ꜰᴜɴᴄᴛɪᴏɴꜱ] ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🔴 চ্যানেল জয়েন চেক ডিজেবলড
    # if not await require_channel_join(update, context):
    #     return
    
    if bot_locked and not is_admin(user_id):
        await update.message.reply_text("🔒 **ꜱʏꜱᴛᴇᴍ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ ʟᴏᴄᴋᴇᴅ ʙʏ ᴀᴅᴍɪɴ**", parse_mode='Markdown')
        return
    
    msg = (
        "🌍 **𝗥𝗜𝗬𝗔𝗗 𝗣𝗥𝗘𝗠𝗜𝗨𝗠 𝗛𝗢𝗦𝗧𝗜𝗡𝗚** 🌸\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💙 **ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴇʟɪᴛᴇ ᴘᴀɴᴇʟ**\n"
        "🔮 **আপনাকে স্বাগতম! এটি বাংলাদেশের সবচেয়ে শক্তিশালী প্রিমিয়াম সার্ভার।**\n\n"
        f"🇧🇩 **ᴏᴡɴᴇʀ:** `{ADMIN_USERNAME}`\n"
        f"📢 **ᴄʜᴀɴɴᴇʟ:** {'Not Set' if not REQUIRED_CHANNEL else REQUIRED_CHANNEL}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id), parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    global bot_locked, auto_restart_mode, recovery_enabled, live_logs_enabled

    # 🔴 চ্যানেল জয়েন চেক ডিজেবলড
    # if not await require_channel_join(update, context):
    #     return

    if bot_locked and not is_admin(user_id):
        await update.message.reply_text("🔒 **সিস্টেম লক করা আছে।**", parse_mode='Markdown')
        return

    # 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦 ᴛᴏɢɢʟᴇ 🔴
    if "📺 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:" in text:
        if "𝗢𝗡" in text:
            live_logs_enabled = True
            await animate(update, context, Loading.logs_on(), delay=0.5, final_text="📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: ᴇɴᴀʙʟᴇᴅ**")
        else:
            live_logs_enabled = False
            # সব লগ সেশন বন্ধ করুন
            for uid in list(user_log_sessions.keys()):
                log_streamer.unsubscribe(uid)
            await animate(update, context, Loading.logs_off(), delay=0.5, final_text="❌ **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦: 𝗗𝗜𝗦𝗔𝗕𝗟𝗘𝗗**")
        
        await update.message.reply_text("𝗠𝗘𝗡𝗨 𝗨𝗣𝗗𝗔𝗧𝗘𝗗 !¡", reply_markup=get_main_keyboard(user_id), parse_mode='Markdown')
        return

    # 𝗣𝗥𝗢𝗝𝗘𝗖𝗧 ɴᴀᴍɪɴɗ
    if user_id in user_upload_state and "path" in user_upload_state[user_id]:
        p_name = text.replace(" ", "_").replace("/", "_")
        state = user_upload_state[user_id]
        extract_path = os.path.join(BASE_DIR, p_name)
        
        try:
            # ʟᴏᴀᴅɪɴɗ ᴀɴɪᴍᴀᴛɪᴏɴ ꜰᴏʀ ᴇxᴛʀᴀᴄᴛɪɴɗ
            msg = await animate(update, context, Loading.executing(), delay=0.4)
            
            os.makedirs(extract_path, exist_ok=True)
            with zipfile.ZipFile(state["path"], 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            
            # ᴄʜᴇᴄᴋ ꜰᴏʀ ᴍᴀɪɴ.ᴘʏ ᴀɴᴅ ʀᴇǫᴜɪʀᴇᴍᴇɴᴛꜱ.ᴛxᴛ
            main_py = os.path.join(extract_path, "main.py")
            req_txt = os.path.join(extract_path, "requirements.txt")
            
            if not os.path.exists(main_py):
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ **ᴇʀʀᴏʀ: ᴍᴀɪɴ.ᴘʏ ɴᴏᴛ ꜰᴏᴜɴᴅ ɪɴ ᴢɪᴘ!**", parse_mode='Markdown')
                shutil.rmtree(extract_path)
                return
            
            # ɪɴꜱᴛᴀʟʟ ʀᴇǫᴜɪʀᴇᴍᴇɴᴛꜱ ɪꜰ ᴇxɪꜱᴛꜱ
            if os.path.exists(req_txt):
                for frame in Loading.installing():
                    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=frame)
                    await asyncio.sleep(1.0)
                
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_txt], check=True, capture_output=True, text=True, cwd=extract_path)
                except subprocess.CalledProcessError as e:
                    logger.error(f"ʀᴇǫᴜɪʀᴇᴍᴇɴᴛꜱ ɪɴꜱᴛᴀʟʟ ꜰᴀɪʟᴇᴅ: {e}")
                    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="⚠️ **ᴡᴀʀɴɪɴɗ: ꜱᴏᴍᴇ ʀᴇǫᴜɪʀᴇᴍᴇɴᴛꜱ ꜰᴀɪʟᴇᴅ ᴛᴏ ɪɴꜱᴛᴀʟʟ**", parse_mode='Markdown')
                    await asyncio.sleep(1)
            
            # ꜱᴀᴠᴇ 𝗣𝗥𝗢𝗝𝗘𝗖𝗧 ᴅᴀᴛᴀ
            project_owners[p_name] = {
                "u_id": user_id,
                "u_name": state["u_name"],
                "u_username": update.effective_user.username or "ɴᴏ_ᴜꜱᴇʀɴᴀᴍᴇ",
                "zip": state["path"],
                "original_name": state["original_name"],
                "path": extract_path
            }
            del user_upload_state[user_id]
            
            final_text = (
                f"✅ **𝗣𝗥𝗢𝗝𝗘𝗖𝗧 `{p_name}` ꜱᴀᴠᴇᴅ!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚀 **এখন '📮 𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥' এ গিয়ে রান করুন।**\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=final_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"ᴜᴘʟᴏᴀᴅ ᴇʀʀᴏʀ: {e}")
            await update.message.reply_text(f"❌ **ᴇʀʀᴏʀ:** `{str(e)}`", parse_mode='Markdown')
        return

    # ʙᴜᴛᴛᴏɴ ʜᴀɴᴅʟᴇʀꜱ
    if text == "🗳️ 𝗨𝗣𝗟𝗢𝗔𝗗 𝗠𝗔𝗡𝗔𝗚𝗘𝗥":
        await update.message.reply_text(
            "🗳️ **𝗨𝗣𝗟𝗢𝗔𝗗 𝗠𝗔𝗡𝗔𝗚𝗘𝗥**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📪 **ꜱᴇɴᴅ ʏᴏᴜʀ .ᴢɪᴘ ꜰɪʟᴇ ᴄᴏɴᴛᴀɪɴɪɴɗ:**\n"
            "• `ᴍᴀɪɴ.ᴘʏ` (ʏᴏᴜʀ ʙᴏᴛ ᴄᴏᴅᴇ)\n"
            "• `ʀᴇǫᴜɪʀᴇᴍᴇɴᴛꜱ.ᴛxᴛ` (ᴅᴇᴘᴇɴᴅᴇɴᴄɪᴇꜱ)\n"
            "━━━━━━━━━━━━━━━━━━━━━", parse_mode='Markdown')

    elif text == "📮 𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥":
        user_projects = [p for p, d in project_owners.items() if d["u_id"] == user_id]
        if not user_projects:
            await update.message.reply_text("📮 **𝗡𝗢 𝗣𝗥𝗢𝗝𝗘𝗖𝗧𝗦 𝗙𝗢𝗨𝗡𝗗**", parse_mode='Markdown')
            return
        keyboard = []
        for p in user_projects:
            status = "💚 𝗢𝗡𝗟𝗜𝗡𝗘" if (p in running_processes and running_processes[p].poll() is None) else "💔 𝗢𝗙𝗟𝗜𝗡𝗘"
            keyboard.append([InlineKeyboardButton(f"{status} | {p}", callback_data=f"manage_{p}")])
        
        await update.message.reply_text(
            "📮 **𝗠𝗬 𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥**\n"
            "━━━━━━━━━━━━━━━━━━━━━", 
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif text == "🗑️ 𝗗𝗘𝗟𝗘𝗧𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗥":
        user_projects = [p for p, d in project_owners.items() if d["u_id"] == user_id]
        if not user_projects:
            await update.message.reply_text("🗑️ **𝗡𝗢 𝗣𝗥𝗢𝗝𝗘𝗖𝗧𝗦**", parse_mode='Markdown')
            return
        keyboard = [[InlineKeyboardButton(f"🗑️ {p}", callback_data=f"del_{p}")] for p in user_projects]
        await update.message.reply_text("🗑️ **𝗦𝗘𝗟𝗘𝗖𝗧 𝗣𝗥𝗢𝗝𝗘𝗖𝗧 𝗧𝗢 𝗗𝗘𝗟𝗘𝗧𝗘:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # ᴀᴅᴍɪɴ ᴄ𝗢𝗡ᴛʀᴏʟꜱ ᴡɪᴛʜ ᴛᴏɢɢʟᴇ ʙᴜᴛᴛ𝗢𝗡ꜱ
    elif "🔄 𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧:" in text and is_admin(user_id):
        if "𝗢𝗡" in text:
            auto_restart_mode = True
            await animate(update, context, Loading.restarting(), delay=0.5, final_text="🔄 **𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧: 𝗔𝗖𝗧𝗜𝗩𝗔𝗧𝗘𝗗**")
        else:
            auto_restart_mode = False
            await animate(update, context, Loading.restarting(), delay=0.5, final_text="🔄 **𝗔𝗨𝗧𝗢 𝗥𝗘𝗦𝗧𝗔𝗥𝗧: 𝗗𝗘𝗔𝗖𝗧𝗜𝗩𝗔𝗧𝗘𝗗**")
        await update.message.reply_text("𝗠𝗘𝗡𝗨 𝗨𝗣𝗗𝗔𝗧𝗘𝗗 !¡", reply_markup=get_main_keyboard(user_id), parse_mode='Markdown')

    elif text in ["🔒 𝗟𝗢𝗖𝗞 𝗦𝗬𝗦𝗧𝗘𝗠", "🔓 𝗨𝗡𝗟𝗢𝗖𝗞 𝗦𝗬𝗦𝗧𝗘𝗠"] and is_admin(user_id):
        if "ʟᴏᴄᴋ" in text and "𝗨𝗡𝗟𝗢𝗖𝗞" not in text:
            bot_locked = True
            await animate(update, context, Loading.executing(), delay=0.3, final_text="🔒 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗟𝗢𝗖𝗞𝗘𝗗**")
        else:
            bot_locked = False
            await animate(update, context, Loading.executing(), delay=0.3, final_text="🔓 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗨𝗡𝗟𝗢𝗖𝗞𝗘𝗗**")
        await update.message.reply_text("𝗠𝗘𝗡𝗨 𝗨𝗣𝗗𝗔𝗧𝗘𝗗 !¡", reply_markup=get_main_keyboard(user_id), parse_mode='Markdown')
    
    elif "🛡️ 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:" in text and is_admin(user_id):
        if "𝗢𝗡" in text:
            recovery_enabled = True
            await animate(update, context, Loading.recovering(), delay=0.5, final_text="🛡️ **𝗔𝗨𝗧𝗢 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬: ᴇɴᴀʙʟᴇᴅ**")
        else:
            recovery_enabled = False
            await animate(update, context, Loading.recovering(), delay=0.5, final_text="🛡️ **𝗔𝗨𝗧𝗢 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬: 𝗗𝗜𝗦𝗔𝗕𝗟𝗘𝗗**")
        await update.message.reply_text("𝗠𝗘𝗡𝗨 𝗨𝗣𝗗𝗔𝗧𝗘𝗗 !¡", reply_markup=get_main_keyboard(user_id), parse_mode='Markdown')

    elif text == "🎬 𝗣𝗥𝗢𝗝𝗘𝗖𝗧 𝗙𝗜𝗟𝗘" and is_admin(user_id):
        # নতুন কোড - শুধু স্ট্যাটিস্টিক্স দেখাবে
        total_projects = len(project_owners)
        running_count = len([p for p in running_processes.values() if p.poll() is None])
        offline_count = total_projects - running_count
        
        status_text = (
            "🎬 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧 𝗦𝗧𝗔𝗧𝗨𝗦**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **𝗧𝗢𝗧𝗔𝗟 𝗣𝗥𝗢𝗝𝗘𝗖𝗧𝗦:** `{total_projects}`\n"
            f"💚 **𝗢𝗡𝗟𝗜𝗡𝗘:** `{running_count}`\n"
            f"💔 **𝗢𝗙𝗟𝗜𝗡𝗘:** `{offline_count}`\n"
            f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** `{'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}`\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')

    elif text == "🏩 𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛":
        # লোডিং অ্যানিমেশন দেখাও
        msg = await update.message.reply_text("🏩 **ᴄʜᴇᴄᴋɪɴɗ 𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛...**")
        
        try:
            health_data = await get_system_health()
            
            if health_data["status"] == "ok":
                # পূর্ণ সিস্টেম ইনফো
                msg_text = (
                    "🏩 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥️ **ᴄᴘᴜ:** {health_data['cpu']} ({health_data['cpu_cores']} ᴄᴏʀᴇꜱ)\n"
                    f"🧠 **ʀᴀᴍ:** {health_data['ram']} ({health_data['ram_used']}/{health_data['ram_total']})\n"
                    f"💾 **ᴅɪꜱᴋ:** {health_data['disk']} ({health_data['disk_used']}/{health_data['disk_total']})\n"
                    f"⏱️ **ᴜᴘᴛɪᴍᴇ:** {health_data['uptime']}\n"
                    f"📮 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧ꜱ:** {len(project_owners)}\n"
                    f"💚 **𝗥𝗨𝗡𝗡𝗜𝗡𝗗:** {len([p for p in running_processes.values() if p.poll() is None])}\n"
                    f"🛡️ **𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:** {'𝗢𝗡' if recovery_enabled else '𝗢𝗙𝗙'}\n"
                    f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "✅ **𝗦𝗬𝗦𝗧𝗘𝗠 ɪꜱ ʜᴇᴀʟᴛʜʏ**"
                )
            elif health_data["status"] == "basic":
                # বেসিক ইনফো (psutil না থাকলে)
                msg_text = (
                    "🏩 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛** (ʙᴀꜱɪᴄ)\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🖥️ **ᴘʟᴀᴛꜰᴏʀᴍ:** {health_data['platform']}\n"
                    f"⚙️ **ᴍᴀᴄʜɪɴᴇ:** {health_data['machine']}\n"
                    f"🔧 **ᴘʀᴏᴄᴇꜱꜱᴏʀ:** {health_data['processor']}\n"
                    f"🐍 **ᴘʏᴛʜᴏɴ:** {health_data['python_version']}\n"
                    f"📮 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧ꜱ:** {len(project_owners)}\n"
                    f"💚 **𝗥𝗨𝗡𝗡𝗜𝗡𝗗:** {len([p for p in running_processes.values() if p.poll() is None])}\n"
                    f"🛡️ **𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:** {'𝗢𝗡' if recovery_enabled else '𝗢𝗙𝗙'}\n"
                    f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ **ɪɴꜱᴛᴀʟʟ `psutil` ꜰᴏʀ ᴅᴇᴛᴀɪʟᴇᴅ ꜱᴛᴀᴛꜱ**"
                )
            else:
                # এরর
                msg_text = (
                    "🏩 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    "💞 ʜɪ ᴇᴠᴇʀʏᴏɴᴇ ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ🔸ʀɪʏᴀᴅ-ʜᴏsᴛɪɴɢ ʙᴏᴛ ᴀʟʟ ꜱᴇʀᴠᴇʀ 💞\n\n"
                    "ꜰʀᴇᴇ ꜰɪʀᴇ\n\n"
                    f"📮 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧𝗦:** {len(project_owners)}\n"
                    f"💚 **𝗥𝗨𝗡𝗡𝗜𝗡𝗗:** {len([p for p in running_processes.values() if p.poll() is None])}\n"
                    f"🛡️ **𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:** {'𝗢𝗡' if recovery_enabled else '𝗢𝗙𝗙'}\n"
                    f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}"
                )
            
            await msg.edit_text(msg_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛 ᴇʀʀᴏʀ: {e}")
            await msg.edit_text(
                "🏩 **𝗦𝗬𝗦𝗧𝗘𝗠 𝗛𝗘𝗔𝗟𝗧𝗛**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "💞 **ᴜɴᴀʙʟᴇ ᴛᴏ ꜰᴇᴛᴄʜ ꜱʏꜱᴛᴇᴍ ɪɴꜰᴏ**\n"
                f"📮 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧𝗦:** {len(project_owners)}\n"
                f"💚 **𝗥𝗨𝗡𝗡𝗜𝗡𝗗:** {len([p for p in running_processes.values() if p.poll() is None])}\n"
                f"🛡️ **𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:** {'𝗢𝗡' if recovery_enabled else '𝗢𝗙𝗙'}\n"
                f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}",
                parse_mode='Markdown'
            )

    elif text == "🌎 𝗦𝗘𝗥𝗩𝗘𝗥 𝗜𝗡𝗙𝗢":
        await update.message.reply_text(
            "🌎 **𝗦𝗘𝗥𝗩𝗘𝗥 𝗜𝗡𝗙𝗢**\n"
            f"🚀 **ᴘᴏʀᴛ:** {PORT}\n"
            f"🛡️ **ᴘʟᴀᴛꜰᴏʀᴍ:** {os.environ.get('PLATFORM', 'ᴜɴᴋɴᴏᴡɴ')}\n"
            f"🔄 **𝗔𝗨𝗧𝗢-𝗥𝗘𝗦𝗧𝗔𝗥𝗧:** {'𝗢𝗡' if auto_restart_mode else '𝗢𝗙𝗙'}\n"
            f"🛡️ **𝗔𝗨𝗧𝗢-𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬:** {'𝗢𝗡' if recovery_enabled else '𝗢𝗙𝗙'}\n"
            f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗢𝗡' if live_logs_enabled else '𝗢𝗙𝗙'}\n"
            f"📢 **ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟ:** {'Not Set' if not REQUIRED_CHANNEL else REQUIRED_CHANNEL}",
            parse_mode='Markdown'
        )

    elif text == "📠 𝗖𝗢𝗡𝗧𝗔𝗖𝗧 𝗔𝗗𝗠𝗜𝗡":
        # ইনলাইন কীবোর্ড বাটন - স্ক্রিনশটের মতো
        contact_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📠  ᴄʟɪᴄᴋ ʜᴀʀᴇ", url=f"tg://user?id={PRIMARY_ADMIN_ID}")]
        ])
        
        await update.message.reply_text(
            f"{ADMIN_DISPLAY_NAME}\n"
            f"📠 𝙲𝙾𝙽𝚃𝙰𝙲𝚃 𝙾𝚆𝙽𝙴𝚁",
            reply_markup=contact_keyboard,
            parse_mode='Markdown'
        )

# --- [ᴅᴏᴄᴜᴍᴇɴᴛ ʜᴀɴᴅʟɪɴɗ - ডিজেবলড চ্যানেল চেক] ---
async def handle_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🔴 চ্যানেল জয়েন চেক ডিজেবলড
    # if not await require_channel_join(update, context):
    #     return
    
    if bot_locked and not is_admin(user_id):
        return
    
    doc = update.message.document
    if not doc.file_name.endswith('.zip'):
        await update.message.reply_text("❌ **ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ .ᴢɪᴘ ꜰɪʟᴇ ᴏɴʟʏ!**", parse_mode='Markdown')
        return
    
    # ᴜᴘʟᴏᴀᴅ ʟᴏᴀᴅɪɴɗ ᴀɴɪᴍᴀᴛɪᴏɴ
    msg = await update.message.reply_text(Loading.uploading()[0])
    for frame in Loading.uploading()[1:]:
        await asyncio.sleep(0.8)
        try:
            msg = await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=frame)
        except:
            pass
    
    temp_dir = os.path.join(BASE_DIR, f"tmp_{user_id}")
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, doc.file_name)
    
    try:
        file = await doc.get_file()
        await file.download_to_drive(zip_path)
        
        user_upload_state[user_id] = {
            "path": zip_path,
            "u_name": update.effective_user.full_name,
            "original_name": doc.file_name
        }
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            text="🖋️ **ɴᴀᴍᴇ ʏᴏᴜʀ 𝗣𝗥𝗢𝗝𝗘𝗖𝗧**\n━━━━━━━━━━━━━━━━━━━━━\n💬 **একটি নাম লিখে পাঠান (ꜱᴘᴀᴄᴇ ᴀʟʟᴏᴡᴇᴅ):**",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"ᴅᴏᴡɴʟᴏᴀᴅ ᴇʀʀᴏʀ: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ **ᴅᴏᴡɴʟᴏᴀᴅ ꜰᴀɪʟᴇᴅ!**", parse_mode='Markdown')
# --- [ᴄᴀʟʟʙᴀᴄᴋꜱ - ডিজেবলড চ্যানেল চেক] ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    action, p_name = data[0], "_".join(data[1:])
    user_id = update.effective_user.id

    # 🔴 চ্যানেল চেক কলব্যাক ডিজেবলড
    # if action == "check":
    #     is_member = await check_channel_membership(user_id, context)
    #     if is_member:
    #         await query.edit_message_text("✅ **চ্যানেল চেক সম্পন্ন! এখন বট ব্যবহার করতে পারেন।**", parse_mode='Markdown')
    #         await start(update, context)
    #     else:
    #         await query.answer("❌ আপনি এখনো চ্যানেলে জয়েন করেননি!", show_alert=True)
    #     return

    if action == "run":
        if p_name in running_processes and running_processes[p_name].poll() is None:
            await query.edit_message_text(f"⚠️ **`{p_name}` 𝗜𝗦 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗥𝗨𝗡𝗡𝗜𝗡𝗗**", parse_mode='Markdown')
            return
            
        folder = os.path.join(BASE_DIR, p_name)
        main_file = os.path.join(folder, "main.py")
        
        if os.path.exists(main_file):
            try:
                # ʀᴜɴ ʟᴏᴀᴅɪɴɗ ᴀɴɪᴍᴀᴛɪᴏɴ
                msg = await query.edit_message_text(Loading.executing()[0])
                for frame in Loading.executing()[1:]:
                    await asyncio.sleep(0.4)
                    try:
                        msg = await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=frame)
                    except:
                        pass
                
                # ʀᴜɴ ᴘʀᴏᴄᴇꜱꜱ
                proc = subprocess.Popen(
                    [sys.executable, "-u", main_file],
                    cwd=folder,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1  # লাইন বাই লাইন বাফারিং
                )
                running_processes[p_name] = proc
                
                # 🔴 লগ স্ট্রিমিং শুরু করুন
                if live_logs_enabled:
                    log_streamer.start_stream(p_name, proc)
                
                # ᴀᴜᴛᴏ-ʀᴇꜱᴛᴀʀᴛ ᴍᴏɴɪᴛᴏʀ
                if auto_restart_mode:
                    asyncio.create_task(monitor_process(p_name, folder))
                
                # লগ দেখার বাটন যোগ করুন
                keyboard = [
                    [
                        InlineKeyboardButton("▶️ 𝗥𝗨𝗡", callback_data=f"run_{p_name}"),
                        InlineKeyboardButton("🛑 𝗦𝗧𝗢𝗣", callback_data=f"stop_{p_name}")
                    ],
                    [
                        InlineKeyboardButton("📺 𝗩𝗜𝗘𝗪 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦", callback_data=f"viewlogs_{p_name}")
                    ],
                    [
                        InlineKeyboardButton("🗑️ 𝗗𝗘𝗟𝗘𝗧𝗘", callback_data=f"del_{p_name}")
                    ]
                ]
                
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=msg.message_id,
                    text=f"🚀 **`{p_name}` 𝗜𝗦 𝗡𝗢𝗪 𝗢𝗡𝗟𝗜𝗡𝗘! 💚**\n\n📺 লাইভ লগস দেখতে **View Live Logs** বাটনে ক্লিক করুন।",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except Exception as e:
                await query.edit_message_text(f"❌ **𝗙𝗔𝗜𝗟𝗘𝗗 𝗧𝗢 𝗦𝗧𝗔𝗥𝗧:** `{str(e)}`", parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ **𝗠𝗔𝗜𝗡.𝗣𝗬 𝗡𝗢𝗧 𝗙𝗢𝗨𝗡𝗗**", parse_mode='Markdown')
    
    elif action == "stop":
        if p_name in running_processes:
            # ʀᴇᴠᴇʀꜱᴇ ᴀɴɪᴍᴀᴛɪᴏɴ ꜰᴏʀ 𝗦𝗧𝗢𝗣
            msg = await query.edit_message_text("🛑 ꜱᴛᴏᴘᴘɪɴɗ: [▰▰▰▰▰▰▰▰▰▰] 100%")
            await asyncio.sleep(0.3)
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="🛑 ꜱᴛᴏᴘᴘɪɴɗ: [▰▰▰▰▰▰▰▰▱▱] 80%")
            await asyncio.sleep(0.3)
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="🛑 ꜱᴛᴏᴘᴘɪɴɗ: [▰▰▰▰▰▰▰▱▱▱] 60%")
            await asyncio.sleep(0.3)
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="🛑 ꜱᴛᴏᴘᴘɪɴɗ: [▰▰▰▰▰▰▱▱▱▱] 40%")
            await asyncio.sleep(0.3)
            
            try:
                # 🔴 লগ স্ট্রিমিং বন্ধ করুন
                log_streamer.stop_stream(p_name)
                
                running_processes[p_name].terminate()
                running_processes[p_name].wait(timeout=5)
            except:
                running_processes[p_name].kill()
            del running_processes[p_name]
            
            # ইউজারদের লগ সেশন বন্ধ করুন
            for uid, session in list(user_log_sessions.items()):
                if session["project"] == p_name:
                    session["active"] = False
            
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=f"🛑 **`{p_name}` 𝗜𝗦 𝗡𝗢𝗪 𝗢𝗙𝗟𝗜𝗡𝗘! 💔**", parse_mode='Markdown')
        else:
            await query.edit_message_text(f"⚠️ **`{p_name}` 𝗪𝗔𝗦 𝗡𝗢𝗧 𝗥𝗨𝗡𝗡𝗜𝗡𝗗**", parse_mode='Markdown')
    
    # 🔴 লাইভ লগস দেখার কলব্যাক
    elif action == "viewlogs":
        if not live_logs_enabled:
            await query.answer("❌ লাইভ লগস বর্তমানে অফ আছে!", show_alert=True)
            return
        
        if p_name not in running_processes or running_processes[p_name].poll() is not None:
            await query.answer("❌ এই প্রজেক্ট বর্তমানে রানিং নেই!", show_alert=True)
            return
        
        # লগ ভিউয়ার মেসেজ পাঠান
        log_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📺 **𝗜𝗡𝗜𝗧𝗜𝗔𝗟𝗜𝗭𝗜𝗡𝗗 𝗟𝗜𝗩𝗘 𝗖𝗢𝗡𝗦𝗢𝗟𝗘...**",
            parse_mode='Markdown'
        )
        
        # সাবস্ক্রাইব করুন
        success = log_streamer.subscribe(p_name, user_id, update.effective_chat.id, log_msg.message_id)
        
        if success:
            await query.answer("✅ লাইভ লগস শুরু হয়েছে!", show_alert=True)
        else:
            await log_msg.edit_text("❌ **লগ স্ট্রিম শুরু করতে ব্যর্থ!**", parse_mode='Markdown')
    
    elif action == "del":
        # 𝗗𝗘𝗟𝗘𝗧𝗘 ʟᴏᴀᴅɪɴɗ ᴀɴɪᴍᴀᴛɪᴏɴ
        msg = await query.edit_message_text(Loading.deleting()[0])
        for frame in Loading.deleting()[1:]:
            await asyncio.sleep(0.5)
            try:
                msg = await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=frame)
            except:
                pass
        
        # 𝗦𝗧𝗢𝗣 ɪꜰ 𝗥𝗨𝗡ɴɪɴɗ
        if p_name in running_processes:
            try:
                # 🔴 লগ স্ট্রিমিং বন্ধ করুন
                log_streamer.stop_stream(p_name)
                
                running_processes[p_name].terminate()
                running_processes[p_name].wait(timeout=5)
            except:
                pass
            del running_processes[p_name]
        
        # ইউজারদের লগ সেশন বন্ধ করুন
        for uid, session in list(user_log_sessions.items()):
            if session["project"] == p_name:
                session["active"] = False
        
        path = os.path.join(BASE_DIR, p_name)
        if os.path.exists(path):
            shutil.rmtree(path)
        if p_name in project_owners:
            del project_owners[p_name]
        
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=f"🗑️ **`{p_name}` 𝗗𝗘𝗟𝗘𝗧𝗘𝗗!**", parse_mode='Markdown')

    elif action == "manage":
        status = "💚 𝗢𝗡𝗟𝗜𝗡𝗘" if (p_name in running_processes and running_processes[p_name].poll() is None) else "💔 𝗢𝗙𝗟𝗜𝗡𝗘"
        
        # 🔴 লাইভ লগস বাটন যোগ করুন
        keyboard = [
            [
                InlineKeyboardButton("▶️ 𝗥𝗨𝗡", callback_data=f"run_{p_name}"),
                InlineKeyboardButton("🛑 𝗦𝗧𝗢𝗣", callback_data=f"stop_{p_name}")
            ],
            [
                InlineKeyboardButton("📺 𝗩𝗜𝗘𝗪 𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦", callback_data=f"viewlogs_{p_name}")
            ],
            [
                InlineKeyboardButton("🗑️ 𝗗𝗘𝗟𝗘𝗧𝗘", callback_data=f"del_{p_name}")
            ]
        ]
        
        await query.edit_message_text(
            f"📦 **𝗣𝗥𝗢𝗝𝗘𝗖𝗧:** `{p_name}`\n"
            f"📡 **𝗦𝗧𝗔𝗧𝗨𝗦:** {status}\n"
            f"📺 **𝗟𝗜𝗩𝗘 𝗟𝗢𝗚𝗦:** {'𝗔𝗩𝗔𝗜𝗟𝗘𝗕𝗟𝗘' if live_logs_enabled else '𝗗𝗜𝗦𝗔𝗕𝗟𝗘𝗗'}", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def monitor_process(p_name, folder):
    """ᴀᴜᴛᴏ-ʀᴇꜱᴛᴀʀᴛ ᴍᴏɴɪᴛᴏʀ"""
    while auto_restart_mode and p_name in running_processes:
        proc = running_processes.get(p_name)
        if proc and proc.poll() is not None:
            await asyncio.sleep(2)
            main_file = os.path.join(folder, "main.py")
            if os.path.exists(main_file):
                new_proc = subprocess.Popen(
                    [sys.executable, "-u", main_file],
                    cwd=folder,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                running_processes[p_name] = new_proc
                
                # 🔴 নতুন প্রসেসের জন্য লগ স্ট্রিমিং শুরু করুন
                if live_logs_enabled:
                    log_streamer.stop_stream(p_name)
                    log_streamer.start_stream(p_name, new_proc)
                
                logger.info(f"𝗔𝗨𝗧𝗢-𝗥𝗘𝗦𝗧𝗔𝗥𝗧𝗘𝗗 {p_name}")
        await asyncio.sleep(5)

# --- [𝗔𝗨𝗧𝗢 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬 ꜱʏꜱᴛᴇᴍ] ---
class BotRecovery:
    def __init__(self):
        self.running = True
        self.restart_count = 0
        self.max_restarts = 100  # ɪɴꜰɪɴɪᴛᴇ ʟᴏᴏᴘ ᴇꜱꜱᴇɴᴛɪᴀʟʟʏ
        self.crash_log = []
    
    async def start_recovery_monitor(self, application):
        """ᴍᴀɪɴ ʀᴇᴄᴏᴠᴇʀʏ ʟᴏᴏᴘ"""
        while self.running and recovery_enabled:
            try:
                # ᴄʜᴇᴄᴋ ɪꜰ ʙᴏᴛ ɪꜱ ʀᴇꜱᴘᴏɴᴅɪɴɗ
                await self.check_bot_health(application)
                
                # ʀᴇᴄᴏᴠᴇʀ ᴀɴʏ ᴄʀᴀꜱʜᴇᴅ 𝗣𝗥𝗢𝗝𝗘𝗖𝗧ꜱ
                await self.recover_projects()
                
                await asyncio.sleep(10)  # ᴄʜᴇᴄᴋ ᴇᴠᴇʀʏ 10 ꜱᴇᴄᴏɴᴅꜱ
                
            except Exception as e:
                logger.error(f"𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗬 𝗘𝗥𝗥𝗢𝗥: {e}")
                self.crash_log.append({"time": time.time(), "error": str(e)})
                await asyncio.sleep(5)
    
    async def check_bot_health(self, application):
        """ᴄʜᴇᴄᴋ ɪꜰ ʙᴏᴛ ɪꜱ ʀᴜɴɴɪɴɗ ᴄᴏʀʀᴇᴄᴛʟʏ"""
        try:
            # ᴛʀʏ ᴛᴏ ɢᴇᴛ ʙᴏᴛ ɪɴꜰᴏ - ɪꜰ ᴛʜɪꜱ ꜰᴀɪʟꜱ, ʙᴏᴛ ɪꜱ ᴅᴏᴡɴ
            await application.bot.get_me()
        except Exception as e:
            logger.critical(f"𝗕𝗢𝗧 𝗛𝗘𝗔𝗟𝗧𝗛 𝗖𝗛𝗘𝗖𝗞 𝗙𝗔𝗜𝗟𝗘𝗗: {e}")
            await self.emergency_restart(application)
    
    async def recover_projects(self):
        """ᴀᴜᴛᴏ-ʀᴇꜱᴛᴀʀᴛ ᴄʀᴀꜱʜᴇᴅ 𝗣𝗥𝗢𝗝𝗘𝗖𝗧ꜱ"""
        for p_name, proc in list(running_processes.items()):
            if proc.poll() is not None:  # ᴘʀᴏᴄᴇꜱꜱ ᴄʀᴀꜱʜᴇᴅ
                if recovery_enabled and p_name in project_owners:
                    logger.info(f"𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗜𝗡𝗗 𝗖𝗥𝗔𝗦𝗛𝗘𝗗 𝗣𝗥𝗢𝗝𝗘𝗖𝗧: {p_name}")
                    folder = project_owners[p_name]["path"]
                    main_file = os.path.join(folder, "main.py")
                    
                    if os.path.exists(main_file):
                        try:
                            # 🔴 আগের লগ স্ট্রিম বন্ধ করুন
                            log_streamer.stop_stream(p_name)
                            
                            new_proc = subprocess.Popen(
                                [sys.executable, "-u", main_file],
                                cwd=folder,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                bufsize=1
                            )
                            running_processes[p_name] = new_proc
                            
                            # 🔴 নতুন লগ স্ট্রিম শুরু করুন
                            if live_logs_enabled:
                                log_streamer.start_stream(p_name, new_proc)
                            
                            logger.info(f"𝗣𝗥𝗢𝗝𝗘𝗖𝗧 {p_name} 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗘𝗗")
                        except Exception as e:
                            logger.error(f"𝗙𝗔𝗜𝗟𝗘𝗗 𝗧𝗢 𝗥𝗘𝗖𝗢𝗩𝗘𝗥𝗘𝗗 {p_name}: {e}")
    
    async def emergency_restart(self, application):
        """𝗘𝗠𝗘𝗥𝗚𝗘𝗡𝗖𝗬 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 ᴡʜᴇɴ ʙᴏᴛ ᴄʀᴀꜱʜᴇꜱ"""
        if self.restart_count < self.max_restarts:
            self.restart_count += 1
            logger.critical(f"𝗘𝗠𝗘𝗥𝗚𝗘𝗡𝗖𝗬 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 #{self.restart_count}")
            
            # ᴡᴀɪᴛ ᴀ ʙɪᴛ ʙᴇꜰᴏʀᴇ ʀᴇꜱᴛᴀʀᴛɪɴɗ
            await asyncio.sleep(5)
            
            try:
                # ꜱᴛᴏᴘ ᴄᴜʀʀᴇɴᴛ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ
                await application.stop()
                await asyncio.sleep(2)
                
                # ʀᴇꜱᴛᴀʀᴛ
                await application.start()
                await application.updater.start_polling(drop_pending_updates=True)
                
                logger.info("𝗘𝗠𝗘𝗥𝗚𝗘𝗡𝗖𝗬 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 𝗦𝗨𝗖𝗖𝗘𝗦𝗦𝗙𝗨𝗟")
                
            except Exception as e:
                logger.critical(f"𝗘𝗠𝗘𝗥𝗚𝗘𝗡𝗖𝗬 𝗥𝗘𝗦𝗧𝗔𝗥𝗧 𝗙𝗔𝗜𝗟𝗘𝗗: {e}")
    
    def stop(self):
        self.running = False

recovery_system = BotRecovery()

# ꜱɪɢɴᴀʟ ʜᴀɴᴅʟᴇʀ ꜰᴏʀ ɢʀᴀᴄᴇꜰᴜʟ ꜱʜᴜᴛᴅᴏᴡɴ
def signal_handler(signum, frame):
    logger.info("ꜱʜᴜᴛᴅᴏᴡɴ ꜱɪɢɴᴀʟ ʀᴇᴄᴇɪᴠᴇᴅ, ꜱᴛᴏᴘᴘɪɴɗ ʀᴇᴄᴏᴠᴇʀʏ...")
    recovery_system.stop()
    # 🔴 সব লগ স্ট্রিম বন্ধ করুন
    for p_name in list(log_streamer.active_streams.keys()):
        log_streamer.stop_stream(p_name)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- [ᴍᴀɪɴ] ---
def main():
    # ꜱᴛᴀʀᴛ ᴡᴇʙ ꜱᴇʀᴠᴇʀ ɪɴ ᴛʜʀᴇᴀᴅ
    web_thread = Thread(target=run_web, daemon=True)
    web_thread.start()
    
    # ꜱᴛᴀʀᴛ ʙᴏᴛ
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ZIP, handle_docs))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("ʙᴏᴛ ꜱᴛᴀʀᴛᴇᴅ!")
    
    # 🔴 লগ ভিউয়ার ব্যাকগ্রাউন্ড টাস্ক শুরু করুন - asyncio.create_task() দিয়ে
    async def post_init(app):
        # লগ ভিউয়ার task
        asyncio.create_task(log_viewer_task(app))
        # রিকভারি সিস্টেম
        asyncio.create_task(recovery_system.start_recovery_monitor(app))
    
    application.post_init = post_init
    
    # ᴜꜱᴇ ᴡᴇʙʜᴏᴏᴋ ɪꜰ ᴡᴇʙʜᴏᴏᴋ_ᴜʀʟ ɪꜱ ꜱᴇᴛ, ᴇʟꜱᴇ ᴘᴏʟʟɪɴɗ
    webhook_url = os.environ.get('WEBHOOK_URL')
    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=webhook_url
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
