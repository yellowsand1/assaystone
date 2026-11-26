"""A policy may not permit an irreversible action it cannot justify.

The draft that `capability init` used to write allowed deploy on production with
no approval and no rollback, so a new user could get a green light from a
manifest that checked almost nothing. These rules make that a manifest error.
"""

import unittest
from pathlib import Path

from assaystone.plane import CapabilityManifest, PlaneError
from assaystone.scaffold import build_manifest

REPO = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO / "examples" / "capability"


def data(policy, oracles=None, irreversible=("deploy",), approval=False):
    return {
        "capability": "integrity",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": list(irreversible),
        "risk": "high",
        "lifecycle": "shadow",
        "manifest_approval": approval,
        "criteria": [],
        "oracles": oracles
        or [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}},
            {"id": "approve", "type": "command", "payload": {"command": ["true"]}},
            {"id": "rollback", "type": "command", "payload": {"command": ["true"]}},
        ],
        "policies": {"production": policy},
    }


class PolicyIntegrityTest(unittest.TestCase):
    def test_deploy_needs_an_approval(self):
        with self.assertRaises(PlaneError) as caught:
            CapabilityManifest.from_dict(
                data({"require": ["ok"], "allow_deploy": True,
                      "rollback_required": True, "rollback": "rollback"})
            )
        self.assertIn("without an approval", str(caught.exception))

    def test_deploy_needs_rollback_evidence(self):
        with self.assertRaises(PlaneError) as caught:
            CapabilityManifest.from_dict(
                data({"require": ["ok"], "approvals": ["approve"],
                      "allow_deploy": True})
            )
        self.assertIn("without rollback evidence", str(caught.exception))

    def test_deploy_needs_a_rollback_oracle_named(self):
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(
                data({"require": ["ok"], "approvals": ["approve"],
                      "allow_deploy": True, "rollback_required": True})
            )

    def test_a_justified_deploy_policy_is_valid(self):
        manifest = CapabilityManifest.from_dict(
            data({"require": ["ok"], "approvals": ["approve"],
                  "allow_deploy": True, "rollback_required": True,
                  "rollback": "rollback"})
        )
        self.assertEqual(manifest.validate(), [])

    def test_owner_manifest_approval_counts_as_an_approval(self):
        CapabilityManifest.from_dict(
            data({"require": ["ok"], "allow_deploy": True,
                  "rollback_required": True, "rollback": "rollback"},
                 approval=True)
        )

    def test_merge_may_not_skip_approval_when_declared_irreversible(self):
        with self.assertRaises(PlaneError) as caught:
            CapabilityManifest.from_dict(
                data({"require": ["ok"], "allow_merge": True},
                     irreversible=("merge",))
            )
        self.assertIn("declares irreversible", str(caught.exception))

    def test_merge_is_fine_when_it_is_not_declared_irreversible(self):
        CapabilityManifest.from_dict(
            data({"require": ["ok"], "allow_merge": True},
                 irreversible=("deploy",))
        )

    def test_the_generated_draft_permits_nothing_it_cannot_justify(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            data_, _ = build_manifest(root, owner="team")
        self.assertFalse(data_["policies"]["canary"]["allow_merge"])
        self.assertFalse(data_["policies"]["production"]["allow_merge"])
        self.assertFalse(data_["policies"]["production"]["allow_deploy"])
        CapabilityManifest.from_dict(data_)

    def test_every_example_still_validates(self):
        for path in sorted(CAPABILITIES.glob("*.json")):
            if path.name == "oracles.json":
                continue
            with self.subTest(path=path.name):
                CapabilityManifest.load(path)

    def test_the_self_capability_still_validates(self):
        CapabilityManifest.load(REPO / ".assaystone" / "capability.json")


if __name__ == "__main__":
    unittest.main()
