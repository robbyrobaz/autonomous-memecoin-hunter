#!/usr/bin/env python3
"""Request new SMS code"""
import asyncio
import os
from pathlib import Path
from telethon import TelegramClient
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

async def request_code():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.send_code_request(PHONE)
        print(f"✅ SMS code sent to {PHONE}")
        print("Check your phone and give me the code!")
    else:
        print("✅ Already authorized!")
    
    await client.disconnect()

asyncio.run(request_code())
