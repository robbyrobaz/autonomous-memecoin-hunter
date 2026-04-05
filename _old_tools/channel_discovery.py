#!/usr/bin/env python3
"""
Telegram Channel Discovery Tool
Tests 100+ Solana/memecoin channels to find active ones
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from telethon import TelegramClient
from telethon.tl.types import Channel
from dotenv import load_dotenv

# Load environment
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

# Telegram API credentials
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')

# Output
RESULTS_FILE = BASE_DIR / 'channel_discovery_results.json'

# Candidate channels (compiled from various sources - Reddit, X, Telegram directories)
# Testing username variants: @name, name, @Name
CANDIDATE_CHANNELS = [
    # Known working (baseline)
    '@gmgnsignals',
    '@XAceCalls',
    '@batman_gem',
    
    # High-reputation channels (commonly mentioned)
    '@cryptogems100x',
    '@SolanaGems',
    '@solana_gems',
    '@SolanaGemsCalls',
    '@solanamemecoins',
    '@SolanaMemeCoins',
    '@MoonShotCalls',
    '@moonshotcalls',
    '@PumpFunAlerts',
    '@pumpfunalerts',
    '@raydiumalerts',
    '@RaydiumAlerts',
    '@dexscreeneralerts',
    '@DexScreenerAlerts',
    
    # Alpha/research groups
    '@SolAlphaGroup',
    '@solalphagroup',
    '@CryptoAlphaCalls',
    '@alphagemhunters',
    '@AlphaGemHunters',
    '@whaletracker_alerts',
    '@WhaleTrackerAlerts',
    
    # KOL/influencer channels
    '@ansemcalls',
    '@AnsemCalls',
    '@muradcalls',
    '@MuradCalls',
    '@cryptokol',
    '@CryptoKOL',
    '@solanaflip',
    '@SolanaFlip',
    
    # Pump.fun specific
    '@pumpfunsignals',
    '@PumpFunSignals',
    '@pumpfungems',
    '@PumpFunGems',
    '@pumpfunnew',
    '@PumpFunNew',
    '@pump_monitor',
    
    # Raydium/DEX focused
    '@raydiumgems',
    '@RaydiumGems',
    '@raydiumsignals',
    '@RaydiumSignals',
    '@dexalerts',
    '@DexAlerts',
    
    # Community channels
    '@soltrending',
    '@SolTrending',
    '@solanacommunity',
    '@SolanaCommunity',
    '@solanawhales',
    '@SolanaWhales',
    '@cryptomoonshots_signals',
    '@CryptoMoonShotsSignals',
    
    # New/trending
    '@fresh_solana_gems',
    '@FreshSolanaGems',
    '@early_solana',
    '@EarlySolana',
    '@solana_early_gems',
    '@new_dex_listings',
    '@NewDexListings',
    
    # Volume/whale tracking
    '@highvolumealerts',
    '@HighVolumeAlerts',
    '@whale_alert_solana',
    '@WhaleAlertSolana',
    '@biggainers',
    '@BigGainers',
    
    # Multi-chain (but Solana-heavy)
    '@multichainGems',
    '@MultiChainGems',
    '@crosschaincalls',
    '@CrossChainCalls',
    
    # Research/analytics
    '@solanacharts',
    '@SolanaCharts',
    '@solanaanalytics',
    '@SolanaAnalytics',
    '@tokenmetrics_sol',
    '@TokenMetricsSol',
    
    # Low-cap hunters
    '@lowcapgems',
    '@LowCapGems',
    '@microcapgems',
    '@MicroCapGems',
    '@hidden_gems_sol',
    '@HiddenGemsSol',
    
    # Specific strategies
    '@fairlaunchonly',
    '@FairLaunchOnly',
    '@presale_alerts',
    '@PresaleAlerts',
    '@stealth_launch',
    '@StealthLaunch',
]


def extract_contract_address(text: str) -> Optional[str]:
    """Extract Solana contract address from message"""
    if not text:
        return None
    
    # Solana addresses are 32-44 chars, base58
    pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    matches = re.findall(pattern, text)
    
    for match in matches:
        # Filter out common false positives
        if match.lower() not in ['sol', 'usdc', 'usdt', 'wsol']:
            return match
    return None


async def test_channel(client: TelegramClient, channel_name: str) -> Optional[Dict]:
    """Test if a channel exists and is active"""
    
    # Try all variants
    variants = [
        channel_name,
        channel_name.lstrip('@'),
        '@' + channel_name.lstrip('@'),
        channel_name.lower(),
        '@' + channel_name.lstrip('@').lower(),
    ]
    
    for variant in variants:
        try:
            entity = await client.get_entity(variant)
            
            # Check if it's actually a channel
            if not isinstance(entity, Channel):
                continue
            
            # Get recent messages (last 24h, max 100)
            messages = await client.get_messages(entity, limit=100)
            
            # Count activity metrics
            now = datetime.now(entity.date.tzinfo)
            last_24h = now - timedelta(hours=24)
            
            recent_messages = [m for m in messages if m.date > last_24h]
            contracts_found = [extract_contract_address(m.message) for m in recent_messages if m.message]
            contracts_found = [c for c in contracts_found if c]
            
            if not recent_messages:
                # Dead channel
                continue
            
            # Calculate stats
            last_post = messages[0].date if messages else None
            hours_since_post = (now - last_post).total_seconds() / 3600 if last_post else 999
            
            result = {
                'username': variant,
                'title': entity.title,
                'members': getattr(entity, 'participants_count', 0),
                'verified': getattr(entity, 'verified', False),
                'scam': getattr(entity, 'scam', False),
                'messages_24h': len(recent_messages),
                'contracts_24h': len(contracts_found),
                'last_post_hours_ago': round(hours_since_post, 1),
                'active': len(recent_messages) > 0 and hours_since_post < 24,
                'has_contracts': len(contracts_found) > 0,
                'sample_contracts': contracts_found[:3],  # First 3
            }
            
            return result
        
        except Exception as e:
            # Try next variant
            continue
    
    # None of the variants worked
    return None


async def discover_channels():
    """Test all candidate channels"""
    
    print(f"=== Telegram Channel Discovery ===")
    print(f"Testing {len(CANDIDATE_CHANNELS)} channels...\n")
    
    # Initialize client (reuse existing session)
    client = TelegramClient('memecoin_hunter', API_ID, API_HASH)
    await client.start()
    
    results = {
        'tested': [],
        'active': [],
        'dead': [],
        'not_found': [],
        'scam': [],
    }
    
    for i, channel in enumerate(CANDIDATE_CHANNELS, 1):
        print(f"[{i}/{len(CANDIDATE_CHANNELS)}] Testing {channel}...", end=' ')
        
        result = await test_channel(client, channel)
        
        if result is None:
            print("❌ Not found")
            results['not_found'].append(channel)
        elif result['scam']:
            print("⚠️  SCAM FLAG")
            results['scam'].append(result)
        elif not result['active']:
            print(f"💀 Dead (last post: {result['last_post_hours_ago']}h ago)")
            results['dead'].append(result)
        elif not result['has_contracts']:
            print(f"⚠️  Active but no contracts ({result['messages_24h']} msgs)")
            results['dead'].append(result)
        else:
            print(f"✅ ACTIVE - {result['contracts_24h']} contracts/day")
            results['active'].append(result)
        
        results['tested'].append(channel)
        
        # Rate limit courtesy
        await asyncio.sleep(1)
    
    await client.disconnect()
    
    # Save results
    with RESULTS_FILE.open('w') as f:
        # Convert sets to lists for JSON
        for category in results.values():
            if isinstance(category, list):
                for item in category:
                    if isinstance(item, dict) and 'sample_contracts' in item:
                        item['sample_contracts'] = list(item['sample_contracts'])
        
        json.dump(results, f, indent=2)
    
    # Print summary
    print(f"\n=== SUMMARY ===")
    print(f"Tested: {len(results['tested'])}")
    print(f"Active with contracts: {len(results['active'])}")
    print(f"Dead/inactive: {len(results['dead'])}")
    print(f"Not found: {len(results['not_found'])}")
    print(f"Scam flagged: {len(results['scam'])}")
    
    # Top 15 by contracts/day
    if results['active']:
        print(f"\n=== TOP 15 ACTIVE CHANNELS ===")
        top_channels = sorted(results['active'], key=lambda x: x['contracts_24h'], reverse=True)[:15]
        
        for i, ch in enumerate(top_channels, 1):
            print(f"{i}. {ch['username']}")
            print(f"   Title: {ch['title']}")
            print(f"   Members: {ch['members']:,}")
            print(f"   Contracts/24h: {ch['contracts_24h']}")
            print(f"   Messages/24h: {ch['messages_24h']}")
            print()
    
    print(f"\n✅ Results saved to {RESULTS_FILE}")
    
    return results


if __name__ == '__main__':
    asyncio.run(discover_channels())
