import os
import random
import asyncio
import logging
import json
import shutil
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
BOT_TOKEN = "8296217662:AAHjIHXtxkjYmDR-9vSPzznUNWjQxvKGgdw"

# The secret key for new users
SECRET_KEY = "Amair"

# Admin user IDs (Replace with actual admin Telegram user IDs)
ADMIN_IDS = [8159360955, ]  # Add your Telegram user IDs here

# Directory where videos are stored
VIDEOS_DIR = "videos"

# Data file for persistent storage
DATA_FILE = "bot_data.json"

# Track user authentication status and video timers
user_data = {}
pending_deletions = []
uploading_admins = {}  # Track admins who are uploading videos

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

def get_video_files():
    """Get list of video files from the videos directory"""
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.3gp', '.m4v', '.mpg', '.mpeg'}
    videos = []
    
    if os.path.exists(VIDEOS_DIR):
        for file in os.listdir(VIDEOS_DIR):
            file_path = os.path.join(VIDEOS_DIR, file)
            if os.path.isfile(file_path) and Path(file).suffix.lower() in video_extensions:
                videos.append(file_path)
    
    return sorted(videos)

def is_admin(user_id):
    """Check if a user is an admin"""
    return user_id in ADMIN_IDS

def get_file_size(file_path):
    """Get file size in human readable format"""
    size = os.path.getsize(file_path)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def get_file_size_from_bytes(size):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

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
    
    videos_count = len(get_video_files())
    
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
        "The video will be automatically deleted after 30 minutes."
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

async def send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random video to the user"""
    query = update.callback_query
    user_id = query.from_user.id
    user_id_str = str(user_id)
    
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
    video_name = os.path.basename(selected_video)
    video_size = get_file_size(selected_video)
    
    try:
        # Send "loading" message
        await query.answer("📤 Sending video...")
        
        # Send the video
        with open(selected_video, 'rb') as video_file:
            message = await query.message.reply_video(
                video=video_file,
                caption=f"🎬 Here's your random video!\n\n"
                       f"⏰ It will be deleted in 30 minutes.\n"
                       f"📹 Video: {video_name}\n"
                       f"📦 Size: {video_size}",
                supports_streaming=True
            )
        
        # Update user stats
        user_data[user_id_str]['videos_watched'] = user_data[user_id_str].get('videos_watched', 0) + 1
        user_data[user_id_str]['last_video_time'] = datetime.now().isoformat()
        save_data()
        
        # Schedule video deletion after 30 minutes
        chat_id = query.message.chat_id
        message_id = message.message_id
        
        # Store for deletion
        pending_deletions.append({
            'chat_id': chat_id,
            'message_id': message_id,
            'delete_time': datetime.now() + timedelta(minutes=30),
            'user_id': user_id,
            'video_name': video_name
        })
        
        await query.answer("✅ Video sent successfully!")
        
        # Show main menu again after a short delay
        await asyncio.sleep(1)
        # Create a new callback query to return to menu
        await show_main_menu(update, context)
    
    except Exception as e:
        logger.error(f"Error sending video: {e}")
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
    is_admin_user = stats.get('is_admin', False)
    
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

# ==================== ADMIN COMMANDS ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized access!")
        return
    
    videos_count = len(get_video_files())
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
        [InlineKeyboardButton("📤 Upload Video", callback_data='admin_upload')],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data='admin_broadcast')],
        [InlineKeyboardButton("👥 User List", callback_data='admin_users')],
        [InlineKeyboardButton("📊 Stats", callback_data='admin_stats')],
        [InlineKeyboardButton("🎬 Manage Videos", callback_data='admin_videos')],
        [InlineKeyboardButton("🔑 Manage Keys", callback_data='admin_keys')],
        [InlineKeyboardButton("🔄 Refresh", callback_data='admin_refresh')],
        [InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "⚙️ *Admin Panel*\n\n"
        f"📊 Total Users: {users_count}\n"
        f"✅ Active Users: {authenticated_users}\n"
        f"📁 Videos Available: {videos_count}\n"
        f"💾 Storage Used: {folder_size_str}\n"
        f"⏳ Pending Deletions: {len(pending_deletions)}\n\n"
        "Select an option:"
    )
    
    await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    await query.answer()

async def admin_upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start video upload process"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Unauthorized!")
        return
    
    # Store that admin is in upload mode
    uploading_admins[user_id] = True
    
    keyboard = [[InlineKeyboardButton("❌ Cancel Upload", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(
        "📤 *Upload Video*\n\n"
        "Please send the video file you want to upload.\n"
        "Supported formats: MP4, AVI, MOV, MKV, WEBM, etc.\n\n"
        "⚠️ *Important:*\n"
        "• Maximum file size: 50MB (Telegram limit)\n"
        "• The video will be saved to the 'videos' folder\n"
        "• Type /cancel to cancel upload\n\n"
        "📤 Send your video now:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    await query.answer()

async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video upload from admin"""
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
            "Send /cancel to cancel upload."
        )
        return
    
    try:
        video = update.message.video
        file_id = video.file_id
        file_name = video.file_name or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        
        # Clean filename
        file_name = file_name.replace('/', '_').replace('\\', '_')
        
        # Get file
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
        
        # Download file
        await update.message.reply_text("📥 Downloading video... Please wait.")
        await file.download_to_drive(file_path)
        
        file_size = get_file_size(file_path)
        
        # Success message
        await update.message.reply_text(
            f"✅ *Video Uploaded Successfully!*\n\n"
            f"📹 Name: {file_name}\n"
            f"📦 Size: {file_size}\n"
            f"📁 Location: `{file_path}`\n\n"
            f"Total videos: {len(get_video_files())}",
            parse_mode='Markdown'
        )
        
        # Notify all admins
        for admin_id in ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📹 *New Video Uploaded*\n\n"
                        f"Uploaded by: {update.effective_user.first_name}\n"
                        f"File: {file_name}\n"
                        f"Size: {file_size}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        
        # Exit upload mode
        uploading_admins[user_id] = False
        
        # Show admin panel again with inline keyboard
        keyboard = [
            [InlineKeyboardButton("⚙️ Back to Admin Panel", callback_data='admin_panel')],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data='back_to_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "What would you like to do next?",
            reply_markup=reply_markup
        )
    
    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        await update.message.reply_text(f"❌ Error uploading video: {str(e)}")
        uploading_admins[user_id] = False

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
            is_admin_user = data.get('is_admin', False)
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
    admin_count = sum(1 for u in user_data.values() if u.get('is_admin', False))
    
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
        folder_size += os.path.getsize(video)
    folder_size_str = get_file_size_from_bytes(folder_size)
    
    message = (
        "📊 *Bot Statistics*\n\n"
        f"👥 Total Users: {users_count}\n"
        f"✅ Authenticated: {authenticated_users}\n"
        f"👑 Admins: {admin_count}\n"
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
        message += "📹 *Video List:*\n"
        
        # Show video details with file size
        for i, video in enumerate(videos[:20], 1):
            video_name = os.path.basename(video)
            video_size = get_file_size(video)
            message += f"{i}. {video_name} ({video_size})\n"
        
        if len(videos) > 20:
            message += f"\n... and {len(videos) - 20} more videos"
        
        message += "\n\nℹ️ To delete a video, manually remove it from the 'videos' folder."
    else:
        message += "❌ No videos found in the folder."
    
    message += "\n\n📤 To add videos, use the 'Upload Video' button in Admin Panel."
    
    keyboard = [
        [InlineKeyboardButton("📤 Upload Video", callback_data='admin_upload')],
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
        f"• Admins: {sum(1 for u in user_data.values() if u.get('is_admin', False))}\n\n"
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
        videos_count = len(get_video_files())
        users_count = len(user_data)
        authenticated_users = sum(1 for u in user_data.values() if u.get('authenticated', False))
        
        keyboard = [
            [InlineKeyboardButton("📤 Upload Video", callback_data='admin_upload')],
            [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("👥 Users", callback_data='admin_users')],
            [InlineKeyboardButton("📊 Stats", callback_data='admin_stats')],
            [InlineKeyboardButton("🎬 Videos", callback_data='admin_videos')],
            [InlineKeyboardButton("🔑 Keys", callback_data='admin_keys')],
            [InlineKeyboardButton("🔙 Main Menu", callback_data='back_to_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "⚙️ *Admin Panel*\n\n"
            f"📊 Total Users: {users_count}\n"
            f"✅ Active Users: {authenticated_users}\n"
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
            "• Upload videos via chat\n"
            "• Broadcast messages to all users\n"
            "• View user statistics\n"
            "• Manage videos\n"
            "• View all users\n\n"
            "📌 *Commands:*\n"
            "/start - Start the bot\n"
            "/admin - Admin panel\n"
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
            "4. Videos auto-delete after 30 minutes\n\n"
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
    
    # Create a new update object with the message
    # We need to pass the query to show_main_menu
    await show_main_menu(update, context)

async def delete_expired_videos(context: ContextTypes.DEFAULT_TYPE):
    """Background task to delete expired videos"""
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
            logger.info(f"Deleted video '{item.get('video_name', 'unknown')}' for user {item['user_id']}")
            pending_deletions.remove(item)
        except Exception as e:
            logger.error(f"Error deleting video: {e}")
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
    elif text and text.startswith('/cancel'):
        if context.user_data.get('broadcast_mode', False):
            context.user_data['broadcast_mode'] = False
            await update.message.reply_text("✅ Broadcast cancelled.")
        elif user_id in uploading_admins and uploading_admins.get(user_id, False):
            uploading_admins[user_id] = False
            await update.message.reply_text("✅ Upload cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")
    elif context.user_data.get('broadcast_mode', False):
        # Handle broadcast message
        await handle_broadcast(update, context)
    elif user_id in uploading_admins and uploading_admins.get(user_id, False):
        # Handle video upload
        await handle_video_upload(update, context)
    else:
        # Unknown command
        await update.message.reply_text(
            "❓ Unknown command.\n"
            "Use /start to begin or /key to enter your key."
        )

# ==================== MAIN FUNCTION ====================

def main():
    """Start the bot"""
    # Load data
    load_data()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("key", handle_key))
    application.add_handler(CommandHandler("admin", handle_admin_commands))
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
    elif query.data == 'admin_refresh':
        await admin_refresh(update, context)
    else:
        await query.message.reply_text("Unknown action!")

if __name__ == '__main__':
    main()
