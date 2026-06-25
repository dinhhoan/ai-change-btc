from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime

from ..models import WhaleDirection, WhaleTransfer


class EtherscanClient:
    def __init__(self, api_key: str, chainid: str = "1", base_url: str = "https://api.etherscan.io/v2/api") -> None:
        self.api_key = api_key
        self.chainid = chainid
        self.base_url = base_url

    def token_transfers(
        self,
        address: str,
        contractaddress: str | None = None,
        page: int = 1,
        offset: int = 25,
        sort: str = "desc",
    ) -> list[dict]:
        params = {
            "chainid": self.chainid,
            "module": "account",
            "action": "tokentx",
            "address": address,
            "page": page,
            "offset": offset,
            "sort": sort,
            "apikey": self.api_key,
        }
        if contractaddress:
            params["contractaddress"] = contractaddress
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "whale-signal-lab/0.1"})
        with urllib.request.urlopen(request, timeout=15.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "0" and "No transactions found" in str(payload.get("message", "")):
            return []
        if payload.get("status") != "1":
            raise RuntimeError(f"Etherscan error: {payload}")
        result = payload.get("result", [])
        if not isinstance(result, list):
            raise RuntimeError(f"Unexpected Etherscan payload: {payload}")
        return result


def convert_token_transfer(
    raw: dict,
    watched_wallet: str,
    exchange_addresses: dict[str, str],
    price_by_token: dict[str, float],
    chain: str = "ethereum",
) -> WhaleTransfer:
    wallet = watched_wallet.lower()
    from_addr = str(raw.get("from", "")).lower()
    to_addr = str(raw.get("to", "")).lower()
    exchange_lookup = {address.lower(): label for label, address in exchange_addresses.items()}

    if to_addr in exchange_lookup:
        direction = WhaleDirection.EXCHANGE_INFLOW
        counterparty = to_addr
        counterparty_label = exchange_lookup[to_addr]
    elif from_addr in exchange_lookup:
        direction = WhaleDirection.EXCHANGE_OUTFLOW
        counterparty = from_addr
        counterparty_label = exchange_lookup[from_addr]
    elif to_addr == wallet:
        direction = WhaleDirection.WHALE_IN
        counterparty = from_addr
        counterparty_label = "unknown"
    elif from_addr == wallet:
        direction = WhaleDirection.WHALE_OUT
        counterparty = to_addr
        counterparty_label = "unknown"
    else:
        direction = WhaleDirection.WALLET_TO_WALLET
        counterparty = to_addr
        counterparty_label = "unknown"

    decimals = int(raw.get("tokenDecimal") or 0)
    amount = int(raw.get("value") or 0) / (10**decimals if decimals else 1)
    token_symbol = str(raw.get("tokenSymbol") or "").upper()
    token_price = price_by_token.get(token_symbol, 0.0)
    timestamp = datetime.fromtimestamp(int(raw.get("timeStamp", "0")), UTC)
    return WhaleTransfer(
        chain=chain,
        tx_hash=str(raw.get("hash", "")),
        wallet=wallet,
        counterparty=counterparty,
        token_symbol=token_symbol,
        token_contract=raw.get("contractAddress"),
        amount=amount,
        usd_value=amount * token_price,
        direction=direction,
        timestamp=timestamp,
        labels={"counterparty": counterparty_label},
    )


def fetch_recent_whale_transfers(
    client: EtherscanClient,
    wallets: Iterable[tuple[str, str]],
    exchange_addresses: dict[str, str],
    price_by_token: dict[str, float],
    min_usd: float,
) -> list[WhaleTransfer]:
    transfers: list[WhaleTransfer] = []
    seen_hashes: set[str] = set()
    for _, address in wallets:
        for raw in client.token_transfers(address):
            event = convert_token_transfer(raw, address, exchange_addresses, price_by_token)
            if event.tx_hash in seen_hashes:
                continue
            seen_hashes.add(event.tx_hash)
            if event.usd_value >= min_usd:
                transfers.append(event)
    return transfers

