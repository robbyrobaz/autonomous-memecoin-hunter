#!/usr/bin/env python3
"""
Autonomous Memecoin Hunter - Main Scanner
Scans Telegram channels for memecoin signals, validates safety, paper trades
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

import requests
from telethon import TelegramClient
from dotenv import load_dotenv

# Load environment
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

# Telegram API credentials
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

# Channels to monitor
# Tested Apr 4 2026 - Only 2 active channels found out of 40+ tested
CHANNELS = [
    '@gmgnsignals',          # 100 contracts/day - GMGN Featured Signals
    '@batman_gem',           # 25 contracts/day - Batman's Gems (high volume, hit-or-miss)
]

# Hype keywords
HYPE_KEYWORDS = ['🚀', 'moon', '100x', 'gem', 'ape', 'send it', 'new launch', 
                 'just launched', 'x100', 'moonshot', 'fair launch']

# Log files
SIGNALS_LOG = BASE_DIR / 'logs' / 'signals.jsonl'
TRADES_LOG = BASE_DIR / 'logs' / 'paper_trades.jsonl'
REJECTIONS_LOG = BASE_DIR / 'logs' / 'rejections.jsonl'
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'

# Paper trading state
PAPER_BALANCE = 10000.0
POSITION_SIZE_PCT = 0.10  # 10% per trade (was 5%) - more aggressive
MAX_POSITIONS = 5  # 5 concurrent (was 3)


def extract_contract_address(text: str) -> Optional[str]:
    """Extract Solana contract address from message"""
    # Solana addresses are 32-44 chars, base58
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    matches = re.findall(pattern, text)
    
    for match in matches:
        # Filter out common false positives
        if match.lower() in ['sol', 'usdc', 'usdt']:
            continue
        return match
    return None


def calculate_hype_score(message: str) -> int:
    """Calculate hype score based on keywords"""
    text_lower = message.lower()
    score = 0
    
    for keyword in HYPE_KEYWORDS:
        if keyword.lower() in text_lower:
            score += 2
    
    # Bonus for multiple rockets
    rocket_count = message.count('🚀')
    score += min(rocket_count, 5)
    
    return score


def check_rugcheck(contract: str) -> tuple[bool, str, Dict]:
    """Check contract safety via rugcheck.xyz"""
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{contract}/report"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return False, f"API error: {resp.status_code}", {}
        
        data = resp.json()
        score = data.get('score', 0)
        risks = data.get('risks', [])
        
        # AGGRESSIVE: Accept score >= 20 (was 60) - we want risky early plays
        if score < 20:
            return False, f"Rug score too low: {score}", data
        
        return True, f"PASS (score: {score})", data
    except Exception as e:
        return False, f"Rugcheck error: {e}", {}


def check_birdeye(contract: str) -> tuple[bool, str, Dict]:
    """Check liquidity and holders via Birdeye"""
    try:
        # Note: Birdeye requires API key for v3
        # Using public endpoints where available
        url = f"https://public-api.birdeye.so/public/token_overview?address={contract}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            # Birdeye API not working - skip check (we have Rugcheck + Dexscreener)
            return True, f"Birdeye unavailable (HTTP {resp.status_code}), skipping", {}
        
        data = resp.json().get('data', {})
        
        liquidity = data.get('liquidity', 0)
        if liquidity < 20000:
            return False, f"Low liquidity: ${liquidity:,.0f}", data
        
        # Check holder distribution if available
        holder_pct = data.get('top_holder_percent', 0)
        if holder_pct > 30:
            return False, f"Whale concentrated: {holder_pct}%", data
        
        return True, "PASS", data
    except Exception as e:
        # Birdeye might be blocked/rate-limited - don't hard fail
        return True, f"Birdeye unavailable (skipped): {e}", {}


def check_dexscreener(contract: str) -> tuple[bool, str, Dict]:
    """Check price, volume, age via Dexscreener - MINIMAL filters for early entry"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return False, f"API error: {resp.status_code}", {}
        
        data = resp.json()
        pairs = data.get('pairs', [])
        
        if not pairs:
            return False, "No trading pairs found", {}
        
        # Use highest liquidity pair
        pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
        
        liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
        volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
        created_at = pair.get('pairCreatedAt')
        
        # SUPER RELAXED: Just need ANY liquidity (was $5k)
        if liquidity < 500:
            return False, f"No liquidity: ${liquidity:,.0f}", pair
        
        # REMOVED volume check - early coins have low volume
        
        # REMOVED age check - we WANT brand new coins
        
        return True, f"PASS (liq: ${liquidity:,.0f})", pair
    except Exception as e:
        return False, f"Dexscreener error: {e}", {}


def get_current_price(contract: str) -> Optional[float]:
    """Get current price from Dexscreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            pairs = resp.json().get('pairs', [])
            if pairs:
                pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
                return float(pair.get('priceUsd', 0) or 0)
    except:
        pass
    return None


def load_positions() -> List[Dict]:
    """Load open positions"""
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


def save_positions(positions: List[Dict]):
    """Save positions to disk"""
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(positions, f, indent=2)


def open_position(contract: str, entry_price: float, signal_data: Dict):
    """Open a paper trading position"""
    positions = load_positions()
    
    # Check position limits
    open_count = len([p for p in positions if p['status'] == 'OPEN'])
    if open_count >= MAX_POSITIONS:
        log_rejection(contract, "Max positions reached", signal_data)
        return
    
    # Calculate position size
    with open(BASE_DIR / 'data' / 'balance.txt') as f:
        balance = float(f.read().strip())
    
    size = balance * POSITION_SIZE_PCT
    
    position = {
        'contract': contract,
        'entry_price': entry_price,
        'entry_time': datetime.now().isoformat(),
        'size_usd': size,
        'target_price': entry_price * 1.5,  # 50% profit (was 100%) - quicker exits
        'stop_loss': entry_price * 0.5,  # -50% stop (was -30%) - riskier
        'status': 'OPEN',
        'signal_data': signal_data
    }
    
    positions.append(position)
    save_positions(positions)
    
    # Update balance
    with open(BASE_DIR / 'data' / 'balance.txt', 'w') as f:
        f.write(str(balance - size))
    
    # Log trade
    log_trade(position, 'OPEN')
    print(f"✅ OPENED position: {contract[:8]}... at ${entry_price:.8f} (size: ${size:.2f})")


def check_exits():
    """Check all open positions for exit conditions"""
    positions = load_positions()
    
    for pos in positions:
        if pos['status'] != 'OPEN':
            continue
        
        current_price = get_current_price(pos['contract'])
        if not current_price:
            continue
        
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        
        # Check exit conditions
        pnl_pct = (current_price / pos['entry_price'] - 1) * 100
        
        if current_price >= pos['target_price']:
            close_position(pos, current_price, 'TARGET_HIT', pnl_pct)
        elif current_price <= pos['stop_loss']:
            close_position(pos, current_price, 'STOP_LOSS', pnl_pct)
        elif hours_held >= 2:  # 2 hours (was 6) - exit faster
            close_position(pos, current_price, 'TIME_LIMIT', pnl_pct)


def close_position(pos: Dict, exit_price: float, reason: str, pnl_pct: float):
    """Close a position"""
    pos['exit_price'] = exit_price
    pos['exit_time'] = datetime.now().isoformat()
    pos['exit_reason'] = reason
    pos['pnl_pct'] = pnl_pct
    pos['pnl_usd'] = pos['size_usd'] * (pnl_pct / 100)
    pos['status'] = 'CLOSED'
    
    # Update balance
    with open(BASE_DIR / 'data' / 'balance.txt') as f:
        balance = float(f.read().strip())
    
    new_balance = balance + pos['size_usd'] + pos['pnl_usd']
    with open(BASE_DIR / 'data' / 'balance.txt', 'w') as f:
        f.write(str(new_balance))
    
    # Save positions
    positions = load_positions()
    for p in positions:
        if p['contract'] == pos['contract'] and p['entry_time'] == pos['entry_time']:
            p.update(pos)
    save_positions(positions)
    
    # Log
    log_trade(pos, 'CLOSE')
    emoji = '🎯' if pnl_pct > 0 else '❌'
    print(f"{emoji} CLOSED {pos['contract'][:8]}... {reason}: {pnl_pct:+.1f}% (${pos['pnl_usd']:+.2f})")


def log_signal(contract: str, score: int, channel: str, message: str):
    """Log detected signal"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'contract': contract,
        'score': score,
        'channel': channel,
        'message_snippet': message[:200]
    }
    
    with open(SIGNALS_LOG, 'a') as f:
        f.write(json.dumps(data) + '\n')


def log_rejection(contract: str, reason: str, signal_data: Dict):
    """Log rejected signal"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'contract': contract,
        'reason': reason,
        'signal_data': signal_data
    }
    
    with open(REJECTIONS_LOG, 'a') as f:
        f.write(json.dumps(data) + '\n')


def log_trade(position: Dict, action: str):
    """Log trade action"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        **position
    }
    
    with open(TRADES_LOG, 'a') as f:
        f.write(json.dumps(data) + '\n')


async def scan_telegram_channels():
    """Scan Telegram channels for signals"""
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    
    # For cron/non-interactive mode, expect session to already exist
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Not authorized! Run manual auth first:")
        print("   cd ~/.openclaw/workspace/autonomous-memecoin-hunter")
        print("   source venv/bin/activate") 
        print("   python -c 'from scanner import *; import asyncio; client = TelegramClient(\"memecoin_hunter\", API_ID, API_HASH); asyncio.run(client.start(phone=PHONE))'")
        await client.disconnect()
        return []
    
    print(f"📡 Scanning {len(CHANNELS)} Telegram channels...")
    
    # Get messages from last 24 hours (catch signals posted throughout the day)
    since = datetime.now() - timedelta(hours=24)
    signals = []
    
    for channel in CHANNELS:
        try:
            messages = await client.get_messages(channel, limit=50)
            
            for msg in messages:
                # Check if message is recent (handle timezone-aware datetime)
                msg_date = msg.date.replace(tzinfo=None) if msg.date.tzinfo else msg.date
                if msg_date < since:
                    continue
                
                text = msg.message or ''
                
                # Extract contract
                contract = extract_contract_address(text)
                if not contract:
                    continue
                
                # Calculate hype score
                score = calculate_hype_score(text)
                
                if score >= 2:  # Lower threshold to catch more signals
                    signals.append({
                        'contract': contract,
                        'score': score,
                        'channel': channel,
                        'message': text
                    })
                    log_signal(contract, score, channel, text)
                    print(f"🔥 Signal: {contract[:8]}... (score: {score}) from {channel}")
        
        except Exception as e:
            print(f"⚠️  Error scanning {channel}: {e}")
    
    await client.disconnect()
    
    return signals


async def main():
    """Main scanner loop"""
    print(f"\n{'='*60}")
    print(f"🤖 Autonomous Memecoin Hunter - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Initialize balance file if needed
    balance_file = BASE_DIR / 'data' / 'balance.txt'
    if not balance_file.exists():
        balance_file.parent.mkdir(parents=True, exist_ok=True)
        balance_file.write_text(str(PAPER_BALANCE))
        print(f"💰 Initialized paper balance: ${PAPER_BALANCE:,.2f}\n")
    
    # Create log dirs
    (BASE_DIR / 'logs').mkdir(exist_ok=True)
    (BASE_DIR / 'data').mkdir(exist_ok=True)
    
    # Check exits first
    print("🔍 Checking open positions for exits...")
    check_exits()
    
    # Scan for new signals
    signals = await scan_telegram_channels()
    
    print(f"\n📊 Found {len(signals)} signals\n")
    
    # Process signals
    for signal in signals:
        contract = signal['contract']
        
        print(f"\n🔬 Analyzing {contract[:8]}...")
        
        # Safety checks
        rug_pass, rug_msg, rug_data = check_rugcheck(contract)
        if not rug_pass:
            print(f"  ❌ Rugcheck: {rug_msg}")
            log_rejection(contract, f"Rugcheck: {rug_msg}", signal)
            continue
        print(f"  ✅ Rugcheck: {rug_msg}")
        
        bird_pass, bird_msg, bird_data = check_birdeye(contract)
        if not bird_pass:
            print(f"  ❌ Birdeye: {bird_msg}")
            log_rejection(contract, f"Birdeye: {bird_msg}", signal)
            continue
        print(f"  ✅ Birdeye: {bird_msg}")
        
        dex_pass, dex_msg, dex_data = check_dexscreener(contract)
        if not dex_pass:
            print(f"  ❌ Dexscreener: {dex_msg}")
            log_rejection(contract, f"Dexscreener: {dex_msg}", signal)
            continue
        print(f"  ✅ Dexscreener: {dex_msg}")
        
        # Get entry price
        price = get_current_price(contract)
        if not price:
            print(f"  ❌ Could not fetch price")
            log_rejection(contract, "Price unavailable", signal)
            continue
        
        # Open position
        open_position(contract, price, signal)
    
    # Summary
    with open(balance_file) as f:
        balance = float(f.read().strip())
    
    positions = load_positions()
    open_count = len([p for p in positions if p['status'] == 'OPEN'])
    closed_count = len([p for p in positions if p['status'] == 'CLOSED'])
    
    total_pnl = sum(p.get('pnl_usd', 0) for p in positions if p['status'] == 'CLOSED')
    
    print(f"\n{'='*60}")
    print(f"📈 Summary:")
    print(f"   Balance: ${balance:,.2f}")
    print(f"   Open: {open_count} | Closed: {closed_count}")
    print(f"   Total P&L: ${total_pnl:+,.2f}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    asyncio.run(main())
