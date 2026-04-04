#!/usr/bin/env python3
"""Find good Solana memecoin Telegram channels"""
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

# Candidate channels to test
CANDIDATES = [
    # Popular/trending
    '@SolanaTrending',
    '@solanatrends',
    '@SolanaGains',
    '@solanacalls',
    '@SolanaAlpha',
    
    # Pump.fun related
    '@pumpfunalpha',
    '@pumpfuncalls',
    '@pumpdotfuncalls',
    '@pumpfuntrending',
    
    # Degen/Ape groups
    '@solanadegen',
    '@soldegens',
    '@solanadegens',
    '@solapeclub',
    
    # Calls/signals
    '@solsignals',
    '@solanasignals',
    '@SolanaCallsOfficial',
    '@solanacallschannel',
    
    # Communities
    '@SolanaCommunity',
    '@solanaapes',
    '@SolanaHunters',
    
    # Rob's addition
    '@gmgnsignals',
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
    
    print("Testing Solana memecoin channels...\n")
    print(f"{'Channel':<30} {'Status':<15} {'Recent':<8} {'Contracts':<10} {'Activity'}")
    print("="*90)
    
    results = []
    
    for channel in CANDIDATES:
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(channel, limit=50)
            
            # Check activity
            if not messages:
                print(f"{channel:<30} {'EMPTY':<15} {'N/A':<8} {'0':<10} Dead")
                continue
            
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            # Count messages with contracts in last 24h
            since = datetime.now() - timedelta(hours=24)
            contracts_found = 0
            recent_count = 0
            
            for msg in messages:
                msg_date = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                if msg_date >= since:
                    recent_count += 1
                    if has_contract(msg.message):
                        contracts_found += 1
            
            status = "✅ ACTIVE" if hours_ago < 24 else "⚠️  SLOW"
            activity = f"{recent_count} msgs/day"
            
            results.append({
                'channel': channel,
                'name': entity.title,
                'hours_ago': hours_ago,
                'contracts': contracts_found,
                'recent_msgs': recent_count,
                'status': status
            })
            
            print(f"{channel:<30} {status:<15} {hours_ago:<8.1f}h {contracts_found:<10} {activity}")
        
        except Exception as e:
            print(f"{channel:<30} {'❌ ERROR':<15} {'N/A':<8} {'0':<10} {str(e)[:30]}")
    
    await client.disconnect()
    
    # Sort by contracts found
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    print("\n" + "="*90)
    print("TOP RECOMMENDATIONS (by contract posts):\n")
    
    top = [r for r in results if r['contracts'] > 0][:10]
    for r in top:
        print(f"  {r['channel']:<30} {r['contracts']} contracts, {r['recent_msgs']} msgs/day")
    
    print("\nRecommended channel list:")
    print("CHANNELS = [")
    for r in top[:7]:
        print(f"    '{r['channel']}',  # {r['contracts']} contracts/day")
    print("]")

asyncio.run(test_channels())
