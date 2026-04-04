#!/usr/bin/env python3
"""Quick auth - request code and sign in immediately"""
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

async def quick_auth(code):
    """Request code and sign in immediately"""
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        # Request code
        sent_code = await client.send_code_request(PHONE)
        
        # Sign in immediately with provided code
        try:
            await client.sign_in(PHONE, code, phone_code_hash=sent_code.phone_code_hash)
            print("✅ Authentication successful!")
            print("✅ Session file created: memecoin_hunter.session")
            
            # Test
            me = await client.get_me()
            print(f"✅ Logged in as: {me.first_name} {me.phone}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            await client.disconnect()
            return False
    else:
        print("✅ Already authorized!")
    
    await client.disconnect()
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python quick_auth.py <code>")
        sys.exit(1)
    
    code = sys.argv[1]
    success = asyncio.run(quick_auth(code))
    sys.exit(0 if success else 1)
