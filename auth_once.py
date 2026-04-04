#!/usr/bin/env python3
"""
One-time authentication script
Accepts verification code as argument
"""
import asyncio
import os
import sys
from pathlib import Path
from telethon import TelegramClient
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

async def auth_with_code(code):
    """Authenticate with provided code"""
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.send_code_request(PHONE)
        await client.sign_in(PHONE, code)
    
    print("✅ Authentication successful!")
    print("✅ Session file created: memecoin_hunter.session")
    
    # Test: get dialogs to verify it works
    dialogs = await client.get_dialogs(limit=5)
    print(f"✅ Connected! Can see {len(dialogs)} chats")
    
    await client.disconnect()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python auth_once.py <code>")
        sys.exit(1)
    
    code = sys.argv[1]
    asyncio.run(auth_with_code(code))
