"""The protocol is the contract between a verifier and the scorecard."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.contract import Contract, VerifierSpec
from assaystone.protocol import (
    INDEPENDENCE,
    LAYERS,
    PROTOCOL_VERSION,
    SCHEMAS,
    check_contract,
    describe_protocol,
    write_schemas,
)

REPO = Path(__file__).resolve().parent.parent
CONTRACTS = REPO / "examples" / "code_agent" / "contracts"


class ProtocolTest(unittest.TestCase):
    def test_description_is_versioned_and_complete(self):
        description = describe_protocol()
        self.assertEqual(description["protocol"], "assaystone-verifier")
        self.assertEqual(description["version"], PROTOCOL_VERSION)
        self.assertGreaterEqual(len(description["verifiers"]), 17)
        self.assertEqual(set(description["outcomes"]), {"pass", "fail", "escalate"})

    def test_every_verifier_manifest_matches_the_abi(self):
        for item in describe_protocol()["verifiers"]:
            if not item["builtin"]:
                continue
            self.assertTrue(item["conformant"], item["name"])
            self.assertIn(item["layer"], LAYERS, item["name"])
            self.assertIn(item["independence"], INDEPENDENCE, item["name"])
            self.assertTrue(item["claim"], item["name"])
            self.assertTrue(item["catches"], item["name"])
            self.assertTrue(item["blind_spots"], item["name"])
            self.assertGreaterEqual(item["cost"]["usd"], 0, item["name"])

    def test_hardened_contract_conforms(self):
        result = check_contract(Contract.load(CONTRACTS / "hardened.json"))
        self.assertTrue(result.ok, result.violations)

    def test_naive_contract_conforms_even_though_it_is_weak(self):
        # Conformance and coverage are different questions.
        result = check_contract(Contract.load(CONTRACTS / "naive.json"))
        self.assertTrue(result.ok, result.violations)

    def test_unknown_verifier_is_a_violation(self):
        contract = Contract(
            name="broken",
            verifiers=[VerifierSpec("does.not.exist")],
        )
        result = check_contract(contract)
        self.assertFalse(result.ok)
        self.assertIn("unknown verifier: does.not.exist", result.violations)

    def test_duplicate_verifier_is_a_violation(self):
        contract = Contract(
            name="duplicate",
            verifiers=[VerifierSpec("tests.pass"), VerifierSpec("tests.pass")],
        )
        result = check_contract(contract)
        self.assertFalse(result.ok)
        self.assertIn("duplicate verifier in contract: tests.pass", result.violations)

    def test_reliability_schema_is_registered(self):
        self.assertIn("reliability", SCHEMAS)
        self.assertEqual(
            SCHEMAS["reliability"]["$id"],
            "https://assaystone.dev/protocol/v1/reliability.schema.json",
        )
        entry = SCHEMAS["reliability"]["$defs"]["entry"]["properties"]
        self.assertEqual(entry["recall"]["maximum"], 1)

    def test_spec_schema_is_registered(self):
        self.assertIn("spec", SCHEMAS)
        self.assertEqual(
            SCHEMAS["spec"]["$id"],
            "https://assaystone.dev/protocol/v1/spec.schema.json",
        )
        kinds = SCHEMAS["spec"]["$defs"]["evidence"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, ["path", "contains", "absent", "exists"])

    def test_write_schemas(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_schemas(tmp)
            self.assertEqual(len(paths), 5)
            names = {Path(path).name for path in paths}
            self.assertEqual(
                names,
                {
                    "contract.schema.json",
                    "verifier.schema.json",
                    "verdict.schema.json",
                    "reliability.schema.json",
                    "spec.schema.json",
                },
            )
            contract_schema = json.loads(
                (Path(tmp) / "contract.schema.json").read_text()
            )
            self.assertEqual(contract_schema["type"], "object")


class ProtocolCliTest(unittest.TestCase):
    def test_json_output_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["protocol", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["version"], "1")

    def test_check_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "protocol",
                    "--check",
                    str(CONTRACTS / "hardened.json"),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("ok", out.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            broken.write_text(
                json.dumps(
                    {
                        "name": "broken",
                        "verifiers": [{"name": "does.not.exist"}],
                    }
                ),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["protocol", "--check", str(broken)])
            self.assertEqual(code, 1)
            self.assertIn("unknown verifier", out.getvalue())

    def test_check_manifest_exit_codes(self):
        manifest = {
            "name": "example.x",
            "version": "1",
            "layer": "L1",
            "independence": "high",
            "claim": "c",
            "catches": ["a"],
            "blind_spots": ["b"],
            "cost": {"usd": 0.0},
        }
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps(manifest), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["protocol", "--check-manifest", str(good)])
            self.assertEqual(code, 0)
            self.assertIn("ok", out.getvalue())

            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"name": "x"}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["protocol", "--check-manifest", str(bad)])
            self.assertEqual(code, 1)
            self.assertIn("missing field", out.getvalue())

    def test_schemas_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["protocol", "--schemas", tmp, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(tmp).glob("*.schema.json"))), 5)


if __name__ == "__main__":
    unittest.main()
