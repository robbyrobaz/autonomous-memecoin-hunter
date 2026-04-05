#!/usr/bin/env python3
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

CHANNELS = [
    '@bullishsbangers', '@manifestingriches', '@batman_gem', 
    '@SolanaMemeCoinss', '@dextoolspumps', '@cryptoclubpump',
    '@solanamemecoinschannel', '@gmgnsignals', '@solanamemecoins',
]

def has_contract(text):
    return bool(re.search(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text or ''))

async def test():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    results = []
    for ch in CHANNELS:
        try:
            entity = await client.get_entity(ch)
            msgs = await client.get_messages(entity, limit=100)
            if msgs:
                since = datetime.now() - timedelta(hours=24)
                contracts = sum(1 for m in msgs 
                    if (m.date.replace(tzinfo=None) if m.date.tzinfo else m.date) >= since 
                    and has_contract(m.message))
                if contracts > 0:
                    results.append((ch, contracts, entity.title))
        except Exception as e:
            pass
    
    await client.disconnect()
    
    results.sort(key=lambda x: x[1], reverse=True)
    print("\nACTIVE CHANNELS FOUND:")
    print("="*80)
    for ch, cnt, name in results:
        print(f"{ch:35s} {cnt:3d} contracts/day - {name}")
    print("\n" + "="*80)
    print(f"Found {len(results)} active channels\n")

asyncio.run(test())
