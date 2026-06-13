"""ShockRehearsal — tabletop shock rehearsal clearance for allocation rights.

A deterministic, stdlib-only tool that answers:
    "Does this tabletop shock rehearsal clear priority flow rights,
     buyer bloc volume, and refusal capacity under simulated coercion?"

Verdict scheme: passed / gaps / failed
Output: machine JSON + human Markdown
CLI triplet: sample / run / report

Derived from recreate DesignSeed (004-shock-rehearsal):
- ReserveFlow (priority clearing + ledger) — copy + parametrize
- BuyBloc (demand bloc volume) — parametrize
- RefusalOption (refusal headroom) — redesign for rehearsal
Lenses: L1_DirectionReversal, L17_ConstraintSubstitute
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ShockScenario:
    """Parsed shock rehearsal input."""

    def __init__(self, data: dict[str, Any]):
        self.id = data.get("id", "shock_scenario")
        self.priority_rights: dict[str, float] = data.get("priority_rights", {})
        self.bloc_volume: float = float(data.get("bloc_volume", 0.0))
        self.refusal_curves: dict[str, float] = data.get("refusal_curves", {})
        self.coercion_vector: dict[str, float] = data.get("coercion_vector", {})
        self.metadata: dict[str, Any] = data.get("metadata", {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority_rights": self.priority_rights,
            "bloc_volume": self.bloc_volume,
            "refusal_curves": self.refusal_curves,
            "coercion_vector": self.coercion_vector,
            "metadata": self.metadata,
        }


class RehearsalEngine:
    """Deterministic 3-axis scoring engine (rights + volume + refusal headroom)."""

    def __init__(self, scenario: ShockScenario):
        self.scenario = scenario
        # Weights and thresholds per DESIGN acceptance + seed
        self.rights_weight = 0.40
        self.volume_weight = 0.30
        self.refusal_weight = 0.30
        self.gap_threshold = 0.15
        self.fail_threshold = 0.30

    def score(self) -> dict[str, float]:
        rights = self._score_rights()
        volume = self._score_volume()
        refusal = self._score_refusal()
        composite = (
            rights * self.rights_weight +
            volume * self.volume_weight +
            refusal * self.refusal_weight
        )
        return {
            "rights": round(rights, 4),
            "volume": round(volume, 4),
            "refusal": round(refusal, 4),
            "composite": round(composite, 4),
        }

    def _score_rights(self) -> float:
        # Adapted from ReserveFlow priority clearing (copy + shock param)
        total = sum(self.scenario.priority_rights.values()) or 1.0
        shock = sum(self.scenario.coercion_vector.values()) * 0.10
        eff = total * max(0.0, 1.0 - shock)
        return max(0.0, min(1.0, eff / total))

    def _score_volume(self) -> float:
        # Adapted from BuyBloc aggregation (parametrized)
        base = self.scenario.bloc_volume
        shock = sum(self.scenario.coercion_vector.values()) * 0.20
        return max(0.0, min(1.0, base * (1.0 - shock)))

    def _score_refusal(self) -> float:
        # Adapted from RefusalOption (redesigned dynamic headroom)
        if not self.scenario.refusal_curves:
            return 0.50
        total = 0.0
        for axis, cap in self.scenario.refusal_curves.items():
            mult = self.scenario.coercion_vector.get(axis, 1.0)
            total += cap / max(0.1, mult)
        avg = total / len(self.scenario.refusal_curves)
        return max(0.0, min(1.0, avg))


class VerdictGate:
    """3-way verdict gate (passed / gaps / failed)."""

    def __init__(self, scores: dict[str, float]):
        self.scores = scores

    def decide(self) -> str:
        r = self.scores["rights"]
        v = self.scores["volume"]
        f = self.scores["refusal"]
        if r >= 0.85 and v >= 0.80 and f >= 0.80:
            return "passed"
        if r < 0.55 or v < 0.50 or f < 0.50:
            return "failed"
        return "gaps"


class HashLedger:
    """Append-only sha256 hash-chained ledger (stdlib)."""

    def __init__(self, path: str | Path = "ledger.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _last_hash(self) -> str:
        if self.path.exists() and self.path.stat().st_size > 0:
            last_line = self.path.read_text(encoding="utf-8").strip().split("\n")[-1]
            try:
                return json.loads(last_line).get("hash", "")
            except Exception:
                return ""
        return ""

    @staticmethod
    def _hash(prev: str, payload: dict) -> str:
        data = (prev + json.dumps(payload, sort_keys=True)).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def append(self, scenario: ShockScenario, scores: dict[str, float], verdict: str) -> dict[str, Any]:
        prev = self._last_hash()
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "scenario_id": scenario.id,
            "scores": scores,
            "verdict": verdict,
            "prev_hash": prev,
        }
        entry["hash"] = self._hash(prev, {k: v for k, v in entry.items() if k != "hash"})
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry


class DualReport:
    """Produces JSON (machine) + Markdown (human)."""

    def __init__(self, ledger_entry: dict[str, Any]):
        self.entry = ledger_entry

    def render(self) -> dict[str, Any]:
        verdict = self.entry["verdict"]
        scores = self.entry["scores"]
        json_out: dict[str, Any] = {
            "verdict": verdict,
            "scores": scores,
            "ledger_ref": self.entry["hash"][:16],
            "timestamp": self.entry["ts"],
        }
        md = (
            f"# ShockRehearsal Report — {verdict.upper()}\n\n"
            f"**Composite score**: {scores['composite']}\n\n"
            f"- rights: {scores['rights']}  |  volume: {scores['volume']}  |  refusal: {scores['refusal']}\n\n"
            "## Gaps / Notes\n"
            "- (detailed gap analysis populated by caller when verdict is gaps/failed)\n\n"
            f"**Ledger entry**: {self.entry['hash']}\n\n"
            "> Boundary: This is not a procurement auction or financial option exchange.\n"
        )
        return {"json": json_out, "markdown": md}


def load_scenario(path: str | Path) -> ShockScenario:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ShockScenario(data)


def run_rehearsal(scenario_path: str | Path, ledger_path: str | Path = "ledger.jsonl") -> dict[str, Any]:
    scenario = load_scenario(scenario_path)
    engine = RehearsalEngine(scenario)
    scores = engine.score()
    verdict = VerdictGate(scores).decide()
    ledger = HashLedger(ledger_path)
    entry = ledger.append(scenario, scores, verdict)
    report = DualReport(entry).render()
    return {
        "verdict": verdict,
        "scores": scores,
        "report": report,
        "ledger_entry": entry,
    }


def cmd_sample() -> None:
    """Emit a canonical example shock scenario JSON to stdout."""
    example = {
        "id": "example_shock_01",
        "priority_rights": {"mineral_a": 120.0, "mineral_b": 80.0},
        "bloc_volume": 0.92,
        "refusal_curves": {"rights": 0.95, "volume": 0.88, "coercion": 0.75},
        "coercion_vector": {"rights": 0.12, "volume": 0.08, "coercion": 0.15},
        "metadata": {"source": "recreate_seed_004", "lens": ["L1", "L17"]},
    }
    print(json.dumps(example, indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    result = run_rehearsal(args.scenario, args.ledger)
    if args.format == "json":
        print(json.dumps(result["report"]["json"], indent=2))
    else:
        print(result["report"]["markdown"])
    if args.verbose:
        print("\n[ledger entry hash]", result["ledger_entry"]["hash"][:16])


def cmd_report(args: argparse.Namespace) -> None:
    # For simplicity, re-run and emit the markdown report
    result = run_rehearsal(args.scenario, args.ledger)
    print(result["report"]["markdown"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shock_rehearsal",
        description="ShockRehearsal — tabletop shock rehearsal clearance for allocation rights",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sample = sub.add_parser("sample", help="emit example shock scenario JSON")
    p_sample.set_defaults(func=lambda a: cmd_sample())

    p_run = sub.add_parser("run", help="execute rehearsal against scenario")
    p_run.add_argument("scenario", help="path to shock scenario JSON")
    p_run.add_argument("--ledger", default="ledger.jsonl", help="ledger file path")
    p_run.add_argument("--format", choices=["md", "json"], default="md")
    p_run.add_argument("--verbose", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="render human report (alias of run --format md)")
    p_report.add_argument("scenario", help="path to shock scenario JSON")
    p_report.add_argument("--ledger", default="ledger.jsonl")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
