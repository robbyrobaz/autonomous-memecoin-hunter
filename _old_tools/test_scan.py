#!/usr/bin/env python3
"""Test script to see what's happening in scanner"""
import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

CHANNELS = [
    '@alphacalls',
    '@solanamemecoins',
    '@solana_calls',
    '@SolanaGems',
    '@degencalls',
    '@soltrending',
    '@SolanaWhales',
    '@pumpdotfun',
    '@SolShitcoins',
]

async def test():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Not authorized!")
        await client.disconnect()
        return
    
    print(f"✅ Connected to Telegram\n")
    
    since = datetime.now() - timedelta(hours=24)
    print(f"Looking for messages since: {since}\n")
    
    for channel in CHANNELS:
        try:
            print(f"Trying {channel}...")
            entity = await client.get_entity(channel)
            print(f"  ✅ Found: {entity.title}")
            
            messages = await client.get_messages(channel, limit=5)
            print(f"  ✅ Fetched {len(messages)} messages")
            
            for msg in messages:
                if msg.message:
                    print(f"    - {msg.date}: {msg.message[:50]}...")
        
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        print()
    
    await client.disconnect()

asyncio.run(test())
