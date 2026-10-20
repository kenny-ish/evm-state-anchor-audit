import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "audit_module",
    ROOT / "evm_state_anchor_audit.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


BLOCK = {
    "number": "0x12a05f0",
    "hash": (
        "0xd66f35791af39278a53e0d17a9b69842357faabeac7917f403313dff79ba2231"
    ),
}
ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
BALANCE = "0x276051b5dac51f4663df1"
CODE = "0x6060604052600436106100af57"


def fake_transport(url, method, params):
    if method == "eth_chainId":
        return {"result": "0x1"}

    if method == "eth_blockNumber":
        return {"result": "0x12a0600"}

    if method in ("eth_getBlockByNumber", "eth_getBlockByHash"):
        return {"result": BLOCK}

    if method == "eth_getBalance":
        return {"result": BALANCE}

    if method == "eth_getCode":
        return {"result": CODE}

    raise AssertionError(method)


class EvmStateAnchorAuditTests(unittest.TestCase):
    def test_quantity_and_address_validation(self):
        self.assertEqual(MODULE.quantity("0x12a05f0"), 19531248)
        self.assertEqual(
            MODULE.normalize_address(ADDRESS),
            ADDRESS.lower(),
        )

        with self.assertRaises(ValueError):
            MODULE.normalize_address("0x1234")

    def test_short_code_is_byte_count_and_prefix(self):
        self.assertEqual(
            MODULE.short_code("0x"),
            {"bytes": 0, "prefix": "0x"},
        )
        self.assertEqual(
            MODULE.short_code(CODE),
            {"bytes": 13, "prefix": CODE[:18]},
        )

    def test_audit_uses_number_and_hash_anchored_state(self):
        report = MODULE.audit(
            ["provider-a", "provider-b"],
            "0x12a05f0",
            ADDRESS,
            fake_transport,
        )

        self.assertEqual(report["block"]["number"], 19531248)
        self.assertEqual(report["block"]["hash"], BLOCK["hash"])
        self.assertEqual(
            report["providers"][0]["state"]["balance"]["by_number"],
            BALANCE,
        )
        self.assertEqual(
            report["comparison"],
            {
                "chain_id": "match",
                "block_hash": "match",
                "balance": "match",
                "code": "match",
            },
        )
        self.assertEqual(report["providers"][0]["head"]["lag"], 16)
        self.assertTrue(
            report["providers"][0]["state"]["balance"]["anchored"]
        )
        self.assertEqual(
            report["providers"][0]["verdict"],
            "consistent",
        )

    def test_unsupported_state_selector_is_incomplete(self):
        def no_hash_selector(url, method, params):
            response = fake_transport(url, method, params)

            if method in ("eth_getBalance", "eth_getCode") and isinstance(
                params[1],
                dict,
            ):
                raise RuntimeError("blockHash selector is unsupported")

            return response

        report = MODULE.audit(
            ["provider-a"],
            "0x12a05f0",
            ADDRESS,
            no_hash_selector,
        )
        provider = report["providers"][0]

        self.assertEqual(provider["verdict"], "incomplete")
        self.assertIsNone(
            provider["state"]["balance"]["anchored"]
        )
        self.assertEqual(len(provider["errors"]), 2)

    def test_provider_error_is_reported(self):
        def failing(url, method, params):
            raise RuntimeError("historical state unavailable")

        report = MODULE.audit(
            ["provider-a"],
            "0x12a05f0",
            ADDRESS,
            failing,
        )

        self.assertEqual(
            report["providers"][0]["verdict"],
            "error",
        )
        self.assertIn(
            "historical state",
            report["providers"][0]["error"],
        )
        self.assertEqual(
            report["comparison"]["balance"],
            "unavailable",
        )

    def test_json_is_serializable(self):
        report = MODULE.audit(
            ["provider-a"],
            "0x12a05f0",
            ADDRESS,
            fake_transport,
        )
        self.assertIsInstance(json.dumps(report), str)


if __name__ == "__main__":
    unittest.main()
