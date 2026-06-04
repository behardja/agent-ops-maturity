"""GCP-native managed Agent Evaluation backend — the platform twin of run_eval.py.

run_eval.py scores the agent with ADK's *local* engine (LocalEvalService). This module
scores it with Google Cloud's **managed** Agent Evaluation service (`vertexai`
`client.evals`), following the documented GEAP evaluation workflow:

    run_inference(agent, src)  ->  evaluate(dataset, metrics)  ->  results

(evaluate-agents / evaluate-offline / manage-metrics). `run_inference` runs the LOCAL
ADK agent over the golden inputs; `evaluate` scores the metric menu in one call and can
persist results to a Cloud Storage output path (`dest`, the evaluate-offline "Output
data path"). The output is adapted to the SAME results schema run_eval.py writes, so
eval_tool/compare.py and the loop consume it unchanged.

Metric menu (predefined + custom): a CUSTOM `types.LLMMetric` replicating our
cites_rule / actionable_fix rubric is the **headline** (computed by `evaluate`), plus
predefined `SAFETY` and `GENERAL_QUALITY`. The predefined Agent FINAL_RESPONSE_QUALITY /
HALLUCINATION raters are N/A for this single-turn, tool-less agent (they need a tool
trajectory or grounding context); revisit them when an agent has retrieval/tools.
"""

import json
import os

import pandas as pd

import run_eval  # reuse ensure_vertex_env / load_agent / parse_verdict

SAFETY_METRIC = "safety_v1"
GENERAL_QUALITY_METRIC = "general_quality_v1"

# The managed SDK requires the custom parser function be named exactly `parse_results`.
_PARSE_FN = (
    "import json, re\n"
    "def parse_results(responses):\n"
    "    m = re.search(r'\\{.*\\}', responses[0], re.S)\n"
    "    d = json.loads(m.group(0)) if m else {}\n"
    "    return {'score': float(d.get('score', 0.0)), 'explanation': d.get('explanation', '')}\n"
)


def custom_metric_name(agent_name):
    """Stable name for this agent's headline rubric metric."""
    return f"{agent_name.replace('-', '_')}_final_response_quality"


def _rubric_lines(criteria):
    """Render the headline rubric's sub-rubrics as grading bullets for the prompt."""
    spec = (criteria.get("criteria") or {}).get("rubric_based_final_response_quality_v1", {})
    lines = [f"- {r.get('rubric_id','')}: {(r.get('rubric_content') or {}).get('textProperty','')}"
             for r in spec.get("rubrics", [])]
    return "\n".join(lines) or "- The response is correct, complete, and actionable."


def thresholds(criteria):
    """Gating thresholds, read from criteria.json (headline + safety)."""
    crit = criteria.get("criteria") or {}
    frq = (crit.get("rubric_based_final_response_quality_v1") or {}).get("threshold", 0.8)
    safety = (crit.get("safety_v1") or {}).get("threshold", 1.0)
    return frq, safety


def build_custom_metric(agent_name, criteria, types):
    """A managed LLM metric replicating our Final Response Quality rubric."""
    return types.LLMMetric(
        name=custom_metric_name(agent_name),
        prompt_template=(
            "You are grading a single-turn brand-guidelines checker.\n"
            "Marketing copy:\n{prompt}\n\n"
            "Checker's JSON verdict:\n{response}\n\n"
            "Top score only if every reported violation cites the correct brand rule id "
            "and the suggested_fix is concrete and would resolve it.\n"
            f"{_rubric_lines(criteria)}\n\n"
            'Return ONLY JSON: {"score": <float 0-1>, "explanation": "<one sentence>"}'
        ),
        result_parsing_function=_PARSE_FN,
    )


def build_prompt_df(golden, agent_name, types):
    """Golden cases -> the inference frame (prompt + per-row session_inputs)."""
    si = types.evals.SessionInput(user_id="eval-user", app_name=agent_name)
    return pd.DataFrame(
        [{"prompt": c["input"], "session_inputs": si} for c in golden["eval_cases"]]
    )


def _metric_results(eval_case_result):
    """{metric_name: EvalCaseMetricResult} for a case's first candidate."""
    rcr = eval_case_result.response_candidate_results
    return rcr[0].metric_results if rcr else {}


def to_live_schema(eval_result, inferred, golden, criteria, agent_name, agent_dir, model):
    """Adapt the EvaluationResult into run_eval.py's output schema (so compare.py is unchanged)."""
    name = custom_metric_name(agent_name)
    frq_thr, safety_thr = thresholds(criteria)
    cases = golden["eval_cases"]
    responses = list(inferred.eval_dataset_df["response"])

    records = []
    for ecr in sorted(eval_result.eval_case_results or [], key=lambda e: e.eval_case_index):
        i = ecr.eval_case_index
        mr = _metric_results(ecr)

        def score(metric):
            m = mr.get(metric)
            return float(m.score) if m is not None and m.score is not None else 0.0

        frq, safety, general = score(name), score(SAFETY_METRIC), score(GENERAL_QUALITY_METRIC)
        expected = cases[i]["expected"]["verdict"]
        actual = run_eval.parse_verdict(responses[i] if i < len(responses) else "")
        records.append({
            "id": cases[i]["id"],
            "expected_verdict": expected,
            "final_response_quality": frq,
            "passed": 1 if (frq >= frq_thr and safety >= safety_thr) else 0,
            "verdict_correct": 1.0 if actual == expected else 0.0,
            "metric_scores": {name: frq, SAFETY_METRIC: safety, GENERAL_QUALITY_METRIC: general},
        })

    n = len(records)
    mean_frq = sum(r["final_response_quality"] for r in records) / n if n else 0.0
    return {
        "agent": agent_name,
        "agent_dir": agent_dir,
        "model": model,
        "num_runs": 1,
        "engine": "managed",
        "criteria": [name, SAFETY_METRIC, GENERAL_QUALITY_METRIC],
        "final_response_quality": mean_frq,
        "per_case": records,
    }


def run_managed(agent_dir, project=None, dest=None, out=None, model=None):
    """End-to-end managed eval (run_inference -> evaluate). Returns the live-schema dict.

    dest: optional GCS uri prefix to persist the managed results (the evaluate-offline
    output path). out: optional local path to write the adapted live.json.
    """
    run_eval.ensure_vertex_env()
    if model:
        os.environ["MODEL"] = model
    project = project or os.environ["GOOGLE_CLOUD_PROJECT"]

    config, agent = run_eval.load_agent(agent_dir)
    agent_name = config.get("name", os.path.basename(agent_dir.rstrip("/")))
    criteria = json.load(open(os.path.join(agent_dir, "eval/criteria.json")))
    golden = json.load(open(os.path.join(agent_dir, "eval/golden.evalset.json")))

    from vertexai import Client, types

    client = Client(project=project, location="global")
    inferred = client.evals.run_inference(agent=agent, src=build_prompt_df(golden, agent_name, types))
    metrics = [build_custom_metric(agent_name, criteria, types),
               types.RubricMetric.SAFETY, types.RubricMetric.GENERAL_QUALITY]
    cfg = types.EvaluateMethodConfig(dest=dest) if dest else None
    result = client.evals.evaluate(
        dataset=inferred, metrics=metrics,
        agent_info=types.evals.AgentInfo.load_from_agent(agent=agent), config=cfg,
    )

    live = to_live_schema(result, inferred, golden, criteria, agent_name, agent_dir,
                          os.environ.get("MODEL"))
    if dest:
        live["dest"] = dest
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(live, open(out, "w"), indent=2, default=str)
    return live
