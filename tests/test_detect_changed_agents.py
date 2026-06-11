"""Unit tests for .github/scripts/detect_changed_agents.sh — the change-detection that
builds the per-agent CD matrix.

Credential-free and cloud-free: each test spins up a throwaway git repo, makes a base
commit on `main` and a feature commit, runs the script with GITHUB_BASE_REF=main, and
asserts the emitted `agents` / `has_agents` outputs. Skips if git/bash/jq aren't on PATH.
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "detect_changed_agents.sh")

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("git", "bash", "jq")),
    reason="needs git + bash + jq on PATH",
)

DEPLOYABLE_MANIFEST = 'name: "{n}"\nagent_directory: "app"\ndeployable: true\n'
PROTOTYPE_MANIFEST = 'name: "{n}"\nagent_directory: "app"\n'   # no deployable => CD skips


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def _write(repo, rel, content):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _run(tmp_path, base_files, head_files):
    """base_files/head_files: {relpath: content}. Returns {'agents': [...], 'has_agents': '...'}."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    for rel, content in base_files.items():
        _write(repo, rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    for rel, content in head_files.items():
        _write(repo, rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")

    out = str(tmp_path / "out.txt")
    env = {**os.environ, "GITHUB_BASE_REF": "main", "GITHUB_OUTPUT": out}
    subprocess.run(["bash", SCRIPT], cwd=repo, check=True, capture_output=True, text=True, env=env)

    result = {}
    with open(out) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            result[k] = v
    result["agents"] = json.loads(result.get("agents", "[]"))
    return result


# Two deployable agents + one prototype form the standing base for every scenario.
BASE = {
    "agents/foo/agents-cli-manifest.yaml": DEPLOYABLE_MANIFEST.format(n="foo"),
    "agents/foo/app/agent.py": "v1\n",
    "agents/bar/agents-cli-manifest.yaml": DEPLOYABLE_MANIFEST.format(n="bar"),
    "agents/bar/app/agent.py": "v1\n",
    "agents/proto/agents-cli-manifest.yaml": PROTOTYPE_MANIFEST.format(n="proto"),
    "agents/proto/app/agent.py": "v1\n",
    "eval_tool/run_eval.py": "v1\n",
    "README.md": "v1\n",
}


def test_one_deployable_agent_changed(tmp_path):
    r = _run(tmp_path, BASE, {"agents/foo/app/agent.py": "v2\n"})
    assert r["agents"] == ["agents/foo"]
    assert r["has_agents"] == "true"


def test_two_agents_changed_sorted(tmp_path):
    r = _run(tmp_path, BASE, {"agents/foo/app/agent.py": "v2\n", "agents/bar/app/agent.py": "v2\n"})
    assert r["agents"] == ["agents/bar", "agents/foo"]
    assert r["has_agents"] == "true"


def test_prototype_only_change_is_skipped(tmp_path):
    r = _run(tmp_path, BASE, {"agents/proto/app/agent.py": "v2\n"})
    assert r["agents"] == []
    assert r["has_agents"] == "false"


def test_shared_code_change_deploys_all_deployable(tmp_path):
    r = _run(tmp_path, BASE, {"eval_tool/run_eval.py": "v2\n"})
    assert r["agents"] == ["agents/bar", "agents/foo"]   # proto excluded (not deployable)
    assert r["has_agents"] == "true"


def test_no_relevant_change_skips_cd(tmp_path):
    r = _run(tmp_path, BASE, {"README.md": "v2\n"})
    assert r["agents"] == []
    assert r["has_agents"] == "false"


def test_new_agent_folder_is_detected(tmp_path):
    head = {
        "agents/newagent/agents-cli-manifest.yaml": DEPLOYABLE_MANIFEST.format(n="newagent"),
        "agents/newagent/app/agent.py": "v1\n",
    }
    r = _run(tmp_path, BASE, head)
    assert r["agents"] == ["agents/newagent"]
    assert r["has_agents"] == "true"
