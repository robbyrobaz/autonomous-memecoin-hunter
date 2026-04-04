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
# Tested Apr 4 2026 - 3 active channels found out of 50+ tested
CHANNELS = [
    '@gmgnsignals',          # 100 contracts/day - GMGN Featured Signals (Solana)
    '@XAceCalls',            # 84 contracts/day - XAce Calls Multichain (NEW!)
    '@batman_gem',           # 25 contracts/day - Batman's Gems (high volume)
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
PAPER_BALANCE = 100.0  # $100 total (realistic small account)
POSITION_SIZE = 1.0  # $1 per trade (MORE TRADES, more data!)
MAX_POSITIONS = 20  # 20 concurrent (collect more data)


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
        
        # SUPER AGGRESSIVE: Accept score >= 10 (was 20) - MORE DATA!
        if score < 10:
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
        
        # ULTRA AGGRESSIVE: Accept $100+ liquidity (was $500)
        if liquidity < 100:
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


def open_position(contract: str, entry_price: float, signal_data: Dict, market_data: Dict = None):
    """Open a paper trading position with FULL DATA COLLECTION"""
    positions = load_positions()
    
    # Check position limits
    open_count = len([p for p in positions if p['status'] == 'OPEN'])
    if open_count >= MAX_POSITIONS:
        print(f"⚠️  Max positions ({MAX_POSITIONS}) reached, skipping")
        return
    
    # Get balance
    with open(BASE_DIR / 'data' / 'balance.txt') as f:
        balance = float(f.read().strip())
    
    # Fixed position size
    size = POSITION_SIZE  # $1 fixed
    
    position = {
        'contract': contract,
        'entry_price': entry_price,
        'entry_time': datetime.now().isoformat(),
        'size_usd': size,
        'initial_stop': entry_price * 0.70,  # -30% initial stop (tight on rugs)
        'trailing_stop': None,  # Activated once profitable
        'peak_price': entry_price,  # Track highest price for trailing
        'peak_time': None,  # When did we hit peak?
        'status': 'OPEN',
        'signal_data': signal_data,
        # ENHANCED DATA COLLECTION FOR ANALYSIS
        'market_data': market_data or {},  # Store liquidity, volume, rugcheck score
        'entry_metrics': {
            'liquidity': market_data.get('liquidity', 0) if market_data else 0,
            'volume_24h': market_data.get('volume_24h', 0) if market_data else 0,
            'rugcheck_score': signal_data.get('rugcheck_score', 0),
            'holder_count': market_data.get('holders', 0) if market_data else 0,
            'age_hours': market_data.get('age_hours', 0) if market_data else 0,
        }
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
    """Check all open positions for exit conditions with TRAILING STOPS"""
    positions = load_positions()
    
    for pos in positions:
        if pos['status'] != 'OPEN':
            continue
        
        current_price = get_current_price(pos['contract'])
        if not current_price:
            continue
        
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        entry_price = pos['entry_price']
        
        # Update peak price and track WHEN we hit peak
        peak_price = pos.get('peak_price', entry_price)
        if current_price > peak_price:
            peak_price = current_price
            pos['peak_price'] = peak_price
            pos['peak_time'] = datetime.now().isoformat()  # Track when we peaked
        
        # Calculate P&L
        pnl_pct = (current_price / entry_price - 1) * 100
        
        # TRAILING STOP LOGIC
        # Once profitable, use trailing stop (30% below peak)
        if current_price > entry_price:
            trailing_stop = peak_price * 0.70  # 30% below peak
            pos['trailing_stop'] = trailing_stop
            
            if current_price <= trailing_stop:
                # Hit trailing stop - lock in profits
                close_position(pos, current_price, 'TRAILING_STOP', pnl_pct)
                continue
        
        # INITIAL STOP LOSS (before profitable)
        # -30% hard stop on rugs
        initial_stop = pos.get('initial_stop', entry_price * 0.70)
        if current_price <= initial_stop:
            close_position(pos, current_price, 'STOP_LOSS', pnl_pct)
            continue
        
        # TIME LIMIT (safety exit after 4 hours)
        if hours_held >= 4:
            close_position(pos, current_price, 'TIME_LIMIT', pnl_pct)
            continue
        
        # Save updated position (peak price, trailing stop)
        save_positions(positions)

def close_position(pos: Dict, exit_price: float, reason: str, pnl_pct: float):
    """Close position and calculate P&L with ANALYTICS DATA"""
    pos['status'] = 'CLOSED'
    pos['exit_price'] = exit_price
    pos['exit_time'] = datetime.now().isoformat()
    pos['exit_reason'] = reason
    pos['pnl_pct'] = pnl_pct
    pos['pnl_usd'] = pos['size_usd'] * (pnl_pct / 100)
    
    # ANALYTICS: How good was this trade?
    entry_time = datetime.fromisoformat(pos['entry_time'])
    exit_time = datetime.fromisoformat(pos['exit_time'])
    peak_price = pos.get('peak_price', pos['entry_price'])
    
    pos['analytics'] = {
        'time_in_position_minutes': (exit_time - entry_time).total_seconds() / 60,
        'peak_gain_pct': ((peak_price / pos['entry_price']) - 1) * 100,
        'exit_from_peak_pct': ((exit_price / peak_price) - 1) * 100,  # How much we gave back
        'trailing_stop_worked': reason == 'TRAILING_STOP',
        'hit_stop_loss': reason == 'STOP_LOSS',
        'time_to_peak_minutes': None,  # Calculate if we have peak_time
    }
    
    # Calculate time to peak if we tracked it
    if pos.get('peak_time'):
        peak_time = datetime.fromisoformat(pos['peak_time'])
        pos['analytics']['time_to_peak_minutes'] = (peak_time - entry_time).total_seconds() / 60
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
        
        # Collect market data for ANALYSIS
        market_data = {
            'liquidity': float(dex_data.get('liquidity', {}).get('usd', 0) or 0),
            'volume_24h': float(dex_data.get('volume', {}).get('h24', 0) or 0),
            'holders': rug_data.get('topHolders', {}).get('count', 0) if rug_pass else 0,
            'age_hours': (datetime.now() - datetime.fromtimestamp(dex_data.get('pairCreatedAt', 0) / 1000)).total_seconds() / 3600 if dex_data.get('pairCreatedAt') else 0,
        }
        signal['rugcheck_score'] = rug_data.get('score', 0) if rug_pass else 0
        
        # Open position
        open_position(contract, price, signal, market_data)
    
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
