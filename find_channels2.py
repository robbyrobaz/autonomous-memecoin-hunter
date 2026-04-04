#!/usr/bin/env python3
"""Search for active Solana/pump.fun channels - second attempt"""
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

# New candidates - trying different names
CANDIDATES = [
    # GMGN (known good)
    '@gmgnsignals',
    '@gmgn_sol',
    '@gmgnalpha',
    
    # Pump.fun specific
    '@pumpfun',
    '@pumpfunofficial',
    '@pumpfunlive',
    '@pumpfunsol',
    
    # Raydium/DEX
    '@raydium',
    '@raydiumofficial',
    
    # Trading groups
    '@solanatrading',
    '@soltrades',
    '@soltraders',
    
    # Specific communities
    '@solanaalerts',
    '@solanamoonshots',
    '@solmoonshot',
    
    # New/hot
    '@solananew',
    '@solhot',
    '@solhype',
    
    # Gem hunters
    '@solgems',
    '@solgemhunter',
    '@solanagem',
    
    # Alpha groups
    '@solalpha',
    '@solgems',
]

def has_contract(text):
    """Check if message has Solana contract address"""
    if not text:
        return False
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    return bool(re.search(pattern, text))

async def test_channels():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Not authorized!")
        await client.disconnect()
        return
    
    print("Testing Solana channels (attempt 2)...\n")
    print(f"{'Channel':<30} {'Name':<35} {'Last Post':<10} {'Contracts':<10}")
    print("="*95)
    
    results = []
    
    for channel in CANDIDATES:
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(channel, limit=100)
            
            if not messages:
                print(f"{channel:<30} {'EMPTY':<35} {'N/A':<10} {'0':<10}")
                continue
            
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            # Count contracts in last 24h
            since = datetime.now() - timedelta(hours=24)
            contracts = 0
            
            for msg in messages:
                msg_date = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                if msg_date >= since and has_contract(msg.message):
                    contracts += 1
            
            results.append({
                'channel': channel,
                'name': entity.title[:33],
                'hours_ago': hours_ago,
                'contracts': contracts
            })
            
            status = "✅" if hours_ago < 24 else "⚠️"
            print(f"{channel:<30} {entity.title[:33]:<35} {status} {hours_ago:<7.1f}h {contracts:<10}")
        
        except Exception as e:
            error = str(e)[:30]
            print(f"{channel:<30} {'ERROR':<35} {'❌':<10} {error}")
    
    await client.disconnect()
    
    # Sort by contracts
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*95)
    print("BEST CHANNELS (sorted by contract posts in last 24h):\n")
    
    for r in results[:15]:
        if r['contracts'] > 0:
            print(f"  {r['channel']:<30} {r['contracts']:>3} contracts/day - {r['name']}")

asyncio.run(test_channels())
