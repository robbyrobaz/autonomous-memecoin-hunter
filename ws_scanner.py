#!/usr/bin/env python3
"""
Real-Time WebSocket Memecoin Scanner — PumpPortal New Token Stream

Connects to wss://pumpportal.fun/api/data and queues new tokens for
ML-filtered evaluation before opening paper positions.
Entry filter: volume ≥ $3k OR price up ≥5% at 3 min. Trailing stop exit.
"""

import asyncio
import json
import os
import sys
import time
import threading
import traceback
import requests
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import websockets

# === CONFIG ===
LIVE_TRADING = False           # PAPER ONLY until strategy proves profitable (Apr 8 2026)
LIVE_SOL_AMOUNT = 0.005        # ~$0.65 per trade
SOL_PRICE_USD = 130.0          # Approximate, for display
TRAILING_STOP_PCT = 0.10       # 10% below peak (backtest: tighter = better)
HARD_STOP_PCT = 0.50           # entry_price * 0.50 = -50% hard stop
TIME_LIMIT_HOURS = 6           # Max hold time
MAX_POSITIONS = 500            # Paper: ~23 tokens/min × 20min DEAD_COIN hold = ~460 steady-state
POSITION_SIZE = 1.0            # $1 paper position
PAPER_BALANCE_DEFAULT = 1000.0  # Raised to match higher position cap

EXIT_CHECK_INTERVAL = 30       # Seconds between exit checks
STATUS_INTERVAL = 60           # Seconds between status prints
WS_URL = "wss://pumpportal.fun/api/data"
RECONNECT_BASE_DELAY = 2       # Starting reconnect delay (seconds)
RECONNECT_MAX_DELAY = 120      # Max reconnect delay

# === ENTRY FILTER (ML-derived, Apr 2026) ===
# Don't buy instantly — wait EVAL_DELAY_S, then check Dexscreener.
# Tokens with real traction at 3 min have 35-49% win rate vs 14% baseline.
EVAL_DELAY_S       = 180   # Wait 3 min before evaluating (seconds)
EVAL_TIMEOUT_S     = 600   # Discard token if still unresolved at 10 min
EVAL_MIN_VOLUME    = 3000  # Min $3k volume in first 3 min to qualify
EVAL_MIN_PRICE_CHG = 5.0   # OR price up ≥5% in last 5 min (momentum signal)

# === DEAD COIN EXIT ===
# Exit early if a token has had virtually no trading activity for the past hour.
# Transaction count beats volume — a single whale can fake volume, not trade count.
# Only triggers after MIN_HOLD to give the token time to develop.
DEAD_COIN_MIN_HOLD_MIN  = 20   # Don't check before 20 min — gives token time to develop
DEAD_COIN_MAX_TXNS_H1   = 3    # Exit if total buys+sells in last 1h < 3 (effectively dead)

# === PATHS ===
BASE_DIR = Path(__file__).parent
SIGNALS_LOG = BASE_DIR / 'logs' / 'signals.jsonl'
TRADES_LOG = BASE_DIR / 'logs' / 'paper_trades.jsonl'
LIVE_TRADES_LOG = BASE_DIR / 'logs' / 'live_trades.jsonl'
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'
LIVE_POSITIONS_FILE = BASE_DIR / 'data' / 'live_positions.json'
LIVE_BALANCE_FILE = BASE_DIR / 'data' / 'live_balance.txt'
BALANCE_FILE = BASE_DIR / 'data' / 'balance.txt'
PRICE_PATHS_LOG = BASE_DIR / 'logs' / 'price_paths.jsonl'  # 30s price ticks for backtesting

# === LOAD ENV ===
from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')

# === IMPORT EXECUTORS ===
sys.path.insert(0, str(BASE_DIR))

try:
    import pumpfun_executor
    print("✅ pumpfun_executor loaded")
except ImportError as e:
    print(f"❌ pumpfun_executor import failed: {e}")
    pumpfun_executor = None

try:
    import swap_executor
    print("✅ swap_executor loaded")
except ImportError as e:
    print(f"❌ swap_executor import failed: {e}")
    swap_executor = None

# === STATS ===
stats = {
    'tokens_seen': 0,
    'buys_paper': 0,     # successful paper opens
    'buys_live': 0,      # successful live buys (0 while LIVE_TRADING=False)
    'buys_skipped': 0,   # passed filter but blocked (max positions / dedup)
    'ws_reconnects': 0,
    'filtered_out': 0,
    'start_time': datetime.now().isoformat(),
}

# === PENDING EVALUATION QUEUE ===
# mint → {seen_at: float, name: str, symbol: str}
# Tokens wait here until EVAL_DELAY_S before Dexscreener check fires.
_pending: Dict[str, dict] = {}

# All mints ever queued this session — prevents re-buying on WS reconnect.
# Capped at 500k entries with FIFO eviction to prevent unbounded memory growth
# over multi-day runs (500 tokens/5min × 1440 min/day ≈ 144k/day × 3.5 days fits).
_EVER_QUEUED_MAX = 500_000
_ever_queued: set = set()
_ever_queued_queue: deque = deque()  # FIFO for eviction order


def _ever_queued_add(mint: str) -> None:
    if mint in _ever_queued:
        return
    if len(_ever_queued) >= _EVER_QUEUED_MAX:
        old = _ever_queued_queue.popleft()
        _ever_queued.discard(old)
    _ever_queued.add(mint)
    _ever_queued_queue.append(mint)

# Lock for paper positions file — prevents race between evaluation_loop (execute_buy)
# and exit_check_loop (check_paper_exits) both writing positions.tmp simultaneously.
_positions_lock = threading.Lock()

# Lock for trade/signal log files — prevents interleaved JSONL writes when
# exit_check_loop and evaluation_loop both call log_trade from separate threads.
_log_lock = threading.Lock()

# Lock for paper balance file — prevents lost balance updates when two threads
# concurrently read-modify-write balance.txt.
_balance_lock = threading.Lock()


# ─── Position Management (mirrors scanner.py) ──────────────────────────

def load_positions() -> List[Dict]:
    """Load paper positions"""
    if POSITIONS_FILE.exists():
        try:
            with open(POSITIONS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_positions(positions: List[Dict]):
    """Save paper positions (atomic write)"""
    tmp = POSITIONS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(positions, f, indent=2)
    try:
        tmp.rename(POSITIONS_FILE)
    except FileNotFoundError:
        # Rare race: another thread already renamed the .tmp file.
        # Re-write and rename once more under the assumption the lock
        # wasn't held correctly (defensive fallback).
        with open(tmp, 'w') as f:
            json.dump(positions, f, indent=2)
        tmp.rename(POSITIONS_FILE)


def load_live_positions() -> List[Dict]:
    """Load live positions"""
    if LIVE_POSITIONS_FILE.exists():
        try:
            with open(LIVE_POSITIONS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_live_positions(positions: List[Dict]):
    """Save live positions (atomic write)"""
    tmp = LIVE_POSITIONS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(positions, f, indent=2)
    tmp.rename(LIVE_POSITIONS_FILE)


def get_live_balance() -> float:
    if LIVE_BALANCE_FILE.exists():
        try:
            return float(LIVE_BALANCE_FILE.read_text().strip())
        except (ValueError, IOError):
            return 0.0
    return 0.0


def save_live_balance(balance: float):
    LIVE_BALANCE_FILE.write_text(str(round(balance, 8)))


def get_paper_balance() -> float:
    if BALANCE_FILE.exists():
        try:
            return float(BALANCE_FILE.read_text().strip())
        except (ValueError, IOError):
            return PAPER_BALANCE_DEFAULT
    return PAPER_BALANCE_DEFAULT


def save_paper_balance(balance: float):
    BALANCE_FILE.write_text(str(round(balance, 4)))


def deduct_paper_balance(amount: float) -> None:
    """Thread-safe read-modify-write on paper balance."""
    with _balance_lock:
        bal = get_paper_balance()
        save_paper_balance(bal - amount)


def credit_paper_balance(amount: float) -> None:
    """Thread-safe credit of paper balance on position close."""
    with _balance_lock:
        bal = get_paper_balance()
        save_paper_balance(bal + amount)


# ─── Logging (mirrors scanner.py) ──────────────────────────────────────

def log_signal(contract: str, name: str, symbol: str):
    """Log detected signal — stores full message, not a truncated snippet."""
    data = {
        'timestamp': datetime.now().isoformat(),
        'contract': contract,
        'score': 0,
        'channel': 'pumpportal_ws',
        'message': f"New PumpFun token: {name} ({symbol}) — {contract}",
    }
    with _log_lock:
        with open(SIGNALS_LOG, 'a') as f:
            f.write(json.dumps(data) + '\n')


def log_trade(position: Dict, action: str, log_file: Path):
    """Log trade action. Uses _log_lock to prevent interleaved JSONL writes
    from exit_check_loop and evaluation_loop running in separate threads."""
    data = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        **position
    }
    with _log_lock:
        with open(log_file, 'a') as f:
            f.write(json.dumps(data) + '\n')


# ─── Dexscreener Batch Price Fetch (mirrors scanner.py) ────────────────

def batch_fetch_dexscreener(contracts: List[str]) -> Dict[str, Dict]:
    """Batch fetch Dexscreener data for up to 30 tokens in ONE call."""
    result = {}
    if not contracts:
        return result

    unique_contracts = list(set(contracts))

    for i in range(0, len(unique_contracts), 30):
        chunk = unique_contracts[i:i + 30]
        try:
            joined = ','.join(chunk)
            url = f"https://api.dexscreener.com/tokens/v1/solana/{joined}"

            resp = None
            for retry_delay in (0, 5, 15):
                if retry_delay:
                    time.sleep(retry_delay)
                resp = requests.get(url, timeout=15)
                if resp.status_code != 429:
                    break
                print(f"⚠️ Dexscreener 429 — retrying in {5 if retry_delay == 0 else 15}s")
            if resp.status_code != 200:
                print(f"⚠️ Dexscreener batch error: {resp.status_code}")
                continue

            pairs = resp.json()
            if not isinstance(pairs, list):
                continue

            for pair in pairs:
                addr = pair.get('baseToken', {}).get('address', '')
                if not addr:
                    continue
                liq = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                existing = result.get(addr)
                if not existing or liq > float(existing.get('liquidity', {}).get('usd', 0) or 0):
                    result[addr] = pair

            if i + 30 < len(unique_contracts):
                time.sleep(0.25)

        except Exception as e:
            print(f"❌ Dexscreener batch error: {e}")

    return result


def batch_get_current_prices(contracts: List[str]) -> Dict[str, float]:
    """Get current prices for multiple tokens in batch."""
    cache = batch_fetch_dexscreener(contracts)
    prices = {}
    for contract, pair in cache.items():
        try:
            price = float(pair.get('priceUsd', 0) or 0)
            if price > 0:
                prices[contract] = price
        except (ValueError, TypeError):
            pass
    return prices


def batch_get_market_data(contracts: List[str]) -> Dict[str, dict]:
    """Get price + txn counts for dead-coin detection. One Dexscreener call."""
    cache = batch_fetch_dexscreener(contracts)
    result = {}
    for contract, pair in cache.items():
        try:
            price = float(pair.get('priceUsd', 0) or 0)
            # Use None when txns.h1 is absent — distinguishes "no data" from "0 trades".
            # Missing data must NOT trigger DEAD_COIN (false positive risk).
            txns_raw = (pair.get('txns') or {}).get('h1')
            txns_h1_total = (
                None if txns_raw is None
                else int(txns_raw.get('buys', 0) or 0) + int(txns_raw.get('sells', 0) or 0)
            )
            result[contract] = {
                'price':       price,
                'txns_h1':     txns_h1_total,
                'volume_h1':   float((pair.get('volume') or {}).get('h1', 0) or 0),
                'volume_m5':   float((pair.get('volume') or {}).get('m5', 0) or 0),
            }
        except (ValueError, TypeError):
            pass
    return result


def get_token_balance(contract: str) -> int:
    """Check if we actually hold tokens of a given mint."""
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


# ─── Buy Logic ──────────────────────────────────────────────────────────

def execute_buy(mint: str, name: str, symbol: str, eval_metrics: dict | None = None):
    """
    Buy a new token: live buy via PumpPortal, open paper + live positions.
    Runs synchronously (called from async via run_in_executor).
    eval_metrics: dict with volume, price_ch, liq, age_m, filter_branch from eval loop.
    """
    now = datetime.now()

    # Pre-check position limits (outside lock — quick rejection before any network calls)
    positions = load_positions()
    open_paper = len([p for p in positions if p['status'] == 'OPEN'])
    live_positions = load_live_positions()
    open_live = len([p for p in live_positions if p['status'] == 'OPEN'])

    if open_paper >= MAX_POSITIONS:
        print(f"⚠️ Max paper positions ({MAX_POSITIONS}) reached, skip {mint[:12]}...")
        stats['buys_skipped'] += 1
        return False

    # Check if already in this token (paper)
    for p in positions:
        if p['contract'] == mint and p['status'] == 'OPEN':
            print(f"⚠️ Already have paper position in {mint[:12]}...")
            stats['buys_skipped'] += 1
            return False

    # --- LIVE BUY via PumpPortal ---
    live_buy_result = None
    if LIVE_TRADING and pumpfun_executor:
        try:
            sol_balance = swap_executor.get_sol_balance() if swap_executor else 999
            if sol_balance < LIVE_SOL_AMOUNT + 0.002:
                print(f"⚠️ LIVE: Insufficient SOL: {sol_balance:.4f}")
            else:
                live_buy_result = pumpfun_executor.buy_pumpfun(mint, LIVE_SOL_AMOUNT)
        except Exception as e:
            print(f"❌ LIVE BUY exception: {e}")

    # We may not get a price from Dexscreener immediately for brand new tokens.
    # Use a placeholder entry price; exit logic will fetch real prices later.
    entry_price = 0.0000001  # Placeholder — will be updated on first exit check

    signal_data = {
        'channel': 'pumpportal_ws',
        'name': name,
        'symbol': symbol,
        'score': 0,
        'message_snippet': f"New PumpFun token: {name} ({symbol})",
    }

    # --- PAPER POSITION ---
    paper_pos = {
        'contract': mint,
        'entry_price': entry_price,
        'entry_time': now.isoformat(),
        'size_usd': POSITION_SIZE,
        'initial_stop': entry_price * HARD_STOP_PCT,
        'trailing_stop': None,
        'peak_price': entry_price,
        'peak_time': None,
        'status': 'OPEN',
        'signal_data': signal_data,
        'market_data': {'token_name': name, 'token_symbol': symbol},
        'entry_metrics': {
            'liquidity': eval_metrics.get('liq', 0) if eval_metrics else 0,
            'volume_24h': eval_metrics.get('volume', 0) if eval_metrics else 0,
            'price_change_5m': eval_metrics.get('price_ch', 0) if eval_metrics else 0,
            'filter_branch': eval_metrics.get('filter_branch', 'unknown') if eval_metrics else 'unknown',
            'rugcheck_score': 0,
            'holder_count': 0,
            'age_hours': eval_metrics.get('age_m', 0) / 60 if eval_metrics else 0,
        },
        'source': 'ws_scanner',
    }
    # Lock covers load→append→save to prevent race with check_paper_exits thread
    with _positions_lock:
        positions = load_positions()  # Re-load inside lock for fresh state
        positions.append(paper_pos)
        save_positions(positions)

    deduct_paper_balance(POSITION_SIZE)

    log_trade(paper_pos, 'OPEN', TRADES_LOG)
    stats['buys_paper'] += 1
    print(f"📝 Paper OPENED: {name} ({symbol}) {mint[:12]}...")

    # --- LIVE POSITION ---
    if live_buy_result and live_buy_result.get('tx_hash'):
        live_pos = {
            'contract': mint,
            'entry_price': entry_price,
            'entry_time': now.isoformat(),
            'sol_spent': LIVE_SOL_AMOUNT,
            'size_usd': LIVE_SOL_AMOUNT * SOL_PRICE_USD,
            'tx_buy_sig': live_buy_result['tx_hash'],
            'buy_details': {
                'in_amount': live_buy_result.get('amount', 0),
                'out_amount': 0,
                'price_impact_pct': '0',
                'confirmed': True,
            },
            'tokens_received': 0,
            'initial_stop': entry_price * HARD_STOP_PCT,
            'trailing_stop': None,
            'peak_price': entry_price,
            'peak_time': None,
            'status': 'OPEN',
            'signal_data': signal_data,
            'market_data': {'token_name': name, 'token_symbol': symbol},
            'sol_received': None,
            'tx_sell_sig': None,
            'source': 'ws_scanner',
        }
        live_positions.append(live_pos)
        save_live_positions(live_positions)

        live_bal = get_live_balance()
        save_live_balance(live_bal - LIVE_SOL_AMOUNT)

        log_trade(live_pos, 'OPEN', LIVE_TRADES_LOG)
        stats['buys_live'] += 1
        print(f"🔴 LIVE OPENED: {name} ({symbol}) {mint[:12]}... tx: {live_buy_result['tx_hash'][:20]}...")
    elif LIVE_TRADING and pumpfun_executor:
        print(f"❌ LIVE BUY failed for {mint[:12]}...")

    return True


# ─── Exit Logic (mirrors scanner.py) ───────────────────────────────────

def check_paper_exits():
    """Check all open paper positions for exit conditions."""
    # Load positions and fetch market data outside the lock (network call)
    positions = load_positions()
    open_contracts = [p['contract'] for p in positions if p['status'] == 'OPEN']
    if not open_contracts:
        return

    market = batch_get_market_data(open_contracts)

    # Collect price ticks for backtesting OUTSIDE the lock (file I/O, not position state)
    now_str = datetime.now().isoformat(timespec='seconds')
    price_ticks = []
    for contract in open_contracts:
        price = (market.get(contract) or {}).get('price', 0)
        if price:
            price_ticks.append({'c': contract, 't': now_str, 'p': price})
    if price_ticks:
        try:
            with open(PRICE_PATHS_LOG, 'a') as _ppf:
                _ppf.write('\n'.join(json.dumps(t) for t in price_ticks) + '\n')
        except Exception:
            pass

    # Re-load inside lock, apply updates, save — prevents race with execute_buy
    with _positions_lock:
        positions = load_positions()
        changed = False

        for pos in positions:
            if pos['status'] != 'OPEN':
                continue

            mdata = market.get(pos['contract'], {})
            current_price = mdata.get('price', 0)
            if not current_price:
                continue

            entry_price = pos['entry_price']
            entry_time = datetime.fromisoformat(pos['entry_time'])
            hours_held = (datetime.now() - entry_time).total_seconds() / 3600
            mins_held  = hours_held * 60

            # Update entry price if it was a placeholder
            if entry_price < 0.000001 and current_price > 0:
                pos['entry_price'] = current_price
                pos['peak_price'] = current_price
                entry_price = current_price
                changed = True

            # Update peak
            peak_price = pos.get('peak_price', entry_price)
            if current_price > peak_price:
                peak_price = current_price
                pos['peak_price'] = peak_price
                pos['peak_time'] = datetime.now().isoformat()
                changed = True

            pnl_pct = (current_price / entry_price - 1) * 100 if entry_price > 0 else 0
            exit_reason = None

            # Trailing stop — two separate steps:
            # 1) Update stop level (only moves up, only when price is above entry)
            if current_price > entry_price:
                new_trail = peak_price * (1 - TRAILING_STOP_PCT)
                pos['trailing_stop'] = new_trail
            # 2) Fire check (always — catches tokens that crash BELOW entry after a pump)
            if not exit_reason and pos.get('trailing_stop') is not None:
                if current_price <= pos['trailing_stop']:
                    exit_reason = 'TRAILING_STOP'

            # Dead coin: < 3 total transactions in last hour after 20+ min hold.
            # txns_h1=None means Dexscreener didn't return h1 data — skip to avoid false positives.
            if not exit_reason and mins_held >= DEAD_COIN_MIN_HOLD_MIN:
                txns_h1 = mdata.get('txns_h1')
                if txns_h1 is not None and txns_h1 < DEAD_COIN_MAX_TXNS_H1:
                    exit_reason = 'DEAD_COIN'

            # Time limit
            if not exit_reason and hours_held >= TIME_LIMIT_HOURS:
                exit_reason = 'TIME_LIMIT'

            if exit_reason:
                close_paper_position(pos, current_price, exit_reason, pnl_pct)
                changed = True

        if changed:
            save_positions(positions)


def close_paper_position(pos: Dict, exit_price: float, reason: str, pnl_pct: float):
    """Close a paper position."""
    pos['status'] = 'CLOSED'
    pos['exit_price'] = exit_price
    pos['exit_time'] = datetime.now().isoformat()
    pos['exit_reason'] = reason
    pos['pnl_pct'] = pnl_pct
    pos['pnl_usd'] = pos['size_usd'] * (pnl_pct / 100)

    entry_time = datetime.fromisoformat(pos['entry_time'])
    exit_time = datetime.fromisoformat(pos['exit_time'])
    peak_price = pos.get('peak_price', pos['entry_price'])

    pos['analytics'] = {
        'time_in_position_minutes': (exit_time - entry_time).total_seconds() / 60,
        'peak_gain_pct': ((peak_price / pos['entry_price']) - 1) * 100 if pos['entry_price'] > 0 else 0,
        'exit_from_peak_pct': ((exit_price / peak_price) - 1) * 100 if peak_price > 0 else 0,
        'trailing_stop_worked': reason == 'TRAILING_STOP',
    }

    # Update balance (thread-safe: exit_check_loop and evaluation_loop both call this)
    credit_paper_balance(pos['size_usd'] + pos['pnl_usd'])

    log_trade(pos, 'CLOSE', TRADES_LOG)
    emoji = '🎯' if pnl_pct > 0 else '❌'
    print(f"{emoji} Paper CLOSED {pos['contract'][:8]}... {reason}: {pnl_pct:+.1f}% (${pos['pnl_usd']:+.2f})")


def check_live_exits():
    """Check all open LIVE positions for exit conditions."""
    if not swap_executor:
        return

    positions = load_live_positions()
    open_contracts = [p['contract'] for p in positions if p['status'] == 'OPEN']
    if not open_contracts:
        return

    prices = batch_get_current_prices(open_contracts)
    if prices:
        print(f"💰 Live exit check: got prices for {len(prices)}/{len(open_contracts)} open positions")
    changed = False

    for pos in positions:
        if pos['status'] != 'OPEN':
            continue

        current_price = prices.get(pos['contract'])
        if not current_price:
            continue

        entry_price = pos['entry_price']
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600

        # Update entry price if placeholder
        if entry_price < 0.000001 and current_price > 0:
            pos['entry_price'] = current_price
            pos['initial_stop'] = current_price * HARD_STOP_PCT
            pos['peak_price'] = current_price
            entry_price = current_price
            changed = True

        # Update peak
        peak_price = pos.get('peak_price', entry_price)
        if current_price > peak_price:
            peak_price = current_price
            pos['peak_price'] = peak_price
            pos['peak_time'] = datetime.now().isoformat()
            changed = True

        pnl_pct = (current_price / entry_price - 1) * 100 if entry_price > 0 else 0
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
    """Close a LIVE position with real swap execution."""
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
        log_trade(pos, 'CLOSE', LIVE_TRADES_LOG)
        return

    # Execute sell (only if live trading enabled)
    if not LIVE_TRADING:
        print(f"📄 LIVE SELL skipped (paper mode): {contract[:8]}...")
        pos['status'] = 'CLOSED'
        pos['exit_reason'] = reason
        pos['exit_price'] = exit_price
        pos['exit_time'] = datetime.now().isoformat()
        pos['sol_received'] = 0
        pos['pnl_sol'] = -pos.get('sol_spent', 0)
        pos['tx_sell_sig'] = None
        log_trade(pos, 'CLOSE', LIVE_TRADES_LOG)
        return

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
    sol_received = details.get('out_amount', 0) / 1_000_000_000
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

    entry_time = datetime.fromisoformat(pos['entry_time'])
    exit_time = datetime.fromisoformat(pos['exit_time'])
    peak_price = pos.get('peak_price', pos['entry_price'])
    pos['analytics'] = {
        'time_in_position_minutes': (exit_time - entry_time).total_seconds() / 60,
        'peak_gain_pct': ((peak_price / pos['entry_price']) - 1) * 100 if pos['entry_price'] > 0 else 0,
        'exit_from_peak_pct': ((exit_price / peak_price) - 1) * 100 if peak_price > 0 else 0,
        'trailing_stop_worked': reason == 'TRAILING_STOP',
    }

    # Update live balance
    live_bal = get_live_balance()
    save_live_balance(live_bal + sol_received)

    log_trade(pos, 'CLOSE', LIVE_TRADES_LOG)
    emoji = '🎯' if sol_pnl > 0 else '❌'
    print(f"{emoji} LIVE CLOSED {contract[:8]}... {reason}: {sol_pnl:+.6f} SOL (${sol_pnl * SOL_PRICE_USD:+.2f})")


# ─── Async Main Loops ──────────────────────────────────────────────────

async def exit_check_loop():
    """Run exit checks every EXIT_CHECK_INTERVAL seconds."""
    while True:
        try:
            # Run blocking exit checks in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, check_paper_exits)
            await loop.run_in_executor(None, check_live_exits)
        except Exception as e:
            print(f"❌ Exit check error: {e}")
            traceback.print_exc()
        await asyncio.sleep(EXIT_CHECK_INTERVAL)


async def status_loop():
    """Print status every STATUS_INTERVAL seconds."""
    while True:
        await asyncio.sleep(STATUS_INTERVAL)
        try:
            paper_positions = load_positions()
            live_positions = load_live_positions()
            open_paper = len([p for p in paper_positions if p['status'] == 'OPEN'])
            open_live = len([p for p in live_positions if p['status'] == 'OPEN'])
            uptime_min = (datetime.now() - datetime.fromisoformat(stats['start_time'])).total_seconds() / 60

            print(f"\n📊 STATUS [{datetime.now().strftime('%H:%M:%S')}] "
                  f"uptime: {uptime_min:.0f}m | "
                  f"paper: {open_paper} open | live: {open_live} open | "
                  f"seen: {stats['tokens_seen']} | pending: {len(_pending)} | "
                  f"paper buys: {stats['buys_paper']} | skipped: {stats['buys_skipped']} | "
                  f"filtered: {stats['filtered_out']} | "
                  f"reconnects: {stats['ws_reconnects']}")
        except Exception as e:
            print(f"⚠️ Status print error: {e}")


async def evaluation_loop():
    """
    Every 60s, evaluate pending tokens that have aged past EVAL_DELAY_S.
    Fetch Dexscreener data and buy only tokens meeting volume/momentum thresholds.
    Discard tokens older than EVAL_TIMEOUT_S.

    ML finding (Apr 2026, 1,236 closed trades):
      - Buy-everything baseline: 14.5% win rate
      - score≥3 AND holders>150 filter:  35.1% win rate (+$9.94 on 94 trades)
    Proxy used here: Dexscreener volume_24h (all trading since launch) and
    priceChange.m5 as traction signals, since holder count requires rugcheck API.
    """
    while True:
        await asyncio.sleep(60)
        if not _pending:
            continue

        now = time.time()
        to_evaluate = [m for m, d in list(_pending.items())
                       if now - d['seen_at'] >= EVAL_DELAY_S]
        to_discard  = [m for m, d in list(_pending.items())
                       if now - d['seen_at'] >= EVAL_TIMEOUT_S]

        # Discard timed-out tokens first
        for mint in to_discard:
            entry = _pending.pop(mint, None)
            if entry:
                age_m = (now - entry['seen_at']) / 60
                print(f"  ⏭ EVAL timeout ({age_m:.0f}m): {entry['name']} ({entry['symbol']}) {mint[:12]}...")
                stats['filtered_out'] += 1

        if not to_evaluate:
            continue

        print(f"\n🔍 EVAL: checking {len(to_evaluate)} pending token(s)...")
        loop = asyncio.get_event_loop()
        try:
            dex_data = await loop.run_in_executor(
                None, batch_fetch_dexscreener, to_evaluate
            )
        except Exception as e:
            print(f"  ❌ EVAL Dexscreener error: {e}")
            continue

        for mint in to_evaluate:
            if mint not in _pending:
                continue  # already discarded above
            entry = _pending.pop(mint)
            pair = dex_data.get(mint, {})

            volume   = float((pair.get('volume') or {}).get('h24', 0) or 0)
            price_ch = float((pair.get('priceChange') or {}).get('m5', 0) or 0)
            liq      = float((pair.get('liquidity') or {}).get('usd', 0) or 0)
            age_m    = (now - entry['seen_at']) / 60

            # Volume branch: token has real traction AND is not already dumping
            # Momentum branch: strong upward price action alone qualifies
            vol_pass = volume >= EVAL_MIN_VOLUME and price_ch >= 0
            mom_pass = price_ch >= EVAL_MIN_PRICE_CHG
            passes = vol_pass or mom_pass
            filter_branch = 'volume' if vol_pass else 'momentum'

            if passes:
                print(f"  ✅ EVAL PASS  {entry['name']:20s}  vol=${volume:,.0f}  "
                      f"Δ5m={price_ch:+.1f}%  liq=${liq:,.0f}  age={age_m:.1f}m  [{filter_branch}]")
                try:
                    await loop.run_in_executor(
                        None, execute_buy, mint, entry['name'], entry['symbol'],
                        {'volume': volume, 'price_ch': price_ch, 'liq': liq,
                         'age_m': age_m, 'filter_branch': filter_branch}
                    )
                except Exception as e:
                    print(f"  ❌ EVAL buy error: {e}")
            else:
                print(f"  ❌ EVAL FAIL  {entry['name']:20s}  vol=${volume:,.0f}  "
                      f"Δ5m={price_ch:+.1f}%  liq=${liq:,.0f}  age={age_m:.1f}m  — skipped")
                stats['filtered_out'] += 1


async def ws_listener():
    """
    Connect to PumpPortal WebSocket, subscribe to new tokens, queue for evaluation.
    Reconnects with exponential backoff on disconnect.
    """
    delay = RECONNECT_BASE_DELAY

    while True:
        try:
            print(f"🔌 Connecting to PumpPortal WebSocket: {WS_URL}")
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:
                # Subscribe to new token events
                subscribe_msg = json.dumps({"method": "subscribeNewToken"})
                await ws.send(subscribe_msg)
                print("✅ Subscribed to subscribeNewToken")
                delay = RECONNECT_BASE_DELAY  # Reset backoff on successful connect

                async for raw_msg in ws:
                    try:
                        data = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    mint = data.get('mint')
                    if not mint:
                        continue  # Not a new token event

                    name = data.get('name', 'Unknown')
                    symbol = data.get('symbol', '???')
                    stats['tokens_seen'] += 1

                    # Log signal immediately
                    log_signal(mint, name, symbol)

                    # Buy immediately at launch — trailing stop handles all exits.
                    # _ever_queued prevents re-buying on WS reconnect.
                    if mint not in _ever_queued:
                        _ever_queued_add(mint)
                        print(f"  🚀 BUY AT LAUNCH: {name} ({symbol}) {mint[:16]}...")
                        loop = asyncio.get_event_loop()
                        def _buy_safe(m=mint, n=name, s=symbol):
                            try:
                                execute_buy(m, n, s)
                            except Exception as e:
                                print(f"  ❌ execute_buy exception [{n}]: {e}")
                        loop.run_in_executor(None, _buy_safe)

        except (websockets.ConnectionClosed, websockets.InvalidURI,
                websockets.InvalidHandshake, OSError, ConnectionError) as e:
            stats['ws_reconnects'] += 1
            print(f"⚠️ WebSocket disconnected: {e}")
            print(f"   Reconnecting in {delay}s... (attempt #{stats['ws_reconnects']})")
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

        except Exception as e:
            stats['ws_reconnects'] += 1
            print(f"❌ Unexpected WS error: {e}")
            traceback.print_exc()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)


async def main():
    """Main entry point — run WS listener + exit checker + status printer concurrently."""
    print(f"\n{'=' * 60}")
    print(f"🚀 Real-Time WebSocket Memecoin Scanner")
    print(f"   PumpPortal: {WS_URL}")
    print(f"   Mode: BUY AT LAUNCH — no eval delay, trailing stop exits only")
    print(f"   Live SOL/trade: {LIVE_SOL_AMOUNT}")
    print(f"   Trailing stop: {TRAILING_STOP_PCT * 100:.0f}% below peak | Hard stop: DISABLED")
    print(f"   Entry filter: NONE — buying every PumpPortal launch")
    print(f"   Exit check interval: {EXIT_CHECK_INTERVAL}s")
    print(f"   Max positions: {MAX_POSITIONS}")
    print(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    # Ensure dirs exist
    (BASE_DIR / 'logs').mkdir(exist_ok=True)
    (BASE_DIR / 'data').mkdir(exist_ok=True)

    # Init balance files if needed
    if not BALANCE_FILE.exists():
        save_paper_balance(PAPER_BALANCE_DEFAULT)
        print(f"💰 Initialized paper balance: ${PAPER_BALANCE_DEFAULT}")

    if not LIVE_BALANCE_FILE.exists():
        save_live_balance(0.0)
        print(f"🔴 Initialized live balance tracking")

    # Run loops concurrently (evaluation_loop removed — buying at launch now)
    await asyncio.gather(
        ws_listener(),
        exit_check_loop(),
        status_loop(),
    )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped by user")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
