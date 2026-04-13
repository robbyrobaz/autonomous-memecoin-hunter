"""
Trailing Stop Backtest v2
=========================
Uses analytics fields from positions.json:
  - analytics.peak_gain_pct  : highest % gain seen during hold (30s resolution)
  - analytics.exit_from_peak : how far from peak the position closed
  - entry_price / exit_price / exit_reason

Key insight: price went entry → peak → exit. If a trailing stop of X% would fire
when price drops X% from peak, and we know the actual exit price was BELOW that
level, then the trailing stop WOULD have fired at peak*(1-X%) for that position.

This lets us correctly backtest any trailing stop % against real price path data.

Strategies tested
-----------------
Fixed:  5%, 8%, 10%, 12%(current), 15%, 20%, 25%, 30%
Tiered by peak gain (dynamic):
  tier_a: peak<20%→trail20%, peak<50%→trail15%, peak>50%→trail10%
  tier_b: peak<50%→trail25%, peak>50%→trail15%
  tier_c: moonshot — peak<100%→trail30%, peak>100%→trail15%
  tier_d: peak<10%→trail25%, peak<30%→trail15%, peak>30%→trail10%
Time-based:
  time_a: 0-10min→25%, 10-30min→15%, >30min→10%

For each closed position, simulate:
  1. If peak_gain >= trail_pct → trailing stop fires at peak*(1-trail)
     (price had to pass through that level on the way down)
  2. If peak_gain < trail_pct → trailing stop never fires; keep original exit
"""

import json
from pathlib import Path

POSITIONS_FILE = Path(__file__).parent / 'data' / 'positions.json'

print("Loading positions...", flush=True)
with open(POSITIONS_FILE) as f:
    all_positions = json.load(f)

closed = [p for p in all_positions
          if p.get('status') == 'CLOSED'
          and p.get('entry_price', 0) > 0
          and p.get('exit_price') is not None]

print(f"  {len(closed)} closed positions", flush=True)

# ── Strategy definitions ───────────────────────────────────────────────────────
# Each strategy is a function: (peak_gain_pct, hold_min) → trail_fraction

def fixed(pct):
    def fn(peak_gain_pct, hold_min): return pct
    return fn

# ── PREVIOUSLY TESTED: loose-early → tight-late ─────────────────────────────
# These all gave back too much before firing. Memecoins don't need room to breathe.

def tier_a(peak_gain_pct, hold_min):   # loose early, tighten with gains
    p = peak_gain_pct
    if p < 20:   return 0.20
    elif p < 50: return 0.15
    else:        return 0.10

def tier_b(peak_gain_pct, hold_min):
    return 0.25 if peak_gain_pct < 50 else 0.15

def tier_c(peak_gain_pct, hold_min):   # moonshot mode: very loose until 100%
    return 0.30 if peak_gain_pct < 100 else 0.15

def tier_d(peak_gain_pct, hold_min):
    p = peak_gain_pct
    if p < 10:   return 0.25
    elif p < 30: return 0.15
    else:        return 0.10

def time_a(peak_gain_pct, hold_min):   # loose in early minutes
    if hold_min <= 10:   return 0.25
    elif hold_min <= 30: return 0.15
    else:                return 0.10

# ── NEW: tight-early → loosen to let winners run ─────────────────────────────
# Hypothesis: memecoins pump fast. Lock in gains immediately.
# Once a token has proven itself (big gain), give it more room to moon further.

def dyn_let_run_a(peak_gain_pct, hold_min):
    """Tight early, loosen as gains grow — let moonshots breathe."""
    p = peak_gain_pct
    if p < 10:    return 0.08   # tiny move, capture fast
    elif p < 30:  return 0.10   # decent move, still tight
    elif p < 100: return 0.15   # real pump, give room
    else:         return 0.20   # moonshot, let it run

def dyn_let_run_b(peak_gain_pct, hold_min):
    """More aggressive let-run — tightest at start, loosest at big gains."""
    p = peak_gain_pct
    if p < 20:    return 0.07
    elif p < 50:  return 0.12
    elif p < 200: return 0.18
    else:         return 0.25   # 5-10x territory: trail 25% to capture max

def dyn_time_tight(peak_gain_pct, hold_min):
    """Time-based: tight in first 5 min (fast pumps), loosen after."""
    if hold_min <= 5:    return 0.07
    elif hold_min <= 15: return 0.10
    elif hold_min <= 60: return 0.15
    else:                return 0.20

def dyn_combo(peak_gain_pct, hold_min):
    """Combined: tight early by TIME and gain, loosen only on big gains."""
    p = peak_gain_pct
    if hold_min <= 5 and p < 20:  return 0.08   # very early + small: capture fast
    elif p < 15:                   return 0.10   # small gain: keep tight
    elif p < 50:                   return 0.12   # mid gain: normal
    elif p < 150:                  return 0.17   # large gain: let it breathe
    else:                          return 0.22   # mega: let it run

def dyn_stepped(peak_gain_pct, hold_min):
    """Step-wise: lock in floors as gains accumulate."""
    # At each tier, the stop locks in a meaningful profit floor
    p = peak_gain_pct
    if p < 5:     return 0.08   # near entry: capture anything
    elif p < 20:  return 0.10
    elif p < 50:  return 0.12
    elif p < 100: return 0.15
    elif p < 300: return 0.18
    else:         return 0.22

STRATEGIES = {
    'fixed_05':          fixed(0.05),
    'fixed_08':          fixed(0.08),
    'fixed_10':  fixed(0.10),
    'fixed_12':  fixed(0.12),   # current
    'fixed_15':  fixed(0.15),
    'fixed_20':  fixed(0.20),
    'fixed_25':  fixed(0.25),
    'fixed_30':  fixed(0.30),
    # Old dynamic (loose-early → tight-late) — kept for comparison
    'tier_a':          tier_a,
    'tier_b':          tier_b,
    'tier_c':          tier_c,
    'tier_d':          tier_d,
    'time_a':          time_a,
    # New dynamic (tight-early → let winners run)
    'dyn_let_run_a':   dyn_let_run_a,
    'dyn_let_run_b':   dyn_let_run_b,
    'dyn_time_tight':  dyn_time_tight,
    'dyn_combo':       dyn_combo,
    'dyn_stepped':     dyn_stepped,
}

# ── Simulate one position ──────────────────────────────────────────────────────

def simulate(pos, strategy_fn):
    entry  = pos['entry_price']
    exit_p = pos['exit_price']
    analytics = pos.get('analytics') or {}
    peak_gain_pct = analytics.get('peak_gain_pct', 0.0) or 0.0
    hold_min      = analytics.get('time_in_position_minutes', 0.0) or 0.0
    orig_reason   = pos.get('exit_reason', 'UNKNOWN')

    peak_price = entry * (1 + peak_gain_pct / 100)

    # Trailing stop level this strategy would set
    trail_pct = strategy_fn(peak_gain_pct, hold_min)
    trail_level = peak_price * (1 - trail_pct)

    # Did the trailing stop fire?
    # It fires if: price came down from peak AND passed through trail_level.
    # We know actual exit_price. If exit_price <= trail_level, the stop fires.
    # (Price had to cross trail_level on the way from peak to its exit price.)
    # If exit_price > trail_level: stop never reached (token still above stop).
    # If peak_gain_pct < trail_pct*100: stop level is below entry — never fires.

    trail_fires = (peak_gain_pct > 0) and (exit_p <= trail_level)

    if trail_fires:
        sim_exit_price  = trail_level
        sim_exit_reason = 'TRAILING_STOP'
    else:
        sim_exit_price  = exit_p
        sim_exit_reason = orig_reason

    sim_pnl_pct = (sim_exit_price - entry) / entry * 100

    return {
        'orig_reason':   orig_reason,
        'sim_reason':    sim_exit_reason,
        'orig_pnl_pct':  (exit_p - entry) / entry * 100,
        'sim_pnl_pct':   sim_pnl_pct,
        'peak_gain_pct': peak_gain_pct,
        'hold_min':      hold_min,
        'trail_pct':     trail_pct,
    }

# ── Run backtest ───────────────────────────────────────────────────────────────

print(f"\nSimulating {len(STRATEGIES)} strategies × {len(closed)} positions...\n", flush=True)

# For reference: real-world stats
real_ts  = [p for p in closed if p.get('exit_reason') == 'TRAILING_STOP']
real_sl  = [p for p in closed if p.get('exit_reason') == 'STOP_LOSS']
real_dc  = [p for p in closed if p.get('exit_reason') == 'DEAD_COIN']
real_tl  = [p for p in closed if p.get('exit_reason') == 'TIME_LIMIT']

def avg(xs): return sum(xs) / len(xs) if xs else 0

real_pnls = [(p['exit_price'] - p['entry_price']) / p['entry_price'] * 100 for p in closed]

print("── REAL WORLD (actual recorded results) ───────────────────────────────")
print(f"  TRAILING_STOP: {len(real_ts):4d}  WR=100%  avg={avg([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p in real_ts]):+.2f}%")
print(f"  STOP_LOSS:     {len(real_sl):4d}  WR=  0%  avg={avg([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p in real_sl]):+.2f}%")
print(f"  DEAD_COIN:     {len(real_dc):4d}         avg={avg([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p in real_dc]):+.2f}%")
print(f"  TIME_LIMIT:    {len(real_tl):4d}         avg={avg([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p in real_tl]):+.2f}%")
print(f"  TOTAL:         {len(closed):4d}         avg={avg(real_pnls):+.2f}%   total=${sum(real_pnls)/100:+.2f}")
print()

# Simulate each strategy
print("── SIMULATED RESULTS ──────────────────────────────────────────────────────────────────────")
print(f"{'Strategy':<12} {'N':>5} {'TotPnL$':>8} {'AvgPnL%':>8} {'TS_count':>9} {'TS_avg%':>8} "
      f"{'DC→TS':>7} {'SL→TS':>7} {'orig<sim':>8}")
print("-" * 100)

strategy_results = {}
for name, fn in STRATEGIES.items():
    sims = [simulate(p, fn) for p in closed]
    strategy_results[name] = sims

    total_pnl = sum(r['sim_pnl_pct'] for r in sims) / 100
    avg_pnl   = avg([r['sim_pnl_pct'] for r in sims])
    ts_sims   = [r for r in sims if r['sim_reason'] == 'TRAILING_STOP']
    ts_avg    = avg([r['sim_pnl_pct'] for r in ts_sims])

    # How many originally DEAD_COIN are now TRAILING_STOP?
    dc_to_ts = sum(1 for r in sims if r['orig_reason'] == 'DEAD_COIN' and r['sim_reason'] == 'TRAILING_STOP')
    sl_to_ts = sum(1 for r in sims if r['orig_reason'] == 'STOP_LOSS' and r['sim_reason'] == 'TRAILING_STOP')

    # How many improved vs worsened
    improved = sum(1 for r in sims if r['sim_pnl_pct'] > r['orig_pnl_pct'])

    marker = " ◀" if name == 'fixed_12' else ""
    print(f"{name:<12} {len(sims):>5} {total_pnl:>8.2f} {avg_pnl:>8.2f} "
          f"{len(ts_sims):>9} {ts_avg:>8.2f} {dc_to_ts:>7} {sl_to_ts:>7} {improved:>8}{marker}")

print()

# ── Peak gain distribution — what's actually available to capture ──────────────
peaks = [p.get('analytics', {}).get('peak_gain_pct', 0) or 0 for p in closed]
peaks_pos = sorted([x for x in peaks if x > 0], reverse=True)

print(f"── PEAK GAIN DISTRIBUTION (tokens that moved at all) ──────────────────")
print(f"  Total closed positions:            {len(closed)}")
print(f"  With ANY positive peak (>0%):      {len(peaks_pos)}  ({len(peaks_pos)/len(closed)*100:.1f}%)")

thresholds = [5, 10, 20, 30, 50, 100, 200, 500]
for t in thresholds:
    n = sum(1 for x in peaks if x >= t)
    print(f"  Peak >= {t:>4}%:  {n:>4}  ({n/len(closed)*100:4.1f}%)   avg_exit_pct_for_these: "
          f"{avg([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p,pk in zip(closed,peaks) if pk>=t]):+.1f}%")

print()
print(f"── HOW MUCH IS LEFT ON TABLE (DEAD_COIN exits with peak > 0) ────────────")
dc_with_peak = [(p, p.get('analytics', {}).get('peak_gain_pct', 0) or 0)
                for p in closed
                if p.get('exit_reason') == 'DEAD_COIN'
                and (p.get('analytics', {}).get('peak_gain_pct', 0) or 0) > 0]

dc_with_peak.sort(key=lambda x: -x[1])
print(f"  DEAD_COIN exits that had positive peak: {len(dc_with_peak)}")
peak_left = [(pk - (p['exit_price']-p['entry_price'])/p['entry_price']*100)
             for p, pk in dc_with_peak]
print(f"  Avg peak left on table: {avg(peak_left):+.1f}%")
print(f"  Median: {sorted(peak_left)[len(peak_left)//2]:+.1f}%")
print(f"  Top 20 DEAD_COIN by peak:")
for p, pk in dc_with_peak[:20]:
    name = p.get('market_data', {}).get('token_name', p['contract'][:12])
    exit_pct = (p['exit_price'] - p['entry_price']) / p['entry_price'] * 100
    print(f"    {name:30s}  peak={pk:+.1f}%  exit={exit_pct:+.1f}%  left={pk-exit_pct:+.1f}%")

print()
print(f"── TRAILING STOP SENSITIVITY: what does 12% vs tighter ACTUALLY do ────")
ts_real = [(p, p.get('analytics', {}).get('peak_gain_pct', 0) or 0,
            p.get('analytics', {}).get('exit_from_peak_pct', 0) or 0)
           for p in closed if p.get('exit_reason') == 'TRAILING_STOP']
print(f"  Real TRAILING_STOP exits: {len(ts_real)}")
exit_from_peaks = [ep for _, _, ep in ts_real]
print(f"  exit_from_peak avg: {avg(exit_from_peaks):+.2f}%  (should be ~-12%)")
print(f"  exit_from_peak min: {min(exit_from_peaks):+.2f}%")
print(f"  exit_from_peak max: {max(exit_from_peaks):+.2f}%")
peak_gains = [pk for _, pk, _ in ts_real]
print(f"  peak_gain avg for TS exits: {avg(peak_gains):+.2f}%")
print(f"  peak_gain median: {sorted(peak_gains)[len(peak_gains)//2]:+.2f}%")

# For tighter stop: how much would we have saved vs lost?
print(f"\n  Impact of tightening stop on TS winners:")
print(f"  {'trail':>8}  {'avg_exit%':>10}  {'total_pnl$':>12}  {'delta_vs_12%':>14}")
for trail in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]:
    sim_exits = []
    for p, pk, _ in ts_real:
        entry = p['entry_price']
        peak  = entry * (1 + pk / 100)
        sim_exit = peak * (1 - trail)
        sim_exits.append((sim_exit - entry) / entry * 100)
    total = sum(sim_exits) / 100
    a = avg(sim_exits)
    delta = total - (sum([(p['exit_price']-p['entry_price'])/p['entry_price']*100 for p,_,_ in ts_real])/100)
    marker = " ◀ current" if trail == 0.12 else ""
    print(f"  {trail:>8.0%}  {a:>10.2f}%  {total:>12.2f}  {delta:>+14.2f}{marker}")

print("\nDone.")
