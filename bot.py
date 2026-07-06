#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import os
from typing import List, Dict
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",")]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================================
# ПАРСЕР
# ============================================================

class TelegramGiftParser:
    def __init__(self):
        self.session = None
        self.toncenter_url = "https://toncenter.com/api/v2/"
    
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
    
    async def get_gift_holders(self, collection_address: str) -> List[Dict]:
        items_url = f"{self.toncenter_url}getNftItems"
        items_data = await self._request(items_url, {
            "address": collection_address,
            "limit": 1000
        })
        
        if "error" in items_data:
            return []
        
        holders = []
        seen = set()
        
        for item in items_data.get("result", []):
            owner = item.get("owner", {})
            owner_address = owner.get("address", "")
            
            if not owner_address or owner_address in seen:
                continue
            
            account_url = f"{self.toncenter_url}getAddressInformation"
            account_data = await self._request(account_url, {
                "address": owner_address
            })
            
            username = account_data.get("result", {}).get("username", "") if "error" not in account_data else ""
            
            holders.append({
                "address": owner_address,
                "username": username,
                "gift_name": item.get("name", "Unknown"),
                "gift_address": item.get("address", ""),
                "index": item.get("index", 0)
            })
            seen.add(owner_address)
        
        return holders
    
    async def get_gift_info(self, gift_address: str) -> Dict:
        url = f"{self.toncenter_url}getNftInfo"
        data = await self._request(url, {"address": gift_address})
        
        if "error" in data:
            return {}
        
        result = data.get("result", {})
        owner = result.get("owner", {})
        
        return {
            "name": result.get("name", "Unknown"),
            "address": result.get("address", ""),
            "owner_address": owner.get("address", ""),
            "owner_username": owner.get("username", ""),
            "collection": result.get("collection", {}).get("address", ""),
            "metadata": result.get("metadata", {})
        }

parser = TelegramGiftParser()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔍 Найти подарок", callback_data="search_gift")],
        [InlineKeyboardButton(text="📊 Владельцы коллекции", callback_data="holders")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
# КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    await message.answer(
        f"🟢 <b>@{message.from_user.username or 'User'}</b>, привет!\n\n"
        "Этот бот ищет владельцев Telegram NFT-подарков.\n\n"
        "🎁 Команды:\n"
        "/gift (address) - найти владельца подарка\n"
        "/holders (collection) - все владельцы в коллекции\n"
        "/find (name) (collection) - поиск по названию",
        parse_mode="HTML",
        reply_markup=main_menu(is_admin)
    )

@dp.message(Command("gift"))
async def get_gift(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ Использование: /gift (адрес_подарка)\nПример: /gift EQD4...")
        return
    
    gift_address = args.strip()
    await message.answer("🔍 Ищу подарок...")
    
    info = await parser.get_gift_info(gift_address)
    
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
        await message.answer("❌ Использование: /holders (адрес_коллекции)\nПример: /holders EQD4...")
        return
    
    collection = args.strip()
    await message.answer("📡 Загружаю владельцев...")
    
    holders = await parser.get_gift_holders(collection)
    
    if not holders:
        await message.answer("❌ Коллекция не найдена или в ней нет подарков.")
        return
    
    text = f"🎯 <b>Найдено {len(holders)} владельцев</b>\n\n"
    
    for h in holders[:10]:
        username = f"@{h['username']}" if h['username'] else "❌ Нет username"
        text += f"📦 {h['gift_name']}\n"
        text += f"   👤 {username}\n"
        text += f"   📍 <code>{h['address'][:20]}...</code>\n\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("find"))
async def find_gift(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ Использование: /find (название) (адрес_коллекции)")
        return
    
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите название и адрес коллекции.")
        return
    
    name = parts[0]
    collection = parts[1]
    
    await message.answer(f"🔍 Ищу подарки с названием «{name}»...")
    
    holders = await parser.get_gift_holders(collection)
    found = [h for h in holders if name.lower() in h['gift_name'].lower()]
    
    if not found:
        await message.answer(f"❌ Подарки с названием «{name}» не найдены.")
        return
    
    text = f"🎯 <b>Найдено {len(found)} подарков с названием «{name}»</b>\n\n"
    for h in found[:10]:
        username = f"@{h['username']}" if h['username'] else "❌ Нет username"
        text += f"📦 {h['gift_name']} → {username}\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    
    if data == "search_gift":
        await callback.message.answer("🔍 Введите команду:\n/gift (адрес_подарка)")
    
    elif data == "holders":
        await callback.message.answer("📊 Введите команду:\n/holders (адрес_коллекции)")
    
    await callback.answer()

# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    print("🤖 Telegram Gift Parser Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())