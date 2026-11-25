"""Ed25519 key generation and signatures (optional dependency)."""

import stat
import tempfile
import unittest
from pathlib import Path

from assaystone import keys

try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - CI dev extra installs it
    HAVE_CRYPTO = False


@unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
class KeyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.private = self.root / "keys" / "owner.key"
        self.public = self.root / "keys" / "owner.pub"

    def generate(self, force=False):
        return keys.generate(self.private, self.public, force=force)

    def test_generate_signs_and_verifies(self):
        self.generate()
        self.assertTrue(self.private.exists())
        self.assertTrue(self.public.exists())
        self.assertEqual(
            stat.S_IMODE(self.private.stat().st_mode) & 0o777, 0o600
        )
        body = b"a decision"
        signature = keys.sign(body, self.private)
        self.assertTrue(signature.startswith("ed25519:"))
        self.assertTrue(keys.verify(body, signature, self.public))
        self.assertFalse(keys.verify(b"another decision", signature, self.public))

    def test_wrong_key_and_tampering(self):
        self.generate()
        other_private = self.root / "other.key"
        other_public = self.root / "other.pub"
        keys.generate(other_private, other_public)
        body = b"a decision"
        signature = keys.sign(body, self.private)
        self.assertFalse(keys.verify(body, signature, other_public))
        self.assertFalse(keys.verify(body, "ed25519:not-base64", self.public))

    def test_no_overwrite_without_force(self):
        self.generate()
        with self.assertRaises(keys.SigningKeyError):
            self.generate()
        self.generate(force=True)

    def test_non_key_file_is_rejected(self):
        self.generate()
        self.public.write_text("not a key", encoding="utf-8")
        with self.assertRaises(keys.SigningKeyError):
            keys.load_public(self.public)


if __name__ == "__main__":
    unittest.main()
