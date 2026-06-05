"""Run the offline threshold check (Agent Evaluation, offline mode) over one agent's golden evalset.

This is the SHARED eval runner — one copy for every agent. You point it at an
agent folder with --agent-dir; everything agent-specific (the agent code, its
criteria, its golden set) is read from that folder:

    agents/<name>/app/agent.py             -> the agent (root_agent)
    agents/<name>/agent.yaml               -> config (model, eval policy, ...)
    agents/<name>/eval/criteria.json       -> ADK EvalConfig (the LLM-judge metrics)
    agents/<name>/eval/golden.evalset.json -> the golden cases
    agents/<name>/results/                  -> where this writes (gitignored)

Scoring runs through ADK's local Agent Evaluation engine (LocalEvalService) — the
same engine `adk eval` / `agents-cli eval run` wrap. The engine inferences the
agent itself (no hand-written invoke()) and applies the criteria.json metrics —
the GEAP Agent Evaluation raters surfaced locally for this single-turn, tool-less
agent: `rubric_based_final_response_quality_v1` (Final Response Quality),
`hallucinations_v1` (Hallucination), `safety_v1` (Safety). All are real Gemini LLM
judges (they need GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION).

Each per-case record carries:
    final_response_quality -- mean rubric_based_final_response_quality_v1 score
                       across runs (the GEAP Final Response Quality rater; the
                       threshold check's bootstrap CI runs on it)
    passed          -- 1 iff every run PASSED all metrics (incl. the hallucination
                       and safety guardrails); compare.py's zero-regression check keys on it
    verdict_correct -- judge-free exact PASS/FAIL verdict match (headline sanity)
    metric_scores   -- per-metric mean score, for transparency

Usage:
    python eval_tool/run_eval.py --agent-dir agents/brand-guidelines-checker \
        --out agents/brand-guidelines-checker/results/live.json
"""

import argparse
import asyncio
import importlib.util
import json
import os
import re
import statistics

import yaml

from google.genai import types as genai_types

# The local ADK eval engine is OPTIONAL — its deps (google-adk[eval]: rouge-score, gepa, …)
# live in the agent's `eval` extra, not the runtime/CI install. The managed engine is the
# default, and the pure helpers below (parse_verdict, load_agent, ensure_vertex_env) don't need
# this stack — so a missing extra mustn't break import (e.g. unit tests in CI). We guard on it in
# main() before the local path runs.
try:
    from google.adk.evaluation.base_eval_service import (
        EvaluateConfig,
        EvaluateRequest,
        InferenceConfig,
        InferenceRequest,
    )
    from google.adk.evaluation.eval_case import Invocation
    from google.adk.evaluation.eval_config import (
        EvalConfig,
        get_eval_metrics_from_config,
    )
    from google.adk.evaluation.eval_set import EvalCase, EvalSet
    from google.adk.evaluation.evaluator import EvalStatus
    from google.adk.evaluation.in_memory_eval_sets_manager import (
        InMemoryEvalSetsManager,
    )
    from google.adk.evaluation.local_eval_service import LocalEvalService
    from google.adk.evaluation.simulation.user_simulator_provider import (
        UserSimulatorProvider,
    )
    from google.adk.utils.context_utils import Aclosing

    _LOCAL_ENGINE_AVAILABLE = True
except ImportError:
    _LOCAL_ENGINE_AVAILABLE = False

# The GEAP Final Response Quality rater — the headline the threshold's bootstrap CI runs on.
PRIMARY_METRIC = "rubric_based_final_response_quality_v1"
APP_NAME = "eval_app"


def ensure_vertex_env():
    """Point the agent + LLM-judge Gemini calls at Vertex's global endpoint.

    Both the agent under test and the LLM-judge metrics call Gemini through the
    google-genai SDK. We route them to Vertex (GOOGLE_GENAI_USE_VERTEXAI) on the
    *global* endpoint (GOOGLE_CLOUD_LOCATION=global) — better model availability
    and no regional-capacity flakiness, and it's the recommended endpoint for
    Gemini on Vertex. The project defaults from configs/defaults.yaml.

    Everything is setdefault, so an already-exported env var (e.g. the authed
    sandbox project, or a pinned region) wins and the placeholder in
    defaults.yaml is ignored. Note: this is the eval/inference endpoint only —
    deploy/teardown still use the regional location from defaults.yaml.
    """
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "configs", "defaults.yaml"
    )
    if not os.path.exists(cfg_path):
        return
    with open(cfg_path) as f:
        d = yaml.safe_load(f) or {}
    pid = (d.get("project") or {}).get("id")
    if pid and pid != "YOUR_PROJECT":
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", pid)


def load_agent(agent_dir):
    """Load an agent folder: returns (config dict, root_agent object).

    Agent folders are named with dashes (matching Agent Registry), so we load
    agent.py by file path rather than as an importable package. The baseline
    model from agent.yaml is set on MODEL unless already overridden (e.g. by the
    loop's model-migration knob or --model, which set MODEL for the candidate).
    """
    with open(os.path.join(agent_dir, "agent.yaml")) as f:
        config = yaml.safe_load(f)
    os.environ.setdefault("MODEL", config.get("model", "gemini-2.5-flash"))

    spec = importlib.util.spec_from_file_location(
        "agent_under_test", os.path.join(agent_dir, "app", "agent.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return config, module.root_agent


def parse_verdict(response_text):
    """Pull the PASS/FAIL verdict out of the agent's JSON response."""
    try:
        return json.loads(response_text).get("verdict")
    except (json.JSONDecodeError, AttributeError, TypeError):
        match = re.search(r'"verdict"\s*:\s*"(PASS|FAIL)"', response_text or "")
        return match.group(1) if match else None


def build_eval_set(agent_name, golden):
    """Convert our golden.evalset.json (custom schema) into an ADK EvalSet.

    Each golden case becomes a single-invocation EvalCase whose reference
    final_response is the serialized expected verdict — the rubric-based Final
    Response Quality judge scores the agent's actual answer with that as context.
    """
    cases = []
    for c in golden["eval_cases"]:
        cases.append(
            EvalCase(
                eval_id=c["id"],
                conversation=[
                    Invocation(
                        invocation_id=c["id"],
                        user_content=genai_types.Content(
                            role="user",
                            parts=[genai_types.Part(text=c["input"])],
                        ),
                        final_response=genai_types.Content(
                            role="model",
                            parts=[genai_types.Part(text=json.dumps(c["expected"]))],
                        ),
                    )
                ],
            )
        )
    return EvalSet(eval_set_id=agent_name, eval_cases=cases)


async def run_engine(root_agent, eval_set, eval_metrics, num_runs):
    """Inference + evaluate via ADK's LocalEvalService; return {eval_id: [EvalCaseResult]}.

    num_runs > 1 reruns inference to absorb temperature-1 output variance; each
    run yields one EvalCaseResult per case, collected per eval_id.
    """
    mgr = InMemoryEvalSetsManager()
    mgr.create_eval_set(app_name=APP_NAME, eval_set_id=eval_set.eval_set_id)
    for ec in eval_set.eval_cases:
        mgr.add_eval_case(
            app_name=APP_NAME, eval_set_id=eval_set.eval_set_id, eval_case=ec
        )

    service = LocalEvalService(
        root_agent=root_agent,
        eval_sets_manager=mgr,
        user_simulator_provider=UserSimulatorProvider(user_simulator_config=None),
    )

    inference_results = []
    for _ in range(num_runs):
        request = InferenceRequest(
            app_name=APP_NAME,
            eval_set_id=eval_set.eval_set_id,
            inference_config=InferenceConfig(),
        )
        async with Aclosing(service.perform_inference(inference_request=request)) as gen:
            async for inference_result in gen:
                inference_results.append(inference_result)

    results_by_id = {}
    evaluate_request = EvaluateRequest(
        inference_results=inference_results,
        evaluate_config=EvaluateConfig(eval_metrics=eval_metrics),
    )
    async with Aclosing(service.evaluate(evaluate_request=evaluate_request)) as gen:
        async for eval_case_result in gen:
            results_by_id.setdefault(eval_case_result.eval_id, []).append(
                eval_case_result
            )
    return results_by_id


def _overall_scores(eval_case_result):
    """metric_name -> overall score for one EvalCaseResult."""
    return {
        m.metric_name: m.score
        for m in eval_case_result.overall_eval_metric_results
    }


def _actual_text(eval_case_result):
    """The agent's actual final-response text from a result (single-invocation cases)."""
    for per_inv in eval_case_result.eval_metric_result_per_invocation:
        content = per_inv.actual_invocation.final_response
        if content and content.parts:
            return "".join(p.text for p in content.parts if p.text)
    return ""


def reduce_results(golden, results_by_id):
    """Fold per-run EvalCaseResults into one record per golden case."""
    records = []
    for case in golden["eval_cases"]:
        cid = case["id"]
        expected_verdict = case["expected"]["verdict"]
        runs = results_by_id.get(cid, [])

        primary_scores, passed_runs, verdict_hits = [], [], []
        metric_accum = {}
        for result in runs:
            scores = _overall_scores(result)
            if scores.get(PRIMARY_METRIC) is not None:
                primary_scores.append(scores[PRIMARY_METRIC])
            for name, score in scores.items():
                if score is not None:
                    metric_accum.setdefault(name, []).append(score)
            passed_runs.append(1 if result.final_eval_status == EvalStatus.PASSED else 0)
            verdict_hits.append(
                int(parse_verdict(_actual_text(result)) == expected_verdict)
            )

        records.append(
            {
                "id": cid,
                "expected_verdict": expected_verdict,
                "final_response_quality": statistics.mean(primary_scores) if primary_scores else 0.0,
                "passed": 1 if passed_runs and all(passed_runs) else 0,
                "verdict_correct": statistics.mean(verdict_hits) if verdict_hits else 0.0,
                "metric_scores": {n: statistics.mean(v) for n, v in metric_accum.items()},
            }
        )
    return records


def emit_score_logs(agent_label, records):
    """Emit one structured JSON line per case to stdout.

    On Agent Runtime / Vertex these become Cloud Logging entries the per-agent
    log-based metric `<agent>_final_response_quality` extracts (filter:
    jsonPayload.metric="final_response_quality"). This makes the offline-eval path a real
    signal source for the drift alert — no Preview online monitor required.
    """
    for r in records:
        print(json.dumps({
            "metric": "final_response_quality",
            "agent": agent_label,
            "case": r["id"],
            "score": r["final_response_quality"],
        }))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="folder holding agent.py, agent.yaml, eval/, observability/")
    ap.add_argument("--evalset", help="defaults to <agent-dir>/eval/golden.evalset.json")
    ap.add_argument("--criteria", help="defaults to <agent-dir>/eval/criteria.json")
    ap.add_argument("--out", help="defaults to <agent-dir>/results/eval.json")
    ap.add_argument("--num-runs", type=int,
                    help="inference repeats; defaults to agent.yaml eval.num_runs or 2")
    ap.add_argument("--model",
                    help="override the agent model (hill-climb model-migration knob)")
    ap.add_argument("--emit-logs", action="store_true",
                    help="emit per-case final_response_quality log lines for the log-based metric")
    ap.add_argument("--engine", choices=["local", "managed"],
                    help="scoring backend: 'local' (ADK LocalEvalService) or 'managed' "
                         "(GCP Agent Evaluation via client.evals.evaluate). Defaults to "
                         "agent.yaml eval.engine, else 'local'.")
    ap.add_argument("--dest", help="managed engine: optional GCS uri prefix to persist "
                                   "the evaluation results (the evaluate-offline output path)")
    args = ap.parse_args()

    if args.model:
        os.environ["MODEL"] = args.model

    evalset_path = args.evalset or os.path.join(args.agent_dir, "eval/golden.evalset.json")
    criteria_path = args.criteria or os.path.join(args.agent_dir, "eval/criteria.json")
    out_path = args.out or os.path.join(args.agent_dir, "results/eval.json")

    # Engine resolves from the flag, else agent.yaml eval.engine, else local.
    engine = args.engine
    if engine is None:
        try:
            with open(os.path.join(args.agent_dir, "agent.yaml")) as f:
                engine = (yaml.safe_load(f).get("eval") or {}).get("engine", "local")
        except (OSError, AttributeError):
            engine = "local"

    if engine == "managed":
        # GCP-native managed Agent Evaluation (client.evals.evaluate). Produces the
        # same results schema run_eval's local engine writes, so compare.py is unchanged.
        import managed_eval
        live = managed_eval.run_managed(
            args.agent_dir, dest=args.dest, out=out_path, model=args.model,
        )
        if args.emit_logs:
            emit_score_logs(live["agent"], live["per_case"])
        n = len(live["per_case"])
        dest_note = f" (persisted to {live['dest']})" if live.get("dest") else ""
        print(f"final_response_quality={live['final_response_quality']:.3f} over {n} cases "
              f"(engine=managed){dest_note} -> {out_path}")
        return

    if not _LOCAL_ENGINE_AVAILABLE:
        raise SystemExit(
            "Local eval engine unavailable: the ADK eval extra isn't installed.\n"
            "  Install it:  pip install 'google-adk[eval]'   (rouge-score, gepa, …)\n"
            "  Or use the managed engine:  --engine managed"
        )

    ensure_vertex_env()

    with open(evalset_path) as f:
        golden = json.load(f)

    config, agent = load_agent(args.agent_dir)
    agent_name = config.get("name", args.agent_dir)
    num_runs = args.num_runs or config.get("eval", {}).get("num_runs", 2)

    eval_config = EvalConfig.model_validate_json(open(criteria_path).read())
    eval_metrics = get_eval_metrics_from_config(eval_config)

    eval_set = build_eval_set(agent_name, golden)
    results_by_id = asyncio.run(run_engine(agent, eval_set, eval_metrics, num_runs))
    records = reduce_results(golden, results_by_id)

    n = len(records)
    final_response_quality = sum(r["final_response_quality"] for r in records) / n if n else 0.0

    if args.emit_logs:
        emit_score_logs(agent_name, records)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "agent": agent_name,
                "agent_dir": args.agent_dir,
                "model": os.environ.get("MODEL"),
                "num_runs": num_runs,
                "criteria": eval_config.criteria and list(eval_config.criteria.keys()),
                "final_response_quality": final_response_quality,
                "per_case": records,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"final_response_quality={final_response_quality:.3f} over {n} cases -> {out_path}")


if __name__ == "__main__":
    main()
