# TO'LIQ TELEGRAM BOT - BARCHA KOD BIR FAYLDA
import asyncio
import logging
import os
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.client.session.aiohttp import AiohttpSession
import aiofiles
from collections import defaultdict
import time
from PIL import Image, ImageDraw, ImageFont

# =================================================================
# KONFIGURATSIYA
# =================================================================

# Bot tokeni (BotFather'dan olingan)
BOT_TOKEN = "8548676063:AAHB15B8j92JKvQWGtzgSXPKTMagFKTAbrk"  # Bu yerga o'zingizning bot tokeningizni kiriting

# Admin ID (o'zingizning Telegram ID'ingiz)
ADMIN_ID = 422057508  # Bu yerga o'zingizning Telegram ID'ingizni kiriting

# Papka yo'llari
EXCEL_FILES_DIR = "data/excel_files"
LOGS_DIR = "logs"

# Fayl nomlari
USERS_DB = "data/users.json"
STATS_FILE = "data/stats.json"
CHANNELS_DB = "data/channels.json"

# Bot sozlamalari
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_FILE_TYPES = ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]  # .xlsx

# Excel ustun nomlari
EXCEL_COLUMNS = ["ID", "Ism", "Familiya", "Fan", "Sana", "Xona"]

# =================================================================
# LOGGING SOZLAMALARI
# =================================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =================================================================
# EXCEL HANDLER KLASI
# =================================================================

class ExcelHandler:
    """Excel fayllar bilan ishlash uchun klass"""
    
    def __init__(self):
        self.excel_files = []
        self.cached_data = {}
        # Keshni tozalab yuklash
        self.load_existing_files()
    
    def load_existing_files(self):
        """Mavjud Excel fayllarini yuklash"""
        if not os.path.exists(EXCEL_FILES_DIR):
            os.makedirs(EXCEL_FILES_DIR)
            return
        
        # Keshni tozalash
        self.excel_files.clear()
        self.cached_data.clear()
        
        for file in os.listdir(EXCEL_FILES_DIR):
            if file.endswith('.xlsx'):
                self.excel_files.append(file)
                self.cache_excel_data(file)
    
    def cache_excel_data(self, filename: str):
        """Excel fayl ma'lumotlarini keshga yuklash"""
        try:
            file_path = os.path.join(EXCEL_FILES_DIR, filename)
            
            # Excel faylini o'qish, sana ustunlarini to'g'ri formatlash
            df = pd.read_excel(file_path)
            
            # ID ustunini avtomatik topish va string formatiga o'tkazish
            id_columns = ['Talaba ID', 'ID', 'Student ID', 'StudentID', 'Student_ID', 'id', 'student_id', 'studentid']
            found_id_column = None
            
            # Avval standart nomlarni qidiramiz
            for col in id_columns:
                if col in df.columns:
                    found_id_column = col
                    df[col] = df[col].astype(str).str.zfill(6)
                    print(f"DEBUG: {col} ustuni 6 xonali formatga o'tkazildi")
                    break
            
            # Agar standart nomlar topilmasa, ID ni taxmin qilish
            if not found_id_column:
                print("DEBUG: Standart ID ustunlari topilmadi, ID ni taxmin qilish...")
                for col in df.columns:
                    col_lower = col.lower().strip()
                    # ID ga o'xshash ustunlarni qidirish
                    if any(keyword in col_lower for keyword in ['id', 'raqam', 'nomer', 'number', 'student', 'talaba']):
                        # Birinchi 3 ta qiymatni tekshirish - ular raqamlarmi
                        sample_values = df[col].head(3).dropna()
                        if len(sample_values) > 0:
                            # Barcha namunalar raqamlarmi (6 xonali)
                            all_numeric = all(str(val).replace('.', '').isdigit() and len(str(val).replace('.', '')) <= 6 for val in sample_values)
                            if all_numeric:
                                found_id_column = col
                                df[col] = df[col].astype(str).str.zfill(6)
                                print(f"DEBUG: Taxminiy ID ustuni '{col}' topildi va formatlandi")
                                break
            
            if not found_id_column:
                print(f"WARNING: {filename} faylida ID ustuni topilmadi! Qidiruv ishlamaydi.")
            
            # Sana ustunlarini formatlash
            date_columns = ['Nazorat sanasi', 'Sana', 'Date', 'Дата']
            for col in date_columns:
                if col in df.columns:
                    # Excel sanalarni string formatiga o'tkazish
                    dates = pd.to_datetime(df[col], errors='coerce')
                    df[col] = dates.dt.strftime('%d.%m.%Y').fillna('Noma\'lum')
                    # Debug uchun birinchi 3 ta qiymatni ko'rsatish
                    sample_values = df[col].head(3).tolist()
                    print(f"DEBUG: {col} ustuni namunalari: {sample_values}")
            
            self.cached_data[filename] = df
            print(f"✅ {filename} fayli keshlandi")
        except Exception as e:
            print(f"❌ {filename} faylini keshlashda xatolik: {e}")
    
    def create_image_from_dataframe(self, df: pd.DataFrame, user_id: int) -> str:
        """Pillow yordamida DataFrame'dan optimallashtirilgan rasm yaratadi"""
        try:
            # Vaqtinchalik rasm papkasini yaratish
            temp_dir = "data/temp_images"
            os.makedirs(temp_dir, exist_ok=True)
            
            # Optimal rasm o'lchamlari (Telegram uchun)
            max_width = 1280  # Telegram maksimal kengligi
            cell_width = 180
            cell_height = 60
            padding = 20
            
            # Ustunlar soniga qarab kenglikni hisoblash
            total_width = min(max_width, len(df.columns) * cell_width + padding * 2)
            total_height = (len(df) + 2) * cell_height + padding * 3
            
            # Rasm yaratish
            img = Image.new('RGB', (total_width, total_height), color='white')
            draw = ImageDraw.Draw(img)
            
            # Fontlar
            try:
                title_font = ImageFont.truetype("arial.ttf", 18)
                header_font = ImageFont.truetype("arialbd.ttf", 14)  # Bold
                cell_font = ImageFont.truetype("arial.ttf", 12)
            except:
                try:
                    # Linux fontlari
                    title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
                    header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
                    cell_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                except:
                    # Default font
                    title_font = ImageFont.load_default()
                    header_font = ImageFont.load_default()
                    cell_font = ImageFont.load_default()
            
            # Sarlavha
            title_text = f"🔍 ID: {user_id} natijalari ({len(df)} ta)"
            draw.text((padding, padding), title_text, fill='black', font=title_font)
            
            # Jadval boshlanishi
            start_x = padding
            start_y = padding * 2 + 20
            
            # Ustunlar kengligini hisoblash
            available_width = total_width - padding * 2
            col_width = available_width // len(df.columns)
            
            # Sarlavha qatori (yashil)
            y_pos = start_y
            for i, col in enumerate(df.columns):
                x_pos = start_x + i * col_width
                # Yashil fon
                draw.rectangle([x_pos, y_pos, x_pos + col_width, y_pos + cell_height], 
                             fill='#4CAF50', outline='black', width=1)
                # Matn (markazlashtirilgan)
                text = str(col)
                if len(text) > 12:
                    text = text[:12] + '...'
                bbox = draw.textbbox((0, 0), text, font=header_font)
                text_width = bbox[2] - bbox[0]
                text_x = x_pos + (col_width - text_width) // 2
                draw.text((text_x, y_pos + 15), text, fill='white', font=header_font)
            
            # Ma'lumot qatorlari
            for row_idx, (_, row) in enumerate(df.iterrows()):
                y_pos = start_y + cell_height * (row_idx + 1)
                
                # Qator rangi
                if row_idx % 2 == 0:
                    fill_color = '#f8f9fa'
                else:
                    fill_color = 'white'
                
                for col_idx, (col_name, value) in enumerate(row.items()):
                    x_pos = start_x + col_idx * col_width
                    # Katakka fon
                    draw.rectangle([x_pos, y_pos, x_pos + col_width, y_pos + cell_height], 
                                 fill=fill_color, outline='black', width=1)
                    # Matn
                    text = str(value) if pd.notna(value) else ''
                    if len(text) > 15:
                        text = text[:15] + '...'
                    draw.text((x_pos + 10, y_pos + 20), text, fill='black', font=cell_font)
            
            # Rasmni saqlash (optimallashtirilgan)
            image_path = os.path.join(temp_dir, f"results_{user_id}_{int(time.time())}.jpg")
            img.save(image_path, 'JPEG', quality=85, optimize=True)
            
            # Fayl hajmini tekshirish
            file_size = os.path.getsize(image_path)
            print(f"✅ Rasm yaratildi: {image_path} ({file_size} bytes)")
            
            # Agar fayl juda katta bo'lsa, sifatni pasaytiramiz
            if file_size > 10 * 1024 * 1024:  # 10MB
                img.save(image_path, 'JPEG', quality=60, optimize=True)
                file_size = os.path.getsize(image_path)
                print(f"🔄 Rasm qayta saqlandi: {file_size} bytes")
            
            return image_path
            
        except Exception as e:
            print(f"❌ Rasm yaratishda xatolik: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def add_excel_file(self, file_path: str) -> bool:
        """Yangi Excel fayl qo'shish"""
        try:
            filename = os.path.basename(file_path)
            
            # Faylni tekshirish
            if not filename.endswith('.xlsx'):
                return False
            
            # Fayl papkaga ko'chirish
            destination = os.path.join(EXCEL_FILES_DIR, filename)
            import shutil
            shutil.move(file_path, destination)
            
            # Fayl ro'yxatiga qo'shish
            if filename not in self.excel_files:
                self.excel_files.append(filename)
            
            # Keshlash
            self.cache_excel_data(filename)
            
            return True
        except Exception as e:
            print(f"❌ Excel faylni qo'shishda xatolik: {e}")
            return False
    
    def search_by_id(self, user_id: str) -> list:
        """Barcha Excel fayllaridan ID bo'yicha qidiruv - barcha mos keladigan ma'lumotlarni qaytarish"""
        user_id = str(user_id).zfill(6)  # 6 xonali qilish
        print(f"DEBUG: Qidiruv uchun ID: {user_id}")
        all_results = []
        
        print(f"DEBUG: Keshdagi fayllar: {list(self.cached_data.keys())}")
        
        for filename, df in self.cached_data.items():
            print(f"DEBUG: {filename} fayli ustunlari: {list(df.columns)}")
            print(f"DEBUG: {filename} fayli barcha ustunlar:")
            for i, col in enumerate(df.columns):
                sample_values = df[col].head(3).tolist()
                print(f"  {i+1}. {col}: {sample_values}")
            
            # ID ustunini turli nomlar bilan qidiramiz
            id_columns = ['Talaba ID', 'ID', 'Student ID', 'StudentID', 'Student_ID', 'id', 'student_id', 'studentid']
            found_id_column = None
            
            for col in id_columns:
                if col in df.columns:
                    found_id_column = col
                    break
            
            if found_id_column:
                id_values = df[found_id_column].head().tolist()
                print(f"  {found_id_column} namunalari: {id_values}")
                
                results = df[df[found_id_column] == user_id]
                print(f"DEBUG: {filename} faylida {len(results)} ta topildi ({found_id_column} ustuni bo'yicha)")
                
                if not results.empty:
                    for _, row in results.iterrows():
                        # Debug: qatorning barcha ma'lumotlarini ko'rsatish
                        print(f"DEBUG: Topilgan qator ma'lumotlari:")
                        for col in df.columns:
                            print(f"  {col}: {row[col]} (tip: {type(row[col])})")
                        
                        # Barcha ustunlardan ma'lumotlarni olish
                        result_data = {}
                        for col in df.columns:
                            result_data[col] = str(row.get(col, ''))
                        result_data['ID'] = str(row.get(found_id_column, ''))
                        all_results.append(result_data)
        
        print(f"DEBUG: Jami topilgan natijalar: {len(all_results)}")
        return all_results if all_results else None
    
    def get_file_list(self) -> list:
        """Excel fayllar ro'yxatini olish"""
        return self.excel_files.copy()
    
    def remove_file(self, filename: str) -> bool:
        """Excel faylni o'chirish"""
        try:
            if filename in self.excel_files:
                self.excel_files.remove(filename)
            
            if filename in self.cached_data:
                del self.cached_data[filename]
            
            file_path = os.path.join(EXCEL_FILES_DIR, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Qayta yuklash - keshni yangilash
            self.load_existing_files()
            
            return True
        except Exception as e:
            print(f"❌ Faylni o'chirishda xatolik: {e}")
            return False
    
    def get_stats(self) -> dict:
        """Statistika olish"""
        total_records = 0
        for df in self.cached_data.values():
            total_records += len(df)
        
        return {
            'files_count': len(self.excel_files),
            'total_records': total_records,
            'files': self.excel_files
        }

# =================================================================
# CHANNEL MANAGER KLASI
# =================================================================

class ChannelManager:
    """Majburiy obuna kanallarini boshqarish uchun klass"""
    
    def __init__(self):
        self.channels = []
        self.load_channels()
    
    def load_channels(self):
        """Kanallarni fayldan yuklash"""
        try:
            print(f"DEBUG: Kanallar fayli yo'li: {CHANNELS_DB}")
            if os.path.exists(CHANNELS_DB):
                with open(CHANNELS_DB, 'r', encoding='utf-8') as f:
                    self.channels = json.load(f)
                print(f"DEBUG: Yuklangan kanallar: {self.channels}")
            else:
                print(f"DEBUG: Kanallar fayli topilmadi: {CHANNELS_DB}")
                self.channels = []
        except Exception as e:
            print(f"❌ Kanallarni yuklashda xatolik: {e}")
            self.channels = []
    
    def save_channels(self):
        """Kanallarni faylga saqlash"""
        try:
            os.makedirs(os.path.dirname(CHANNELS_DB), exist_ok=True)
            with open(CHANNELS_DB, 'w', encoding='utf-8') as f:
                json.dump(self.channels, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Kanallarni saqlashda xatolik: {e}")
    
    def add_channel(self, channel_id: str, channel_name: str = None):
        """Yangi kanal qo'shish (faqat 1 ta kanal mumkin)"""
        # Agar allaqachon kanal bo'lsa, yangisini qo'shmaslik
        if len(self.channels) >= 1:
            return False
        
        # Kanal ID dan username ni ajratib olish
        username = channel_id
        if not username.startswith('@'):
            username = f"@{username}"
        
        channel_info = {
            'id': channel_id,
            'username': username,  # username ni qo'shish
            'name': channel_name or channel_id,
            'added_date': datetime.now().isoformat()
        }
        
        # Takrorlanishni tekshirish
        for channel in self.channels:
            if channel['id'] == channel_id:
                return False
        
        self.channels.append(channel_info)
        self.save_channels()
        return True
    
    def remove_channel(self, channel_id: str):
        """Kanalni o'chirish"""
        self.channels = [ch for ch in self.channels if ch['id'] != channel_id]
        self.save_channels()
        return True
    
    def get_channels(self) -> list:
        """Barcha kanallarni olish"""
        return self.channels.copy()
    
    async def check_subscription(self, user_id: int, bot: Bot) -> bool:
        """Foydalanuvchining barcha kanallarga obuna bo'lganini tekshirish"""
        print(f"DEBUG: check_subscription chaqirildi, user_id: {user_id}")
        print(f"DEBUG: Kanallar ro'yxati: {self.channels}")
        
        if not self.channels:
            print("DEBUG: Kanallar yo'q, True qaytaramiz")
            return True
        
        for channel in self.channels:
            try:
                # Kanal username ni to'g'ri formatga keltirish
                channel_username = channel['username']
                print(f"DEBUG: Tekshirilayotgan kanal: {channel_username}")
                
                if not channel_username.startswith('@'):
                    channel_username = f"@{channel_username}"  # @ belgisini qo'shish
                    print(f"DEBUG: Qo'shilgan @: {channel_username}")
                
                print(f"DEBUG: {channel_username} kanalida {user_id} obunasini tekshirish")
                member = await bot.get_chat_member(channel_username, user_id)
                print(f"DEBUG: User status: {member.status}")
                
                if member.status not in ['member', 'administrator', 'creator']:
                    print(f"DEBUG: User {user_id} obuna bo'lmagan, status: {member.status}")
                    return False
                else:
                    print(f"DEBUG: User {user_id} obuna bo'lgan")
            except Exception as e:
                # Agar kanal topilmasa yoki bot kanalda admin bo'lmasa, bu kanalni o'tkazib yuborish
                print(f"DEBUG: Kanal tekshiruvi xatoligi: {e}")
                continue
        
        print(f"DEBUG: Barcha kanallar uchun obuna tasdiqlandi")
        return True

# =================================================================
# DATABASE KLASI
# =================================================================

class Database:
    """Foydalanuvchilar va statistika ma'lumotlarini saqlash uchun klass"""
    
    def __init__(self):
        self.users = {}
        self.stats = {
            'total_users': 0,
            'total_searches': 0,
            'total_files': 0,
            'daily_searches': {},
            'user_activity': {}
        }
        self.load_data()
    
    def load_data(self):
        """Ma'lumotlarni fayldan yuklash"""
        try:
            # Foydalanuvchilar ma'lumotlari
            if os.path.exists(USERS_DB):
                with open(USERS_DB, 'r', encoding='utf-8') as f:
                    self.users = json.load(f)
            
            # Statistika ma'lumotlari
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
        except Exception as e:
            print(f"❌ Ma'lumotlarni yuklashda xatolik: {e}")
    
    def save_data(self):
        """Ma'lumotlarni faylga saqlash"""
        try:
            # Papkalar yaratish
            os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)
            os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
            
            # Foydalanuvchilar ma'lumotlari
            with open(USERS_DB, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
            
            # Statistika ma'lumotlari
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Ma'lumotlarni saqlashda xatolik: {e}")
    
    def add_user(self, user_id: int, username: str = None, full_name: str = None):
        """Yangi foydalanuvchi qo'shish"""
        if str(user_id) not in self.users:
            self.users[str(user_id)] = {
                'username': username,
                'full_name': full_name,
                'joined_date': datetime.now().isoformat(),
                'last_active': datetime.now().isoformat(),
                'search_count': 0
            }
            self.stats['total_users'] = len(self.users)
            self.save_data()
    
    def update_user_activity(self, user_id: int):
        """Foydalanuvchi faoliyatini yangilash"""
        if str(user_id) in self.users:
            self.users[str(user_id)]['last_active'] = datetime.now().isoformat()
            self.save_data()
    
    def increment_search_count(self, user_id: int):
        """Qidiruv sonini oshirish"""
        if str(user_id) in self.users:
            self.users[str(user_id)]['search_count'] += 1
        
        # Umumiy statistikani yangilash
        self.stats['total_searches'] += 1
        
        # Kunlik statistika
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in self.stats['daily_searches']:
            self.stats['daily_searches'][today] = 0
        self.stats['daily_searches'][today] += 1
        
        self.save_data()
    
    def get_all_users(self) -> list:
        """Barcha foydalanuvchi IDlarini olish"""
        return [int(uid) for uid in self.users.keys()]
    
    def get_user_info(self, user_id: int) -> dict:
        """Foydalanuvchi ma'lumotlarini olish"""
        return self.users.get(str(user_id))
    
    def update_files_count(self, count: int):
        """Fayllar sonini yangilash"""
        self.stats['total_files'] = count
        self.save_data()
    
    def get_stats(self) -> dict:
        """Statistikani olish"""
        return self.stats.copy()
    
    def get_daily_stats(self, days: int = 7) -> dict:
        """Oxirgi kunlar statistikasi"""
        daily_stats = {}
        end_date = datetime.now()
        
        for i in range(days):
            date = (end_date - timedelta(days=i)).strftime('%Y-%m-%d')
            daily_stats[date] = self.stats['daily_searches'].get(date, 0)
        
        return daily_stats

# =================================================================
# BOT OBYEKTLARI VA KLAVIATURALAR
# =================================================================

# Bot obyektlari
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Global obyektlar
excel_handler = ExcelHandler()
db = Database()
channel_manager = ChannelManager()

# Admin xabar yuborish holati
admin_broadcast_mode = set()  # Xabar yuborish rejimidagi adminlar ID lari

# Admin klaviaturasi
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="📁 Fayllar")],
        [KeyboardButton(text="📢 Xabar yuborish")],
        [KeyboardButton(text="🔐 Majburiy obuna")]
    ],
    resize_keyboard=True
)

# Asosiy klaviatura
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 ID bilan qidirish")],
        [KeyboardButton(text="ℹ️ Yordam")]
    ],
    resize_keyboard=True
)

# =================================================================
# BOT KLASI
# =================================================================

class TelegramBot:
    """Asosiy bot klassi"""
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        """Foydalanuvchi admin ekanligini tekshirish"""
        return user_id == ADMIN_ID

# =================================================================
# HANDLER FUNKSIYALARI
# =================================================================

@dp.message(Command("start"))
async def start_command(message: Message):
    """Botni ishga tushurish komandasi"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        full_name = message.from_user.full_name
        
        # Foydalanuvchini bazaga qo'shish
        db.add_user(user_id, username, full_name)
        db.update_user_activity(user_id)
        
        if TelegramBot.is_admin(user_id):
            await message.answer(
                "👨‍💻 Admin paneliga xush kelibsiz!\n\n"
                "🤖 Excel qidiruv boti admin interfeysi\n\n"
                "📋 Admin imkoniyatlari:\n"
                "• 📊 Statistika ko'rish\n"
                "• 📁 Excel fayl yuklash\n"
                "• 📢 Foydalanuvchilarga xabar yuborish\n"
                "• 🔐 Majburiy obuna kanallarini boshqarish\n\n"
                "📄 Excel faylni yuklash uchun faylni to'g'ridan-to'g'ri yuboring!\n\n"
                "👨‍💻 Admin @shohjahon_o5",
                reply_markup=admin_keyboard
            )
        else:
            # Majburiy obuna tekshiruvi
            is_subscribed = await channel_manager.check_subscription(user_id, message.bot)
            
            if not is_subscribed:
                # Obuna bo'lmagan kanallar ro'yxati
                channels = channel_manager.get_channels()
                channel_text = ""
                
                # Username larsiz xabar
                
                # Obuna tugmasi
                subscription_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📢 Kanalga o'tish", url=f"https://t.me/{channels[0]['username'].lstrip('@')}")],
                        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                    ]
                ) if channels else InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                    ]
                )
                
                await message.answer(
                    f"🔐 **Majburiy obuna talab qilinadi!**\n\n"
                    f"📢 Botdan foydalanish uchun kanalga obuna bo'lishingiz kerak:\n\n"
                    f"📋 Obuna bo'lgach, '✅ Tasdiqlash' tugmasini bosing!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=subscription_keyboard
                )
                return
            
            await message.answer(
                "🤖 SAMDAQU qidiruv botiga xush kelibsiz!\n\n"
                "Men Excel fayllaridan ID orqali ma'lumotlarni topishim mumkin.\n\n"
                "📋 Qo'llanma:\n"
                "• 6 xonali ID raqamini yuboring\n"
                "• Bot siz yuborgan ID bo'yicha ma'lumot topadi\n\n"
                "🔍 Iltimos, 6 xonali ID raqamingizni yuboring!\n\n"
                "👨‍💻 Admin @shohjahon_o5",
                reply_markup=main_keyboard
            )
            
    except Exception as e:
        logger.error(f"Start komandasida xatolik: {e}")
        await message.answer(
            "❌ Botni ishga tushirishda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5",
            parse_mode=ParseMode.MARKDOWN
        )

@dp.callback_query(F.data == "start_search")
async def start_search_callback(callback: CallbackQuery):
    """ID raqamni yuborish uchun callback"""
    try:
        # Obunani tekshirish (faqat admin bo'lmaganlar uchun)
        if not TelegramBot.is_admin(callback.from_user.id):
            is_subscribed = await channel_manager.check_subscription(callback.from_user.id, callback.bot)
            
            if not is_subscribed:
                await callback.answer(
                    "❌ Avval kanalga obuna bo'ling!",
                    show_alert=True
                )
                return
        
        await callback.message.answer(
            "🔍 **ID raqamini yuboring:**\n\n"
            "Iltimos, 6 xonali ID raqamingizni yuboring.\n"
            "Masalan: `123456`",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Start search callback da xatolik: {e}")
        await callback.answer("❌ Xatolik yuz berdi!", show_alert=True)

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    """Majburiy obuna tasdiqlash callback"""
    try:
        user_id = callback.from_user.id
        print(f"DEBUG: Obuna tekshiruv boshlandi, user_id: {user_id}")
        
        # Obunani tekshirish
        is_subscribed = await channel_manager.check_subscription(user_id, callback.bot)
        print(f"DEBUG: Obuna tekshiruv natijasi: {is_subscribed}")
        
        if is_subscribed:
            # Foydalanuvchiga darhol foydalanish imkoniyati berish
            welcome_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔍 ID raqamni yuborish", callback_data="start_search")]
                ]
            )
            
            await callback.message.edit_text(
                "✅ Obuna tasdiqlandi!\n\n"
                "Endi botdan to'liq foydalanishingiz mumkin.\n\n"
                "🔍 6 xonali ID raqamingizni yuboring va nazorat ma'lumotlarini toping!\n\n"
                "👨‍💻 Admin @shohjahon_o5",
                reply_markup=welcome_keyboard
            )
            
            await callback.answer("✅ Obuna tasdiqlandi!", show_alert=True)
        else:
            await callback.answer(
                "❌ Siz hali kanal(lar)ga obuna bo'lmagansiz!\n"
                "Iltimos, avval obuna bo'ling.",
                show_alert=True
            )
            
    except Exception as e:
        logger.error(f"Obuna tekshirishda xatolik: {e}")
        print(f"DEBUG: Obuna tekshirish xatoligi: {e}")
        await callback.answer(
            "❌ Xatolik yuz berdi!\n"
            "Qaytadan urinib ko'ring.",
            show_alert=True
        )

@dp.message(Command("help"))
async def help_command(message: Message):
    """Yordam komandasi"""
    try:
        user_id = message.from_user.id
        
        if TelegramBot.is_admin(user_id):
            help_text = (
                "📚 Admin qo'llanmasi:\n\n"
                "1️⃣ Fayl yuklash:\n"
                "   - Excel (.xlsx) faylni yuboring\n"
                "   - Fayllar bazaga saqlanadi\n\n"
                "2️⃣ Fayllarni boshqarish:\n"
                "   - 📁 Fayllar - Barcha fayllarni ko'rish\n"
                "   - 📊 Statistika - Bot statistikasi\n\n"
                "3️⃣ Foydalanuvchi so'rovlari:\n"
                "   - Foydalanuvchilar ID orqali qidiradi\n"
                "   - Siz yuklagan fayllarda qidiriladi\n\n"
                "4️⃣ Xavfsizlik:\n"
                "   - Faqat admin fayl yuklay oladi\n"
                "   - Foydalanuvchilar faqat qidirishi mumkin\n\n"
                "👨‍💻 Admin @shohjahon_o5"
            )
        else:
            help_text = (
                "📚 Botdan foydalanish qo'llanmasi:\n\n"
                "1️⃣ ID bilan qidirish:\n"
                "   - Qidirish uchun 6 xonali ID raqamini yuboring\n"
                "   - Bot admin yuklagan Excel fayllarda qidiradi\n\n"
                "2️⃣ Natijalar:\n"
                "   - Topilgan ma'lumotlar chiroyli formatda ko'rsatiladi\n"
                "   - Agar ma'lumot topilmasa, xabar beriladi\n\n"
                "3️⃣ Qo'llab-quvvatlanadigan format:\n"
                "   • Excel (.xlsx)\n\n"
                "❓ Savollaringiz bo'lsa, admin ga murojaat qiling!\n\n"
                "👨‍💻 Admin @shohjahon_o5"
            )
        
        await message.answer(help_text)
        
    except Exception as e:
        logger.error(f"Help command xatolik: {e}")
        await message.answer(
            "❌ Yordam ko'rsatishda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )

@dp.message(F.document)
async def handle_document(message: Message):
    """Faylni qabul qilish va saqlash (faqat admin uchun)"""
    try:
        user_id = message.from_user.id
        
        # Faqat admin fayl yuklay oladi
        if not TelegramBot.is_admin(user_id):
            await message.answer(
                "❌ Siz fayl yuklay olmaysiz!\n"
                "📋 Faqat admin fayl yuklay oladi.\n"
                "🔍 ID orqali qidirish uchun raqam yuboring.\n\n"
                "👨‍💻 Admin @shohjahon_o5"
            )
            return
        
        document = message.document
        if not document:
            await message.answer("❌ Fayl topilmadi!")
            return
        
        # Fayl nomini olish
        file_name = document.file_name
        if not file_name:
            file_name = f"document_{document.file_id}.xlsx"
        
        # Faqat .xlsx formatini qabul qilish
        if not file_name.endswith('.xlsx'):
            await message.answer(
                "❌ Faqat Excel (.xlsx) fayllar qabul qilinadi!\n"
                "📋 Iltimos, to'g'ri formatdagi fayl yuboring."
            )
            return
        
        # Faylni yuklab olish
        file_info = await bot.get_file(document.file_id)
        
        # Faylni saqlash
        os.makedirs(EXCEL_FILES_DIR, exist_ok=True)
        file_path = os.path.join(EXCEL_FILES_DIR, file_name)
        
        await bot.download_file(file_info.file_path, file_path)
        
        # Excel handler ga faylni qo'shish
        if excel_handler.add_excel_file(file_path):
            # Statistikani yangilash
            db.update_files_count(len(excel_handler.get_file_list()))
            
            # Foydalanuvchilarga bildirish yuborish
            await notify_users_new_file(file_name, message.from_user.full_name)
            
            await message.answer(
                f"✅ Excel fayli muvaffaqiyatli yuklandi: {file_name}\n"
                f"📁 Saqlandi: {EXCEL_FILES_DIR}\n"
                f"🔍 Endi barcha foydalanuvchilar qidirishi mumkin!\n"
                f"📢 Barcha foydalanuvchilarga bildirish yuborildi!"
            )
        else:
            await message.answer(
                "❌ Faylni qo'shishda xatolik yuz berdi!\n"
                "🔄 Qaytadan urinib ko'ring."
            )
        
    except Exception as e:
        logger.error(f"Faylni yuklashda xatolik: {e}")
        await message.answer(
            f"❌ Faylni yuklashda xatolik yuz berdi: {str(e)}\n"
            "🔄 Qaytadan urinib ko'ring."
        )

@dp.message(Command("del"))
async def delete_file_command(message: Message):
    """Faylni o'chirish komandasi"""
    print(f"DEBUG: delete_file_command chaqirildi, xabar: {message.text}")
    
    if not TelegramBot.is_admin(message.from_user.id):
        print("DEBUG: Foydalanuvchi admin emas")
        await message.answer(
            "❌ Bu komanda faqat admin uchun!\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )
        return
    
    # Komandadan fayl nomini ajratib olish
    command_text = message.text
    print(f"DEBUG: Command text: {command_text}")
    
    # Agar oddiy /del bo'lsa, fayllar ro'yxatini ko'rsatish
    if command_text == "/del" or command_text.startswith("/del "):
        print("DEBUG: Oddiy /del komandasi")
        files = excel_handler.get_file_list()
        print(f"DEBUG: Fayllar ro'yxati: {files}")
        
        if not files:
            await message.answer(
                "📁 **O'chirish uchun fayllar yo'q!**\n\n"
                "📋 Excel fayllar hali yuklanmagan.\n\n"
                "🔄 Fayl yuklash uchun faylni to'g'ridan-to'g'ri yuboring.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        files_text = "📁 **O'chirish uchun fayllar:**\n\n"
        for i, file in enumerate(files, 1):
            files_text += f"{i}. `{file}`\n"
        
        files_text += "\n📋 **O'chirish uchun:**\n"
        files_text += "```\n/del_fayl_nomi.xlsx\n```\n\n"
        files_text += "📌 Masalan: `/del_nazorat.xlsx`"
        
        await message.answer(files_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    # /del_ bilan boshlanadigan komandalarni qabul qilish
    if not command_text.startswith('/del_'):
        await message.answer(
            "❌ Noto'g'ri komanda formati!\n\n"
            "📋 To'g'ri format: /del_fayl_nomi.xlsx\n\n"
            "📁 Barcha fayllarni ko'rish uchun: /del"
        )
        return
    
    filename = command_text[5:]  # '/del_' dan keyin qolgan qism
    
    if not filename:
        await message.answer(
            "❌ Fayl nomi ko'rsatilmadi!\n\n"
            "📋 To'g'ri format: /del_fayl_nomi.xlsx"
        )
        return
    
    # Faylni o'chirish
    if excel_handler.remove_file(filename):
        # Statistikani yangilash
        db.update_files_count(len(excel_handler.get_file_list()))
        
        await message.answer(
            f"✅ Fayl muvaffaqiyatli o'chirildi: {filename}\n\n"
            f"📊 Qolgan fayllar: {len(excel_handler.get_file_list())} ta\n"
            f"🔄 Yangi fayl ro'yxatini ko'rish uchun '📁 Fayllar' tugmasini bosing."
        )
    else:
        await message.answer(
            f"❌ Faylni o'chirishda xatolik: {filename}\n\n"
            "📋 Fayl nomini to'g'ri kiritingganimizga ishonch hosil qiling."
        )

@dp.message(F.text & ~F.command)
async def handle_message(message: Message):
    """Xabarlarni qabul qilish (ID qidirish va admin tugmalari)"""
    try:
        user_id = message.from_user.id
        message_text = message.text.strip()
        
        # Foydalanuvchi faoliyatini yangilash
        db.update_user_activity(user_id)
        
        # Avval obunani tekshirish (faqat admin bo'lmaganlar uchun)
        if not TelegramBot.is_admin(user_id):
            is_subscribed = await channel_manager.check_subscription(user_id, message.bot)
            
            if not is_subscribed:
                # Kanal ma'lumotlarini olish
                channels = channel_manager.get_channels()
                channel = channels[0] if channels else None
                
                # Obuna tugmasi
                if channel:
                    subscription_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="📢 Kanalga o'tish", url=f"https://t.me/{channel['username'].lstrip('@')}")],
                            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                        ]
                    )
                else:
                    subscription_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                        ]
                    )
                
                await message.answer(
                    "🔐 **Majburiy obuna talab qilinadi!**\n\n"
                    "📢 Botdan to'liq foydalanish uchun kanalga obuna bo'lishingiz kerak:\n\n"
                    "👉 **Obuna bo'lgach, pastdagi '✅ Tasdiqlash' tugmasini bosing!**\n\n"
                    "⚠️ Obuna bo'lmasangiz, bot ishlamaydi!",
                    reply_markup=subscription_keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        
        # Komandalarni tekshirish (agar ular Command handlerlar tomonidan qabul qilinmagan bo'lsa)
        if message_text.startswith('/'):
            print(f"DEBUG: Komanda keldi: {message_text}")
            # /del komandasi uchun tekshirish
            if message_text == "/del" or message_text.startswith("/del "):
                print("DEBUG: /del komandasi chaqirilmoqda")
                await delete_file_command(message)
                return
            elif message_text.startswith('/del_'):
                print(f"DEBUG: /del_ komandasi chaqirilmoqda: {message_text}")
                await delete_file_command(message)
                return
            # Boshqa komandalarni ham tekshirish mumkin
            elif message_text == "/start":
                await start_command(message)
                return
            elif message_text == "/help":
                await help_command(message)
                return
        
        # Admin tugmalari
        if TelegramBot.is_admin(user_id):
            if message_text == "📊 Statistika":
                await show_stats(message)
                return
            elif message_text == "📁 Fayllar":
                await list_files(message)
                return
            elif message_text == "📢 Xabar yuborish":
                admin_broadcast_mode.add(user_id)
                await message.answer(
                    "📢 Xabar yuborish\n\n"
                    "Yubormoqchi bo'lgan xabaringizni yozing.\n"
                    "Xabar barcha foydalanuvchilarga yuboriladi.\n\n"
                    "📝 **Shaxsiylashtirish uchun o'zgaruvchilar:**\n"
                    "• {first_name} - Foydalanuvchi ismi\n"
                    "• {username} - Foydalanuvchi username\n"
                    "• {user_id} - Foydalanuvchi ID\n\n"
                    "❌ Bekor qilish uchun 'bekor' deb yozing."
                )
                return
            elif message_text == "🔐 Majburiy obuna":
                try:
                    await manage_subscription_channels(message)
                except Exception as e:
                    logger.error(f"Majburiy obuna tugmasida xatolik: {e}")
                    await message.answer(
                        "❌ Majburiy obuna menuni ochishda xatolik yuz berdi!\n"
                        "🔄 Qaytadan urinib ko'ring.\n\n"
                        "👨‍💻 Admin @shohjahon_o5"
                    )
                return
        
        # Oddiy foydalanuvchi tugmalari
        if message_text == "🔍 ID bilan qidirish":
            # Obunani tekshirish (faqat admin bo'lmaganlar uchun)
            if not TelegramBot.is_admin(user_id):
                is_subscribed = await channel_manager.check_subscription(user_id, message.bot)
                
                if not is_subscribed:
                    # Kanal ma'lumotlarini olish
                    channels = channel_manager.get_channels()
                    channel = channels[0] if channels else None
                    
                    # Obuna tugmasi
                    if channel:
                        subscription_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="📢 Kanalga o'tish", url=f"https://t.me/{channel['username'].lstrip('@')}")],
                                [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                            ]
                        )
                    else:
                        subscription_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                            ]
                        )
                    
                    await message.answer(
                        "🔐 **Majburiy obuna talab qilinadi!**\n\n"
                        "📢 Botdan to'liq foydalanish uchun kanalga obuna bo'lishingiz kerak:\n\n"
                        "👉 **Obuna bo'lgach, pastdagi '✅ Tasdiqlash' tugmasini bosing!**\n\n"
                        "⚠️ Obuna bo'lmasangiz, bot ishlamaydi!",
                        reply_markup=subscription_keyboard,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            await message.answer(
                "🔍 ID qidirish\n\n"
                "Iltimos, 6 xonali ID raqamingizni yuboring:\n"
                "Masalan: 123456"
            )
            return
        elif message_text == "ℹ️ Yordam":
            # Obunani tekshirish (faqat admin bo'lmaganlar uchun)
            if not TelegramBot.is_admin(user_id):
                is_subscribed = await channel_manager.check_subscription(user_id, message.bot)
                
                if not is_subscribed:
                    # Kanal ma'lumotlarini olish
                    channels = channel_manager.get_channels()
                    channel = channels[0] if channels else None
                    
                    # Obuna tugmasi
                    if channel:
                        subscription_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="📢 Kanalga o'tish", url=f"https://t.me/{channel['username'].lstrip('@')}")],
                                [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                            ]
                        )
                    else:
                        subscription_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                            ]
                        )
                    
                    await message.answer(
                        "🔐 **Majburiy obuna talab qilinadi!**\n\n"
                        "📢 Botdan to'liq foydalanish uchun kanalga obuna bo'lishingiz kerak:\n\n"
                        "👉 **Obuna bo'lgach, pastdagi '✅ Tasdiqlash' tugmasini bosing!**\n\n"
                        "⚠️ Obuna bo'lmasangiz, bot ishlamaydi!",
                        reply_markup=subscription_keyboard,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            try:
                await help_command(message)
            except Exception as e:
                logger.error(f"Yordam komandasida xatolik: {e}")
                await message.answer(
                    "❌ Yordam ko'rsatishda xatolik yuz berdi!\n"
                    "🔄 Qaytadan urinib ko'ring.\n\n"
                    "👨‍💻 Admin @shohjahon_o5"
                )
            return
        
        # ID qidirish (faqat raqamlar uchun)
        if message_text.isdigit():
            # ID validation
            if len(message_text) != 6:
                await message.answer(
                    "❌ ID 6 xonali raqam bo'lishi kerak!\n\n"
                    "📋 Masalan: 123456\n"
                    "🔄 Qaytadan urinib ko'ring."
                )
                return
            
            # Qidiruvni amalga oshirish
            await search_by_id(message, message_text)
        else:
            # Majburiy obuna boshqaruvi (admin uchun) - faqat kanal formatlarini tekshirish
            if TelegramBot.is_admin(user_id):
                current_channels = channel_manager.get_channels()
                
                # Faqat kanal qo'shish/o'chirish xabarlarini qabul qilish
                message_text = message.text.strip()
                
                # Kanal qo'shish formatlari
                is_channel_format = (
                    message_text.startswith('@') or 
                    message_text.startswith('https://t.me/') or 
                    message_text.startswith('t.me/') or
                    message_text.lower() in ['bekor', 'ochirish']
                )
                
                # Agar kanal formatida bo'lsa va kanallar mavjud bo'lsa/yo'q bo'lsa
                if is_channel_format and (not current_channels or len(current_channels) > 0):
                    await handle_subscription_management(message)
                    return
            
            # Broadcast xabar (admin uchun) - faqat maxsus xabarlar uchun
            if TelegramBot.is_admin(user_id):
                # Agar admin xabar yuborish rejimida bo'lsa
                if user_id in admin_broadcast_mode:
                    if message_text.lower() == 'bekor':
                        admin_broadcast_mode.remove(user_id)
                        await message.answer(
                            "❌ Xabar yuborish bekor qilindi.\n"
                            "📋 Admin menyudasiz."
                        )
                        return
                    else:
                        await broadcast_message(message, message_text)
                        admin_broadcast_mode.remove(user_id)
                        return
                else:
                    await message.answer(
                        "❌ Noto'g'ri buyruq!\n\n"
                        "📋 Iltimos, tugmalardan foydalaning yoki 6 xonali ID raqamini yuboring."
                    )
            else:
                await message.answer(
                    "❌ Noto'g'ri format!\n\n"
                    "📋 Iltimos, 6 xonali ID raqamini yuboring\n"
                    "yoki tugmalardan foydalaning."
                )
                
    except Exception as e:
        logger.error(f"Xabarni qayta ishlashda xatolik: {e}")
        await message.answer(
            "❌ Xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring."
        )

async def search_by_id(message: Message, user_id: str):
    """ID bo'yicha qidiruv"""
    try:
        # Majburiy obuna tekshiruvi (faqat admin bo'lmaganlar uchun)
        if not TelegramBot.is_admin(message.from_user.id):
            is_subscribed = await channel_manager.check_subscription(message.from_user.id, message.bot)
            
            if not is_subscribed:
                # Kanal ma'lumotlarini olish
                channels = channel_manager.get_channels()
                channel = channels[0] if channels else None
                
                # Obuna tugmasi
                if channel:
                    subscription_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="📢 Kanalga o'tish", url=f"https://t.me/{channel['username'].lstrip('@')}")],
                            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                        ]
                    )
                else:
                    subscription_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check_subscription")]
                        ]
                    )
                
                await message.answer(
                    "🔐 **Majburiy obuna talab qilinadi!**\n\n"
                    "📢 Botdan to'liq foydalanish uchun kanalga obuna bo'lishingiz kerak:\n\n"
                    "👉 **Obuna bo'lgach, pastdagi '✅ Tasdiqlash' tugmasini bosing!**\n\n"
                    "⚠️ Obuna bo'lmasangiz, bot ishlamaydi!",
                    reply_markup=subscription_keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        
        # Excel fayllarida qidirish
        result = excel_handler.search_by_id(user_id)
        
        # Qidiruv statistikasini yangilash
        db.increment_search_count(message.from_user.id)
        
        if result:
            # Natijalarni DataFrame ga aylantirish
            df_results = pd.DataFrame(result)
            
            # Keraksiz ustunlarni olib tashlash
            excluded_columns = ['fan_kodi', 'group_code', 'curriculum_language', 'exam', 'source_file', 'sirtqi', 'date', 'vaqti']
            df_filtered = df_results.drop(columns=[col for col in excluded_columns if col in df_results.columns])
            
            # Rasm yaratish
            image_path = excel_handler.create_image_from_dataframe(df_filtered, message.from_user.id)
            
            if image_path and os.path.exists(image_path):
                # Rasm hajmini tekshirish
                file_size = os.path.getsize(image_path)
                print(f"DEBUG: Rasm fayli hajmi: {file_size} bytes")
                
                # Rasmni yuborish
                try:
                    from aiogram.types import FSInputFile
                    photo = FSInputFile(image_path)
                    
                    await message.answer_photo(
                        photo,
                        caption=f"🔍 **ID: {user_id} bo'yicha topilgan ma'lumotlar**\n\n"
                               f"📊 Jami {len(result)} ta natija topildi\n"
                               f"🤖 SAMDAQU qidiruv boti",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    # Vaqtinchalik rasmni o'chirish
                    try:
                        os.remove(image_path)
                        print(f"🗑️ Vaqtinchalik rasm o'chirildi: {image_path}")
                    except:
                        pass
                        
                except Exception as e:
                    print(f"❌ Rasm yuborishda xatolik: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Xatolik tafsilotlari
                    if "file too large" in str(e).lower():
                        error_msg = "❌ Rasm hajmi juda katta! Matn ko'rinishida yuborilmoqda..."
                    elif "wrong file type" in str(e).lower():
                        error_msg = "❌ Rasm formati noto'g'ri! Matn ko'rinishida yuborilmoqda..."
                    else:
                        error_msg = f"❌ Rasm yuborib bo'lmadi: {str(e)[:100]}"
                    
                    # Agar rasm yuborib bo'lmasa, matn sifatida yuborish
                    await message.answer(
                        f"{error_msg}\n\n"
                        f"🔍 ID: {user_id} bo'yicha {len(result)} ta natija topildi."
                    )
            else:
                # Agar rasm yaratib bo'lmasa, xabar berish
                await message.answer(
                    "❌ Rasm yaratishda xatolik yuz berdi!\n"
                    "🔄 Qaytadan urinib ko'ring."
                )
        else:
            await message.answer(
                f"❌ ID: {user_id} bo'yicha ma'lumot topilmadi.\n\n"
                "🔍 Boshqa ID bilan urinib ko'ring."
            )
            
    except Exception as e:
        logger.error(f"Qidiruvda xatolik: {e}")
        await message.answer(
            "❌ Qidiruvda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring."
        )

async def list_files(message: Message):
    """Admin fayllar ro'yxatini ko'rsatish"""
    try:
        if not TelegramBot.is_admin(message.from_user.id):
            await message.answer(
                    "❌ Bu komanda faqat admin uchun!\n\n"
                    "👨‍💻 Admin @shohjahon_o5")
            return
        
        files = excel_handler.get_file_list()
        
        if not files:
            await message.answer("📭 Excel fayllari yo'q.\n\n📄 Yangi fayl yuklash uchun faylni to'g'ridan-to'g'ri yuboring!")
            return
        
        response_text = "📁 **Excel fayllari:**\n\n"
        
        for i, filename in enumerate(files, 1):
            try:
                file_path = os.path.join(EXCEL_FILES_DIR, filename)
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)
                
                # Fayl nomidagi _ belgisini escape qilish
                safe_filename = filename.replace('_', '\\_')
                del_command = f"/del_{filename}".replace('_', '\\_')
                
                response_text += f"{i}. 📄 `{safe_filename}`\n"
                response_text += f"   📊 Hajmi: {file_size_mb:.2f} MB\n"
                response_text += f"   🗑️ O'chirish uchun: `{del_command}`\n\n"
            except Exception as file_error:
                print(f"DEBUG: {filename} fayli ma'lumotlarini olishda xatolik: {file_error}")
                safe_filename = filename.replace('_', '\\_')
                del_command = f"/del_{filename}".replace('_', '\\_')
                response_text += f"{i}. 📄 `{safe_filename}`\n"
                response_text += f"   📊 Hajmi: Noma'lum\n"
                response_text += f"   🗑️ O'chirish uchun: `{del_command}`\n\n"
        
        response_text += "\n� **Yangi fayl qo'shish:**\n"
        response_text += "Faylni to'g'ridan-to'g'ri yuboring!\n\n"
        response_text += "⚠️ **Diqqat:** Fayl o'chirgandan so'ng, u bilan bog'liq barcha ma'lumotlar o'chib ketadi!"
        
        await message.answer(response_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Fayllar ro'yxatini ko'rsatishda xatolik: {e}")
        await message.answer(
            "❌ Fayllar ro'yxatini ko'rsatishda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )

async def show_stats(message: Message):
    """Statistikani ko'rsatish"""
    try:
        if not TelegramBot.is_admin(message.from_user.id):
            await message.answer(
                    "❌ Bu komanda faqat admin uchun!\n\n"
                    "👨‍💻 Admin @shohjahon_o5")
            return
        
        # Statistikani olish
        stats = db.get_stats()
        excel_stats = excel_handler.get_stats()
        daily_stats = db.get_daily_stats(7)
        
        stats_text = f"""
📊 **Bot statistikasi:**

👥 **Umumiy foydalanuvchilar:** {stats['total_users']} ta
🔍 **Jami qidiruvlar:** {stats['total_searches']} ta
📁 **Excel fayllar:** {excel_stats['files_count']} ta
📊 **Jami yozuvlar:** {excel_stats['total_records']} ta

📈 **Oxirgi 7 kun:**
"""
        
        for date, count in daily_stats.items():
            stats_text += f"• {date}: {count} ta qidiruv\n"
        
        await message.answer(stats_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Statistikani ko'rsatishda xatolik: {e}")
        await message.answer(
            "❌ Statistikani ko'rsatishda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )

async def notify_users_new_file(file_name: str, admin_name: str):
    """Yangi fayl yuklanganda barcha foydalanuvchilarga bildirish yuborish"""
    users = db.get_all_users()
    success_count = 0
    error_count = 0
    
    # Adminni istisno qilish
    admin_id = ADMIN_ID
    
    for user_id in users:
        # Admin ga yubormaslik
        if user_id == admin_id:
            continue
            
        try:
            notification_text = f"""
📢 **YANGI NAZORAT JADVALI!**

👨‍💻 Yukladi: {admin_name}

ID raqamingizni yuboring va nazorat sanangizni bilib oling.

🤖 SAMDAQU qidiruv boti
            """
            
            await bot.send_message(user_id, notification_text, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Exception as e:
            logger.error(f"Bildirish yuborishda xatolik (user {user_id}): {e}")
            error_count += 1
    
    print(f"📢 Bildirish yuborish natijalari: ✅ {success_count} ta, ❌ {error_count} ta")

async def broadcast_message(message: Message, text: str):
    """Barcha foydalanuvchilarga xabar yuborish - shaxsiy o'zgaruvchilar bilan"""
    if not TelegramBot.is_admin(message.from_user.id):
        return
    
    users = db.get_all_users()
    success_count = 0
    error_count = 0
    
    for user_id in users:
        try:
            # Foydalanuvchi ma'lumotlarini olish
            user_info = db.get_user_info(user_id)
            
            # Shaxsiylashtirilgan xabar yaratish
            personalized_text = text
            
            if user_info:
                first_name = user_info.get('full_name', '').split()[0] if user_info.get('full_name') else 'Foydalanuvchi'
                username = user_info.get('username', '')
                
                # O'zgaruvchilarni almashtirish
                personalized_text = text.replace('{first_name}', first_name)
                personalized_text = personalized_text.replace('{username}', f"@{username}" if username else '')
                personalized_text = personalized_text.replace('{user_id}', str(user_id))
            
            await bot.send_message(user_id, personalized_text)
            success_count += 1
        except Exception as e:
            logger.error(f"Xabar yuborishda xatolik (user {user_id}): {e}")
            error_count += 1
    
    await message.answer(
        f"📢 **Xabar yuborish natijalari:**\n\n"
        f"✅ Muvaffaqiyatli: {success_count} ta\n"
        f"❌ Xatolik: {error_count} ta\n"
        f"📊 Jami: {len(users)} ta foydalanuvchi",
        parse_mode=ParseMode.MARKDOWN
    )

async def manage_subscription_channels(message: Message):
    """Majburiy obuna kanallarini boshqarish"""
    try:
        current_channels = channel_manager.get_channels()
        
        if not current_channels:
            # Kanal qo'shish rejimi
            await message.answer(
                "🔐 **Majburiy obuna kanali qo'shish:**\n\n"
                "📋 Kanal qo'shish uchun quyidagi formatlarda yuboring:\n"
                "```\n@channel_username\nhttps://t.me/channel_username\nt.me/channel_username\n```\n\n"
                "❌ Bekor qilish uchun 'bekor' deb yozing.\n\n"
                "📌 Eslatma: Faqat 1 ta majburiy kanal qo'shish mumkin!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Kanalni o'chirish yoki ko'rish
        channel_info = current_channels[0]
        
        # Kanal ma'lumotlarini escape qilish
        safe_id = channel_info['id'].replace('_', '\\_')
        safe_name = channel_info['name'].replace('_', '\\_')
        
        channel_text = f"📢 **Joriy majburiy kanal:**\n\n"
        channel_text += f"🔗 Kanal: @{safe_id}\n"
        channel_text += f"📝 Nomi: {safe_name}\n"
        channel_text += f"📅 Qo'shilgan sana: {channel_info['added_date'][:10]}\n\n"
        channel_text += "🗑️ **Kanalni o'chirish uchun:**\n"
        channel_text += "`ochirish` deb yozing\n\n"
        channel_text += "❌ **Bekor qilish uchun:**\n"
        channel_text += "`bekor` deb yozing"
        
        await message.answer(channel_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Majburiy obuna menuni ochishda xatolik: {e}")
        await message.answer(
            "❌ Majburiy obuna menuni ochishda xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )

async def handle_subscription_management(message: Message):
    """Majburiy obuna kanallarini boshqarish - xabarlar qayta ishlash"""
    try:
        message_text = message.text.strip()
        
        if message_text.lower() == 'bekor':
            await message.answer(
                "❌ Majburiy obuna boshqaruvi bekor qilindi.\n\n"
                "🔙 Admin menyuga qaytish uchun '📁 Fayllar' tugmasini bosing.",
                reply_markup=admin_keyboard
            )
            return
        
        current_channels = channel_manager.get_channels()
        
        if not current_channels:
            # Yangi kanal qo'shish - faqat @username yoki https://t.me/ linklar
            channel_input = message_text.strip()
            
            # Validatsiya - faqat @username yoki https://t.me/ formatlar
            is_valid = False
            channel_id = channel_input
            
            if channel_input.startswith('@'):
                # @username format
                if len(channel_input) > 1 and channel_input[1:].replace('_', '').replace('-', '').isalnum():
                    is_valid = True
                    channel_id = channel_input
            elif channel_input.startswith('https://t.me/'):
                # https://t.me/username format
                username = channel_input.replace('https://t.me/', '').replace('/', '')
                if username and username.replace('_', '').replace('-', '').isalnum():
                    is_valid = True
                    channel_id = '@' + username
            elif channel_input.startswith('t.me/'):
                # t.me/username format
                username = channel_input.replace('t.me/', '').replace('/', '')
                if username and username.replace('_', '').replace('-', '').isalnum():
                    is_valid = True
                    channel_id = '@' + username
            
            if not is_valid:
                await message.answer(
                    "❌ Noto'g'ri kanal formati!\n\n"
                    "📋 **To'g'ri formatlar:**\n"
                    "• `@channel_username`\n"
                    "• `https://t.me/channel_username`\n"
                    "• `t.me/channel_username`\n\n"
                    "🔄 Qaytadan urinib ko'ring yoki 'bekor' deb yozing."
                )
                return
            
            # Kanalni qo'shish
            if channel_manager.add_channel(channel_id, channel_id):
                safe_channel_id = channel_id.replace('_', '\\_')
                await message.answer(
                    f"✅ Majburiy obuna kanali muvaffaqiyatli qo'shildi!\n\n"
                    f"📢 Kanal: {safe_channel_id}\n\n"
                    f"🔐 Endi foydalanuvchilar shu kanalga obuna bo'lishi shart.\n\n"
                    f"🔙 Admin menyuga qaytish uchun '📁 Fayllar' tugmasini bosing.",
                    reply_markup=admin_keyboard
                )
            else:
                await message.answer(
                    f"❌ Kanalni qo'shishda xatolik yuz berdi!\n\n"
                    f"📋 Ehtimol sabablar:\n"
                    f"• Kanal allaqachon qo'shilgan\n"
                    f"• Bot kanalda admin emas\n\n"
                    f"🔄 Qaytadan urinib ko'ring yoki 'bekor' deb yozing."
                )
        else:
            # Kanalni o'chirish
            if message_text.lower() == 'ochirish':
                channel_info = current_channels[0]
                if channel_manager.remove_channel(channel_info['id']):
                    safe_id = channel_info['id'].replace('_', '\\_')
                    await message.answer(
                        f"✅ Majburiy obuna kanali o'chirildi!\n\n"
                        f"📢 O'chirilgan kanal: @{safe_id}\n\n"
                        f"🔐 Endi majburiy obuna talabi yo'q.\n\n"
                        f"🔙 Admin menyuga qaytish uchun '📁 Fayllar' tugmasini bosing.",
                        reply_markup=admin_keyboard
                    )
                else:
                    await message.answer(
                        "❌ Kanalni o'chirishda xatolik yuz berdi!\n\n"
                        "🔄 Qaytadan urinib ko'ring."
                    )
            else:
                await message.answer(
                    "❌ Noto'g'ri buyruq!\n\n"
                    "📋 Mavjud buyruqlar:\n"
                    "• `ochirish` - kanalni o'chirish\n"
                    "• `bekor` - bekor qilish\n\n"
                    "🔄 Qaytadan urinib ko'ring."
                )
    
    except Exception as e:
        logger.error(f"Majburiy obuna boshqarishda xatolik: {e}")
        await message.answer(
            "❌ Xatolik yuz berdi!\n"
            "🔄 Qaytadan urinib ko'ring.\n\n"
            "👨‍💻 Admin @shohjahon_o5"
        )

# =================================================================
# ASOSIY FUNKSIYA
# =================================================================

async def main():
    """Botni ishga tushurish - Railway uchun optimallashtirilgan"""
    try:
        # Logging sozlamalari
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        logger = logging.getLogger(__name__)
        
        print("🤖 Excel qidiruv boti ishga tushmoqda...")
        print(f"👨‍💻 Admin ID: {ADMIN_ID}")
        print(f"📁 Excel fayllar papkasi: {EXCEL_FILES_DIR}")
        
        # Bot yaratish
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        )
        
        # Dispatcher yaratish
        dp = Dispatcher()
        
        # Global obyektlarni yaratish
        global excel_handler, channel_manager, db
        
        # Papkalarni yaratish
        os.makedirs(EXCEL_FILES_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        os.makedirs(os.path.dirname(CHANNELS_DB), exist_ok=True)
        os.makedirs("data/temp_images", exist_ok=True)
        
        # Obyektlarni yaratish
        excel_handler = ExcelHandler()
        channel_manager = ChannelManager()
        db = Database()
        
        # Excel fayllarini yuklash
        await excel_handler.load_existing_files_async()
        print(f"📊 Yuklangan Excel fayllar: {len(excel_handler.get_file_list())} ta")
        
        # Handlerlarni ro'yxatga olish
        from aiogram import Router
        router = Router()
        
        # Handlerlarni qo'shish
        router.message.register(start_command, Command("start"))
        router.callback_query.register(start_search_callback, F.data == "start_search")
        router.callback_query.register(check_subscription_callback, F.data == "check_subscription")
        router.message.register(help_command, Command("help"))
        router.message.register(handle_document, F.document)
        router.message.register(delete_file_command, Command("del"))
        router.message.register(handle_message, F.text & ~F.command)
        
        dp.include_router(router)
        
        # Botni ishga tushurish
        print("🚀 Bot polling boshlandi...")
        await dp.start_polling(bot)
        
    except Exception as e:
        print(f"❌ Botni ishga tushirishda xatolik: {e}")
        import traceback
        traceback.print_exc()
        # Railway da bot qayta ishga tushishi uchun
        await asyncio.sleep(5)
        await main()
    finally:
        # Sessionni yopish
        if 'bot' in locals():
            await bot.session.close()
            print("🔒 Bot session yopildi")

if __name__ == "__main__":
    asyncio.run(main())
