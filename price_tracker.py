#!/usr/bin/env python3
"""
Price Tracker Service for Memecoin Signals
Monitors all signaled memecoins with periodic price snapshots via Dexscreener.
Tracks contracts for 24h after first signal, then expires them.
"""

import gzip
import json
import os
import sys
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/rob/.openclaw/workspace/autonomous-memecoin-hunter")
SIGNALS_FILE = BASE_DIR / "logs" / "signals.jsonl"
SNAPSHOTS_FILE = BASE_DIR / "data" / "price_snapshots.jsonl"
ARCHIVE_DIR    = BASE_DIR / "data" / "snapshots_archive"
CYCLE_INTERVAL = 300  # 5 minutes
TRACK_DURATION = timedelta(hours=24)
BATCH_SIZE = 30
BATCH_DELAY = 1.0  # seconds between API calls
DEXSCREENER_URL = "https://api.dexscreener.com/tokens/v1/solana/{addresses}"

# Early snapshot: capture price 3-15 min after signal (before regular ~17min cycle)
EARLY_SNAP_AFTER_S   = 180    # 3 min — don't fetch before token is discoverable
EARLY_SNAP_TIMEOUT_S = 2400   # 40 min — main cycle takes ~22 min; keep until next check

# Archive rotation: entries older than this move to dated gzip archives every 6h.
# Main file stays ~24h of data; archives accumulate indefinitely for backtesting.
ARCHIVE_AFTER_HOURS = 24      # move entries older than 24h to daily archive
ARCHIVE_ROTATE_CYCLES = 72    # rotate every 72 cycles × 5min = 6 hours

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
# early snapshot queue: contract -> unix timestamp when first seen (incremental only)
early_queue: dict[str, float] = {}
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
    """Load contracts from signals.jsonl. Returns count of new contracts added.
    On incremental loads, newly-seen contracts are also added to early_queue."""
    global signals_file_pos
    if not SIGNALS_FILE.exists():
        log.warning("Signals file not found: %s", SIGNALS_FILE)
        return 0

    new_count = 0
    now_unix = time.time()
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
                # Queue early snapshot only for incremental loads (not historical backfill)
                if not initial:
                    early_queue[contract] = now_unix
        signals_file_pos = f.tell()
    return new_count


def expire_old_contracts() -> int:
    """Remove contracts older than 24h. Returns count expired."""
    now = datetime.now(timezone.utc)
    expired = [c for c, ts in tracked_contracts.items() if now - ts > TRACK_DURATION]
    for c in expired:
        del tracked_contracts[c]
    return len(expired)


def rotate_snapshots() -> None:
    """Move entries older than ARCHIVE_AFTER_HOURS from price_snapshots.jsonl into
    dated gzip archives under data/snapshots_archive/price_snapshots_YYYY-MM-DD.jsonl.gz.

    Archives accumulate indefinitely — use them for backtesting.
    Main file stays small (~24h of data).
    Runs at startup and every ARCHIVE_ROTATE_CYCLES cycles (~6h).
    """
    if not SNAPSHOTS_FILE.exists():
        return

    cutoff_str = (datetime.now(timezone.utc) - timedelta(hours=ARCHIVE_AFTER_HOURS)).isoformat()
    size_mb = SNAPSHOTS_FILE.stat().st_size / (1024 * 1024)

    keep: list[str] = []
    archive_by_date: dict[str, list[str]] = defaultdict(list)

    with open(SNAPSHOTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
                ts = snap.get("timestamp", "")
                if ts < cutoff_str:
                    date_key = ts[:10]  # YYYY-MM-DD
                    archive_by_date[date_key].append(line)
                else:
                    keep.append(line)
            except json.JSONDecodeError:
                pass  # drop malformed lines

    if not archive_by_date:
        return  # nothing old enough to archive

    # Append to dated gzip archives (create or extend)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for date_key, lines in sorted(archive_by_date.items()):
        archive_path = ARCHIVE_DIR / f"price_snapshots_{date_key}.jsonl.gz"
        mode = "ab" if archive_path.exists() else "wb"
        with gzip.open(archive_path, mode) as gz:
            for line in lines:
                gz.write((line + "\n").encode())

    # Rewrite main file with only recent entries
    tmp = SNAPSHOTS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for line in keep:
            f.write(line + "\n")
    tmp.rename(SNAPSHOTS_FILE)

    new_mb = SNAPSHOTS_FILE.stat().st_size / (1024 * 1024)
    archived_total = sum(len(v) for v in archive_by_date.values())
    archive_files = ", ".join(sorted(archive_by_date.keys()))
    log.info(
        "Snapshot rotate: %.0f MB → %.0f MB | %d entries archived to [%s] | %d entries kept",
        size_mb, new_mb, archived_total, archive_files, len(keep),
    )


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


def snapshot_early_queue() -> int:
    """Snapshot tokens 3-15 min after signal. Returns count of early snapshots written."""
    if not early_queue:
        return 0

    now = time.time()
    ready    = [c for c, t in early_queue.items() if now - t >= EARLY_SNAP_AFTER_S]
    timed_out = [c for c, t in early_queue.items() if now - t >= EARLY_SNAP_TIMEOUT_S]

    # Drop anything past the early window without snapshotting
    for c in timed_out:
        early_queue.pop(c, None)
        ready[:] = [r for r in ready if r != c]

    if not ready:
        return 0

    log.info("Early snapshot: %d tokens ready (queue size %d, %d timed out)", len(ready), len(early_queue), len(timed_out))

    ts_now = datetime.now(timezone.utc).isoformat()
    best_by_contract: dict[str, dict] = {}

    for i in range(0, len(ready), BATCH_SIZE):
        batch = ready[i : i + BATCH_SIZE]
        pairs = fetch_prices(batch)

        for pair in pairs:
            base = pair.get("baseToken", {})
            contract = base.get("address", "")
            if not contract:
                continue
            if contract not in early_queue:
                for c in batch:
                    if c.lower() == contract.lower():
                        contract = c
                        break
                else:
                    continue

            liq = pair.get("liquidity", {})
            price_change = pair.get("priceChange", {})
            snap = {
                "timestamp": ts_now,
                "contract": contract,
                "price_usd": safe_float(pair.get("priceUsd")),
                "liquidity_usd": safe_float(liq.get("usd") if isinstance(liq, dict) else liq),
                "volume_24h": safe_float(pair.get("volume", {}).get("h24") if isinstance(pair.get("volume"), dict) else 0),
                "fdv": safe_float(pair.get("fdv")),
                "price_change_5m": safe_float(price_change.get("m5") if isinstance(price_change, dict) else 0),
                "price_change_1h": safe_float(price_change.get("h1") if isinstance(price_change, dict) else 0),
                "snapshot_type": "early",
                "age_s": int(now - early_queue.get(contract, now)),
            }
            existing = best_by_contract.get(contract)
            if existing is None or snap["liquidity_usd"] > existing["liquidity_usd"]:
                best_by_contract[contract] = snap

        if i + BATCH_SIZE < len(ready):
            time.sleep(BATCH_DELAY)

    snapshots = list(best_by_contract.values())
    if snapshots:
        SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SNAPSHOTS_FILE, "a") as f:
            for snap in snapshots:
                f.write(json.dumps(snap) + "\n")

    # Remove snapshotted contracts from early_queue
    for snap in snapshots:
        early_queue.pop(snap["contract"], None)

    # Also remove any ready contracts that returned no pair data (token not yet on Dex)
    for c in ready:
        early_queue.pop(c, None)

    log.info("Early snapshot complete: %d snapshots written", len(snapshots))
    return len(snapshots)


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

    # Rotate old snapshots into dated archives at startup
    rotate_snapshots()

    # Initial load
    new = load_signals(initial=True)
    expired = expire_old_contracts()
    log.info("Initial load: %d contracts loaded, %d already expired", new, expired)

    cycles = 0
    while True:
        cycles += 1
        try:
            # Periodic archive rotation: every 72 cycles (~6h at 5-min intervals)
            if cycles % ARCHIVE_ROTATE_CYCLES == 0:
                rotate_snapshots()

            # Check for new signals
            new_signals = load_signals(initial=False)
            if new_signals:
                log.info("Loaded %d new contract(s) from signals", new_signals)

            # Expire old contracts
            expired = expire_old_contracts()

            # Early snapshots: capture tokens 3-15 min after signal
            early_count = snapshot_early_queue()

            # Snapshot prices
            snapshot_count = snapshot_prices()

            # Summary
            log.info(
                "Cycle complete: %d contracts tracked, %d new snapshots (%d early), %d expired",
                len(tracked_contracts),
                snapshot_count,
                early_count,
                expired,
            )

        except Exception as e:
            log.error("Error in tracking cycle: %s", e, exc_info=True)

        # Sleep for 5 minutes
        log.info("Sleeping %d seconds until next cycle...", CYCLE_INTERVAL)
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
