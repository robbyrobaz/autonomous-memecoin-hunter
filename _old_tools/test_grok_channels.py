#!/usr/bin/env python3
"""Test Grok's recommended channels"""
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

# Grok's recommendations
GROK_CHANNELS = [
    '@bullishsbangers',      # Quality-over-quantity calls
    '@manifestingriches',    # Rachel Wolchin - low-cap micros
    '@batman_gem',           # High-volume calls
    '@DEXTOOLSPUMPS',        # DEX tracking
    '@solanamemecoinss',     # Caller focus
    '@gmgnsignals',          # Our current winner
    
    # Variants to try
    '@dextoolspumps',
    '@DexToolsPumps',
    '@memecoinwhalepumps',
    '@farmercistjournal',
    '@FarmercistJournal',
    '@solpumpcalls',
    '@solanapumps',
    '@pumpfunsignals',
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
    
    print("Testing Grok's recommended channels...\n")
    print(f"{'Channel':<30} {'Active':<8} {'Contracts':<10} {'Members':<10} {'Name'}")
    print("="*100)
    
    results = []
    
    for channel in GROK_CHANNELS:
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(entity, limit=100)
            
            if not messages:
                print(f"{channel:<30} {'EMPTY':<8} {'0':<10} {'-':<10}")
                continue
            
            # Check last post
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            # Count contracts in last 24h
            since = datetime.now() - timedelta(hours=24)
            contracts = sum(1 for msg in messages 
                          if (msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date) >= since 
                          and has_contract(msg.message))
            
            members = getattr(entity, 'participants_count', 0)
            
            status = "✅" if hours_ago < 24 else "⚠️"
            
            results.append({
                'channel': channel,
                'name': entity.title,
                'hours': hours_ago,
                'contracts': contracts,
                'members': members
            })
            
            print(f"{channel:<30} {status:<8} {contracts:<10} {members:<10} {entity.title[:40]}")
        
        except Exception as e:
            error = str(e)[:30]
            print(f"{channel:<30} {'❌':<8} {'ERROR':<10} {'-':<10} {error}")
    
    await client.disconnect()
    
    # Sort by contracts
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*100)
    print("TOP CHANNELS BY CONTRACT POSTS:\n")
    
    for r in results[:15]:
        if r['contracts'] > 0:
            print(f"  {r['channel']:<30} {r['contracts']:>3} contracts/day - {r['name']}")
    
    print("\n" + "="*100)
    print("RECOMMENDED CONFIG:\n")
    print("CHANNELS = [")
    for r in results[:10]:
        if r['contracts'] > 5:  # At least 5 contracts/day
            print(f"    '{r['channel']}',  # {r['contracts']} contracts/day")
    print("]")

asyncio.run(test())
