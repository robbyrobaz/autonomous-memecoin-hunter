#!/usr/bin/env python3
"""Check channels/groups YOU'RE already in"""
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

def has_contract(text):
    if not text:
        return False
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    return bool(re.search(pattern, text))

async def check_my_channels():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.disconnect()
        return
    
    print("Checking YOUR joined channels/groups for Solana contracts...\n")
    print(f"{'Name':<40} {'Username':<25} {'Contracts':<10} {'Last Post'}")
    print("="*95)
    
    results = []
    
    # Get all dialogs (chats you're in)
    async for dialog in client.iter_dialogs(limit=200):
        try:
            # Skip private chats
            if dialog.is_user:
                continue
            
            entity = dialog.entity
            
            # Get recent messages
            messages = await client.get_messages(entity, limit=100)
            
            if not messages:
                continue
            
            # Count contracts in last 24h
            since = datetime.now() - timedelta(hours=24)
            contracts = 0
            
            for msg in messages:
                msg_date = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                if msg_date >= since and has_contract(msg.message):
                    contracts += 1
            
            # Get username
            username = getattr(entity, 'username', '')
            username_str = f"@{username}" if username else "[no username]"
            
            # Get last message time
            latest = messages[0].date.replace(tzinfo=None) if messages[0].date.tzinfo else messages[0].date
            hours_ago = (datetime.now() - latest).total_seconds() / 3600
            
            if contracts > 0 or (hours_ago < 24 and 'sol' in entity.title.lower()):
                results.append({
                    'name': entity.title,
                    'username': username_str,
                    'contracts': contracts,
                    'hours': hours_ago
                })
                
                print(f"{entity.title[:38]:<40} {username_str[:23]:<25} {contracts:<10} {hours_ago:.1f}h ago")
        
        except Exception as e:
            pass
    
    await client.disconnect()
    
    print("\n" + "="*95)
    print("CHANNELS WITH CONTRACTS:\n")
    
    results.sort(key=lambda x: x['contracts'], reverse=True)
    
    for r in results[:20]:
        if r['contracts'] > 0:
            print(f"  {r['username']:<30} {r['contracts']:>3} contracts/day - {r['name']}")
    
    print("\n" + "="*95)
    print("RECOMMENDED CONFIG:\n")
    print("CHANNELS = [")
    for r in results[:10]:
        if r['contracts'] > 0 and r['username'] != "[no username]":
            print(f"    '{r['username']}',  # {r['contracts']} contracts/day")
    print("]")

asyncio.run(check_my_channels())
