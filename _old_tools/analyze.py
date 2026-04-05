#!/usr/bin/env python3
"""
Weekly Analyzer - Check if paper trading is profitable
Run this on Day 5 to decide if ready for live trading
"""

import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path(__file__).parent
TRADES_LOG = BASE_DIR / 'logs' / 'paper_trades.jsonl'
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'
BALANCE_FILE = BASE_DIR / 'data' / 'balance.txt'


def load_trades():
    """Load all trades from log"""
    trades = []
    if TRADES_LOG.exists():
        with open(TRADES_LOG) as f:
            for line in f:
                trades.append(json.loads(line))
    return trades


def load_positions():
    """Load positions file"""
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []


def main():
    print("\n" + "="*70)
    print("📊 AUTONOMOUS MEMECOIN HUNTER - PERFORMANCE ANALYSIS")
    print("="*70 + "\n")
    
    # Load data
    positions = load_positions()
    
    if not positions:
        print("❌ No trades found yet. Keep running!\n")
        return
    
    # Separate open vs closed
    open_positions = [p for p in positions if p['status'] == 'OPEN']
    closed_positions = [p for p in positions if p['status'] == 'CLOSED']
    
    # Current balance
    if BALANCE_FILE.exists():
        with open(BALANCE_FILE) as f:
            current_balance = float(f.read().strip())
    else:
        current_balance = 10000.0
    
    starting_balance = 10000.0
    total_pnl = current_balance - starting_balance
    total_pnl_pct = (total_pnl / starting_balance) * 100
    
    print(f"💰 BALANCE:")
    print(f"   Starting: ${starting_balance:,.2f}")
    print(f"   Current:  ${current_balance:,.2f}")
    print(f"   P&L:      ${total_pnl:+,.2f} ({total_pnl_pct:+.1f}%)")
    print()
    
    print(f"📈 POSITIONS:")
    print(f"   Open:   {len(open_positions)}")
    print(f"   Closed: {len(closed_positions)}")
    print(f"   Total:  {len(positions)}")
    print()
    
    if not closed_positions:
        print("⏳ No closed positions yet. Need more time to collect data.\n")
        return
    
    # Analyze closed positions
    winners = [p for p in closed_positions if p.get('pnl_usd', 0) > 0]
    losers = [p for p in closed_positions if p.get('pnl_usd', 0) <= 0]
    
    win_rate = len(winners) / len(closed_positions) * 100
    
    # Targets hit
    target_hits = [p for p in closed_positions if p.get('exit_reason') == 'TARGET_HIT']
    target_hit_rate = len(target_hits) / len(closed_positions) * 100
    
    # Avg time to target
    target_times = []
    for p in target_hits:
        entry = datetime.fromisoformat(p['entry_time'])
        exit_time = datetime.fromisoformat(p['exit_time'])
        hours = (exit_time - entry).total_seconds() / 3600
        target_times.append(hours)
    
    avg_time_to_target = sum(target_times) / len(target_times) if target_times else 0
    
    print(f"✅ WIN RATE: {win_rate:.1f}% ({len(winners)}/{len(closed_positions)})")
    print(f"🎯 TARGET HIT RATE: {target_hit_rate:.1f}% ({len(target_hits)} hit 2x)")
    if target_times:
        print(f"⏱️  AVG TIME TO 2X: {avg_time_to_target:.1f} hours")
    print()
    
    # Breakdown by exit reason
    by_reason = defaultdict(int)
    for p in closed_positions:
        by_reason[p.get('exit_reason', 'UNKNOWN')] += 1
    
    print(f"📋 EXIT REASONS:")
    for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        pct = count / len(closed_positions) * 100
        print(f"   {reason:15s}: {count:3d} ({pct:5.1f}%)")
    print()
    
    # Breakdown by channel
    by_channel = defaultdict(lambda: {'trades': 0, 'wins': 0, 'targets': 0, 'pnl': 0})
    for p in closed_positions:
        channel = p.get('signal_data', {}).get('channel', 'UNKNOWN')
        by_channel[channel]['trades'] += 1
        if p.get('pnl_usd', 0) > 0:
            by_channel[channel]['wins'] += 1
        if p.get('exit_reason') == 'TARGET_HIT':
            by_channel[channel]['targets'] += 1
        by_channel[channel]['pnl'] += p.get('pnl_usd', 0)
    
    print(f"📡 PERFORMANCE BY CHANNEL:")
    print(f"   {'Channel':20s} {'Trades':>7s} {'Win%':>7s} {'2x%':>7s} {'P&L':>12s}")
    print(f"   {'-'*60}")
    
    for channel in sorted(by_channel.keys(), key=lambda c: by_channel[c]['pnl'], reverse=True):
        stats = by_channel[channel]
        win_pct = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        target_pct = (stats['targets'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        print(f"   {channel:20s} {stats['trades']:7d} {win_pct:6.1f}% {target_pct:6.1f}% ${stats['pnl']:+10.2f}")
    
    print()
    
    # Largest win/loss
    if winners:
        best = max(winners, key=lambda p: p.get('pnl_usd', 0))
        print(f"🏆 BEST TRADE: {best['contract'][:8]}... +${best.get('pnl_usd', 0):.2f} ({best.get('pnl_pct', 0):+.1f}%)")
    
    if losers:
        worst = min(losers, key=lambda p: p.get('pnl_usd', 0))
        print(f"💀 WORST TRADE: {worst['contract'][:8]}... ${worst.get('pnl_usd', 0):.2f} ({worst.get('pnl_pct', 0):+.1f}%)")
    
    print()
    
    # Decision
    print("="*70)
    print("🔮 DECISION:")
    print("="*70)
    
    if len(closed_positions) < 50:
        print(f"⏳ NEED MORE DATA - Only {len(closed_positions)} closed trades")
        print(f"   Keep running until 50+ trades collected")
    elif win_rate >= 55 and target_hit_rate >= 30:
        print(f"✅ PROVEN STRATEGY - READY FOR LIVE TRADING")
        print(f"   Win rate: {win_rate:.1f}% (target: ≥55%)")
        print(f"   2x hit rate: {target_hit_rate:.1f}% (target: ≥30%)")
        print(f"   Total P&L: ${total_pnl:+,.2f}")
        print(f"\n   👉 Next step: Fund Phantom wallet with $100 and go live!")
    elif win_rate < 45 or target_hit_rate < 20:
        print(f"❌ FAILING - Strategy needs adjustment")
        print(f"   Win rate: {win_rate:.1f}% (need: ≥55%)")
        print(f"   2x hit rate: {target_hit_rate:.1f}% (need: ≥30%)")
        print(f"\n   👉 Need to improve signal detection or safety filters")
    else:
        print(f"🤔 INCONCLUSIVE - Performance is marginal")
        print(f"   Win rate: {win_rate:.1f}%")
        print(f"   2x hit rate: {target_hit_rate:.1f}%")
        print(f"\n   👉 Collect more data or adjust strategy")
    
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
