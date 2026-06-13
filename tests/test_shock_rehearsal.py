"""Basic tests for ShockRehearsal (stdlib, deterministic)."""

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shock_rehearsal import (
    ShockScenario,
    RehearsalEngine,
    VerdictGate,
    HashLedger,
    run_rehearsal,
)


class TestShockRehearsal(unittest.TestCase):
    def test_scenario_roundtrip(self):
        data = {"id": "t1", "priority_rights": {"a": 10}, "bloc_volume": 0.8,
                "refusal_curves": {"x": 0.9}, "coercion_vector": {"x": 0.1}}
        s = ShockScenario(data)
        self.assertEqual(s.id, "t1")
        self.assertIn("priority_rights", s.to_dict())

    def test_engine_scores_in_range(self):
        data = {"priority_rights": {"a": 100}, "bloc_volume": 0.9,
                "refusal_curves": {"r": 0.85}, "coercion_vector": {"r": 0.1}}
        s = ShockScenario(data)
        scores = RehearsalEngine(s).score()
        for k in ("rights", "volume", "refusal", "composite"):
            self.assertGreaterEqual(scores[k], 0.0)
            self.assertLessEqual(scores[k], 1.0)

    def test_verdict_logic(self):
        # high scores -> passed
        self.assertEqual(VerdictGate({"rights": 0.9, "volume": 0.88, "refusal": 0.87}).decide(), "passed")
        # low -> failed
        self.assertEqual(VerdictGate({"rights": 0.4, "volume": 0.3, "refusal": 0.5}).decide(), "failed")
        # middle -> gaps
        self.assertEqual(VerdictGate({"rights": 0.7, "volume": 0.6, "refusal": 0.65}).decide(), "gaps")

    def test_ledger_and_run(self):
        with tempfile.TemporaryDirectory() as td:
            scen = Path(td) / "s.json"
            led = Path(td) / "l.jsonl"
            scen.write_text(json.dumps({
                "priority_rights": {"m": 50}, "bloc_volume": 0.9,
                "refusal_curves": {"r": 0.9}, "coercion_vector": {"r": 0.05}
            }))
            out = run_rehearsal(scen, led)
            self.assertIn(out["verdict"], ("passed", "gaps", "failed"))
            self.assertTrue(led.exists())
            # hash present
            self.assertIn("hash", out["ledger_entry"])

    def test_cli_sample_smoke(self):
        # just ensure module import + basic structure
        from shock_rehearsal import cmd_sample
        # cmd_sample prints; we just ensure no crash on import/definition
        self.assertTrue(callable(cmd_sample))


if __name__ == "__main__":
    unittest.main()
