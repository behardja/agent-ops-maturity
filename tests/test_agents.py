"""Central tests — the generic agent contract.

Discovered + parametrized over EVERY agents/*/agent.yaml, so dropping in a new agent folder
makes it validated automatically (each agent shows as its own test case). Not tied to any one
agent. Plus the repo-level configs/defaults.yaml. Pure (PyYAML / JSON); no cloud calls. An agent
that needs more than this central contract adds its own file under tests/agents/.
"""
import glob
import json
import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIRS = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(ROOT, "agents", "*", "agent.yaml")))
AGENT_IDS = [os.path.basename(d) for d in AGENT_DIRS]
GOLDEN = [(os.path.basename(d), os.path.join(d, "eval", "golden.evalset.json"))
          for d in AGENT_DIRS if os.path.exists(os.path.join(d, "eval", "golden.evalset.json"))]


def _yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def test_at_least_one_agent_discovered():
    assert AGENT_DIRS, "no agents/*/agent.yaml found"


@pytest.mark.parametrize("agent_dir", AGENT_DIRS, ids=AGENT_IDS)
def test_agent_yaml_is_valid(agent_dir):
    cfg = _yaml(os.path.join(agent_dir, "agent.yaml"))
    name = os.path.basename(agent_dir)
    for key in ("name", "display_name", "model", "eval", "monitor", "deploy"):
        assert key in cfg, f"{name}/agent.yaml missing required key: {key}"
    assert isinstance(cfg["model"], str) and cfg["model"].strip(), f"{name}: model unset"
    assert int(cfg["eval"].get("num_runs", 0)) >= 1, f"{name}: eval.num_runs must be >= 1"
    assert cfg["eval"].get("engine") in ("managed", "local"), f"{name}: eval.engine invalid"
    assert 0.0 < float(cfg["monitor"]["drift_threshold"]) <= 1.0, f"{name}: drift_threshold out of range"


@pytest.mark.parametrize("name,path", GOLDEN, ids=[n for n, _ in GOLDEN])
def test_golden_evalset_schema(name, path):
    cases = json.load(open(path))["eval_cases"]
    assert cases, f"{name}: empty golden set"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"{name}: duplicate case ids"
    for c in cases:
        assert "id" in c and "input" in c and "expected" in c, f"{name}/{c.get('id')}: missing fields"
        assert c["expected"].get("verdict") in ("PASS", "FAIL"), f"{name}/{c['id']}: bad verdict"
        if c["expected"]["verdict"] == "FAIL":
            viols = c["expected"].get("violations", [])
            assert viols and all("rule" in v for v in viols), f"{name}/{c['id']}: FAIL must cite rules"
    assert {c["expected"]["verdict"] for c in cases} == {"PASS", "FAIL"}, f"{name}: cover both verdicts"


def test_defaults_yaml_has_model_and_project():
    d = _yaml(os.path.join(ROOT, "configs", "defaults.yaml"))
    assert d["defaults"]["model"]
    assert d["project"]["id"]
