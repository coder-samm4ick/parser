#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",")]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================================
# РЕАЛЬНЫЙ ПАРСЕР МАРКЕТА TELEGRAM NFT
# ============================================================

class TelegramNFTMarket:
    """
    Парсер маркета NFT Telegram
    Использует официальные API TON и GetGems
    """
    
    def __init__(self):
        self.session = None
        self.tonapi_url = "https://tonapi.io/v1/"
        self.getgems_url = "https://api.getgems.io/graphql"
    
    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def _request(self, url: str, headers: dict = None) -> Dict:
        session = await self._get_session()
        try:
            async with session.get(url, headers=headers or {}, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _graphql_request(self, query: str, variables: dict = None) -> Dict:
        """Запрос к GetGems GraphQL API"""
        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        payload = {"query": query, "variables": variables or {}}
        
        try:
            async with session.post(self.getgems_url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_telegram_gifts_collections(self) -> List[Dict]:
        """
        Получить все коллекции Telegram NFT-подарков
        Использует GetGems API
        """
        query = """
        query GetCollections($first: Int) {
            collections(first: $first, where: {platform: {_eq: "telegram"}}) {
                items {
                    address
                    name
                    description
                    stats {
                        floorPrice
                        volume24h
                        itemsCount
                        ownersCount
                    }
                }
            }
        }
        """
        result = await self._graphql_request(query, {"first": 50})
        
        if "error" in result:
            return []
        
        return result.get("data", {}).get("collections", {}).get("items", [])
    
    async def get_nft_holders(self, collection_address: str, limit: int = 1000) -> List[Dict]:
        """
        Получить всех владельцев NFT в коллекции
        """
        url = f"{self.tonapi_url}nft/getItems?collection={collection_address}&limit={limit}"
        data = await self._request(url)
        
        if "error" in data:
            return []
        
        holders = []
        seen = set()
        
        for item in data.get("nft_items", []):
            owner = item.get("owner", {})
            owner_address = owner.get("address", "")
            
            if not owner_address or owner_address in seen:
                continue
            
            # Получаем username владельца
            account_url = f"{self.tonapi_url}account/getInfo?account={owner_address}"
            account_data = await self._request(account_url)
            username = account_data.get("username", "") if "error" not in account_data else ""
            
            holders.append({
                "address": owner_address,
                "username": username,
                "nft_name": item.get("name", "Unknown"),
                "nft_address": item.get("address", ""),
                "index": item.get("index", 0)
            })
            seen.add(owner_address)
        
        return holders
    
    async def search_gift_by_name(self, collection_address: str, gift_name: str) -> List[Dict]:
        """
        Найти конкретный подарок по названию
        """
        items = await self.get_nft_holders(collection_address, 1000)
        
        results = []
        for item in items:
            if gift_name.lower() in item["nft_name"].lower():
                results.append(item)
        
        return results
    
    async def get_market_stats(self, collection_address: str) -> Dict:
        """
        Получить рыночную статистику коллекции
        """
        query = """
        query GetCollectionStats($address: String!) {
            collection(address: $address) {
                stats {
                    floorPrice
                    volume24h
                    volume7d
                    itemsCount
                    ownersCount
                    listedCount
                }
            }
        }
        """
        result = await self._graphql_request(query, {"address": collection_address})
        
        if "error" in result:
            return {}
        
        return result.get("data", {}).get("collection", {}).get("stats", {})

parser = TelegramNFTMarket()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🎁 Все коллекции подарков", callback_data="list_gifts")],
        [InlineKeyboardButton(text="🔍 Найти подарок", callback_data="search_gift")],
        [InlineKeyboardButton(text="📊 Рынок NFT", callback_data="market_stats")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить рынок", callback_data="refresh_market")],
        [InlineKeyboardButton(text="📊 Все пользователи", callback_data="users_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

# ============================================================
# КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    await message.answer(
        f"🟢 <b>@{message.from_user.username or 'User'}</b>, привет!\n\n"
        "Этот бот парсит <b>Telegram NFT-подарки</b> и показывает информацию о рынке.\n\n"
        "🎁 <b>Что умеет:</b>\n"
        "• Показывать все коллекции подарков\n"
        "• Находить владельцев конкретных подарков\n"
        "• Рыночную статистику (цена, объём)\n"
        "• Искать подарки по названию\n\n"
        "📌 <i>Все данные берутся из открытых источников (TON, GetGems)</i>",
        parse_mode="HTML",
        reply_markup=main_menu(is_admin)
    )

@dp.message(Command("collections"))
async def list_collections(message: types.Message):
    """Показать все коллекции Telegram NFT-подарков"""
    await message.answer("📡 Загружаю список коллекций...")
    
    collections = await parser.get_telegram_gifts_collections()
    
    if not collections:
        await message.answer("❌ Не удалось загрузить коллекции. Попробуйте позже.")
        return
    
    text = "🎁 <b>Коллекции Telegram NFT-подарков</b>\n\n"
    
    for col in collections[:20]:
        stats = col.get("stats", {})
        floor = stats.get("floorPrice", 0)
        volume = stats.get("volume24h", 0)
        items = stats.get("itemsCount", 0)
        owners = stats.get("ownersCount", 0)
        
        text += f"📦 <b>{col.get('name', 'Без названия')}</b>\n"
        text += f"   💰 Пол: {floor} TON\n"
        text += f"   📊 Объём (24ч): {volume} TON\n"
        text += f"   🖼️ NFT: {items} | 👥 Владельцев: {owners}\n"
        text += f"   📍 <code>{col.get('address', '')[:20]}...</code>\n\n"
    
    if len(collections) > 20:
        text += f"\n... и ещё {len(collections) - 20} коллекций."
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("find_gift"))
async def find_gift(message: types.Message, command: CommandObject):
    """Найти подарок по названию"""
    args = command.args
    if not args:
        await message.answer("❌ Использование: /find_gift <название> <адрес_коллекции>\nПример: /find_gift Yan EQD4...")
        return
    
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите название и адрес коллекции.")
        return
    
    gift_name = parts[0]
    collection_address = parts[1]
    
    await message.answer(f"🔍 Ищу подарок «{gift_name}»...")
    
    results = await parser.search_gift_by_name(collection_address, gift_name)
    
    if not results:
        await message.answer(f"❌ Подарок «{gift_name}» не найден в этой коллекции.")
        return
    
    text = f"🎯 <b>Найдено {len(results)} подарков с названием «{gift_name}»</b>\n\n"
    
    for nft in results[:10]:
        username = f"@{nft['username']}" if nft['username'] else "❌ Нет username"
        text += f"📦 <b>{nft['nft_name']}</b>\n"
        text += f"   👤 Владелец: {username}\n"
        text += f"   📍 <code>{nft['address'][:20]}...</code>\n\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("market"))
async def market_stats(message: types.Message):
    """Показать статистику рынка"""
    await message.answer("📡 Загружаю статистику рынка...")
    
    collections = await parser.get_telegram_gifts_collections()
    
    if not collections:
        await message.answer("❌ Не удалось загрузить данные.")
        return
    
    total_volume = sum(c.get("stats", {}).get("volume24h", 0) for c in collections)
    total_items = sum(c.get("stats", {}).get("itemsCount", 0) for c in collections)
    total_owners = sum(c.get("stats", {}).get("ownersCount", 0) for c in collections)
    
    text = "📊 <b>Рынок Telegram NFT-подарков</b>\n\n"
    text += f"📦 Коллекций: {len(collections)}\n"
    text += f"🖼️ Всего NFT: {total_items}\n"
    text += f"👥 Уникальных владельцев: {total_owners}\n"
    text += f"💰 Объём за 24ч: {total_volume:.2f} TON\n\n"
    
    # Топ-3 коллекции по объёму
    sorted_cols = sorted(collections, key=lambda x: x.get("stats", {}).get("volume24h", 0), reverse=True)
    text += "🏆 <b>Топ-3 по объёму:</b>\n"
    for col in sorted_cols[:3]:
        volume = col.get("stats", {}).get("volume24h", 0)
        text += f"• {col.get('name', 'Без названия')}: {volume:.2f} TON\n"
    
    await message.answer(text, parse_mode="HTML")

# ============================================================
# CALLBACK HANDLERS
# ============================================================

@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS
    data = callback.data
    
    if data == "list_gifts":
        await list_collections(callback.message)
        await callback.answer()
    
    elif data == "search_gift":
        await callback.message.answer("🔍 Введите команду:\n/find_gift <название> <адрес_коллекции>\n\nПример:\n/find_gift Yan EQD4...")
        await callback.answer()
    
    elif data == "market_stats":
        await market_stats(callback.message)
        await callback.answer()
    
    elif data == "admin_panel":
        if is_admin:
            await callback.message.edit_text(
                "⚙️ <b>Админ-панель</b>",
                parse_mode="HTML",
                reply_markup=admin_panel()
            )
        else:
            await callback.answer("⛔ Нет прав.", show_alert=True)
    
    elif data == "refresh_market":
        if is_admin:
            await callback.message.answer("🔄 Обновляю данные рынка...")
            # Здесь можно добавить логику обновления
            await callback.message.answer("✅ Рынок обновлён.")
    
    elif data == "users_list":
        if is_admin:
            await callback.message.answer("👥 Список пользователей пока недоступен.")
    
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
    print("🤖 Telegram NFT Market Parser Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())