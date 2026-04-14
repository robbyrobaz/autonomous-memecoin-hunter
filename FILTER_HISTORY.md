# Filter Settings History

## V2 Filters (Active until April 7, 2026)

**Results:** 191 closed trades, $12.97 profit, 1.40x profit factor, 33.5% win rate

```
MIN_RUGCHECK_SCORE = 10000   # Rugcheck >= 10K
MAX_RUGCHECK_SCORE = (none)  # No upper cap
MIN_AGE_MINUTES = 6          # Under 6 min = fake pumps
MAX_AGE_MINUTES = 30         # Over 30 min = momentum fading
MIN_LIQUIDITY = (none)       # No liquidity floor
HARD_STOP_PCT = 0.30         # -70% hard stop (entry * 0.30)
TRAILING_STOP_PCT = 0.20     # 20% below peak
TIME_LIMIT_HOURS = 4         # Safety exit after 4hrs
HYPE_SCORE_THRESHOLD = 2     # Minimum hype score to enter
POSITION_SIZE = $1.00        # Fixed per trade
MAX_POSITIONS = 100          # Concurrent position limit
```

### V2 Performance by Exit Reason
| Exit Reason    | Trades | Total P&L | Avg P&L | Win Rate |
|----------------|--------|-----------|---------|----------|
| TRAILING_STOP  | 16     | +$29.61   | +$1.85  | 100%     |
| TIME_LIMIT     | 146    | +$7.24    | +$0.05  | 33%      |
| STOP_LOSS      | 29     | -$23.88   | -$0.82  | 0%       |

### V2 Data-Driven Insights (from 191 trades)
- **Rugcheck 10K-20K was the ONLY profitable bucket** (+$28.40). Higher scores lost money.
- **Liquidity $10K-50K** was best: $7.95 profit, 54% WR. Under $10K = more noise.
- **Low hype (<=2)** outperformed: $15.02 profit, 76% WR on 17 trades. Medium hype (3-5) lost.
- **30-60min hold time** was the sweet spot: $12.97 profit. 1-2hr zone = dead (-$5.58, 0% WR).
- **Peak gain avg: 72.4%**, actual exit avg: 34.5%. Left 37.9% on the table — trailing too loose.
- Single channel source: @gmgnsignals (100% of trades)

---

## V3 Filters (Activated April 7, 2026)

**Changes based on V2 data analysis:**

```
MIN_RUGCHECK_SCORE = 10000   # Keep: 10K floor works
MAX_RUGCHECK_SCORE = 20000   # NEW: Cap at 20K (higher scores lose money)
MIN_AGE_MINUTES = 6          # Keep: under 6min = fake pumps
MAX_AGE_MINUTES = 30         # Keep: over 30min = stale
MIN_LIQUIDITY_USD = 5000     # NEW: Floor at $5K (filters garbage pairs)
HARD_STOP_PCT = 0.30         # Keep: -70% stop only for real rugs
TRAILING_STOP_PCT = 0.15     # TIGHTENED from 0.20: 15% below peak (capture more gains)
TIME_LIMIT_HOURS = 2         # SHORTENED from 4: 1-2hr zone was dead
HYPE_SCORE_THRESHOLD = 2     # Keep: low hype actually wins more
POSITION_SIZE = $1.00        # Keep
MAX_POSITIONS = 100          # Keep
```

### Rationale for each change:
1. **MAX_RUGCHECK_SCORE=20K**: Counterintuitive but data is clear. 10K-20K bucket: +$28.40 profit. 20K-50K: -$4.40. 50K+: -$11.03. Lower-score tokens have more upside.
2. **MIN_LIQUIDITY_USD=5K**: 167/191 trades were <$10K liquidity. Adding a $5K floor filters the worst garbage without cutting too much volume.
3. **TRAILING_STOP_PCT=0.15**: Was leaving 37.9% on the table. Tightening from 20% to 15% should capture ~5-10% more of the peak gains.
4. **TIME_LIMIT_HOURS=2**: 1-2hr hold zone was -$5.58 with 0% WR. Most profitable exits happen within first hour. Cutting time limit to 2hrs avoids the dead zone.
