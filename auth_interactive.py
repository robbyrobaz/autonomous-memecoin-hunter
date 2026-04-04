#!/usr/bin/env python3
"""Interactive Telegram authentication"""
import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv
from pathlib import Path

# Load .env from explicit path
env_path = Path.home() / '.openclaw/workspace/autonomous-memecoin-hunter/.env'
load_dotenv(env_path)

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

print("="*50)
print("Telegram Authentication")
print("="*50)
print(f"\nUsing phone: {PHONE}")
print(f"API ID: {API_ID}\n")
print("You will receive an SMS code...")
print("Enter it when prompted below.\n")

async def auth():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"\n{'='*50}")
    print(f"✅✅✅ SUCCESS!")
    print(f"✅ Authenticated as: {me.first_name} ({me.phone})")
    print(f"✅ Session file created: memecoin_hunter.session")
    print(f"✅ Cron job will now work automatically")
    print(f"{'='*50}\n")
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(auth())
