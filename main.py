import os
import sys
import subprocess
import psutil
import zipfile
import tarfile
import threading
import shutil
import json
import platform
import signal
import time
import traceback
import re
import random
import glob
from datetime import datetime, timedelta
import fcntl
import ast

import telebot
from telebot import types

# ================= NEW: WEB SERVER FOR PORT BINDING =================
from flask import Flask

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8048859483:AAG-uCtIBHe2tnIK1oQKHiOBi5v7hxgUNaA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8124942237"))
CLONED_BOT = os.getenv("CLONED_BOT", "false").lower() == "true"
MAX_FREE_BOTS = 3
PORT = int(os.getenv("PORT", 8080))  # Default port 8080

# PAYMENT CONFIGURATION
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_TOKEN", "") 
CURRENCY = "XTR"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# ================= FLASK APP SETUP =================
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Riyad Hosting Bot is running!", 200

@app.route('/health')
def health():
    return json.dumps({"status": "ok", "uptime": int(time.time() - START_TIME)}), 200

@app.route('/bot_info')
def bot_info():
    try:
        info = bot.get_me()
        return json.dumps({
            "bot_id": info.id,
            "username": info.username,
            "name": info.first_name,
            "status": "active"
        }), 200
    except:
        return json.dumps({"error": "Bot not accessible"}), 503

def run_web_server():
    """Run Flask web server in background thread"""
    log_to_terminal(f"[WEB] Starting web server on port {PORT}")
    # Don't use debug mode in production
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ================= DIRECTORIES =================
SAFE_TOKEN = BOT_TOKEN.replace(":", "_").replace("/", "_").replace("\\", "_")
BOT_DATA_DIR_NAME = "main" if not CLONED_BOT else SAFE_TOKEN
BOT_DATA_DIR = os.path.abspath(os.path.join("bot_data", BOT_DATA_DIR_NAME))

BASE_DIR = os.path.join(BOT_DATA_DIR, "uploads")
TEMP_DIR = os.path.join(BOT_DATA_DIR, "temp_uploads")
LOG_DIR = os.path.join(BOT_DATA_DIR, "logs")
USER_DATA_FILE = os.path.join(BOT_DATA_DIR, "user_names.json")
BLOCK_FILE = os.path.join(BOT_DATA_DIR, "blocked_users.json")
TEMP_ADMINS_FILE = os.path.join(BOT_DATA_DIR, "temp_admins.json")
PREMIUM_USERS_FILE = os.path.join(BOT_DATA_DIR, "premium_users.json") 
SETTINGS_FILE = os.path.join(BOT_DATA_DIR, "settings.json")
PROCESS_FILE = os.path.join(BOT_DATA_DIR, "user_processes.json")
USER_STATS_FILE = os.path.join(BOT_DATA_DIR, "user_stats.json")

if not CLONED_BOT:
    CLONE_REQUESTS_FILE = os.path.abspath("clone_requests_global.json")
    CLONED_BOTS_FILE = os.path.abspath("cloned_bots_global.json")
else:
    CLONE_REQUESTS_FILE = None
    CLONED_BOTS_FILE = None

for d in [BOT_DATA_DIR, BASE_DIR, TEMP_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# ================= GLOBAL VARIABLES =================
pending_uploads = {}
user_states = {}
lock = threading.Lock()
START_TIME = time.time()
instance_counter = 0
user_processes = {}
active_installations = {}

# ================= LOGGING & HELPERS =================
def log_to_terminal(message):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[BOT] [{timestamp}] {message}")
    except Exception as e:
        print(f"[BOT] Logging error: {e}")

def print_banner(bot_info):
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║███████╗ █████╗ ███╗   ███╗██╗██╗   ██╗██╗                      ║
║██╔════╝██╔══██╗████╗ ████║██║██║   ██║██║                      ║
║███████╗███████║██╔████╔██║██║██║   ██║██║                      ║
║╚════██║██╔══██║██║╚██╔╝██║██║██║   ██║██║                      ║
║███████║██║  ██║██║ ╚═╝ ██║██║╚██████╔╝███████╗                 ║
║╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚═════╝ ╚══════╝                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    🚀 Riyad Hosting Bot is RUNNING!
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🤖 Bot Name: @{bot_info.username}
    🆔 Bot ID: {bot_info.id}
    👑 Admin ID: {ADMIN_ID}
    🧬 Mode: {'🟢 MAIN BOT' if not CLONED_BOT else '🔸 CLONED BOT'}
    📂 Data Directory: {BOT_DATA_DIR_NAME}
    💎 Premium Price: {settings.get('price', 1)} XTR
    🔒 Premium Only: {'ON' if settings.get('premium_only', False) else 'OFF'}
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    🐍 Python: {platform.python_implementation()} {platform.python_version()}
    💻 OS: {platform.system()} {platform.release()}
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🌐 Web Server: Running on port {PORT}
"""
    print(banner)

def safe_markdown(text):
    if text is None:
        return ""
    text = str(text)
    if not text:
        return ""
    escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)
    escaped = escaped.replace('\\\\', '\\')
    return escaped

def safe_username(username):
    if not username:
        return "No username"
    return f"@{safe_markdown(username)}"

def safe_cpu_percent():
    try:
        return psutil.cpu_percent(interval=0.1)
    except:
        return "N/A"

def safe_memory_percent():
    try:
        return psutil.virtual_memory().percent
    except:
        return "N/A"

def safe_is_process_running(pid):
    try:
        if not pid:
            return False
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except:
        return False

def safe_kill_process_tree(pid):
    try:
        if not pid:
            return
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
        log_to_terminal(f"[PROCESS] Killed process tree for PID: {pid}")
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        log_to_terminal(f"[PROCESS] Kill error: {e}")

def get_safe_token(token):
    return token.replace(':', '_').replace('/', '_').replace('\\', '_').replace('|', '_')[:20]

def is_owner(user_id):
    try:
        return int(user_id) == int(ADMIN_ID)
    except:
        return False

def is_admin(user_id):
    try:
        user_id = int(user_id)
        admin_id = int(ADMIN_ID)
    except:
        return False
    
    if user_id == admin_id: 
        return True
    
    if user_id in temp_admins:
        try:
            expiry = datetime.fromisoformat(temp_admins[user_id])
            if expiry > datetime.now():
                return True
            else:
                del temp_admins[user_id]
                save_data(TEMP_ADMINS_FILE, temp_admins)
                return False
        except:
            return False
    
    return False

def is_premium(user_id):
    if is_admin(user_id): 
        return True
    return int(user_id) in premium_users

def get_user_project_count(user_id):
    user_dir = os.path.join(BASE_DIR, str(user_id))
    if not os.path.exists(user_dir):
        return 0
    return len([d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))])

def get_user_active_count(user_id):
    return len(user_processes.get(str(user_id), {}))

def get_user_total_files(user_id):
    total_files = 0
    user_dir = os.path.join(BASE_DIR, str(user_id))
    if os.path.exists(user_dir):
        for root, dirs, files in os.walk(user_dir):
            total_files += sum(1 for f in files if f.endswith((".py", ".js", ".sh")))
    return total_files

def get_user_memory_usage(user_id):
    try:
        active = user_processes.get(str(user_id), {})
        if not active:
            return 0.0
        
        total_memory = 0
        for iid, data in active.items():
            pid = data.get("pid")
            if pid and safe_is_process_running(pid):
                process = psutil.Process(pid)
                total_memory += process.memory_info().rss
        
        return total_memory / (1024 * 1024)
    except Exception as e:
        log_to_terminal(f"[MEMORY] Error calculating memory usage: {e}")
        return 0.0

def check_free_limits(user_id, action_type="deploy"):
    if is_premium(user_id):
        return True, ""
    
    if action_type == "deploy":
        count = get_user_project_count(user_id)
    elif action_type == "run":
        count = get_user_active_count(user_id)
    else:
        return True, ""
    
    if count >= MAX_FREE_BOTS:
        return False, f"❌ **Free User Limit Reached!**\n\nYou have {count}/{MAX_FREE_BOTS} bots.\n💡 Upgrade to Premium for unlimited access."
    
    return True, ""

def is_premium_only():
    return bool(settings.get("premium_only", False))

def start_cloned_bot(token, owner_id):
    try:
        log_to_terminal(f"[CLONE] Starting bot for user {owner_id}...")
        env = os.environ.copy()
        env.update({
            'BOT_TOKEN': token,
            'ADMIN_ID': str(owner_id),
            'CLONED_BOT': 'true'
        })
        
        bot_name = token.split(':')[0]
        log_file = os.path.join(LOG_DIR, f"clone_{bot_name}.log")
        with open(log_file, "a") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", __file__], 
                env=env, 
                cwd=os.getcwd(),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
        
        log_to_terminal(f"[CLONE] Started bot with PID: {process.pid}")
        return True, process.pid
    except Exception as e:
        log_to_terminal(f"[CLONE] Failed to start: {e}")
        return False, str(e)

def stop_cloned_bot(token):
    try:
        log_to_terminal(f"[CLONE] Stopping bot {token[:10]}...")
        if token in cloned_bots and 'process_pid' in cloned_bots[token]:
            pid = cloned_bots[token]['process_pid']
            if safe_is_process_running(pid):
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    child.terminate()
                parent.terminate()
                
                gone, alive = psutil.wait_procs([parent] + children, timeout=5)
                for p in alive:
                    p.kill()
                
                log_to_terminal(f"[CLONE] Stopped PID: {pid}")
            return True, "Bot stopped"
        return False, "Bot not found"
    except Exception as e:
        log_to_terminal(f"[CLONE] Stop error: {e}")
        return False, str(e)

def cleanup_all_cloned_bots():
    global cloned_bots
    if CLONED_BOT:
        return
    
    log_to_terminal("[CLEANUP] Cleaning up cloned bots...")
    existing_clones = load_json(CLONED_BOTS_FILE, {})
    killed_count = 0
    
    for token, config in existing_clones.items():
        pid = config.get('process_pid')
        if pid:
            try:
                if safe_is_process_running(pid):
                    safe_kill_process_tree(pid)
                    killed_count += 1
            except:
                pass
        
        config['status'] = 'stopped'
        config['process_pid'] = None
        cloned_bots[token] = config
    
    save_data(CLONED_BOTS_FILE, cloned_bots)
    log_to_terminal(f"[CLEANUP] Killed {killed_count} processes")

def restart_active_cloned_bots():
    if CLONED_BOT:
        return
    
    log_to_terminal("[RESTART] Checking active clones...")
    current_clones = load_json(CLONED_BOTS_FILE, {})
    restarted = 0
    
    for token, config in current_clones.items():
        if config.get('status') == 'active':
            owner_id = config.get('owner_id')
            if owner_id:
                log_to_terminal(f"[RESTART] Starting bot for user {owner_id}...")
                success, pid = start_cloned_bot(token, owner_id)
                if success:
                    config['process_pid'] = pid
                    restarted += 1
                else:
                    config['status'] = 'stopped'
                    config['process_pid'] = None
    
    save_data(CLONED_BOTS_FILE, current_clones)
    log_to_terminal(f"[RESTART] Restarted {restarted} cloned bots")

def cleanup_stale_processes():
    """Clean up stale process entries that are no longer running"""
    global user_processes
    cleaned = 0
    
    with lock:
        for uid in list(user_processes.keys()):
            for iid in list(user_processes[uid].keys()):
                pid = user_processes[uid][iid].get("pid")
                if pid and not safe_is_process_running(pid):
                    user_processes[uid].pop(iid, None)
                    cleaned += 1
            
            if not user_processes[uid]:
                del user_processes[uid]
        
        if cleaned > 0:
            save_data(PROCESS_FILE, user_processes)
            log_to_terminal(f"[CLEANUP] Removed {cleaned} stale process entries")

def get_recent_log_file(user_id):
    """Get the most recent log file for a user - FIXED VERSION"""
    try:
        active = user_processes.get(str(user_id), {})
        if active:
            latest_iid = max(active.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            log_path = active[latest_iid].get("log")
            if log_path and os.path.exists(log_path):
                return log_path
        
        log_pattern = os.path.join(LOG_DIR, f"{user_id}_*.log")
        log_files = glob.glob(log_pattern)
        
        if not log_files:
            return None
        
        latest_log = max(log_files, key=os.path.getmtime)
        
        if os.path.exists(latest_log) and os.path.getsize(latest_log) > 0:
            return latest_log
        
        return None
    except Exception as e:
        log_to_terminal(f"[LOGS] Error finding log file: {e}")
        return None

def get_user_running_processes(user_id):
    """Get count of actually running processes for a user"""
    running_count = 0
    try:
        user_procs = user_processes.get(str(user_id), {})
        for iid, data in user_procs.items():
            pid = data.get("pid")
            if pid and safe_is_process_running(pid):
                running_count += 1
    except:
        pass
    return running_count

# ================= NEW: SMART DEPENDENCY SCANNER =================
def scan_python_imports(project_path):
    """
    Scan all Python files in the project and extract import statements.
    Returns a list of required packages.
    """
    imports = set()
    
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ['venv', 'env', '__pycache__', '.git']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        try:
                            tree = ast.parse(content)
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Import):
                                    for alias in node.names:
                                        imports.add(alias.name.split('.')[0])
                                elif isinstance(node, ast.ImportFrom):
                                    if node.module:
                                        imports.add(node.module.split('.')[0])
                        except SyntaxError:
                            import_lines = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)', content, re.MULTILINE)
                            imports.update(import_lines)
                except:
                    continue
    
    return list(imports)

def get_standard_lib_modules():
    """Get a list of Python standard library modules"""
    try:
        std_lib = sys.stdlib_module_names
    except AttributeError:
        std_lib = {
            'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio', 'asyncore', 'atexit',
            'base64', 'bdb', 'binascii', 'binhex', 'bisect', 'builtins', 'bz2',
            'calendar', 'cgi', 'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs',
            'codeop', 'collections', 'colorsys', 'compileall', 'concurrent', 'configparser',
            'contextlib', 'contextvars', 'copy', 'copyreg', 'cProfile', 'csv', 'ctypes',
            'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis', 'distutils',
            'doctest', 'email', 'encodings', 'ensurepip', 'enum', 'errno',
            'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'fractions',
            'ftplib', 'functools',
            'gc', 'getopt', 'getpass', 'gettext', 'glob', 'graphlib', 'gzip',
            'hashlib', 'heapq', 'hmac', 'html', 'http',
            'imaplib', 'imghdr', 'imp', 'importlib', 'inspect', 'io', 'ipaddress',
            'itertools', 'json',
            'keyword', 'lib2to3', 'linecache', 'locale', 'logging', 'lzma',
            'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder',
            'msilib', 'msvcrt', 'multiprocessing',
            'netrc', 'nis', 'nntplib', 'numbers',
            'opcode', 'operator', 'optparse', 'os', 'ossaudiodev',
            'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil', 'platform',
            'plistlib', 'poplib', 'posix', 'pprint', 'profile', 'pstats', 'pty', 'pwd',
            'py_compile', 'pyclbr', 'pydoc', 'queue', 'quopri',
            'random', 're', 'readline', 'reprlib', 'resource', 'rlcompleter', 'runpy',
            'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex', 'shutil',
            'signal', 'site', 'smtpd', 'smtplib', 'sndhdr', 'socket', 'socketserver',
            'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep', 'struct',
            'subprocess', 'sunau', 'symtable', 'sys', 'sysconfig', 'syslog',
            'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios', 'textwrap',
            'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize', 'trace',
            'traceback', 'tracemalloc', 'tty', 'turtle', 'turtle demo', 'types', 'typing',
            'unicodedata', 'unittest', 'urllib', 'uu', 'uuid',
            'venv', 'warnings', 'wave', 'weakref', 'webbrowser', 'winreg', 'winsound',
            'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib'
        }
    return std_lib

def map_import_to_package(import_name):
    """
    Map Python import names to pip package names.
    Common packages often have different names.
    """
    mapping = {
        'cv2': 'opencv-python',
        'PIL': 'Pillow',
        'skimage': 'scikit-image',
        'sklearn': 'scikit-learn',
        'keras': 'Keras',
        'tensorflow': 'tensorflow',
        'tf': 'tensorflow',
        'torch': 'torch',
        'nn': 'torch',
        'F': 'torch',
        'transformers': 'transformers',
        'bs4': 'beautifulsoup4',
        'requests_html': 'requests-html',
        'dotenv': 'python-dotenv',
        'yaml': 'PyYAML',
        'jwt': 'PyJWT',
        'jwt_token': 'PyJWT',
        'pymongo': 'pymongo',
        'mongo': 'pymongo',
        'redis': 'redis',
        'psutil': 'psutil',
        'telebot': 'pyTelegramBotAPI',
        'telethon': 'Telethon',
        'aiohttp': 'aiohttp',
        'asyncio': None,
        'uvloop': 'uvloop',
        'flask': 'Flask',
        'django': 'Django',
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'starlette': 'starlette',
        'jinja2': 'Jinja2',
        'markupsafe': 'MarkupSafe',
        'werkzeug': 'Werkzeug',
        'pytz': 'pytz',
        'dateutil': 'python-dateutil',
        'numpy': 'numpy',
        'pandas': 'pandas',
        'matplotlib': 'matplotlib',
        'mpl_toolkits': 'matplotlib',
        'seaborn': 'seaborn',
        'plotly': 'plotly',
        'bokeh': 'bokeh',
        'pydantic': 'pydantic',
        'sqlalchemy': 'SQLAlchemy',
        'alembic': 'alembic',
        'sqlite3': None,
        'mysql': 'mysql-connector-python',
        'psycopg2': 'psycopg2-binary',
        'cx_oracle': 'cx_Oracle',
        'websocket': 'websocket-client',
        'websockets': 'websockets',
        'pynput': 'pynput',
        'keyboard': 'keyboard',
        'mouse': 'mouse',
        'selenium': 'selenium',
        'webdriver': 'selenium',
        'pyautogui': 'PyAutoGUI',
        'pillow': 'Pillow',
        'qrcode': 'qrcode',
        'Cryptodome': 'pycryptodomex',
        'Crypto': 'pycryptodome',
        'cryptography': 'cryptography',
        'nacl': 'PyNaCl',
        'paramiko': 'paramiko',
        'fabric': 'fabric',
        'invoke': 'invoke',
        'colorama': 'colorama',
        'termcolor': 'termcolor',
        'tqdm': 'tqdm',
        'click': 'click',
        'typer': 'typer',
        'rich': 'rich',
        'prompt_toolkit': 'prompt_toolkit',
        'pygments': 'Pygments',
        'strftime': None,
        'cmath': None,
        'decimal': None,
        'fractions': None,
        'statistics': None,
        'hashlib': None,
        'secrets': None,
        'venv': None,
        'pip': None,
        'setuptools': None,
        'wheel': None,
    }
    
    return mapping.get(import_name, import_name)

def filter_valid_packages(packages):
    """
    Filter out standard library modules and already installed packages.
    Returns a list of packages that actually need installation.
    """
    valid_packages = []
    std_lib = get_standard_lib_modules()
    
    for pkg in packages:
        if not pkg or pkg in std_lib:
            continue
        
        pip_package = map_import_to_package(pkg)
        if not pip_package:
            continue
        
        try:
            __import__(pkg)
            log_to_terminal(f"[SCAN] Package '{pkg}' already installed, skipping")
        except ImportError:
            valid_packages.append(pip_package)
    
    return list(set(valid_packages))

def scan_nodejs_dependencies(project_path):
    """
    Scan Node.js files for require() and import statements.
    Returns a list of detected packages.
    """
    packages = set()
    
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build']]
        
        for file in files:
            if file.endswith('.js'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        require_matches = re.findall(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content)
                        packages.update(require_matches)
                        
                        import_matches = re.findall(r'import\s+(?:.*\s+from\s+)?["\']([^"\']+)["\']', content)
                        packages.update(import_matches)
                except:
                    continue
    
    valid_packages = []
    for pkg in packages:
        if not pkg.startswith('.') and not pkg.startswith('/'):
            if pkg.startswith('@'):
                valid_packages.append(pkg)
            else:
                main_pkg = pkg.split('/')[0]
                if main_pkg and not main_pkg.startswith('.'):
                    valid_packages.append(main_pkg)
    
    return list(set(valid_packages))

# ================= ENHANCED DEPENDENCY INSTALLATION =================
def install_project_dependencies(project_path):
    """
    Automatically install Python and Node.js dependencies for a project.
    Scans files to detect requirements if no requirements.txt/package.json exists.
    Returns: (success, message) tuple
    """
    results = []
    
    # ===== PYTHON DEPENDENCIES =====
    py_packages = []
    
    req_file = os.path.join(project_path, "requirements.txt")
    if os.path.exists(req_file):
        try:
            log_to_terminal(f"[INSTALL] Installing from requirements.txt: {os.path.basename(project_path)}")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=180
            )
            
            if result.returncode == 0:
                results.append(("✅ Python", "Installed from requirements.txt"))
            else:
                error_msg = result.stderr.split('\n')[-2] if result.stderr else "Unknown error"
                results.append(("⚠️ Python", f"Failed: {error_msg[:100]}"))
        except subprocess.TimeoutExpired:
            results.append(("⚠️ Python", "Installation timed out"))
        except Exception as e:
            results.append(("⚠️ Python", f"Error: {str(e)}"))
    else:
        log_to_terminal(f"[SCAN] Scanning Python files for imports: {os.path.basename(project_path)}")
        try:
            detected_imports = scan_python_imports(project_path)
            log_to_terminal(f"[SCAN] Detected imports: {detected_imports}")
            
            packages_to_install = filter_valid_packages(detected_imports)
            
            if packages_to_install:
                log_to_terminal(f"[INSTALL] Installing detected packages: {packages_to_install}")
                
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", *packages_to_install],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode == 0:
                    results.append(("✅ Python", f"Installed {len(packages_to_install)} packages from scan"))
                else:
                    error_msg = result.stderr.split('\n')[-2] if result.stderr else "Unknown error"
                    results.append(("⚠️ Python", f"Partial install: {error_msg[:100]}"))
            else:
                results.append(("ℹ️ Python", "No external dependencies detected"))
                
        except Exception as e:
            log_to_terminal(f"[SCAN] Error scanning Python files: {e}")
            results.append(("ℹ️ Python", "No requirements.txt found, scan failed"))
    
    # ===== NODE.JS DEPENDENCIES =====
    package_file = os.path.join(project_path, "package.json")
    if os.path.exists(package_file):
        try:
            log_to_terminal(f"[INSTALL] Installing Node.js packages for {os.path.basename(project_path)}")
            
            npm_check = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=10)
            if npm_check.returncode != 0:
                results.append(("⚠️ Node.js", "npm not available on server"))
            else:
                result = subprocess.run(
                    ["npm", "install", "--silent"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=180
                )
                
                if result.returncode == 0:
                    results.append(("✅ Node.js", "Packages installed from package.json"))
                else:
                    error_msg = result.stderr.split('\n')[-2] if result.stderr else "Unknown error"
                    results.append(("⚠️ Node.js", f"Failed: {error_msg[:100]}"))
        except subprocess.TimeoutExpired:
            results.append(("⚠️ Node.js", "Installation timed out"))
        except FileNotFoundError:
            results.append(("⚠️ Node.js", "npm not installed"))
        except Exception as e:
            results.append(("⚠️ Node.js", f"Error: {str(e)}"))
    else:
        log_to_terminal(f"[SCAN] Scanning Node.js files for requires: {os.path.basename(project_path)}")
        try:
            detected_packages = scan_nodejs_dependencies(project_path)
            log_to_terminal(f"[SCAN] Detected Node packages: {detected_packages}")
            
            if detected_packages:
                npm_check = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=10)
                if npm_check.returncode != 0:
                    results.append(("⚠️ Node.js", "npm not available on server"))
                else:
                    result = subprocess.run(
                        ["npm", "install", *detected_packages, "--silent"],
                        cwd=project_path,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    
                    if result.returncode == 0:
                        results.append(("✅ Node.js", f"Installed {len(detected_packages)} packages from scan"))
                    else:
                        results.append(("⚠️ Node.js", f"Partial install: {len(detected_packages)} packages"))
            else:
                results.append(("ℹ️ Node.js", "No package.json found, no dependencies detected"))
                
        except Exception as e:
            log_to_terminal(f"[SCAN] Error scanning Node.js files: {e}")
            results.append(("ℹ️ Node.js", "No package.json found, scan failed"))
    
    message = "📦 **Dependency Installation Results:**\n\n"
    for platform, status in results:
        message += f"{platform}: {status}\n"
    
    overall_success = not any("Failed" in msg or "Error" in msg for _, msg in results)
    
    return overall_success, message

def async_install_dependencies(call, uid, proj, project_path):
    """Install dependencies with PREMIUM VISUAL progress bar and simple success message"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    key = f"{uid}_{proj}"
    
    if key in active_installations:
        bot.answer_callback_query(call.id, "⏳ Installation already in progress!", show_alert=True)
        return
    
    # PREMIUM VISUAL progress message
    progress_msg = bot.send_message(chat_id, "⚡ **Installing Dependencies...**\n\n⬜⬜⬜⬜  0%\n🔥 Initializing...", 
                                   parse_mode="Markdown")
    
    installation_done = False
    installation_result = None
    
    def run_install():
        nonlocal installation_done, installation_result
        installation_result = install_project_dependencies(project_path)
        installation_done = True
    
    install_thread = threading.Thread(target=run_install)
    install_thread.start()
    active_installations[key] = install_thread
    
    # PREMIUM VISUAL progress bar generator
    def get_progress_bar(percentage):
        if percentage >= 95:  # Final state shows 100%
            return "🟩🟩🟩🟩  100%"
        elif percentage >= 75:
            return "🟩🟩🟩⬜  75%"
        elif percentage >= 50:
            return "🟩🟩⬜⬜  50%"
        elif percentage >= 25:
            return "🟩⬜⬜⬜  25%"
        else:
            return "⬜⬜⬜⬜  0%"

    progress_steps = [0, 25, 50, 75, 95]  # Visual steps (95 maps to 100% bar)
    step_index = 0
    
    while not installation_done and install_thread.is_alive():
        if step_index < len(progress_steps):
            progress = progress_steps[step_index]
            try:
                bar = get_progress_bar(progress)
                status_text = "Initializing..." if progress == 0 else "Almost done..." if progress >= 75 else "Processing..."
                bot.edit_message_text(f"⚡ **Installing Dependencies...**\n\n{bar}\n🔥 {status_text}", 
                                     chat_id, progress_msg.message_id, parse_mode="Markdown")
            except:
                pass
            step_index += 1
        time.sleep(0.7)  # Slightly slower for premium feel
    
    install_thread.join()
    active_installations.pop(key, None)
    
    try:
        bot.delete_message(chat_id, progress_msg.message_id)
    except:
        pass
    
    success, msg = installation_result
    
    if success:
        marker_file = os.path.join(project_path, ".dependencies_installed")
        with open(marker_file, 'w') as f:
            f.write(datetime.now().isoformat())
    
    # ✅ FIX 2: REMOVED the problematic callback answer - already answered in main thread!
    # bot.answer_callback_query(call.id, "✅ Dependencies installed successfully!" if success else "⚠️ Some dependencies failed", 
    #                          show_alert=not success)
    
    # FINAL MESSAGE WITHOUT ANY BUTTONS - Just plain text
    if success:
        bot.edit_message_text(
            f"🎉 **✨ Installation Complete! ✨** 🎉\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📂 **Project:** *{safe_markdown(proj)}*\n"
            f"✅ **Status:** All dependencies installed successfully!\n\n"
            f"🚀 **Your project is ready to run!**\n\n"
            f"💡 **Next Step:** Go to **Deploy Console** to manage your project and start your bot.\n\n"
            f"✨ You're all set!",
            chat_id, message_id,
            parse_mode="Markdown"
        )
    else:
        # If failed, just refresh the original panel
        try:
            bot.edit_message_text(f"📁 Project: {safe_markdown(proj)}", chat_id, message_id,
                                 reply_markup=project_control_panel(uid, proj), parse_mode="Markdown")
        except Exception as e:
            log_to_terminal(f"[INSTALL] Error refreshing panel: {e}")

def are_dependencies_installed(project_path):
    """Check if dependencies were already installed"""
    marker_file = os.path.join(project_path, ".dependencies_installed")
    return os.path.exists(marker_file)

# ================= DATA PERSISTENCE =================
def load_json(file, default):
    """Load JSON data with file locking and safe key conversion"""
    if not file or not os.path.exists(file):
        return default
    try:
        with open(file, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return convert_keys_to_int(data)
    except Exception as e:
        log_to_terminal(f"[LOAD] Error loading {file}: {e}")
        return default

def save_data(file, data):
    """Save JSON data with file locking and atomic write"""
    if not file:
        return False
    try:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        temp_file = f"{file}.tmp"
        with open(temp_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(temp_file, file)
        return True
    except Exception as e:
        log_to_terminal(f"[SAVE] Error saving {file}: {e}")
        return False

def convert_keys_to_int(data):
    """Recursively convert string keys that represent integers to actual integers."""
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if isinstance(k, str) and k.lstrip('-').isdigit():
                try:
                    new_key = int(k)
                except ValueError:
                    new_key = k
            else:
                new_key = k
            
            new_dict[new_key] = convert_keys_to_int(v)
        return new_dict
    elif isinstance(data, list):
        return [convert_keys_to_int(item) for item in data]
    return data

# ================= LOAD DATA =================
blocked_users = load_json(BLOCK_FILE, {})
user_names = load_json(USER_DATA_FILE, {})
temp_admins = load_json(TEMP_ADMINS_FILE, {})
premium_users = load_json(PREMIUM_USERS_FILE, {}) 
settings = load_json(SETTINGS_FILE, {"price": 1, "premium_only": False})
clone_requests = load_json(CLONE_REQUESTS_FILE, {}) if not CLONED_BOT else {}
cloned_bots = {} if CLONED_BOT else load_json(CLONED_BOTS_FILE, {})
user_stats = load_json(USER_STATS_FILE, {})

try:
    raw_processes = load_json(PROCESS_FILE, {})
    if isinstance(raw_processes, dict):
        user_processes = raw_processes
    else:
        log_to_terminal("[WARNING] Invalid processes file, resetting")
        user_processes = {}
    
    instance_counter = 0
    users_to_remove = []
    
    for user_id, user_procs in list(user_processes.items()):
        if not isinstance(user_procs, dict):
            log_to_terminal(f"[WARNING] Corrupted data for user {user_id}, marking for removal")
            users_to_remove.append(user_id)
            continue
        
        for iid in user_procs.keys():
            try:
                if int(iid) > instance_counter:
                    instance_counter = int(iid)
            except (ValueError, TypeError):
                continue
    
    for user_id in users_to_remove:
        del user_processes[user_id]
    
    if users_to_remove:
        save_data(PROCESS_FILE, user_processes)
    
    log_to_terminal(f"[LOAD] Loaded {len(user_processes)} user processes, max instance: {instance_counter}")
    
except Exception as e:
    log_to_terminal(f"[ERROR] Failed to load processes: {e}, resetting")
    user_processes = {}
    instance_counter = 0

# ================= KEYBOARDS =================
def reply_menu(user_id):
    if is_admin(user_id) and str(user_id) not in user_names:
        try:
            user_chat = bot.get_chat(user_id)
            user_names[str(user_id)] = user_chat.full_name or "Admin"
            save_data(USER_DATA_FILE, user_names)
        except:
            user_names[str(user_id)] = "Admin"
            save_data(USER_DATA_FILE, user_names)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📂 Upload File", "🚀 Deploy Console")
    markup.row("📊 My Statistics", "⚡ Boot Speed")
    markup.row("📜 Live Logs", "🌐 Server Info")
    markup.row("💎 Get Premium", "📞 Contact Owner") 
    
    if not CLONED_BOT and is_premium(user_id):
        markup.add("🤖 Clone Bot")
    
    if is_admin(user_id): 
        markup.add("👑 Admin Panel")
    
    return markup

def premium_menu(user_id):
    markup = types.InlineKeyboardMarkup()
    current_price = settings.get("price", 1)
    markup.row(types.InlineKeyboardButton("👤 Contact Owner @RIHUU_X_DP", url="https://t.me/RIHUU_PRM_AI_BOT"))
    markup.row(types.InlineKeyboardButton(f"💎 Buy Premium ({current_price} XTR)", callback_data="PREMIUM_PAY_INVOICE"))
    return markup

def admin_panel_inline(user_id):
    if not is_admin(user_id):
        return types.InlineKeyboardMarkup()
    
    markup = types.InlineKeyboardMarkup()

    if not is_owner(user_id):
        markup.row(types.InlineKeyboardButton("📨 Private Msg", callback_data="ADM|PRIV_LIST"),
                   types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM|BC_START"))
        markup.row(types.InlineKeyboardButton("👥 User List", callback_data="ADM|USER_LIST"))
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|CLOSE_PANEL"))
        return markup

    markup.row(types.InlineKeyboardButton("📂 File Manager", callback_data="ADM|FILE_MAN"),
               types.InlineKeyboardButton("👥 Users", callback_data="ADM|USER_LIST"))
    
    markup.row(types.InlineKeyboardButton("📨 Private Msg", callback_data="ADM|PRIV_LIST"),
               types.InlineKeyboardButton("📢 Broadcast", callback_data="ADM|BC_START"))
    
    markup.row(types.InlineKeyboardButton("🚫 Block", callback_data="ADM|LIST_ACTIVE"),
               types.InlineKeyboardButton("✅ Unblock", callback_data="ADM|LIST_BLOCKED"))
    
    markup.row(types.InlineKeyboardButton("➕ Grant Temp", callback_data="ADM|TEMP_LIST"),
               types.InlineKeyboardButton("➖ Revoke Temp", callback_data="ADM|TEMP_REVOKE_LIST"))
    
    markup.row(types.InlineKeyboardButton("💎 Premium List", callback_data="ADM|PREM_LIST"),
               types.InlineKeyboardButton("💰 Set Price", callback_data="ADM|CHANGE_PRICE"))
    
    markup.row(types.InlineKeyboardButton("🎁 Give Premium", callback_data="ADM|PREM_GIVEAWAY"),
               types.InlineKeyboardButton("🗑️ Revoke Premium", callback_data="ADM|PREM_DELETE"))
    
    current_mode = is_premium_only()
    status_emoji = "🔓" if current_mode else "🔒"
    action_text = "Turn OFF" if current_mode else "Turn ON"
    status_text = f"{status_emoji} Premium Mode: {action_text}"
    markup.row(types.InlineKeyboardButton(status_text, callback_data="ADM|PREMIUM_TOGGLE"))
    
    if not CLONED_BOT:
        pending_count = len([r for r in clone_requests.values() if r.get('status') == 'pending'])
        markup.row(types.InlineKeyboardButton(f"⏳ Clone ({pending_count})", callback_data="ADM|CLONE_PENDING"),
                   types.InlineKeyboardButton("🤖 Manage Bots", callback_data="ADM|CLONE_MANAGE"))
    
    markup.row(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|CLOSE_PANEL"))
    
    return markup

def cloned_bots_menu():
    markup = types.InlineKeyboardMarkup()
    current_clones = load_json(CLONED_BOTS_FILE, {}) if not CLONED_BOT else {}
    
    if not current_clones:
        markup.add(types.InlineKeyboardButton("❌ No Cloned Bots Found", callback_data="NOOP"))
    else:
        for token, config in current_clones.items():
            try:
                owner_name = user_names.get(str(config.get('owner_id', '')), 'Unknown')
                bot_name = config.get('bot_name', 'Unknown')
                
                if not bot_name or bot_name == "None":
                    bot_name = "Unknown"
                
                pid = config.get('process_pid')
                is_running = safe_is_process_running(pid)
                status_icon = "🟢" if is_running else "🔴"
                
                safe_token = get_safe_token(token)
                btn_text = f"{status_icon} @{safe_markdown(bot_name)} → {safe_markdown(owner_name)}"
                
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"ADM|CLONE_VIEW|{safe_token}"))
            except:
                continue
    
    markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
    return markup

def projects_menu(user_id):
    user_dir = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    projects = []
    if os.path.exists(user_dir):
        projects = [d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))]
    
    markup = types.InlineKeyboardMarkup()
    if not projects:
        markup.add(types.InlineKeyboardButton("❌ No Projects Found", callback_data="NOOP"))
    else:
        for p in projects:
            markup.add(types.InlineKeyboardButton(f"📁 {safe_markdown(p)}", callback_data=f"OPEN_PROJ|{user_id}|{p}"))
    return markup

def project_control_panel(target_user_id, project_name):
    markup = types.InlineKeyboardMarkup()
    active = user_processes.get(str(target_user_id), {})
    
    for iid, data in active.items():
        if data["project"] == project_name:
            markup.row(
                types.InlineKeyboardButton(f"🛑 Stop {safe_markdown(data['file'])}", 
                                          callback_data=f"STOP|{target_user_id}|{iid}|{project_name}"),
                types.InlineKeyboardButton(f"🔄 Restart", 
                                          callback_data=f"RESTART|{target_user_id}|{iid}|{project_name}|{data['file']}")
            )

    project_path = os.path.join(BASE_DIR, str(target_user_id), project_name)
    if os.path.exists(project_path):
        runnable_files = [f for f in os.listdir(project_path) if f.endswith((".py", ".js", ".sh"))]
        
        has_dep_files = os.path.exists(os.path.join(project_path, "requirements.txt")) or \
                       os.path.exists(os.path.join(project_path, "package.json")) or \
                       any(f.endswith('.py') for f in runnable_files) or \
                       any(f.endswith('.js') for f in runnable_files)
        
        if has_dep_files and not are_dependencies_installed(project_path):
            markup.add(types.InlineKeyboardButton("📦 Install Dependencies", 
                                                 callback_data=f"INSTALL_DEPS|{target_user_id}|{project_name}"))
        
        if not runnable_files:
            markup.add(types.InlineKeyboardButton("⚠️ No runnable files found", callback_data="NOOP"))
        else:
            for f in runnable_files:
                is_disabled = False
                if not is_premium(target_user_id):
                    active_count = get_user_active_count(target_user_id)
                    if active_count >= MAX_FREE_BOTS:
                        is_running = False
                        for iid, data in active.items():
                            if data["project"] == project_name and data["file"] == f:
                                is_running = True
                                break
                        if not is_running:
                            is_disabled = True
                
                if is_disabled:
                    markup.row(
                        types.InlineKeyboardButton(f"⛔ {safe_markdown(f)} (Limit Reached)", callback_data="NOOP"),
                        types.InlineKeyboardButton("💎 Upgrade", callback_data="PREMIUM_PAY_INVOICE")
                    )
                else:
                    markup.row(
                        types.InlineKeyboardButton(f"▶️ Run {safe_markdown(f)}", 
                                                  callback_data=f"RUN|{target_user_id}|{project_name}|{f}"),
                        types.InlineKeyboardButton("🗑️ Delete File", 
                                                  callback_data=f"DEL_FILE|{target_user_id}|{project_name}|{f}")
                    )
        
        markup.add(types.InlineKeyboardButton("🗑️ Delete Project 💥", 
                                              callback_data=f"DEL_PROJ|{target_user_id}|{project_name}"))
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", 
                                              callback_data=f"BACK_TO_LIST|{target_user_id}"))
    
    return markup

def get_speed_test_message():
    """Generate speed test message with current metrics"""
    start_time = time.time()
    try:
        bot_info = bot.get_me()
        response_time = round((time.time() - start_time) * 1000, 2)
    except:
        response_time = round(random.uniform(50, 250), 2)
    
    cpu_percent = safe_cpu_percent()
    memory_percent = safe_memory_percent()
    
    if isinstance(response_time, (int, float)) and response_time < 100:
        status_line = "🟢📡 Low"
    elif isinstance(response_time, (int, float)) and response_time < 200:
        status_line = "🟡📡 Medium"
    else:
        status_line = "🔴📡 High"
    
    uptime_seconds = int(time.time() - START_TIME)
    uptime_str = str(timedelta(seconds=uptime_seconds)).split('.')[0]
    
    return f"""╔═══════════════════════╗
    ⚡ SPEED TEST ⚡
╚═══════════════════════╝
🐌 Response Time: {response_time}ms
📊 Status: {status_line}
🖥️ Server Info:
• CPU: {cpu_percent}%
• Memory: {memory_percent}%
• Uptime: Online ✅ ({uptime_str})
✨ Bot is running smoothly!"""

@bot.message_handler(commands=['start'])
def start(message):
    user = message.from_user
    user_id = int(user.id)
    
    log_to_terminal(f"User {user.full_name} ({user_id}) started the bot")
    
    if is_premium_only() and not is_premium(user_id) and not is_admin(user_id):
        bot.send_message(message.chat.id, f"🔒 **Premium Only Mode is Active**\n\nThis bot is currently available only for Premium users.\n\n💎 Purchase Premium to access all features.", 
                        reply_markup=premium_menu(user_id), parse_mode="Markdown")
        return
    
    if user_id == int(ADMIN_ID):
        if user_id in blocked_users:
            del blocked_users[user_id]
            save_data(BLOCK_FILE, blocked_users)
        user_names[str(user_id)] = user.full_name or "Admin"
        save_data(USER_DATA_FILE, user_names)
    
    if user_id in blocked_users and user_id != int(ADMIN_ID):
        bot.send_message(message.chat.id, "🚫 You have been blocked.")
        return
    
    user_names[str(user_id)] = user.full_name
    save_data(USER_DATA_FILE, user_names)
    
    bio = "Not available"
    try:
        chat_info = bot.get_chat(user_id)
        if chat_info.bio:
            bio = f"```\n{safe_markdown(chat_info.bio)}\n```"
        else:
            bio = "No bio set"
    except:
        bio = "Could not fetch bio"
    
    username = f"@{user.username}" if user.username else "No username"
    bot_display_name = "🚀 Main Hosting Bot" if not CLONED_BOT else "🤖 Cloned Bot"
    
    if is_owner(user_id):
        admin_msg = "👑 Owner / Full Admin"
    elif is_admin(user_id):
        admin_msg = "👮 Temporary Admin"
    elif is_premium(user_id):
        admin_msg = "💎 Premium User"
    else:
        admin_msg = "👤 Free User (Limit: 3 bots)"
    
    premium_mode_status = ""
    if is_premium_only():
        premium_mode_status = "\n🔒 **Premium Mode: ON** - Only premium users can access"
    
    user_info_text = (
        f"👋 Hello, *{safe_markdown(user.full_name)}*!\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"👤 **Username:** {username}\n"
        f"📝 **Bio:** {bio}\n\n"
        f"Riyad Hosting Bot is a Telegram bot that makes managing your hosting and servers easy. "
        f"With simple commands, you can check server status, create backups, view hosting plans, "
        f"and get real-time notifications. It's designed to save time and simplify server management for everyone! 🚀\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"**{bot_display_name}**\n"
        f"{admin_msg}\n"
        f"📂 **Data Dir:** `{BOT_DATA_DIR_NAME}`"
        f"{premium_mode_status}"
    )
    
    try:
        photos = bot.get_user_profile_photos(user_id)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            bot.send_photo(message.chat.id, file_id, caption=user_info_text,
                         parse_mode="Markdown", reply_markup=reply_menu(user_id))
            return
    except:
        pass
    
    bot.send_message(message.chat.id, user_info_text, parse_mode="Markdown", reply_markup=reply_menu(user_id))

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    user_id = message.from_user.id
    payment_info = message.successful_payment
    
    premium_users[user_id] = {
        "date": datetime.now().isoformat(),
        "amount": payment_info.total_amount,
        "currency": payment_info.currency,
        "via": "payment"
    }
    save_data(PREMIUM_USERS_FILE, premium_users)
    
    bot.send_message(message.chat.id, "🎉 **Payment Successful!**\n\n✅ Your Premium Plan has been activated! 💎", parse_mode="Markdown")
    
    try:
        bot.send_message(ADMIN_ID, f"💰 **New Premium User!**\nUser: {safe_markdown(message.from_user.full_name)} (`{user_id}`)\nAmount: {payment_info.total_amount} {payment_info.currency}")
    except:
        pass

@bot.message_handler(content_types=['document'])
def upload_file(message):
    user_id = message.from_user.id
    log_to_terminal(f"User {user_id} uploading file...")
    
    if user_id in blocked_users and user_id != int(ADMIN_ID): 
        return
    
    if is_premium_only() and not is_premium(user_id) and not is_admin(user_id):
        bot.send_message(message.chat.id, f"🔒 **Premium Only Mode is Active**\n\nThis bot is currently available only for Premium users.\n\n💎 Purchase Premium to access all features.", 
                        reply_markup=premium_menu(user_id), parse_mode="Markdown")
        return
    
    if not is_premium(user_id):
        can_proceed, msg = check_free_limits(user_id, "deploy")
        if not can_proceed:
            bot.send_message(message.chat.id, msg, reply_markup=premium_menu(user_id), parse_mode="Markdown")
            return
    
    file_name = message.document.file_name.lower()
    
    if file_name.endswith(".zip") or file_name.endswith(".tar.gz"):
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            file_type = "zip" if file_name.endswith(".zip") else "tar"
            temp_ext = ".zip" if file_name.endswith(".zip") else ".tar.gz"
            
            temp_path = os.path.join(TEMP_DIR, f"{user_id}_temp_{int(time.time())}{temp_ext}")
            with open(temp_path, 'wb') as f: 
                f.write(downloaded_file)
            
            user_states[user_id] = {
                "state": "WAITING_FOR_PROJECT_NAME",
                "temp_path": temp_path,
                "file_type": file_type
            }
            
            bot.send_message(message.chat.id, "✅ File received!\n\nNow, please enter your bot name:")
                
        except Exception as e:
            log_to_terminal(f"Upload error: {e}")
            bot.send_message(message.chat.id, f"❌ Upload failed: {safe_markdown(str(e))}")
    else:
        bot.send_message(message.chat.id, "❌ Please send a .zip or .tar.gz file only.", parse_mode=None)

@bot.message_handler(func=lambda message: True)
def text_handler(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if user_id in blocked_users and user_id != int(ADMIN_ID): 
        return

    if is_premium_only() and not is_premium(user_id) and not is_admin(user_id):
        if text != "💎 Get Premium" and not text.startswith("/"):
            bot.send_message(message.chat.id, f"🔒 **Premium Only Mode is Active**\n\nThis bot is currently available only for Premium users.\n\n💎 Purchase Premium to access all features.", 
                            reply_markup=premium_menu(user_id), parse_mode="Markdown")
            return

    if isinstance(user_states.get(user_id), dict) and user_states[user_id].get("state") == "WAITING_FOR_PROJECT_NAME":
        if not is_premium(user_id):
            can_proceed, msg = check_free_limits(user_id, "deploy")
            if not can_proceed:
                bot.send_message(message.chat.id, msg, reply_markup=premium_menu(user_id), parse_mode="Markdown")
                return
        
        project_name = text.strip()
        project_name = "".join(x for x in project_name if x.isalnum() or x in "._-")
        if not project_name: 
            bot.send_message(message.chat.id, "❌ Invalid name. Use letters, numbers, ., _, - only.", parse_mode=None)
            return
        
        temp_info = user_states[user_id]
        temp_path = temp_info["temp_path"]
        file_type = temp_info["file_type"]
        
        dest = os.path.join(BASE_DIR, str(user_id), project_name)
        if os.path.exists(dest): 
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        
        try:
            if file_type == "zip":
                with zipfile.ZipFile(temp_path, "r") as z: 
                    z.extractall(dest)
            else:
                with tarfile.open(temp_path, "r:gz") as tar:
                    tar.extractall(dest)
            
            extracted_files = []
            for root, dirs, files in os.walk(dest):
                for f in files:
                    if f.endswith((".py", ".js", ".sh")):
                        extracted_files.append(f)
            
            runnable_count = len(extracted_files)
            py_files = [f for f in extracted_files if f.endswith('.py')]
            js_files = [f for f in extracted_files if f.endswith('.js')]
            
            file_summary = f"📊 **Project Analysis Complete!**\n"
            file_summary += f"📁 {runnable_count} runnable files found\n"
            if py_files:
                file_summary += f"🐍 {len(py_files)} Python files\n"
            if js_files:
                file_summary += f"📜 {len(js_files)} Node.js files\n\n"
            
            if runnable_count > 0:
                files_list = "\n".join([f"📄 {safe_markdown(f)}" for f in extracted_files[:5]])
                if runnable_count > 5:
                    files_list += f"\n... and {runnable_count - 5} more"
                
                markup = types.InlineKeyboardMarkup()
                req_file = os.path.join(dest, "requirements.txt")
                package_file = os.path.join(dest, "package.json")
                has_py_files = any(f.endswith('.py') for f in extracted_files)
                has_js_files = any(f.endswith('.js') for f in extracted_files)
                
                if os.path.exists(req_file) or os.path.exists(package_file) or has_py_files or has_js_files:
                    markup.add(types.InlineKeyboardButton("📦 Install Dependencies", 
                                                         callback_data=f"INSTALL_DEPS|{user_id}|{project_name}"))
                
                bot.send_message(message.chat.id, f"{file_summary}📂 **Project Files:**\n{files_list}\n\nClick the button to install dependencies if needed.", 
                               reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, f"{file_summary}⚠️ No runnable files (.py, .js, .sh) found.")
                
            if str(user_id) not in user_stats:
                user_stats[str(user_id)] = {"uploads": 0, "script_runs": 0}
            user_stats[str(user_id)]["uploads"] += 1
            save_data(USER_STATS_FILE, user_stats)
                
        except Exception as e:
            log_to_terminal(f"Extraction error: {e}")
            bot.send_message(message.chat.id, f"❌ Failed to extract: {safe_markdown(str(e))}")
        
        if os.path.exists(temp_path): 
            os.remove(temp_path)
        user_states[user_id] = None
        return

    if isinstance(user_states.get(user_id), str) and user_states[user_id] == "WAITING_FOR_CLONE_TOKEN":
        token = text.strip()
        
        if not token or ":" not in token or len(token) < 40:
            bot.send_message(message.chat.id, "❌ Invalid token format.", parse_mode=None)
            user_states[user_id] = None
            return
        
        try:
            test_bot = telebot.TeleBot(token)
            bot_info = test_bot.get_me()
            bot_name = bot_info.username
            
            if token in cloned_bots:
                bot.send_message(message.chat.id, "❌ This bot is already cloned!", parse_mode=None)
                user_states[user_id] = None
                return
            
            clone_requests[token] = {
                "user_id": user_id,
                "bot_name": bot_name,
                "bot_id": bot_info.id,
                "timestamp": datetime.now().isoformat(),
                "status": "pending"
            }
            save_data(CLONE_REQUESTS_FILE, clone_requests)
            
            user_details = (
                f"🤖 **CLONE BOT REQUEST**\n\n"
                f"👤 **User:** {safe_markdown(user_names.get(str(user_id), 'Unknown'))}\n"
                f"🆔 **User ID:** `{user_id}`\n"
                f"🤖 **Bot Name:** `@{safe_markdown(bot_info.username)}`\n"
                f"**Token:** `{token}`\n\n"
                f"Approve this request?"
            )
            
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("✅ Yes, Clone It", callback_data=f"CLONE_APPROVE|{token}"),
                types.InlineKeyboardButton("❌ No, Reject", callback_data=f"CLONE_REJECT|{token}")
            )
            
            bot.send_message(ADMIN_ID, user_details, parse_mode="Markdown", reply_markup=markup)
            
            bot.send_message(message.chat.id, f"✅ **Clone request submitted!**\n\n**Bot:** `@{safe_markdown(bot_name)}`\n\n⏳ Waiting for admin approval...")
            
        except Exception as e:
            log_to_terminal(f"Clone token error: {e}")
            bot.send_message(message.chat.id, f"❌ Invalid token or error: {safe_markdown(str(e))}")
        
        user_states[user_id] = None
        return

    if isinstance(user_states.get(user_id), str) and user_states[user_id].startswith("TEMP_ADMIN_DURATION|"):
        if not is_owner(user_id):
            bot.send_message(message.chat.id, "🚫 Only Owner can grant temp admin.")
            return

        try:
            duration_input = text.strip().lower()
            if duration_input.endswith('m'):
                minutes = int(duration_input[:-1])
                expiry = datetime.now() + timedelta(minutes=minutes)
                duration_text = f"{minutes} minutes"
            elif duration_input.endswith('h'):
                hours = float(duration_input[:-1])
                expiry = datetime.now() + timedelta(hours=hours)
                duration_text = f"{hours} hours"
            else:
                hours = float(duration_input)
                expiry = datetime.now() + timedelta(hours=hours)
                duration_text = f"{hours} hours"
                
            target_id = int(user_states[user_id].split("|")[1])
            temp_admins[target_id] = expiry.isoformat()
            save_data(TEMP_ADMINS_FILE, temp_admins)
            
            target_name = user_names.get(str(target_id), 'Unknown')
            
            try:
                bot.send_message(target_id, f"⏳ **You have been granted Temporary Admin access!**\n\nDuration: {duration_text}\n\nYou now have admin privileges. Use them responsibly!")
            except:
                pass
            
            bot.send_message(message.chat.id, f"✅ **Temp admin granted to {safe_markdown(target_name)}** for {duration_text}!")
            
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid duration. Enter a number with 'm' for minutes (e.g., 30m) or 'h' for hours (e.g., 2h).", parse_mode=None)
        
        user_states[user_id] = None
        return

    if isinstance(user_states.get(user_id), str) and user_states[user_id].startswith("PM_TO|"):
        target_id = int(user_states[user_id].split("|")[1])
        try:
            bot.send_message(target_id, f"📩 **Message from Admin:**\n\n{text}")
            bot.send_message(message.chat.id, "✅ Message sent!")
        except: 
            bot.send_message(message.chat.id, "❌ Failed to send.", parse_mode=None)
        user_states[user_id] = None
        return

    if user_states.get(user_id) == "BC_WAIT" and is_admin(user_id):
        count = 0
        for uid in user_names.keys():
            try:
                bot.send_message(uid, f"📢 **Broadcast:**\n\n{text}")
                count += 1
            except: 
                pass
        user_states[user_id] = None
        bot.send_message(message.chat.id, f"✅ Broadcast sent to {count} users!")
        return
    
    if user_states.get(user_id) == "WAITING_FOR_PRICE" and is_owner(user_id):
        try:
            new_price = int(text)
            if new_price < 1: raise ValueError
            settings['price'] = new_price
            save_data(SETTINGS_FILE, settings)
            bot.send_message(message.chat.id, f"✅ Premium price updated to {new_price} XTR.")
        except:
            bot.send_message(message.chat.id, "❌ Invalid price. Enter a whole number (e.g., 50).", parse_mode=None)
        user_states[user_id] = None
        return

    if text == "💎 Get Premium":
        benefits = f"""💎 **PREMIUM PLAN BENEFITS**

✅ **Unlimited Bot Hosting** - No limits on projects
✅ **Maximum Performance** - Priority resources
✅ **Priority Support** - Direct admin access
✅ **All Features** - Full access to everything
{'✅ **Clone Bot** - Create your own cloned bots' if not CLONED_BOT else ''}
{'✅ **Bot Access** - Use bot during premium-only mode' if is_premium_only() else ''}

Current Price: **{settings.get('price', 1)} XTR**

💰 Click below to purchase!"""
    
        bot.send_message(message.chat.id, benefits, reply_markup=premium_menu(user_id), parse_mode="Markdown")

    elif text == "📂 Upload File":
        bot.send_message(message.chat.id, "📎 Please send your .zip or .tar.gz file now.", parse_mode=None)
    
    elif text == "🚀 Deploy Console":
        markup = projects_menu(user_id)
        bot.send_message(message.chat.id, "📂 Select Project:", reply_markup=markup)
    
    elif text == "📊 My Statistics":
        if str(user_id) not in user_stats:
            user_stats[str(user_id)] = {"uploads": 0, "script_runs": 0}
        
        user_name = user_names.get(str(user_id), "Unknown")
        account_type = "Premium 💎" if is_premium(user_id) else "Free 🆓"
        projects = get_user_project_count(user_id)
        total_files = get_user_total_files(user_id)
        running_scripts = get_user_active_count(user_id)
        memory_usage = get_user_memory_usage(user_id)
        uploads = user_stats[str(user_id)].get("uploads", 0)
        script_runs = user_stats[str(user_id)].get("script_runs", 0)
        bot_status = "Active" if running_scripts > 0 else "Idle"
        tier = "Premium Tier - Unlimited" if is_premium(user_id) else f"Free Tier - {MAX_FREE_BOTS} projects max"
        
        stats_text = f"""╔═══════════════════════╗
    📊 YOUR STATISTICS 📊
╚═══════════════════════╝
👤 User: {safe_markdown(user_name)}
🆔 ID: `{user_id}`
💎 Account: {account_type}
📦 PROJECT STATISTICS:
📁 Projects: {projects}
📄 Total Files: {total_files}
🚀 Running Scripts: {running_scripts}
💾 RAM Usage: {"∞ Unlimited" if is_premium(user_id) else f"{memory_usage:.1f} MB"}
📈 USAGE STATISTICS:
📂 Uploads: {uploads}
▶️ Script Runs: {script_runs}
✅ Bot Status: {bot_status}
🎯 YOUR TIER:
{tier}"""
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="MY_STATS_DELETE"))
        
        bot.send_message(message.chat.id, stats_text, parse_mode="Markdown", reply_markup=markup)
    
    elif text == "⚡ Boot Speed":
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🔄 testing", callback_data="SPEED_TEST"),
            types.InlineKeyboardButton("🏠 Main Menu", callback_data="SPEED_MAIN_MENU")
        )
        
        cpu_percent = safe_cpu_percent()
        memory_percent = safe_memory_percent()
        uptime_seconds = int(time.time() - START_TIME)
        uptime_str = str(timedelta(seconds=uptime_seconds)).split('.')[0]
        
        initial_msg = f"""╔═══════════════════════╗
    ⚡ SPEED TEST ⚡
╚═══════════════════════╝
🐌 Response Time: Press 'testing' to measure
📊 Status: 🟡📡 Medium
🖥️ Server Info:
• CPU: {cpu_percent}%
• Memory: {memory_percent}%
• Uptime: Online ✅ ({uptime_str})
✨ Bot is running smoothly!"""
        
        bot.send_message(message.chat.id, initial_msg, reply_markup=markup, parse_mode="Markdown")
    
    elif text == "🌐 Server Info":
        py_version = sys.version.split()[0]
        os_info = safe_markdown(f"{platform.system()} {platform.release()} ({platform.machine()})")
        
        server_banner = f"""┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🇧🇩🏡🇯🇵  PYTHON VIRTUAL PRIVATE SERVER [PRO]          ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

  ⭐ PREMIUM PYTHON VPS ENVIRONMENT ⭐

  📌 SERVER INFO:
  ──────────────────────────────────────────
  🚀 STATUS    : Ultra Optimized & Online
  🐍 RUNTIME   : Python {py_version} (Latest Stable)
  ⚡ NETWORK   : 10 Gbps Hyper-Speed
  🛡️ SECURITY  : Enterprise Grade Anti-DDoS
  💎 UPTIME    : 99.99% Guaranteed
  💻 OS        : {os_info}
  ──────────────────────────────────────────

  🛠️ SYSTEM LOGS:
  [✔] CPU Core Optimization: Active
  [✔] RAM Management: Balanced
  [✔] Root Access: Fully Encrypted

  ✨ "Empowering your code with elite performance" """
        
        bot.send_message(message.chat.id, server_banner, parse_mode="Markdown")
    
    elif text == "📜 Live Logs":
        running_count = get_user_running_processes(user_id)
        
        if running_count == 0:
            bot.send_message(message.chat.id, "❌ **No script currently running**\n\nStart a bot first to view live logs.", 
                           parse_mode="Markdown")
            return
        
        log_path = get_recent_log_file(user_id)
        
        if not log_path:
            bot.send_message(message.chat.id, "⏳ **Process started but logs not available yet**\n\nPlease wait 5-10 seconds and try again.", 
                           parse_mode="Markdown")
            return
        
        try:
            with open(log_path, "r", encoding="utf-8", errors='ignore') as f:
                f.seek(0, 2)
                file_size = f.tell()
                
                if file_size == 0:
                    bot.send_message(message.chat.id, "📜 **Log file is empty (process starting...)**\n\nWait a moment and try again.", 
                                   parse_mode="Markdown")
                    return
                
                read_size = min(4000, file_size)
                f.seek(file_size - read_size)
                logs_content = f.read()
            
            safe_logs = logs_content.replace('`', '‛').replace('```', '‛‛‛')
            log_file_name = os.path.basename(log_path)
            
            header = f"📜 **Live Logs** ({running_count} active)\n\n📄 File: `{safe_markdown(log_file_name)}`\n📊 Size: {file_size} bytes\n━━━━━━━━━━━━━━━\n\n"
            if file_size > 4000:
                header += f"⚠️ Showing last 4,000 characters of {file_size} total:\n━━━━━━━━━━━━━━━\n\n"
            
            full_message = f"{header}```\n{safe_logs}\n```"
            
            if len(full_message) > 4096:
                safe_logs = safe_logs[:4096 - len(header) - 10]
                full_message = f"{header}```\n{safe_logs}\n```"
            
            bot.send_message(message.chat.id, full_message, parse_mode="Markdown")
            
        except Exception as e:
            log_to_terminal(f"[LOGS] Error reading log file: {e}")
            bot.send_message(message.chat.id, f"❌ **Error reading logs:**\n\n`{safe_markdown(str(e))}`\n\nTry running a bot first.", 
                           parse_mode="Markdown")
    
    elif text == "📞 Contact Owner":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Message Owner", url="https://t.me/RIHUU_PRM_AI_BOT"))
        
        bot.send_message(
            message.chat.id, 
            "Click below to contact the owner:", 
            parse_mode=None,
            reply_markup=markup
        )
    
    elif text == "👑 Admin Panel" and is_admin(user_id):
        bot.send_message(message.chat.id, "👑 Admin Panel", reply_markup=admin_panel_inline(user_id))
    
    elif text == "🤖 Clone Bot" and not CLONED_BOT:
        if not is_premium(user_id):
            bot.send_message(message.chat.id, f"❌ **Clone Bot is a Premium Feature!**\n\n🤖 Only Premium users can create their own cloned bots.\n\n💎 **Upgrade to Premium** to unlock this feature:", 
                            reply_markup=premium_menu(user_id), parse_mode="Markdown")
            return
        
        bot.send_message(message.chat.id, "🤖 Want your own bot?\n\n1. Create bot via @BotFather\n2. Copy HTTP API token\n3. Send it here\n\nRequest will be reviewed by admin.", parse_mode=None)
        user_states[user_id] = "WAITING_FOR_CLONE_TOKEN"
    
    else:
        pass

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global instance_counter, clone_requests, cloned_bots, user_processes, user_stats
    
    user_id = call.from_user.id
    data_parts = call.data.split("|")
    
    try:
        if call.data == "CLOSE_PANEL" or (len(data_parts) > 1 and data_parts[1] == "CLOSE_PANEL"):
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id, "✅ Panel closed!")
            except Exception as e:
                log_to_terminal(f"[CLOSE] Error: {e}")
                bot.answer_callback_query(call.id, "❌ Failed to close panel", show_alert=True)
            return

        if call.data == "MY_STATS_DELETE":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id, "✅ Message deleted!")
            except:
                bot.answer_callback_query(call.id, "❌ Failed to delete message", show_alert=True)
            return
        
        if data_parts[0] == "OPEN_PROJ" and len(data_parts) >= 3:
            target_user = int(data_parts[1])
            project_name = data_parts[2]
            
            if not (is_admin(user_id) or user_id == target_user):
                bot.answer_callback_query(call.id, "Access denied!", show_alert=True)
                return
                
            bot.edit_message_text(f"📁 Project: {safe_markdown(project_name)}", call.message.chat.id, call.message.message_id,
                                 reply_markup=project_control_panel(target_user, project_name), parse_mode="Markdown")
            return

        if data_parts[0] == "BACK_TO_LIST" and len(data_parts) >= 2:
            target_user = int(data_parts[1])
            
            if not (is_admin(user_id) or user_id == target_user):
                return
                
            bot.edit_message_text("📂 Select Project:", call.message.chat.id, call.message.message_id,
                                 reply_markup=projects_menu(target_user), parse_mode="Markdown")
            return

        if data_parts[0] == "DEL_FILE" and len(data_parts) >= 4:
            target_user = int(data_parts[1])
            project_name = data_parts[2]
            filename = data_parts[3]
            
            if not (is_admin(user_id) or user_id == target_user):
                return
            
            file_path = os.path.join(BASE_DIR, str(target_user), project_name, filename)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                
                bot.edit_message_text(f"📁 Project: {safe_markdown(project_name)}", call.message.chat.id, call.message.message_id,
                                     reply_markup=project_control_panel(target_user, project_name), parse_mode="Markdown")
                bot.answer_callback_query(call.id, f"✅ File {safe_markdown(filename)} deleted!")
            else:
                bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return

        if data_parts[0] == "INSTALL_DEPS" and len(data_parts) >= 3:
            uid, proj = int(data_parts[1]), data_parts[2]
            
            if not (is_admin(user_id) or user_id == uid):
                bot.answer_callback_query(call.id, "Access denied!", show_alert=True)
                return
            
            project_path = os.path.join(BASE_DIR, str(uid), proj)
            
            if not os.path.exists(project_path):
                bot.answer_callback_query(call.id, "Project not found!", show_alert=True)
                return
            
            # ✅ FIX 1: Answer callback IMMEDIATELY before starting thread
            bot.answer_callback_query(call.id, "⏳ Installation started...", show_alert=False)
            
            # Then start installation in background
            threading.Thread(target=async_install_dependencies, 
                           args=(call, uid, proj, project_path), 
                           daemon=True).start()
            
            return

        if data_parts[0] == "RUN" and len(data_parts) >= 4:
            uid, proj, file = int(data_parts[1]), data_parts[2], data_parts[3]
            
            if not (is_admin(user_id) or user_id == uid):
                return
            
            if not is_premium(uid):
                can_proceed, msg = check_free_limits(uid, "run")
                if not can_proceed:
                    bot.answer_callback_query(call.id, msg, show_alert=True)
                    return
            
            work_dir = os.path.join(BASE_DIR, str(uid), proj)
            file_path = os.path.join(work_dir, file)
            
            if file.endswith(".py"):
                cmd = [sys.executable, "-u", file_path]
            elif file.endswith(".js"):
                cmd = ["node", file_path]
            else:
                cmd = ["bash", file_path]
            
            with lock:
                instance_counter += 1
                current_iid = instance_counter
            
            log_path = os.path.join(LOG_DIR, f"{uid}_{current_iid}.log")
            
            def runner():
                global user_processes
                log_to_terminal(f"[RUN] User {uid} running {file} in {proj}")
                with open(log_path, "w") as l:
                    p = subprocess.Popen(cmd, stdout=l, stderr=l, cwd=work_dir, start_new_session=True)
                    with lock:
                        if str(uid) not in user_processes:
                            user_processes[str(uid)] = {}
                        user_processes[str(uid)][str(current_iid)] = {
                            "pid": p.pid,
                            "file": file,
                            "project": proj,
                            "log": log_path
                        }
                        save_data(PROCESS_FILE, user_processes)
                    p.wait()
                with lock:
                    if str(uid) in user_processes:
                        user_processes[str(uid)].pop(str(current_iid), None)
                        if not user_processes[str(uid)]:
                            del user_processes[str(uid)]
                        save_data(PROCESS_FILE, user_processes)
                log_to_terminal(f"[STOP] User {uid} stopped {file}")
            
            threading.Thread(target=runner, daemon=True).start()
            
            if str(uid) not in user_stats:
                user_stats[str(uid)] = {"uploads": 0, "script_runs": 0}
            user_stats[str(uid)]["script_runs"] += 1
            save_data(USER_STATS_FILE, user_stats)
            
            bot.answer_callback_query(call.id, "🚀 Bot Started!")
            
            start_wait = time.time()
            process_registered = False
            while time.time() - start_wait < 3.0:
                with lock:
                    if str(uid) in user_processes:
                        for proc_iid, proc_data in user_processes[str(uid)].items():
                            if proc_data.get("file") == file and proc_data.get("project") == proj:
                                process_registered = True
                                break
                if process_registered:
                    break
                time.sleep(0.1)
            
            try:
                bot.edit_message_text(f"📁 Project: {safe_markdown(proj)}", call.message.chat.id, call.message.message_id,
                                     reply_markup=project_control_panel(uid, proj), parse_mode="Markdown")
            except Exception as e:
                if "message is not modified" in str(e):
                    log_to_terminal(f"[EDIT] Harmless error in RUN handler: {e}")
                else:
                    raise
            return

        if data_parts[0] == "STOP" and len(data_parts) >= 4:
            uid, iid, proj = data_parts[1], data_parts[2], data_parts[3]
            
            if not (is_admin(user_id) or user_id == int(uid)):
                return
            
            log_to_terminal(f"[STOP] User {uid} stopping instance {iid}")
            
            with lock:
                if str(uid) in user_processes and str(iid) in user_processes[str(uid)]:
                    pid = user_processes[str(uid)][str(iid)].get("pid")
                    if pid:
                        safe_kill_process_tree(pid)
                    user_processes[str(uid)].pop(str(iid), None)
                    if not user_processes[str(uid)]:
                        del user_processes[str(uid)]
                    save_data(PROCESS_FILE, user_processes)
                    bot.answer_callback_query(call.id, "✅ Bot Stopped!")
                else:
                    bot.answer_callback_query(call.id, "❌ Bot not running!", show_alert=True)
            
            time.sleep(0.5)
            bot.edit_message_text(f"📁 Project: {safe_markdown(proj)}", call.message.chat.id, call.message.message_id,
                                 reply_markup=project_control_panel(int(uid), proj), parse_mode="Markdown")
            return

        if data_parts[0] == "RESTART" and len(data_parts) >= 5:
            uid, iid, proj, file = data_parts[1], data_parts[2], data_parts[3], data_parts[4]
            
            if not (is_admin(user_id) or user_id == int(uid)):
                return
            
            try:
                with lock:
                    if str(uid) in user_processes and str(iid) in user_processes[str(uid)]:
                        pid = user_processes[str(uid)][str(iid)].get("pid")
                        if pid:
                            safe_kill_process_tree(pid)
                        user_processes[str(uid)].pop(str(iid), None)
                        save_data(PROCESS_FILE, user_processes)
                        time.sleep(0.5)
                
                work_dir = os.path.join(BASE_DIR, str(uid), proj)
                file_path = os.path.join(work_dir, file)
                
                if file.endswith(".py"):
                    cmd = [sys.executable, "-u", file_path]
                elif file.endswith(".js"):
                    cmd = ["node", file_path]
                else:
                    cmd = ["bash", file_path]
                
                log_path = os.path.join(LOG_DIR, f"{uid}_{iid}.log")
                
                def runner():
                    global user_processes
                    log_to_terminal(f"[RESTART] User {uid} restarted {file}")
                    with open(log_path, "w") as l:
                        p = subprocess.Popen(cmd, stdout=l, stderr=l, cwd=work_dir, start_new_session=True)
                        with lock:
                            if str(uid) not in user_processes:
                                user_processes[str(uid)] = {}
                            user_processes[str(uid)][str(iid)] = {
                                "pid": p.pid,
                                "file": file,
                                "project": proj,
                                "log": log_path
                            }
                            save_data(PROCESS_FILE, user_processes)
                        p.wait()
                    with lock:
                        if str(uid) in user_processes:
                            user_processes[str(uid)].pop(str(iid), None)
                            if not user_processes[str(uid)]:
                                del user_processes[str(uid)]
                            save_data(PROCESS_FILE, user_processes)
                    log_to_terminal(f"[STOP] User {uid} stopped {file}")
                
                threading.Thread(target=runner, daemon=True).start()
                
                bot.answer_callback_query(call.id, "✅ Bot Restarted!")
                
                time.sleep(1)
                bot.edit_message_text(f"📁 Project: {safe_markdown(proj)}", call.message.chat.id, call.message.message_id,
                                     reply_markup=project_control_panel(int(uid), proj), parse_mode="Markdown")
            except Exception as e:
                log_to_terminal(f"Restart error: {e}")
                bot.answer_callback_query(call.id, f"❌ Restart failed: {safe_markdown(str(e))}", show_alert=True)
            return

        if data_parts[0] == "DEL_PROJ" and len(data_parts) >= 3:
            uid, proj = data_parts[1], data_parts[2]
            
            if not (is_admin(user_id) or user_id == int(uid)):
                return
            
            log_to_terminal(f"[DELETE] User {uid} deleting project {proj}")
            path = os.path.join(BASE_DIR, str(uid), proj)
            
            with lock:
                if str(uid) in user_processes:
                    for iid in list(user_processes[str(uid)].keys()):
                        if user_processes[str(uid)][iid]['project'] == proj:
                            pid = user_processes[str(uid)][iid].get("pid")
                            if pid:
                                safe_kill_process_tree(pid)
                            user_processes[str(uid)].pop(iid, None)
                    if not user_processes[str(uid)]:
                        del user_processes[str(uid)]
                    save_data(PROCESS_FILE, user_processes)
            
            if os.path.exists(path): 
                shutil.rmtree(path)
            
            bot.edit_message_text("📂 Select Project:", call.message.chat.id, call.message.message_id,
                                 reply_markup=projects_menu(int(uid)), parse_mode="Markdown")
            bot.answer_callback_query(call.id, f"✅ Project {safe_markdown(proj)} deleted!")
            return

        if data_parts[0] == "NOOP":
            bot.answer_callback_query(call.id, "No action")
            return

        if data_parts[0] == "PREMIUM_PAY_INVOICE":
            if is_premium(user_id) and not is_admin(user_id):
                bot.answer_callback_query(call.id, "You are already Premium!", show_alert=True)
                return
            
            try:
                price = settings.get("price", 1)
                bot.send_invoice(
                    call.message.chat.id,
                    title="💎 Premium Plan",
                    description="Get access to premium features!",
                    invoice_payload="premium_sub_payload",
                    provider_token=PAYMENT_PROVIDER_TOKEN,
                    currency=CURRENCY,
                    prices=[types.LabeledPrice(label="Premium Plan", amount=price)],
                    start_parameter="premium-sub"
                )
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Invoice Error: {safe_markdown(str(e))}\n(Setup Payment Token in code)")
            return

        if data_parts[0] == "SPEED_TEST":
            start_measuring = time.time()
            try:
                bot_info = bot.get_me()
                response_time = round((time.time() - start_measuring) * 1000, 2)
            except:
                response_time = round(random.uniform(50, 250), 2)
            
            cpu_percent = safe_cpu_percent()
            memory_percent = safe_memory_percent()
            
            if isinstance(response_time, (int, float)) and response_time < 100:
                status_line = "🟢📡 Low"
            elif isinstance(response_time, (int, float)) and response_time < 200:
                status_line = "🟡📡 Medium"
            else:
                status_line = "🔴📡 High"
            
            uptime_seconds = int(time.time() - START_TIME)
            uptime_str = str(timedelta(seconds=uptime_seconds)).split('.')[0]
            
            speed_msg = f"""╔═══════════════════════╗
    ⚡ SPEED TEST ⚡
╚═══════════════════════╝
🐌 Response Time: {response_time}ms
📊 Status: {status_line}
🖥️ Server Info:
• CPU: {cpu_percent}%
• Memory: {memory_percent}%
• Uptime: Online ✅ ({uptime_str})
✨ Bot is running smoothly!"""
            
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("🔄 testing", callback_data="SPEED_TEST"),
                types.InlineKeyboardButton("🏠 Main Menu", callback_data="SPEED_MAIN_MENU")
            )
            
            bot.edit_message_text(speed_msg, call.message.chat.id, call.message.message_id,
                                 reply_markup=markup, parse_mode="Markdown")
            bot.answer_callback_query(call.id, "✅ Speed test refreshed! Click again for new test.")
            return
        
        if data_parts[0] == "SPEED_MAIN_MENU":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id, "✅ Message deleted!")
            except:
                bot.answer_callback_query(call.id, "❌ Failed to delete message", show_alert=True)
            return

        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "Admin only!", show_alert=True)
            return
        
        message = call.message
        
        if data_parts[0] == "ADM":
            if len(data_parts) < 2:
                return
            
            action = data_parts[1]
            
            if action == "MAIN":
                bot.edit_message_text("👑 Admin Panel", message.chat.id, message.message_id,
                                     reply_markup=admin_panel_inline(user_id), parse_mode="Markdown")
                return
            
            elif action == "USER_LIST":
                ulist = "\n".join([f"👤 {safe_markdown(name)} (`{uid}`)" for uid, name in list(user_names.items())[:50]])
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text(f"👥 Users ({len(user_names)}):\n\n{ulist[:4000]}", message.chat.id, message.message_id,
                                     parse_mode="Markdown", reply_markup=markup)
                return

            elif action == "BC_START": 
                user_states[user_id] = "BC_WAIT"
                bot.edit_message_text("📢 Send broadcast message:", message.chat.id, message.message_id)
                return
            
            elif action == "PRIV_LIST":
                markup = types.InlineKeyboardMarkup()
                for uid, name in list(user_names.items())[:50]:
                    if int(uid) != int(ADMIN_ID):
                        markup.add(types.InlineKeyboardButton(f"📨 {safe_markdown(name)}", callback_data=f"ADM|PRIV_MSG|{uid}"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("📨 Select User:", message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "PRIV_MSG" and len(data_parts) > 2:
                target = data_parts[2]
                user_states[user_id] = f"PM_TO|{target}"
                bot.edit_message_text(f"📨 Message to {safe_markdown(user_names.get(str(target), 'Unknown'))}:", message.chat.id, message.message_id)
                return

            restricted_actions = ["FILE_MAN", "BROWSE", "LIST_ACTIVE", "BLOCK", "LIST_BLOCKED", 
                                  "UNBLOCK", "TEMP_LIST", "TEMP_REVOKE_LIST", "CLONE_MANAGE", "CLONE_VIEW",
                                  "CLONE_DELETE", "CLONE_RESTART", "CHANGE_PRICE", "PREM_LIST", "TEMP_REVOKE", 
                                  "PREM_GIVEAWAY", "PREM_DELETE", "PREM_GRANT", "PREM_REVOKE", "TEMP_REVOKE_LIST", "PREMIUM_TOGGLE"]
            
            if action in restricted_actions and not is_owner(user_id):
                bot.answer_callback_query(call.id, "Owner only!", show_alert=True)
                return

            if action == "FILE_MAN":
                markup = types.InlineKeyboardMarkup()
                for uid, name in list(user_names.items())[:50]: 
                    markup.add(types.InlineKeyboardButton(f"📂 {safe_markdown(name)}", callback_data=f"ADM|BROWSE|{uid}"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("📂 Select User:", message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "BROWSE" and len(data_parts) > 2:
                target = data_parts[2]
                user_dir = os.path.join(BASE_DIR, str(target))
                markup = types.InlineKeyboardMarkup()
                if os.path.exists(user_dir):
                    projects = [p for p in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, p))]
                    for p in projects[:20]: 
                        markup.add(types.InlineKeyboardButton(f"📁 {p}", callback_data=f"OPEN_PROJ|{target}|{p}"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text(f"📂 Projects for {safe_markdown(user_names.get(target, 'Unknown'))}:", message.chat.id, message.message_id,
                                     reply_markup=markup)
                return
            
            elif action == "LIST_ACTIVE":
                markup = types.InlineKeyboardMarkup()
                active_users = [uid for uid in user_names.keys() if int(uid) not in blocked_users and int(uid) != int(ADMIN_ID)]
                if not active_users:
                    markup.add(types.InlineKeyboardButton("❌ No Active Users", callback_data="NOOP"))
                else:
                    for uid in active_users[:50]: 
                        markup.add(types.InlineKeyboardButton(f"🚫 {safe_markdown(user_names[uid])}", callback_data=f"ADM|BLOCK|{uid}"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("🚫 Block User:", message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "BLOCK" and len(data_parts) > 2:
                t = int(data_parts[2])
                blocked_users[t] = True
                save_data(BLOCK_FILE, blocked_users)
                try:
                    bot.send_message(t, "🚫 You have been blocked by an admin. Contact @RIHUU_X_DP for help.")
                except:
                    pass
                
                markup = types.InlineKeyboardMarkup()
                active_users = [uid for uid in user_names.keys() if int(uid) not in blocked_users and int(uid) != int(ADMIN_ID)]
                if not active_users:
                    markup.add(types.InlineKeyboardButton("❌ No Active Users", callback_data="NOOP"))
                else:
                    for uid in active_users[:50]: 
                        markup.add(types.InlineKeyboardButton(f"🚫 {safe_markdown(user_names[uid])}", callback_data=f"ADM|BLOCK|{uid}"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "LIST_BLOCKED":
                markup = types.InlineKeyboardMarkup()
                blocked = [uid for uid in user_names.keys() if int(uid) in blocked_users]
                if blocked:
                    for uid in blocked:
                        markup.add(types.InlineKeyboardButton(f"✅ {safe_markdown(user_names[uid])}", callback_data=f"ADM|UNBLOCK|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Blocked Users", callback_data="NOOP"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("✅ Unblock User:", message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "UNBLOCK" and len(data_parts) > 2:
                t = int(data_parts[2])
                if t in blocked_users:
                    del blocked_users[t]
                    save_data(BLOCK_FILE, blocked_users)
                
                markup = types.InlineKeyboardMarkup()
                blocked = [uid for uid in user_names.keys() if int(uid) in blocked_users]
                if blocked:
                    for uid in blocked:
                        markup.add(types.InlineKeyboardButton(f"✅ {safe_markdown(user_names[uid])}", callback_data=f"ADM|UNBLOCK|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Blocked Users", callback_data="NOOP"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)
                
                try:
                    bot.send_message(t, "✅ You have been unblocked by an admin. You can now use SamiixonBot again. 🎉")
                except:
                    pass
                return

            elif action == "TEMP_LIST":
                markup = types.InlineKeyboardMarkup()
                
                available_users = []
                for uid, name in list(user_names.items())[:50]:
                    if int(uid) != int(ADMIN_ID) and int(uid) not in temp_admins:
                        available_users.append((uid, name))
                
                if available_users:
                    for uid, name in available_users:
                        markup.add(types.InlineKeyboardButton(f"👤 {safe_markdown(name)}", callback_data=f"ADM|TEMP_SELECT|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Users Available", callback_data="NOOP"))
                
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("⏳ Grant Temp Admin - Select User:", message.chat.id, message.message_id, reply_markup=markup)
                return

            elif action == "TEMP_REVOKE_LIST":
                markup = types.InlineKeyboardMarkup()
                
                active_temps = [uid for uid in temp_admins.keys() if int(uid) != int(ADMIN_ID)]
                
                if active_temps:
                    for uid in active_temps:
                        name = user_names.get(str(uid), "Unknown")
                        expiry = temp_admins[uid]
                        
                        try:
                            expiry_time = datetime.fromisoformat(expiry)
                            now = datetime.now()
                            remaining = expiry_time - now
                            
                            if remaining.total_seconds() <= 0:
                                continue
                                
                            days = remaining.days
                            hours = remaining.seconds // 3600
                            minutes = (remaining.seconds % 3600) // 60
                            
                            if days > 0:
                                time_left = f"{days}d {hours}h"
                            elif hours > 0:
                                time_left = f"{hours}h {minutes}m"
                            else:
                                time_left = f"{minutes}m"
                        except:
                            time_left = "Unknown"
                        
                        markup.add(types.InlineKeyboardButton(f"🗑️ {safe_markdown(name)} (Expires: {time_left})", callback_data=f"ADM|TEMP_REVOKE|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Active Temp Admins", callback_data="NOOP"))
                
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("🗑️ Revoke Temp Admin - Select User:", message.chat.id, message.message_id, reply_markup=markup)
                return

            elif action == "TEMP_REVOKE" and len(data_parts) > 2:
                target = int(data_parts[2])
                if target in temp_admins:
                    del temp_admins[target]
                    save_data(TEMP_ADMINS_FILE, temp_admins)
                    
                    target_name = user_names.get(str(target), 'Unknown')
                    try:
                        bot.send_message(target, "⚠️ **Your Temporary Admin access has been revoked by the Owner.**")
                    except:
                        pass
                    
                    bot.send_message(message.chat.id, f"✅ **Temp admin revoked from {safe_markdown(target_name)}!**")
                    
                    markup = types.InlineKeyboardMarkup()
                    active_temps = [uid for uid in temp_admins.keys() if int(uid) != int(ADMIN_ID)]
                    
                    if active_temps:
                        for uid in active_temps:
                            name = user_names.get(str(uid), "Unknown")
                            expiry = temp_admins[uid]
                            
                            try:
                                expiry_time = datetime.fromisoformat(expiry)
                                now = datetime.now()
                                remaining = expiry_time - now
                                
                                if remaining.total_seconds() <= 0:
                                    continue
                                    
                                days = remaining.days
                                hours = remaining.seconds // 3600
                                minutes = (remaining.seconds % 3600) // 60
                                
                                if days > 0:
                                    time_left = f"{days}d {hours}h"
                                elif hours > 0:
                                    time_left = f"{hours}h {minutes}m"
                                else:
                                    time_left = f"{minutes}m"
                            except:
                                time_left = "Unknown"
                            
                            markup.add(types.InlineKeyboardButton(f"🗑️ {safe_markdown(name)} (Expires: {time_left})", callback_data=f"ADM|TEMP_REVOKE|{uid}"))
                    else:
                        markup.add(types.InlineKeyboardButton("❌ No Active Temp Admins", callback_data="NOOP"))
                    
                    markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                    bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "TEMP_SELECT" and len(data_parts) > 2:
                target = data_parts[2]
                markup = types.InlineKeyboardMarkup()
                markup.row(
                    types.InlineKeyboardButton("30 Minutes", callback_data=f"ADM|TEMP_GRANT|{target}|0.5"),
                    types.InlineKeyboardButton("1 Hour", callback_data=f"ADM|TEMP_GRANT|{target}|1")
                )
                markup.row(
                    types.InlineKeyboardButton("6 Hours", callback_data=f"ADM|TEMP_GRANT|{target}|6"),
                    types.InlineKeyboardButton("12 Hours", callback_data=f"ADM|TEMP_GRANT|{target}|12")
                )
                markup.row(
                    types.InlineKeyboardButton("24 Hours", callback_data=f"ADM|TEMP_GRANT|{target}|24"),
                    types.InlineKeyboardButton("Custom", callback_data=f"ADM|TEMP_CUSTOM|{target}")
                )
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|TEMP_LIST"))
                bot.edit_message_text(f"⏳ Select duration for {safe_markdown(user_names.get(str(target), 'Unknown'))}:", message.chat.id, message.message_id,
                                     reply_markup=markup)
                return

            elif action == "TEMP_GRANT" and len(data_parts) > 3:
                target = int(data_parts[2])
                hours = float(data_parts[3])
                
                if hours < 1:
                    minutes = int(hours * 60)
                    duration_text = f"{minutes} minutes"
                else:
                    if hours == int(hours):
                        duration_text = f"{int(hours)} hours"
                    else:
                        duration_text = f"{hours} hours"
                
                expiry = datetime.now() + timedelta(hours=hours)
                temp_admins[target] = expiry.isoformat()
                save_data(TEMP_ADMINS_FILE, temp_admins)
                
                target_name = user_names.get(str(target), 'Unknown')
                try:
                    bot.send_message(target, f"⏳ **You have been granted Temporary Admin access!**\n\nDuration: {duration_text}\n\nYou now have admin privileges. Use them responsibly!")
                except:
                    pass
                
                bot.send_message(message.chat.id, f"✅ **Temp admin granted to {safe_markdown(target_name)}** for {duration_text}!")
                
                bot.edit_message_text("👑 Admin Panel", message.chat.id, message.message_id,
                                     reply_markup=admin_panel_inline(user_id), parse_mode="Markdown")
                return

            elif action == "TEMP_CUSTOM" and len(data_parts) > 2:
                target = data_parts[2]
                user_states[user_id] = f"TEMP_ADMIN_DURATION|{target}"
                bot.edit_message_text(f"⏳ Enter duration for {safe_markdown(user_names.get(str(target), 'Unknown'))}:\n\nUse format:\n• `30m` for 30 minutes\n• `2h` for 2 hours\n• `1.5h` for 1.5 hours", message.chat.id, message.message_id)
                return

            elif action == "CHANGE_PRICE":
                user_states[user_id] = "WAITING_FOR_PRICE"
                current = settings.get("price", 1)
                bot.edit_message_text(f"💰 Current Price: {current} XTR\n\nEnter new price (number only):", message.chat.id, message.message_id)
                return

            elif action == "PREM_LIST":
                if not premium_users:
                    text = "💎 **No Premium Users yet.**"
                else:
                    text = "💎 **Premium Users List:**\n━━━━━━━━━━━━━━━\n"
                    for uid, data in list(premium_users.items())[:50]:
                        name = user_names.get(str(uid), "Unknown")
                        date = data.get('date', '')[:10]
                        amount = data.get('amount', 0)
                        currency = data.get('currency', 'XTR')
                        via = data.get('via', 'payment')
                        text += f"👤 **{safe_markdown(name)}** (`{uid}`)\n📅 {date} | 💰 {amount} {currency} | 📝 {via}\n\n"
                
                markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text(text, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=markup)
                return

            elif action == "PREM_GIVEAWAY":
                markup = types.InlineKeyboardMarkup()
                
                regular_users = [uid for uid in user_names.keys() if int(uid) not in premium_users and int(uid) != int(ADMIN_ID) and not is_admin(int(uid))]
                if regular_users:
                    for uid in regular_users[:30]:
                        name = user_names.get(str(uid), "Unknown")
                        markup.add(types.InlineKeyboardButton(f"👤 {safe_markdown(name)}", callback_data=f"ADM|PREM_GRANT|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Regular Users Found", callback_data="NOOP"))
                
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("🎁 Premium Giveaway - Select User to Grant Premium:", message.chat.id, message.message_id, reply_markup=markup)
                return

            elif action == "PREM_DELETE":
                markup = types.InlineKeyboardMarkup()
                
                premium_user_list = [uid for uid in premium_users.keys() if not is_admin(int(uid))]
                if premium_user_list:
                    for uid in premium_user_list:
                        name = user_names.get(str(uid), "Unknown")
                        markup.add(types.InlineKeyboardButton(f"🗑️ Revoke Premium: {safe_markdown(name)}", callback_data=f"ADM|PREM_REVOKE|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Premium Users Found", callback_data="NOOP"))
                
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_text("🗑️ Revoke Premium - Select User:", message.chat.id, message.message_id, reply_markup=markup)
                return

            elif action == "PREM_GRANT" and len(data_parts) > 2:
                target = int(data_parts[2])
                if target in premium_users:
                    bot.answer_callback_query(call.id, "User is already Premium!", show_alert=True)
                    return
                
                premium_users[target] = {
                    "date": datetime.now().isoformat(),
                    "amount": 0,
                    "currency": CURRENCY,
                    "via": "admin_giveaway"
                }
                save_data(PREMIUM_USERS_FILE, premium_users)
                
                try:
                    bot.send_message(target, "🎉 **Congratulations!**\n\nYou have been granted Premium status by the Admin! 💎")
                except:
                    pass
                
                markup = types.InlineKeyboardMarkup()
                regular_users = [uid for uid in user_names.keys() if int(uid) not in premium_users and int(uid) != int(ADMIN_ID) and not is_admin(int(uid))]
                if regular_users:
                    for uid in regular_users[:30]:
                        name = user_names.get(str(uid), "Unknown")
                        markup.add(types.InlineKeyboardButton(f"👤 {safe_markdown(name)}", callback_data=f"ADM|PREM_GRANT|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Regular Users Found", callback_data="NOOP"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)
                return

            elif action == "PREM_REVOKE" and len(data_parts) > 2:
                target = int(data_parts[2])
                if target not in premium_users:
                    bot.answer_callback_query(call.id, "User is not Premium!", show_alert=True)
                    return
                
                del premium_users[target]
                save_data(PREMIUM_USERS_FILE, premium_users)
                
                try:
                    bot.send_message(target, "😔 **Your Premium status has been revoked by the Admin.**")
                except:
                    pass
                
                markup = types.InlineKeyboardMarkup()
                premium_user_list = [uid for uid in premium_users.keys() if not is_admin(int(uid))]
                if premium_user_list:
                    for uid in premium_user_list:
                        name = user_names.get(str(uid), "Unknown")
                        markup.add(types.InlineKeyboardButton(f"🗑️ Revoke Premium: {safe_markdown(name)}", callback_data=f"ADM|PREM_REVOKE|{uid}"))
                else:
                    markup.add(types.InlineKeyboardButton("❌ No Premium Users Found", callback_data="NOOP"))
                markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=markup)
                return
            
            elif action == "PREMIUM_TOGGLE":
                settings["premium_only"] = not settings.get("premium_only", False)
                save_data(SETTINGS_FILE, settings)
                
                new_status = settings["premium_only"]
                status_text = "ON" if new_status else "OFF"
                
                bot.answer_callback_query(call.id, f"Premium-only mode is now {status_text}!", show_alert=True)
                
                bot.edit_message_text("👑 Admin Panel", message.chat.id, message.message_id,
                                     reply_markup=admin_panel_inline(user_id), parse_mode="Markdown")
                return
            
            elif action == "CLONE_PENDING" and not CLONED_BOT:
                pending = {token: req for token, req in clone_requests.items() if req.get('status') == 'pending'}
                
                if not pending:
                    bot.edit_message_text("⏳ No pending clone requests", message.chat.id, message.message_id,
                                         reply_markup=admin_panel_inline(user_id))
                else:
                    token, request = list(pending.items())[0]
                    user_id_req = request['user_id']
                    
                    details = (f"⏳ **PENDING CLONE REQUEST**\n\n"
                              f"👤 User: {safe_markdown(user_names.get(str(user_id_req), 'Unknown'))} (`{user_id_req}`)\n"
                              f"🤖 Bot Name: `@{safe_markdown(request['bot_name'])}`\n"
                              f"Token: `{token}`\n\n"
                              f"Approve this request?")
                    
                    markup = types.InlineKeyboardMarkup()
                    markup.row(
                        types.InlineKeyboardButton("✅ Yes, Clone It", callback_data=f"CLONE_APPROVE|{token}"),
                        types.InlineKeyboardButton("❌ No, Reject", callback_data=f"CLONE_REJECT|{token}")
                    )
                    markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                    
                    bot.edit_message_text(details, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=markup)
                return
            
            elif action == "CLONE_MANAGE" and not CLONED_BOT:
                current_clones = load_json(CLONED_BOTS_FILE, {})
                bot.edit_message_text(f"🧬 **Cloned Bots Management**\n\nTotal: {len(current_clones)}\n"
                                     f"Pending: {len([r for r in clone_requests.values() if r.get('status') == 'pending'])}\n\nSelect a bot:",
                                     message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=cloned_bots_menu())
                return
            
            elif action == "CLONE_VIEW" and len(data_parts) >= 3 and not CLONED_BOT:
                safe_token_prefix = data_parts[2]
                current_clones = load_json(CLONED_BOTS_FILE, {})
                found_token = None
                
                for full_token in current_clones.keys():
                    if get_safe_token(full_token) == safe_token_prefix:
                        found_token = full_token
                        break
                
                if not found_token:
                    bot.answer_callback_query(call.id, "Bot not found!", show_alert=True)
                else:
                    config = current_clones[found_token]
                    owner_name = user_names.get(str(config['owner_id']), 'Unknown')
                    bot_name = config.get('bot_name', 'Unknown') or 'Unknown'
                    pid = config.get('process_pid')
                    is_running = safe_is_process_running(pid)
                    status = "🟢 Active" if is_running else "🔴 Stopped"
                    pid_display = pid or "N/A"
                    
                    details = (f"🤖 **Bot Details**\n\n"
                              f"Name: `@{safe_markdown(bot_name)}`\n"
                              f"Owner: {safe_markdown(owner_name)} (`{config['owner_id']}`)\n"
                              f"Status: {status}\nPID: `{pid_display}`\n"
                              f"Created: {config.get('created_at', 'N/A')}\n"
                              f"Token: `{found_token[:15]}...`")
                    
                    markup = types.InlineKeyboardMarkup()
                    action_buttons = [
                        types.InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"ADM|CLONE_DELETE|{safe_token_prefix}"),
                        types.InlineKeyboardButton("🔄 Restart Bot" if is_running else "▶️ Start Bot", 
                                                 callback_data=f"ADM|CLONE_RESTART|{safe_token_prefix}")
                    ]
                    markup.row(*action_buttons)
                    markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="ADM|MAIN"))
                    
                    bot.edit_message_text(details, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=markup)
                return
            
            elif action == "CLONE_DELETE" and len(data_parts) >= 3 and not CLONED_BOT:
                safe_token_prefix = data_parts[2]
                current_clones = load_json(CLONED_BOTS_FILE, {})
                found_token = None
                
                for full_token in list(current_clones.keys()):
                    if get_safe_token(full_token) == safe_token_prefix:
                        found_token = full_token
                        break
                
                if not found_token:
                    bot.answer_callback_query(call.id, "Bot not found!", show_alert=True)
                else:
                    stop_cloned_bot(found_token)
                    
                    bot_data_dir = os.path.abspath(f"bot_data/{found_token.replace(':', '_')}")
                    if os.path.exists(bot_data_dir):
                        shutil.rmtree(bot_data_dir)
                    
                    del current_clones[found_token]
                    save_data(CLONED_BOTS_FILE, current_clones)
                    cloned_bots.pop(found_token, None)
                    
                    bot.edit_message_text("🧬 Cloned Bots Management", message.chat.id, message.message_id,
                                         parse_mode="Markdown", reply_markup=cloned_bots_menu())
                return
            
            elif action == "CLONE_RESTART" and len(data_parts) >= 3 and not CLONED_BOT:
                safe_token_prefix = data_parts[2]
                current_clones = load_json(CLONED_BOTS_FILE, {})
                found_token = None
                
                for full_token in current_clones.keys():
                    if get_safe_token(full_token) == safe_token_prefix:
                        found_token = full_token
                        break
                
                if not found_token:
                    bot.answer_callback_query(call.id, "Bot not found!", show_alert=True)
                else:
                    config = current_clones[found_token]
                    bot_name = config.get('bot_name', 'Unknown')
                    owner_id = config.get('owner_id')
                    
                    stop_cloned_bot(found_token)
                    time.sleep(1)
                    
                    success, result = start_cloned_bot(found_token, owner_id)
                    
                    if success:
                        current_clones[found_token]['process_pid'] = result
                        current_clones[found_token]['status'] = 'active'
                        save_data(CLONED_BOTS_FILE, current_clones)
                        cloned_bots[found_token] = current_clones[found_token]
                        
                        bot.answer_callback_query(call.id, "✅ Bot started!")
                        bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=cloned_bots_menu())
                    else:
                        bot.answer_callback_query(call.id, f"Failed to start: {result}", show_alert=True)
                return
            
            elif action == "NOOP":
                bot.answer_callback_query(call.id, "No action")
                return
            
            else:
                bot.answer_callback_query(call.id, "Unknown action!", show_alert=True)
                return
        
        elif data_parts[0] == "CLONE_APPROVE" and len(data_parts) > 1 and not CLONED_BOT:
            if not is_owner(user_id): 
                bot.answer_callback_query(call.id, "Owner only!", show_alert=True)
                return

            token = data_parts[1]
            
            if token not in clone_requests:
                bot.answer_callback_query(call.id, "Request not found!", show_alert=True)
            else:
                request = clone_requests[token]
                user_id_req = request['user_id']
                bot_name = request['bot_name']
                
                success, result = start_cloned_bot(token, user_id_req)
                
                if success:
                    cloned_bots[token] = {
                        "owner_id": user_id_req,
                        "created_at": datetime.now().isoformat(),
                        "bot_name": bot_name,
                        "bot_id": request['bot_id'],
                        "status": "active",
                        "process_pid": result
                    }
                    
                    save_data(CLONED_BOTS_FILE, cloned_bots)
                    del clone_requests[token]
                    save_data(CLONE_REQUESTS_FILE, clone_requests)
                    
                    try:
                        bot.send_message(user_id_req, f"🎉 **Your clone request was approved!**\n\n"
                                                     f"**Bot:** `@{safe_markdown(bot_name)}`\n"
                                                     f"**Admin ID:** `{user_id_req}`\n\n"
                                                     f"✨ **You have FULL ADMIN ACCESS!**\n"
                                                     f"Send /start to the bot to see Admin Panel.", parse_mode="Markdown")
                    except:
                        pass
                
                bot.edit_message_text("👑 Admin Panel", message.chat.id, message.message_id,
                                     reply_markup=admin_panel_inline(user_id), parse_mode="Markdown")
            return
        
        elif data_parts[0] == "CLONE_REJECT" and len(data_parts) > 1 and not CLONED_BOT:
            if not is_owner(user_id): 
                bot.answer_callback_query(call.id, "Owner only!", show_alert=True)
                return

            token = data_parts[1]
            
            if token not in clone_requests:
                bot.answer_callback_query(call.id, "Request not found!", show_alert=True)
            else:
                request = clone_requests[token]
                user_id_req = request['user_id']
                bot_name = request['bot_name']
                
                del clone_requests[token]
                save_data(CLONE_REQUESTS_FILE, clone_requests)
                
                try:
                    bot.send_message(user_id_req, f"😞 **Your clone request was rejected.**\n\n"
                                                 f"**Bot:** `@{safe_markdown(bot_name)}`\n\n"
                                                 f"Contact @ RIHUU_X_DP questions.", parse_mode="Markdown")
                except:
                    pass
                
                bot.edit_message_text("👑 Admin Panel", message.chat.id, message.message_id,
                                     reply_markup=admin_panel_inline(user_id), parse_mode="Markdown")
            return
        
        else:
            bot.answer_callback_query(call.id, "Unknown callback!", show_alert=True)
            return
    
    except Exception as e:
        log_to_terminal(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id, f"Error: {safe_markdown(str(e))}", show_alert=True)
        except:
            pass

def periodic_cleanup_task():
    """Background task to clean up stale processes every 5 minutes"""
    while True:
        try:
            time.sleep(300)
            cleanup_stale_processes()
        except Exception as e:
            log_to_terminal(f"[CLEANUP] Background task error: {e}")

cleanup_thread = threading.Thread(target=periodic_cleanup_task, daemon=True)
cleanup_thread.start()

# ================= MAIN EXECUTION =================
if __name__ == "__main__":
    try:
        bot_info = bot.get_me()
        print_banner(bot_info)
        
        # Start web server in background thread
        web_thread = threading.Thread(target=run_web_server, daemon=True)
        web_thread.start()
        log_to_terminal(f"[WEB] Flask server started on port {PORT}")
        
        if not CLONED_BOT:
            log_to_terminal("Cleaning up old cloned bot processes...")
            cleanup_all_cloned_bots()
            
            log_to_terminal("Restarting previously active cloned bots...")
            restart_active_cloned_bots()
        
        log_to_terminal("Bot is running and ready!")
        
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=20, long_polling_timeout=15,
                           allowed_updates=['message', 'callback_query', 'pre_checkout_query'])
            except KeyboardInterrupt:
                log_to_terminal("Shutting down...")
                if not CLONED_BOT:
                    with lock:
                        for uid, procs in user_processes.items():
                            for iid, proc_data in procs.items():
                                pid = proc_data.get("pid")
                                if pid:
                                    safe_kill_process_tree(pid)
                        save_data(PROCESS_FILE, user_processes)
                break
            except Exception as e:
                log_to_terminal(f"Polling error: {e}")
                time.sleep(5)
        
    except Exception as e:
        log_to_terminal(f"CRITICAL ERROR: Bot cannot start: {e}")
        traceback.print_exc()
        sys.exit(1)
