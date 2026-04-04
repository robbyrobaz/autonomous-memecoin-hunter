#!/bin/bash
# Run this script YOURSELF in your terminal
# It will prompt for the Telegram code interactively

cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate

echo "========================================"
echo "Telegram Authentication"
echo "========================================"
echo ""
echo "You will receive an SMS code."
echo "Enter it when prompted."
echo ""

python3 << 'EOF'
import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv
from pathlib import Path

# Load .env from explicit path
env_path = Path.home() / '.openclaw/workspace/autonomous-memecoin-hunter/.env'
load_dotenv(env_path)

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

print(f"Using phone: {PHONE}")
print(f"API ID: {API_ID}")
print("")

async def auth():
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"\n✅✅✅ SUCCESS! Authenticated as: {me.first_name}")
    print(f"✅ Session file created")
    print(f"✅ Cron job will now work automatically\n")
    await client.disconnect()

asyncio.run(auth())
EOF

echo ""
echo "Done! The scanner will now run every 5 minutes automatically."
