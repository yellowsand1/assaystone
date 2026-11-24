import json
import tempfile
import unittest
from pathlib import Path

from assaystone.cli import main
from assaystone.schema import (
    SchemaError,
    available_schemas,
    load_schema,
    validate_document,
)

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "assaystone" / "demo_data"


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
            self.assertEqual(validate_document(document, "trace"), [], trace_path.name)

    def test_demo_contracts_validate(self):
        for contract_path in (DEMO / "ops_agent" / "contracts").glob("*.json"):
            document = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_document(document, "contract"), [], contract_path.name)

    def test_trace_missing_required_id_is_rejected(self):
        errors = validate_document({"task": "do something"}, "trace")
        self.assertTrue(any("missing required property 'id'" in e for e in errors), errors)

    def test_trace_bad_label_verdict_is_rejected(self):
        document = {
            "id": "t1",
            "task": "x",
            "labels": {"verdict": "maybe"},
        }
        errors = validate_document(document, "trace")
        self.assertTrue(errors, "expected a validation error for bad verdict")

    def test_contract_requires_at_least_one_verifier(self):
        errors = validate_document({"verifiers": []}, "contract")
        self.assertTrue(any("at least 1 items" in e for e in errors), errors)

    def test_contract_rejects_unknown_property(self):
        errors = validate_document({"verifiers": [{"name": "x"}], "bogus": 1}, "contract")
        self.assertTrue(any("unexpected property 'bogus'" in e for e in errors), errors)

    def test_unknown_schema_raises(self):
        with self.assertRaises(SchemaError):
            load_schema("nope")

    def test_cli_schema_list(self):
        self.assertEqual(main(["schema", "list"]), 0)

    def test_cli_schema_validate_good_document(self):
        path = DEMO / "ops_agent" / "traces" / "t01-correct.json"
        self.assertEqual(main(["schema", "validate", "trace", str(path)]), 0)

    def test_cli_schema_validate_bad_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"task": "no id"}), encoding="utf-8")
            self.assertEqual(main(["schema", "validate", "trace", str(bad)]), 1)


if __name__ == "__main__":
    unittest.main()