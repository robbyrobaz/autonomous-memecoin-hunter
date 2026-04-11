#!/usr/bin/env python3
"""
Price Tracker Service for Memecoin Signals
Monitors all signaled memecoins with periodic price snapshots via Dexscreener.
Tracks contracts for 24h after first signal, then expires them.
"""

import json
import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/rob/.openclaw/workspace/autonomous-memecoin-hunter")
SIGNALS_FILE = BASE_DIR / "logs" / "signals.jsonl"
SNAPSHOTS_FILE = BASE_DIR / "data" / "price_snapshots.jsonl"
CYCLE_INTERVAL = 300  # 5 minutes
TRACK_DURATION = timedelta(hours=24)
BATCH_SIZE = 30
BATCH_DELAY = 1.0  # seconds between API calls
DEXSCREENER_URL = "https://api.dexscreener.com/tokens/v1/solana/{addresses}"

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("price_tracker")

# ── State ───────────────────────────────────────────────────────────────
# contract -> first_seen timestamp (datetime)
tracked_contracts: dict[str, datetime] = {}
# file position for incremental reading
signals_file_pos: int = 0


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp, handle with/without timezone."""
    ts_str = ts_str.strip()
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_signals(initial: bool = False) -> int:
    """Load contracts from signals.jsonl. Returns count of new contracts added."""
    global signals_file_pos
    if not SIGNALS_FILE.exists():
        log.warning("Signals file not found: %s", SIGNALS_FILE)
        return 0

    new_count = 0
    with open(SIGNALS_FILE, "r") as f:
        if not initial:
            f.seek(signals_file_pos)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            contract = entry.get("contract", "").strip()
            if not contract:
                continue
            ts = parse_timestamp(entry.get("timestamp", datetime.now(timezone.utc).isoformat()))
            if contract not in tracked_contracts:
                tracked_contracts[contract] = ts
                new_count += 1
        signals_file_pos = f.tell()
    return new_count


def expire_old_contracts() -> int:
    """Remove contracts older than 24h. Returns count expired."""
    now = datetime.now(timezone.utc)
    expired = [c for c, ts in tracked_contracts.items() if now - ts > TRACK_DURATION]
    for c in expired:
        del tracked_contracts[c]
    return len(expired)


def fetch_prices(addresses: list[str]) -> list[dict]:
    """Fetch prices from Dexscreener for a batch of addresses. Retries on 429."""
    url = DEXSCREENER_URL.format(addresses=",".join(addresses))
    backoffs = [5, 15, 30]
    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            time.sleep(wait)
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                if attempt < len(backoffs):
                    log.warning("Dexscreener 429 — retrying in %ds (attempt %d)", backoffs[attempt], attempt + 1)
                    continue
                log.error("Dexscreener 429 — giving up after %d retries", len(backoffs))
                return []
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("pairs", data.get("data", []))
            return []
        except requests.exceptions.RequestException as e:
            log.error("Dexscreener API error: %s", e)
            return []
    return []


def safe_float(val) -> float:
    """Convert value to float, return 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def snapshot_prices() -> int:
    """Snapshot prices for all active contracts. Returns count of snapshots written."""
    if not tracked_contracts:
        return 0

    contracts = list(tracked_contracts.keys())
    now = datetime.now(timezone.utc).isoformat()
    snapshots = []

    # Track which contracts we've already captured (pick best pair per token)
    best_by_contract: dict[str, dict] = {}

    # Batch in groups of BATCH_SIZE
    for i in range(0, len(contracts), BATCH_SIZE):
        batch = contracts[i : i + BATCH_SIZE]
        pairs = fetch_prices(batch)

        for pair in pairs:
            base = pair.get("baseToken", {})
            contract = base.get("address", "")
            if not contract:
                continue
            # Normalize: match against our tracked set (case-insensitive not needed for Solana)
            if contract not in tracked_contracts:
                # Try matching from the batch
                for c in batch:
                    if c.lower() == contract.lower():
                        contract = c
                        break
                else:
                    continue

            liq = pair.get("liquidity", {})
            price_change = pair.get("priceChange", {})

            snap = {
                "timestamp": now,
                "contract": contract,
                "price_usd": safe_float(pair.get("priceUsd")),
                "liquidity_usd": safe_float(liq.get("usd") if isinstance(liq, dict) else liq),
                "volume_24h": safe_float(pair.get("volume", {}).get("h24") if isinstance(pair.get("volume"), dict) else 0),
                "fdv": safe_float(pair.get("fdv")),
                "price_change_5m": safe_float(price_change.get("m5") if isinstance(price_change, dict) else 0),
                "price_change_1h": safe_float(price_change.get("h1") if isinstance(price_change, dict) else 0),
            }

            # Keep best pair per contract (highest liquidity)
            existing = best_by_contract.get(contract)
            if existing is None or snap["liquidity_usd"] > existing["liquidity_usd"]:
                best_by_contract[contract] = snap

        # Rate limit between batches
        if i + BATCH_SIZE < len(contracts):
            time.sleep(BATCH_DELAY)

    snapshots = list(best_by_contract.values())

    # Write snapshots
    if snapshots:
        SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SNAPSHOTS_FILE, "a") as f:
            for snap in snapshots:
                f.write(json.dumps(snap) + "\n")

    return len(snapshots)


def main():
    log.info("=== Memecoin Price Tracker Starting ===")
    log.info("Signals file: %s", SIGNALS_FILE)
    log.info("Snapshots file: %s", SNAPSHOTS_FILE)

    # Ensure data dir exists
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Initial load
    new = load_signals(initial=True)
    expired = expire_old_contracts()
    log.info("Initial load: %d contracts loaded, %d already expired", new, expired)

    while True:
        try:
            # Check for new signals
            new_signals = load_signals(initial=False)
            if new_signals:
                log.info("Loaded %d new contract(s) from signals", new_signals)

            # Expire old contracts
            expired = expire_old_contracts()

            # Snapshot prices
            snapshot_count = snapshot_prices()

            # Summary
            log.info(
                "Cycle complete: %d contracts tracked, %d new snapshots, %d expired",
                len(tracked_contracts),
                snapshot_count,
                expired,
            )

        except Exception as e:
            log.error("Error in tracking cycle: %s", e, exc_info=True)

        # Sleep for 5 minutes
        log.info("Sleeping %d seconds until next cycle...", CYCLE_INTERVAL)
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
