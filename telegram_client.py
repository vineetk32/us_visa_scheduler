#!.venv/bin/python
from telegram import Bot

class TelegramClient:
    bot: Bot

    def __init__(self, token: str) -> None:
        self.bot = Bot(token)
    
    async def send_message(self, chat_id: str, message: str):
        async with self.bot:
            await self.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
