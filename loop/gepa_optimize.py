"""Hill-climb knob (a): GEPA prompt optimization — ADK's documented optimizer.

Runs ADK's `GEPARootAgentPromptOptimizer` (reflective Genetic-Pareto prompt search)
to rewrite the agent's instruction, scored on DETERMINISTIC **verdict accuracy** vs
the golden answer key. We score on verdict accuracy (not an LLM rubric) because on a
small evalset an LLM judge is too noisy to separate a good checker from a weak one —
it can't drive optimization. Verdict accuracy uses the ground truth we already have,
so GEPA gets a clean gradient: starting from a format-aware-but-rules-free instruction,
it reflects on the cases it gets wrong and DISCOVERS the brand rules.

Needs a GEPA-capable google-adk (>=1.30; this repo's env is on 1.34.2). GEPA's
`optimize()` runs via `asyncio.run()`, so in a notebook call `nest_asyncio.apply()` first.

Docs: https://adk.dev/optimize/#optimizing-an-agent-programmatically
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eval_tool"))
import run_eval  # noqa: E402  (reuses build_eval_set / run_engine / reduce_results / parse_verdict)

from google.adk.evaluation.eval_config import EvalConfig, get_eval_metrics_from_config  # noqa: E402
from google.adk.optimization.sampler import Sampler  # noqa: E402
from google.adk.optimization.data_types import UnstructuredSamplingResult  # noqa: E402
from google.adk.optimization.gepa_root_agent_prompt_optimizer import (  # noqa: E402
    GEPARootAgentPromptOptimizer,
    GEPARootAgentPromptOptimizerConfig,
)

APP_NAME = "brand_guidelines_checker"


def _det_metric():
    """A deterministic (ROUGE, no-LLM) metric so LocalEvalService.evaluate emits per-case
    results — we ignore its score and read verdict_correct, which is computed from the
    agent's actual response regardless of the metric."""
    return get_eval_metrics_from_config(EvalConfig(criteria={"response_match_score": 0.0}))


class VerdictSampler(Sampler):
    """GEPA sampler: per-case score = 1.0 iff the agent's PASS/FAIL verdict matches the golden."""

    def __init__(self, golden, samples=2):
        self.golden = golden
        self.ids = [c["id"] for c in golden["eval_cases"]]
        self._det = _det_metric()
        self.samples = samples   # inference passes averaged per case (denoise the verdict signal)

    def get_train_example_ids(self):
        return list(self.ids)

    def get_validation_example_ids(self):
        return list(self.ids)

    async def sample_and_score(self, candidate, example_set="validation", batch=None,
                               capture_full_eval_data=False):
        ids = set(batch) if batch else set(self.ids)
        sub = {"eval_cases": [c for c in self.golden["eval_cases"] if c["id"] in ids]}
        eval_set = run_eval.build_eval_set(APP_NAME, sub)
        results = await run_eval.run_engine(candidate, eval_set, self._det, self.samples)
        recs = run_eval.reduce_results(sub, results)
        return UnstructuredSamplingResult(
            scores={r["id"]: float(r["verdict_correct"]) for r in recs}
        )


def _load_agent(agent_dir, model, instruction_file):
    if model:
        os.environ["MODEL"] = model
    if instruction_file:
        os.environ["AGENT_INSTRUCTION_FILE"] = os.path.abspath(instruction_file)
    else:
        os.environ.pop("AGENT_INSTRUCTION_FILE", None)
    spec = importlib.util.spec_from_file_location("gepa_agent", os.path.join(agent_dir, "app", "agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.root_agent


async def _accuracy(sampler, agent):
    res = await sampler.sample_and_score(agent)
    vals = list(res.scores.values())
    return sum(vals) / len(vals) if vals else 0.0


async def _run(agent_dir, model, instruction_file, max_metric_calls, samples):
    run_eval.ensure_vertex_env()
    golden = json.load(open(os.path.join(agent_dir, "eval/golden.evalset.json")))
    sampler = VerdictSampler(golden, samples=samples)
    initial = _load_agent(agent_dir, model, instruction_file)
    before = await _accuracy(sampler, initial)
    optimizer = GEPARootAgentPromptOptimizer(
        config=GEPARootAgentPromptOptimizerConfig(max_metric_calls=max_metric_calls)
    )
    result = await optimizer.optimize(initial, sampler)
    best = result.optimized_agents[result.gepa_result["best_idx"]]
    return before, best.overall_score, best.optimized_agent.instruction, initial.instruction


def run_gepa(agent_dir="agents/brand-guidelines-checker", model="gemini-3.5-flash",
             instruction_file=None, max_metric_calls=40, out=None, quiet=True, samples=2):
    """Run GEPA, write the optimized instruction, return a summary dict.

    instruction_file defaults to the agent's eval/weak_instruction.txt (the live, drifted,
    format-aware-but-rules-free instruction GEPA improves from). quiet=True silences GEPA's
    verbose per-iteration progress (proposed prompts, Pareto fronts); set False to watch it."""
    import contextlib
    import io
    import logging
    instruction_file = instruction_file or os.path.join(agent_dir, "eval/weak_instruction.txt")
    out = out or os.path.join(agent_dir, "results/optimized_instruction.txt")
    if quiet:
        for _n in ("gepa", "google_adk.google.adk.optimization.gepa_root_agent_prompt_optimizer"):
            logging.getLogger(_n).setLevel(logging.ERROR)
    _ctx = contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext()
    with _ctx:
        before, after, instruction, start_instr = asyncio.run(
            _run(agent_dir, model, instruction_file, max_metric_calls, samples)
        )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(instruction)
    return {
        "before_accuracy": before,
        "after_accuracy": after,
        "changed": instruction.strip() != start_instr.strip(),
        "start_instruction": start_instr,
        "instruction": instruction,
        "out_path": out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker")
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--instruction-file", default=None)
    ap.add_argument("--max-metric-calls", type=int, default=40)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    r = run_gepa(args.agent_dir, args.model, args.instruction_file, args.max_metric_calls, args.out, samples=args.samples)
    print(f"verdict accuracy: {r['before_accuracy']:.3f} -> {r['after_accuracy']:.3f}  (changed={r['changed']})")
    print(f"wrote {r['out_path']}")
    print("\n--- optimized instruction ---\n" + r["instruction"])


if __name__ == "__main__":
    main()
