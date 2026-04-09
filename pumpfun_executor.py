"""
PumpFun Swap Executor — executes trades via PumpPortal Local Transaction API.

Uses pumpportal.fun/api/trade-local → sign with solders → send via Helius RPC.
No API key needed for PumpPortal. Supports pump, raydium, pump-amm, auto pools.

Adapted from reef-workspace/pumpfun_executor.py for the memecoin hunter.
Uses synchronous requests to match the hunter's existing swap_executor pattern.
"""

import base64
import json
import os
import requests
from pathlib import Path
from typing import Optional

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# ── Paths & Config ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
KEYPAIR_FILE = BASE_DIR / 'data' / 'hot_wallet.json'

PUMPPORTAL_API = "https://pumpportal.fun/api/trade-local"
SOL_MINT = "So11111111111111111111111111111111111111112"

# Helius RPC for faster tx landing — fall back to public RPC
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
if not HELIUS_API_KEY:
    # Try to read from reef .env as fallback
    _reef_env = Path.home() / "reef-workspace" / ".env"
    if _reef_env.exists():
        for line in _reef_env.read_text().splitlines():
            if line.startswith("HELIUS_API_KEY="):
                HELIUS_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if HELIUS_API_KEY:
    RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
else:
    RPC_URL = "https://api.mainnet-beta.solana.com"
    print("⚠️  No HELIUS_API_KEY found — using public RPC (slower)")

# Trade parameters
SLIPPAGE_PCT = 15       # 15% slippage for pumpfun tokens
PRIORITY_FEE_SOL = 0.001  # 0.001 SOL priority fee


def _load_keypair() -> Keypair:
    """Load hot wallet keypair from file (same as swap_executor)."""
    with open(KEYPAIR_FILE) as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))


def _send_via_rpc(signed_tx: VersionedTransaction) -> Optional[str]:
    """Send signed transaction via RPC. Returns signature or None."""
    tx_b64 = base64.b64encode(bytes(signed_tx)).decode()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            tx_b64,
            {
                "encoding": "base64",
                "skipPreFlight": True,
                "preflightCommitment": "processed",
                "maxRetries": 5,
            },
        ],
    }
    try:
        resp = requests.post(RPC_URL, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                return data["result"]
            elif "error" in data:
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                print(f"❌ RPC error: {msg[:200]}")
                return None
        else:
            print(f"❌ RPC HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"❌ RPC request failed: {e}")
        return None


def _execute_pumpportal(action: str, mint: str, amount: float, denominated_in_sol: bool = True) -> Optional[dict]:
    """
    Core PumpPortal execution.
    Returns dict with tx_hash on success, or None on failure.
    """
    kp = _load_keypair()

    # Step 1: Get unsigned transaction from PumpPortal
    try:
        body = {
            "publicKey": str(kp.pubkey()),
            "action": action,
            "mint": mint,
            "amount": amount,
            "denominatedInSol": "true" if denominated_in_sol else "false",
            "slippage": SLIPPAGE_PCT,
            "priorityFee": PRIORITY_FEE_SOL,
            "pool": "auto",
        }
        resp = requests.post(PUMPPORTAL_API, json=body, timeout=15)
        if resp.status_code != 200:
            print(f"❌ PumpPortal {resp.status_code}: {resp.text[:100]}")
            return None
        tx_bytes = resp.content
    except Exception as e:
        print(f"❌ PumpPortal request failed: {e}")
        return None

    if not tx_bytes or len(tx_bytes) < 50:
        print("❌ Empty/invalid tx from PumpPortal")
        return None

    # Step 2: Sign the transaction
    try:
        unsigned_tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(unsigned_tx.message, [kp])
    except Exception as e:
        print(f"❌ TX signing failed: {e}")
        return None

    # Step 3: Send via RPC
    sig = _send_via_rpc(signed_tx)
    if sig:
        print(f"✅ PumpPortal {action.upper()} sent: {mint[:16]}... | {sig[:20]}...")
        return {"tx_hash": sig, "mint": mint, "action": action, "amount": amount}
    return None


def buy_pumpfun(mint: str, sol_amount: float) -> Optional[dict]:
    """
    Buy a pumpfun token with SOL via PumpPortal.

    Args:
        mint: Token mint address
        sol_amount: Amount of SOL to spend

    Returns:
        dict with tx_hash, mint, action, amount on success; None on failure
    """
    print(f"🐸 PumpPortal BUY: {sol_amount:.4f} SOL → {mint[:16]}...")
    return _execute_pumpportal("buy", mint, sol_amount, denominated_in_sol=True)


def sell_pumpfun(mint: str, token_amount: int) -> Optional[dict]:
    """
    Sell a pumpfun token back to SOL via PumpPortal.

    Args:
        mint: Token mint address
        token_amount: Raw token amount to sell

    Returns:
        dict with tx_hash, mint, action, amount on success; None on failure
    """
    print(f"🐸 PumpPortal SELL: {token_amount} tokens of {mint[:16]}...")
    # For sells, amount is token quantity, not SOL
    return _execute_pumpportal("sell", mint, token_amount, denominated_in_sol=False)


if __name__ == "__main__":
    print(f"RPC URL: {RPC_URL[:50]}...")
    kp = _load_keypair()
    print(f"Wallet: {kp.pubkey()}")
    print(f"Slippage: {SLIPPAGE_PCT}%  Priority fee: {PRIORITY_FEE_SOL} SOL")
