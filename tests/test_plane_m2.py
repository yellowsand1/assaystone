"""M2: http, sql, shadow primitives, the oracle registry, and the trail."""

import contextlib
import io
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from assaystone import cli, trail
from assaystone.oracles import (
    OracleError,
    OracleRegistry,
    OracleSpec,
    check_read_only_sql,
    oracle_fingerprint,
    run_oracle,
)
from assaystone.plane import CapabilityManifest, PlaneError, evaluate_gate

REPO = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO / "examples" / "capability"
PRICING = CAPABILITIES / "pricing.json"
PRICING_PROJECT = CAPABILITIES / "pricing_project"


def manifest_data(oracles, policies, criteria=None):
    return {
        "capability": "test",
        "owner": "team",
        "systems": ["svc"],
        "data_classes": ["internal"],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": criteria or [],
        "oracles": oracles,
        "policies": policies,
    }


def spec(type_, payload, spec_id="oracle"):
    return OracleSpec(id=spec_id, type=type_, payload=payload)


def command_spec(code, spec_id="cmd"):
    return spec(
        "command",
        {"command": [sys.executable, "-c", code]},
        spec_id=spec_id,
    )


class HttpHandler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._send(200, {"data": {"status": "ok", "fee_cents": 105}})
        elif self.path == "/auth":
            allowed = self.headers.get("X-Token") == "s3cret"
            self._send(200 if allowed else 401, {"allowed": allowed})
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/boom":
            self._send(500, {"error": "boom"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send(200, {"received": body})

    def log_message(self, *args):  # keep test output clean
        pass


class HttpOracleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HttpHandler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_status_and_json_path_pass(self):
        result = run_oracle(
            spec(
                "http",
                {
                    "url": self.url("/ok"),
                    "expect_status": 200,
                    "json_path": "data.fee_cents",
                    "equals": 105,
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertIn("status=200", result.evidence)

    def test_wrong_value_fails(self):
        result = run_oracle(
            spec("http", {"url": self.url("/ok"), "json_path": "data.fee_cents", "equals": 100}),
            self.root,
        )
        self.assertEqual(result.outcome, "fail")

    def test_missing_json_path_fails(self):
        result = run_oracle(
            spec("http", {"url": self.url("/ok"), "json_path": "data.nope"}),
            self.root,
        )
        self.assertEqual(result.outcome, "fail")

    def test_error_status_fails(self):
        result = run_oracle(
            spec("http", {"url": self.url("/boom"), "expect_status": 200}),
            self.root,
        )
        self.assertEqual(result.outcome, "fail")

    def test_unreachable_host_escalates(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        result = run_oracle(
            spec("http", {"url": f"http://127.0.0.1:{port}/", "timeout": 2}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_missing_credential_escalates(self):
        result = run_oracle(
            spec(
                "http",
                {
                    "url": self.url("/auth"),
                    "headers": {"X-Token": "env:ASSAYSTONE_TEST_MISSING"},
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("ASSAYSTONE_TEST_MISSING", result.reasons[0])

    def test_credential_from_environment(self):
        with mock.patch.dict(os.environ, {"ASSAYSTONE_TEST_TOKEN": "s3cret"}):
            result = run_oracle(
                spec(
                    "http",
                    {
                        "url": self.url("/auth"),
                        "headers": {"X-Token": "env:ASSAYSTONE_TEST_TOKEN"},
                        "json_path": "allowed",
                        "equals": True,
                    },
                ),
                self.root,
            )
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertFalse(
            any("s3cret" in item for item in result.evidence),
            "credentials must not appear in evidence",
        )

    def test_mutating_request_needs_opt_in(self):
        result = run_oracle(
            spec("http", {"url": self.url("/ok"), "method": "POST"}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_mutating_request_with_opt_in(self):
        result = run_oracle(
            spec(
                "http",
                {
                    "url": self.url("/ok"),
                    "method": "POST",
                    "allow_write": True,
                    "body": {"order_id": "o-1"},
                    "json_path": "received.order_id",
                    "equals": "o-1",
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_redirect_escalates(self):
        result = run_oracle(
            spec("http", {"url": self.url("/redirect")}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("redirect", result.reasons[0])

    def test_oversized_response_escalates(self):
        result = run_oracle(
            spec("http", {"url": self.url("/ok"), "max_bytes": 10}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_non_http_scheme_escalates(self):
        result = run_oracle(
            spec("http", {"url": "file:///etc/passwd"}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")


class SqlOracleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        connection = sqlite3.connect(self.root / "ledger.db")
        connection.execute(
            "create table orders (order_id text primary key, cents integer)"
        )
        connection.executemany(
            "insert into orders values (?, ?)",
            [("o-1", 4000), ("o-2", 5000), ("o-3", 3300)],
        )
        connection.commit()
        connection.close()

    def query(self, sql, expect=None, payload=None):
        data = {"driver": "sqlite", "database": "ledger.db", "query": sql}
        if expect is not None:
            data["expect"] = expect
        data.update(payload or {})
        return run_oracle(spec("sql", data), self.root)

    def test_scalar_pass_and_fail(self):
        sql = "select sum(cents) from orders"
        passed = self.query(sql, {"mode": "scalar", "equals": 12300})
        self.assertEqual(passed.outcome, "pass", passed.reasons)
        failed = self.query(sql, {"mode": "scalar", "equals": 12000})
        self.assertEqual(failed.outcome, "fail")

    def test_rows_pass_and_mismatch(self):
        sql = "select count(*) as n, sum(cents) as total from orders"
        passed = self.query(sql, {"mode": "rows", "equals": [{"n": 3, "total": 12300}]})
        self.assertEqual(passed.outcome, "pass", passed.reasons)
        failed = self.query(sql, {"mode": "rows", "equals": [{"n": 2, "total": 12300}]})
        self.assertEqual(failed.outcome, "fail")
        self.assertIn("n", failed.reasons[0])

    def test_baseline_file(self):
        (self.root / "expected.json").write_text(
            json.dumps([{"order_id": "o-1", "cents": 4000}]), encoding="utf-8"
        )
        result = self.query(
            "select order_id, cents from orders where order_id = 'o-1'",
            {"mode": "rows", "baseline": "expected.json"},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_empty_expectation(self):
        passed = self.query(
            "select * from orders where cents > 999999",
            {"mode": "empty"},
        )
        self.assertEqual(passed.outcome, "pass", passed.reasons)
        failed = self.query("select * from orders", {"mode": "empty"})
        self.assertEqual(failed.outcome, "fail")

    def test_write_queries_are_rejected(self):
        for sql in (
            "insert into orders values ('o-4', 1)",
            "update orders set cents = 0",
            "delete from orders",
            "drop table orders",
            "select 1; delete from orders",
            "pragma table_info(orders)",
            "select 1; select 2",
        ):
            result = self.query(sql)
            self.assertEqual(result.outcome, "escalate", sql)

    def test_comments_and_string_literals_are_allowed(self):
        self.assertIsNone(
            check_read_only_sql("-- note\nselect 'drop' as word from orders")
        )
        result = self.query(
            "-- note\nselect 'drop' as word from orders limit 1",
            {"mode": "rows", "equals": [{"word": "drop"}]},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_with_query_is_allowed(self):
        result = self.query(
            "with totals as (select sum(cents) as total from orders) "
            "select total from totals",
            {"mode": "scalar", "equals": 12300},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_database_must_stay_inside_root(self):
        result = run_oracle(
            spec(
                "sql",
                {
                    "driver": "sqlite",
                    "database": "../ledger.db",
                    "query": "select 1",
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_missing_database_escalates(self):
        result = run_oracle(
            spec(
                "sql",
                {
                    "driver": "sqlite",
                    "database": "absent.db",
                    "query": "select 1",
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_unknown_driver_escalates(self):
        result = run_oracle(
            spec(
                "sql",
                {"driver": "oracle-db", "database": "ledger.db", "query": "select 1"},
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_no_expectation_reports_row_count(self):
        result = self.query("select * from orders")
        self.assertEqual(result.outcome, "pass")
        self.assertIn("rows=3", result.evidence)


class ShadowOracleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def shadow(self, old_code, new_code, compare=None):
        return run_oracle(
            spec(
                "shadow",
                {
                    "old": {
                        "type": "command",
                        "payload": {"command": [sys.executable, "-c", old_code]},
                    },
                    "new": {
                        "type": "command",
                        "payload": {"command": [sys.executable, "-c", new_code]},
                    },
                    "compare": compare or {"mode": "text"},
                },
            ),
            self.root,
        )

    def test_identical_output_passes(self):
        result = self.shadow("print('a')", "print('a')")
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_text_whitespace_is_normalized(self):
        result = self.shadow("print('a  b')", "print('a b')")
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_text_divergence_fails(self):
        result = self.shadow("print('a')", "print('b')")
        self.assertEqual(result.outcome, "fail")

    def test_text_ignore_regex(self):
        result = self.shadow(
            "print('fee=100 at 09:00')",
            "print('fee=100 at 11:30')",
            {"mode": "text", "ignore": [r"at \d+:\d+"]},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_json_key_order_is_irrelevant(self):
        result = self.shadow(
            'print(\'{"a": 1, "b": 2}\')',
            'print(\'{"b": 2, "a": 1}\')',
            {"mode": "json"},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_json_ignored_keys(self):
        result = self.shadow(
            'print(\'{"fee": 1, "at": "old"}\')',
            'print(\'{"fee": 1, "at": "new"}\')',
            {"mode": "json", "ignore": ["at"]},
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_json_tolerance(self):
        exact = self.shadow(
            'print(\'{"fee": 1.0}\')',
            'print(\'{"fee": 1.004}\')',
            {"mode": "json", "tolerance": 0.001},
        )
        self.assertEqual(exact.outcome, "fail")
        tolerant = self.shadow(
            'print(\'{"fee": 1.0}\')',
            'print(\'{"fee": 1.004}\')',
            {"mode": "json", "tolerance": 0.01},
        )
        self.assertEqual(tolerant.outcome, "pass", tolerant.reasons)

    def test_json_diff_names_the_path(self):
        result = self.shadow(
            'print(\'{"fee": {"us": 100}}\')',
            'print(\'{"fee": {"us": 105}}\')',
            {"mode": "json"},
        )
        self.assertEqual(result.outcome, "fail")
        self.assertIn("fee.us", result.reasons[0])

    def test_nested_escalation_escalates(self):
        result = run_oracle(
            spec(
                "shadow",
                {
                    "old": {
                        "type": "command",
                        "payload": {"command": ["definitely-not-a-command-xyz"]},
                    },
                    "new": {"type": "command", "payload": {"command": ["true"]}},
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_both_failing_sides_escalate(self):
        result = self.shadow("raise SystemExit(2)", "raise SystemExit(2)")
        self.assertEqual(result.outcome, "escalate")

    def test_outcome_change_fails(self):
        result = self.shadow("print('ok')", "raise SystemExit(2)")
        self.assertEqual(result.outcome, "fail")

    def test_shadow_cannot_nest(self):
        result = run_oracle(
            spec(
                "shadow",
                {
                    "old": {"type": "shadow", "payload": {}},
                    "new": {"type": "command", "payload": {"command": ["true"]}},
                },
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")


class FailClosedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_bad_payload_value_escalates_instead_of_crashing(self):
        result = run_oracle(
            spec("command", {"command": ["true"], "timeout": "soon"}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("oracle error", result.reasons[0])

    def test_invalid_regex_escalates(self):
        (self.root / "a.txt").write_text("x", encoding="utf-8")
        result = run_oracle(
            spec(
                "file",
                {"path": "a.txt", "mode": "regex", "pattern": "("},
            ),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")

    def test_non_utf8_file_escalates(self):
        (self.root / "a.bin").write_bytes(b"\xff\xfe\x00")
        result = run_oracle(
            spec("file", {"path": "a.bin", "mode": "json"}),
            self.root,
        )
        self.assertEqual(result.outcome, "escalate")


class RegistryTest(unittest.TestCase):
    def registry_dict(self, version=2, command=None):
        return {
            "version": 1,
            "oracles": [
                {
                    "id": "java.compile",
                    "version": version,
                    "type": "command",
                    "owner": "platform-team",
                    "payload": {"command": command or ["mvn", "-q", "compile"]},
                }
            ],
        }

    def test_resolve_and_pin(self):
        registry = OracleRegistry.from_dict(self.registry_dict())
        definition = registry.resolve("java.compile", 2)
        self.assertEqual(definition.payload["command"], ["mvn", "-q", "compile"])
        with self.assertRaises(OracleError):
            registry.resolve("java.compile", 1)
        with self.assertRaises(OracleError):
            registry.resolve("absent")

    def test_duplicate_and_bad_type_rejected(self):
        duplicate = self.registry_dict()
        duplicate["oracles"].append(dict(duplicate["oracles"][0]))
        with self.assertRaises(OracleError):
            OracleRegistry.from_dict(duplicate)
        bad = self.registry_dict()
        bad["oracles"][0]["type"] = "magic"
        with self.assertRaises(OracleError):
            OracleRegistry.from_dict(bad)

    def test_manifest_resolves_ref(self):
        registry = OracleRegistry.from_dict(self.registry_dict())
        data = manifest_data(
            [{"id": "compile", "ref": "java.compile", "version": 2}],
            {"shadow": {"require": ["compile"]}},
        )
        manifest = CapabilityManifest.from_dict(data, registry=registry)
        oracle = manifest.oracles[0]
        self.assertEqual(oracle.type, "command")
        self.assertEqual(oracle.payload["command"], ["mvn", "-q", "compile"])
        self.assertEqual(oracle.ref, "java.compile")
        self.assertEqual(oracle.version, 2)
        self.assertTrue(oracle.fingerprint.startswith("sha256:"))
        self.assertTrue(manifest.registry_fingerprint.startswith("sha256:"))

    def test_ref_cannot_override_payload(self):
        registry = OracleRegistry.from_dict(self.registry_dict())
        data = manifest_data(
            [
                {
                    "id": "compile",
                    "ref": "java.compile",
                    "payload": {"command": ["true"]},
                }
            ],
            {"shadow": {"require": ["compile"]}},
        )
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data, registry=registry)

    def test_ref_without_registry_is_rejected(self):
        data = manifest_data(
            [{"id": "compile", "ref": "java.compile"}],
            {"shadow": {"require": ["compile"]}},
        )
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_registry_autodiscovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "oracles.json").write_text(
                json.dumps(self.registry_dict()), encoding="utf-8"
            )
            data = manifest_data(
                [{"id": "compile", "ref": "java.compile"}],
                {"shadow": {"require": ["compile"]}},
            )
            data["registry"] = "oracles.json"
            (root / "capability.json").write_text(json.dumps(data), encoding="utf-8")
            manifest = CapabilityManifest.load(root / "capability.json")
            self.assertEqual(
                manifest.oracles[0].payload["command"], ["mvn", "-q", "compile"]
            )

    def test_fingerprint_tracks_type_and_payload(self):
        first = oracle_fingerprint("command", {"command": ["mvn", "test"]})
        same = oracle_fingerprint("command", {"command": ["mvn", "test"]})
        other = oracle_fingerprint("command", {"command": ["mvn", "-q", "test"]})
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)

    def test_java_template_uses_the_registry(self):
        manifest = CapabilityManifest.load(CAPABILITIES / "java.json")
        self.assertEqual(manifest.registry, "oracles.json")
        compile_oracle = next(
            item for item in manifest.oracles if item.id == "compile"
        )
        self.assertEqual(compile_oracle.payload["command"][0], "mvn")
        self.assertEqual(compile_oracle.version, 2)


class GateGapTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def manifest(self, extra_oracle=False):
        oracles = [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}}
        ]
        if extra_oracle:
            oracles.append(
                {"id": "approval", "type": "command", "payload": {"command": ["true"]}}
            )
        criteria = [
            {
                "id": "critical-thing",
                "kind": "invariant",
                "statement": "a critical property",
                "oracle": "approval",
                "severity": "critical",
            }
        ]
        return CapabilityManifest.from_dict(
            manifest_data(
                oracles,
                {
                    "shadow": {"require": ["ok"]},
                    "design": {"require": []},
                },
                criteria=criteria,
            )
        )

    def test_gap_is_reported_without_strict(self):
        result = evaluate_gate(self.manifest(extra_oracle=True), "shadow", self.root)
        self.assertEqual(result.outcome, "pass")
        self.assertEqual([item["criterion"] for item in result.gap], ["critical-thing"])

    def test_strict_escalates_on_a_critical_gap(self):
        result = evaluate_gate(
            self.manifest(extra_oracle=True), "shadow", self.root, strict=True
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertTrue(any("strict" in reason for reason in result.reasons))

    def test_failure_beats_a_gap(self):
        manifest = self.manifest(extra_oracle=True)
        manifest.oracles[0].payload["command"] = [
            sys.executable,
            "-c",
            "raise SystemExit(1)",
        ]
        result = evaluate_gate(manifest, "shadow", self.root, strict=True)
        self.assertEqual(result.outcome, "fail")

    def test_design_stage_is_not_blocked_by_a_gap(self):
        result = evaluate_gate(
            self.manifest(extra_oracle=True), "design", self.root, strict=True
        )
        self.assertEqual(result.outcome, "pass")


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def manifest(self, rollback_command=None, policy_extra=None):
        oracles = [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}},
        ]
        if rollback_command is not None:
            oracles.append(
                {
                    "id": "rollback",
                    "type": "command",
                    "payload": {
                        "command": [sys.executable, "-c", rollback_command]
                    },
                }
            )
        policy = {
            "require": ["ok"],
            "allow_merge": True,
            "allow_deploy": True,
            "rollback_required": True,
        }
        policy.update(policy_extra or {})
        return CapabilityManifest.from_dict(
            manifest_data(oracles, {"production": policy})
        )

    def test_rollback_claim_needs_an_oracle(self):
        with self.assertRaises(PlaneError) as caught:
            self.manifest()
        self.assertIn("rollback oracle", str(caught.exception))

    def test_unknown_rollback_oracle_is_rejected(self):
        with self.assertRaises(PlaneError):
            self.manifest(
                rollback_command="pass", policy_extra={"rollback": "nope"}
            )

    def test_rollback_oracle_runs_and_fails_the_gate(self):
        manifest = self.manifest(
            rollback_command="raise SystemExit(3)", policy_extra={"rollback": "rollback"}
        )
        result = evaluate_gate(manifest, "production", self.root)
        self.assertEqual(result.outcome, "fail")
        self.assertFalse(result.deploy_allowed)
        rollback = next(item for item in result.results if item.oracle == "rollback")
        self.assertEqual(rollback.outcome, "fail")
        self.assertTrue(result.rollback_required)
        self.assertEqual(result.rollback, "rollback")

    def test_rollback_oracle_passes_the_gate(self):
        manifest = self.manifest(
            rollback_command="pass", policy_extra={"rollback": "rollback"}
        )
        result = evaluate_gate(manifest, "production", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(result.deploy_allowed)

    def test_rollback_is_recorded_in_the_trail(self):
        manifest = self.manifest(
            rollback_command="pass", policy_extra={"rollback": "rollback"}
        )
        gate = evaluate_gate(manifest, "production", self.root)
        entry = trail.entry_for(gate, actor="ci", at="2026-11-25T00:00:00Z")
        self.assertTrue(entry["rollback_required"])
        self.assertEqual(entry["rollback"], "rollback")
        self.assertEqual(entry["manifest_lifecycle"], "shadow")
        self.assertIn(
            "rollback", [item["id"] for item in entry["oracles"]]
        )


class TrailTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifest = CapabilityManifest.from_dict(
            manifest_data(
                [{"id": "ok", "type": "command", "payload": {"command": ["true"]}}],
                {"shadow": {"require": ["ok"]}},
            )
        )

    def gate(self, stage="shadow"):
        return evaluate_gate(self.manifest, stage, self.root)

    def test_append_and_verify(self):
        path = self.root / "trail.jsonl"
        first = trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:00:00Z")
        second = trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:01:00Z")
        self.assertEqual(first["seq"], 0)
        self.assertEqual(first["prev"], trail.GENESIS)
        self.assertEqual(second["seq"], 1)
        self.assertEqual(second["prev"], first["hash"])
        check = trail.verify(path)
        self.assertTrue(check.ok, check.errors)
        self.assertEqual(check.entries, 2)
        self.assertEqual(check.head, second["hash"])

    def test_modified_entry_breaks_the_chain(self):
        path = self.root / "trail.jsonl"
        trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:00:00Z")
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["outcome"] = "fail"
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        check = trail.verify(path)
        self.assertFalse(check.ok)
        self.assertTrue(any("hash mismatch" in item for item in check.errors))

    def test_append_refuses_a_broken_trail(self):
        path = self.root / "trail.jsonl"
        trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:00:00Z")
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["outcome"] = "fail"
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        with self.assertRaises(trail.TrailError):
            trail.append(path, self.gate(), actor="ci")

    def test_deleted_middle_entry_breaks_the_chain(self):
        path = self.root / "trail.jsonl"
        for minute in range(3):
            trail.append(
                path,
                self.gate(),
                actor="ci",
                at=f"2026-11-25T00:0{minute}:00Z",
            )
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
        check = trail.verify(path)
        self.assertFalse(check.ok)

    def test_expected_head_detects_truncation(self):
        path = self.root / "trail.jsonl"
        trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:00:00Z")
        head = trail.verify(path).head
        trail.append(path, self.gate(), actor="ci", at="2026-11-25T00:01:00Z")
        check = trail.verify(path, expected_head=head)
        self.assertFalse(check.ok)
        self.assertTrue(any("anchored" in item for item in check.errors))

    def test_empty_and_missing_trails_are_not_ok(self):
        path = self.root / "trail.jsonl"
        self.assertFalse(trail.verify(path).ok)
        path.write_text("", encoding="utf-8")
        self.assertFalse(trail.verify(path).ok)

    def test_digest_is_stable_and_sensitive(self):
        first = run_oracle(
            command_spec("print('same')"), self.root
        )
        second = run_oracle(
            command_spec("print('same')"), self.root
        )
        third = run_oracle(
            command_spec("print('different')"), self.root
        )
        self.assertEqual(first.digest, second.digest)
        self.assertNotEqual(first.digest, third.digest)

    def test_gate_cli_writes_the_trail(self):
        manifest_path = self.root / "capability.json"
        manifest_path.write_text(
            json.dumps(
                manifest_data(
                    [
                        {
                            "id": "ok",
                            "type": "command",
                            "payload": {"command": ["true"]},
                        }
                    ],
                    {"shadow": {"require": ["ok"]}},
                )
            ),
            encoding="utf-8",
        )
        trail_path = self.root / "trail.jsonl"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest",
                    str(manifest_path),
                    "--stage",
                    "shadow",
                    "--root",
                    str(self.root),
                    "--audit",
                    str(trail_path),
                    "--actor",
                    "release-bot",
                ]
            )
        self.assertEqual(code, 0, out.getvalue())
        entries = trail.read(trail_path)
        self.assertEqual(entries[0]["actor"], "release-bot")
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["trail", "verify", str(trail_path)])
        self.assertEqual(code, 0)


class PricingVerticalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = CapabilityManifest.load(PRICING)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        shutil.copytree(PRICING_PROJECT, self.root)

    def test_shadow_passes_with_a_declared_gap(self):
        result = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertFalse(result.merge_allowed)
        self.assertEqual(
            [item["criterion"] for item in result.gap], ["publish-approved"]
        )
        self.assertTrue((self.root / "ledger.db").exists())

    def test_canary_passes_with_approval(self):
        result = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(result.merge_allowed)

    def test_canary_escalates_without_approval(self):
        (self.root / "approvals.json").unlink()
        result = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertFalse(result.merge_allowed)

    def test_parity_break_is_caught(self):
        # A refactor that emits an extra audit flag only for the new path:
        # the unit tests still pass, but old and new no longer agree.
        fee = self.root / "fee.py"
        text = fee.read_text(encoding="utf-8")
        fee.write_text(
            text.replace(
                '"fee_cents": fee_cents(',
                '"audited": version != "old", "fee_cents": fee_cents(',
            ),
            encoding="utf-8",
        )
        result = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "fail")
        parity = next(item for item in result.results if item.oracle == "parity")
        self.assertEqual(parity.outcome, "fail")
        self.assertIn("audited", parity.reasons[0])

    def test_ledger_break_is_caught(self):
        orders = self.root / "orders.json"
        data = json.loads(orders.read_text(encoding="utf-8"))
        data[0]["amount_cents"] = 4100
        orders.write_text(json.dumps(data), encoding="utf-8")
        result = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "fail")
        ledger = next(item for item in result.results if item.oracle == "ledger")
        self.assertEqual(ledger.outcome, "fail")


if __name__ == "__main__":
    unittest.main()
