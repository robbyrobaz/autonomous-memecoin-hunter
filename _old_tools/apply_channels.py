#!/usr/bin/env python3
"""
Apply discovered channels to scanner.py
Automatically updates CHANNELS list with top N active channels
"""

import json
import re
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / 'channel_discovery_results.json'
SCANNER_FILE = Path(__file__).parent / 'scanner.py'
TOP_N = 15  # How many channels to use


def update_scanner(top_channels):
    """Update scanner.py with new channel list"""
    
    # Read current scanner
    scanner_code = SCANNER_FILE.read_text()
    
    # Build new CHANNELS list
    new_channels_code = "CHANNELS = [\n"
    for ch in top_channels:
        username = ch['username']
        contracts = ch['contracts_24h']
        title = ch['title'][:40]  # Truncate long titles
        new_channels_code += f"    '{username}',  # {contracts} contracts/day - {title}\n"
    new_channels_code += "]\n"
    
    # Replace old CHANNELS definition
    pattern = r'CHANNELS = \[.*?\]'
    new_code = re.sub(pattern, new_channels_code.rstrip(), scanner_code, flags=re.DOTALL)
    
    # Write back
    SCANNER_FILE.write_text(new_code)
    
    print(f"✅ Updated {SCANNER_FILE} with {len(top_channels)} channels")


def main():
    if not RESULTS_FILE.exists():
        print(f"❌ Results file not found: {RESULTS_FILE}")
        print("Run channel_discovery.py first!")
        return
    
    # Load results
    with RESULTS_FILE.open() as f:
        results = json.load(f)
    
    if not results['active']:
        print("❌ No active channels found in results")
        return
    
    # Get top N by contracts/day
    top_channels = sorted(results['active'], key=lambda x: x['contracts_24h'], reverse=True)[:TOP_N]
    
    print(f"=== Applying Top {len(top_channels)} Channels ===\n")
    for i, ch in enumerate(top_channels, 1):
        print(f"{i}. {ch['username']} - {ch['contracts_24h']} contracts/day")
    
    # Update scanner
    update_scanner(top_channels)
    
    print(f"\n✅ Scanner updated successfully")
    print(f"Old channel count: 3")
    print(f"New channel count: {len(top_channels)}")


if __name__ == '__main__':
    main()
