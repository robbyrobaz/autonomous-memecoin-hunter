# Setup Instructions

## 1. Get Telegram API Credentials

**You need to do this once:**

1. Go to https://my.telegram.org/apps
2. Log in with your phone number (SMS code)
3. Click "Create Application"
   - App title: "Memecoin Hunter"
   - Short name: "memehunter"
   - Platform: Other
4. Copy the **API ID** and **API hash**

## 2. Configure .env File

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
cp .env.template .env
nano .env
```

Fill in:
```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456...
TELEGRAM_PHONE=+15551234567
```

## 3. First Run (Manual - Required)

**This authorizes the Telegram session:**

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python scanner.py
```

**You'll be prompted for:**
1. SMS verification code (sent to your phone)
2. 2FA password (if you have it enabled)

**This creates `memecoin_hunter.session` file - that's your auth token.**

The scanner will then run once and show you any signals found.

## 4. Set Up Cron Job

**Add to your crontab (runs every 5 minutes):**

```bash
crontab -e
```

Add this line:
```
*/5 * * * * /home/rob/.openclaw/workspace/autonomous-memecoin-hunter/run.sh
```

**Or use the systemd timer (alternative):**

Create `~/.config/systemd/user/memecoin-hunter.timer`:
```ini
[Unit]
Description=Autonomous Memecoin Hunter Scanner

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

Create `~/.config/systemd/user/memecoin-hunter.service`:
```ini
[Unit]
Description=Memecoin Hunter Scanner

[Service]
Type=oneshot
ExecStart=/home/rob/.openclaw/workspace/autonomous-memecoin-hunter/run.sh
```

Then:
```bash
systemctl --user daemon-reload
systemctl --user enable --now memecoin-hunter.timer
systemctl --user list-timers  # Verify it's scheduled
```

## 5. Monitor Logs

**Watch live scanning:**
```bash
tail -f ~/.openclaw/workspace/autonomous-memecoin-hunter/logs/cron.log
```

**View signals:**
```bash
cat ~/.openclaw/workspace/autonomous-memecoin-hunter/logs/signals.jsonl | jq
```

**View trades:**
```bash
cat ~/.openclaw/workspace/autonomous-memecoin-hunter/logs/paper_trades.jsonl | jq
```

**Check current positions:**
```bash
cat ~/.openclaw/workspace/autonomous-memecoin-hunter/data/positions.json | jq
```

**Current balance:**
```bash
cat ~/.openclaw/workspace/autonomous-memecoin-hunter/data/balance.txt
```

## 6. Wait for Data (Days 2-4)

Let it run for 3-4 days. Goal: 50+ paper trades.

Check daily:
```bash
# How many trades so far?
wc -l ~/.openclaw/workspace/autonomous-memecoin-hunter/logs/paper_trades.jsonl

# Current balance?
cat ~/.openclaw/workspace/autonomous-memecoin-hunter/data/balance.txt
```

## 7. Analysis (Day 5)

I'll build an analyzer script to calculate:
- Win rate (% that hit 100% profit target)
- Avg time to 2x
- Best/worst channels
- Total P&L

If win rate ≥ 55% over 50+ trades → ready for live trading.

## Troubleshooting

**"Could not find the input entity for" error**
- Channel name might be wrong or you're not a member
- Join all 10 channels manually first
- Or edit `scanner.py` to remove that channel

**"SessionPasswordNeededError"**
- You have 2FA enabled
- Enter your 2FA password when prompted

**"FloodWaitError: A wait of X seconds is required"**
- Telegram rate limit hit
- Wait X seconds, then try again
- Happens if scanning too frequently

**No signals found**
- Normal! Not every 5min scan will find new signals
- Check logs/signals.jsonl over time
- Make sure you joined all 10 channels

**All signals rejected by safety checks**
- Also normal! Most memecoins ARE rugs
- That's why we have safety filters
- Over time, some will pass
