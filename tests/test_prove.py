"""`prove` is the one command that answers: can the checks be trusted?"""

import contextlib
import io
import json
import unittest

from assaystone import cli


class ProveTest(unittest.TestCase):
    def test_prove_reports_recall_resistance_and_pass_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["prove", "--json"])
        self.assertEqual(code, 0)
        document = json.loads(out.getvalue())
        self.assertTrue(document["passed"])
        self.assertIn("recall", document)
        self.assertIn("resistance", document)

    def test_prove_human_output_names_both_questions(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["prove"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("[recall]", text)
        self.assertIn("[resistance]", text)


if __name__ == "__main__":
    unittest.main()
