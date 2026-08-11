import os
import random
import asyncio
import logging
import json
import shutil
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token - Replace with your actual bot token
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# The secret key for new users
SECRET_KEY = "Amair"

# Admin user IDs (Replace with actual admin Telegram user IDs)
ADMIN_IDS = [123456789, 987654321]  # Add your Telegram user IDs here

# Directory where videos are stored
VIDEOS_DIR = "videos"

# Data file for persistent storage
DATA_FILE = "bot_data.json"
ADMIN_FILE = "admin_ids.json"
VIDEO_DB_FILE = "video_db.json"

# Track user authentication status and video timers
user_data = {}
pending_deletions = []  # Track messages to delete from chat
uploading_admins = {}  # Track admins who are uploading videos
video_database = {}  # Store video metadata with permanent IDs

# Ensure directories exist
os.makedirs(VIDEOS_DIR, exist_ok=True)

def load_data():
    """Load data from JSON file"""
    global user_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                user_data = data.get('users', {})
                logger.info(f"Loaded data for {len(user_data)} users")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            user_data = {}

def save_data():
    """Save data to JSON file"""
    try:
        data = {
            'users': user_data,
            'last_save': datetime.now().isoformat()
        }
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_video_database():
    """Load video database from JSON file"""
    global video_database
    if os.path.exists(VIDEO_DB_FILE):
        try:
            with open(VIDEO_DB_FILE, 'r') as f:
                video_database = json.load(f)
                logger.info(f"Loaded video database with {len(video_database)} videos")
        except Exception as e:
            logger.error(f"Error loading video database: {e}")
            video_database = {}
    else:
        # Create new database with existing videos
        rebuild_video_database()

def save_video_database():
    """Save video database to JSON file"""
    try:
        with open(VIDEO_DB_FILE, 'w') as f:
            json.dump(video_database, f, indent=2)
        logger.info(f"Video database saved with {len(video_database)} videos")
    except Exception as e:
        logger.error(f"Error saving video database: {e}")

def rebuild_video_database():
    """Rebuild video database from filesystem"""
    global video_database
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.3gp', '.m4v', '.mpg', '.mpeg'}
    
    # Find all video files
    existing_videos = {}
    if os.path.exists(VIDEOS_DIR):
        for file in os.listdir(VIDEOS_DIR):
            file_path = os.path.join(VIDEOS_DIR, file)
            if os.path.isfile(file_path) and Path(file).suffix.lower() in video_extensions:
                # Generate unique ID based on file name and size
                file_hash = hashlib.md5(f"{file}_{os.path.getsize(file_path)}".encode()).hexdigest()[:8]
                existing_videos[file] = {
                    'name': file,
                    'path': file_path,
                    'size': get_file_size(file_path),
                    'size_bytes': os.path.getsize(file_path),
                    'hash': file_hash,
                    'upload_date': datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                }
    
    # Merge with existing database
    for filename, data in existing_videos.items():
        # Check if video already exists in database
        found = False
        for vid, vdata in video_database.items():
            if vdata.get('name') == filename:
                found = True
                # Update path if changed
                if vdata.get('path') != data['path']:
                    vdata['path'] = data['path']
                break
        
        if not found:
            # Assign new ID
            new_id = str(len(video_database) + 1)
            video_database[new_id] = data
    
    # Remove videos that no longer exist
    to_remove = []
    for vid, vdata in video_database.items():
        if not os.path.exists(vdata.get('path', '')):
            to_remove.append(vid)
    
    for vid in to_remove:
        del video_database[vid]
        logger.info(f"Removed missing video from database: {vid}")
    
    # Renumber IDs to be sequential
    if video_database:
        # Sort by ID
        sorted_ids = sorted(video_database.keys(), key=lambda x: int(x))
        new_db = {}
        for new_id, old_id in enumerate(sorted_ids, 1):
            new_db[str(new_id)] = video_database[old_id]
        video_database = new_db
    
    save_video_database()
    logger.info(f"Rebuilt video database with {len(video_database)} videos")

def get_video_files():
    """Get list of video files from database with permanent IDs"""
    videos = []
    # Sort by ID
    for vid in sorted(video_database.keys(), key=lambda x: int(x)):
        vdata = video_database[vid]
        # Check if file still exists
        if os.path.exists(vdata.get('path', '')):
            videos.append({
                'id': int(vid),
                'name': vdata['name'],
                'path': vdata['path'],
                'size': vdata.get('size', get_file_size(vdata['path'])),
                'upload_date': vdata.get('upload_date', 'Unknown')
            })
        else:
            # Remove missing video from database
            del video_database[vid]
            save_video_database()
    
    return videos

def get_video_by_id(video_id):
    """Get video by its permanent ID"""
    video_id_str = str(video_id)
    if video_id_str in video_database:
        vdata = video_database[video_id_str]
        if os.path.exists(vdata.get('path', '')):
            return {
                'id': int(video_id_str),
                'name': vdata['name'],
                'path': vdata['path'],
                'size': vdata.get('size', get_file_size(vdata['path'])),
                'upload_date': vdata.get('upload_date', 'Unknown')
            }
    return None

def is_admin(user_id):
    """Check if a user is an admin"""
    return user_id in ADMIN_IDS

def get_file_size(file_path):
    """Get file size in human readable format"""
    try:
        size = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    except:
        return "Unknown"

def get_file_size_from_bytes(size):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def save_admin_ids():
    """Save admin IDs to a file"""
    try:
        with open(ADMIN_FILE, 'w') as f:
            json.dump({'admins': ADMIN_IDS}, f, indent=2)
        logger.info(f"Admin IDs saved: {ADMIN_IDS}")
    except Exception as e:
        logger.error(f"Error saving admin IDs: {e}")

def load_admin_ids():
    """Load admin IDs from file"""
    global ADMIN_IDS
    try:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, 'r') as f:
                data = json.load(f)
                ADMIN_IDS = data.get('admins', ADMIN_IDS)
                logger.info(f"Loaded {len(ADMIN_IDS)} admin IDs")
        else:
            # Create file with default admins
            save_admin_ids()
    except Exception as e:
        logger.error(f"Error loading admin IDs: {e}")

# Load data at startup
load_data()
load_admin_ids()
load_video_database()

# ==================== USER COMMANDS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    
    # Check if user is admin - auto-authenticate
    if is_admin(user_id):
        if user_id_str not in user_data:
            user_data[user_id_str] = {
                'authenticated': True,
                'joined_at': datetime.now().isoformat(),
                'videos_watched': 0,
                'last_activity': datetime.now().isoformat(),
                'is_admin': True
            }
            save_data()
        else:
            user_data[user_id_str]['authenticated'] = True
            user_data[user_id_str]['is_admin'] = True
            save_data()
        
        await update.message.reply_text(
            "👑 *Welcome Admin!*\n\n"
            "You have been automatically authenticated.\n"
            "You have full access to all features.",
            parse_mode='Markdown'
        )
        await show_main_menu(update, context)
        return
    
    # Regular user flow
    if user_id_str not in user_data:
        user_data[user_id_str] = {
            'authenticated': False,
            'joined_at': datetime.now().isoformat(),
            'videos_watched': 0,
            'last_activity': datetime.now().isoformat()
        }
        save_data()
    
    if not user_data[user_id_str].get('authenticated', False):
        # User is not authenticated, ask for key
        keyboard = [[InlineKeyboardButton("❓ How to get key?", callback_data='help_key')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "🔐 *Welcome to the Video Bot!*\n\n"
            "This bot requires a special key to access videos.\n"
            "Please enter your key to continue.\n\n"
            "Format: `/key YOUR_KEY`\n\n"
            "💡 *Tip:* Contact the admin if you don't have a key."
        )
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        # User is already authenticated, show main menu
        await show_main_menu(update, context)

async def handle_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle key verification"""
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    user_input = update.message.text.strip()
    
    # Check if user is admin - auto-authenticate
    if is_admin(user_id):
        await update.message.reply_text(
            "👑 You're an admin! You don't need to enter a key.\n"
            "You already have full access."
        )
        await show_main_menu(update, context)
        return
    
    # Check if the user is sending a key (format: /key KEY)
    if user_input.startswith('/key '):
        provided_key = user_input.split(' ', 1)[1].strip()
        
        if provided_key == SECRET_KEY:
            # Correct key
            if user_id_str not in user_data:
                user_data[user_id_str] = {}
            
            user_data[user_id_str]['authenticated'] = True
            user_data[user_id_str]['authenticated_at'] = datetime.now().isoformat()
            user_data[user_id_str]['videos_watched'] = 0
            save_data()
            
            await update.message.reply_text(
                "✅ *Access Granted!*\n\n"
                "You can now use the bot to watch videos.\n"
                "Press the button below to get a video.",
                parse_mode='Markdown'
            )
            await show_main_menu(update, context)
            
            # Notify admins about new user
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"👤 *New User Joined!*\n"
                        f"User: {update.effective_user.first_name}\n"
                        f"ID: `{user_id}`\n"
                        f"Username: @{update.effective_user.username or 'N/A'}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        else:
            # Wrong key
            await update.message.reply_text(
                "❌ *Invalid Key!*\n\n"
                "The key you provided is incorrect.\n"
                "Please try again with the correct key.\n\n"
                "Format: `/key YOUR_KEY`",
                parse_mode='Markdown'
            )
    else:
        # User didn't use the /key command format
        await update.message.reply_text(
            "Please use the correct format:\n"
            "`/key YOUR_KEY`\n\n"
            "Replace YOUR_KEY with the actual key.",
            parse_mode='Markdown'
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu with video button"""
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    
    # Admin auto-authentication check
    if is_admin(user_id):
        if user_id_str not in user_data:
            user_data[user_id_str] = {
                'authenticated': True,
                'is_admin': True,
                'joined_at': datetime.now().isoformat(),
                'videos_watched': 0,
                'last_activity': datetime.now().isoformat()
            }
            save_data()
        elif not user_data[user_id_str].get('authenticated', False):
            user_data[user_id_str]['authenticated'] = True
            user_data[user_id_str]['is_admin'] = True
            save_data()
    
    if user_id_str not in user_data or not user_data[user_id_str].get('authenticated', False):
        if update.callback_query:
            await update.callback_query.message.edit_text(
                "⚠️ You need to authenticate first.\n"
                "Use the /key command to enter your key."
            )
            await update.callback_query.answer()
        else:
            await update.message.reply_text(
                "⚠️ You need to authenticate first.\n"
                "Use the /key command to enter your key."
            )
        return
    
    # Update last activity
    user_data[user_id_str]['last_activity'] = datetime.now().isoformat()
    save_data()
    
    keyboard = [
        [InlineKeyboardButton("🎬 Get Random Video", callback_data='get_video')],
        [InlineKeyboardButton("📊 My Stats", callback_data='my_stats')],
        [InlineKeyboardButton("❓ Help", callback_data='help_user')]
    ]
    
    # Add admin buttons if user is admin
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    videos = get_video_files()
    videos_count = len(videos)
    
    # Admin greeting
    if is_admin(user_id):
        greeting = f"👑 Welcome Admin, {update.effective_user.first_name}!"
    else:
        greeting = f"👋 Welcome, {update.effective_user.first_name}!"
    
    message_text = (
        "🎥 *Video Bot*\n\n"
        f"{greeting}\n"
        f"📁 Available videos: {videos_count}\n"
        f"🎬 Videos watched: {user_data[user_id_str].get('videos_watched', 0)}\n\n"
        "Click the button below to receive a random video.\n"
        "The video message will be automatically deleted after 30 minutes."
    )
    
    # Handle both callback queries and direct messages
    if update.callback_query:
        await update.callback_query.message.edit_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        await update.callback_query.answer()
    else:
        await update.message.reply_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

# ==================== ADMIN COMMANDS ====================

async def give_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give admin access to a user"""
    user_id = update.effective_user.id
    
    # Check if the command user is admin
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    # Check if user ID is provided
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a user ID.\n"
            "Usage: `/giveadmin USER_ID`\n\n"
            "Example: `/giveadmin 123456789`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid user ID. Please provide a valid numeric ID.\n"
            "Usage: `/giveadmin USER_ID`",
            parse_mode='Markdown'
        )
        return
    
    # Check if user is already an admin
    if new_admin_id in ADMIN_IDS:
        await update.message.reply_text(
            f"ℹ️ User `{new_admin_id}` is already an admin.",
            parse_mode='Markdown'
        )
        return
    
    # Add to admin list
    ADMIN_IDS.append(new_admin_id)
    save_admin_ids()  # Save to file
    
    # Update user data
    user_id_str = str(new_admin_id)
    if user_id_str not in user_data:
        user_data[user_id_str] = {
            'authenticated': True,
            'is_admin': True,
            'joined_at': datetime.now().isoformat(),
            'videos_watched': 0,
            'last_activity': datetime.now().isoformat()
        }
    else:
        user_data[user_id_str]['authenticated'] = True
        user_data[user_id_str]['is_admin'] = True
    save_data()
    
    # Notify the new admin
    try:
        await context.bot.send_message(
            new_admin_id,
            "👑 *Congratulations!*\n\n"
            "You have been granted admin access to the Video Bot!\n"
            "You now have full access to all admin features.\n"
            "Use /admin to access the admin panel.",
            parse_mode='Markdown'
        )
    except:
        pass
    
    # Confirm to the admin who gave the command
    await update.message.reply_text(
        f"✅ *Admin Added Successfully!*\n\n"
        f"User ID: `{new_admin_id}`\n"
        f"Total admins now: {len(ADMIN_IDS)}\n\n"
        f"The user has been notified.",
        parse_mode='Markdown'
    )

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove admin access from a user"""
    user_id = update.effective_user.id
    
    # Check if the command user is admin
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    # Check if user ID is provided
    if not context.args:
        # Show list of admins
        if len(ADMIN_IDS) <= 1:
            await update.message.reply_text(
                "⚠️ You are the only admin. You cannot remove yourself if you're the last admin.\n\n"
                "Usage: `/rmadmin USER_ID`\n"
                "Example: `/rmadmin 123456789`"
            )
            return
        
        message = "👑 *Current Admins:*\n\n"
        for idx, admin_id in enumerate(ADMIN_IDS, 1):
            # Try to get user info
            try:
                user_info = await context.bot.get_chat(admin_id)
                name = user_info.first_name or "Unknown"
                username = f"(@{user_info.username})" if user_info.username else ""
                message += f"{idx}. `{admin_id}` - {name} {username}\n"
            except:
                message += f"{idx}. `{admin_id}`\n"
        
        message += "\n\nUsage: `/rmadmin USER_ID`\n"
        message += "Example: `/rmadmin 123456789`"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    try:
        remove_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid user ID. Please provide a valid numeric ID.\n"
            "Usage: `/rmadmin USER_ID`",
            parse_mode='Markdown'
        )
        return
    
    # Check if user is an admin
    if remove_admin_id not in ADMIN_IDS:
        await update.message.reply_text(
            f"❌ User `{remove_admin_id}` is not an admin.",
            parse_mode='Markdown'
        )
        return
    
    # Check if trying to remove self
    if remove_admin_id == user_id:
        if len(ADMIN_IDS) <= 1:
            await update.message.reply_text(
                "⚠️ You cannot remove yourself as you're the only admin.\n"
                "Please add another admin first using /giveadmin",
                parse_mode='Markdown'
            )
            return
        else:
            # Ask for confirmation
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, Remove Me", callback_data=f'confirm_remove_self_{remove_admin_id}'),
                    InlineKeyboardButton("❌ No, Cancel", callback_data='cancel_remove_admin')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"⚠️ *Warning!*\n\n"
                f"You are about to remove YOURSELF as an admin.\n"
                f"This action cannot be undone easily.\n\n"
                f"Are you sure you want to proceed?",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
    
    # Remove from admin list
    ADMIN_IDS.remove(remove_admin_id)
    save_admin_ids()  # Save to file
    
    # Update user data
    user_id_str = str(remove_admin_id)
    if user_id_str in user_data:
        user_data[user_id_str]['is_admin'] = False
        save_data()
    
    # Notify the removed admin
    try:
        await context.bot.send_message(
            remove_admin_id,
            "⚠️ *Admin Access Removed*\n\n"
            "Your admin access to the Video Bot has been revoked.\n"
            "You will still have regular user access.\n\n"
            "If you think this is a mistake, contact another admin.",
            parse_mode='Markdown'
        )
    except:
        pass
    
    # Confirm to the admin who removed
    await update.message.reply_text(
        f"✅ *Admin Removed Successfully!*\n\n"
        f"User ID: `{remove_admin_id}`\n"
        f"Remaining admins: {len(ADMIN_IDS)}\n\n"
        f"The user has been notified.",
        parse_mode='Markdown'
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized access!")
        return
    
    videos = get_video_files()
    videos_count = len(videos)
    users_count = len(user_data)
    authenticated_users = sum(1 for u in user_data.values() if u.get('authenticated', False))
    
    # Get video folder size
    folder_size = 0
    if os.path.exists(VIDEOS_DIR):
        for path, dirs, files in os.walk(VIDEOS_DIR):
            for f in files:
                fp = os.path.join(path, f)
                if os.path.isfile(fp):
                    folder_size += os.path.getsize(fp)
    folder_size_str = get_file_size_from_bytes(folder_size)
    
    keyboard = [
        [InlineKeyboardButton("📤 Upload Videos", callback_data='admin_upload')],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data='admin_broadcast')],
        [InlineKeyboardButton("👥 User List", callback_data='admin_users')],
        [InlineKeyboardButton("📊 Stats", callback_data='admin_stats')],
        [InlineKeyboardButton("🎬 Manage Videos", callback_data='admin_videos')],
        [InlineKeyboardButton("🔑 Manage Keys", callback_data='admin_keys')],
        [InlineKeyboardButton("👑 Manage Admins", callback_data='admin_manage_admins')],
        [InlineKeyboardButton("🔄 Refresh", callback_data='admin_refresh')],
        [InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "⚙️ *Admin Panel*\n\n"
        f"📊 Total Users: {users_count}\n"
        f"✅ Active Users: {authenticated_users}\n"
        f"👑 Admins: {len(ADMIN_IDS)}\n"
        f"📁 Videos Available: {videos_count}\n"
        f"💾 Storage Used: {folder_size_str}\n"
        f"⏳ Pending Deletions: {len(pending_deletions)}\n\n"
        "Select an option:"
    )
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin management options"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    message = "👑 *Manage Admins*\n\n"
    message += f"Total Admins: {len(ADMIN_IDS)}\n\n"
    message += "📋 *Current Admins:*\n"
    
    for idx, admin_id in enumerate(ADMIN_IDS, 1):
        try:
            user_info = await context.bot.get_chat(admin_id)
            name = user_info.first_name or "Unknown"
            username = f"(@{user_info.username})" if user_info.username else ""
            is_self = " (You)" if admin_id == user_id else ""
            message += f"{idx}. `{admin_id}` - {name} {username}{is_self}\n"
        except:
            message += f"{idx}. `{admin_id}`\n"
    
    message += "\n📌 *Commands:*\n"
    message += "• `/giveadmin USER_ID` - Add new admin\n"
    message += "• `/rmadmin USER_ID` - Remove admin\n"
    message += "• `/listadmins` - Show all admins"
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins"""
    user_id = update.effective_user.id
    
    # Check if the command user is admin
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    if not ADMIN_IDS:
        await update.message.reply_text("❌ No admins found.")
        return
    
    message = "👑 *Admin List*\n\n"
    for idx, admin_id in enumerate(ADMIN_IDS, 1):
        try:
            user_info = await context.bot.get_chat(admin_id)
            name = user_info.first_name or "Unknown"
            username = f"(@{user_info.username})" if user_info.username else ""
            is_self = " (You)" if admin_id == user_id else ""
            message += f"{idx}. `{admin_id}` - {name} {username}{is_self}\n"
        except:
            message += f"{idx}. `{admin_id}`\n"
    
    message += f"\nTotal: {len(ADMIN_IDS)} admins"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def admin_upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start video upload process"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Store that admin is in upload mode
    uploading_admins[user_id] = True
    uploading_admins[f"{user_id}_count"] = 0
    uploading_admins[f"{user_id}_videos"] = []
    
    keyboard = [[InlineKeyboardButton("❌ Cancel Upload", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(
        "📤 *Upload Videos*\n\n"
        "Please send the video files you want to upload.\n"
        "You can send multiple videos one by one.\n"
        "Supported formats: MP4, AVI, MOV, MKV, WEBM, etc.\n\n"
        "⚠️ *Important:*\n"
        "• No file size limit (Telegram allows up to 2GB)\n"
        "• Videos will be saved to the 'videos' folder\n"
        "• Each video will get a permanent ID\n"
        "• Send one video at a time\n"
        "• Type /done when you're finished uploading\n"
        "• Type /cancel to cancel upload\n\n"
        "📤 Send your first video now:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    await query.answer()

async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video upload from admin (supports bulk upload)"""
    user_id = update.effective_user.id
    
    # Check if admin is in upload mode
    if user_id not in uploading_admins or not uploading_admins.get(user_id, False):
        return
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized!")
        return
    
    # Check if it's a video
    if not update.message.video:
        await update.message.reply_text(
            "❌ Please send a valid video file.\n"
            "Send /done when finished or /cancel to cancel."
        )
        return
    
    try:
        video = update.message.video
        file_id = video.file_id
        file_name = video.file_name or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        
        # Clean filename
        file_name = file_name.replace('/', '_').replace('\\', '_')
        
        # Get file (no size check - Telegram handles it)
        file = await context.bot.get_file(file_id)
        file_path = os.path.join(VIDEOS_DIR, file_name)
        
        # Check if file already exists
        if os.path.exists(file_path):
            base, ext = os.path.splitext(file_name)
            counter = 1
            while os.path.exists(os.path.join(VIDEOS_DIR, f"{base}_{counter}{ext}")):
                counter += 1
            file_name = f"{base}_{counter}{ext}"
            file_path = os.path.join(VIDEOS_DIR, file_name)
        
        # Send download progress
        status_msg = await update.message.reply_text(f"📥 Downloading '{file_name}'... Please wait.")
        
        # Download file
        await file.download_to_drive(file_path)
        
        file_size = get_file_size(file_path)
        
        # Add to video database with permanent ID
        new_id = str(len(video_database) + 1)
        video_database[new_id] = {
            'name': file_name,
            'path': file_path,
            'size': file_size,
            'size_bytes': os.path.getsize(file_path),
            'upload_date': datetime.now().isoformat(),
            'uploaded_by': user_id
        }
        save_video_database()
        
        # Track uploaded videos for bulk upload
        if f"{user_id}_videos" not in uploading_admins:
            uploading_admins[f"{user_id}_videos"] = []
        uploading_admins[f"{user_id}_videos"].append({
            'id': int(new_id),
            'name': file_name,
            'size': file_size
        })
        
        # Update count
        uploading_admins[f"{user_id}_count"] = uploading_admins.get(f"{user_id}_count", 0) + 1
        
        await status_msg.edit_text(
            f"✅ *Video Uploaded Successfully!*\n\n"
            f"🆔 *Permanent ID:* `{new_id}`\n"
            f"📹 Name: {file_name}\n"
            f"📦 Size: {file_size}\n"
            f"📊 Uploaded: {uploading_admins[f'{user_id}_count']} video(s) so far\n\n"
            f"Send another video, or type /done to finish.",
            parse_mode='Markdown'
        )
        
        # Notify all admins about new video
        for admin_id in ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📹 *New Video Uploaded*\n\n"
                        f"Uploaded by: {update.effective_user.first_name}\n"
                        f"ID: `{new_id}`\n"
                        f"File: {file_name}\n"
                        f"Size: {file_size}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                
    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        await update.message.reply_text(f"❌ Error uploading video: {str(e)}")

async def done_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish bulk upload process"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized!")
        return
    
    if user_id not in uploading_admins or not uploading_admins.get(user_id, False):
        await update.message.reply_text("❌ You're not in upload mode.")
        return
    
    count = uploading_admins.get(f"{user_id}_count", 0)
    videos = uploading_admins.get(f"{user_id}_videos", [])
    
    if count == 0:
        await update.message.reply_text(
            "❌ No videos were uploaded.\n"
            "Send /cancel to exit upload mode."
        )
        return
    
    # Create summary
    message = f"✅ *Bulk Upload Complete!*\n\n"
    message += f"📊 Total videos uploaded: {count}\n\n"
    message += "📹 *Uploaded Videos:*\n"
    for video in videos[:20]:
        message += f"• ID: `{video['id']}` - {video['name']} ({video['size']})\n"
    
    if len(videos) > 20:
        message += f"\n... and {len(videos) - 20} more videos\n"
    
    message += f"\n💡 Total videos available: {len(get_video_files())}"
    
    # Clear upload mode
    uploading_admins[user_id] = False
    uploading_admins[f"{user_id}_count"] = 0
    uploading_admins[f"{user_id}_videos"] = []
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Back to Admin Panel", callback_data='admin_panel')],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast functionality"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Store the fact that we're in broadcast mode
    context.user_data['broadcast_mode'] = True
    
    keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(
        "📢 *Broadcast Message*\n\n"
        "Please send the message you want to broadcast to all users.\n"
        "You can use text, images, videos, or any other media.\n\n"
        "*Note:* This will send the message to ALL authenticated users.\n"
        "Type /cancel to cancel broadcast.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    await query.answer()

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message sending"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized!")
        return
    
    # Check if in broadcast mode
    if not context.user_data.get('broadcast_mode', False):
        return
    
    # Get all authenticated users
    authenticated_users = [uid for uid, data in user_data.items() if data.get('authenticated', False)]
    
    if not authenticated_users:
        await update.message.reply_text("❌ No authenticated users to broadcast to!")
        context.user_data['broadcast_mode'] = False
        return
    
    # Send initial message
    status_msg = await update.message.reply_text(
        f"📢 Starting broadcast to {len(authenticated_users)} users..."
    )
    
    success_count = 0
    fail_count = 0
    
    # Send the message to each user
    for user_id_str in authenticated_users:
        try:
            # Copy the message to each user
            await update.message.copy(user_id_str)
            success_count += 1
            await asyncio.sleep(0.1)  # To avoid rate limiting
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id_str}: {e}")
            fail_count += 1
    
    # Update status message with inline buttons
    keyboard = [
        [InlineKeyboardButton("⚙️ Admin Panel", callback_data='admin_panel')],
        [InlineKeyboardButton("🔙 Main Menu", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await status_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"📤 Sent to: {success_count} users\n"
        f"❌ Failed: {fail_count} users\n"
        f"📊 Total: {len(authenticated_users)} users",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    # Exit broadcast mode
    context.user_data['broadcast_mode'] = False

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of users"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    users_list = []
    for uid, data in user_data.items():
        if data.get('authenticated', False):
            is_admin_user = data.get('is_admin', False) or int(uid) in ADMIN_IDS
            role = "👑" if is_admin_user else "👤"
            videos = data.get('videos_watched', 0)
            users_list.append(f"{role} ID: `{uid}` - {videos} videos")
    
    if not users_list:
        message = "👥 No authenticated users found."
    else:
        message = f"👥 *User List*\n\n{chr(10).join(users_list[:50])}"
        if len(users_list) > 50:
            message += f"\n\n... and {len(users_list) - 50} more users"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data='admin_users')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    videos = get_video_files()
    videos_count = len(videos)
    users_count = len(user_data)
    authenticated_users = sum(1 for u in user_data.values() if u.get('authenticated', False))
    total_videos_watched = sum(u.get('videos_watched', 0) for u in user_data.values())
    
    # Calculate active users (last 7 days)
    week_ago = datetime.now() - timedelta(days=7)
    active_users = 0
    for data in user_data.values():
        if data.get('authenticated', False):
            last_activity = data.get('last_activity')
            if last_activity:
                try:
                    last_time = datetime.fromisoformat(last_activity)
                    if last_time > week_ago:
                        active_users += 1
                except:
                    pass
    
    # Get video folder size
    folder_size = 0
    for video in videos:
        try:
            folder_size += os.path.getsize(video['path'])
        except:
            pass
    folder_size_str = get_file_size_from_bytes(folder_size)
    
    message = (
        "📊 *Bot Statistics*\n\n"
        f"👥 Total Users: {users_count}\n"
        f"✅ Authenticated: {authenticated_users}\n"
        f"👑 Admins: {len(ADMIN_IDS)}\n"
        f"🟢 Active (7 days): {active_users}\n"
        f"🎬 Videos Watched: {total_videos_watched}\n"
        f"📁 Videos Available: {videos_count}\n"
        f"💾 Storage Used: {folder_size_str}\n"
        f"⏳ Pending Deletions: {len(pending_deletions)}\n\n"
        f"📈 Average videos/user: {total_videos_watched / max(authenticated_users, 1):.1f}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data='admin_stats')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage videos"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    videos = get_video_files()
    
    message = "🎬 *Video Management*\n\n"
    if videos:
        message += f"📁 Total videos: {len(videos)}\n\n"
        message += "📹 *Video List with Permanent IDs:*\n"
        
        # Show video details with ID and file size
        for video in videos[:20]:
            message += f"`{video['id']:3d}`. {video['name']} ({video['size']})\n"
        
        if len(videos) > 20:
            message += f"\n... and {len(videos) - 20} more videos\n"
        
        message += "\n💡 To delete a video from the folder (permanent), use:\n"
        message += "`/rmvideo VIDEO_ID`\n"
        message += "Example: `/rmvideo 5`\n\n"
        message += "📤 To add videos, use the 'Upload Videos' button below."
    else:
        message += "❌ No videos found in the folder."
    
    keyboard = [
        [InlineKeyboardButton("📤 Upload Videos", callback_data='admin_upload')],
        [InlineKeyboardButton("🔄 Refresh List", callback_data='admin_videos')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage keys"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Generate a random key (for demonstration)
    import string
    import random as rand
    new_key = ''.join(rand.choices(string.ascii_uppercase + string.digits, k=8))
    
    message = (
        "🔑 *Key Management*\n\n"
        f"Current key: `{SECRET_KEY}`\n\n"
        "ℹ️ To change the key, modify the `SECRET_KEY` variable in the code.\n\n"
        "📋 *User Stats:*\n"
        f"• Total users: {len(user_data)}\n"
        f"• Authenticated: {sum(1 for u in user_data.values() if u.get('authenticated', False))}\n"
        f"• Admins: {len(ADMIN_IDS)}\n\n"
        f"💡 *Generated Key:* `{new_key}` (for demo only)\n\n"
        "📌 *Admins:* You don't need a key - you have automatic access!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh admin panel"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Rebuild database to sync with filesystem
    rebuild_video_database()
    
    await query.answer("🔄 Refreshing...")
    await admin_panel(update, context)

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin commands"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use admin commands.")
        return
    
    # Auto-authenticate admin
    user_id_str = str(user_id)
    if user_id_str not in user_data:
        user_data[user_id_str] = {
            'authenticated': True,
            'is_admin': True,
            'joined_at': datetime.now().isoformat(),
            'videos_watched': 0,
            'last_activity': datetime.now().isoformat()
        }
        save_data()
    
    text = update.message.text
    
    if text == '/admin':
        # Send admin panel via message with inline buttons
        videos = get_video_files()
        videos_count = len(videos)
        users_count = len(user_data)
        authenticated_users = sum(1 for u in user_data.values() if u.get('authenticated', False))
        
        keyboard = [
            [InlineKeyboardButton("📤 Upload Videos", callback_data='admin_upload')],
            [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("👥 Users", callback_data='admin_users')],
            [InlineKeyboardButton("📊 Stats", callback_data='admin_stats')],
            [InlineKeyboardButton("🎬 Videos", callback_data='admin_videos')],
            [InlineKeyboardButton("🔑 Keys", callback_data='admin_keys')],
            [InlineKeyboardButton("👑 Manage Admins", callback_data='admin_manage_admins')],
            [InlineKeyboardButton("🔙 Main Menu", callback_data='back_to_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "⚙️ *Admin Panel*\n\n"
            f"📊 Total Users: {users_count}\n"
            f"✅ Active Users: {authenticated_users}\n"
            f"👑 Admins: {len(ADMIN_IDS)}\n"
            f"📁 Videos: {videos_count}"
        )
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

# ==================== HELPER FUNCTIONS ====================

async def help_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help to user"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check if user is admin
    if is_admin(user_id):
        help_text = (
            "❓ *Admin Help Center*\n\n"
            "🤖 *Admin Features:*\n"
            "• Upload multiple videos (bulk upload)\n"
            "• Forward videos from other chats\n"
            "• Permanent video IDs (never change)\n"
            "• Broadcast messages to all users\n"
            "• View user statistics\n"
            "• Manage videos\n"
            "• View all users\n"
            "• Give/Remove admin access\n"
            "• Delete videos from folder\n\n"
            "📌 *Admin Commands:*\n"
            "/start - Start the bot\n"
            "/admin - Admin panel\n"
            "/giveadmin USER_ID - Give admin access\n"
            "/rmadmin USER_ID - Remove admin access\n"
            "/listadmins - List all admins\n"
            "/rmvideo VIDEO_ID - Delete video from folder\n"
            "/listvideos - List all videos with IDs\n"
            "/done - Finish bulk upload\n"
            "/cancel - Cancel current operation\n\n"
            "💡 You have automatic access - no key needed!"
        )
    else:
        help_text = (
            "❓ *Help Center*\n\n"
            "🤖 *How to use the bot:*\n"
            "1. Use /start to begin\n"
            "2. Enter the key using /key KEY\n"
            "3. Click 'Get Random Video' to watch\n"
            "4. Video messages auto-delete after 30 minutes\n\n"
            "📌 *Commands:*\n"
            "/start - Start the bot\n"
            "/key - Enter your key\n"
            "/admin - Admin panel (admins only)\n"
            "/cancel - Cancel current operation\n\n"
            "💡 *Need help?* Contact the administrator."
        )
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu"""
    query = update.callback_query
    await show_main_menu(update, context)

async def delete_expired_videos(context: ContextTypes.DEFAULT_TYPE):
    """Background task to delete expired video messages from chat"""
    now = datetime.now()
    to_delete = []
    
    for item in pending_deletions:
        if item['delete_time'] <= now:
            to_delete.append(item)
    
    for item in to_delete:
        try:
            await context.bot.delete_message(
                chat_id=item['chat_id'],
                message_id=item['message_id']
            )
            logger.info(f"Deleted video message '{item.get('video_name', 'unknown')}' for user {item['user_id']}")
            pending_deletions.remove(item)
        except Exception as e:
            logger.error(f"Error deleting video message: {e}")
            pending_deletions.remove(item)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if it's a key command
    if text and text.startswith('/key'):
        await handle_key(update, context)
    elif text and text.startswith('/admin'):
        await handle_admin_commands(update, context)
    elif text and text.startswith('/giveadmin'):
        await give_admin(update, context)
    elif text and text.startswith('/rmadmin'):
        await remove_admin(update, context)
    elif text and text.startswith('/listadmins'):
        await list_admins(update, context)
    elif text and text.startswith('/rmvideo'):
        await remove_video(update, context)
    elif text and text.startswith('/listvideos'):
        await list_videos(update, context)
    elif text and text.startswith('/done'):
        await done_upload(update, context)
    elif text and text.startswith('/cancel'):
        if context.user_data.get('broadcast_mode', False):
            context.user_data['broadcast_mode'] = False
            await update.message.reply_text("✅ Broadcast cancelled.")
        elif user_id in uploading_admins and uploading_admins.get(user_id, False):
            uploading_admins[user_id] = False
            uploading_admins[f"{user_id}_count"] = 0
            uploading_admins[f"{user_id}_videos"] = []
            await update.message.reply_text("✅ Upload cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")
    elif context.user_data.get('broadcast_mode', False):
        # Handle broadcast message
        await handle_broadcast(update, context)
    elif user_id in uploading_admins and uploading_admins.get(user_id, False):
        # Handle video upload (including forwarded videos)
        await handle_video_upload(update, context)
    else:
        # Unknown command
        await update.message.reply_text(
            "❓ Unknown command.\n"
            "Use /start to begin or /key to enter your key."
        )

async def remove_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a video from the folder (permanent deletion)"""
    user_id = update.effective_user.id
    
    # Check if the command user is admin
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    # Check if video ID is provided
    if not context.args:
        # Show list of videos with IDs
        videos = get_video_files()
        if not videos:
            await update.message.reply_text("❌ No videos found in the folder.")
            return
        
        message = "📹 *Available Videos with IDs:*\n\n"
        for video in videos[:20]:
            message += f"`{video['id']}`. {video['name']} ({video['size']})\n"
        
        if len(videos) > 20:
            message += f"\n... and {len(videos) - 20} more videos"
        
        message += "\n\nUsage: `/rmvideo VIDEO_ID`\n"
        message += "Example: `/rmvideo 5`\n\n"
        message += "💡 To see all videos, use `/listvideos`"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    try:
        video_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid video ID. Please provide a valid numeric ID.\n"
            "Usage: `/rmvideo VIDEO_ID`",
            parse_mode='Markdown'
        )
        return
    
    # Find the video
    video = get_video_by_id(video_id)
    if not video:
        await update.message.reply_text(
            f"❌ Video with ID `{video_id}` not found.\n"
            "Use `/listvideos` to see all available videos.",
            parse_mode='Markdown'
        )
        return
    
    # Ask for confirmation before permanent deletion
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete Permanently", callback_data=f'confirm_delete_video_{video_id}'),
            InlineKeyboardButton("❌ No, Cancel", callback_data='cancel_delete_video')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚠️ *WARNING: Permanent Deletion*\n\n"
        f"You are about to permanently delete this video from the folder:\n"
        f"📹 Name: {video['name']}\n"
        f"🆔 ID: {video_id}\n"
        f"📦 Size: {video['size']}\n\n"
        f"This action CANNOT be undone!\n\n"
        f"Are you sure you want to proceed?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def list_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all videos with their IDs"""
    user_id = update.effective_user.id
    
    # Check if the command user is admin
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    videos = get_video_files()
    
    if not videos:
        await update.message.reply_text("❌ No videos found in the folder.")
        return
    
    message = "📹 *Complete Video List (Permanent IDs):*\n\n"
    
    # Show all videos with IDs
    for video in videos:
        message += f"`{video['id']:3d}`. {video['name']} ({video['size']})\n"
        
        # Split into multiple messages if too long
        if len(message) > 4000:
            await update.message.reply_text(message, parse_mode='Markdown')
            message = ""
    
    if message:
        await update.message.reply_text(message, parse_mode='Markdown')
    
    # Show usage info
    await update.message.reply_text(
        "💡 To permanently delete a video from the folder, use:\n"
        "`/rmvideo VIDEO_ID`\n\n"
        "Example: `/rmvideo 5`\n\n"
        "⚠️ This will delete the video file permanently!",
        parse_mode='Markdown'
    )

# ==================== MAIN FUNCTION ====================

def main():
    """Start the bot"""
    # Load data
    load_data()
    load_admin_ids()
    load_video_database()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("key", handle_key))
    application.add_handler(CommandHandler("admin", handle_admin_commands))
    application.add_handler(CommandHandler("giveadmin", give_admin))
    application.add_handler(CommandHandler("rmadmin", remove_admin))
    application.add_handler(CommandHandler("listadmins", list_admins))
    application.add_handler(CommandHandler("rmvideo", remove_video))
    application.add_handler(CommandHandler("listvideos", list_videos))
    application.add_handler(CommandHandler("done", done_upload))
    application.add_handler(CommandHandler("cancel", handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VIDEO, handle_message))  # Handle video uploads
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_broadcast))
    
    # Add job queue for video deletion (run every minute)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(delete_expired_videos, interval=60, first=10)
    
    # Start the bot
    print("=" * 50)
    print("🤖 Bot is starting...")
    print(f"📁 Videos directory: {os.path.abspath(VIDEOS_DIR)}")
    print(f"🎬 Available videos: {len(get_video_files())}")
    print(f"👥 Loaded users: {len(user_data)}")
    print(f"🛡️ Admins: {len(ADMIN_IDS)}")
    print("=" * 50)
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# Callback handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'get_video':
        await send_video(update, context)
    elif query.data == 'next_video':
        # Send another video without returning to menu
        await send_video(update, context)
    elif query.data == 'my_stats':
        await show_user_stats(update, context)
    elif query.data == 'help_user' or query.data == 'help_key':
        await help_user(update, context)
    elif query.data == 'back_to_menu':
        await back_to_menu(update, context)
    elif query.data == 'admin_panel':
        await admin_panel(update, context)
    elif query.data == 'admin_upload':
        await admin_upload_start(update, context)
    elif query.data == 'admin_broadcast':
        await admin_broadcast(update, context)
    elif query.data == 'admin_users':
        await admin_users(update, context)
    elif query.data == 'admin_stats':
        await admin_stats(update, context)
    elif query.data == 'admin_videos':
        await admin_videos(update, context)
    elif query.data == 'admin_keys':
        await admin_keys(update, context)
    elif query.data == 'admin_manage_admins':
        await admin_manage_admins(update, context)
    elif query.data == 'admin_refresh':
        await admin_refresh(update, context)
    elif query.data.startswith('confirm_remove_self_'):
        # Handle self-removal confirmation
        admin_id = int(query.data.replace('confirm_remove_self_', ''))
        await confirm_remove_self(update, context, admin_id)
    elif query.data == 'cancel_remove_admin':
        await query.message.edit_text("✅ Admin removal cancelled.")
        await admin_panel(update, context)
    elif query.data.startswith('confirm_delete_video_'):
        # Handle video deletion confirmation
        video_id = int(query.data.replace('confirm_delete_video_', ''))
        await confirm_delete_video(update, context, video_id)
    elif query.data == 'cancel_delete_video':
        await query.message.edit_text("✅ Video deletion cancelled.")
        await admin_panel(update, context)
    else:
        await query.message.reply_text("Unknown action!")

async def confirm_delete_video(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id):
    """Confirm permanent video deletion from folder"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Find the video
    video = get_video_by_id(video_id)
    if not video:
        await query.message.edit_text(
            f"❌ Video with ID `{video_id}` not found.",
            parse_mode='Markdown'
        )
        return
    
    # Delete the video file
    try:
        os.remove(video['path'])
        
        # Remove from database
        if str(video_id) in video_database:
            del video_database[str(video_id)]
            save_video_database()
        
        # Log the deletion
        logger.info(f"Video '{video['name']}' (ID: {video_id}) permanently deleted by admin {user_id}")
        
        await query.message.edit_text(
            f"✅ *Video Permanently Deleted!*\n\n"
            f"📹 Name: {video['name']}\n"
            f"🆔 ID: {video_id}\n"
            f"📦 Size: {video['size']}\n\n"
            f"Remaining videos: {len(get_video_files())}\n\n"
            f"⚠️ This video has been removed from the folder.",
            parse_mode='Markdown'
        )
        
        # Notify other admins
        for admin_id in ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🗑️ *Video Permanently Deleted*\n\n"
                        f"Deleted by: {update.effective_user.first_name}\n"
                        f"Video: {video['name']}\n"
                        f"ID: {video_id}\n"
                        f"⚠️ This video has been removed from the folder.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                
    except Exception as e:
        logger.error(f"Error deleting video: {e}")
        await query.message.edit_text(
            f"❌ Error deleting video: {str(e)}"
        )

async def confirm_remove_self(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id):
    """Confirm self-removal of admin"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Verify it's the same user
    if user_id != admin_id:
        await query.answer("⛔ You can only remove yourself!")
        return
    
    # Check if trying to remove self
    if len(ADMIN_IDS) <= 1:
        await query.answer("⚠️ Cannot remove yourself as you're the only admin!")
        return
    
    # Remove from admin list
    ADMIN_IDS.remove(admin_id)
    save_admin_ids()
    
    # Update user data
    user_id_str = str(admin_id)
    if user_id_str in user_data:
        user_data[user_id_str]['is_admin'] = False
        save_data()
    
    await query.message.edit_text(
        "✅ *You have been removed as an admin.*\n\n"
        "You will now have regular user access.\n"
        "If you need admin access again, contact another admin.",
        parse_mode='Markdown'
    )
    
    # Show main menu
    await show_main_menu(update, context)

async def send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random video to the user with Next Video button"""
    # Determine if it's a callback query or direct message
    if update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        user_id_str = str(user_id)
        is_callback = True
        message_obj = query.message
    else:
        # Not used directly from command, but for completeness
        return
    
    # Check authentication (admin auto-auth)
    if is_admin(user_id):
        if user_id_str not in user_data:
            user_data[user_id_str] = {'authenticated': True, 'is_admin': True}
            save_data()
        elif not user_data[user_id_str].get('authenticated', False):
            user_data[user_id_str]['authenticated'] = True
            user_data[user_id_str]['is_admin'] = True
            save_data()
    
    if user_id_str not in user_data or not user_data[user_id_str].get('authenticated', False):
        await query.answer("⚠️ Please authenticate first using /key")
        return
    
    # Get list of videos
    videos = get_video_files()
    
    if not videos:
        await query.answer("❌ No videos available in the folder!")
        return
    
    # Select a random video
    selected_video = random.choice(videos)
    video_name = selected_video['name']
    video_size = selected_video['size']
    video_id = selected_video['id']
    
    try:
        # Send "loading" message
        if is_callback:
            await query.answer("📤 Sending video...")
        
        # Send the video with inline buttons: Next Video and Main Menu
        keyboard = [
            [
                InlineKeyboardButton("🎬 Next Video", callback_data='next_video'),
                InlineKeyboardButton("🔙 Main Menu", callback_data='back_to_menu')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        with open(selected_video['path'], 'rb') as video_file:
            sent_message = await message_obj.reply_video(
                video=video_file,
                caption=f"🎬 Here's your random video!\n\n"
                       f"⏰ This message will be deleted in 30 minutes.\n"
                       f"📹 Video: {video_name}\n"
                       f"🆔 ID: {video_id} (permanent)\n"
                       f"📦 Size: {video_size}\n\n"
                       f"💡 The video file is stored permanently.\n"
                       f"Click 'Next Video' for another random video.",
                reply_markup=reply_markup,
                supports_streaming=True
            )
        
        # Update user stats
        user_data[user_id_str]['videos_watched'] = user_data[user_id_str].get('videos_watched', 0) + 1
        user_data[user_id_str]['last_video_time'] = datetime.now().isoformat()
        save_data()
        
        # Schedule ONLY the message deletion from chat after 30 minutes
        pending_deletions.append({
            'chat_id': chat_id,
            'message_id': sent_message.message_id,
            'delete_time': datetime.now() + timedelta(minutes=30),
            'user_id': user_id,
            'video_name': video_name,
            'video_id': video_id
        })
        
        if is_callback:
            await query.answer("✅ Video sent!")
            # Do not show main menu automatically; user can click buttons
    
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        if is_callback:
            await query.answer("❌ Error sending video. Please try again.")

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    query = update.callback_query
    user_id = query.from_user.id
    user_id_str = str(user_id)
    
    # Admin auto-auth check
    if is_admin(user_id) and user_id_str not in user_data:
        user_data[user_id_str] = {'authenticated': True, 'is_admin': True}
        save_data()
    
    if user_id_str not in user_data:
        await query.answer("No data found!")
        return
    
    stats = user_data[user_id_str]
    videos_watched = stats.get('videos_watched', 0)
    joined_at = stats.get('joined_at', 'Unknown')
    is_admin_user = stats.get('is_admin', False) or is_admin(user_id)
    
    # Format join date
    try:
        join_date = datetime.fromisoformat(joined_at).strftime('%Y-%m-%d %H:%M')
    except:
        join_date = 'Unknown'
    
    message = (
        "📊 *Your Statistics*\n\n"
        f"👤 Name: {query.from_user.first_name}\n"
        f"🆔 ID: `{user_id}`\n"
        f"📅 Joined: {join_date}\n"
        f"🎬 Videos Watched: {videos_watched}\n"
        f"✅ Status: {'Active' if stats.get('authenticated', False) else 'Inactive'}\n"
        f"👑 Role: {'Admin' if is_admin_user else 'User'}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

if __name__ == '__main__':
    main()
