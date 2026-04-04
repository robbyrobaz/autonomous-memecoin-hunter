#!/usr/bin/env python3
"""Final search - alpha groups, bots, trending feeds"""
import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv
from pathlib import Path
import re

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# Final attempt - bots, trending feeds, specific alpha groups
CANDIDATES = [
    # Known good
    '@gmgnsignals',
    
    # Trending/tracking bots
    '@soltrending',
    '@soltrendingbot',
    '@solanatrendingbot',
    
    # DEX/Birdeye bots
    '@birdeyesolanabot',
    '@dexscreenerbot',
    
    # Call channels
    '@AlphaSolCalls',
    '@SolanaAlphaCalls',
    '@solcalls',
    '@SolCallsOfficial',
    
    # Community calls
    '@solanacallsgroup',
    '@SolanaCallsChat',
    
    # Specific known groups
    '@photonsolana',
    '@bonfida',
    '@magic_eden',
]

def has_contract(text):
    if not text:
        return False
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    return bool(re.search(pattern, text))

async def test():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        return
    
    print("Final channel search...\n")
    
    good = []
    
    for channel in CANDIDATES:
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(channel, limit=100)
            
            if not messages:
                continue
            
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            since = datetime.now() - timedelta(hours=24)
            contracts = sum(1 for msg in messages 
                          if (msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date) >= since 
                          and has_contract(msg.message))
            
            if contracts > 0 or hours_ago < 12:
                good.append({
                    'channel': channel,
                    'name': entity.title,
                    'hours': hours_ago,
                    'contracts': contracts
                })
                print(f"{channel:<30} {contracts:>3} contracts - {entity.title[:40]}")
        
        except Exception as e:
            pass
    
    await client.disconnect()
    
    print("\n" + "="*80)
    print("FINAL RECOMMENDATION:")
    print("="*80)
    
    good.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\nCHANNELS = [")
    for g in good[:7]:
        if g['contracts'] > 0:
            print(f"    '{g['channel']}',  # {g['contracts']} contracts/day")
    print("]")

asyncio.run(test())
