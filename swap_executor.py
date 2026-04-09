"""
Jupiter Swap Executor — executes real SOL↔token swaps on Solana mainnet.

Uses Jupiter V6 API for best price routing.
Hot wallet keypair at data/hot_wallet.json.
"""

import json
import time
import base64
import requests
from pathlib import Path
from typing import Optional, Tuple
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed

from pumpfun_executor import buy_pumpfun, sell_pumpfun

BASE_DIR = Path(__file__).parent
KEYPAIR_FILE = BASE_DIR / 'data' / 'hot_wallet.json'
# Jupiter V6 API — new domain (api.jup.ag), free at 0.5 RPS, no key needed
JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"
SOL_MINT = "So11111111111111111111111111111111111111112"
RPC_URL = "https://api.mainnet-beta.solana.com"

# Priority fee for faster inclusion (in lamports)
PRIORITY_FEE_LAMPORTS = 1_000_000  # 0.001 SOL

# Slippage in basis points (1% = 100 bps)
SLIPPAGE_BPS = 1000  # 10% slippage tolerance for memecoins


def load_keypair() -> Keypair:
    """Load hot wallet keypair from file."""
    with open(KEYPAIR_FILE) as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))


def get_wallet_address() -> str:
    """Get the hot wallet public address."""
    kp = load_keypair()
    return str(kp.pubkey())


def get_sol_balance() -> float:
    """Get SOL balance of hot wallet."""
    client = Client(RPC_URL)
    kp = load_keypair()
    resp = client.get_balance(kp.pubkey())
    return resp.value / 1_000_000_000


def get_quote(input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int = SLIPPAGE_BPS) -> Optional[dict]:
    """Get Jupiter swap quote."""
    try:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_lamports),
            "slippageBps": slippage_bps,
        }
        resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"❌ Jupiter quote error: {resp.status_code} {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        print(f"❌ Jupiter quote failed: {e}")
        return None


def execute_swap(input_mint: str, output_mint: str, amount_lamports: int, 
                 slippage_bps: int = SLIPPAGE_BPS) -> Tuple[bool, str, dict]:
    """
    Execute a swap via Jupiter.
    
    Returns: (success, tx_signature_or_error, details_dict)
    """
    kp = load_keypair()
    wallet = str(kp.pubkey())
    
    # Step 1: Get quote
    quote = get_quote(input_mint, output_mint, amount_lamports, slippage_bps)
    if not quote:
        return False, "Failed to get quote", {}
    
    in_amount = int(quote.get("inAmount", 0))
    out_amount = int(quote.get("outAmount", 0))
    price_impact = quote.get("priceImpactPct", "0")
    
    print(f"📊 Quote: {in_amount} → {out_amount} (impact: {price_impact}%)")
    
    # Step 2: Get swap transaction
    try:
        swap_body = {
            "quoteResponse": quote,
            "userPublicKey": wallet,
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": PRIORITY_FEE_LAMPORTS,
        }
        resp = requests.post(JUPITER_SWAP_URL, json=swap_body, timeout=30)
        if resp.status_code != 200:
            return False, f"Swap API error: {resp.status_code} {resp.text[:200]}", {"quote": quote}
        
        swap_data = resp.json()
        swap_tx_b64 = swap_data.get("swapTransaction")
        if not swap_tx_b64:
            return False, "No swapTransaction in response", {"quote": quote}
    except Exception as e:
        return False, f"Swap request failed: {e}", {"quote": quote}
    
    # Step 3: Deserialize, sign, and send
    try:
        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        
        # Sign the transaction
        signed_tx = VersionedTransaction(tx.message, [kp])
        
        # Send
        from solana.rpc.types import TxOpts
        client = Client(RPC_URL)
        tx_sig = client.send_transaction(
            signed_tx,
            opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
        )
        
        signature = str(tx_sig.value)
        print(f"✅ TX sent: {signature}")
        
        # Wait for confirmation (up to 30s)
        confirmed = False
        for i in range(15):
            time.sleep(2)
            status = client.get_signature_statuses([tx_sig.value])
            if status.value and status.value[0]:
                slot_status = status.value[0]
                if slot_status.err:
                    return False, f"TX failed on-chain: {slot_status.err}", {
                        "signature": signature,
                        "quote": quote,
                    }
                confirmed = True
                print(f"✅ Confirmed in {(i+1)*2}s")
                break
        
        if not confirmed:
            print(f"⚠️  TX sent but not confirmed after 30s: {signature}")
        
        details = {
            "signature": signature,
            "confirmed": confirmed,
            "in_amount": in_amount,
            "out_amount": out_amount,
            "price_impact_pct": price_impact,
            "input_mint": input_mint,
            "output_mint": output_mint,
        }
        
        return True, signature, details
        
    except Exception as e:
        return False, f"TX sign/send failed: {e}", {"quote": quote}


def buy_token(token_mint: str, sol_amount: float) -> Tuple[bool, str, dict]:
    """Buy a token with SOL."""
    # Route pumpfun tokens through PumpPortal
    if token_mint.endswith("pump"):
        print(f"🐸 Routing to PumpPortal (pumpfun token): {token_mint[:16]}...")
        result = buy_pumpfun(token_mint, sol_amount)
        if result and result.get("tx_hash"):
            return True, result["tx_hash"], result
        return False, "PumpPortal buy failed", {}

    lamports = int(sol_amount * 1_000_000_000)
    print(f"🛒 Buying {token_mint[:8]}... with {sol_amount} SOL ({lamports} lamports)")
    time.sleep(1)  # Rate limit protection for Jupiter
    return execute_swap(SOL_MINT, token_mint, lamports)


def sell_token(token_mint: str, token_amount_raw: int) -> Tuple[bool, str, dict]:
    """Sell a token back to SOL."""
    # Route pumpfun tokens through PumpPortal
    if token_mint.endswith("pump"):
        print(f"🐸 Routing to PumpPortal (pumpfun token): {token_mint[:16]}...")
        result = sell_pumpfun(token_mint, token_amount_raw)
        if result and result.get("tx_hash"):
            return True, result["tx_hash"], result
        return False, "PumpPortal sell failed", {}

    print(f"💰 Selling {token_mint[:8]}... ({token_amount_raw} raw tokens)")
    time.sleep(1)  # Rate limit protection for Jupiter
    return execute_swap(token_mint, SOL_MINT, token_amount_raw)


def sell_all_token(token_mint: str) -> Tuple[bool, str, dict]:
    """Sell entire token balance back to SOL."""
    # Route pumpfun tokens through PumpPortal
    if token_mint.endswith("pump"):
        try:
            kp = load_keypair()
            client = Client(RPC_URL)
            from solana.rpc.types import TokenAccountOpts
            resp = client.get_token_accounts_by_owner_json_parsed(
                kp.pubkey(),
                TokenAccountOpts(mint=Pubkey.from_string(token_mint)),
            )
            if not resp.value:
                return False, "No token account found", {}
            account_data = resp.value[0].account.data
            parsed = json.loads(account_data.to_json())
            token_amount = int(parsed["parsed"]["info"]["tokenAmount"]["amount"])
            if token_amount == 0:
                return False, "Zero token balance", {}
            print(f"🐸 Routing sell_all to PumpPortal: {token_amount} tokens of {token_mint[:16]}...")
            result = sell_pumpfun(token_mint, token_amount)
            if result and result.get("tx_hash"):
                return True, result["tx_hash"], result
            return False, "PumpPortal sell_all failed", {}
        except Exception as e:
            return False, f"PumpPortal sell_all failed: {e}", {}

    try:
        kp = load_keypair()
        client = Client(RPC_URL)
        
        # Get token accounts
        from solders.pubkey import Pubkey
        from solana.rpc.types import TokenAccountOpts
        resp = client.get_token_accounts_by_owner_json_parsed(
            kp.pubkey(),
            TokenAccountOpts(mint=Pubkey.from_string(token_mint)),
        )
        
        if not resp.value:
            return False, "No token account found", {}
        
        # Get balance from first account
        account_data = resp.value[0].account.data
        parsed = json.loads(account_data.to_json())
        token_amount = int(parsed["parsed"]["info"]["tokenAmount"]["amount"])
        
        if token_amount == 0:
            return False, "Zero token balance", {}
        
        print(f"💰 Selling all: {token_amount} raw tokens of {token_mint[:8]}...")
        return execute_swap(token_mint, SOL_MINT, token_amount)
        
    except Exception as e:
        return False, f"sell_all failed: {e}", {}


if __name__ == "__main__":
    # Quick status check
    addr = get_wallet_address()
    bal = get_sol_balance()
    print(f"🔑 Hot wallet: {addr}")
    print(f"💰 Balance: {bal:.4f} SOL")
    
    # Test quote only (no execution)
    print("\n--- Test Quote (SOL → USDC) ---")
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDj1v"
    quote = get_quote(SOL_MINT, USDC_MINT, 1_000_000)  # 0.001 SOL
    if quote:
        print(f"0.001 SOL → {int(quote['outAmount'])/1e6:.4f} USDC")
        print(f"Price impact: {quote.get('priceImpactPct', '?')}%")
    else:
        print("Quote failed")
