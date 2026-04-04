# Autonomous Memecoin Hunter

**Goal:** Find Solana memecoins that 2x (100% profit) within 6 hours

**Status:** Paper trading mode (no real money)

## How It Works

1. **Scans 10 Telegram channels** for memecoin mentions every 5 minutes
2. **Detects hype signals** (contract address + keywords like 🚀, moon, 100x)
3. **Safety checks** via Rugcheck + Birdeye + Dexscreener APIs
4. **Paper trades** with $10k fake money (5% position size, max 3 concurrent)
5. **Auto-exits** at 100% profit, -30% stop loss, or 6-hour time limit

## Setup

### 1. Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy API ID and API Hash

### 2. Configure Environment

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
cp .env.template .env
# Edit .env with your Telegram credentials
```

### 3. First Run (Manual Test)

```bash
source venv/bin/activate
python scanner.py
```

This will:
- Prompt for SMS verification code (first time only)
- Scan all channels
- Log signals/trades to `logs/`
- Save positions to `data/positions.json`

### 4. Set Up Cron Job

The cron job runs every 5 minutes using the cronjob tool with Anthropic Sonnet.

## Files

```
autonomous-memecoin-hunter/
├── scanner.py              # Main scanner script
├── venv/                   # Python virtual environment
├── .env                    # Telegram API credentials (not in git)
├── logs/
│   ├── signals.jsonl       # All detected signals
│   ├── paper_trades.jsonl  # All trades (open + close)
│   └── rejections.jsonl    # Signals that failed safety checks
└── data/
    ├── balance.txt         # Current paper trading balance
    └── positions.json      # Open + closed positions
```

## Monitored Channels

1. @solanamemecoins
2. @SolanaFloor
3. @solana_calls
4. @SolanaGems
5. @degencalls
6. @alphacalls
7. @soltrending
8. @SolanaWhales
9. @pumpdotfun
10. @SolShitcoins

## Safety Filters

**All must pass or trade is rejected:**

1. **Rugcheck** - Contract safety score ≥ 60
2. **Birdeye** - Liquidity ≥ $20k, top holder < 30%
3. **Dexscreener** - Liquidity ≥ $10k, volume ≥ $5k/24h, age > 0.5 hours

## Paper Trading Rules

- **Starting balance:** $10,000
- **Position size:** 5% per trade ($500)
- **Max concurrent:** 3 positions
- **Target:** 100% profit (2x)
- **Stop loss:** -30%
- **Time limit:** 6 hours

## Timeline

- **Days 1-4:** Collect 50+ paper trades
- **Day 5:** Analyze results (win rate, avg time to 2x, best channels)
- **Days 6-7:** Go live with Phantom wallet ($100) if profitable

## Next Steps

After paper trading proves profitable (≥55% win rate over 50+ trades):

1. Create/fund Phantom wallet with $100
2. Switch to live mode
3. Monitor first 10 trades closely
4. Scale if working

## Dashboard (Future)

Once profitable, build real-time dashboard showing:
- Current balance
- Open positions (entry price, current P&L, time held)
- Closed trades (win/loss, exit reason)
- Win rate by channel
- Total P&L chart
