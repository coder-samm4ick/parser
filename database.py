import aiosqlite
from datetime import datetime

DB_FILE = "nft_data.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                address TEXT UNIQUE,
                last_parsed TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS nfts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER,
                nft_address TEXT UNIQUE,
                name TEXT,
                owner_address TEXT,
                owner_username TEXT,
                parsed_at TEXT,
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

async def add_collection(name: str, address: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO collections (name, address, last_parsed) VALUES (?, ?, ?)",
            (name, address, datetime.now().isoformat())
        )
        await db.commit()

async def get_collections():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM collections")
        return await cursor.fetchall()

async def save_nft(collection_id: int, nft_address: str, name: str, owner: str, username: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT OR REPLACE INTO nfts (collection_id, nft_address, name, owner_address, owner_username, parsed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (collection_id, nft_address, name, owner, username, datetime.now().isoformat()))
        await db.commit()

async def get_nfts_by_collection(collection_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM nfts WHERE collection_id = ?", (collection_id,))
        return await cursor.fetchall()