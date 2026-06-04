"""Agent Identity & least-privilege — Central CI lint.

The agent's RUNTIME identity (Agent Identity / SPIFFE) is auto-issued by Agent
Runtime at deploy time and can't be unit-tested. What we CAN enforce in CI,
credential-free, is the least-privilege CONFIG around it: every agent runs under
its own dedicated service account, granted roles stay within a reviewed allowlist
(no owner/editor/broad-admin), and there are no long-lived service-account keys
(keyless = WIF + Agent Identity).

Deny-by-default: adding a role to the Terraform means adding it to the allowlist
here too — a deliberate review gate.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT_IAM = REPO / "terraform/modules/agent_ops/iam.tf"
CICD_WIF = REPO / "cicd/wif.tf"

# Reviewed least-privilege allowlist for the per-agent ops SA.
AGENT_SA_ROLES = {
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/monitoring.metricWriter",
    "roles/storage.objectAdmin",
}

# Reviewed allowlist for the CI/CD deployer SA (broader by necessity — it builds + deploys).
DEPLOYER_SA_ROLES = {
    "roles/aiplatform.user",
    "roles/artifactregistry.writer",
    "roles/storage.admin",
    "roles/cloudbuild.builds.editor",
    "roles/logging.viewer",
    "roles/iam.workloadIdentityUser",
}

# Never acceptable on a non-human identity.
FORBIDDEN = {"roles/owner", "roles/editor"}


def _roles(path):
    return set(re.findall(r"roles/[A-Za-z0-9._]+", path.read_text()))


def test_agent_runs_under_dedicated_per_agent_sa():
    # Each agent gets its own {name}-sa (folder-derived), never a shared/default SA.
    assert '"${var.agent_name}-sa"' in AGENT_IAM.read_text()


def test_agent_sa_roles_within_allowlist():
    extra = _roles(AGENT_IAM) - AGENT_SA_ROLES
    assert not extra, f"agent SA has roles outside the least-privilege allowlist: {sorted(extra)}"


def test_deployer_sa_roles_within_allowlist():
    extra = _roles(CICD_WIF) - DEPLOYER_SA_ROLES
    assert not extra, f"deployer SA has roles outside its reviewed allowlist: {sorted(extra)}"


def test_no_project_owner_or_editor():
    for f in (AGENT_IAM, CICD_WIF):
        assert not (_roles(f) & FORBIDDEN), f"{f.name} grants project owner/editor (not least-privilege)"


def test_no_long_lived_service_account_keys():
    for f in (AGENT_IAM, CICD_WIF):
        assert "google_service_account_key" not in f.read_text(), (
            f"{f.name} creates a long-lived SA key — use WIF / Agent Identity instead"
        )
