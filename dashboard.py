#!/usr/bin/env python3
"""
Autonomous Memecoin Hunter - Live Dashboard
Real-time view of paper trading + LIVE trading performance
"""

from flask import Flask, jsonify, render_template_string
from pathlib import Path
import json
import time
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
BALANCE_FILE = BASE_DIR / 'data' / 'balance.txt'
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'
LIVE_POSITIONS_FILE = BASE_DIR / 'data' / 'live_positions.json'
LIVE_BALANCE_FILE = BASE_DIR / 'data' / 'live_balance.txt'
SIGNALS_LOG = BASE_DIR / 'logs' / 'signals.jsonl'
TRADES_LOG = BASE_DIR / 'logs' / 'paper_trades.jsonl'
REJECTIONS_LOG = BASE_DIR / 'logs' / 'rejections.jsonl'

STARTING_BALANCE = 100.0
SOL_PRICE_USD = 130.0  # Approximate

# Cache for paper_trades.jsonl CLOSE records — reading 20MB+ JSONL on every request is too slow
_closed_trades_cache: list = []
_closed_trades_cache_mtime: float = 0.0

# Cache for signals count — signals.jsonl is 47MB+, only need the count
_signals_count_cache: int = 0
_signals_count_mtime: float = 0.0

# V4 epoch — WS scanner start; only show trades from this point forward
V4_EPOCH = '2026-04-08T18:00:00'

def load_balance():
    if BALANCE_FILE.exists():
        return float(BALANCE_FILE.read_text().strip())
    return STARTING_BALANCE

def load_positions():
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []

def load_live_positions():
    if LIVE_POSITIONS_FILE.exists():
        with open(LIVE_POSITIONS_FILE) as f:
            return json.load(f)
    return []

def load_signals_count_cached() -> int:
    """Count V4-epoch signals from signals.jsonl, re-reading only when file changes.
    Uses string scan (no JSON parsing) to stay fast on 47MB+ files."""
    global _signals_count_cache, _signals_count_mtime
    try:
        mtime = SIGNALS_LOG.stat().st_mtime
    except FileNotFoundError:
        return 0
    if mtime == _signals_count_mtime:
        return _signals_count_cache
    count = 0
    v4_prefix = f'"timestamp": "{V4_EPOCH[:10]}'  # e.g. '"timestamp": "2026-04-08'
    with open(SIGNALS_LOG) as f:
        for line in f:
            # Quick string check: timestamp field must be >= V4_EPOCH date
            ts_idx = line.find('"timestamp": "')
            if ts_idx >= 0:
                ts = line[ts_idx + 14: ts_idx + 33]  # 19-char ISO datetime
                if ts >= V4_EPOCH:
                    count += 1
    _signals_count_cache = count
    _signals_count_mtime = mtime
    return count

def load_closed_trades_cached() -> list:
    """Load CLOSE records from paper_trades.jsonl, re-reading only when the file changes."""
    global _closed_trades_cache, _closed_trades_cache_mtime
    try:
        mtime = TRADES_LOG.stat().st_mtime
    except FileNotFoundError:
        return []
    if mtime == _closed_trades_cache_mtime:
        return _closed_trades_cache
    result = []
    with open(TRADES_LOG) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get('action') == 'CLOSE' and r.get('entry_time', '') >= V4_EPOCH:
                    result.append(r)
            except Exception:
                pass
    _closed_trades_cache = result
    _closed_trades_cache_mtime = mtime
    return result

def load_jsonl(filepath):
    if not filepath.exists():
        return []
    lines = []
    with open(filepath) as f:
        for line in f:
            try:
                lines.append(json.loads(line))
            except:
                pass
    return lines

def get_current_price(contract):
    import requests
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            pairs = resp.json().get('pairs', [])
            if pairs:
                pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
                return float(pair.get('priceUsd', 0) or 0)
    except:
        pass
    return None

def extract_token_name(position):
    """Extract human-readable token name from signal message."""
    import re
    msg = position.get('signal_data', {}).get('message', '')
    if not msg:
        return position.get('contract', '???')[:8] + '...'
    
    # Pattern 1: "$NAME(SYMBOL)" or "$NAME (SYMBOL)" like "$HYRE(Hyre Agent)" or "$aircoin(aircoin)"
    m = re.search(r'\$([A-Za-z][A-Za-z0-9_]*)\s*\(', msg)
    if m:
        return m.group(1)
    
    # Pattern 2: "NAME (SYMBOL)" on its own line like "TINYCOIN (TINYCOIN)" or "MIGA (Make Iran Great Again)"
    m = re.search(r'^([A-Za-z][A-Za-z0-9_]*)\s+\(', msg, re.MULTILINE)
    if m:
        return m.group(1)
    
    # Pattern 3: "KOL Buy NAME!" like "3 KOL Buy HYRE!"
    m = re.search(r'KOL Buy\s+([A-Za-z][A-Za-z0-9_]*)!', msg)
    if m:
        return m.group(1)
    
    # Pattern 4: Just $SYMBOL anywhere
    m = re.search(r'\$([A-Za-z][A-Za-z0-9_]{1,19})', msg)
    if m:
        return m.group(1)
    
    return position.get('contract', '???')[:8] + '...'


def get_sol_balance_safe():
    """Get hot wallet SOL balance, return 0 on failure"""
    try:
        import swap_executor
        return swap_executor.get_sol_balance()
    except:
        return 0.0

def get_wallet_address_safe():
    try:
        import swap_executor
        return swap_executor.get_wallet_address()
    except:
        return "Ejj6mb3nEAGBfMoucvabqQATPBvruB3fM2tWDkysCJeh"

def time_ago(timestamp_str):
    try:
        ts = datetime.fromisoformat(timestamp_str)
        delta = datetime.now() - ts
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return f"{delta.seconds}s ago"
    except:
        return "N/A"

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/api/live_data')
def api_live_data():
    """API endpoint for live trading data"""
    live_positions = load_live_positions()
    wallet_sol = get_sol_balance_safe()
    wallet_address = get_wallet_address_safe()

    # Filter to V4 epoch only
    live_positions = [p for p in live_positions if p.get('entry_time', '') >= V4_EPOCH]

    open_positions = [p for p in live_positions if p.get('status') == 'OPEN']
    closed_positions = [p for p in live_positions if p.get('status') == 'CLOSED']

    # Update open positions with current prices and names
    for pos in open_positions:
        pos['token_name'] = extract_token_name(pos)
        current_price = get_current_price(pos['contract'])
        if current_price:
            pos['current_price'] = current_price
            pos['current_pnl_pct'] = (current_price / pos['entry_price'] - 1) * 100
        else:
            pos['current_price'] = pos['entry_price']
            pos['current_pnl_pct'] = 0

        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        pos['hours_held'] = round(hours_held, 1)
        pos['time_ago'] = time_ago(pos['entry_time'])

    for pos in closed_positions:
        pos['token_name'] = extract_token_name(pos)
        pos['time_ago'] = time_ago(pos.get('exit_time', pos['entry_time']))

    # Calculate live P&L
    total_sol_spent = sum(p.get('sol_spent', 0) for p in closed_positions)
    total_sol_received = sum(p.get('sol_received', 0) for p in closed_positions)
    total_sol_pnl = sum(p.get('sol_pnl', 0) for p in closed_positions)
    total_usd_pnl = total_sol_pnl * SOL_PRICE_USD

    # Open positions unrealized
    open_sol_invested = sum(p.get('sol_spent', 0) for p in open_positions)

    return jsonify({
        'wallet_sol': wallet_sol,
        'wallet_address': wallet_address,
        'open_positions': open_positions,
        'closed_positions': sorted(closed_positions, key=lambda p: p.get('exit_time', ''), reverse=True),
        'open_count': len(open_positions),
        'closed_count': len(closed_positions),
        'total_sol_pnl': total_sol_pnl,
        'total_usd_pnl': total_usd_pnl,
        'total_sol_spent': total_sol_spent,
        'total_sol_received': total_sol_received,
        'open_sol_invested': open_sol_invested,
        'sol_price_usd': SOL_PRICE_USD,
        'last_update': datetime.now().isoformat(),
    })

@app.route('/api/data')
def api_data():
    """Main API endpoint for paper trading dashboard data — V4 epoch only"""
    positions = load_positions()

    # Filter to V4 epoch only
    positions = [p for p in positions if p.get('entry_time', '') >= V4_EPOCH]

    open_positions = [p for p in positions if p.get('status') == 'OPEN']

    # Load closed positions from paper_trades.jsonl (full history — positions.json
    # is trimmed to last 1,000 CLOSED to bound file size). mtime-cached so the
    # 20MB+ file is only re-parsed when new trades are appended.
    closed_positions = load_closed_trades_cached()

    # Calculate V4-era balance: start from $100 + all closed P&L
    v4_pnl = sum(p.get('pnl_usd', 0) for p in closed_positions)
    balance = STARTING_BALANCE + v4_pnl

    signals_count = load_signals_count_cached()
    rejections = []  # Don't load huge rejections file, not needed for display

    for pos in open_positions:
        pos['token_name'] = extract_token_name(pos)
        # Skip live Dexscreener lookup — with 300+ open positions it causes 30s+ latency.
        # ws_scanner.py tracks live prices every 30s; dashboard shows entry price only.
        pos['current_price'] = pos.get('entry_price', 0)
        pos['current_pnl_pct'] = 0
        pos['current_pnl_usd'] = 0

        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        pos['hours_held'] = round(hours_held, 1)
        pos['time_ago'] = time_ago(pos['entry_time'])

    for pos in closed_positions:
        pos['token_name'] = extract_token_name(pos)
        pos['time_ago'] = time_ago(pos.get('exit_time', pos['entry_time']))

    # Only add unrealized PnL from open positions — their initial capital was already
    # deducted from balance when opened (balance is computed from closed-trade PnL only,
    # so adding size_usd here would double-count the deployed capital)
    open_unrealized_pnl = sum(pos.get('current_pnl_usd', 0) for pos in open_positions)
    total_portfolio_value = balance + open_unrealized_pnl
    total_pnl = total_portfolio_value - STARTING_BALANCE
    total_pnl_pct = (total_pnl / STARTING_BALANCE) * 100

    winners = [p for p in closed_positions if p.get('pnl_usd', 0) > 0]
    losers = [p for p in closed_positions if p.get('pnl_usd', 0) < 0]
    total_wins = sum(p.get('pnl_usd', 0) for p in winners)
    total_losses = abs(sum(p.get('pnl_usd', 0) for p in losers))
    profit_factor = (total_wins / total_losses) if total_losses > 0 else 0
    avg_win = (total_wins / len(winners)) if winners else 0
    avg_loss = (total_losses / len(losers)) if losers else 0
    win_rate = (len(winners) / len(closed_positions) * 100) if closed_positions else 0
    trailing_stops = [p for p in closed_positions if p.get('exit_reason') == 'TRAILING_STOP']
    trailing_stop_rate = (len(trailing_stops) / len(closed_positions) * 100) if closed_positions else 0
    best_trade = max(closed_positions, key=lambda p: p.get('pnl_usd', 0)) if closed_positions else None
    worst_trade = min(closed_positions, key=lambda p: p.get('pnl_usd', 0)) if closed_positions else None

    by_channel = defaultdict(lambda: {'trades': 0, 'wins': 0, 'targets': 0, 'pnl': 0})
    for p in closed_positions:
        channel = p.get('signal_data', {}).get('channel', 'UNKNOWN')
        by_channel[channel]['trades'] += 1
        if p.get('pnl_usd', 0) > 0:
            by_channel[channel]['wins'] += 1
        if p.get('exit_reason') == 'TARGET_HIT':
            by_channel[channel]['targets'] += 1
        by_channel[channel]['pnl'] += p.get('pnl_usd', 0)

    channels_list = []
    for channel, stats in sorted(by_channel.items(), key=lambda x: x[1]['pnl'], reverse=True):
        win_pct = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        channels_list.append({
            'channel': channel,
            'trades': stats['trades'],
            'win_pct': round(win_pct, 1),
            'pnl': round(stats['pnl'], 2)
        })

    balance_history = [{'time': 0, 'balance': STARTING_BALANCE}]
    running_balance = STARTING_BALANCE
    for pos in sorted(closed_positions, key=lambda p: p.get('exit_time', '')):
        if pos.get('exit_time'):
            running_balance += pos.get('pnl_usd', 0)
            balance_history.append({
                'time': pos['exit_time'],
                'balance': round(running_balance, 2)
            })

    # ROI by hour-of-day (0–23): avg pnl_pct of all trades closed in that hour
    _roi_buckets: dict = defaultdict(list)
    for p in closed_positions:
        et = p.get('exit_time', '')
        if len(et) >= 13:
            try:
                hour = int(et[11:13])
                _roi_buckets[hour].append(p.get('pnl_pct', 0))
            except ValueError:
                pass
    roi_by_hour = []
    for h in range(24):
        pnls = _roi_buckets.get(h, [])
        roi_by_hour.append({
            'hour': h,
            'avg_roi': round(sum(pnls) / len(pnls), 2) if pnls else 0,
            'count': len(pnls),
        })

    return jsonify({
        'balance': balance,
        'open_positions': open_positions,
        'closed_positions': closed_positions,
        'starting_balance': STARTING_BALANCE,
        'total_pnl': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'total_signals': signals_count,
        'total_rejections': len(rejections),
        'total_trades': len(open_positions) + len(closed_positions),
        'open_count': len(open_positions),
        'closed_count': len(closed_positions),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'trailing_stop_rate': round(trailing_stop_rate, 1),
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'channels': channels_list,
        'balance_history': balance_history,
        'roi_by_hour': roi_by_hour,
        'filter_change_ts': '2026-04-10T22:49:43',  # ML entry filter added (commit bc4010b)
        'last_update': datetime.now().isoformat()
    })

TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Memecoin Hunter - Live Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0e1a;
            color: #e0e0e0;
            padding: 20px;
        }

        .container { max-width: 1400px; margin: 0 auto; }

        h1 {
            font-size: 28px;
            margin-bottom: 10px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .status {
            font-size: 14px;
            color: #888;
            margin-bottom: 30px;
        }

        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }

        .metric {
            background: #151b2d;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #1f2937;
        }

        .metric-label {
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .metric-value {
            font-size: 28px;
            font-weight: bold;
            color: #fff;
        }

        .metric-change {
            font-size: 14px;
            margin-top: 5px;
        }

        .positive { color: #10b981; }
        .negative { color: #ef4444; }
        .neutral { color: #888; }

        .section {
            background: #151b2d;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #1f2937;
        }

        .section-title {
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 15px;
            color: #fff;
        }

        /* LIVE section special styling */
        .live-section {
            background: #151b2d;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            border: 2px solid #ef4444;
            position: relative;
        }

        .live-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #ef444430;
            color: #ef4444;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .live-dot {
            width: 8px;
            height: 8px;
            background: #ef4444;
            border-radius: 50%;
            animation: livePulse 1.5s ease-in-out infinite;
        }

        @keyframes livePulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
            50% { opacity: 0.6; box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
        }

        .live-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin: 15px 0;
        }

        .live-metric {
            background: #0a0e1a;
            padding: 15px;
            border-radius: 6px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            text-align: left;
            padding: 12px;
            background: #0a0e1a;
            color: #888;
            font-size: 12px;
            text-transform: uppercase;
            font-weight: 600;
        }

        td {
            padding: 12px;
            border-top: 1px solid #1f2937;
            font-size: 14px;
        }

        tr:hover {
            background: #1a2030;
        }

        .contract {
            font-family: monospace;
            font-size: 12px;
            color: #888;
        }

        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .badge-success { background: #10b98120; color: #10b981; }
        .badge-danger { background: #ef444420; color: #ef4444; }
        .badge-warning { background: #f59e0b20; color: #f59e0b; }
        .badge-info { background: #3b82f620; color: #3b82f6; }

        .chart-container {
            width: 100%;
            height: 300px;
            margin-top: 20px;
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #666;
        }

        a { color: #3b82f6; text-decoration: none; }
        a:hover { text-decoration: underline; }

        .tx-link {
            font-family: monospace;
            font-size: 11px;
            color: #3b82f6;
        }

        .paper-label {
            display: inline-block;
            background: #3b82f620;
            color: #3b82f6;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
        }

        .divider {
            border: 0;
            border-top: 2px solid #1f2937;
            margin: 40px 0 30px;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .loading {
            animation: pulse 2s ease-in-out infinite;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container">
        <h1>&#x1F916; Autonomous Memecoin Hunter <span style="font-size:14px;color:#f59e0b;background:#f59e0b20;padding:3px 10px;border-radius:12px;">V4 ML Filter</span></h1>
        <div class="status" id="status">Loading...</div>

        <!-- ===== LIVE TRADING SECTION ===== -->
        <div class="live-section" id="live-section">
            <div class="section-title" style="display:flex;align-items:center;gap:12px;">
                <span class="live-badge"><span class="live-dot"></span> LIVE</span>
                Real Money Trading <span style="font-size:12px;color:#888;margin-left:8px;">PAUSED — paper testing V4 strategy</span>
            </div>
            <div class="live-metrics" id="live-metrics">
                <div class="live-metric">
                    <div class="metric-label">Loading...</div>
                </div>
            </div>

            <div style="margin-top:15px;">
                <div class="section-title" style="font-size:15px;">Open Positions (<span id="live-open-count">0</span>)</div>
                <div id="live-open-positions"></div>
            </div>

            <div style="margin-top:15px;">
                <div class="section-title" style="font-size:15px;">Closed Trades (<span id="live-closed-count">0</span>)</div>
                <div id="live-closed-trades"></div>
            </div>
        </div>

        <!-- ===== DIVIDER ===== -->
        <hr class="divider">

        <!-- ===== PAPER TRADING SECTION ===== -->
        <h2 style="color:#fff;margin-bottom:15px;display:flex;align-items:center;">
            &#x1F4C4; Paper Trading <span class="paper-label">V4 ML Filter (Real-Time)</span>
        </h2>
        <div style="color:#888;font-size:13px;margin-bottom:20px;">
            PumpPortal WebSocket &bull; 3-min eval: vol&thinsp;&ge;&thinsp;$3k <em>or</em> &Delta;5m&thinsp;&ge;&thinsp;5% &bull; 12% trailing stop &bull; 70% hard stop &bull; 6h time limit
        </div>

        <div class="metrics" id="metrics"></div>

        <div class="section">
            <div class="section-title">&#x1F4CA; Balance History</div>
            <div class="chart-container">
                <canvas id="balanceChart"></canvas>
            </div>
        </div>

        <div class="section">
            <div class="section-title">&#x23F1; Avg ROI % by Hour of Day <span style="font-size:12px;color:#888;font-weight:normal;margin-left:8px;">UTC — all closed trades</span></div>
            <div class="chart-container" style="height:220px;">
                <canvas id="roiHourChart"></canvas>
            </div>
        </div>

        <div class="section">
            <div class="section-title">&#x1F525; Open Positions (<span id="open-count">0</span>)</div>
            <div id="open-positions"></div>
        </div>

        <div class="section">
            <div class="section-title">&#x1F4DC; Recent Closed Trades (<span id="closed-count">0</span>)</div>
            <div id="closed-trades"></div>
        </div>

        <div class="section">
            <div class="section-title">&#x1F4E1; Performance by Channel</div>
            <div id="channels"></div>
        </div>
    </div>

    <script>
        let balanceChart = null;
        let roiHourChart = null;
        const SOL_PRICE = 130;

        function formatMoney(val) {
            if (val === null || val === undefined) return '-';
            if (Math.abs(val) < 0.01 && val !== 0) return '$' + val.toFixed(8);
            return '$' + val.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }

        function formatSOL(val) {
            if (val === null || val === undefined) return '-';
            return val.toFixed(6) + ' SOL';
        }

        function formatPct(val) {
            return (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
        }

        function truncate(str, len) {
            return str.length > len ? str.substring(0, len) + '...' : str;
        }

        function solscanTx(sig) {
            if (!sig) return '-';
            return `<a href="https://solscan.io/tx/${sig}" target="_blank" class="tx-link">${sig.substring(0,12)}...</a>`;
        }

        function solscanAddr(addr) {
            return `<a href="https://solscan.io/account/${addr}" target="_blank">${addr.substring(0,8)}...${addr.substring(addr.length-4)}</a>`;
        }

        // ===== LIVE TRADING RENDERING =====

        function renderLiveData(data) {
            const pnlClass = data.total_sol_pnl >= 0 ? 'positive' : 'negative';
            const pnlSign = data.total_sol_pnl >= 0 ? '+' : '';

            document.getElementById('live-metrics').innerHTML = `
                <div class="live-metric">
                    <div class="metric-label">Hot Wallet</div>
                    <div class="metric-value" style="font-size:20px;">${data.wallet_sol.toFixed(4)} SOL</div>
                    <div class="metric-change neutral">${solscanAddr(data.wallet_address)}</div>
                    <div class="metric-change neutral">~${formatMoney(data.wallet_sol * SOL_PRICE)}</div>
                </div>
                <div class="live-metric">
                    <div class="metric-label">Live P&L</div>
                    <div class="metric-value ${pnlClass}" style="font-size:20px;">${pnlSign}${data.total_sol_pnl.toFixed(6)} SOL</div>
                    <div class="metric-change ${pnlClass}">${formatMoney(data.total_usd_pnl)}</div>
                </div>
                <div class="live-metric">
                    <div class="metric-label">Live Trades</div>
                    <div class="metric-value" style="font-size:20px;">${data.open_count + data.closed_count}</div>
                    <div class="metric-change neutral">${data.open_count} open &middot; ${data.closed_count} closed</div>
                </div>
                <div class="live-metric">
                    <div class="metric-label">SOL In Positions</div>
                    <div class="metric-value" style="font-size:20px;">${data.open_sol_invested.toFixed(4)} SOL</div>
                    <div class="metric-change neutral">~${formatMoney(data.open_sol_invested * SOL_PRICE)}</div>
                </div>
            `;

            // Live open positions
            document.getElementById('live-open-count').textContent = data.open_count;
            if (data.open_positions.length === 0) {
                document.getElementById('live-open-positions').innerHTML = '<div class="empty-state">No live open positions</div>';
            } else {
                let html = '<table><thead><tr><th>Name</th><th>Contract</th><th>Entry Price</th><th>Current</th><th>P&L</th><th>SOL Spent</th><th>Time</th><th>Buy TX</th></tr></thead><tbody>';
                data.open_positions.forEach(pos => {
                    const pnl = pos.current_pnl_pct || 0;
                    const cls = pnl >= 0 ? 'positive' : 'negative';
                    html += '<tr>';
                    html += `<td><strong>${pos.token_name || '?'}</strong></td>`;
                    html += `<td><a href="https://dexscreener.com/solana/${pos.contract}" target="_blank" class="contract">${truncate(pos.contract, 12)}</a></td>`;
                    html += `<td>${formatMoney(pos.entry_price)}</td>`;
                    html += `<td>${formatMoney(pos.current_price)}</td>`;
                    html += `<td class="${cls}">${formatPct(pnl)}</td>`;
                    html += `<td>${(pos.sol_spent || 0).toFixed(4)}</td>`;
                    html += `<td>${pos.hours_held}h</td>`;
                    html += `<td>${solscanTx(pos.tx_buy_sig)}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
                document.getElementById('live-open-positions').innerHTML = html;
            }

            // Live closed trades
            document.getElementById('live-closed-count').textContent = data.closed_count;
            if (data.closed_positions.length === 0) {
                document.getElementById('live-closed-trades').innerHTML = '<div class="empty-state">No live closed trades yet</div>';
            } else {
                let html = '<table><thead><tr><th>Name</th><th>Contract</th><th>SOL In</th><th>SOL Out</th><th>P&L (SOL)</th><th>P&L ($)</th><th>Reason</th><th>Buy TX</th><th>Sell TX</th><th>Time</th></tr></thead><tbody>';
                data.closed_positions.forEach(trade => {
                    const solPnl = trade.sol_pnl || 0;
                    const cls = solPnl >= 0 ? 'positive' : 'negative';
                    const badgeClass = trade.exit_reason === 'TRAILING_STOP' ? 'badge-success' :
                                       trade.exit_reason === 'STOP_LOSS' ? 'badge-danger' : 'badge-warning';
                    html += '<tr>';
                    html += `<td><strong>${trade.token_name || '?'}</strong></td>`;
                    html += `<td><a href="https://dexscreener.com/solana/${trade.contract}" target="_blank" class="contract">${truncate(trade.contract, 12)}</a></td>`;
                    html += `<td>${(trade.sol_spent || 0).toFixed(4)}</td>`;
                    html += `<td>${(trade.sol_received || 0).toFixed(4)}</td>`;
                    html += `<td class="${cls}">${solPnl >= 0 ? '+' : ''}${solPnl.toFixed(6)}</td>`;
                    html += `<td class="${cls}">${formatMoney(trade.pnl_usd || 0)}</td>`;
                    html += `<td><span class="badge ${badgeClass}">${trade.exit_reason || '-'}</span></td>`;
                    html += `<td>${solscanTx(trade.tx_buy_sig)}</td>`;
                    html += `<td>${solscanTx(trade.tx_sell_sig)}</td>`;
                    html += `<td>${trade.time_ago}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
                document.getElementById('live-closed-trades').innerHTML = html;
            }
        }

        // ===== PAPER TRADING RENDERING =====

        function renderMetrics(data) {
            const html = `
                <div class="metric">
                    <div class="metric-label">Paper Balance</div>
                    <div class="metric-value">${formatMoney(data.balance)}</div>
                    <div class="metric-change ${data.total_pnl >= 0 ? 'positive' : 'negative'}">
                        ${formatMoney(data.total_pnl)} (${formatPct(data.total_pnl_pct)})
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Trades</div>
                    <div class="metric-value">${data.total_trades}</div>
                    <div class="metric-change neutral">
                        ${data.open_count} open &middot; ${data.closed_count} closed
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Profit Factor</div>
                    <div class="metric-value ${data.profit_factor >= 1 ? 'positive' : 'negative'}">
                        ${data.profit_factor.toFixed(2)}x
                    </div>
                    <div class="metric-change neutral">
                        ${data.profit_factor >= 1 ? '&#x2713; Profitable' : 'Target: &ge;1.0x'}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Avg Win / Loss</div>
                    <div class="metric-value">${formatMoney(data.avg_win)} / ${formatMoney(data.avg_loss)}</div>
                    <div class="metric-change neutral">
                        Ratio: ${data.avg_loss > 0 ? (data.avg_win / data.avg_loss).toFixed(2) + 'x' : '-'}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Wins / Losses</div>
                    <div class="metric-value">
                        <span class="positive">${formatMoney(data.total_wins)}</span> / <span class="negative">${formatMoney(data.total_losses)}</span>
                    </div>
                    <div class="metric-change neutral">
                        Trailing stops: ${data.trailing_stop_rate.toFixed(0)}%
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Signals Detected</div>
                    <div class="metric-value">${data.total_signals}</div>
                    <div class="metric-change neutral">
                        ${data.total_rejections} rejected
                    </div>
                </div>
            `;
            document.getElementById('metrics').innerHTML = html;
        }

        function renderOpenPositions(positions) {
            document.getElementById('open-count').textContent = positions.length;
            if (positions.length === 0) {
                document.getElementById('open-positions').innerHTML = '<div class="empty-state">No open positions</div>';
                return;
            }
            let html = '<table><thead><tr><th>Name</th><th>Contract</th><th>Entry</th><th>Current</th><th>P&L</th><th>Time Held</th></tr></thead><tbody>';
            positions.forEach(pos => {
                const pnlClass = pos.current_pnl_usd >= 0 ? 'positive' : 'negative';
                html += '<tr>';
                html += `<td><strong>${pos.token_name || '?'}</strong></td>`;
                html += `<td><span class="contract">${truncate(pos.contract, 12)}</span></td>`;
                html += `<td>${formatMoney(pos.entry_price)}</td>`;
                html += `<td>${formatMoney(pos.current_price)}</td>`;
                html += `<td class="${pnlClass}">${formatMoney(pos.current_pnl_usd)} (${formatPct(pos.current_pnl_pct)})</td>`;
                html += `<td>${pos.hours_held}h</td>`;
                html += '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('open-positions').innerHTML = html;
        }

        function renderClosedTrades(trades) {
            document.getElementById('closed-count').textContent = trades.length;
            if (trades.length === 0) {
                document.getElementById('closed-trades').innerHTML = '<div class="empty-state">No closed trades yet</div>';
                return;
            }
            let html = '<table><thead><tr><th>Name</th><th>Contract</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th><th>Time</th></tr></thead><tbody>';
            trades.forEach(trade => {
                const pnlClass = trade.pnl_usd >= 0 ? 'positive' : 'negative';
                const badgeClass = trade.exit_reason === 'TARGET_HIT' ? 'badge-success' :
                                   trade.exit_reason === 'STOP_LOSS' ? 'badge-danger' : 'badge-warning';
                html += '<tr>';
                html += `<td><strong>${trade.token_name || '?'}</strong></td>`;
                html += `<td><span class="contract">${truncate(trade.contract, 12)}</span></td>`;
                html += `<td>${formatMoney(trade.entry_price)}</td>`;
                html += `<td>${formatMoney(trade.exit_price)}</td>`;
                html += `<td class="${pnlClass}">${formatMoney(trade.pnl_usd)} (${formatPct(trade.pnl_pct)})</td>`;
                html += `<td><span class="badge ${badgeClass}">${trade.exit_reason}</span></td>`;
                html += `<td>${trade.time_ago}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('closed-trades').innerHTML = html;
        }

        function renderChannels(channels) {
            if (channels.length === 0) {
                document.getElementById('channels').innerHTML = '<div class="empty-state">No channel data yet</div>';
                return;
            }
            let html = '<table><thead><tr><th>Channel</th><th>Trades</th><th>Win %</th><th>P&L</th></tr></thead><tbody>';
            channels.forEach(ch => {
                const pnlClass = ch.pnl >= 0 ? 'positive' : 'negative';
                html += '<tr>';
                html += `<td>${ch.channel}</td>`;
                html += `<td>${ch.trades}</td>`;
                html += `<td>${ch.win_pct}%</td>`;
                html += `<td class="${pnlClass}">${formatMoney(ch.pnl)}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table>';
            document.getElementById('channels').innerHTML = html;
        }

        function renderBalanceChart(history, filterChangeTs) {
            const ctx = document.getElementById('balanceChart').getContext('2d');
            if (balanceChart) balanceChart.destroy();

            // Format timestamps as "Apr 8 18:30" — blank for start point
            function fmtTime(iso) {
                if (!iso || iso === 0) return 'Start';
                const d = new Date(iso);
                return d.toLocaleDateString('en-US', {month:'short', day:'numeric'})
                    + ' ' + d.toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit', hour12:false});
            }
            const labels = history.map(h => fmtTime(h.time));
            const data = history.map(h => h.balance);

            // Find the first trade index at or after the filter change timestamp
            let filterIdx = -1;
            if (filterChangeTs) {
                filterIdx = history.findIndex(h => h.time && h.time >= filterChangeTs);
            }

            // Inline plugin: draws a vertical amber dashed line + label at filterIdx
            const filterAnnotationPlugin = {
                id: 'filterAnnotation',
                afterDraw(chart) {
                    if (filterIdx < 0 || filterIdx >= chart.data.labels.length) return;
                    const meta = chart.getDatasetMeta(0);
                    const point = meta.data[filterIdx];
                    if (!point) return;
                    const x = point.x;
                    const top = chart.chartArea.top;
                    const bottom = chart.chartArea.bottom;
                    const c = chart.ctx;
                    c.save();
                    c.setLineDash([5, 4]);
                    c.strokeStyle = '#f59e0b';
                    c.lineWidth = 2;
                    c.beginPath();
                    c.moveTo(x, top);
                    c.lineTo(x, bottom);
                    c.stroke();
                    c.setLineDash([]);
                    // Label pill
                    const label = 'Filter v4';
                    c.font = 'bold 10px sans-serif';
                    const tw = c.measureText(label).width;
                    const px = 6, py = 3;
                    const rx = x + 5, ry = top + 8;
                    c.fillStyle = '#f59e0b';
                    c.beginPath();
                    c.roundRect(rx, ry, tw + px * 2, 16 + py, 3);
                    c.fill();
                    c.fillStyle = '#000';
                    c.fillText(label, rx + px, ry + 12);
                    c.restore();
                }
            };

            balanceChart = new Chart(ctx, {
                type: 'line',
                plugins: [filterAnnotationPlugin],
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Balance',
                        data: data,
                        borderColor: '#10b981',
                        backgroundColor: '#10b98120',
                        tension: 0.1,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: items => labels[items[0].dataIndex],
                                label: item => ` $${item.raw.toFixed(2)}`
                            }
                        }
                    },
                    elements: { point: { radius: 0, hoverRadius: 4 } },
                    scales: {
                        y: {
                            ticks: { color: '#888', callback: v => '$' + v.toFixed(2) },
                            grid: { color: '#1f2937' }
                        },
                        x: {
                            ticks: {
                                color: '#888',
                                autoSkip: true,
                                maxTicksLimit: 10,
                                maxRotation: 30,
                            },
                            grid: { color: '#1f2937' }
                        }
                    }
                }
            });
        }

        function renderRoiHourChart(roiByHour) {
            const ctx = document.getElementById('roiHourChart').getContext('2d');
            if (roiHourChart) roiHourChart.destroy();

            const labels = roiByHour.map(d => d.hour.toString().padStart(2,'0') + ':00');
            const values = roiByHour.map(d => d.avg_roi);
            const counts = roiByHour.map(d => d.count);
            const colors = values.map(v => v >= 0 ? '#10b98199' : '#ef444499');
            const borderColors = values.map(v => v >= 0 ? '#10b981' : '#ef4444');

            roiHourChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: 'Avg ROI %',
                        data: values,
                        backgroundColor: colors,
                        borderColor: borderColors,
                        borderWidth: 1,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: items => labels[items[0].dataIndex] + ' UTC',
                                label: item => [
                                    ` Avg ROI: ${item.raw >= 0 ? '+' : ''}${item.raw.toFixed(2)}%`,
                                    ` Trades: ${counts[item.dataIndex]}`
                                ]
                            }
                        }
                    },
                    scales: {
                        y: {
                            ticks: {
                                color: '#888',
                                callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
                            },
                            grid: { color: '#1f2937' },
                            border: { dash: [3, 3] }
                        },
                        x: {
                            ticks: { color: '#888', font: { size: 10 } },
                            grid: { color: '#1f293720' }
                        }
                    }
                }
            });
        }

        async function fetchData() {
            try {
                // Fetch both live and paper data
                const [liveResp, paperResp] = await Promise.all([
                    fetch('/api/live_data'),
                    fetch('/api/data')
                ]);
                const liveData = await liveResp.json();
                const paperData = await paperResp.json();

                document.getElementById('status').innerHTML =
                    `<span class="live-badge" style="font-size:11px;padding:2px 8px;"><span class="live-dot" style="width:6px;height:6px;"></span> LIVE</span> ` +
                    `Last update: ${new Date(paperData.last_update).toLocaleString()}`;

                renderLiveData(liveData);
                renderMetrics(paperData);
                renderOpenPositions(paperData.open_positions);
                renderClosedTrades(paperData.closed_positions);
                renderChannels(paperData.channels);
                renderBalanceChart(paperData.balance_history, paperData.filter_change_ts);
                renderRoiHourChart(paperData.roi_by_hour);

            } catch (err) {
                console.error('Error fetching data:', err);
                document.getElementById('status').innerHTML =
                    '<span class="negative">Error loading data</span>';
            }
        }

        // Initial load
        fetchData();
        // Auto-refresh every 10 seconds
        setInterval(fetchData, 10000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("Starting Memecoin Hunter Dashboard on http://0.0.0.0:8899")
    print("Access via: http://omen-claw.tail76e7df.ts.net:8899/")
    app.run(host='0.0.0.0', port=8899, debug=False)
