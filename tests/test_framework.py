"""Central tests — framework code.

Exercise the eval/loop code that EVERY agent uses (eval_tool/), independent of which agents
exist. Imports the modules (no cloud calls).
"""
import pytest

import managed_eval
import run_eval


@pytest.mark.parametrize("text,expected", [
    ('{"verdict": "PASS"}', "PASS"),
    ('{"verdict": "FAIL", "violations": [{"rule": 1}]}', "FAIL"),
    ('```json\n{"verdict": "FAIL"}\n```', "FAIL"),       # fenced -> regex fallback
    ('Sure! {"verdict":"PASS"} done', "PASS"),            # prose-wrapped -> regex fallback
    ('no verdict here', None),
    ('', None),
    (None, None),                                         # must not raise (TypeError-safe)
])
def test_parse_verdict(text, expected):
    assert run_eval.parse_verdict(text) == expected


def test_thresholds_defaults_when_missing():
    assert managed_eval.thresholds({}) == (0.8, 1.0)


def test_thresholds_reads_explicit_values():
    crit = {"criteria": {
        "rubric_based_final_response_quality_v1": {"threshold": 0.7},
        "safety_v1": {"threshold": 0.9},
    }}
    assert managed_eval.thresholds(crit) == (0.7, 0.9)


def test_rubric_lines_fallback_is_nonempty():
    assert managed_eval._rubric_lines({}).strip()


def test_rubric_lines_renders_bullets():
    crit = {"criteria": {"rubric_based_final_response_quality_v1": {"rubrics": [
        {"rubric_id": "cites_rule", "rubric_content": {"textProperty": "cites the broken rule"}},
    ]}}}
    out = managed_eval._rubric_lines(crit)
    assert "cites_rule" in out and "cites the broken rule" in out
