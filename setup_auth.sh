#!/bin/bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python3 << 'PYEOF'
import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

async def auth():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"\n✅ Authenticated as: {me.first_name} ({me.phone})")
    await client.disconnect()

asyncio.run(auth())
PYEOF
