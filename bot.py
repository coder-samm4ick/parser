#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NFT Парсинг Бот - created by @bestdevshell
Полноценный бот для поиска владельцев редких NFT-подарков в Telegram 
"""

import asyncio
import aiohttp
import aiosqlite
import json
import os
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ============================================================
# ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ============================================================

load_dotenv()

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "123456789").split(",")]

# TON API - MAINNET
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")
TONCENTER_URL = "https://toncenter.com/api/v2/"  # MAINNET
TONAPI_URL = "https://tonapi.io/v1/"  # MAINNET

# Настройки парсинга
MAX_RESULTS_PER_GIFT = 10
PARSE_INTERVAL_SECONDS = 5
MAX_ITERATIONS = 10

# База данных
DB_FILE = "nft_parsing.db"

# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================

class ParseState(StatesGroup):
    waiting_for_gift_name = State()
    waiting_for_collection = State()

# ============================================================
# БАЗА ДАННЫХ
# ============================================================

async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_admin INTEGER DEFAULT 0,
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                collection TEXT,
                rarity TEXT,
                floor_price REAL,
                max_supply INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gift_id INTEGER,
                owner_address TEXT,
                owner_username TEXT,
                quantity INTEGER DEFAULT 1,
                found_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (gift_id) REFERENCES gifts(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS parse_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_id INTEGER,
                status TEXT DEFAULT 'running',
                found_count INTEGER DEFAULT 0,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT
            )
        """)
        await db.commit()
        print("✅ База данных инициализирована")

async def add_user(user_id: int, username: str, first_name: str):
    """Добавление или обновление пользователя"""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_active)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, username, first_name))
        await db.commit()

async def add_gift(name: str, collection: str, rarity: str = "", floor_price: float = 0, max_supply: int = 0) -> int:
    """Добавление подарка в базу"""
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("""
            INSERT INTO gifts (name, collection, rarity, floor_price, max_supply)
            VALUES (?, ?, ?, ?, ?)
        """, (name, collection, rarity, floor_price, max_supply))
        await db.commit()
        return cursor.lastrowid

async def add_owner(gift_id: int, address: str, username: str = "", quantity: int = 1):
    """Добавление владельца подарка"""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO owners (gift_id, owner_address, owner_username, quantity)
            VALUES (?, ?, ?, ?)
        """, (gift_id, address, username, quantity))
        await db.commit()

async def get_gifts() -> List[Dict]:
    """Получение всех подарков"""
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM gifts ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(zip(['id', 'name', 'collection', 'rarity', 'floor_price', 'max_supply', 'created_at'], row)) for row in rows]

async def get_owners_by_gift(gift_id: int) -> List[Dict]:
    """Получение владельцев подарка"""
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM owners WHERE gift_id = ? ORDER BY quantity DESC", (gift_id,))
        rows = await cursor.fetchall()
        return [dict(zip(['id', 'gift_id', 'owner_address', 'owner_username', 'quantity', 'found_at'], row)) for row in rows]

# ============================================================
# TON API ИНТЕГРАЦИЯ (MAINNET)
# ============================================================

class TONAPI:
    """Класс для работы с TON API (Mainnet)"""
    
    def __init__(self):
        self.session = None
        self.api_key = TONCENTER_API_KEY
        self.base_url = TONCENTER_URL  # MAINNET
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение или создание сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def _make_request(self, method: str, params: Dict = None) -> Dict:
        """Универсальный метод для запросов к TON API"""
        session = await self._get_session()
        url = f"{self.base_url}{method}"
        
        if params is None:
            params = {}
        
        if self.api_key:
            params["api_key"] = self.api_key
        
        try:
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    return await response.json()
                return {"error": f"HTTP {response.status}", "detail": await response.text()}
        except asyncio.TimeoutError:
            return {"error": "Timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_nft_collection(self, collection_address: str) -> Dict:
        """Получение информации о коллекции NFT (Mainnet)"""
        return await self._make_request("getNftCollection", {"address": collection_address})
    
    async def get_nft_items(self, collection_address: str, limit: int = 100) -> List[Dict]:
        """Получение NFT в коллекции (Mainnet)"""
        result = await self._make_request("getNftItems", {
            "address": collection_address,
            "limit": limit
        })
        return result.get("result", []) if "error" not in result else []
    
    async def get_nft_transfers(self, address: str, limit: int = 50) -> List[Dict]:
        """Получение истории переводов NFT (Mainnet)"""
        result = await self._make_request("getNftTransfers", {
            "address": address,
            "limit": limit
        })
        return result.get("result", []) if "error" not in result else []
    
    async def get_account_info(self, address: str) -> Dict:
        """Получение информации об аккаунте (Mainnet)"""
        return await self._make_request("getAddressInformation", {"address": address})
    
    async def search_nft_holders(self, collection_address: str, target_owner: str = None) -> List[Dict]:
        """Поиск владельцев NFT в коллекции (Mainnet)"""
        holders = []
        seen_addresses = set()
        
        # Пробуем получить через getNftItems
        items = await self.get_nft_items(collection_address, 200)
        
        if items:
            for item in items:
                owner = item.get("owner", {})
                owner_address = owner.get("address", "")
                
                if owner_address and owner_address not in seen_addresses:
                    if target_owner is None or owner_address.lower() == target_owner.lower():
                        holders.append({
                            "address": owner_address,
                            "item_name": item.get("name", "Unknown"),
                            "item_index": item.get("index", 0),
                            "item_address": item.get("address", "")
                        })
                        seen_addresses.add(owner_address)
        
        # Если через getNftItems ничего не нашли, пробуем через getNftCollection
        if not holders:
            collection_info = await self.get_nft_collection(collection_address)
            if "error" not in collection_info:
                owners = collection_info.get("owners", [])
                for owner in owners:
                    owner_address = owner.get("address", "")
                    if owner_address and owner_address not in seen_addresses:
                        if target_owner is None or owner_address.lower() == target_owner.lower():
                            holders.append({
                                "address": owner_address,
                                "item_name": "Unknown",
                                "item_index": 0,
                                "item_address": ""
                            })
                            seen_addresses.add(owner_address)
        
        return holders

# ============================================================
# КЛАВИАТУРЫ (ИСПРАВЛЕНО)
# ============================================================

def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="🔍 Начать парсинг", callback_data="start_parse")],
        [InlineKeyboardButton(text="📊 Список подарков", callback_data="list_gifts")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="stats")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    """Админ-панель"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить подарок", callback_data="admin_add_gift")],
        [InlineKeyboardButton(text="🔍 Парсить по коллекции", callback_data="admin_parse_collection")],
        [InlineKeyboardButton(text="📊 Все пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

# ============================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Словарь для хранения активных сессий парсинга
active_sessions: Dict[int, bool] = {}

# ============================================================
# ФОНДОВЫЕ КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    
    await add_user(user_id, username, first_name)
    
    is_admin = user_id in ADMIN_IDS
    
    await message.answer(
        f"🟢 <b>@{username}</b>, привет!\n\n"
        "Этот бот поможет искать владельцев Telegram NFT-подарков в Mainnet.\n\n"
        "<b>🔍 Возможности:</b>\n"
        "• Поиск владельцев редких NFT\n"
        "• Мониторинг коллекций\n"
        "• Анализ рынка\n"
        f"\n👥 <b>Админы:</b> {', '.join(map(str, ADMIN_IDS))}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(is_admin)
    )

@dp.message(Command("parse"))
async def cmd_parse(message: types.Message, command: CommandObject):
    """Команда для запуска парсинга"""
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    if not is_admin:
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    if user_id in active_sessions and active_sessions[user_id]:
        await message.answer("⚠️ Парсинг уже запущен. Используйте /stop для остановки.")
        return
    
    # Получаем аргументы команды
    args = command.args
    if args:
        parts = args.split(maxsplit=1)
        if len(parts) >= 2:
            collection = parts[0]
            target_owner = parts[1] if len(parts) > 1 else None
            active_sessions[user_id] = True
            await message.answer(f"🔍 Запущен поиск владельцев NFT в коллекции {collection}...")
            asyncio.create_task(run_parsing(message.chat.id, user_id, collection, target_owner))
            return
        else:
            collection = parts[0]
            active_sessions[user_id] = True
            await message.answer(f"🔍 Запущен поиск владельцев NFT в коллекции {collection}...")
            asyncio.create_task(run_parsing(message.chat.id, user_id, collection))
            return
    
    await message.answer(
        "❌ Использование: /parse <адрес_коллекции> [адрес_владельца]\n\n"
        "Пример:\n"
        "/parse EQD4FPq-PRDieyQKkizfTRPUSpMq9LkWxmVS9tzN4c4ZBUpc\n"
        "/parse EQD4FPq-PRDieyQKkizfTRPUSpMq9LkWxmVS9tzN4c4ZBUpc UQD..."
    )

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    """Остановка парсинга"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав.")
        return
    
    if user_id in active_sessions and active_sessions[user_id]:
        active_sessions[user_id] = False
        await message.answer("🛑 Парсинг остановлен.")
    else:
        await message.answer("ℹ️ Активных сессий нет.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Статус парсинга"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав.")
        return
    
    status = "🟢 Активен" if active_sessions.get(user_id, False) else "🔴 Остановлен"
    await message.answer(f"📊 Статус парсинга: {status}")

@dp.message(Command("add_gift"))
async def cmd_add_gift(message: types.Message, command: CommandObject):
    """Добавление подарка в базу"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав.")
        return
    
    args = command.args
    if not args:
        await message.answer(
            "❌ Использование: /add_gift <название> <адрес_коллекции> [редкость] [цена]\n\n"
            "Пример:\n"
            "/add_gift TON Diamonds EQD4FPq-PRDieyQKkizfTRPUSpMq9LkWxmVS9tzN4c4ZBUpc legendary 100"
        )
        return
    
    parts = args.split(maxsplit=3)
    if len(parts) < 2:
        await message.answer("❌ Укажите название и адрес коллекции (mainnet).")
        return
    
    name = parts[0]
    collection = parts[1]
    rarity = parts[2] if len(parts) > 2 else ""
    floor_price = float(parts[3]) if len(parts) > 3 else 0
    
    gift_id = await add_gift(name, collection, rarity, floor_price)
    await message.answer(f"✅ Подарок «{name}» добавлен (ID: {gift_id})")

@dp.message(Command("list_gifts"))
async def cmd_list_gifts(message: types.Message):
    """Список подарков в базе"""
    gifts = await get_gifts()
    if not gifts:
        await message.answer("📭 В базе пока нет подарков.")
        return
    
    text = "🎁 <b>Список подарков:</b>\n\n"
    for gift in gifts[:20]:
        text += f"• <b>{gift['name']}</b>\n"
        text += f"  📦 Коллекция: <code>{gift['collection'][:30]}...</code>\n"
        text += f"  🏷️ Редкость: {gift['rarity'] or 'Не указана'}\n"
        text += f"  💰 Цена: {gift['floor_price'] or 'N/A'}\n"
        text += f"  🆔 ID: {gift['id']}\n\n"
    
    await message.answer(text, parse_mode="HTML")

# ============================================================
# ОБРАБОТЧИКИ CALLBACK
# ============================================================

@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик callback-запросов"""
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "start_parse":
        if user_id not in ADMIN_IDS:
            await callback.answer("⛔ Нет прав.", show_alert=True)
            return
        
        if user_id in active_sessions and active_sessions[user_id]:
            await callback.answer("⚠️ Парсинг уже запущен", show_alert=True)
            return
        
        await callback.message.answer(
            "🔍 Введите адрес коллекции (mainnet) для парсинга:\n"
            "Или используйте /parse <адрес>"
        )
        await callback.answer()
    
    elif data == "list_gifts":
        await cmd_list_gifts(callback.message)
        await callback.answer()
    
    elif data == "stats":
        await cmd_status(callback.message)
        await callback.answer()
    
    elif data == "admin_panel":
        if user_id in ADMIN_IDS:
            await callback.message.edit_text(
                "⚙️ <b>Админ-панель</b>\n\n"
                "Выберите действие:",
                parse_mode="HTML",
                reply_markup=admin_panel_keyboard()
            )
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    elif data == "back_to_menu":
        is_admin = user_id in ADMIN_IDS
        await callback.message.edit_text(
            "🟢 <b>Главное меню</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(is_admin)
        )
    
    elif data == "admin_add_gift":
        if user_id in ADMIN_IDS:
            await state.set_state(ParseState.waiting_for_gift_name)
            await callback.message.answer(
                "➕ <b>Добавление нового подарка</b>\n\n"
                "Введите название подарка:",
                parse_mode="HTML"
            )
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    elif data == "admin_users":
        if user_id in ADMIN_IDS:
            async with aiosqlite.connect(DB_FILE) as db:
                cursor = await db.execute("SELECT user_id, username, registered_at FROM users ORDER BY id DESC LIMIT 20")
                users = await cursor.fetchall()
                
                text = "👥 <b>Последние пользователи:</b>\n\n"
                for uid, username, reg_date in users:
                    text += f"• <code>{uid}</code> - @{username or 'Нет юзернейма'} - {reg_date[:10]}\n"
                
                await callback.message.answer(text, parse_mode="HTML")
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    elif data == "admin_parse_collection":
        if user_id in ADMIN_IDS:
            await state.set_state(ParseState.waiting_for_collection)
            await callback.message.answer(
                "🔍 <b>Парсинг коллекции (Mainnet)</b>\n\n"
                "Введите адрес коллекции для поиска владельцев:",
                parse_mode="HTML"
            )
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    await callback.answer()

# ============================================================
# FSM ОБРАБОТЧИКИ
# ============================================================

@dp.message(ParseState.waiting_for_gift_name)
async def process_gift_name(message: types.Message, state: FSMContext):
    """Обработка названия подарка"""
    name = message.text.strip()
    await state.update_data(gift_name=name)
    await state.set_state(ParseState.waiting_for_collection)
    await message.answer(
        f"Название: <b>{name}</b>\n\n"
        "Теперь введите адрес коллекции (mainnet):",
        parse_mode="HTML"
    )

@dp.message(ParseState.waiting_for_collection)
async def process_collection(message: types.Message, state: FSMContext):
    """Обработка адреса коллекции"""
    collection = message.text.strip()
    data = await state.get_data()
    name = data.get("gift_name", "")
    
    if not name:
        await message.answer("❌ Ошибка: название не найдено. Попробуйте /add_gift")
        await state.clear()
        return
    
    gift_id = await add_gift(name, collection)
    await message.answer(
        f"✅ Подарок <b>{name}</b> добавлен!\n"
        f"📦 Коллекция: <code>{collection}</code>\n"
        f"🆔 ID: {gift_id}",
        parse_mode="HTML"
    )
    await state.clear()

# ============================================================
# ОСНОВНАЯ ЛОГИКА ПАРСИНГА (MAINNET)
# ============================================================

async def run_parsing(chat_id: int, user_id: int, collection: str, target_owner: str = None):
    """Основной процесс парсинга в Mainnet"""
    if user_id not in active_sessions:
        active_sessions[user_id] = True
    
    api = TONAPI()
    found_owners = []
    iteration = 0
    
    try:
        await bot.send_message(
            chat_id,
            f"📡 Начинаю сканирование коллекции в Mainnet:\n<code>{collection}</code>\n"
            f"{f'🎯 Целевой владелец: <code>{target_owner}</code>' if target_owner else ''}",
            parse_mode="HTML"
        )
        
        # Получаем информацию о коллекции
        collection_info = await api.get_nft_collection(collection)
        if "error" in collection_info:
            await bot.send_message(
                chat_id,
                f"❌ Ошибка получения коллекции: {collection_info.get('error')}"
            )
            active_sessions[user_id] = False
            return
        
        # Получаем владельцев NFT
        while active_sessions.get(user_id, False) and iteration < MAX_ITERATIONS:
            iteration += 1
            holders = await api.search_nft_holders(collection, target_owner)
            
            for holder in holders:
                if holder["address"] not in [o["address"] for o in found_owners]:
                    found_owners.append(holder)
                    
                    # Отправляем найденного владельца
                    owner_message = (
                        f"🔍 <b>Найден владелец в Mainnet!</b>\n\n"
                        f"📍 Адрес: <code>{holder['address']}</code>\n"
                        f"📦 NFT: {holder.get('item_name', 'Unknown')}\n"
                        f"🔢 Индекс: {holder.get('item_index', 'N/A')}\n"
                    )
                    
                    await bot.send_message(chat_id, owner_message, parse_mode="HTML")
                    
                    # Ищем username через транзакции
                    transfers = await api.get_nft_transfers(holder["address"])
                    if transfers:
                        for tx in transfers:
                            if tx.get("owner_username"):
                                await bot.send_message(
                                    chat_id,
                                    f"📎 <b>Username:</b> @{tx['owner_username']}",
                                    parse_mode="HTML"
                                )
                                break
            
            # Проверка, достигнут ли лимит
            if len(found_owners) >= MAX_RESULTS_PER_GIFT:
                await bot.send_message(
                    chat_id,
                    f"✅ Найдено {len(found_owners)} владельцев. Достигнут лимит."
                )
                break
            
            if not active_sessions.get(user_id, False):
                break
            
            # Задержка между итерациями
            await asyncio.sleep(PARSE_INTERVAL_SECONDS)
        
        # Завершаем сессию
        if active_sessions.get(user_id, False):
            await bot.send_message(
                chat_id,
                f"✅ <b>Сканирование завершено!</b>\n\n"
                f"📊 Найдено владельцев: {len(found_owners)}\n"
                f"🔄 Итераций: {iteration}\n"
                f"⏱️ Затрачено времени: {iteration * PARSE_INTERVAL_SECONDS} сек.\n"
                f"🌐 Сеть: Mainnet",
                parse_mode="HTML"
            )
        else:
            await bot.send_message(chat_id, "🛑 Парсинг остановлен пользователем.")
    
    except asyncio.CancelledError:
        await bot.send_message(chat_id, "🛑 Парсинг был отменён.")
    except Exception as e:
        await bot.send_message(
            chat_id,
            f"❌ Ошибка при парсинге:\n<code>{str(e)}</code>",
            parse_mode="HTML"
        )
    finally:
        active_sessions[user_id] = False

# ============================================================
# МОНИТОРИНГ АКТИВНОСТИ
# ============================================================

async def keep_alive():
    """Фоновый процесс для поддержания активности"""
    while True:
        # Очищаем завершившиеся сессии
        for user_id in list(active_sessions.keys()):
            if not active_sessions.get(user_id):
                del active_sessions[user_id]
        await asyncio.sleep(60)

# ============================================================
# ЗАПУСК БОТА
# ============================================================

async def main():
    """Главная функция запуска бота"""
    await init_db()
    print("🤖 NFT Parsing Bot запущен!")
    print(f"👤 Админы: {ADMIN_IDS}")
    print(f"🌐 Сеть: MAINNET")
    print(f"🔗 API: {TONCENTER_URL}")
    
    # Запускаем фоновый процесс
    asyncio.create_task(keep_alive())
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⏹️ Бот остановлен")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())