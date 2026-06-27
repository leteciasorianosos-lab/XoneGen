import os
import sys
import json
import random
import asyncio
import logging
import platform
import psutil
import time
import re
import zipfile
import io
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# === CONFIGURATION ===
TOKEN = os.getenv("TELEGRAM_TOKEN", "8814382996:AAF69aEUOrSQ4uvGQBGDiHXCk_795j9Qyx4")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7058453451"))
KEYS_FILE = "keys.json"
DATABASE_FILES = ["db.txt"]
USED_ACCOUNTS_FILE = "used_accounts.txt"
LINES_TO_SEND = 1000
BOT_USERNAME = "XoneBot Checker"
MAX_KEYS_PER_GENERATION = 20
MAX_ACCOUNTS_PER_USER = 1000  # Daily limit per user
MAX_PREMIUM_ACCOUNTS = 5000   # Daily limit for premium users
REQUEST_COOLDOWN = 30  # Seconds between requests
PREMIUM_COOLDOWN = 10  # Seconds between requests for premium users
MAX_LOG_ENTRIES = 1000  # Maximum log entries to keep
URL_PATTERN = re.compile(
    r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
    re.IGNORECASE
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ENHANCED DOMAIN LIST ===
DOMAINS = [
    # Gaming
    "Steam", "Origin", "EpicGames", "Uplay", "Battle.net", "Rockstar", 
    "GOG", "Xbox", "PlayStation", "Nintendo", "Roblox", "Garena",
    "PUBG", "FreeFire", "MobileLegends", "CallOfDuty", "Valorant",
    "Fortnite", "ApexLegends", "Minecraft", "LeagueOfLegends", "Dota2",
    
    # Streaming
    "Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
    "Apple TV", "Spotify", "YouTube Premium", "Deezer", "Tidal",
    "Crunchyroll", "Funimation", "Twitch", "Patreon", "Viu",
    
    # Social Media
    "Facebook", "Instagram", "Twitter", "TikTok", "Snapchat",
    "Pinterest", "Reddit", "LinkedIn", "Discord", "Telegram",
    "WhatsApp", "WeChat", "Line", "Viber", "Signal", "capcut",
    
    # VPN & Security
    "NordVPN", "ExpressVPN", "Surfshark", "CyberGhost", "ProtonVPN",
    "IPVanish", "Hotspot Shield", "Private Internet Access", "TunnelBear", "Windscribe",
    
    # Education
    "Coursera", "Udemy", "Skillshare", "MasterClass", "Brilliant",
    "Duolingo", "Babbel", "Rosetta Stone", "Khan Academy", "Codecademy",
    
    # Productivity
    "Microsoft 365", "Google Workspace", "Dropbox", "Evernote", "Notion",
    "Todoist", "Trello", "Asana", "Slack", "Zoom",
    
    # Others
    "Adobe Creative Cloud", "Canva Pro", "Figma", "Autodesk", "Grammarly",
    "LastPass", "1Password", "Dashlane", "Bitwarden", "Malwarebytes"
]

# Premium domains (require higher privileges)
PREMIUM_DOMAINS = [
    # Gaming
    "Steam", "Origin", "EpicGames", "Battle.net", "Rockstar",
    
    # Streaming
    "Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
    "Apple TV", "Spotify", "YouTube Premium", "Tidal",
    
    # VPN & Security
    "NordVPN", "ExpressVPN", "Surfshark", "ProtonVPN",
    
    # Education
    "MasterClass", "Brilliant", "Rosetta Stone",
    
    # Productivity
    "Microsoft 365", "Google Workspace", "Adobe Creative Cloud"
]

# === DATA MODELS ===
class KeyData:
    def __init__(self):
        self.keys: Dict[str, Optional[float]] = {}  # key: expiry_timestamp
        self.user_keys: Dict[str, Optional[float]] = {}  # user_id: expiry_timestamp
        self.user_stats: Dict[str, Dict[str, int]] = {}  # user_id: {"today": count, "date": YYYY-MM-DD}
        self.global_stats: Dict[str, int] = {"generated": 0, "keys_created": 0}
        self.logs: List[str] = []
        self.user_last_request: Dict[str, float] = {}  # user_id: last_request_timestamp
        self.premium_users: Set[str] = set()  # Users with premium access
        self.banned_users: Set[str] = set()  # Banned users
        self.user_notes: Dict[str, str] = {}  # User notes for admins

    def to_dict(self):
        return {
            "keys": self.keys,
            "user_keys": self.user_keys,
            "user_stats": self.user_stats,
            "global_stats": self.global_stats,
            "logs": self.logs[-MAX_LOG_ENTRIES:],  # Keep only recent logs
            "user_last_request": self.user_last_request,
            "premium_users": list(self.premium_users),
            "banned_users": list(self.banned_users),
            "user_notes": self.user_notes
        }

    @classmethod
    def from_dict(cls, data: dict):
        instance = cls()
        instance.keys = data.get("keys", {})
        instance.user_keys = data.get("user_keys", {})
        instance.user_stats = data.get("user_stats", {})
        instance.global_stats = data.get("global_stats", {"generated": 0, "keys_created": 0})
        instance.logs = data.get("logs", [])
        instance.user_last_request = data.get("user_last_request", {})
        instance.premium_users = set(data.get("premium_users", []))
        instance.banned_users = set(data.get("banned_users", []))
        instance.user_notes = data.get("user_notes", {})
        return instance

# === DATA MANAGEMENT ===
def load_keys() -> KeyData:
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                return KeyData.from_dict(json.load(f))
        except Exception as e:
            logger.error(f"Error loading keys: {e}")
            return KeyData()
    return KeyData()

def save_keys(data: KeyData):
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving keys: {e}")

keys_data = load_keys()

# === UTILITY FUNCTIONS ===
def generate_random_key(length: int = 16) -> str:
    """Generate a random alphanumeric key"""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "PREMIUM-" + ''.join(random.choices(chars, k=length))

def get_expiry_time(duration: str) -> Optional[float]:
    """Convert duration string to expiry timestamp"""
    now = datetime.now()
    duration_map = {
        "1m": 60, "5m": 300, "15m": 900,
        "1h": 3600, "6h": 21600, "12h": 43200,
        "1d": 86400, "3d": 259200, "7d": 604800,
        "14d": 1209600, "30d": 2592000
    }
    if duration == "lifetime":
        return None
    if duration in duration_map:
        return (now + timedelta(seconds=duration_map[duration])).timestamp()
    return None

def format_time(seconds: float) -> str:
    """Convert seconds to human-readable time"""
    periods = [
        ('day', 86400),
        ('hour', 3600),
        ('minute', 60),
        ('second', 1)
    ]
    result = []
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            if period_value > 0:
                result.append(f"{int(period_value)} {period_name}{'s' if period_value != 1 else ''}")
    return ', '.join(result) if result else "0 seconds"

def remove_urls(text: str) -> str:
    """Remove URLs from text"""
    return URL_PATTERN.sub('', text)

async def send_large_message(update: Update, text: str, max_length: int = 4000):
    """Split large messages into chunks"""
    try:
        for i in range(0, len(text), max_length):
            if update.callback_query:
                await update.callback_query.message.reply_text(text[i:i+max_length], parse_mode="Markdown")
            else:
                await update.message.reply_text(text[i:i+max_length], parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending large message: {e}")

def get_used_accounts() -> Set[str]:
    """Load used accounts from file"""
    try:
        with open(USED_ACCOUNTS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()
    except Exception as e:
        logger.error(f"Error loading used accounts: {e}")
        return set()

def save_used_accounts(accounts: Set[str]):
    """Save used accounts to file"""
    try:
        with open(USED_ACCOUNTS_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write("\n".join(accounts) + "\n")
    except Exception as e:
        logger.error(f"Error saving used accounts: {e}")

def update_user_stats(user_id: str, count: int):
    """Update user statistics with daily limits"""
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id not in keys_data.user_stats:
        keys_data.user_stats[user_id] = {"date": today, "today": 0}
    
    if keys_data.user_stats[user_id]["date"] != today:
        keys_data.user_stats[user_id] = {"date": today, "today": 0}
    
    keys_data.user_stats[user_id]["today"] += count
    keys_data.global_stats["generated"] += count

def check_user_limit(user_id: str) -> bool:
    """Check if user has exceeded daily limit"""
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id not in keys_data.user_stats:
        return False
    if keys_data.user_stats[user_id]["date"] != today:
        return False
    
    max_limit = MAX_PREMIUM_ACCOUNTS if is_premium_user(user_id) else MAX_ACCOUNTS_PER_USER
    return keys_data.user_stats[user_id]["today"] >= max_limit

def check_cooldown(user_id: str) -> Optional[float]:
    """Check if user is on cooldown and return remaining time if true"""
    last_request = keys_data.user_last_request.get(user_id, 0)
    current_time = datetime.now().timestamp()
    elapsed = current_time - last_request
    
    cooldown = PREMIUM_COOLDOWN if is_premium_user(user_id) else REQUEST_COOLDOWN
    if elapsed < cooldown:
        return cooldown - elapsed
    return None

def update_last_request(user_id: str):
    """Update the last request time for a user"""
    keys_data.user_last_request[user_id] = datetime.now().timestamp()

def is_premium_user(user_id: str) -> bool:
    """Check if user has premium status"""
    return user_id in keys_data.premium_users

def is_premium_domain(domain: str) -> bool:
    """Check if domain requires premium access"""
    return domain.lower() in [d.lower() for d in PREMIUM_DOMAINS]

def is_valid_key(user_id: str) -> bool:
    """Check if user has a valid key"""
    if user_id in keys_data.premium_users:
        return True
    
    if user_id not in keys_data.user_keys:
        return False
    
    expiry = keys_data.user_keys[user_id]
    if expiry is None:  # Lifetime key
        return True
    
    if datetime.now().timestamp() > expiry:
        del keys_data.user_keys[user_id]
        save_keys(keys_data)
        return False
    
    return True

def is_banned(user_id: str) -> bool:
    """Check if user is banned"""
    return user_id in keys_data.banned_users

# === COMMAND HANDLERS ===
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the enhanced main menu with better keyboard layout"""
    try:
        user_id = str(update.effective_user.id)
        
        if is_banned(user_id):
            await update.message.reply_text("🚫 You are banned from using this bot!")
            return
        
        keyboard = [
            [
                InlineKeyboardButton("🎮 Generate Accounts", callback_data="main_generate"),
                InlineKeyboardButton("💎 Premium Features", callback_data="main_premium")
            ],
            [
                InlineKeyboardButton("📊 Account Stats", callback_data="main_stats"),
                InlineKeyboardButton("🌐 Domain List", callback_data="main_domains")
            ],
            [
                InlineKeyboardButton("ℹ️ Bot Info", callback_data="main_info"),
                InlineKeyboardButton("🆘 Help Center", callback_data="main_help")
            ],
            [
                InlineKeyboardButton("📞 Contact Admin", callback_data="main_contact"),
                InlineKeyboardButton("🔑 Redeem Key", callback_data="main_redeem")
            ]
        ]
        
        if str(update.effective_user.id) == str(ADMIN_ID):
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="main_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_message = (
            "🌟 *Welcome to Premium Account Generator* 🌟\n\n"
            "🔹 Generate premium accounts for various platforms\n"
            "🔹 Daily limits based on your subscription\n"
            "🔹 Fast and reliable service\n\n"
            "Select an option below to get started:"
        )
        
        if update.message:
            await update.message.reply_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        elif update.callback_query:
            await update.callback_query.message.edit_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def check_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user's daily usage with enhanced formatting"""
    try:
        user_id = str(update.effective_user.id)
        
        if is_banned(user_id):
            await update.message.reply_text("🚫 You are banned from using this bot!")
            return
        
        today = datetime.now().strftime("%Y-%m-%d")
        if user_id not in keys_data.user_stats or keys_data.user_stats[user_id]["date"] != today:
            usage = 0
        else:
            usage = keys_data.user_stats[user_id]["today"]
        
        max_limit = MAX_PREMIUM_ACCOUNTS if is_premium_user(user_id) else MAX_ACCOUNTS_PER_USER
        remaining = max(0, max_limit - usage)
        
        expiry = keys_data.user_keys.get(user_id, None)
        expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
        
        # Create a progress bar
        progress = min(usage / max_limit, 1.0)
        progress_bar = "[" + "■" * int(progress * 20) + "□" * (20 - int(progress * 20)) + "]"
        
        response = (
            f"📊 *Your Usage Stats*\n\n"
            f"{progress_bar} {int(progress * 100)}%\n\n"
            f"🔸 *Used today:* `{usage}/{max_limit}` accounts\n"
            f"🔸 *Remaining:* `{remaining}` accounts\n"
            f"⏳ *Key expires:* `{expiry_text}`\n\n"
        )
        
        if is_premium_user(user_id):
            response += "🌟 *Premium Benefits Active:*\n- Higher limits\n- Faster generation\n- Premium domains"
        else:
            response += "💡 *Tip:* Upgrade to premium for higher limits and exclusive domains!"
        
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in check_usage: {e}")
        await update.message.reply_text("❌ An error occurred while checking your usage.")

async def list_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available domains with categorized display"""
    try:
        user_id = str(update.effective_user.id)
        
        if is_banned(user_id):
            await update.message.reply_text("🚫 You are banned from using this bot!")
            return
        
        # Categorize domains
        categories = {
            "🎮 Gaming": [],
            "🎬 Streaming": [],
            "📱 Social Media": [],
            "🔒 VPN & Security": [],
            "📚 Education": [],
            "💼 Productivity": [],
            "🎨 Creative": []
        }
        
        for domain in DOMAINS:
            if domain in ["Steam", "Origin", "EpicGames", "Uplay", "Battle.net", "Rockstar", 
                         "GOG", "Xbox", "PlayStation", "Nintendo", "Roblox", "Garena",
                         "PUBG", "FreeFire", "MobileLegends", "CallOfDuty", "Valorant",
                         "Fortnite", "ApexLegends", "Minecraft", "LeagueOfLegends", "Dota2"]:
                categories["🎮 Gaming"].append(domain)
            elif domain in ["Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
                           "Apple TV", "Spotify", "YouTube Premium", "Deezer", "Tidal",
                           "Crunchyroll", "Funimation", "Twitch", "Patreon", "Viu"]:
                categories["🎬 Streaming"].append(domain)
            elif domain in ["Facebook", "Instagram", "Twitter", "TikTok", "Snapchat",
                           "Pinterest", "Reddit", "LinkedIn", "Discord", "Telegram",
                           "WhatsApp", "WeChat", "Line", "Viber", "Signal"]:
                categories["📱 Social Media"].append(domain)
            elif domain in ["NordVPN", "ExpressVPN", "Surfshark", "CyberGhost", "ProtonVPN",
                           "IPVanish", "Hotspot Shield", "Private Internet Access", "TunnelBear", "Windscribe"]:
                categories["🔒 VPN & Security"].append(domain)
            elif domain in ["Coursera", "Udemy", "Skillshare", "MasterClass", "Brilliant",
                           "Duolingo", "Babbel", "Rosetta Stone", "Khan Academy", "Codecademy"]:
                categories["📚 Education"].append(domain)
            elif domain in ["Microsoft 365", "Google Workspace", "Dropbox", "Evernote", "Notion",
                            "Todoist", "Trello", "Asana", "Slack", "Zoom"]:
                categories["💼 Productivity"].append(domain)
            else:
                categories["🎨 Creative"].append(domain)
        
        response = "🌐 *Available Domains by Category*\n\n"
        
        for category, domains in categories.items():
            if domains:
                response += f"{category}:\n"
                for domain in sorted(domains):
                    if is_premium_domain(domain):
                        response += f"✨ *{domain}* (Premium)\n"
                    else:
                        response += f"🔹 {domain}\n"
                response += "\n"
        
        response += (
            "\n✨ = Premium domain (requires premium access)\n"
            "Use /generate to select a domain"
        )
        
        await send_large_message(update, response)
    except Exception as e:
        logger.error(f"Error in list_domains: {e}")
        await update.message.reply_text("❌ An error occurred while listing domains.")

async def generate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced domain selection menu with categorized keyboards"""
    try:
        if update.message:
            user_id = str(update.message.from_user.id)
            chat_id = str(update.message.chat_id)
            message = update.message
        elif update.callback_query:
            user_id = str(update.callback_query.from_user.id)
            chat_id = str(update.callback_query.message.chat_id)
            message = update.callback_query.message
            await update.callback_query.answer()
        else:
            return
        
        if is_banned(user_id):
            await message.reply_text("🚫 You are banned from using this bot!")
            return
        
        if not is_valid_key(chat_id):
            return await message.reply_text(
                "🔒 *Premium Access Required*\n\n"
                "You need a valid key to use this feature!\n"
                "Get a key from the admin or use /key to redeem one.",
                parse_mode="Markdown"
            )

        # Create categorized keyboards
        categories = {
            "🎮 Gaming": [],
            "🎬 Streaming": [],
            "📱 Social": [],
            "🔒 VPN": [],
            "📚 Education": [],
            "💼 Productivity": []
        }
        
        for domain in DOMAINS:
            if domain in ["Steam", "Origin", "EpicGames", "Uplay", "Battle.net", "Rockstar", 
                         "GOG", "Xbox", "PlayStation", "Nintendo", "Roblox", "Garena",
                         "PUBG", "FreeFire", "MobileLegends", "CallOfDuty", "Valorant",
                         "Fortnite", "ApexLegends", "Minecraft", "LeagueOfLegends", "Dota2"]:
                categories["🎮 Gaming"].append(domain)
            elif domain in ["Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
                           "Apple TV", "Spotify", "YouTube Premium", "Deezer", "Tidal",
                           "Crunchyroll", "Funimation", "Twitch", "Patreon", "Viu"]:
                categories["🎬 Streaming"].append(domain)
            elif domain in ["Facebook", "Instagram", "Twitter", "TikTok", "Snapchat",
                           "Pinterest", "Reddit", "LinkedIn", "Discord", "Telegram",
                           "WhatsApp", "WeChat", "Line", "Viber", "Signal"]:
                categories["📱 Social"].append(domain)
            elif domain in ["NordVPN", "ExpressVPN", "Surfshark", "CyberGhost", "ProtonVPN",
                           "IPVanish", "Hotspot Shield", "Private Internet Access", "TunnelBear", "Windscribe"]:
                categories["🔒 VPN"].append(domain)
            elif domain in ["Coursera", "Udemy", "Skillshare", "MasterClass", "Brilliant",
                           "Duolingo", "Babbel", "Rosetta Stone", "Khan Academy", "Codecademy"]:
                categories["📚 Education"].append(domain)
            elif domain in ["Microsoft 365", "Google Workspace", "Dropbox", "Evernote", "Notion",
                            "Todoist", "Trello", "Asana", "Slack", "Zoom"]:
                categories["💼 Productivity"].append(domain)
        
        # Create inline keyboard with category buttons
        keyboard = []
        for category in categories:
            if categories[category]:  # Only add category if it has domains
                keyboard.append([InlineKeyboardButton(category, callback_data=f"category_{category[2:]}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await message.edit_text(
                "🛠 *Select a Category to Generate Accounts* 🛠\n\n"
                "✨ = Premium domain (requires premium key)\n"
                "Browse through categories to find your desired platform:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await message.reply_text(
                "🛠 *Select a Category to Generate Accounts* 🛠\n\n"
                "✨ = Premium domain (requires premium key)\n"
                "Browse through categories to find your desired platform:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in generate_menu: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def show_category_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show domains for a specific category"""
    try:
        query = update.callback_query
        await query.answer()
        
        category = query.data.replace("category_", "")
        full_category = ""
        
        # Map back to full category name with emoji
        if category == "Gaming":
            full_category = "🎮 Gaming"
        elif category == "Streaming":
            full_category = "🎬 Streaming"
        elif category == "Social":
            full_category = "📱 Social"
        elif category == "VPN":
            full_category = "🔒 VPN"
        elif category == "Education":
            full_category = "📚 Education"
        elif category == "Productivity":
            full_category = "💼 Productivity"
        
        # Get domains for this category
        domains = []
        for domain in DOMAINS:
            if domain in ["Steam", "Origin", "EpicGames", "Uplay", "Battle.net", "Rockstar", 
                         "GOG", "Xbox", "PlayStation", "Nintendo", "Roblox", "Garena",
                         "PUBG", "FreeFire", "MobileLegends", "CallOfDuty", "Valorant",
                         "Fortnite", "ApexLegends", "Minecraft", "LeagueOfLegends", "Dota2"] and category == "Gaming":
                domains.append(domain)
            elif domain in ["Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
                           "Apple TV", "Spotify", "YouTube Premium", "Deezer", "Tidal",
                           "Crunchyroll", "Funimation", "Twitch", "Patreon", "Viu"] and category == "Streaming":
                domains.append(domain)
            elif domain in ["Facebook", "Instagram", "Twitter", "TikTok", "Snapchat",
                           "Pinterest", "Reddit", "LinkedIn", "Discord", "Telegram",
                           "WhatsApp", "WeChat", "Line", "Viber", "Signal"] and category == "Social":
                domains.append(domain)
            elif domain in ["NordVPN", "ExpressVPN", "Surfshark", "CyberGhost", "ProtonVPN",
                           "IPVanish", "Hotspot Shield", "Private Internet Access", "TunnelBear", "Windscribe"] and category == "VPN":
                domains.append(domain)
            elif domain in ["Coursera", "Udemy", "Skillshare", "MasterClass", "Brilliant",
                           "Duolingo", "Babbel", "Rosetta Stone", "Khan Academy", "Codecademy"] and category == "Education":
                domains.append(domain)
            elif domain in ["Microsoft 365", "Google Workspace", "Dropbox", "Evernote", "Notion",
                            "Todoist", "Trello", "Asana", "Slack", "Zoom"] and category == "Productivity":
                domains.append(domain)
        
        # Create keyboard with domains (3 per row)
        keyboard = []
        row = []
        for i, domain in enumerate(sorted(domains)):
            emoji = "✨" if is_premium_domain(domain) else "🔹"
            row.append(InlineKeyboardButton(f"{emoji} {domain}", callback_data=f"generate_{domain}"))
            if (i + 1) % 3 == 0:
                keyboard.append(row)
                row = []
        if row:  # Add remaining buttons if any
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="main_generate")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            f"🛠 *{full_category} Domains*\n\n"
            "Select a domain to generate accounts:\n"
            "✨ = Premium domain (requires premium key)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in show_category_domains: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def generate_filtered_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send accounts for selected domain"""
    try:
        query = update.callback_query
        await query.answer()
        
        chat_id = str(query.message.chat_id)
        user_id = str(query.from_user.id)
        
        if is_banned(user_id):
            await query.message.reply_text("🚫 You are banned from using this bot!")
            return
        
        cooldown = check_cooldown(user_id)
        if cooldown:
            return await query.message.reply_text(
                f"⏳ Please wait {format_time(cooldown)} before making another request."
            )
        
        if not is_valid_key(chat_id):
            return await query.message.reply_text("🚨 You need a valid key to use this feature!")

        if check_user_limit(chat_id):
            return await query.message.reply_text(
                "⚠️ You've reached your daily limit of accounts!\n"
                "Try again tomorrow or contact admin for premium access."
            )

        selected_domain = query.data.replace("generate_", "")
        
        if is_premium_domain(selected_domain) and not is_premium_user(user_id):
            return await query.message.reply_text(
                "🔒 This is a premium domain!\n"
                "You need a premium account to generate these accounts.\n\n"
                "Use /premium to learn more."
            )

        processing_msg = await query.message.reply_text("⚡ **Processing... Please wait 2-5 seconds.**")
        update_last_request(user_id)

        used_accounts = get_used_accounts()
        matched_lines = []
        
        for db_file in DATABASE_FILES:
            if len(matched_lines) >= LINES_TO_SEND:
                break
            
            try:
                with open(db_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        stripped_line = line.strip()
                        if (selected_domain.lower() in stripped_line.lower() and 
                            stripped_line not in used_accounts and 
                            len(stripped_line.split(":")) >= 2):
                            cleaned_line = remove_urls(stripped_line)
                            if cleaned_line:
                                matched_lines.append(cleaned_line)
                            if len(matched_lines) >= LINES_TO_SEND:
                                break
            except Exception as e:
                logger.error(f"Error reading {db_file}: {e}")
                continue

        if not matched_lines:
            await processing_msg.delete()
            return await query.message.reply_text(f"❌ No accounts found for {selected_domain}. Try another domain.")

        save_used_accounts(set(matched_lines))
        update_user_stats(chat_id, len(matched_lines))
        save_keys(keys_data)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"PREMIUM_{selected_domain}_{timestamp}.txt"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"🔥 Premium Accounts Generator\n")
            f.write(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"🔍 Domain: {selected_domain}\n")
            f.write(f"📦 Accounts: {len(matched_lines)}\n\n")
            f.write("\n".join(matched_lines))

        await asyncio.sleep(2)  # Simulate processing time

        expiry = keys_data.user_keys.get(chat_id, None)
        expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
        
        max_limit = MAX_PREMIUM_ACCOUNTS if is_premium_user(user_id) else MAX_ACCOUNTS_PER_USER
        caption = (
            f"✅ *{selected_domain.upper()} Accounts Generated!*\n"
            f"📦 *Count:* `{len(matched_lines)}`\n"
            f"⏳ *Key Expires:* `{expiry_text}`\n"
            f"📊 *Daily Usage:* `{keys_data.user_stats.get(chat_id, {}).get('today', 0)}/{max_limit}`\n\n"
            f"💡 *Tip:* Use accounts quickly as they may become invalid over time."
        )
        
        await processing_msg.delete()
        with open(filename, "rb") as f:
            await query.message.reply_document(
                document=InputFile(f, filename=filename),
                caption=caption,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in generate_filtered_accounts: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("❌ An error occurred while generating accounts. Please try again.")
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                logger.error(f"Error deleting temp file: {e}")

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced premium features menu"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = str(query.from_user.id)
        is_premium = is_premium_user(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("💎 Premium Domains", callback_data="premium_domains"),
                InlineKeyboardButton("⚡ Speed Benefits", callback_data="premium_speed")
            ],
            [
                InlineKeyboardButton("📈 Higher Limits", callback_data="premium_limits"),
                InlineKeyboardButton("🛡️ Premium Support", callback_data="premium_support")
            ],
            [
                InlineKeyboardButton("🛒 Get Premium", callback_data="premium_buy")
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")
            ]
        ]
        
        if is_premium:
            status_text = "🌟 *You are a Premium User!* 🌟"
        else:
            status_text = "🔹 *Premium Status: Not Active*"
        
        await query.message.edit_text(
            f"🎁 *Premium Features* 🎁\n\n"
            f"{status_text}\n\n"
            "✨ *Benefits of Premium Membership:*\n"
            "- Access to exclusive premium domains\n"
            "- Faster generation times (2-5 seconds)\n"
            f"- Higher daily limits ({MAX_PREMIUM_ACCOUNTS} accounts/day)\n"
            "- Priority customer support\n"
            "- Early access to new features\n\n"
            "Select an option to learn more:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in premium_menu: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_premium_domains_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium domains information with better formatting"""
    try:
        query = update.callback_query
        await query.answer()
        
        domains_text = "💎 *Premium Domains*\n\n"
        domains_text += "✨ *Gaming:*\n"
        domains_text += ", ".join(d for d in PREMIUM_DOMAINS if d in ["Steam", "Origin", "EpicGames", "Battle.net", "Rockstar"]) + "\n\n"
        
        domains_text += "✨ *Streaming:*\n"
        domains_text += ", ".join(d for d in PREMIUM_DOMAINS if d in ["Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
                                                                     "Apple TV", "Spotify", "YouTube Premium", "Tidal"]) + "\n\n"
        
        domains_text += "✨ *VPN & Security:*\n"
        domains_text += ", ".join(d for d in PREMIUM_DOMAINS if d in ["NordVPN", "ExpressVPN", "Surfshark", "ProtonVPN"]) + "\n\n"
        
        domains_text += "✨ *Education:*\n"
        domains_text += ", ".join(d for d in PREMIUM_DOMAINS if d in ["MasterClass", "Brilliant", "Rosetta Stone"]) + "\n\n"
        
        domains_text += "✨ *Productivity:*\n"
        domains_text += ", ".join(d for d in PREMIUM_DOMAINS if d in ["Microsoft 365", "Google Workspace", "Adobe Creative Cloud"]) + "\n\n"
        
        domains_text += "These domains require a premium account to generate."
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Premium Menu", callback_data="main_premium")]
        ]
        
        await query.message.edit_text(
            domains_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_premium_domains_info: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_premium_speed_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium speed benefits with comparison table"""
    try:
        query = update.callback_query
        await query.answer()
        
        speed_text = (
            "⚡ *Premium Speed Benefits*\n\n"
            "🚀 *Generation Speed Comparison*\n"
            "```\n"
            "+----------------+-------------------+-----------------+\n"
            "| Feature        | Regular Users     | Premium Users   |\n"
            "+----------------+-------------------+-----------------+\n"
            f"| Generation Time| 5-10 seconds      | 2-5 seconds     |\n"
            f"| Cooldown       | {REQUEST_COOLDOWN}s           | {PREMIUM_COOLDOWN}s           |\n"
            "| Queue Priority | Standard          | High            |\n"
            "+----------------+-------------------+-----------------+\n"
            "```\n\n"
            "This means you can generate accounts much faster when you need them!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Premium Menu", callback_data="main_premium")]
        ]
        
        await query.message.edit_text(
            speed_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_premium_speed_info: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_premium_limits_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium limits with visual comparison"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Create visual comparison
        regular_bar = "[" + "■" * 5 + "□" * 15 + "]"
        premium_bar = "[" + "■" * 15 + "□" * 5 + "]"
        
        limits_text = (
            "📈 *Premium Limits Benefits*\n\n"
            "Premium users enjoy significantly higher daily limits:\n\n"
            f"🔹 *Regular Users:* {MAX_ACCOUNTS_PER_USER} accounts/day\n"
            f"{regular_bar}\n\n"
            f"🌟 *Premium Users:* {MAX_PREMIUM_ACCOUNTS} accounts/day\n"
            f"{premium_bar}\n\n"
            "That's 5x more accounts per day for premium members!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Premium Menu", callback_data="main_premium")]
        ]
        
        await query.message.edit_text(
            limits_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_premium_limits_info: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_premium_support_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium support information"""
    try:
        query = update.callback_query
        await query.answer()
        
        support_text = (
            "🛡️ *Premium Support*\n\n"
            "As a premium user, you get exclusive access to:\n\n"
            "🔹 *Priority Support* - Your requests are handled first\n"
            "🔹 *Dedicated Channel* - Direct line to our support team\n"
            "🔹 *Faster Response* - Typically within 1-2 hours\n"
            "🔹 *Extended Help* - We'll go the extra mile for you\n\n"
            "Premium users also get personalized assistance with any issues."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Premium Menu", callback_data="main_premium")]
        ]
        
        await query.message.edit_text(
            support_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_premium_support_info: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_premium_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle premium purchase with options"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = str(query.from_user.id)
        is_premium = is_premium_user(user_id)
        
        if is_premium:
            status_text = "🌟 *You already have premium access!* 🌟"
        else:
            status_text = "🔹 *Premium Status: Not Active*"
        
        keyboard = [
            [
                InlineKeyboardButton("1 Month - $10", callback_data="purchase_1m"),
                InlineKeyboardButton("3 Months - $25", callback_data="purchase_3m")
            ],
            [
                InlineKeyboardButton("6 Months - $45", callback_data="purchase_6m"),
                InlineKeyboardButton("1 Year - $80", callback_data="purchase_1y")
            ],
            [
                InlineKeyboardButton("Lifetime - $150", callback_data="purchase_lifetime")
            ],
            [
                InlineKeyboardButton("🔙 Back to Premium Menu", callback_data="main_premium"),
                InlineKeyboardButton("💬 Contact Admin", callback_data="main_contact")
            ]
        ]
        
        await query.message.edit_text(
            f"🛒 *Get Premium Access* 🛒\n\n"
            f"{status_text}\n\n"
            "💰 *Pricing Plans:*\n"
            "• 1 Month: $10\n"
            "• 3 Months: $25 (save $5)\n"
            "• 6 Months: $45 (save $15)\n"
            "• 1 Year: $80 (save $40)\n"
            "• Lifetime: $150 (one-time payment)\n\n"
            "💳 *Payment Methods:*\n"
            "- Cryptocurrency (BTC, ETH, USDT)\n"
            "- PayPal\n"
            "- Credit Card\n\n"
            "Select a plan or contact admin for more options:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_premium_purchase: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def bot_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced bot information"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("📊 Bot Stats", callback_data="main_stats")],
            [InlineKeyboardButton("🌐 Domain List", callback_data="main_domains")],
            [InlineKeyboardButton("🆘 Help Center", callback_data="main_help")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")]
        ]
        
        await query.message.edit_text(
            "ℹ️ *Premium Account Generator Bot* ℹ️\n\n"
            "🔹 *Version:* 5.0 (Enhanced Edition)\n"
            "🔹 *Developer:* @YourUsername\n"
            "🔹 *Last Updated:* 2024-01-01\n\n"
            "🌟 *Features:*\n"
            "- 100+ supported platforms\n"
            "- Fast account generation\n"
            "- Premium key system\n"
            "- Daily account limits\n"
            "- Regular database updates\n"
            "- Premium domains available\n\n"
            "📈 *Statistics:*\n"
            f"- {len(DOMAINS)} total domains\n"
            f"- {len(PREMIUM_DOMAINS)} premium domains\n"
            f"- {keys_data.global_stats.get('generated', 0)} accounts generated\n\n"
            "Use /generate to start!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in bot_info: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced public statistics"""
    try:
        query = update.callback_query
        await query.answer()
        
        total_generated = keys_data.global_stats.get("generated", 0)
        active_users = len(keys_data.user_keys) + len(keys_data.premium_users)
        
        # Create category breakdown
        categories = {
            "🎮 Gaming": len([d for d in DOMAINS if d in ["Steam", "Origin", "EpicGames", "Uplay", "Battle.net", "Rockstar", 
                                                         "GOG", "Xbox", "PlayStation", "Nintendo", "Roblox", "Garena",
                                                         "PUBG", "FreeFire", "MobileLegends", "CallOfDuty", "Valorant",
                                                         "Fortnite", "ApexLegends", "Minecraft", "LeagueOfLegends", "Dota2"]]),
            "🎬 Streaming": len([d for d in DOMAINS if d in ["Netflix", "DisneyPlus", "HBO Max", "Amazon Prime", "Hulu",
                                                           "Apple TV", "Spotify", "YouTube Premium", "Deezer", "Tidal",
                                                           "Crunchyroll", "Funimation", "Twitch", "Patreon", "Viu"]]),
            "📱 Social": len([d for d in DOMAINS if d in ["Facebook", "Instagram", "Twitter", "TikTok", "Snapchat",
                                                         "Pinterest", "Reddit", "LinkedIn", "Discord", "Telegram",
                                                         "WhatsApp", "WeChat", "Line", "Viber", "Signal"]]),
            "🔒 VPN": len([d for d in DOMAINS if d in ["NordVPN", "ExpressVPN", "Surfshark", "CyberGhost", "ProtonVPN",
                                                     "IPVanish", "Hotspot Shield", "Private Internet Access", "TunnelBear", "Windscribe"]])
        }
        
        category_text = "\n".join(f"{cat}: {count} domains" for cat, count in categories.items())
        
        keyboard = [
            [InlineKeyboardButton("🌐 Domain List", callback_data="main_domains")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")]
        ]
        
        await query.message.edit_text(
            f"📊 *Public Statistics* 📊\n\n"
            f"🔢 *Total Accounts Generated:* `{total_generated}`\n"
            f"👥 *Active Users:* `{active_users}`\n"
            f"🌐 *Supported Domains:* `{len(DOMAINS)}`\n\n"
            "*Category Breakdown:*\n"
            f"{category_text}\n\n"
            "🔥 *More features coming soon!*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in bot_stats: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def bot_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced help message with sections"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [
                InlineKeyboardButton("🔑 Key Help", callback_data="help_keys"),
                InlineKeyboardButton("🛠 Generation", callback_data="help_generate")
            ],
            [
                InlineKeyboardButton("💎 Premium", callback_data="help_premium"),
                InlineKeyboardButton("📊 Limits", callback_data="help_limits")
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back"),
                InlineKeyboardButton("📞 Contact", callback_data="main_contact")
            ]
        ]
        
        await query.message.edit_text(
            "🆘 *Help Center* 🆘\n\n"
            "Welcome to the Premium Account Generator help section. "
            "Select a category below for detailed information:\n\n"
            "🔹 *Key Help* - About premium keys\n"
            "🔹 *Generation* - How to generate accounts\n"
            "🔹 *Premium* - Premium features info\n"
            "🔹 *Limits* - Understanding usage limits\n\n"
            "Or contact admin directly for personalized assistance.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in bot_help: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def help_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help about keys"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Help", callback_data="main_help")]
        ]
        
        await query.message.edit_text(
            "🔑 *Key Help*\n\n"
            "🔸 *What are keys?*\n"
            "Keys grant access to account generation features. "
            "They can be time-limited or lifetime access.\n\n"
            "🔸 *How to get a key?*\n"
            "Contact the bot admin (@YourUsername) to purchase a key.\n\n"
            "🔸 *How to redeem?*\n"
            "Use the command: `/key YOUR_KEY_HERE`\n\n"
            "🔸 *Key types:*\n"
            "- Regular keys: Limited access\n"
            "- Premium keys: Full access to all features\n\n"
            "Need help? Contact admin using the button below.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in help_keys: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def help_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help about generation"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Help", callback_data="main_help")]
        ]
        
        await query.message.edit_text(
            "🛠 *Account Generation Help*\n\n"
            "🔸 *How to generate accounts:*\n"
            "1. Get and redeem a valid key\n"
            "2. Use /generate command\n"
            "3. Select your desired platform\n"
            "4. Wait for processing (2-10 seconds)\n"
            "5. Receive your accounts file\n\n"
            "🔸 *Tips for best results:*\n"
            "- Use accounts quickly after generation\n"
            "- Try different platforms if one is empty\n"
            "- Premium users get faster generation\n\n"
            "🔸 *File format:*\n"
            "Accounts are delivered as username:password pairs in a text file.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in help_generate: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def help_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help about premium features"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Help", callback_data="main_help")],
            [InlineKeyboardButton("💎 Premium Features", callback_data="main_premium")]
        ]
        
        await query.message.edit_text(
            "💎 *Premium Features Help*\n\n"
            "🌟 *Benefits of Premium Membership:*\n"
            "- Access to exclusive premium domains\n"
            f"- Higher daily limits ({MAX_PREMIUM_ACCOUNTS} accounts/day)\n"
            f"- Faster generation times ({PREMIUM_COOLDOWN}s cooldown)\n"
            "- Priority customer support\n\n"
            "🔸 *How to get premium?*\n"
            "1. Purchase a premium key from admin\n"
            "2. Redeem it with /key command\n"
            "3. Enjoy all premium benefits immediately\n\n"
            "For pricing and options, visit the premium menu:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in help_premium: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def help_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help about usage limits"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Help", callback_data="main_help")],
            [InlineKeyboardButton("📊 Check Usage", callback_data="main_stats")]
        ]
        
        await query.message.edit_text(
            "📊 *Usage Limits Help*\n\n"
            "🔸 *Daily Limits:*\n"
            f"- Regular users: {MAX_ACCOUNTS_PER_USER} accounts/day\n"
            f"- Premium users: {MAX_PREMIUM_ACCOUNTS} accounts/day\n\n"
            "🔸 *Cooldown Periods:*\n"
            f"- Regular users: {REQUEST_COOLDOWN} seconds between requests\n"
            f"- Premium users: {PREMIUM_COOLDOWN} seconds between requests\n\n"
            "🔸 *Reset Time:*\n"
            "Limits reset daily at midnight UTC.\n\n"
            "Check your current usage with the button below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in help_limits: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show enhanced contact information"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")]
        ]
        
        await query.message.edit_text(
            "📞 *Contact Admin* 📞\n\n"
            "For support, key requests, or premium access:\n\n"
            "🔹 *Telegram:* @YourUsername\n"
            "🔹 *Email:* youremail@example.com\n"
            "🔹 *Support Hours:* 10AM-10PM UTC\n\n"
            "📌 *Before contacting:*\n"
            "- Check /help for answers\n"
            "- Have your user ID ready\n"
            "- Be specific about your issue\n\n"
            "Please be patient for a response.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in contact_admin: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def redeem_key_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show key redemption menu"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_back")],
            [InlineKeyboardButton("📞 Contact Admin", callback_data="main_contact")]
        ]
        
        await query.message.edit_text(
            "🔑 *Redeem Premium Key*\n\n"
            "To redeem a key:\n"
            "1. Get a key from the admin\n"
            "2. Use the command: `/key YOUR_KEY_HERE`\n\n"
            "🔸 *Key Types:*\n"
            "- Regular keys: Limited access\n"
            "- Premium keys: Full access to all features\n\n"
            "Don't have a key? Contact admin to purchase one:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in redeem_key_menu: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show expanded admin panel"""
    try:
        query = update.callback_query
        await query.answer()
        
        if str(query.from_user.id) != str(ADMIN_ID):
            return await query.message.reply_text("❌ Access denied!")

        keyboard = [
            [InlineKeyboardButton("📋 View Logs", callback_data="admin_logs"),
             InlineKeyboardButton("📊 View Stats", callback_data="admin_stats")],
            [InlineKeyboardButton("🔑 Generate Keys", callback_data="admin_genkeys"),
             InlineKeyboardButton("👥 Manage Users", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
             InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
            [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
             InlineKeyboardButton("📥 Export Data", callback_data="admin_export")],
            [InlineKeyboardButton("🖥 Server Stats", callback_data="admin_server"),
             InlineKeyboardButton("🔄 Restart", callback_data="admin_restart")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_back")]
        ]
        
        await query.message.edit_text(
            "👑 *Admin Panel*\nSelect an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in admin_panel: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def view_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active users and logs"""
    try:
        query = update.callback_query
        await query.answer()
        
        if str(query.from_user.id) != str(ADMIN_ID):
            return await query.message.reply_text("❌ Access denied!")

        if not keys_data.user_keys and not keys_data.premium_users:
            return await query.message.reply_text("📂 No active users.")

        log_text = "📋 *Active Users*\n\n"
        
        if keys_data.premium_users:
            log_text += "🌟 *Premium Users*\n"
            for user in keys_data.premium_users:
                usage = keys_data.user_stats.get(user, {}).get("today", 0)
                log_text += f"👤 User: `{user}`\n📊 Usage: `{usage}/{MAX_PREMIUM_ACCOUNTS}`\n\n"
        
        for user, expiry in keys_data.user_keys.items():
            expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
            usage = keys_data.user_stats.get(user, {}).get("today", 0)
            log_text += f"👤 User: `{user}`\n⏳ Expiry: `{expiry_text}`\n📊 Usage: `{usage}/{MAX_ACCOUNTS_PER_USER}`\n\n"

        if keys_data.banned_users:
            log_text += "\n🚫 *Banned Users*\n"
            log_text += "\n".join(f"👤 `{user}`" for user in keys_data.banned_users)

        await send_large_message(update, log_text)
    except Exception as e:
        logger.error(f"Error in view_logs: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def view_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics"""
    try:
        query = update.callback_query
        await query.answer()
        
        active_users = len(keys_data.user_keys)
        premium_users = len(keys_data.premium_users)
        banned_users = len(keys_data.banned_users)
        active_keys = len(keys_data.keys)
        total_generated = keys_data.global_stats.get("generated", 0)
        keys_created = keys_data.global_stats.get("keys_created", 0)
        
        stats_text = (
            f"📊 *Bot Statistics*\n\n"
            f"🔢 Total Accounts Generated: `{total_generated}`\n"
            f"🔑 Total Keys Created: `{keys_created}`\n"
            f"👥 Active Users: `{active_users}`\n"
            f"🌟 Premium Users: `{premium_users}`\n"
            f"🚫 Banned Users: `{banned_users}`\n"
            f"🔑 Available Keys: `{active_keys}`\n\n"
            f"🌐 Supported Domains: `{len(DOMAINS)}`\n"
            f"💎 Premium Domains: `{len(PREMIUM_DOMAINS)}`\n"
            f"📂 Database Files: `{len(DATABASE_FILES)}`"
        )
        
        await query.message.edit_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in view_stats: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all user logs"""
    try:
        query = update.callback_query
        await query.answer()
        
        if str(query.from_user.id) != str(ADMIN_ID):
            return await query.message.reply_text("❌ Access denied!")

        keys_data.user_keys = {}
        keys_data.user_stats = {}
        keys_data.premium_users = set()
        save_keys(keys_data)
        await query.message.reply_text("✅ All user logs and stats have been cleared!")
    except Exception as e:
        logger.error(f"Error in clear_logs: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage users interface"""
    try:
        query = update.callback_query
        await query.answer()
        
        if str(query.from_user.id) != str(ADMIN_ID):
            return await query.message.reply_text("❌ Access denied!")

        keyboard = [
            [InlineKeyboardButton("➕ Add Premium User", callback_data="admin_add_premium")],
            [InlineKeyboardButton("➖ Remove Premium User", callback_data="admin_remove_premium")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        
        await query.message.edit_text(
            "👥 *User Management*\nSelect an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in manage_users: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def add_premium_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add premium user"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "👤 *Add Premium User*\n\n"
            "Send the user ID to grant premium access:",
            parse_mode="Markdown"
        )
        
        context.user_data["awaiting_user_id"] = "add_premium"
    except Exception as e:
        logger.error(f"Error in add_premium_user: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def remove_premium_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove premium user"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "👤 *Remove Premium User*\n\n"
            "Send the user ID to revoke premium access:",
            parse_mode="Markdown"
        )
        
        context.user_data["awaiting_user_id"] = "remove_premium"
    except Exception as e:
        logger.error(f"Error in remove_premium_user: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user ID input for premium management"""
    try:
        user_id = update.message.text.strip()
        action = context.user_data.get("awaiting_user_id")
        
        if action == "add_premium":
            keys_data.premium_users.add(user_id)
            response = f"✅ User {user_id} has been granted premium access!"
        elif action == "remove_premium":
            keys_data.premium_users.discard(user_id)
            response = f"✅ User {user_id} has been removed from premium access!"
        else:
            return
        
        save_keys(keys_data)
        context.user_data.pop("awaiting_user_id", None)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error in handle_user_id_input: {e}")
        await update.message.reply_text("❌ An error occurred while processing your request.")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate broadcast process"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "📢 *Broadcast Message*\n\n"
            "Send the message you want to broadcast to all users:",
            parse_mode="Markdown"
        )
        context.user_data["broadcasting"] = True
    except Exception as e:
        logger.error(f"Error in handle_broadcast: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def perform_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message to all users"""
    try:
        if not context.user_data.get("broadcasting"):
            return
        
        message = update.message.text
        all_users = set(keys_data.user_keys.keys()).union(keys_data.premium_users)
        
        if not all_users:
            await update.message.reply_text("❌ No users to broadcast to!")
            return
        
        success = 0
        failures = 0
        progress_msg = await update.message.reply_text(f"📤 Broadcasting to {len(all_users)} users...")
        
        for user_id in all_users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 *Broadcast Message*\n\n{message}",
                    parse_mode=ParseMode.MARKDOWN
                )
                success += 1
            except Exception as e:
                failures += 1
                logger.error(f"Failed to send to {user_id}: {e}")
            await asyncio.sleep(0.1)  # Rate limiting
        
        await progress_msg.edit_text(
            f"✅ Broadcast complete!\n"
            f"• Success: {success}\n"
            f"• Failures: {failures}"
        )
        context.user_data.pop("broadcasting", None)
    except Exception as e:
        logger.error(f"Error in perform_broadcast: {e}")
        await update.message.reply_text("❌ An error occurred during broadcast.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user from using the bot"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "🚫 *Ban User*\n\n"
            "Send the user ID to ban:",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_input"] = "ban"
    except Exception as e:
        logger.error(f"Error in ban_user: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "✅ *Unban User*\n\n"
            "Send the user ID to unban:",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_input"] = "unban"
    except Exception as e:
        logger.error(f"Error in unban_user: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def handle_ban_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process ban/unban requests"""
    try:
        action = context.user_data.get("awaiting_input")
        user_id = update.message.text.strip()
        
        if action == "ban":
            keys_data.banned_users.add(user_id)
            response = f"✅ User {user_id} has been banned!"
        elif action == "unban":
            keys_data.banned_users.discard(user_id)
            response = f"✅ User {user_id} has been unbanned!"
        else:
            return
        
        save_keys(keys_data)
        context.user_data.pop("awaiting_input", None)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error in handle_ban_unban: {e}")
        await update.message.reply_text("❌ An error occurred while processing your request.")

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export bot data as files"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Export user data
        users = []
        for user, expiry in keys_data.user_keys.items():
            users.append({
                "user_id": user,
                "key_expiry": expiry,
                "premium": user in keys_data.premium_users,
                "banned": user in keys_data.banned_users,
                "usage": keys_data.user_stats.get(user, {})
            })
        
        with open("user_export.json", "w") as f:
            json.dump(users, f, indent=2)
        
        # Export logs
        with open("log_export.txt", "w") as f:
            f.write("\n".join(keys_data.logs))
        
        # Send files
        files = [
            InputFile("user_export.json"),
            InputFile("log_export.txt"),
            InputFile(KEYS_FILE),
            InputFile(USED_ACCOUNTS_FILE)
        ]
        
        await query.message.reply_document(
            documents=files,
            caption="📥 *Data Export*\nExported files: user data, logs, keys, and used accounts"
        )
    except Exception as e:
        logger.error(f"Error in export_data: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("❌ An error occurred while exporting data.")

async def server_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show server statistics"""
    try:
        query = update.callback_query
        await query.answer()
        
        # System info
        uname = platform.uname()
        # Memory
        mem = psutil.virtual_memory()
        # Disk
        disk = psutil.disk_usage('/')
        # CPU
        cpu_usage = psutil.cpu_percent(interval=1)
        
        stats_text = (
            "🖥 *Server Statistics*\n\n"
            f"*System:* {uname.system} {uname.release}\n"
            f"*Processor:* {uname.processor}\n\n"
            f"*CPU Usage:* {cpu_usage}%\n"
            f"*Memory Usage:* {mem.percent}% ({mem.used/1e9:.1f}GB/{mem.total/1e9:.1f}GB)\n"
            f"*Disk Usage:* {disk.percent}% ({disk.used/1e9:.1f}GB/{disk.total/1e9:.1f}GB)\n\n"
            f"*Bot Uptime:* {format_time(time.time() - psutil.Process().create_time())}"
        )
        
        await query.message.edit_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in server_stats: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the bot"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text("🔄 Restarting bot...")
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        logger.error(f"Error in restart_bot: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("❌ Failed to restart bot.")

async def handle_admin_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin update command"""
    try:
        query = update.callback_query
        await query.answer()
        
        if str(query.from_user.id) != str(ADMIN_ID):
            return await query.message.reply_text("❌ Access denied!")
        
        await query.message.edit_text(
            "🔄 *Update Bot*\n\n"
            "This will pull the latest changes from GitHub and restart the bot.\n"
            "Are you sure you want to continue?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Update", callback_data="confirm_update")],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]
            ]),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_update: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def redeem_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeem a premium key"""
    try:
        chat_id = str(update.message.chat_id)
        
        if is_banned(chat_id):
            await update.message.reply_text("🚫 You are banned from using this bot!")
            return

        if len(context.args) != 1:
            return await update.message.reply_text(
                "⚠ *Usage:* `/key <your_key>`\n"
                "Get a key from the bot admin to access premium features.",
                parse_mode="Markdown"
            )

        entered_key = context.args[0]

        if entered_key not in keys_data.keys:
            return await update.message.reply_text("❌ Invalid or expired key!")

        if keys_data.keys[entered_key] == "premium":
            keys_data.premium_users.add(chat_id)
            del keys_data.keys[entered_key]
            save_keys(keys_data)
            
            return await update.message.reply_text(
                "🎉 *Premium Account Activated!*\n\n"
                "🌟 *Benefits unlocked:*\n"
                "- Access to premium domains\n"
                "- Faster generation times\n"
                "- Higher daily limits\n"
                "- Priority support\n\n"
                "Use /generate to start!",
                parse_mode="Markdown"
            )
        
        expiry = keys_data.keys[entered_key]
        if expiry is not None and datetime.now().timestamp() > expiry:
            del keys_data.keys[entered_key]
            save_keys(keys_data)
            return await update.message.reply_text("❌ This key has expired!")

        if chat_id in keys_data.user_keys:
            old_expiry = keys_data.user_keys[chat_id]
            if old_expiry is None or (expiry is not None and old_expiry > expiry):
                return await update.message.reply_text(
                    f"⚠ You already have a better active key!\n"
                    f"Current expiry: `{'Lifetime' if old_expiry is None else datetime.fromtimestamp(old_expiry).strftime('%Y-%m-%d %H:%M:%S')}`",
                    parse_mode="Markdown"
                )

        keys_data.user_keys[chat_id] = expiry
        del keys_data.keys[entered_key]
        save_keys(keys_data)

        expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
        await update.message.reply_text(
            f"✅ *Key activated successfully!*\n"
            f"⏳ *Expires:* `{expiry_text}`\n"
            f"💎 *Features unlocked:*\n"
            f"- Generate premium accounts\n"
            f"- Priority access\n"
            f"- Daily limit: {MAX_ACCOUNTS_PER_USER} accounts\n\n"
            f"Use /generate to start!",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in redeem_key: {e}")
        await update.message.reply_text("❌ An error occurred while redeeming the key.")

async def generate_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to generate premium keys"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to generate keys!")

        if len(context.args) < 1 or context.args[0] not in ["1m", "5m", "15m", "1h", "6h", "12h", "1d", "3d", "7d", "14d", "30d", "lifetime", "premium"]:
            return await update.message.reply_text(
                "⚠ *Usage:* `/genkey <duration> [amount]`\n"
                "*Examples:*\n"
                "• `/genkey 1h` - Single 1-hour key\n"
                "• `/genkey 1d 5` - Five 1-day keys\n"
                "• `/genkey premium 3` - Three premium keys\n"
                "*Durations:* 1m, 5m, 15m, 1h, 6h, 12h, 1d, 3d, 7d, 14d, 30d, lifetime, premium",
                parse_mode="Markdown"
            )

        duration = context.args[0]
        amount = 1 if len(context.args) < 2 else min(int(context.args[1]), MAX_KEYS_PER_GENERATION)
        
        keys_generated = []
        for _ in range(amount):
            new_key = generate_random_key()
            
            if duration == "premium":
                keys_data.keys[new_key] = "premium"
            else:
                expiry = get_expiry_time(duration)
                keys_data.keys[new_key] = expiry
            
            keys_generated.append(new_key)

        keys_data.global_stats["keys_created"] += amount
        save_keys(keys_data)
        
        key_list = "\n".join(f"`{key}`" for key in keys_generated)
        await update.message.reply_text(
            f"✅ *Generated {amount} {duration} key(s):*\n{key_list}\n\n"
            f"*Total active keys:* `{len(keys_data.keys)}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in generate_key: {e}")
        await update.message.reply_text("❌ An error occurred while generating keys.")

async def delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to delete a key"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if len(context.args) < 1:
            return await update.message.reply_text(
                "⚠ *Usage:* `/delkey <key>`\n"
                "Deletes the specified key from the system.",
                parse_mode="Markdown"
            )

        key = context.args[0]
        if key in keys_data.keys:
            del keys_data.keys[key]
            save_keys(keys_data)
            await update.message.reply_text(
                f"✅ Key `{key}` has been deleted.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ Key `{key}` not found.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in delete_key: {e}")
        await update.message.reply_text("❌ An error occurred while deleting the key.")

async def list_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to list all active keys"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if not keys_data.keys:
            return await update.message.reply_text("🔑 No active keys found.")

        keys_text = "🔑 *Active Keys*\n\n"
        for key, expiry in keys_data.keys.items():
            if expiry == "premium":
                keys_text += f"🌟 Premium Key: `{key}`\n"
            else:
                expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
                keys_text += f"🔹 Key: `{key}` (Expires: {expiry_text})\n"

        await send_large_message(update, keys_text)
    except Exception as e:
        logger.error(f"Error in list_keys: {e}")
        await update.message.reply_text("❌ An error occurred while listing keys.")

async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add a note about a user"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if len(context.args) < 2:
            return await update.message.reply_text(
                "⚠ *Usage:* `/note <user_id> <note_text>`\n"
                "Adds a note about the specified user.",
                parse_mode="Markdown"
            )

        user_id = context.args[0]
        note_text = ' '.join(context.args[1:])
        keys_data.user_notes[user_id] = note_text
        save_keys(keys_data)
        
        await update.message.reply_text(
            f"✅ Note added for user `{user_id}`:\n\n{note_text}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in add_note: {e}")
        await update.message.reply_text("❌ An error occurred while adding the note.")

async def view_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view user notes"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if not keys_data.user_notes:
            return await update.message.reply_text("📭 No user notes found.")

        notes_text = "📝 *User Notes*\n\n"
        for user_id, note in keys_data.user_notes.items():
            notes_text += f"👤 User: `{user_id}`\n📄 Note: {note}\n\n"

        await send_large_message(update, notes_text)
    except Exception as e:
        logger.error(f"Error in view_notes: {e}")
        await update.message.reply_text("❌ An error occurred while viewing notes.")

async def clear_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to clear a user's daily usage"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if len(context.args) < 1:
            return await update.message.reply_text(
                "⚠ *Usage:* `/clearusage <user_id>`\n"
                "Resets the daily usage counter for the specified user.",
                parse_mode="Markdown"
            )

        user_id = context.args[0]
        if user_id in keys_data.user_stats:
            keys_data.user_stats[user_id]["today"] = 0
            save_keys(keys_data)
            await update.message.reply_text(
                f"✅ Usage cleared for user `{user_id}`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"ℹ No usage data found for user `{user_id}`",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in clear_usage: {e}")
        await update.message.reply_text("❌ An error occurred while clearing usage.")

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to get info about a user"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        if len(context.args) < 1:
            return await update.message.reply_text(
                "⚠ *Usage:* `/userinfo <user_id>`\n"
                "Shows information about the specified user.",
                parse_mode="Markdown"
            )

        user_id = context.args[0]
        info_text = f"👤 *User Info for {user_id}*\n\n"
        
        # Basic info
        info_text += f"🔹 Premium: {'✅' if is_premium_user(user_id) else '❌'}\n"
        info_text += f"🔹 Banned: {'✅' if is_banned(user_id) else '❌'}\n"
        
        # Key info
        if user_id in keys_data.user_keys:
            expiry = keys_data.user_keys[user_id]
            expiry_text = "Lifetime" if expiry is None else datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M:%S')
            info_text += f"⏳ Key expires: `{expiry_text}`\n"
        
        # Usage info
        today = datetime.now().strftime("%Y-%m-%d")
        if user_id in keys_data.user_stats and keys_data.user_stats[user_id]["date"] == today:
            usage = keys_data.user_stats[user_id]["today"]
            max_limit = MAX_PREMIUM_ACCOUNTS if is_premium_user(user_id) else MAX_ACCOUNTS_PER_USER
            info_text += f"📊 Usage today: `{usage}/{max_limit}`\n"
        
        # Last request
        if user_id in keys_data.user_last_request:
            last_request = datetime.fromtimestamp(keys_data.user_last_request[user_id]).strftime('%Y-%m-%d %H:%M:%S')
            info_text += f"⏱ Last request: `{last_request}`\n"
        
        # Notes
        if user_id in keys_data.user_notes:
            info_text += f"\n📝 Note: {keys_data.user_notes[user_id]}\n"
        
        await update.message.reply_text(info_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in user_info: {e}")
        await update.message.reply_text("❌ An error occurred while getting user info.")

async def backup_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to backup all data"""
    try:
        if update.message.chat_id != ADMIN_ID:
            return await update.message.reply_text("❌ You are not authorized to use this command!")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        
        # Create in-memory zip file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add keys file
            if os.path.exists(KEYS_FILE):
                zip_file.write(KEYS_FILE, f"keys_{timestamp}.json")
            
            # Add used accounts file
            if os.path.exists(USED_ACCOUNTS_FILE):
                zip_file.write(USED_ACCOUNTS_FILE, f"used_accounts_{timestamp}.txt")
            
            # Add database files
            for db_file in DATABASE_FILES:
                if os.path.exists(db_file):
                    zip_file.write(db_file, f"database/{os.path.basename(db_file)}")
        
        zip_buffer.seek(0)
        
        await update.message.reply_document(
            document=InputFile(zip_buffer, filename=backup_filename),
            caption=f"📦 *Full Backup* - {timestamp}",
            parse_mode="Markdown"
        )
        
        await update.message.reply_text("✅ Backup completed successfully!")
    except Exception as e:
        logger.error(f"Error in backup_data: {e}")
        await update.message.reply_text("❌ An error occurred during backup.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    try:
        user_id = str(update.effective_user.id)
        
        if is_banned(user_id):
            await update.message.reply_text("🚫 You are banned from using this bot!")
            return
        
        text = update.message.text.lower()
        
        if text in ["/start", "start", "menu"]:
            await show_main_menu(update, context)
        elif text in ["help", "info"]:
            await bot_help(update, context)
        elif text == "generate":
            await generate_menu(update, context)
        elif text == "premium":
            await premium_menu(update, context)
        elif text.isdigit() and context.user_data.get("awaiting_input"):
            await handle_ban_unban(update, context)
        elif text.isdigit() and context.user_data.get("awaiting_user_id"):
            await handle_user_id_input(update, context)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        if update.effective_chat:
            await update.effective_chat.send_message("An error occurred. Please try again.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify admin"""
    try:
        logger.error(f"Update {update} caused error: {context.error}")
        
        if ADMIN_ID:
            error_msg = (
                f"⚠️ *Error occurred:*\n"
                f"```python\n{context.error}\n```\n"
                f"*Update:*\n`{update}`"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

def setup_bot_handlers(application: Application):
    """Set up all bot handlers with new callbacks"""
    # Command handlers
    application.add_handler(CommandHandler("start", show_main_menu))
    application.add_handler(CommandHandler("generate", generate_menu))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", bot_help))
    application.add_handler(CommandHandler("stats", bot_stats))
    application.add_handler(CommandHandler("key", redeem_key))
    application.add_handler(CommandHandler("genkey", generate_key))
    application.add_handler(CommandHandler("logs", view_logs))
    application.add_handler(CommandHandler("domains", list_domains))
    application.add_handler(CommandHandler("usage", check_usage))
    
    # Admin commands
    application.add_handler(CommandHandler("note", add_note))
    application.add_handler(CommandHandler("notes", view_notes))
    application.add_handler(CommandHandler("clearusage", clear_usage))
    application.add_handler(CommandHandler("userinfo", user_info))
    application.add_handler(CommandHandler("backup", backup_data))
    application.add_handler(CommandHandler("delkey", delete_key))
    application.add_handler(CommandHandler("listkeys", list_keys))
    
    # Callback query handlers
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_back$"))
    application.add_handler(CallbackQueryHandler(generate_menu, pattern="^main_generate$"))
    application.add_handler(CallbackQueryHandler(premium_menu, pattern="^main_premium$"))
    application.add_handler(CallbackQueryHandler(bot_info, pattern="^main_info$"))
    application.add_handler(CallbackQueryHandler(bot_stats, pattern="^main_stats$"))
    application.add_handler(CallbackQueryHandler(bot_help, pattern="^main_help$"))
    application.add_handler(CallbackQueryHandler(contact_admin, pattern="^main_contact$"))
    application.add_handler(CallbackQueryHandler(redeem_key_menu, pattern="^main_redeem$"))
    application.add_handler(CallbackQueryHandler(list_domains, pattern="^main_domains$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^main_admin$"))
    
    # Category and generation handlers
    application.add_handler(CallbackQueryHandler(show_category_domains, pattern="^category_"))
    application.add_handler(CallbackQueryHandler(generate_filtered_accounts, pattern="^generate_"))
    
    # Premium feature handlers
    application.add_handler(CallbackQueryHandler(handle_premium_domains_info, pattern="^premium_domains$"))
    application.add_handler(CallbackQueryHandler(handle_premium_speed_info, pattern="^premium_speed$"))
    application.add_handler(CallbackQueryHandler(handle_premium_limits_info, pattern="^premium_limits$"))
    application.add_handler(CallbackQueryHandler(handle_premium_support_info, pattern="^premium_support$"))
    application.add_handler(CallbackQueryHandler(handle_premium_purchase, pattern="^premium_buy$"))
    
    # Help section handlers
    application.add_handler(CallbackQueryHandler(help_keys, pattern="^help_keys$"))
    application.add_handler(CallbackQueryHandler(help_generate, pattern="^help_generate$"))
    application.add_handler(CallbackQueryHandler(help_premium, pattern="^help_premium$"))
    application.add_handler(CallbackQueryHandler(help_limits, pattern="^help_limits$"))
    
    # Admin panel handlers
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_back$"))
    application.add_handler(CallbackQueryHandler(view_logs, pattern="^admin_logs$"))
    application.add_handler(CallbackQueryHandler(view_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(manage_users, pattern="^admin_users$"))
    application.add_handler(CallbackQueryHandler(add_premium_user, pattern="^admin_add_premium$"))
    application.add_handler(CallbackQueryHandler(remove_premium_user, pattern="^admin_remove_premium$"))
    application.add_handler(CallbackQueryHandler(clear_logs, pattern="^admin_clearlogs$"))
    application.add_handler(CallbackQueryHandler(handle_admin_update, pattern="^admin_update$"))
    application.add_handler(CallbackQueryHandler(handle_broadcast, pattern="^admin_broadcast$"))
    application.add_handler(CallbackQueryHandler(ban_user, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(unban_user, pattern="^admin_unban$"))
    application.add_handler(CallbackQueryHandler(export_data, pattern="^admin_export$"))
    application.add_handler(CallbackQueryHandler(server_stats, pattern="^admin_server$"))
    application.add_handler(CallbackQueryHandler(restart_bot, pattern="^admin_restart$"))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Chat(ADMIN_ID),
        lambda update, context: (
            perform_broadcast(update, context) if context.user_data.get("broadcasting") else
            handle_ban_unban(update, context) if context.user_data.get("awaiting_input") else
            handle_user_id_input(update, context) if context.user_data.get("awaiting_user_id") else
            None
        )
    ))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(error_handler)

def main():
    """Start the bot"""
    try:
        app = Application.builder().token(TOKEN).build()
        setup_bot_handlers(app)
        
        # Check for required files
        for db_file in DATABASE_FILES:
            if not os.path.exists(db_file):
                logger.warning(f"Database file not found: {db_file}")
        
        logger.info("🤖 Premium Account Generator Bot is running...")
        app.run_polling()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()