# 📡 Telegram Channel Expansion Guide

## Current State
- **3 channels** (gmgnsignals, XAceCalls, batman_gem)
- 209 contracts/day combined
- Limited coverage

## Goal
- **15+ active channels**
- 500+ contracts/day
- Better early detection through multiple sources

---

## Step-by-Step Expansion

### Step 1: Discover Active Channels

**What it does:** Tests 100+ candidate channels to find which ones are actually active with contract posts.

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate  # or create venv if needed
python channel_discovery.py
```

**Expected runtime:** 2-5 minutes (tests 100+ channels)

**Expected output:**
```
=== Telegram Channel Discovery ===
Testing 95 channels...

[1/95] Testing @gmgnsignals... ✅ ACTIVE - 100 contracts/day
[2/95] Testing @XAceCalls... ✅ ACTIVE - 84 contracts/day
[3/95] Testing @cryptogems100x... ❌ Not found
[4/95] Testing @SolanaGems... ✅ ACTIVE - 45 contracts/day
...

=== SUMMARY ===
Tested: 95
Active with contracts: 15
Dead/inactive: 35
Not found: 42
Scam flagged: 3

=== TOP 15 ACTIVE CHANNELS ===
1. @gmgnsignals
   Title: GMGN Featured Signals
   Members: 12,500
   Contracts/24h: 100
   Messages/24h: 120

2. @XAceCalls
   Title: XAce Multichain Calls
   Members: 8,300
   Contracts/24h: 84
   Messages/24h: 95
...

✅ Results saved to channel_discovery_results.json
```

### Step 2: Review Results

```bash
cat channel_discovery_results.json | jq '.active | length'
# Shows how many active channels found

cat channel_discovery_results.json | jq '.active[] | {username, contracts_24h, members}'
# View all active channels with stats
```

**What to look for:**
- ✅ 10+ contracts/day (minimum threshold)
- ✅ Recent activity (last post <24h ago)
- ✅ Not scam-flagged
- ⚠️ Avoid channels with <5 contracts/day (too slow)

### Step 3: Apply to Scanner

```bash
python apply_channels.py
```

**What it does:**
- Reads `channel_discovery_results.json`
- Sorts channels by contracts/day
- Takes top 15 most active
- Updates `scanner.py` CHANNELS list automatically

**Output:**
```
=== Applying Top 15 Channels ===

1. @gmgnsignals - 100 contracts/day
2. @XAceCalls - 84 contracts/day
3. @SolanaGems - 45 contracts/day
4. @batman_gem - 25 contracts/day
5. @PumpFunAlerts - 38 contracts/day
...

✅ Updated scanner.py with 15 channels
Old channel count: 3
New channel count: 15
```

### Step 4: Verify Scanner Update

```bash
grep -A 20 "^CHANNELS = " scanner.py
```

Should show the new list with 15 channels.

### Step 5: Test Run

```bash
python scanner.py
```

Watch for:
- All 15 channels being scanned
- More signals collected
- No authentication errors

---

## Expected Improvement

### Before Expansion
```
3 channels
~209 contracts/day scanned
Limited coverage
Single-source signals
```

### After Expansion
```
15 channels
~500+ contracts/day scanned
5x coverage increase
Better confluence detection (same contract from multiple channels = stronger signal)
```

---

## Candidate Channels Tested

The discovery script tests these categories:

**High-Volume Signal Channels:**
- @gmgnsignals, @XAceCalls, @batman_gem (current)
- @SolanaGems, @solanamemecoins, @MoonShotCalls
- @PumpFunAlerts, @raydiumalerts, @dexscreeneralerts

**Alpha/Research Groups:**
- @SolAlphaGroup, @CryptoAlphaCalls, @alphagemhunters
- @whaletracker_alerts

**KOL/Influencer Channels:**
- @ansemcalls, @muradcalls, @cryptokol, @solanaflip

**Platform-Specific:**
- @pumpfunsignals, @pumpfungems (Pump.fun launches)
- @raydiumgems, @raydiumsignals (Raydium DEX)

**Community Channels:**
- @soltrending, @solanacommunity, @solanawhales
- @cryptomoonshots_signals

**Early-Stage Hunters:**
- @fresh_solana_gems, @early_solana, @new_dex_listings

**Volume/Whale Tracking:**
- @highvolumealerts, @whale_alert_solana, @biggainers

**Low-Cap/Hidden Gems:**
- @lowcapgems, @microcapgems, @hidden_gems_sol

**Strategy-Specific:**
- @fairlaunchonly, @presale_alerts, @stealth_launch

Total: ~95 candidates tested

---

## Channel Quality Metrics

**Good Channel:**
- ✅ 20+ contracts/day
- ✅ Recent activity (<12h since last post)
- ✅ Verified or high member count (>5K)
- ✅ Clear contract addresses in posts
- ✅ Not scam-flagged

**Skip:**
- ❌ <10 contracts/day (too slow)
- ❌ Dead (>24h since last post)
- ❌ No contract addresses (just news/hype)
- ❌ Scam flag by Telegram
- ❌ Mostly reposts from other channels

---

## Maintenance

**Re-run discovery every 2-4 weeks:**

Channels die, new ones emerge. Keep your list fresh:

```bash
# Monthly channel refresh
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python channel_discovery.py
python apply_channels.py
```

**Monitor channel health:**

```bash
# Check which channels are actually providing signals
grep "New signal from" logs/signals.jsonl | jq -r '.channel' | sort | uniq -c | sort -rn
```

If a channel drops to <5 signals/day for a week, consider replacing it.

---

## Troubleshooting

### "Authentication required"
The discovery script needs the same Telegram credentials as the main scanner.

Make sure `.env` has:
```
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=your_phone
```

### "FloodWaitError"
Telegram rate limited you. Wait 60 seconds and retry.

The script has 1-second delays built in, but if you run it multiple times quickly, Telegram may throttle.

### "Channel not found"
Some channels are private, banned, or the username changed.

The script tests multiple variants (@name, name, @Name) automatically. If none work, the channel is truly gone.

### "Too many active channels"
If discovery finds 30+ active channels, the apply script will take top 15 by default.

To use more:
```bash
# Edit apply_channels.py
TOP_N = 20  # Increase from 15
```

Then re-run `python apply_channels.py`.

---

## Next: Multi-Platform Confluence

Once you have 15+ Telegram channels running:

1. **X Scanner** is collecting signals → `x-memecoin-scanner/logs/x_signals.jsonl`
2. **Telegram Scanner** (expanded) → `autonomous-memecoin-hunter/logs/signals.jsonl`
3. **Build Confluence Engine** → Find contracts mentioned on BOTH platforms within 15 minutes

Those are the strongest signals (multi-platform validation).

---

## Quick Reference

```bash
# Discovery
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python channel_discovery.py          # Test 100+ channels
cat channel_discovery_results.json   # Review results
python apply_channels.py             # Apply top 15

# Verify
grep -A 20 "^CHANNELS = " scanner.py  # Check new list
python scanner.py                     # Test run

# Monitor
tail -f logs/scanner.log              # Watch live
grep "contracts/day" scanner.py       # See channel stats
```

---

## Status After Expansion

After running these steps, you'll have:

✅ 15+ active Telegram channels (vs 3 before)
✅ 500+ contracts/day scanned (vs 209 before)
✅ Better confluence detection (same contract from multiple sources)
✅ Higher chance of catching launches early
✅ Ready for multi-platform confluence engine (next step)

The expanded channel list will feed into the confluence engine along with X/Twitter signals for maximum signal quality.
