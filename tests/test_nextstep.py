"""What blocks the next stage, and the patch that removes it."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.nextstep import next_stage, plan, render
from assaystone.plane import CapabilityManifest

REPO = Path(__file__).resolve().parent.parent


def data(policies, lifecycle="shadow", criteria=None, oracles=None):
    return {
        "capability": "next-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": lifecycle,
        "criteria": criteria or [],
        "oracles": oracles
        or [
            {"id": "build", "type": "command", "payload": {"command": ["true"]}},
            {"id": "reviewer", "type": "command", "payload": {"command": ["true"]}},
            {"id": "rollback", "type": "command", "payload": {"command": ["true"]}},
        ],
        "policies": policies,
    }


class NextTest(unittest.TestCase):
    def manifest(self, **kwargs):
        return CapabilityManifest.from_dict(data(**kwargs))

    def test_the_next_stage_follows_the_lifecycle(self):
        self.assertEqual(next_stage(self.manifest(lifecycle="design", policies={
            "shadow": {"require": ["build"]}})), "shadow")
        self.assertEqual(next_stage(self.manifest(policies={
            "canary": {"require": ["build"]}})), "canary")
        self.assertEqual(next_stage(self.manifest(lifecycle="production", policies={
            "canary": {"require": ["build"]}})), "production")

    def test_a_missing_stage_shows_the_policy_to_add(self):
        result = plan(self.manifest(policies={"shadow": {"require": ["build"]}}))
        self.assertFalse(result.ready)
        blocker = result.blockers[0]
        self.assertEqual(blocker.kind, "no-policy")
        payload = json.loads(blocker.fix)
        self.assertIn("canary", payload)
        self.assertIn("require", payload["canary"])

    def test_a_locked_stage_is_the_blocker(self):
        result = plan(self.manifest(policies={
            "shadow": {"require": ["build"]},
            "canary": {"require": ["build"], "allow_merge": False},
        }))
        kinds = [item.kind for item in result.blockers]
        self.assertIn("locked-stage", kinds)
        text = render(result)
        self.assertIn("does not allow merging", text)
        self.assertIn('"type": "human"', text)

    def test_an_ungated_critical_criterion_is_a_blocker(self):
        criteria = [
            {
                "id": "api-stable",
                "kind": "invariant",
                "statement": "the API is stable",
                "oracle": "rollback",
                "severity": "critical",
            }
        ]
        result = plan(self.manifest(
            policies={
                "shadow": {"require": ["build"]},
                "canary": {"require": ["build"], "allow_merge": True},
            },
            criteria=criteria,
        ))
        kinds = [item.kind for item in result.blockers]
        self.assertIn("ungated-criterion", kinds)

    def test_ready_when_the_stage_is_fully_declared(self):
        result = plan(self.manifest(policies={
            "shadow": {"require": ["build"]},
            "canary": {
                "require": ["build"],
                "approvals": ["reviewer"],
                "allow_merge": True,
            },
        }))
        self.assertTrue(result.ready, [item.detail for item in result.blockers])
        self.assertIn("ready: nothing blocks", render(result))

    def test_missing_evidence_is_reported_when_a_trail_is_given(self):
        result = plan(
            self.manifest(policies={
                "shadow": {"require": ["build"]},
                "canary": {
                    "require": ["build"],
                    "approvals": ["reviewer"],
                    "allow_merge": True,
                },
            }),
            ready_oracles=set(),
        )
        self.assertFalse(result.ready)
        self.assertEqual(result.blockers[0].kind, "no-evidence")
        self.assertIn("gate --manifest", result.blockers[0].command)

    def test_the_pricing_example_is_ready_for_production(self):
        manifest = CapabilityManifest.load(
            REPO / "examples" / "capability" / "pricing.json"
        )
        result = plan(manifest, target="production")
        self.assertTrue(result.ready, [item.detail for item in result.blockers])

    def test_cli_text_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "capability.json"
            path.write_text(
                json.dumps(data({"shadow": {"require": ["build"]}})),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["capability", "next", "--manifest", str(path), "--json"]
                )
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["target"], "canary")
            self.assertFalse(payload["ready"])

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["capability", "next", "--manifest", str(path)]
                )
            self.assertEqual(code, 0)
            self.assertIn("blocker(s)", out.getvalue())

    def test_cli_reports_missing_evidence_from_a_trail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "capability.json"
            path.write_text(
                json.dumps(
                    data({
                        "shadow": {"require": ["build"]},
                        "canary": {
                            "require": ["build"],
                            "approvals": ["reviewer"],
                            "allow_merge": True,
                        },
                    })
                ),
                encoding="utf-8",
            )
            trail_path = root / "trail.jsonl"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cli.main(
                        [
                            "capability", "next", "--manifest", str(path),
                            "--trail", str(trail_path), "--stage", "canary",
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertIn("trail", err.getvalue())


if __name__ == "__main__":
    unittest.main()
