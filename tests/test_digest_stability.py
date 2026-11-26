"""The digest an owner signs must survive a tool upgrade.

Adding `budget_usd` to the policy serialisation changed every manifest digest and
silently invalidated the owner's approval — the self-gate refused on CI, which is
how it was found. The serialised shape is now frozen; this test pins it.
"""

import copy
import unittest

from assaystone.plane import CapabilityManifest, manifest_digest

# If this changes, every approval in the world is invalid and must be re-signed.
# Change it only with a migration note in the release notes.
GOLDEN = "sha256:b17a39f9ec518dd696c2ed1b647eb095acb59f90c4bc6e8bbb21461a9ef7ddb7"


def manifest_data():
    return {
        "capability": "digest-pin",
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}}
        ],
        "policies": {"shadow": {"require": ["ok"]}},
    }


class DigestStabilityTest(unittest.TestCase):
    def test_the_serialised_shape_is_pinned(self):
        manifest = CapabilityManifest.from_dict(manifest_data())
        self.assertEqual(manifest_digest(manifest), GOLDEN)

    def test_an_unset_new_field_is_not_a_change(self):
        manifest = CapabilityManifest.from_dict(manifest_data())
        data = copy.deepcopy(manifest_data())
        data["policies"]["shadow"]["budget_usd"] = None
        self.assertEqual(
            manifest_digest(CapabilityManifest.from_dict(data)),
            manifest_digest(manifest),
        )

    def test_a_set_new_field_is_a_change(self):
        manifest = CapabilityManifest.from_dict(manifest_data())
        data = copy.deepcopy(manifest_data())
        data["policies"]["shadow"]["budget_usd"] = 0.5
        self.assertNotEqual(
            manifest_digest(CapabilityManifest.from_dict(data)),
            manifest_digest(manifest),
        )

    def test_the_self_capability_still_matches_its_approval(self):
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / ".assaystone"
        manifest = CapabilityManifest.load(root / "capability.json")
        approval = json.loads(
            (root / "capability.approval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(approval["manifest_digest"], manifest_digest(manifest))


if __name__ == "__main__":
    unittest.main()
