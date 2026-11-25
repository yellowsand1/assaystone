"""MySQL adapter tests. Skipped unless a DSN is provided.

Run locally with a read-only account:

    ASSAYSTONE_TEST_MYSQL_DSN='mysql://user:pass@127.0.0.1:3306/db' \
        python3 -m unittest discover -s tests -t . -p 'test_mysql_optional.py'

The tests never write: they check the session flag, a scalar, a row shape, and
that the SQL validator rejects a write before a connection is opened.
"""

import os
import unittest
from decimal import Decimal

from assaystone.oracles import OracleSpec, _same_scalar, run_oracle

DSN = os.environ.get("ASSAYSTONE_TEST_MYSQL_DSN")


@unittest.skipUnless(DSN, "set ASSAYSTONE_TEST_MYSQL_DSN to run MySQL tests")
class MySQLAdapterTest(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.get("ASSAYSTONE_SQL_DSN")
        os.environ["ASSAYSTONE_SQL_DSN"] = DSN

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("ASSAYSTONE_SQL_DSN", None)
        else:
            os.environ["ASSAYSTONE_SQL_DSN"] = self._previous

    def run_sql(self, payload):
        return run_oracle(
            OracleSpec(
                id="mysql",
                type="sql",
                payload={
                    "driver": "mysql",
                    "dsn_env": "ASSAYSTONE_SQL_DSN",
                    **payload,
                },
            ),
            ".",
        )

    def test_scalar(self):
        result = self.run_sql(
            {"query": "select 1 as one", "expect": {"mode": "scalar", "equals": 1}}
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_session_is_read_only(self):
        result = self.run_sql(
            {
                "query": "select @@session.transaction_read_only as ro",
                "expect": {"mode": "scalar", "equals": 1},
            }
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_rows(self):
        result = self.run_sql(
            {
                "query": "select 1 as a, 'x' as b",
                "expect": {"mode": "rows", "equals": [{"a": 1, "b": "x"}]},
            }
        )
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_decimal_comparison(self):
        result = self.run_sql(
            {
                "query": "select 0.1 + 0.2 as v",
                "expect": {
                    "mode": "scalar",
                    "equals": 0.30000000000000004,
                    "tolerance": 1e-9,
                },
            }
        )
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(_same_scalar(Decimal("0.3"), 0.3, 0.0))

    def test_write_is_rejected(self):
        result = self.run_sql({"query": "delete from information_schema.tables"})
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("SELECT", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
