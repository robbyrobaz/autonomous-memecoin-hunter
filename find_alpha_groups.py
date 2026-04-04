#!/usr/bin/env python3
"""Find REAL alpha - groups, bots, everything"""
import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User
from dotenv import load_dotenv
from pathlib import Path
import re

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# EVERYTHING - channels, groups, bots
SEARCH_TARGETS = [
    # GMGN variants
    '@gmgnsignals',
    '@gmgn',
    '@gmgnbot',
    
    # Pump.fun bots/feeds
    '@pumpfunbot',
    '@pumpportalbot',
    '@pepeboost',
    
    # DEX screener bots
    '@dexscreener_bot',
    '@DexScreenerBot',
    '@dextools_bot',
    
    # Photon bot
    '@photon_sol_bot',
    '@photonbot',
    
    # Trending bots
    '@soltrending',
    '@soltrendingbot',
    '@dextrendingbot',
    
    # Birdeye
    '@birdeye_bot',
    '@birdeyebot',
    
    # Community groups (not channels)
    '@solanamemes',
    '@solanadev',
    '@solanadefi',
    
    # Ape/degen groups
    '@apesolana',
    '@solanadegens',
    '@solapes',
    
    # Known call groups
    '@SolanaCallsGroup',
    '@solanacallsgroup',
    
    # Alpha leak groups
    '@solalerts',
    '@solanalpha',
    '@solanainsider',
    
    # Whale watchers
    '@solwhales',
    '@solanawhale',
    '@whalealert',
]

def has_contract(text):
    if not text:
        return False
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    return bool(re.search(pattern, text))

async def search_all():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        return
    
    print("Searching ALL Telegram sources...\n")
    print(f"{'Source':<35} {'Type':<10} {'Last':<8} {'Contracts':<10} {'Members'}")
    print("="*85)
    
    results = []
    
    for target in SEARCH_TARGETS:
        try:
            entity = await client.get_entity(target)
            messages = await client.get_messages(entity, limit=100)
            
            if not messages:
                continue
            
            # Determine type
            entity_type = "Bot" if isinstance(entity, User) else \
                         "Group" if isinstance(entity, Chat) else \
                         "Channel"
            
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            # Count contracts
            since = datetime.now() - timedelta(hours=24)
            contracts = sum(1 for msg in messages 
                          if (msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date) >= since 
                          and has_contract(msg.message))
            
            # Get member count if available
            members = getattr(entity, 'participants_count', 0)
            
            if hours_ago < 72 or contracts > 0:  # Active in last 3 days OR has contracts
                results.append({
                    'target': target,
                    'type': entity_type,
                    'name': getattr(entity, 'title', getattr(entity, 'username', 'Unknown')),
                    'hours': hours_ago,
                    'contracts': contracts,
                    'members': members
                })
                
                print(f"{target:<35} {entity_type:<10} {hours_ago:>6.1f}h {contracts:>8}   {members:>8}")
        
        except Exception as e:
            pass
    
    await client.disconnect()
    
    # Sort by contracts
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*85)
    print("TOP SOURCES BY CONTRACT POSTS:\n")
    
    for r in results[:15]:
        if r['contracts'] > 0:
            print(f"  {r['target']:<35} {r['contracts']:>3} contracts/day ({r['type']})")
    
    print("\n" + "="*85)
    print("RECOMMENDED CONFIG:\n")
    print("CHANNELS = [")
    for r in results[:10]:
        if r['contracts'] > 0:
            print(f"    '{r['target']}',  # {r['contracts']} contracts/day - {r['type']}")
    print("]")

asyncio.run(search_all())
