#!/usr/bin/env python3
"""
Full ML/statistical analysis of memecoin paper trading dataset.
"""

import json
import math
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

# ── Load all CLOSE records ──────────────────────────────────────────────────
TRADES_FILE = "/home/rob/.openclaw/workspace/autonomous-memecoin-hunter/logs/paper_trades.jsonl"
SNAPSHOTS_FILE = "/home/rob/.openclaw/workspace/autonomous-memecoin-hunter/data/price_snapshots.jsonl"

closes = []
with open(TRADES_FILE) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("action") == "CLOSE":
            closes.append(rec)

print(f"Total CLOSE records: {len(closes)}")

# ── Build flat feature table ─────────────────────────────────────────────────
rows = []
for r in closes:
    analytics = r.get("analytics", {})
    entry_metrics = r.get("entry_metrics", {})
    signal_data = r.get("signal_data", {})
    market_data = r.get("market_data", {})

    entry_price = r.get("entry_price", 0)
    entry_time_str = r.get("entry_time") or r.get("timestamp")
    try:
        entry_dt = datetime.fromisoformat(entry_time_str)
        hour_utc = entry_dt.hour
    except Exception:
        hour_utc = -1

    pnl_usd = r.get("pnl_usd", 0)
    pnl_pct = r.get("pnl_pct", 0)

    rows.append({
        "contract": r.get("contract", ""),
        "entry_price": entry_price,
        "log_entry_price": math.log10(entry_price) if entry_price and entry_price > 0 else None,
        "exit_price": r.get("exit_price", 0),
        "exit_reason": r.get("exit_reason", "UNKNOWN"),
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "win": 1 if pnl_usd > 0 else 0,
        "hour_utc": hour_utc,
        "time_in_position_minutes": analytics.get("time_in_position_minutes", 0),
        "peak_gain_pct": analytics.get("peak_gain_pct", 0),
        "exit_from_peak_pct": analytics.get("exit_from_peak_pct", 0),
        "trailing_stop_worked": analytics.get("trailing_stop_worked", False),
        "hit_stop_loss": analytics.get("hit_stop_loss", False),
        "time_to_peak_minutes": analytics.get("time_to_peak_minutes", 0),
        "liquidity": entry_metrics.get("liquidity", 0),
        "volume_24h": entry_metrics.get("volume_24h", 0) or market_data.get("volume_24h", 0),
        "rugcheck_score": entry_metrics.get("rugcheck_score", 0) or signal_data.get("rugcheck_score", 0),
        "holder_count": entry_metrics.get("holder_count", 0),
        "age_hours": entry_metrics.get("age_hours", 0),
        "signal_score": signal_data.get("score", 0),
        "channel": signal_data.get("channel", ""),
        "entry_time_str": entry_time_str,
    })

# Convert to numpy-friendly structure
wins = [r for r in rows if r["win"] == 1]
losses = [r for r in rows if r["win"] == 0]

print(f"\n{'='*60}")
print(f"STEP 1: DATASET OVERVIEW")
print(f"{'='*60}")
print(f"Total closed trades: {len(rows)}")
print(f"Winners: {len(wins)} ({100*len(wins)/len(rows):.1f}%)")
print(f"Losers:  {len(losses)} ({100*len(losses)/len(rows):.1f}%)")
total_pnl = sum(r["pnl_usd"] for r in rows)
print(f"Total PnL: ${total_pnl:.2f}")
print(f"Avg PnL per trade: ${total_pnl/len(rows):.4f}")

# ── STEP 2: Basic Statistics ─────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"STEP 2: PnL DISTRIBUTION")
print(f"{'='*60}")

pnl_pcts = [r["pnl_pct"] for r in rows]
win_pnl_pcts = [r["pnl_pct"] for r in wins]
loss_pnl_pcts = [r["pnl_pct"] for r in losses]

print(f"\nAll trades pnl_pct:")
print(f"  Min:    {min(pnl_pcts):.1f}%")
print(f"  Max:    {max(pnl_pcts):.1f}%")
print(f"  Mean:   {np.mean(pnl_pcts):.1f}%")
print(f"  Median: {np.median(pnl_pcts):.1f}%")
print(f"  Std:    {np.std(pnl_pcts):.1f}%")

print(f"\nWinners pnl_pct:")
if win_pnl_pcts:
    print(f"  Min:    {min(win_pnl_pcts):.1f}%")
    print(f"  Max:    {max(win_pnl_pcts):.1f}%")
    print(f"  Mean:   {np.mean(win_pnl_pcts):.1f}%")
    print(f"  Median: {np.median(win_pnl_pcts):.1f}%")
    pct_10x = sum(1 for x in win_pnl_pcts if x >= 900)/len(win_pnl_pcts)*100
    pct_5x  = sum(1 for x in win_pnl_pcts if x >= 400)/len(win_pnl_pcts)*100
    pct_2x  = sum(1 for x in win_pnl_pcts if x >= 100)/len(win_pnl_pcts)*100
    print(f"  Winners that are 10x+ (>=900%): {pct_10x:.1f}%")
    print(f"  Winners that are 5x+  (>=400%): {pct_5x:.1f}%")
    print(f"  Winners that are 2x+  (>=100%): {pct_2x:.1f}%")

print(f"\nLosers pnl_pct:")
if loss_pnl_pcts:
    print(f"  Min:    {min(loss_pnl_pcts):.1f}%")
    print(f"  Max:    {max(loss_pnl_pcts):.1f}%")
    print(f"  Mean:   {np.mean(loss_pnl_pcts):.1f}%")
    print(f"  Median: {np.median(loss_pnl_pcts):.1f}%")
    pct_90down = sum(1 for x in loss_pnl_pcts if x <= -90)/len(loss_pnl_pcts)*100
    pct_50down = sum(1 for x in loss_pnl_pcts if x <= -50)/len(loss_pnl_pcts)*100
    print(f"  Losses of -90% or worse: {pct_90down:.1f}%")
    print(f"  Losses of -50% or worse: {pct_50down:.1f}%")

# PnL buckets
print(f"\nPnL buckets (all trades):")
buckets = [
    ("<-90%",    lambda x: x < -90),
    ("-90 to -50%", lambda x: -90 <= x < -50),
    ("-50 to -20%", lambda x: -50 <= x < -20),
    ("-20 to 0%",   lambda x: -20 <= x < 0),
    ("0 to 50%",    lambda x: 0 <= x < 50),
    ("50 to 100%",  lambda x: 50 <= x < 100),
    ("100 to 500%", lambda x: 100 <= x < 500),
    ("500%+",       lambda x: x >= 500),
]
for label, fn in buckets:
    count = sum(1 for r in rows if fn(r["pnl_pct"]))
    print(f"  {label:20s}: {count:5d} ({100*count/len(rows):.1f}%)")

# ── Exit reason breakdown ────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"EXIT REASON BREAKDOWN")
print(f"{'='*60}")
by_reason = defaultdict(list)
for r in rows:
    by_reason[r["exit_reason"]].append(r)

for reason, group in sorted(by_reason.items()):
    win_count = sum(1 for r in group if r["win"])
    mean_pnl = np.mean([r["pnl_usd"] for r in group])
    mean_pct = np.mean([r["pnl_pct"] for r in group])
    print(f"  {reason:20s}: n={len(group):4d}, win%={100*win_count/len(group):5.1f}%, "
          f"avg_pnl=${mean_pnl:.4f}, avg_pct={mean_pct:.1f}%")

# ── Peak gain analysis ───────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"PEAK GAIN ANALYSIS")
print(f"{'='*60}")
peak_gains = [r["peak_gain_pct"] for r in rows]
win_peaks  = [r["peak_gain_pct"] for r in wins]
loss_peaks = [r["peak_gain_pct"] for r in losses]

print(f"Trades that peaked >50% but ended as loss: {sum(1 for r in losses if r['peak_gain_pct'] > 50)}")
print(f"Trades that peaked >100% but ended as loss: {sum(1 for r in losses if r['peak_gain_pct'] > 100)}")
print(f"Trades that peaked >200% but ended as loss: {sum(1 for r in losses if r['peak_gain_pct'] > 200)}")
print(f"Winners avg peak: {np.mean(win_peaks):.1f}%,  Losers avg peak: {np.mean(loss_peaks):.1f}%")
print(f"Winners exit_from_peak avg: {np.mean([r['exit_from_peak_pct'] for r in wins]):.1f}%")
print(f"Losers  exit_from_peak avg: {np.mean([r['exit_from_peak_pct'] for r in losses]):.1f}%")

# ── Time in position ─────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"TIME IN POSITION ANALYSIS")
print(f"{'='*60}")
win_times  = [r["time_in_position_minutes"] for r in wins]
loss_times = [r["time_in_position_minutes"] for r in losses]
print(f"Winners  avg time: {np.mean(win_times):.1f} min, median: {np.median(win_times):.1f} min")
print(f"Losers   avg time: {np.mean(loss_times):.1f} min, median: {np.median(loss_times):.1f} min")

# Fast trades (<30 min)
fast = [r for r in rows if r["time_in_position_minutes"] < 30]
slow = [r for r in rows if r["time_in_position_minutes"] >= 30]
print(f"\nFast trades (<30 min): n={len(fast)}, win%={100*sum(r['win'] for r in fast)/max(len(fast),1):.1f}%")
print(f"Slow trades (>=30 min): n={len(slow)}, win%={100*sum(r['win'] for r in slow)/max(len(slow),1):.1f}%")

# ── STEP 3: Feature analysis ──────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"STEP 3: FEATURE ANALYSIS")
print(f"{'='*60}")

# Entry price
ep_valid = [r for r in rows if r["log_entry_price"] is not None]
print(f"\nEntry price non-null: {len(ep_valid)}")
win_ep  = [r["log_entry_price"] for r in ep_valid if r["win"]]
loss_ep = [r["log_entry_price"] for r in ep_valid if not r["win"]]
if win_ep and loss_ep:
    print(f"Winners  avg log10(entry_price): {np.mean(win_ep):.3f}  (entry ~{10**np.mean(win_ep):.2e})")
    print(f"Losers   avg log10(entry_price): {np.mean(loss_ep):.3f}  (entry ~{10**np.mean(loss_ep):.2e})")

# Entry price quantile analysis
log_eps = sorted(r["log_entry_price"] for r in ep_valid)
q1 = np.percentile(log_eps, 25)
q2 = np.percentile(log_eps, 50)
q3 = np.percentile(log_eps, 75)
print(f"\nEntry price quartiles (log10): Q1={q1:.2f}, Q2={q2:.2f}, Q3={q3:.2f}")
print(f"  => Q1~{10**q1:.2e}, Q2~{10**q2:.2e}, Q3~{10**q3:.2e}")

quartile_groups = [
    ("Q1 (cheapest)",  lambda r: r["log_entry_price"] <= q1),
    ("Q2",             lambda r: q1 < r["log_entry_price"] <= q2),
    ("Q3",             lambda r: q2 < r["log_entry_price"] <= q3),
    ("Q4 (costliest)", lambda r: r["log_entry_price"] > q3),
]
print(f"\nWin rate by entry price quartile:")
for label, fn in quartile_groups:
    group = [r for r in ep_valid if fn(r)]
    if group:
        wr = 100*sum(r["win"] for r in group)/len(group)
        avg_pnl = np.mean([r["pnl_usd"] for r in group])
        print(f"  {label:20s}: n={len(group):4d}, win%={wr:.1f}%, avg_pnl=${avg_pnl:.4f}")

# Time of day
print(f"\nWin rate by hour UTC:")
hour_stats = defaultdict(list)
for r in rows:
    if r["hour_utc"] >= 0:
        hour_stats[r["hour_utc"]].append(r)
for h in sorted(hour_stats):
    group = hour_stats[h]
    wr = 100*sum(r["win"] for r in group)/len(group)
    avg_pnl = np.mean([r["pnl_usd"] for r in group])
    print(f"  Hour {h:2d}:00 UTC: n={len(group):4d}, win%={wr:5.1f}%, avg_pnl=${avg_pnl:.4f}")

# Signal score
print(f"\nWin rate by signal_score:")
score_stats = defaultdict(list)
for r in rows:
    score_stats[r["signal_score"]].append(r)
for s in sorted(score_stats):
    group = score_stats[s]
    wr = 100*sum(r["win"] for r in group)/len(group)
    avg_pnl = np.mean([r["pnl_usd"] for r in group])
    print(f"  Score {s}: n={len(group):4d}, win%={wr:.1f}%, avg_pnl=${avg_pnl:.4f}")

# Rugcheck score
rc_valid = [r for r in rows if r["rugcheck_score"] > 0]
print(f"\nRugcheck score non-zero: {len(rc_valid)}")
if rc_valid:
    rc_vals = sorted(r["rugcheck_score"] for r in rc_valid)
    rc_q2 = np.percentile(rc_vals, 50)
    rc_q3 = np.percentile(rc_vals, 75)
    low_rc  = [r for r in rc_valid if r["rugcheck_score"] <= rc_q2]
    high_rc = [r for r in rc_valid if r["rugcheck_score"] > rc_q2]
    print(f"  Low rugcheck  (<=median {rc_q2:.0f}): n={len(low_rc)}, win%={100*sum(r['win'] for r in low_rc)/max(len(low_rc),1):.1f}%")
    print(f"  High rugcheck (>median  {rc_q2:.0f}): n={len(high_rc)}, win%={100*sum(r['win'] for r in high_rc)/max(len(high_rc),1):.1f}%")

# Volume
vol_valid = [r for r in rows if r["volume_24h"] > 0]
print(f"\nVolume_24h non-zero: {len(vol_valid)}")
if vol_valid:
    vols = sorted(r["volume_24h"] for r in vol_valid)
    v_med = np.median(vols)
    low_vol  = [r for r in vol_valid if r["volume_24h"] <= v_med]
    high_vol = [r for r in vol_valid if r["volume_24h"] > v_med]
    print(f"  Low vol  (<=median ${v_med:.0f}): n={len(low_vol)}, win%={100*sum(r['win'] for r in low_vol)/max(len(low_vol),1):.1f}%")
    print(f"  High vol (>median  ${v_med:.0f}): n={len(high_vol)}, win%={100*sum(r['win'] for r in high_vol)/max(len(high_vol),1):.1f}%")

# Age
age_valid = [r for r in rows if r["age_hours"] > 0]
print(f"\nAge non-zero: {len(age_valid)}")
if age_valid:
    ages = [r["age_hours"] for r in age_valid]
    a_med = np.median(ages)
    young = [r for r in age_valid if r["age_hours"] <= a_med]
    old   = [r for r in age_valid if r["age_hours"] > a_med]
    print(f"  Young (<=median {a_med:.3f}h): n={len(young)}, win%={100*sum(r['win'] for r in young)/max(len(young),1):.1f}%")
    print(f"  Old   (>median  {a_med:.3f}h): n={len(old)}, win%={100*sum(r['win'] for r in old)/max(len(old),1):.1f}%")

# ── STEP 4: ML Classification ─────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"STEP 4: ML CLASSIFICATION")
print(f"{'='*60}")

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    import warnings
    warnings.filterwarnings("ignore")

    # Build feature matrix
    # Use features that are available in most records
    feature_names = [
        "log_entry_price",
        "hour_utc",
        "signal_score",
        "age_hours",
        "volume_24h_log",
        "rugcheck_score_norm",
        "liquidity_log",
    ]

    def build_X_y(records):
        X_rows = []
        y_rows = []
        for r in records:
            lep = r["log_entry_price"] if r["log_entry_price"] is not None else 0
            hour = r["hour_utc"] if r["hour_utc"] >= 0 else 12
            sscore = r["signal_score"]
            age = r["age_hours"]
            vol = math.log10(r["volume_24h"] + 1)
            rc = r["rugcheck_score"] / 100000.0
            liq = math.log10(r["liquidity"] + 1)
            X_rows.append([lep, hour, sscore, age, vol, rc, liq])
            y_rows.append(r["win"])
        return np.array(X_rows, dtype=float), np.array(y_rows)

    X, y = build_X_y(rows)
    print(f"\nFeature matrix shape: {X.shape}")
    print(f"Positive rate (win): {y.mean():.3f} ({100*y.mean():.1f}%)")
    print(f"Baseline accuracy (predict all-lose): {(1-y.mean()):.3f} ({100*(1-y.mean()):.1f}%)")

    # Check feature variance
    print(f"\nFeature std devs:")
    for i, name in enumerate(feature_names):
        print(f"  {name:30s}: std={X[:,i].std():.4f}, mean={X[:,i].mean():.4f}")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # 1. Logistic Regression
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    lr = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    lr_scores = cross_val_score(lr, X_scaled, y, cv=cv, scoring="accuracy")
    lr_roc = cross_val_score(lr, X_scaled, y, cv=cv, scoring="roc_auc")
    print(f"\nLogistic Regression:")
    print(f"  Accuracy: {lr_scores.mean():.3f} +/- {lr_scores.std():.3f}")
    print(f"  ROC-AUC:  {lr_roc.mean():.3f} +/- {lr_roc.std():.3f}")

    # Fit once to get coefficients
    lr.fit(X_scaled, y)
    print(f"  Coefficients:")
    for name, coef in zip(feature_names, lr.coef_[0]):
        print(f"    {name:30s}: {coef:.4f}")

    # 2. Random Forest
    rf = RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                 max_depth=5, random_state=42, n_jobs=-1)
    rf_scores = cross_val_score(rf, X, y, cv=cv, scoring="accuracy")
    rf_roc = cross_val_score(rf, X, y, cv=cv, scoring="roc_auc")
    print(f"\nRandom Forest:")
    print(f"  Accuracy: {rf_scores.mean():.3f} +/- {rf_scores.std():.3f}")
    print(f"  ROC-AUC:  {rf_roc.mean():.3f} +/- {rf_roc.std():.3f}")

    rf.fit(X, y)
    print(f"  Feature importances:")
    for name, imp in sorted(zip(feature_names, rf.feature_importances_), key=lambda x: -x[1]):
        print(f"    {name:30s}: {imp:.4f}")

    # 3. Gradient Boosting
    gb = GradientBoostingClassifier(n_estimators=100, max_depth=3,
                                     learning_rate=0.1, random_state=42)
    gb_scores = cross_val_score(gb, X, y, cv=cv, scoring="accuracy")
    gb_roc = cross_val_score(gb, X, y, cv=cv, scoring="roc_auc")
    print(f"\nGradient Boosting:")
    print(f"  Accuracy: {gb_scores.mean():.3f} +/- {gb_scores.std():.3f}")
    print(f"  ROC-AUC:  {gb_roc.mean():.3f} +/- {gb_roc.std():.3f}")

    # Try with ONLY entry_price and hour (the most reliable features)
    print(f"\n--- Reduced model (entry_price + hour only) ---")
    X2 = X[:, :2]  # log_entry_price, hour_utc
    X2_scaled = StandardScaler().fit_transform(X2)
    lr2 = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    lr2_scores = cross_val_score(lr2, X2_scaled, y, cv=cv, scoring="accuracy")
    lr2_roc = cross_val_score(lr2, X2_scaled, y, cv=cv, scoring="roc_auc")
    print(f"  LR Accuracy: {lr2_scores.mean():.3f}, ROC-AUC: {lr2_roc.mean():.3f}")

except ImportError as e:
    print(f"sklearn not available: {e}")

# ── STEP 5: Price snapshot enrichment ────────────────────────────────────────
print(f"\n{'='*60}")
print(f"STEP 5: PRICE SNAPSHOT ENRICHMENT")
print(f"{'='*60}")

# Build a dict: contract -> sorted list of (timestamp, snapshot)
print("Loading price snapshots (this may take a moment for 3M lines)...")
snap_by_contract = defaultdict(list)
with open(SNAPSHOTS_FILE) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            s = json.loads(line)
            snap_by_contract[s["contract"]].append(s)
        except Exception:
            pass

print(f"Unique contracts in snapshots: {len(snap_by_contract)}")

# For each closed trade, find the earliest snapshot AFTER open
trade_contracts = set(r["contract"] for r in rows)
matched = 0
snapshot_features = []

for r in rows:
    contract = r["contract"]
    if contract not in snap_by_contract:
        continue
    snaps = snap_by_contract[contract]
    # Sort by timestamp
    snaps_sorted = sorted(snaps, key=lambda s: s["timestamp"])
    entry_time_str = r["entry_time_str"]
    try:
        entry_dt = datetime.fromisoformat(entry_time_str.replace("Z",""))
    except Exception:
        continue

    # Find first snapshot after entry
    after_snaps = [s for s in snaps_sorted
                   if s["timestamp"] > entry_time_str]
    if not after_snaps:
        continue
    first_snap = after_snaps[0]

    # Calculate minutes after entry
    try:
        snap_dt = datetime.fromisoformat(first_snap["timestamp"].replace("Z",""))
        mins_after = (snap_dt - entry_dt).total_seconds() / 60
    except Exception:
        continue

    if mins_after > 30:
        continue  # only use early snapshots

    price_at_snap = first_snap.get("price_usd", 0)
    if price_at_snap and r["entry_price"] and r["entry_price"] > 0:
        pct_change_at_snap = 100 * (price_at_snap - r["entry_price"]) / r["entry_price"]
    else:
        pct_change_at_snap = 0

    snapshot_features.append({
        "contract": contract,
        "win": r["win"],
        "pnl_usd": r["pnl_usd"],
        "pnl_pct": r["pnl_pct"],
        "mins_after_entry": mins_after,
        "price_change_at_snap_pct": pct_change_at_snap,
        "snap_liquidity": first_snap.get("liquidity_usd", 0),
        "snap_volume": first_snap.get("volume_24h", 0),
        "snap_price_change_5m": first_snap.get("price_change_5m", 0),
    })
    matched += 1

print(f"Trades with early snapshot (<30 min after entry): {matched}")
print(f"Coverage: {100*matched/len(rows):.1f}%")

if snapshot_features:
    snap_wins   = [s for s in snapshot_features if s["win"]]
    snap_losses = [s for s in snapshot_features if not s["win"]]

    print(f"\nAmong matched trades: {len(snap_wins)} wins, {len(snap_losses)} losses")
    print(f"Win rate: {100*len(snap_wins)/len(snapshot_features):.1f}%")

    if snap_wins:
        print(f"\nPrice change at first snapshot:")
        print(f"  Winners avg: {np.mean([s['price_change_at_snap_pct'] for s in snap_wins]):.1f}%")
        print(f"  Losers  avg: {np.mean([s['price_change_at_snap_pct'] for s in snap_losses]):.1f}%")

    # Split by early momentum: is early price up or down?
    pos_momentum = [s for s in snapshot_features if s["price_change_at_snap_pct"] > 0]
    neg_momentum = [s for s in snapshot_features if s["price_change_at_snap_pct"] <= 0]
    print(f"\nEarly momentum >0: n={len(pos_momentum)}, win%={100*sum(s['win'] for s in pos_momentum)/max(len(pos_momentum),1):.1f}%")
    print(f"Early momentum <=0: n={len(neg_momentum)}, win%={100*sum(s['win'] for s in neg_momentum)/max(len(neg_momentum),1):.1f}%")

    # Strong early momentum
    strong_pos = [s for s in snapshot_features if s["price_change_at_snap_pct"] > 20]
    strong_neg = [s for s in snapshot_features if s["price_change_at_snap_pct"] < -20]
    print(f"Early momentum >20%: n={len(strong_pos)}, win%={100*sum(s['win'] for s in strong_pos)/max(len(strong_pos),1):.1f}%")
    print(f"Early momentum <-20%: n={len(strong_neg)}, win%={100*sum(s['win'] for s in strong_neg)/max(len(strong_neg),1):.1f}%")

    # ML with snapshot feature
    try:
        print(f"\n--- ML with early snapshot price change ---")
        X_snap = np.array([[
            s.get("price_change_at_snap_pct", 0),
            math.log10(max(s["snap_liquidity"], 1)),
            s["snap_price_change_5m"],
        ] for s in snapshot_features])
        y_snap = np.array([s["win"] for s in snapshot_features])
        X_snap_scaled = StandardScaler().fit_transform(X_snap)

        cv2 = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        rf_snap = RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                          max_depth=4, random_state=42)
        rf_snap_scores = cross_val_score(rf_snap, X_snap_scaled, y_snap, cv=cv2, scoring="accuracy")
        rf_snap_roc = cross_val_score(rf_snap, X_snap_scaled, y_snap, cv=cv2, scoring="roc_auc")
        print(f"  RF Accuracy: {rf_snap_scores.mean():.3f}, ROC-AUC: {rf_snap_roc.mean():.3f}")
        print(f"  Baseline:    {1-y_snap.mean():.3f}")
    except Exception as e:
        print(f"  Error: {e}")

# ── STEP 6: Actionable filters ───────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"STEP 6: FILTER BACKTESTS")
print(f"{'='*60}")

# Try various filters and compute win rate + expected value
def backtest_filter(name, subset):
    n = len(subset)
    if n == 0:
        print(f"  {name}: no trades")
        return
    wr = 100 * sum(r["win"] for r in subset) / n
    avg_pnl = np.mean([r["pnl_usd"] for r in subset])
    total_pnl = sum(r["pnl_usd"] for r in subset)
    pct_kept = 100 * n / len(rows)
    print(f"  {name}: n={n:4d} ({pct_kept:4.1f}% of trades), "
          f"win%={wr:5.1f}%, avg_pnl=${avg_pnl:.4f}, total_pnl=${total_pnl:.2f}")

print(f"\nBaseline (all trades): n={len(rows)}, win%={100*sum(r['win'] for r in rows)/len(rows):.1f}%")

# Entry price filters
ep_rows = [r for r in rows if r["log_entry_price"] is not None]
backtest_filter("entry_price < 1e-6", [r for r in ep_rows if r["entry_price"] < 1e-6])
backtest_filter("entry_price 1e-6 to 1e-5", [r for r in ep_rows if 1e-6 <= r["entry_price"] < 1e-5])
backtest_filter("entry_price 1e-5 to 1e-4", [r for r in ep_rows if 1e-5 <= r["entry_price"] < 1e-4])
backtest_filter("entry_price > 1e-4", [r for r in ep_rows if r["entry_price"] >= 1e-4])

# Time filters
backtest_filter("hour 0-7 UTC (Asia night)", [r for r in rows if 0 <= r["hour_utc"] <= 7])
backtest_filter("hour 8-15 UTC (EU hours)", [r for r in rows if 8 <= r["hour_utc"] <= 15])
backtest_filter("hour 16-23 UTC (US hours)", [r for r in rows if 16 <= r["hour_utc"] <= 23])

# Volume filters (if available)
backtest_filter("volume_24h > 50000", [r for r in rows if r["volume_24h"] > 50000])
backtest_filter("volume_24h > 100000", [r for r in rows if r["volume_24h"] > 100000])

# Age filters
backtest_filter("age_hours < 0.5h", [r for r in rows if 0 < r["age_hours"] < 0.5])
backtest_filter("age_hours < 1h", [r for r in rows if 0 < r["age_hours"] < 1])

# Combined filters
backtest_filter("vol>50k AND age<1h", [r for r in rows if r["volume_24h"] > 50000 and 0 < r["age_hours"] < 1])
backtest_filter("US hours AND vol>50k", [r for r in rows if 13 <= r["hour_utc"] <= 23 and r["volume_24h"] > 50000])

print(f"\n{'='*60}")
print(f"SUMMARY STATISTICS FOR CONCLUSIONS")
print(f"{'='*60}")
print(f"Total trades analyzed: {len(rows)}")
print(f"Win rate: {100*sum(r['win'] for r in rows)/len(rows):.2f}%")
print(f"Total PnL: ${sum(r['pnl_usd'] for r in rows):.2f}")
print(f"Features with meaningful non-zero values:")
print(f"  entry_price: {sum(1 for r in rows if r['entry_price'] and r['entry_price']>0)} records ({100*sum(1 for r in rows if r['entry_price'] and r['entry_price']>0)/len(rows):.0f}%)")
print(f"  volume_24h:  {sum(1 for r in rows if r['volume_24h']>0)} records ({100*sum(1 for r in rows if r['volume_24h']>0)/len(rows):.0f}%)")
print(f"  age_hours:   {sum(1 for r in rows if r['age_hours']>0)} records ({100*sum(1 for r in rows if r['age_hours']>0)/len(rows):.0f}%)")
print(f"  rugcheck:    {sum(1 for r in rows if r['rugcheck_score']>0)} records ({100*sum(1 for r in rows if r['rugcheck_score']>0)/len(rows):.0f}%)")
print(f"  liquidity:   {sum(1 for r in rows if r['liquidity']>0)} records ({100*sum(1 for r in rows if r['liquidity']>0)/len(rows):.0f}%)")
print(f"  holders:     {sum(1 for r in rows if r['holder_count']>0)} records ({100*sum(1 for r in rows if r['holder_count']>0)/len(rows):.0f}%)")

print("\nDone.")
