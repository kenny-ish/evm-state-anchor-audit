#!/usr/bin/env python3
"""Compare block and hash-anchored EVM state across JSON-RPC providers."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional


Json = Any


def quantity(value: Any) -> int:
    """Parse a JSON-RPC quantity or an integer."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a quantity")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    raise ValueError("invalid quantity")


def block_tag(value: str) -> str:
    number = quantity(value)
    if number < 0:
        raise ValueError("block must not be negative")
    return hex(number)


def normalize_address(value: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError("address must be a 20-byte 0x-prefixed value")
    try:
        int(value[2:], 16)
    except ValueError as exc:
        raise ValueError("address contains non-hex characters") from exc
    return "0x" + value[2:].lower()


def rpc_call(
    rpc_url: str,
    method: str,
    params: List[Json],
    transport: Optional[Callable[[str, str, List[Json]], Json]] = None,
) -> Json:
    """Call JSON-RPC, or use an injected transport in tests."""
    if transport is not None:
        response = transport(rpc_url, method, params)
    else:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params,
            }
        ).encode()
        request = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "evm-state-anchor-audit/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as handle:
            response = json.load(handle)

    if not isinstance(response, dict):
        raise RuntimeError("RPC response is not an object")

    if response.get("error") is not None:
        error = response["error"]
        message = error.get("message", "RPC error") if isinstance(error, dict) else str(error)
        raise RuntimeError(message)

    if "result" not in response:
        raise RuntimeError("RPC response has no result")

    return response["result"]


def short_code(code: str) -> Dict[str, Any]:
    if not isinstance(code, str) or not code.startswith("0x"):
        raise ValueError("eth_getCode did not return a hex string")
    return {
        "bytes": max(0, (len(code) - 2) // 2),
        "prefix": code[:18],
    }


def block_summary(block: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(block, dict):
        raise ValueError("block result is not an object")
    if not block.get("hash") or block.get("number") is None:
        raise ValueError("incomplete block result")

    return {
        "number": quantity(block["number"]),
        "hash": block["hash"].lower(),
    }


def compare_values(records: Iterable[Dict[str, Any]], path: str) -> str:
    values = []

    for record in records:
        value: Any = record
        try:
            for part in path.split("."):
                value = value[part]
        except (KeyError, TypeError):
            continue

        if value is not None:
            values.append(value)

    if not values:
        return "unavailable"

    return "match" if all(value == values[0] for value in values[1:]) else "mismatch"


def audit_provider(
    rpc_url: str,
    requested_block: str,
    address: str,
    transport: Optional[Callable[[str, str, List[Json]], Json]] = None,
) -> Dict[str, Any]:
    tag = block_tag(requested_block)
    result: Dict[str, Any] = {"rpc": rpc_url}

    try:
        chain_id = rpc_call(rpc_url, "eth_chainId", [], transport)
        head = quantity(rpc_call(rpc_url, "eth_blockNumber", [], transport))

        by_number = rpc_call(
            rpc_url,
            "eth_getBlockByNumber",
            [tag, False],
            transport,
        )
        target = block_summary(by_number)

        by_hash = rpc_call(
            rpc_url,
            "eth_getBlockByHash",
            [target["hash"], False],
            transport,
        )
        hash_target = block_summary(by_hash)

        result.update(
            {
                "chain_id": chain_id,
                "head": {
                    "number": head,
                    "lag": head - target["number"],
                },
                "block_lookup": "match" if target == hash_target else "mismatch",
                "block": target,
            }
        )

        hash_selector = {
            "blockHash": target["hash"],
            "requireCanonical": True,
        }
        errors = []

        def read_state(
            method: str,
            formatter: Callable[[Json], Json],
        ) -> Dict[str, Any]:
            values: Dict[str, Any] = {}

            for label, selector in (
                ("by_number", tag),
                ("by_hash", hash_selector),
            ):
                try:
                    values[label] = formatter(
                        rpc_call(
                            rpc_url,
                            method,
                            [address, selector],
                            transport,
                        )
                    )
                except Exception as exc:
                    values[label] = None
                    errors.append(
                        {
                            "method": method,
                            "selector": label,
                            "error": str(exc),
                        }
                    )

            values["anchored"] = (
                values["by_number"] == values["by_hash"]
                if values["by_number"] is not None
                and values["by_hash"] is not None
                else None
            )
            return values

        result["state"] = {
            "balance": read_state("eth_getBalance", lambda value: value),
            "code": read_state("eth_getCode", short_code),
        }

        if errors:
            result["errors"] = errors
            result["verdict"] = "incomplete"
        else:
            result["verdict"] = (
                "consistent"
                if result["block_lookup"] == "match"
                and result["state"]["balance"]["anchored"]
                and result["state"]["code"]["anchored"]
                else "inconsistent"
            )

    except Exception as exc:
        result["verdict"] = "error"
        result["error"] = str(exc)

    return result


def audit(
    rpc_urls: List[str],
    block: str,
    address: str,
    transport: Optional[Callable[[str, str, List[Json]], Json]] = None,
) -> Dict[str, Any]:
    normalized = normalize_address(address)
    providers = [
        audit_provider(url, block, normalized, transport)
        for url in rpc_urls
    ]
    successful = [
        item for item in providers
        if item.get("verdict") != "error"
    ]
    first = successful[0] if successful else {}

    return {
        "block": {
            "number": quantity(block),
            "tag": block_tag(block),
            "hash": first.get("block", {}).get("hash"),
        },
        "providers": providers,
        "comparison": {
            "chain_id": compare_values(successful, "chain_id"),
            "block_hash": compare_values(successful, "block.hash"),
            "balance": compare_values(successful, "state.balance.by_hash"),
            "code": compare_values(successful, "state.code.by_hash"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rpc",
        action="append",
        required=True,
        help="JSON-RPC URL; repeat for each provider",
    )
    parser.add_argument(
        "--block",
        required=True,
        help="block number, decimal or hex quantity",
    )
    parser.add_argument(
        "--address",
        required=True,
        help="20-byte EVM address",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print compact JSON",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        report = audit(args.rpc, args.block, args.address)
    except (ValueError, urllib.error.URLError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            report,
            indent=None if args.json else 2,
            sort_keys=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
