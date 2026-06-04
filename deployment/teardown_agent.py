"""Tear down one agent's deployed Agent Runtime (the inverse of deploy_agent.py).

Shared teardown script — one copy for every agent. Point it at an agent folder
with --agent-dir; the agent's registered name comes from agents/<name>/agent.yaml.

There is no `agents-cli` delete verb — deleting a deployed agent is SDK-only.
This lists the project's Agent Runtimes, matches the one whose display_name equals
this agent's name, and deletes it. It is called two ways:

  * the notebook teardown path (notebooks/05-teardown.ipynb), and
  * Terraform's destroy-time provisioner on the deploy null_resource
    (terraform/modules/agent_ops/agent.tf), so `terraform destroy` actually
    undeploys the managed agent instead of leaving it running.

Idempotent: prints what it deleted, or says nothing matched.
"""

import argparse
import os

import yaml


def load_config(agent_dir):
    with open(os.path.join(agent_dir, "agent.yaml")) as f:
        return yaml.safe_load(f)


def teardown(agent_dir, project, region):
    import vertexai
    from vertexai import agent_engines

    name = load_config(agent_dir).get("name", os.path.basename(agent_dir.rstrip("/")))
    vertexai.init(project=project, location=region)

    # Match by display_name. deploy_agent.py creates the engine from the agent
    # folder; depending on how your deploy names the resource you may need to
    # adjust this predicate (e.g. match a name prefix or a label).
    deleted = []
    for ae in agent_engines.list():
        display_name = getattr(ae, "display_name", None) or getattr(
            getattr(ae, "api_resource", None), "display_name", None
        )
        if display_name == name:
            ae.delete(force=True)
            deleted.append(getattr(ae, "resource_name", display_name))

    if deleted:
        print(f"deleted Agent Runtime(s) for '{name}': {', '.join(map(str, deleted))}")
    else:
        print(f"no deployed Agent Runtime found with display_name '{name}' — nothing to delete")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="folder holding agent.yaml (its name is matched against deployed runtimes)")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    help="GCP project id (defaults to $GOOGLE_CLOUD_PROJECT)")
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    args = ap.parse_args()

    teardown(args.agent_dir, args.project, args.region)


if __name__ == "__main__":
    main()
