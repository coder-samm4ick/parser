#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import os
import json
from typing import List, Dict
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = "8891656964:AAFVJpGEuGpc_D03GNvzMSvtlDCGqM8Wv90"
ADMIN_IDS = [8563327706, 2015797733]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================================
# БАЗА ДАННЫХ (SQLite)
# ============================================================

import aiosqlite

DB_FILE = "gifts.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT UNIQUE,
                name TEXT,
                parsed_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER,
                gift_address TEXT UNIQUE,
                gift_name TEXT,
                owner_address TEXT,
                owner_username TEXT,
                found_at TEXT,
                FOREIGN KEY (collection_id) REFERENCES collections(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                registered_at TEXT
            )
        """)
        await db.commit()

async def add_collection(address: str, name: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO collections (address, name, parsed_at) VALUES (?, ?, ?)",
            (address, name, datetime.now().isoformat())
        )
        await db.commit()

async def get_collections():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM collections")
        return await cursor.fetchall()

async def add_gift(collection_id: int, gift_address: str, gift_name: str, owner: str, username: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT OR REPLACE INTO gifts 
            (collection_id, gift_address, gift_name, owner_address, owner_username, found_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (collection_id, gift_address, gift_name, owner, username, datetime.now().isoformat()))
        await db.commit()

async def get_gifts_by_collection(collection_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM gifts WHERE collection_id = ?", (collection_id,))
        return await cursor.fetchall()

async def add_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, registered_at) VALUES (?, ?, ?)",
            (user_id, username, datetime.now().isoformat())
        )
        await db.commit()

# ============================================================
# ПАРСЕР TELEGRAM NFT ПОДАРКОВ
# ============================================================

class TelegramGiftParser:
    """Парсер всех NFT-подарков в Telegram"""
    
    def __init__(self):
        self.session = None
        self.toncenter_url = "https://toncenter.com/api/v2/"
        
        # Известные коллекции Telegram Gift NFT
        self.known_collections = [
            {"name": "Telegram Gifts", "address": "EQD4FPq-PRDieyQKkizfTRPUSpMq9LkWxmVS9tzN4c4ZBUpc"},
            {"name": "Gift Collection", "address": "EQCcLAzU6M5jYj_g6t8Lizj3Wc07n25C9ou4Tbp5W0eTsQ7r"},
            {"name": "Stars Gifts", "address": "EQDk7dWj4S6_5hX5tC8s9nK3mJ2pL1qR4tY7uW8iZ3XyN"},
            # Добавь новые коллекции по мере обнаружения
        ]
    
    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def _request(self, url: str, params: dict = None) -> Dict:
        session = await self._get_session()
        try:
            async with session.get(url, params=params or {}, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_all_gifts_in_collection(self, collection_address: str) -> List[Dict]:
        """
        Получить ВСЕ подарки в коллекции
        """
        items_url = f"{self.toncenter_url}getNftItems"
        all_items = []
        offset = 0
        limit = 100
        
        while True:
            items_data = await self._request(items_url, {
                "address": collection_address,
                "limit": limit,
                "offset": offset
            })
            
            if "error" in items_data:
                break
            
            items = items_data.get("result", [])
            if not items:
                break
            
            all_items.extend(items)
            
            if len(items) < limit:
                break
            
            offset += limit
        
        return all_items
    
    async def get_gift_owner(self, gift_address: str) -> Dict:
        """
        Получить владельца конкретного подарка
        """
        url = f"{self.toncenter_url}getNftInfo"
        data = await self._request(url, {"address": gift_address})
        
        if "error" in data:
            return {}
        
        result = data.get("result", {})
        owner = result.get("owner", {})
        
        # Получаем username владельца
        owner_address = owner.get("address", "")
        username = ""
        if owner_address:
            account_url = f"{self.toncenter_url}getAddressInformation"
            account_data = await self._request(account_url, {"address": owner_address})
            if "error" not in account_data:
                username = account_data.get("result", {}).get("username", "")
        
        return {
            "address": gift_address,
            "name": result.get("name", "Unknown"),
            "owner_address": owner_address,
            "owner_username": username,
            "collection": result.get("collection", {}).get("address", "")
        }
    
    async def scan_all_gifts(self) -> List[Dict]:
        """
        Сканировать ВСЕ подарки во ВСЕХ коллекциях
        """
        all_gifts = []
        seen_addresses = set()
        
        for collection in self.known_collections:
            collection_address = collection["address"]
            collection_name = collection["name"]
            
            print(f"🔍 Сканирую коллекцию: {collection_name}")
            
            items = await self.get_all_gifts_in_collection(collection_address)
            
            for item in items:
                gift_address = item.get("address", "")
                if not gift_address or gift_address in seen_addresses:
                    continue
                
                owner_info = await self.get_gift_owner(gift_address)
                
                all_gifts.append({
                    "collection_name": collection_name,
                    "collection_address": collection_address,
                    "gift_address": gift_address,
                    "gift_name": item.get("name", "Unknown"),
                    "owner_address": owner_info.get("owner_address", ""),
                    "owner_username": owner_info.get("owner_username", ""),
                    "index": item.get("index", 0)
                })
                seen_addresses.add(gift_address)
                
                # Сохраняем в БД
                await add_gift(1, gift_address, item.get("name", "Unknown"), 
                              owner_info.get("owner_address", ""), 
                              owner_info.get("owner_username", ""))
            
            await add_collection(collection_address, collection_name)
        
        return all_gifts
    
    async def search_gifts_by_name(self, search_name: str) -> List[Dict]:
        """
        Искать подарки по названию
        """
        results = []
        
        for collection in self.known_collections:
            items = await self.get_all_gifts_in_collection(collection["address"])
            
            for item in items:
                if search_name.lower() in item.get("name", "").lower():
                    gift_address = item.get("address", "")
                    owner_info = await self.get_gift_owner(gift_address)
                    
                    results.append({
                        "collection_name": collection["name"],
                        "gift_address": gift_address,
                        "gift_name": item.get("name", "Unknown"),
                        "owner_address": owner_info.get("owner_address", ""),
                        "owner_username": owner_info.get("owner_username", ""),
                        "index": item.get("index", 0)
                    })
        
        return results

parser = TelegramGiftParser()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔍 Найти подарок", callback_data="search_gift")],
        [InlineKeyboardButton(text="📊 Все подарки", callback_data="all_gifts")],
        [InlineKeyboardButton(text="🔄 Сканировать все", callback_data="scan_all")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Обновить коллекции", callback_data="admin_refresh")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

# ============================================================
# КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    await init_db()
    await add_user(user_id, message.from_user.username or "")
    
    await message.answer(
        f"🟢 <b>@{message.from_user.username or 'User'}</b>, привет!\n\n"
        "Этот бот ищет ВСЕ Telegram NFT-подарки и их владельцев.\n\n"
        "🎁 <b>Команды:</b>\n"
        "/scan - сканировать все коллекции\n"
        "/search (название) - искать подарок по названию\n"
        "/gift (адрес) - найти владельца подарка\n"
        "/holders (коллекция) - все подарки в коллекции\n\n"
        "📌 <i>Все данные из открытых источников TON</i>",
        parse_mode="HTML",
        reply_markup=main_menu(is_admin)
    )

@dp.message(Command("scan"))
async def scan_all(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Нет прав.")
        return
    
    await message.answer("📡 Начинаю сканирование ВСЕХ коллекций... Это может занять время.")
    
    gifts = await parser.scan_all_gifts()
    
    if not gifts:
        await message.answer("❌ Не найдено ни одного подарка.")
        return
    
    text = f"🎯 <b>Найдено {len(gifts)} подарков</b>\n\n"
    
    # Группируем по коллекциям
    collections = {}
    for g in gifts:
        col = g.get("collection_name", "Unknown")
        if col not in collections:
            collections[col] = []
        collections[col].append(g)
    
    for col_name, col_gifts in collections.items():
        text += f"📦 <b>{col_name}</b>: {len(col_gifts)} подарков\n"
        for g in col_gifts[:5]:
            username = f"@{g['owner_username']}" if g['owner_username'] else "❌ Нет username"
            text += f"   • {g['gift_name']} → {username}\n"
        if len(col_gifts) > 5:
            text += f"   ... и ещё {len(col_gifts) - 5}\n"
        text += "\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("search"))
async def search_gift(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ Использование: /search (название)\nПример: /search Yan")
        return
    
    search_name = args.strip()
    await message.answer(f"🔍 Ищу подарки с названием «{search_name}»...")
    
    results = await parser.search_gifts_by_name(search_name)
    
    if not results:
        await message.answer(f"❌ Подарки с названием «{search_name}» не найдены.")
        return
    
    text = f"🎯 <b>Найдено {len(results)} подарков с названием «{search_name}»</b>\n\n"
    
    for r in results[:20]:
        username = f"@{r['owner_username']}" if r['owner_username'] else "❌ Нет username"
        text += f"📦 {r['gift_name']}\n"
        text += f"   👤 {username}\n"
        text += f"   📍 <code>{r['gift_address'][:20]}...</code>\n\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("gift"))
async def get_gift(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ /gift (адрес_подарка)")
        return
    
    gift_address = args.strip()
    await message.answer("🔍 Ищу подарок...")
    
    info = await parser.get_gift_owner(gift_address)
    
    if not info:
        await message.answer("❌ Подарок не найден.")
        return
    
    text = f"🎁 <b>Подарок: {info.get('name', 'Unknown')}</b>\n\n"
    text += f"📍 Адрес: <code>{info.get('address', '')}</code>\n"
    text += f"👤 Владелец: <code>{info.get('owner_address', '')}</code>\n"
    if info.get('owner_username'):
        text += f"   Username: @{info.get('owner_username')}\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("holders"))
async def get_holders(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ /holders (адрес_коллекции)")
        return
    
    collection = args.strip()
    await message.answer("📡 Загружаю подарки из коллекции...")
    
    items = await parser.get_all_gifts_in_collection(collection)
    
    if not items:
        await message.answer("❌ Коллекция не найдена.")
        return
    
    text = f"🎯 <b>Найдено {len(items)} подарков в коллекции</b>\n\n"
    
    for item in items[:15]:
        gift_address = item.get("address", "")
        owner_info = await parser.get_gift_owner(gift_address)
        username = f"@{owner_info.get('owner_username', '')}" if owner_info.get('owner_username') else "❌ Нет username"
        text += f"📦 {item.get('name', 'Unknown')}\n"
        text += f"   👤 {username}\n"
        text += f"   📍 <code>{gift_address[:20]}...</code>\n\n"
    
    await message.answer(text, parse_mode="HTML")

# ============================================================
# CALLBACK
# ============================================================

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS
    data = callback.data
    
    if data == "search_gift":
        await callback.message.answer("🔍 Введите команду:\n/search (название)")
    
    elif data == "all_gifts":
        await callback.message.answer("📊 Введите команду:\n/holders (адрес_коллекции)")
    
    elif data == "scan_all":
        await scan_all(callback.message)
    
    elif data == "admin_panel":
        if is_admin:
            await callback.message.edit_text(
                "⚙️ <b>Админ-панель</b>",
                parse_mode="HTML",
                reply_markup=admin_keyboard()
            )
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    elif data == "admin_stats":
        if is_admin:
            collections = await get_collections()
            await callback.message.answer(f"📊 Коллекций в БД: {len(collections)}")
    
    elif data == "admin_refresh":
        if is_admin:
            await callback.message.answer("🔄 Обновляю коллекции...")
            await scan_all(callback.message)
    
    elif data == "back_to_menu":
        await callback.message.edit_text(
            "🟢 <b>Главное меню</b>",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin)
        )
    
    await callback.answer()

# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    await init_db()
    print("🤖 Telegram Gift Parser Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())