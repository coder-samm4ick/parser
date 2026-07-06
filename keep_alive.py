import os
import sys
import socket

lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

try:
    # Уникальный идентификатор для блокировки
    lock_id = "my-username.my-bot-task"
    lock_socket.bind('\0' + lock_id)
    print("✅ Бот не запущен. Запускаю...")
    
    # Запускаем твоего бота
    os.execv(sys.executable, ['python', 'bot.py'])
    
except socket.error:
    print("⚠️ Бот уже запущен. Выхожу.")
    sys.exit()