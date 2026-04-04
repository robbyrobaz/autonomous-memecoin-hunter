#!/usr/bin/env python3
"""Check REAL current value of open positions"""
import json
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'
BALANCE_FILE = BASE_DIR / 'data' / 'balance.txt'

def get_current_price(contract):
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

# Load positions
with open(POSITIONS_FILE) as f:
    positions = json.load(f)

# Load cash balance
with open(BALANCE_FILE) as f:
    cash_balance = float(f.read().strip())

open_positions = [p for p in positions if p['status'] == 'OPEN']
closed_positions = [p for p in positions if p['status'] == 'CLOSED']

print("\n" + "="*90)
print("REAL PORTFOLIO VALUE")
print("="*90 + "\n")

print(f"💵 CASH BALANCE: ${cash_balance:.2f}")
print(f"\n📊 OPEN POSITIONS: {len(open_positions)}\n")

total_current_value = 0
total_entry_value = 0

for i, pos in enumerate(open_positions, 1):
    contract = pos['contract']
    entry_price = pos['entry_price']
    size_usd = pos['size_usd']
    
    current_price = get_current_price(contract)
    
    if current_price:
        # Calculate current value
        tokens = size_usd / entry_price
        current_value = tokens * current_price
        pnl_usd = current_value - size_usd
        pnl_pct = (current_price / entry_price - 1) * 100
        
        total_current_value += current_value
        total_entry_value += size_usd
        
        status = "🚀" if pnl_pct > 0 else "📉"
        print(f"{i}. {contract[:8]}...")
        print(f"   Entry: ${entry_price:.8f} | Current: ${current_price:.8f}")
        print(f"   Value: ${size_usd:.2f} → ${current_value:.2f} ({pnl_pct:+.1f}%)")
        print(f"   P&L: {status} ${pnl_usd:+.2f}")
        print()
    else:
        print(f"{i}. {contract[:8]}... - ❌ Can't fetch price (might be rugged)")
        print()

print("="*90)
print(f"💰 CASH: ${cash_balance:.2f}")
print(f"📦 POSITIONS ENTRY VALUE: ${total_entry_value:.2f}")
print(f"📈 POSITIONS CURRENT VALUE: ${total_current_value:.2f}")
print(f"📊 POSITIONS P&L: ${total_current_value - total_entry_value:+.2f}")
print(f"\n🏦 TOTAL PORTFOLIO VALUE: ${cash_balance + total_current_value:.2f}")
print(f"📉 TOTAL P&L: ${cash_balance + total_current_value - 100:.2f}")
print("="*90 + "\n")

# Closed trades summary
total_closed_pnl = sum(p.get('pnl_usd', 0) for p in closed_positions)
print(f"💀 CLOSED TRADES: {len(closed_positions)} trades, ${total_closed_pnl:.2f} P&L")
print()
