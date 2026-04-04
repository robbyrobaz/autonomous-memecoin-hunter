#!/usr/bin/env python3
"""Test Grok's full list of 20 channels"""
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

# All 20 from Grok's list
CHANNELS = [
    # Top 5 recommended
    '@bullishsbangers',
    '@manifestingriches',
    '@batman_gem',
    '@SolanaMemeCoinss',
    '@dextoolspumps',
    
    # Other active channels
    '@cryptoclubpump',
    '@solanamemecoinschannel',
    
    # Our current winner
    '@gmgnsignals',
    
    # Try variants
    '@DEXTOOLSPUMPS',
    '@SolanaMemeCoinsChannel',
    '@solanamemecoins',
    '@memecoinpumps',
    '@solpumps',
    '@degenpump',
    '@cryptowhalepumps',
]

def has_contract(text):
    if not text:
        return False
    return bool(re.search(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text))

async def test():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Not authorized!")
        await client.disconnect()
        return
    
    print("Testing Grok's 20 recommended channels...\n")
    print(f"{'Channel':<35} {'Status':<8} {'Contracts':<10} {'Members':<10} {'Name'}")
    print("="*100)
    
    results = []
    
    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(entity, limit=100)
            
            if not messages:
                print(f"{channel:<35} {'EMPTY':<8} {'0':<10} {'-':<10}")
                continue
            
            # Check activity
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
            
            print(f"{channel:<35} {status:<8} {contracts:<10} {members:<10} {entity.title[:35]}")
        
        except Exception as e:
            error_msg = str(e)[:30]
            print(f"{channel:<35} {'❌':<8} {'ERROR':<10} {'-':<10} {error_msg}")
    
    await client.disconnect()
    
    # Sort by contracts
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*100)
    print("TOP ACTIVE CHANNELS (sorted by contracts/day):\n")
    
    for r in results[:15]:
        if r['contracts'] > 0:
            print(f"  {r['channel']:<35} {r['contracts']:>3} contracts/day - {r['name'][:40]}")
    
    print("\n" + "="*100)
    print("RECOMMENDED CONFIG (channels with 5+ contracts/day):\n")
    print("CHANNELS = [")
    for r in results:
        if r['contracts'] >= 5:
            print(f"    '{r['channel']}',  # {r['contracts']} contracts/day - {r['name'][:35]}")
    print("]")
    
    print("\n" + "="*100)
    print(f"SUMMARY: Found {len([r for r in results if r['contracts'] > 0])} active channels out of {len(CHANNELS)} tested")

asyncio.run(test())
