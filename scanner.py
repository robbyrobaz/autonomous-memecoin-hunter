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

import time
import requests
from telethon import TelegramClient
from dotenv import load_dotenv

# === LIVE TRADING CONFIG ===
LIVE_TRADING = False  # PAPER ONLY until strategy proves profitable (Apr 8 2026)
# === YOLO MODE (data-driven, Apr 8 2026) ===
# Analysis of 25,192 price points across 2,606 contracts:
# - 72% of missed moonshots (10x+) were killed by rugcheck filters
# - 23% more missed due to rugcheck API rate limits
# - Trailing stop is the ONLY profitable exit mechanism (+$619)
# - All entry filters REMOVED — trailing stop IS the risk management
# - See FILTER_HISTORY.md for full analysis
LIVE_SOL_AMOUNT = 0.005  # ~$0.65 per trade
SOL_PRICE_USD = 130.0  # Approximate, for display only

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

# Live trading files (separate from paper)
LIVE_POSITIONS_FILE = BASE_DIR / 'data' / 'live_positions.json'
LIVE_BALANCE_FILE = BASE_DIR / 'data' / 'live_balance.txt'
LIVE_TRADES_LOG = BASE_DIR / 'logs' / 'live_trades.jsonl'

# Import swap executor for live trading
if LIVE_TRADING:
    try:
        import swap_executor
        print("✅ Live trading enabled - swap_executor loaded")
    except ImportError as e:
        print(f"⚠️ swap_executor import failed, disabling live trading: {e}")
        LIVE_TRADING = False

# Paper trading state
PAPER_BALANCE = 100.0  # $100 starting balance
POSITION_SIZE = 1.0  # $1 per trade
MAX_POSITIONS = 100  # 100 concurrent positions max

# === V3 FILTERS (data-driven from 191 closed trades, April 7 2026) ===
# See FILTER_HISTORY.md for V2 settings and full analysis
# Trailing stop = ONLY profitable exit (+$29.61, 100% WR)
# Key insight: rugcheck 10K-20K was the ONLY profitable score band
MIN_RUGCHECK_SCORE = 0      # YOLO: Accept any score
MAX_RUGCHECK_SCORE = 999999 # YOLO: Accept any score
MIN_AGE_MINUTES = 1         # YOLO: Widened from 6
MAX_AGE_MINUTES = 120       # YOLO: Widened from 30
MIN_LIQUIDITY_USD = 0       # YOLO: Accept any liquidity
HARD_STOP_PCT = 0.30        # -70% hard stop (only catches real rugs)
TRAILING_STOP_PCT = 0.12    # YOLO: Tightened from 0.15 (data showed tighter = more profit)
TIME_LIMIT_HOURS = 6        # YOLO: Extended from 2 (give winners time to run)


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


RUGCHECK_API_KEY = "613f82fb-b9d9-4c72-971b-e6dcaa39ffe5"


def check_rugcheck(contract: str) -> tuple[bool, str, Dict]:
    """Check contract safety via rugcheck.xyz (uses lighter summary endpoint)"""
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{contract}/report/summary"
        params = {"key": RUGCHECK_API_KEY} if RUGCHECK_API_KEY else {}
        resp = requests.get(url, params=params, timeout=30)
        
        if resp.status_code != 200:
            return False, f"API error: {resp.status_code}", {}
        
        data = resp.json()
        if data.get('error'):
            return False, f"Report error: {data['error']}", {}
        
        score = data.get('score', 0)
        risks = data.get('risks', [])
        
        # YOLO MODE: Accept any rugcheck score — data shows filters kill 72% of moonshots
        # Trailing stop is our risk management, not rugcheck scores
        pass  # All scores accepted
        
        return True, f"PASS (score: {score})", data
    except Exception as e:
        return False, f"Rugcheck error: {e}", {}


def batch_check_rugcheck(contracts: List[str]) -> Dict[str, tuple]:
    """Check rugcheck for multiple contracts using concurrent requests.
    Returns dict mapping contract -> (pass, msg, data) tuple.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results = {}
    
    def check_one(contract):
        return contract, check_rugcheck(contract)
    
    # Run up to 3 concurrent rugcheck calls (free tier = 3 req/sec)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(check_one, c): c for c in contracts}
        for future in as_completed(futures):
            try:
                contract, result = future.result()
                results[contract] = result
            except Exception as e:
                contract = futures[future]
                results[contract] = (False, f"Rugcheck error: {e}", {})
    
    passed = sum(1 for r in results.values() if r[0])
    print(f"🔍 Rugcheck batch: {passed}/{len(contracts)} passed ({len(contracts)} concurrent calls)")
    return results


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


def batch_fetch_dexscreener(contracts: List[str]) -> Dict[str, Dict]:
    """Batch fetch Dexscreener data for up to 30 tokens in ONE call.
    Returns dict mapping contract -> best pair data.
    """
    result = {}
    if not contracts:
        return result
    
    # Dedupe and chunk into batches of 30
    unique_contracts = list(set(contracts))
    
    for i in range(0, len(unique_contracts), 30):
        chunk = unique_contracts[i:i+30]
        try:
            joined = ','.join(chunk)
            url = f"https://api.dexscreener.com/tokens/v1/solana/{joined}"
            resp = requests.get(url, timeout=15)
            
            if resp.status_code != 200:
                print(f"⚠️  Dexscreener batch error: {resp.status_code}")
                continue
            
            pairs = resp.json()
            if not isinstance(pairs, list):
                continue
            
            # Group pairs by base token address, keep best (highest liquidity)
            for pair in pairs:
                addr = pair.get('baseToken', {}).get('address', '')
                if not addr:
                    continue
                liq = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                existing = result.get(addr)
                if not existing or liq > float(existing.get('liquidity', {}).get('usd', 0) or 0):
                    result[addr] = pair
            
            if i + 30 < len(unique_contracts):
                time.sleep(0.25)  # Small delay between chunks
                
        except Exception as e:
            print(f"❌ Dexscreener batch error: {e}")
    
    print(f"📊 Dexscreener batch: {len(result)} pairs for {len(unique_contracts)} tokens ({(len(unique_contracts) + 29) // 30} API calls)")
    return result


def check_dexscreener_from_cache(contract: str, dex_cache: Dict[str, Dict]) -> tuple[bool, str, Dict]:
    """Check Dexscreener filters using pre-fetched batch data."""
    pair = dex_cache.get(contract)
    
    if not pair:
        return False, "No trading pairs found", {}
    
    liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
    volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
    created_at = pair.get('pairCreatedAt')
    
    # YOLO MODE: Accept any liquidity — biggest winners had $0 liq at entry
    pass  # All liquidity levels accepted
    
    # V3: Check token age (6-30 min sweet spot from data analysis)
    if created_at:
        age_minutes = (datetime.now().timestamp() * 1000 - created_at) / 60000
        if age_minutes < MIN_AGE_MINUTES:
            return False, f"Too new: {age_minutes:.1f}min (need >= {MIN_AGE_MINUTES}min)", pair
        if age_minutes > MAX_AGE_MINUTES:
            return False, f"Too old: {age_minutes:.1f}min (need <= {MAX_AGE_MINUTES}min)", pair
    
    return True, f"PASS (liq: ${liquidity:,.0f})", pair


def check_dexscreener(contract: str) -> tuple[bool, str, Dict]:
    """Check price, volume, age via Dexscreener - single token fallback"""
    cache = batch_fetch_dexscreener([contract])
    return check_dexscreener_from_cache(contract, cache)


def get_current_price(contract: str) -> Optional[float]:
    """Get current price from Dexscreener (single token)"""
    try:
        cache = batch_fetch_dexscreener([contract])
        pair = cache.get(contract)
        if pair:
            return float(pair.get('priceUsd', 0) or 0)
    except:
        pass
    return None


def batch_get_current_prices(contracts: List[str]) -> Dict[str, float]:
    """Get current prices for multiple tokens in batch. Returns contract -> price."""
    cache = batch_fetch_dexscreener(contracts)
    prices = {}
    for contract, pair in cache.items():
        try:
            price = float(pair.get('priceUsd', 0) or 0)
            if price > 0:
                prices[contract] = price
        except:
            pass
    return prices


def load_positions() -> List[Dict]:
    """Load paper positions"""
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


def save_positions(positions: List[Dict]):
    """Save paper positions to disk (atomic write to prevent corruption)"""
    tmp = POSITIONS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(positions, f, indent=2)
    tmp.rename(POSITIONS_FILE)


# === LIVE TRADING FUNCTIONS ===

def load_live_positions() -> List[Dict]:
    """Load live positions"""
    if LIVE_POSITIONS_FILE.exists():
        with open(LIVE_POSITIONS_FILE) as f:
            return json.load(f)
    return []


def save_live_positions(positions: List[Dict]):
    """Save live positions (atomic write)"""
    tmp = LIVE_POSITIONS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(positions, f, indent=2)
    tmp.rename(LIVE_POSITIONS_FILE)


def get_live_balance() -> float:
    """Get live SOL balance tracking value"""
    if LIVE_BALANCE_FILE.exists():
        return float(LIVE_BALANCE_FILE.read_text().strip())
    return 0.0


def save_live_balance(balance: float):
    """Save live SOL balance"""
    LIVE_BALANCE_FILE.write_text(str(round(balance, 8)))


def log_live_trade(position: Dict, action: str):
    """Log live trade action"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        **position
    }
    with open(LIVE_TRADES_LOG, 'a') as f:
        f.write(json.dumps(data) + '\n')


def get_token_balance(contract: str) -> int:
    """Check if we actually hold tokens of a given mint. Returns raw token amount."""
    try:
        from solders.pubkey import Pubkey
        from solana.rpc.api import Client
        from solana.rpc.types import TokenAccountOpts

        kp = swap_executor.load_keypair()
        client = Client(swap_executor.RPC_URL)
        resp = client.get_token_accounts_by_owner_json_parsed(
            kp.pubkey(),
            TokenAccountOpts(mint=Pubkey.from_string(contract)),
        )
        if not resp.value:
            return 0
        account_data = resp.value[0].account.data
        parsed = json.loads(account_data.to_json())
        return int(parsed["parsed"]["info"]["tokenAmount"]["amount"])
    except Exception as e:
        print(f"⚠️ get_token_balance error: {e}")
        return 0


def open_live_position(contract: str, entry_price: float, signal_data: Dict, market_data: Dict = None):
    """Open a LIVE position with real swap execution"""
    if not LIVE_TRADING:
        return

    positions = load_live_positions()

    # Check if already in this token
    for p in positions:
        if p['contract'] == contract and p['status'] == 'OPEN':
            print(f"⚠️ LIVE: Already have open position in {contract[:8]}...")
            return

    # Check SOL balance
    try:
        sol_balance = swap_executor.get_sol_balance()
        if sol_balance < LIVE_SOL_AMOUNT + 0.002:  # Need SOL for swap + fees
            print(f"⚠️ LIVE: Insufficient SOL balance: {sol_balance:.4f} (need {LIVE_SOL_AMOUNT + 0.002:.4f})")
            return
    except Exception as e:
        print(f"⚠️ LIVE: Failed to check SOL balance: {e}")
        return

    # Execute the buy swap
    print(f"🛒 LIVE BUY: {contract[:8]}... with {LIVE_SOL_AMOUNT} SOL")
    try:
        success, sig_or_err, details = swap_executor.buy_token(contract, LIVE_SOL_AMOUNT)
    except Exception as e:
        print(f"❌ LIVE BUY FAILED (exception): {e}")
        return

    if not success:
        print(f"❌ LIVE BUY FAILED: {sig_or_err}")
        return

    # Build live position
    position = {
        'contract': contract,
        'entry_price': entry_price,
        'entry_time': datetime.now().isoformat(),
        'sol_spent': LIVE_SOL_AMOUNT,
        'size_usd': LIVE_SOL_AMOUNT * SOL_PRICE_USD,
        'tx_buy_sig': sig_or_err,
        'buy_details': {
            'in_amount': details.get('in_amount', 0),
            'out_amount': details.get('out_amount', 0),
            'price_impact_pct': details.get('price_impact_pct', '0'),
            'confirmed': details.get('confirmed', False),
        },
        'tokens_received': details.get('out_amount', 0),
        'initial_stop': entry_price * HARD_STOP_PCT,
        'trailing_stop': None,
        'peak_price': entry_price,
        'peak_time': None,
        'status': 'OPEN',
        'signal_data': signal_data,
        'market_data': market_data or {},
        'sol_received': None,
        'tx_sell_sig': None,
    }

    positions.append(position)
    save_live_positions(positions)

    # Track cumulative SOL spent
    live_bal = get_live_balance()
    save_live_balance(live_bal - LIVE_SOL_AMOUNT)

    log_live_trade(position, 'OPEN')
    print(f"✅ LIVE OPENED: {contract[:8]}... tx: {sig_or_err[:16]}... ({LIVE_SOL_AMOUNT} SOL)")


def check_live_exits():
    """Check all open LIVE positions for exit conditions"""
    if not LIVE_TRADING:
        return

    positions = load_live_positions()
    changed = False

    # Batch fetch all open live position prices in one call
    open_contracts = [p['contract'] for p in positions if p['status'] == 'OPEN']
    if open_contracts:
        prices = batch_get_current_prices(open_contracts)
        print(f"💰 Live exit check: got prices for {len(prices)}/{len(open_contracts)} open positions")
    else:
        prices = {}

    for pos in positions:
        if pos['status'] != 'OPEN':
            continue

        current_price = prices.get(pos['contract'])
        if not current_price:
            continue

        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        entry_price = pos['entry_price']

        # Update peak
        peak_price = pos.get('peak_price', entry_price)
        if current_price > peak_price:
            peak_price = current_price
            pos['peak_price'] = peak_price
            pos['peak_time'] = datetime.now().isoformat()
            changed = True

        pnl_pct = (current_price / entry_price - 1) * 100
        exit_reason = None

        # Trailing stop
        if current_price > entry_price:
            trailing_stop = peak_price * (1 - TRAILING_STOP_PCT)
            pos['trailing_stop'] = trailing_stop
            if current_price <= trailing_stop:
                exit_reason = 'TRAILING_STOP'

        # Hard stop
        if not exit_reason:
            initial_stop = pos.get('initial_stop', entry_price * HARD_STOP_PCT)
            if current_price <= initial_stop:
                exit_reason = 'STOP_LOSS'

        # Time limit
        if not exit_reason and hours_held >= TIME_LIMIT_HOURS:
            exit_reason = 'TIME_LIMIT'

        if exit_reason:
            close_live_position(pos, current_price, exit_reason, pnl_pct)
            changed = True

    if changed:
        save_live_positions(positions)


def close_live_position(pos: Dict, exit_price: float, reason: str, pnl_pct: float):
    """Close a LIVE position with real swap"""
    contract = pos['contract']

    # Check if we actually hold tokens
    token_bal = get_token_balance(contract)
    if token_bal == 0:
        print(f"⚠️ LIVE: No tokens held for {contract[:8]}..., marking as closed (no sell)")
        pos['status'] = 'CLOSED'
        pos['exit_price'] = exit_price
        pos['exit_time'] = datetime.now().isoformat()
        pos['exit_reason'] = reason + '_NO_TOKENS'
        pos['pnl_pct'] = -100.0
        pos['pnl_usd'] = -pos['sol_spent'] * SOL_PRICE_USD
        pos['sol_received'] = 0
        pos['tx_sell_sig'] = None
        log_live_trade(pos, 'CLOSE')
        return

    # Execute sell
    print(f"💰 LIVE SELL ({reason}): {contract[:8]}...")
    try:
        success, sig_or_err, details = swap_executor.sell_all_token(contract)
    except Exception as e:
        print(f"❌ LIVE SELL FAILED (exception): {e}")
        return

    if not success:
        print(f"❌ LIVE SELL FAILED: {sig_or_err}")
        return

    # Calculate actual P&L in SOL
    sol_received = details.get('out_amount', 0) / 1_000_000_000  # lamports to SOL
    sol_spent = pos['sol_spent']
    sol_pnl = sol_received - sol_spent

    pos['status'] = 'CLOSED'
    pos['exit_price'] = exit_price
    pos['exit_time'] = datetime.now().isoformat()
    pos['exit_reason'] = reason
    pos['pnl_pct'] = pnl_pct
    pos['sol_received'] = sol_received
    pos['sol_pnl'] = sol_pnl
    pos['pnl_usd'] = sol_pnl * SOL_PRICE_USD
    pos['tx_sell_sig'] = sig_or_err
    pos['sell_details'] = {
        'in_amount': details.get('in_amount', 0),
        'out_amount': details.get('out_amount', 0),
        'price_impact_pct': details.get('price_impact_pct', '0'),
        'confirmed': details.get('confirmed', False),
    }

    # Analytics
    entry_time = datetime.fromisoformat(pos['entry_time'])
    exit_time = datetime.fromisoformat(pos['exit_time'])
    peak_price = pos.get('peak_price', pos['entry_price'])
    pos['analytics'] = {
        'time_in_position_minutes': (exit_time - entry_time).total_seconds() / 60,
        'peak_gain_pct': ((peak_price / pos['entry_price']) - 1) * 100,
        'exit_from_peak_pct': ((exit_price / peak_price) - 1) * 100 if peak_price > 0 else 0,
        'trailing_stop_worked': reason == 'TRAILING_STOP',
    }

    # Update live balance
    live_bal = get_live_balance()
    save_live_balance(live_bal + sol_received)

    # Save live positions
    live_positions = load_live_positions()
    for p in live_positions:
        if p['contract'] == pos['contract'] and p['entry_time'] == pos['entry_time']:
            p.update(pos)
    save_live_positions(live_positions)

    log_live_trade(pos, 'CLOSE')
    emoji = '🎯' if sol_pnl > 0 else '❌'
    print(f"{emoji} LIVE CLOSED {contract[:8]}... {reason}: {sol_pnl:+.6f} SOL (${sol_pnl * SOL_PRICE_USD:+.2f}) tx: {sig_or_err[:16]}...")


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
        'initial_stop': entry_price * HARD_STOP_PCT,  # -70% stop (only catches real rugs, not normal volatility)
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
    
    # Batch fetch all open position prices in one call
    open_contracts = [p['contract'] for p in positions if p['status'] == 'OPEN']
    if open_contracts:
        prices = batch_get_current_prices(open_contracts)
        print(f"💰 Paper exit check: got prices for {len(prices)}/{len(open_contracts)} open positions")
    else:
        prices = {}
    
    for pos in positions:
        if pos['status'] != 'OPEN':
            continue
        
        current_price = prices.get(pos['contract'])
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
        # V2: Tighter trailing stop (20% below peak) to lock profits faster
        if current_price > entry_price:
            trailing_stop = peak_price * (1 - TRAILING_STOP_PCT)  # 20% below peak
            pos['trailing_stop'] = trailing_stop
            
            if current_price <= trailing_stop:
                # Hit trailing stop - lock in profits
                close_position(pos, current_price, 'TRAILING_STOP', pnl_pct)
                continue
        
        # V2: Wide stop loss - only catches real rugs, not normal volatility
        # Data showed -30% stop destroyed $669 in value. Widened to -70%.
        initial_stop = pos.get('initial_stop', entry_price * HARD_STOP_PCT)
        if current_price <= initial_stop:
            close_position(pos, current_price, 'STOP_LOSS', pnl_pct)
            continue
        
        # TIME LIMIT (safety exit)
        if hours_held >= TIME_LIMIT_HOURS:
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
        'message': message
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

    # Initialize live balance file if needed
    if LIVE_TRADING and not LIVE_BALANCE_FILE.exists():
        LIVE_BALANCE_FILE.write_text("0.0")
        print(f"🔴 Initialized live balance tracking")
    
    # Create log dirs
    (BASE_DIR / 'logs').mkdir(exist_ok=True)
    (BASE_DIR / 'data').mkdir(exist_ok=True)
    
    # Check exits first
    print("🔍 Checking open positions for exits...")
    check_exits()

    # Check LIVE exits
    if LIVE_TRADING:
        print("🔍 Checking LIVE positions for exits...")
        check_live_exits()
    
    # Scan for new signals
    signals = await scan_telegram_channels()
    
    print(f"\n📊 Found {len(signals)} signals\n")
    
    # Process signals - BATCH fetch all data upfront
    if signals:
        all_contracts = list(set(s['contract'] for s in signals))
        print(f"\n📡 Batch fetching data for {len(all_contracts)} unique contracts...")
        
        # Fetch dexscreener (1-2 API calls) and rugcheck (concurrent) in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            dex_future = executor.submit(batch_fetch_dexscreener, all_contracts)
            rug_future = executor.submit(batch_check_rugcheck, all_contracts)
            dex_cache = dex_future.result()
            rug_cache = rug_future.result()
    else:
        dex_cache = {}
        rug_cache = {}
    
    for signal in signals:
        contract = signal['contract']
        
        print(f"\n🔬 Analyzing {contract[:8]}...")
        
        # Safety checks — use pre-fetched data (no per-token API calls!)
        if contract in rug_cache:
            rug_pass, rug_msg, rug_data = rug_cache[contract]
        else:
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
        
        # Use batch-cached dexscreener data (no per-token API call!)
        dex_pass, dex_msg, dex_data = check_dexscreener_from_cache(contract, dex_cache)
        if not dex_pass:
            print(f"  ❌ Dexscreener: {dex_msg}")
            log_rejection(contract, f"Dexscreener: {dex_msg}", signal)
            continue
        print(f"  ✅ Dexscreener: {dex_msg}")
        
        # Get entry price from cached data (no extra API call!)
        price = float(dex_data.get('priceUsd', 0) or 0) if dex_data else None
        if not price:
            print(f"  ❌ Could not fetch price")
            log_rejection(contract, "Price unavailable", signal)
            continue
        
        # Collect market data for ANALYSIS
        market_data = {
            'liquidity': float(dex_data.get('liquidity', {}).get('usd', 0) or 0),
            'volume_24h': float(dex_data.get('volume', {}).get('h24', 0) or 0),
            'holders': rug_data.get('topHolders', {}).get('count', 0) if (rug_pass and isinstance(rug_data.get('topHolders'), dict)) else 0,
            'age_hours': (datetime.now() - datetime.fromtimestamp(dex_data.get('pairCreatedAt', 0) / 1000)).total_seconds() / 3600 if dex_data.get('pairCreatedAt') else 0,
            'token_name': dex_data.get('baseToken', {}).get('name', ''),
            'token_symbol': dex_data.get('baseToken', {}).get('symbol', ''),
        }
        signal['rugcheck_score'] = rug_data.get('score', 0) if (rug_pass and isinstance(rug_data, dict)) else 0
        
        # Open paper position
        open_position(contract, price, signal, market_data)

        # Open LIVE position (real swap)
        if LIVE_TRADING:
            open_live_position(contract, price, signal, market_data)
    
    # Summary
    with open(balance_file) as f:
        balance = float(f.read().strip())
    
    positions = load_positions()
    open_count = len([p for p in positions if p['status'] == 'OPEN'])
    closed_count = len([p for p in positions if p['status'] == 'CLOSED'])
    
    total_pnl = sum(p.get('pnl_usd', 0) for p in positions if p['status'] == 'CLOSED')
    
    print(f"\n{'='*60}")
    print(f"📈 Paper Summary:")
    print(f"   Balance: ${balance:,.2f}")
    print(f"   Open: {open_count} | Closed: {closed_count}")
    print(f"   Total P&L: ${total_pnl:+,.2f}")

    if LIVE_TRADING:
        live_positions = load_live_positions()
        live_open = len([p for p in live_positions if p['status'] == 'OPEN'])
        live_closed = len([p for p in live_positions if p['status'] == 'CLOSED'])
        live_pnl_sol = sum(p.get('sol_pnl', 0) for p in live_positions if p['status'] == 'CLOSED')
        try:
            wallet_sol = swap_executor.get_sol_balance()
        except:
            wallet_sol = 0
        print(f"\n🔴 LIVE Summary:")
        print(f"   Wallet SOL: {wallet_sol:.4f}")
        print(f"   Live Open: {live_open} | Closed: {live_closed}")
        print(f"   Live P&L: {live_pnl_sol:+.6f} SOL (${live_pnl_sol * SOL_PRICE_USD:+.2f})")

    print(f"{'='*60}\n")


if __name__ == '__main__':
    asyncio.run(main())
