import requests
from telegram import Bot
import time

BOT_TOKEN = "8226209807:AAEadwBefaPvJtNtGtL2k3t_3Z6Dj1eH-ps"
CHAT_ID = "8563327706","2015797733"

bot = Bot(token=BOT_TOKEN)

def get_nfts():
    url = "https://api.opensea.io/api/v1/assets"
    params = {
        "order_by": "created_date",
        "order_direction": "desc",
        "limit": 5
    }
    headers = {
        "X-API-KEY": "ТВОЙ_OPENSEA_API_KEY"  # если есть
    }

    r = requests.get(url, params=params, headers=headers)
    if r.status_code != 200:
        return []

    return r.json().get("assets", [])

def send_nft(nft):
    name = nft.get("name") or "Без названия"
    link = nft.get("permalink")
    owner = nft.get("owner", {}).get("address", "Неизвестно")
    collection = nft.get("collection", {}).get("name", "NFT")

    text = f"""
📦 Тип: {collection}
🎨 Название: {name}
👤 Владелец: {owner}
🔗 Ссылка: {link}
"""
    bot.send_message(chat_id=CHAT_ID, text=text)

def main():
    seen = set()
    while True:
        nfts = get_nfts()
        for nft in nfts:
            nft_id = nft.get("id")
            if nft_id not in seen:
                seen.add(nft_id)
                send_nft(nft)
        time.sleep(30)

if __name__ == "__main__":
    main()