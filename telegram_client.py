#!.venv/bin/python
from telegram import Bot
import asyncio

class TelegramClient:
    bot: Bot

    def __init__(self, token: str) -> None:
        self.bot = Bot(token)
    
    def send_message(self, chat_id: str, message: str):
        asyncio.run(self.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown'))
