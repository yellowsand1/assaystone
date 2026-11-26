"""A canary compares distributions, not single measurements."""

import json
import random
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assaystone.canary import compare_means, extract, run_comparison
from assaystone.oracles import OracleSpec, run_oracle


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        rng = random.Random(self.path)
        if self.path.startswith("/same"):
            value = 100 + rng.gauss(0, 5)
        elif self.path.startswith("/worse"):
            value = 130 + rng.gauss(0, 5)
        elif self.path.startswith("/noisy"):
            value = 100 + rng.gauss(0, 40)
        elif self.path.startswith("/broken"):
            self.send_response(500)
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"p95_ms": value}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class CanaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

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

    def canary(self, baseline, candidate, **extra):
        payload = {
            "baseline": {"type": "http", "payload": {"url": self.url(baseline)}},
            "candidate": {"type": "http", "payload": {"url": self.url(candidate)}},
            "json_path": "p95_ms",
            "samples": 12,
            **extra,
        }
        return run_oracle(
            OracleSpec(id="canary", type="canary", payload=payload), self.root
        )

    def test_an_equivalent_candidate_passes(self):
        result = self.canary("/same", "/same")
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertIn("baseline_median", result.facts)

    def test_a_worse_candidate_fails_with_an_interval(self):
        result = self.canary("/same", "/worse")
        self.assertEqual(result.outcome, "fail")
        self.assertIn("worse than the baseline", result.reasons[0])
        self.assertIn("excludes zero", result.reasons[0])

    def test_noise_is_not_a_regression(self):
        result = self.canary("/noisy", "/noisy", max_relative_increase=0.05)
        self.assertEqual(result.outcome, "pass", result.reasons)

    def test_a_tolerance_can_absorb_a_small_change(self):
        close = self.canary("/same", "/worse", max_relative_increase=0.5)
        self.assertEqual(close.outcome, "pass", close.reasons)

    def test_too_few_samples_escalates(self):
        result = self.canary("/same", "/same", samples=3)
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("fewer than five", result.reasons[0])

    def test_a_side_that_does_not_answer_escalates(self):
        result = self.canary("/same", "/broken")
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("could not complete", result.reasons[0])

    def test_a_missing_number_escalates(self):
        payload = {
            "baseline": {"type": "http", "payload": {"url": self.url("/same")}},
            "candidate": {"type": "http", "payload": {"url": self.url("/same")}},
            "json_path": "absent",
            "samples": 6,
        }
        result = run_oracle(
            OracleSpec(id="canary", type="canary", payload=payload), self.root
        )
        self.assertEqual(result.outcome, "escalate")

    def test_a_canary_cannot_nest(self):
        payload = {
            "baseline": {"type": "canary", "payload": {}},
            "candidate": {"type": "http", "payload": {"url": self.url("/same")}},
        }
        result = run_oracle(
            OracleSpec(id="canary", type="canary", payload=payload), self.root
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("cannot be nested", result.reasons[0])


class StatisticsTest(unittest.TestCase):
    def test_extract_from_json_and_text(self):
        class Result:
            def __init__(self, output):
                self.output = output

        self.assertEqual(extract(Result('{"a": {"b": 1.5}}'), "a.b"), 1.5)
        self.assertEqual(extract(Result("p95=12.5ms"), ""), 12.5)
        with self.assertRaises(ValueError):
            extract(Result("no digits here"), "")

    def test_the_interval_excludes_zero_for_a_real_difference(self):
        change, low, high = compare_means(
            [100 + (i % 3) for i in range(30)],
            [160 + (i % 3) for i in range(30)],
        )
        self.assertGreater(change, 50)
        self.assertGreater(low, 0)

    def test_identical_distributions_straddle_zero(self):
        values = [100 + (i % 5) for i in range(30)]
        _, low, high = compare_means(values, values)
        self.assertLessEqual(low, 0)
        self.assertGreaterEqual(high, 0)

    def test_the_comparison_is_deterministic(self):
        first = compare_means([1.0, 2.0, 3.0, 4.0], [2.0, 3.0, 4.0, 5.0])
        second = compare_means([1.0, 2.0, 3.0, 4.0], [2.0, 3.0, 4.0, 5.0])
        self.assertEqual(first, second)

    def test_a_zero_baseline_escalates(self):
        def side(name):
            return (0.0, "") if name == "baseline" else (1.0, "")

        result = run_comparison(side, samples=6)
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("zero", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
