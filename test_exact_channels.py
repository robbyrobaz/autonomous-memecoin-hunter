#!/usr/bin/env python3
"""Test exact channels from Rob's list"""
import asyncio, os, re
from datetime import datetime, timedelta
from telethon import TelegramClient
from pathlib import Path

# Load env manually
env_file = Path.home() / '.openclaw/workspace/autonomous-memecoin-hunter/.env'
for line in env_file.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, val = line.split('=', 1)
        os.environ[key.strip()] = val.strip()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# Rob's exact list
CHANNELS = [
    'bullishsbangers',        # Quality-focused
    'manifestingriches',      # Early low-cap alpha
    'DEXTOOLSPUMPS',          # Early Solana pumps
    'dextoolspumps',          # variant
    'cryptoclubpump',         # Insider-style pumps
    'SolanaMemeCoinss',       # Caller lounge
    'XAceCalls',              # Active calls on X
    'gmgnsignals',            # Our current winner
    'batman_gem',             # Our current winner
]

def has_contract(text):
    return bool(re.search(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text or ''))

async def test():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    print("\nTesting exact channels from Rob's list...")
    print("="*90)
    print(f"{'Channel':<25} {'Status':<10} {'Contracts':<12} {'Last Post':<12} {'Name'}")
    print("="*90)
    
    results = []
    
    for ch in CHANNELS:
        try:
            # Try both with and without @
            try:
                entity = await client.get_entity(f'@{ch}')
            except:
                entity = await client.get_entity(ch)
            
            msgs = await client.get_messages(entity, limit=100)
            
            if not msgs:
                print(f"{ch:<25} {'EMPTY':<10} {'0':<12} {'-':<12}")
                continue
            
            # Get last post time
            latest = msgs[0].date.replace(tzinfo=None) if msgs[0].date.tzinfo else msgs[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            # Count contracts in last 24h
            since = datetime.now() - timedelta(hours=24)
            contracts = sum(1 for m in msgs 
                if (m.date.replace(tzinfo=None) if m.date.tzinfo else m.date) >= since 
                and has_contract(m.message))
            
            status = "✅ ACTIVE" if hours_ago < 24 else "⚠️  SLOW"
            last_post = f"{hours_ago:.1f}h ago" if hours_ago < 48 else f"{int(hours_ago/24)}d ago"
            
            results.append({
                'channel': ch,
                'name': entity.title,
                'contracts': contracts,
                'hours': hours_ago
            })
            
            print(f"{ch:<25} {status:<10} {contracts:<12} {last_post:<12} {entity.title[:30]}")
            
        except Exception as e:
            error_msg = str(e)[:40]
            print(f"{ch:<25} {'❌ ERROR':<10} {'-':<12} {'-':<12} {error_msg}")
    
    await client.disconnect()
    
    # Sort by contracts
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*90)
    print("ACTIVE CHANNELS (sorted by contracts/day):\n")
    
    active = [r for r in results if r['contracts'] > 0]
    for r in active:
        print(f"  @{r['channel']:<30} {r['contracts']:>3} contracts/day - {r['name']}")
    
    print("\n" + "="*90)
    print("RECOMMENDED SCANNER CONFIG:\n")
    print("CHANNELS = [")
    for r in active:
        print(f"    '@{r['channel']}',  # {r['contracts']} contracts/day")
    print("]")
    
    print("\n" + "="*90)
    print(f"TOTAL: {len(active)} active channels found (out of {len(CHANNELS)} tested)\n")

asyncio.run(test())
