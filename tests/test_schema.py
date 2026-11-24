import json
import unittest
from pathlib import Path

import jsonschema

from assaystone.cli import main
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
    return [f"{list(e.path)}: {e.message}" for e in sorted(validator.iter_errors(document), key=lambda e: list(e.path))]


class SchemaTest(unittest.TestCase):
    def test_available_schemas(self):
        self.assertEqual(available_schemas(), ["contract", "trace"])

    def test_bundled_schemas_are_valid_json(self):
        for name in available_schemas():
            schema = load_schema(name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_demo_traces_validate(self):
        for trace_path in (DEMO / "ops_agent" / "traces").glob("*.json"):
            document = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(_validate(document, "trace"), [], trace_path.name)

    def test_demo_contracts_validate(self):
        for contract_path in (DEMO / "ops_agent" / "contracts").glob("*.json"):
            document = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(_validate(document, "contract"), [], contract_path.name)

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

    def test_cli_schema_list(self):
        self.assertEqual(main(["schema", "list"]), 0)

    def test_cli_schema_show_trace(self):
        self.assertEqual(main(["schema", "trace"]), 0)

    def test_cli_schema_show_contract(self):
        self.assertEqual(main(["schema", "contract"]), 0)

    def test_cli_schema_validate_is_not_a_subcommand(self):
        # The issue asks only for `schema list` / `schema <name>`; a `validate`
        # subcommand must not exist (it would require a third-party runtime dep).
        with self.assertRaises(SystemExit) as ctx:
            main(["schema", "validate", "trace", "whatever.json"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()