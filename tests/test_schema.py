import contextlib
import io
import json
import unittest
from dataclasses import fields
from pathlib import Path

import jsonschema

from assaystone.cli import main
from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Label, Step, Trace
from assaystone.schema import (
    SchemaError,
    available_schemas,
    load_schema,
)

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "assaystone" / "demo_data"


def _validate(document, schema_name):
    """Validate *document* against the named schema using jsonschema directly."""
    validator = jsonschema.Draft202012Validator(load_schema(schema_name))
    return [
        f"{list(e.path)}: {e.message}"
        for e in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    ]


def _run_cli(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _demo_traces():
    return sorted(DEMO.glob("*/traces/*.json"))


def _demo_contracts():
    return sorted(DEMO.glob("*/contracts/*.json"))


class SchemaTest(unittest.TestCase):
    def test_available_schemas(self):
        self.assertEqual(available_schemas(), ["contract", "trace"])

    def test_bundled_schemas_are_valid_json(self):
        for name in available_schemas():
            schema = load_schema(name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_demo_traces_validate(self):
        traces = _demo_traces()
        self.assertTrue(traces, "expected bundled demo traces")
        for trace_path in traces:
            document = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(_validate(document, "trace"), [], trace_path)

    def test_demo_contracts_validate(self):
        contracts = _demo_contracts()
        self.assertTrue(contracts, "expected bundled demo contracts")
        for contract_path in contracts:
            document = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(_validate(document, "contract"), [], contract_path)

    def test_trace_schema_matches_model_fields(self):
        schema = load_schema("trace")
        self.assertEqual(set(schema["properties"]), {f.name for f in fields(Trace)})
        defs = schema["$defs"]
        self.assertEqual(set(defs["step"]["properties"]), {f.name for f in fields(Step)})
        self.assertEqual(set(defs["artifact"]["properties"]), {f.name for f in fields(Artifact)})
        self.assertEqual(set(defs["label"]["properties"]), {f.name for f in fields(Label)})

    def test_contract_schema_matches_model_fields(self):
        schema = load_schema("contract")
        self.assertEqual(set(schema["properties"]), {f.name for f in fields(Contract)})
        self.assertEqual(
            set(schema["$defs"]["verifier"]["properties"]), {f.name for f in fields(VerifierSpec)}
        )

    def test_demo_traces_round_trip_through_model(self):
        for trace_path in _demo_traces():
            trace = Trace.load(trace_path)
            self.assertEqual(_validate(trace.to_dict(), "trace"), [], trace_path)

    def test_demo_contracts_round_trip_through_model(self):
        for contract_path in _demo_contracts():
            contract = Contract.load(contract_path)
            self.assertEqual(_validate(contract.to_dict(), "contract"), [], contract_path)

    def test_trace_missing_required_id_is_rejected(self):
        errors = _validate({"task": "do something"}, "trace")
        self.assertTrue(any("'id' is a required property" in e for e in errors), errors)

    def test_trace_bad_label_verdict_is_rejected(self):
        document = {
            "id": "t1",
            "task": "x",
            "labels": {"verdict": "maybe"},
        }
        errors = _validate(document, "trace")
        self.assertTrue(errors, "expected a validation error for bad verdict")

    def test_contract_requires_at_least_one_verifier(self):
        errors = _validate({"verifiers": []}, "contract")
        self.assertTrue(any("non-empty" in e for e in errors), errors)

    def test_contract_rejects_unknown_property(self):
        errors = _validate({"verifiers": [{"name": "x"}], "bogus": 1}, "contract")
        self.assertTrue(any("bogus" in e for e in errors), errors)

    def test_unknown_schema_raises(self):
        with self.assertRaises(SchemaError):
            load_schema("nope")

    def test_cli_schema_list_prints_names(self):
        code, stdout, stderr = _run_cli(["schema", "list"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout.split(), ["contract", "trace"])

    def test_cli_schema_defaults_to_trace(self):
        code, stdout, stderr = _run_cli(["schema"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["title"], "Assaystone Trace")

    def test_cli_schema_show_trace(self):
        code, stdout, stderr = _run_cli(["schema", "trace"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), load_schema("trace"))

    def test_cli_schema_show_contract(self):
        code, stdout, stderr = _run_cli(["schema", "contract"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout), load_schema("contract"))

    def test_cli_schema_validate_is_not_a_subcommand(self):
        # The issue asks only for `schema list` / `schema <name>`; a `validate`
        # subcommand must not exist (it would require a third-party runtime dep).
        with self.assertRaises(SystemExit) as ctx:
            main(["schema", "validate", "trace", "whatever.json"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
