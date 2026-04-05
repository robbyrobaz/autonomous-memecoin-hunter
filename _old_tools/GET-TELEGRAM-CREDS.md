# Get Telegram API Credentials (3 values needed)

**Takes 3 minutes. I need these to read Telegram channels.**

## Step 1: Go to Telegram's Developer Portal

**URL:** https://my.telegram.org/apps

## Step 2: Log In

- Enter your phone number (the one you use for Telegram)
- Click "Next"
- Enter the SMS code Telegram sends you

## Step 3: Create Application

**App title:** Memecoin Hunter  
**Short name:** memehunter  
**Platform:** Other  
**Description:** (leave blank)

Click "Create application"

## Step 4: Copy These 3 Values

You'll see:

```
App api_id: 12345678
App api_hash: abc123def456...
```

## Step 5: Add to .env File

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
nano .env
```

Replace FILLME with your actual values:

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456...
TELEGRAM_PHONE=+15551234567
```

**Format for phone:** Must include country code with + (e.g., +1 for US)

Save and exit (Ctrl+X, Y, Enter)

## Step 6: First Run (One Time Only)

```bash
cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python scanner.py
```

**You'll be prompted for:**
- SMS verification code (Telegram sends it)
- 2FA password (if you have 2FA enabled)

This creates `memecoin_hunter.session` file (your auth token).

**Then it will run once and show you any signals found.**

## Done!

After this first run, the cron job (already set up) will run it automatically every 5 minutes.

You never need to enter codes again - the session file persists.
