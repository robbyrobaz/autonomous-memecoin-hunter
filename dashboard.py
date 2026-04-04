#!/usr/bin/env python3
"""
Autonomous Memecoin Hunter - Live Dashboard
Real-time view of paper trading performance
"""

from flask import Flask, jsonify, render_template_string
from pathlib import Path
import json
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
BALANCE_FILE = BASE_DIR / 'data' / 'balance.txt'
POSITIONS_FILE = BASE_DIR / 'data' / 'positions.json'
SIGNALS_LOG = BASE_DIR / 'logs' / 'signals.jsonl'
TRADES_LOG = BASE_DIR / 'logs' / 'paper_trades.jsonl'
REJECTIONS_LOG = BASE_DIR / 'logs' / 'rejections.jsonl'

STARTING_BALANCE = 10000.0

def load_balance():
    """Get current balance"""
    if BALANCE_FILE.exists():
        return float(BALANCE_FILE.read_text().strip())
    return STARTING_BALANCE

def load_positions():
    """Load all positions"""
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []

def load_jsonl(filepath):
    """Load JSONL file"""
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
    """Get current price from Dexscreener"""
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

def time_ago(timestamp_str):
    """Human-readable time ago"""
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

@app.route('/api/data')
def api_data():
    """Main API endpoint for dashboard data"""
    
    # Load data
    balance = load_balance()
    positions = load_positions()
    signals = load_jsonl(SIGNALS_LOG)
    rejections = load_jsonl(REJECTIONS_LOG)
    
    # Separate open vs closed
    open_positions = [p for p in positions if p['status'] == 'OPEN']
    closed_positions = [p for p in positions if p['status'] == 'CLOSED']
    
    # Update open positions with current prices
    for pos in open_positions:
        current_price = get_current_price(pos['contract'])
        if current_price:
            pos['current_price'] = current_price
            pos['current_pnl_pct'] = (current_price / pos['entry_price'] - 1) * 100
            pos['current_pnl_usd'] = pos['size_usd'] * (pos['current_pnl_pct'] / 100)
        else:
            pos['current_price'] = pos['entry_price']
            pos['current_pnl_pct'] = 0
            pos['current_pnl_usd'] = 0
        
        # Time held
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_held = (datetime.now() - entry_time).total_seconds() / 3600
        pos['hours_held'] = round(hours_held, 1)
        pos['time_ago'] = time_ago(pos['entry_time'])
    
    # Add time_ago to closed positions
    for pos in closed_positions:
        pos['time_ago'] = time_ago(pos.get('exit_time', pos['entry_time']))
    
    # Calculate metrics
    total_pnl = balance - STARTING_BALANCE
    total_pnl_pct = (total_pnl / STARTING_BALANCE) * 100
    
    winners = [p for p in closed_positions if p.get('pnl_usd', 0) > 0]
    win_rate = (len(winners) / len(closed_positions) * 100) if closed_positions else 0
    
    target_hits = [p for p in closed_positions if p.get('exit_reason') == 'TARGET_HIT']
    target_hit_rate = (len(target_hits) / len(closed_positions) * 100) if closed_positions else 0
    
    # Best/worst trades
    best_trade = max(closed_positions, key=lambda p: p.get('pnl_usd', 0)) if closed_positions else None
    worst_trade = min(closed_positions, key=lambda p: p.get('pnl_usd', 0)) if closed_positions else None
    
    # Performance by channel
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
        target_pct = (stats['targets'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        channels_list.append({
            'channel': channel,
            'trades': stats['trades'],
            'win_pct': round(win_pct, 1),
            'target_pct': round(target_pct, 1),
            'pnl': round(stats['pnl'], 2)
        })
    
    # Balance history (from closed trades)
    balance_history = [{'time': 0, 'balance': STARTING_BALANCE}]
    running_balance = STARTING_BALANCE
    for pos in sorted(closed_positions, key=lambda p: p.get('exit_time', '')):
        if pos.get('exit_time'):
            running_balance += pos.get('pnl_usd', 0)
            balance_history.append({
                'time': pos['exit_time'],
                'balance': round(running_balance, 2)
            })
    
    return jsonify({
        'balance': round(balance, 2),
        'starting_balance': STARTING_BALANCE,
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'open_positions': open_positions,
        'closed_positions': sorted(closed_positions, key=lambda p: p.get('exit_time', ''), reverse=True)[:20],
        'total_signals': len(signals),
        'total_rejections': len(rejections),
        'total_trades': len(positions),
        'open_count': len(open_positions),
        'closed_count': len(closed_positions),
        'win_rate': round(win_rate, 1),
        'target_hit_rate': round(target_hit_rate, 1),
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'channels': channels_list,
        'balance_history': balance_history,
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
        <h1>🤖 Autonomous Memecoin Hunter</h1>
        <div class="status" id="status">Loading...</div>
        
        <div class="metrics" id="metrics"></div>
        
        <div class="section">
            <div class="section-title">📊 Balance History</div>
            <div class="chart-container">
                <canvas id="balanceChart"></canvas>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">🔥 Open Positions (<span id="open-count">0</span>)</div>
            <div id="open-positions"></div>
        </div>
        
        <div class="section">
            <div class="section-title">📜 Recent Closed Trades (<span id="closed-count">0</span>)</div>
            <div id="closed-trades"></div>
        </div>
        
        <div class="section">
            <div class="section-title">📡 Performance by Channel</div>
            <div id="channels"></div>
        </div>
    </div>
    
    <script>
        let balanceChart = null;
        
        function formatMoney(val) {
            return '$' + val.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        
        function formatPct(val) {
            return (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
        }
        
        function truncate(str, len) {
            return str.length > len ? str.substring(0, len) + '...' : str;
        }
        
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
                        ${data.open_count} open · ${data.closed_count} closed
                    </div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value ${data.win_rate >= 55 ? 'positive' : data.win_rate < 45 ? 'negative' : 'neutral'}">
                        ${data.win_rate.toFixed(1)}%
                    </div>
                    <div class="metric-change neutral">
                        Target: ≥55%
                    </div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">2x Hit Rate</div>
                    <div class="metric-value ${data.target_hit_rate >= 30 ? 'positive' : 'neutral'}">
                        ${data.target_hit_rate.toFixed(1)}%
                    </div>
                    <div class="metric-change neutral">
                        Target: ≥30%
                    </div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">Signals Detected</div>
                    <div class="metric-value">${data.total_signals}</div>
                    <div class="metric-change neutral">
                        ${data.total_rejections} rejected
                    </div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">Best Trade</div>
                    <div class="metric-value positive">
                        ${data.best_trade ? formatMoney(data.best_trade.pnl_usd) : '-'}
                    </div>
                    <div class="metric-change neutral">
                        ${data.best_trade ? formatPct(data.best_trade.pnl_pct) : 'No trades yet'}
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
            
            let html = '<table><thead><tr>';
            html += '<th>Contract</th><th>Entry</th><th>Current</th><th>P&L</th><th>Time Held</th><th>Target</th></tr></thead><tbody>';
            
            positions.forEach(pos => {
                const pnlClass = pos.current_pnl_usd >= 0 ? 'positive' : 'negative';
                html += '<tr>';
                html += `<td><span class="contract">${truncate(pos.contract, 12)}</span></td>`;
                html += `<td>${formatMoney(pos.entry_price)}</td>`;
                html += `<td>${formatMoney(pos.current_price)}</td>`;
                html += `<td class="${pnlClass}">${formatMoney(pos.current_pnl_usd)} (${formatPct(pos.current_pnl_pct)})</td>`;
                html += `<td>${pos.hours_held}h</td>`;
                html += `<td>${formatMoney(pos.target_price)}</td>`;
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
            
            let html = '<table><thead><tr>';
            html += '<th>Contract</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th><th>Time</th></tr></thead><tbody>';
            
            trades.forEach(trade => {
                const pnlClass = trade.pnl_usd >= 0 ? 'positive' : 'negative';
                const badgeClass = trade.exit_reason === 'TARGET_HIT' ? 'badge-success' : 
                                   trade.exit_reason === 'STOP_LOSS' ? 'badge-danger' : 'badge-warning';
                
                html += '<tr>';
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
            
            let html = '<table><thead><tr>';
            html += '<th>Channel</th><th>Trades</th><th>Win %</th><th>2x %</th><th>P&L</th></tr></thead><tbody>';
            
            channels.forEach(ch => {
                const pnlClass = ch.pnl >= 0 ? 'positive' : 'negative';
                html += '<tr>';
                html += `<td>${ch.channel}</td>`;
                html += `<td>${ch.trades}</td>`;
                html += `<td>${ch.win_pct}%</td>`;
                html += `<td>${ch.target_pct}%</td>`;
                html += `<td class="${pnlClass}">${formatMoney(ch.pnl)}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            document.getElementById('channels').innerHTML = html;
        }
        
        function renderBalanceChart(history) {
            const ctx = document.getElementById('balanceChart').getContext('2d');
            
            if (balanceChart) {
                balanceChart.destroy();
            }
            
            const labels = history.map((h, i) => i === 0 ? 'Start' : `Trade ${i}`);
            const data = history.map(h => h.balance);
            
            balanceChart = new Chart(ctx, {
                type: 'line',
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
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            ticks: { color: '#888' },
                            grid: { color: '#1f2937' }
                        },
                        x: {
                            ticks: { color: '#888' },
                            grid: { color: '#1f2937' }
                        }
                    }
                }
            });
        }
        
        async function fetchData() {
            try {
                const resp = await fetch('/api/data');
                const data = await resp.json();
                
                document.getElementById('status').innerHTML = 
                    `Paper Trading Mode · Last update: ${new Date(data.last_update).toLocaleString()}`;
                
                renderMetrics(data);
                renderOpenPositions(data.open_positions);
                renderClosedTrades(data.closed_positions);
                renderChannels(data.channels);
                renderBalanceChart(data.balance_history);
                
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
    print("🚀 Starting Memecoin Hunter Dashboard on http://0.0.0.0:8899")
    print("📊 Access via: http://omen-claw.tail76e7df.ts.net:8899/")
    app.run(host='0.0.0.0', port=8899, debug=False)
