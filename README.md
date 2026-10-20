# EVM State Anchor Audit

EVM State Anchor Audit checks whether several JSON-RPC providers return the same block and the same account state when a query is anchored by both a block number and an EIP-1898 block hash. It helps find providers that disagree, cannot serve historical state, or do not support hash-anchored reads.

## Example

The following is a real run against Ethereum mainnet on 2026-10-10 UTC. The fixed target block was 77 blocks behind the provider heads when the command ran.

```text
$ python evm_state_anchor_audit.py \
    --rpc https://ethereum-rpc.publicnode.com \
    --rpc https://eth.drpc.org \
    --block 0x18f2fe6 \
    --address 0x000000000000000000000000000000000000dEaD
{
  "block": {
    "number": 26161126,
    "tag": "0x18f2fe6",
    "hash": "0x6b4247350e952e32ad229df759e46dc406142e2a74e068a90e71179584e673d8"
  },
  "providers": [
    {
      "rpc": "https://ethereum-rpc.publicnode.com",
      "chain_id": "0x1",
      "head": {
        "number": 26161203,
        "lag": 77
      },
      "block_lookup": "match",
      "block": {
        "number": 26161126,
        "hash": "0x6b4247350e952e32ad229df759e46dc406142e2a74e068a90e71179584e673d8"
      },
      "state": {
        "balance": {
          "by_number": "0x2ad4065dfbab2d1c92a",
          "by_hash": "0x2ad4065dfbab2d1c92a",
          "anchored": true
        },
        "code": {
          "by_number": {
            "bytes": 0,
            "prefix": "0x"
          },
          "by_hash": {
            "bytes": 0,
            "prefix": "0x"
          },
          "anchored": true
        }
      },
      "verdict": "consistent"
    },
    {
      "rpc": "https://eth.drpc.org",
      "chain_id": "0x1",
      "head": {
        "number": 26161203,
        "lag": 77
      },
      "block_lookup": "match",
      "block": {
        "number": 26161126,
        "hash": "0x6b4247350e952e32ad229df759e46dc406142e2a74e068a90e71179584e673d8"
      },
      "state": {
        "balance": {
          "by_number": "0x2ad4065dfbab2d1c92a",
          "by_hash": "0x2ad4065dfbab2d1c92a",
          "anchored": true
        },
        "code": {
          "by_number": {
            "bytes": 0,
            "prefix": "0x"
          },
          "by_hash": {
            "bytes": 0,
            "prefix": "0x"
          },
          "anchored": true
        }
      },
      "verdict": "consistent"
    }
  ],
  "comparison": {
    "chain_id": "match",
    "block_hash": "match",
    "balance": "match",
    "code": "match"
  }
}
```

The address in the example is the Ethereum burn address, not an exchange account. The output is a snapshot from that run; providers and heads change.

## Usage

```text
python evm_state_anchor_audit.py --rpc URL --rpc URL --block BLOCK --address ADDRESS
```

`--rpc` can be repeated and at least two providers are useful for comparison. `--block` accepts a decimal number or a hexadecimal quantity. `--address` must be a 20-byte EVM address. Use `--json` to request compact JSON without indentation. The tool makes no requests to an indexer or explorer.

## How it works

For each provider, the tool calls `eth_chainId`, `eth_blockNumber`, `eth_getBlockByNumber`, and `eth_getBlockByHash`. It then reads the address with `eth_getBalance` and `eth_getCode` twice: once with the block number and once with an EIP-1898 `{blockHash, requireCanonical: true}` selector. It compares the two reads per provider and then compares successful results across providers. Unsupported historical or hash-anchored methods are reported as incomplete rather than treated as agreement.

## Tests

```text
python -m unittest -v
```
