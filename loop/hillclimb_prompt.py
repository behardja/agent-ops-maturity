"""Hill-climb knob (a): prompt optimization via the ADK optimizer.

Drives ADK's `SimplePromptOptimizer` (an iterative LLM-rewrite optimizer) to
refine the agent's system instruction against its golden eval set. The optimizer
needs a `Sampler` that scores a candidate agent on a batch of cases; we bridge
that to the same `LocalEvalService`-backed engine the threshold check uses
(`eval_tool`), so the optimizer hill-climbs the *real* Final Response Quality
judge.

The winning instruction is written to `<agent-dir>/results/optimized_instruction.txt`
and exposed via the `AGENT_INSTRUCTION_FILE` env var, which `agent.py` reads —
exactly mirroring how the model-migration knob (b) propagates `MODEL`. The loop
then evaluates the same agent-dir with that env set.

This is one of two independent, combinable knobs. Either alone counts if it
clears the threshold.

Tunables (env overrides win, then agent.yaml `eval.optimizer`, then defaults):
  OPTIMIZER_ITERS  - rewrite iterations            (default 3)
  OPTIMIZER_BATCH  - cases scored per candidate    (default 4, capped at N cases)
"""

import asyncio
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eval_tool")
)
import run_eval  # noqa: E402

from google.adk.evaluation.eval_config import (  # noqa: E402
    EvalConfig,
    get_eval_metrics_from_config,
)
from google.adk.evaluation.eval_set import EvalSet  # noqa: E402
from google.adk.optimization.data_types import (  # noqa: E402
    UnstructuredSamplingResult,
)
from google.adk.optimization.sampler import Sampler  # noqa: E402
from google.adk.optimization.simple_prompt_optimizer import (  # noqa: E402
    SimplePromptOptimizer,
    SimplePromptOptimizerConfig,
)


class _GoldenSetSampler(Sampler):
    """Scores a candidate agent on the golden set via the threshold's eval engine."""

    def __init__(self, eval_set, eval_metrics):
        self._eval_set = eval_set
        self._metrics = eval_metrics
        self._ids = [ec.eval_id for ec in eval_set.eval_cases]

    def get_train_example_ids(self):
        return list(self._ids)

    def get_validation_example_ids(self):
        return list(self._ids)

    async def sample_and_score(
        self,
        candidate,
        example_set="validation",
        batch=None,
        capture_full_eval_data=False,
    ):
        ids = set(batch) if batch else set(self._ids)
        subset = EvalSet(
            eval_set_id=self._eval_set.eval_set_id,
            eval_cases=[
                ec for ec in self._eval_set.eval_cases if ec.eval_id in ids
            ],
        )
        results_by_id = await run_eval.run_engine(
            candidate, subset, self._metrics, num_runs=1
        )
        scores = {}
        for cid, results in results_by_id.items():
            vals = [
                run_eval._overall_scores(r).get(run_eval.PRIMARY_METRIC)
                for r in results
            ]
            vals = [v for v in vals if v is not None]
            scores[cid] = sum(vals) / len(vals) if vals else 0.0
        return UnstructuredSamplingResult(scores=scores)


def optimize_prompt(agent_dir="agents/brand-guidelines-checker"):
    """Hill-climb the instruction; return the agent-dir to evaluate next.

    Writes the winning instruction to <agent-dir>/results/optimized_instruction.txt
    and sets AGENT_INSTRUCTION_FILE so the subsequent eval/deploy of the same
    agent-dir picks it up.
    """
    run_eval.ensure_vertex_env()
    config, root_agent = run_eval.load_agent(agent_dir)
    agent_name = config.get("name", agent_dir)

    with open(os.path.join(agent_dir, "eval/golden.evalset.json")) as f:
        golden = json.load(f)
    eval_set = run_eval.build_eval_set(agent_name, golden)

    eval_config = EvalConfig.model_validate_json(
        open(os.path.join(agent_dir, "eval/criteria.json")).read()
    )
    metrics = [
        m
        for m in get_eval_metrics_from_config(eval_config)
        if m.metric_name == run_eval.PRIMARY_METRIC
    ]

    opt_cfg = (config.get("eval") or {}).get("optimizer", {})
    n_cases = len(eval_set.eval_cases)
    cfg = SimplePromptOptimizerConfig(
        num_iterations=int(
            os.environ.get("OPTIMIZER_ITERS", opt_cfg.get("num_iterations", 3))
        ),
        batch_size=min(
            int(os.environ.get("OPTIMIZER_BATCH", opt_cfg.get("batch_size", 4))),
            n_cases,
        ),
    )

    sampler = _GoldenSetSampler(eval_set, metrics)
    result = asyncio.run(SimplePromptOptimizer(cfg).optimize(root_agent, sampler))
    best = result.optimized_agents[0].optimized_agent

    out_dir = os.path.join(agent_dir, "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "optimized_instruction.txt")
    with open(out_path, "w") as f:
        f.write(best.instruction)

    os.environ["AGENT_INSTRUCTION_FILE"] = os.path.abspath(out_path)
    print(
        f"prompt-optimization candidate for {agent_dir}: "
        f"AGENT_INSTRUCTION_FILE={out_path}"
    )
    return agent_dir


if __name__ == "__main__":
    print(optimize_prompt())
