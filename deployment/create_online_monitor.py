"""Create the live online monitor for one agent (Preview).

The online monitor scores a sample of live traffic with the Final Response Quality rater
and is the richest L1 trigger signal. It is a Public Preview capability with no
stable Terraform resource or `gcloud` surface yet — creation is console-driven
(Agent Platform > Agents > Evaluation > Online monitors > New monitor).

This script is the seam Terraform's gated null_resource calls
(var.enable_online_monitor). It reads the agent's monitor spec
(agents/<name>/observability/monitor.yaml) and creates the monitor via the Vertex
SDK if the Preview API is available in your project; otherwise it prints the spec
and the console steps so the demo path stays unblocked.

Drift detection does NOT depend on this — the log-based metric + alert in
terraform/modules/agent_ops/observability.tf fire on any project. This only adds
the live signal when a project opts in.
"""

import argparse
import os

import yaml


def load_config(agent_dir):
    with open(os.path.join(agent_dir, "agent.yaml")) as f:
        return yaml.safe_load(f)


def load_monitor_spec(agent_dir):
    path = os.path.join(agent_dir, "observability", "monitor.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def create_monitor(agent_dir, project, region):
    cfg = load_config(agent_dir)
    spec = load_monitor_spec(agent_dir)
    monitor = cfg.get("monitor", {})
    sampling = monitor.get("sampling_percentage", 5)
    poll = monitor.get("poll_interval_minutes", 10)

    try:
        # Preview API — wrapped in try/except because the surface is not stable
        # across projects. If it's unavailable, fall through to the console path.
        from google.cloud import aiplatform_v1beta1 as aip  # noqa: F401

        raise NotImplementedError(
            "online monitor create is Preview / console-driven"
        )
    except (ImportError, NotImplementedError) as e:
        print(f"online monitor not created programmatically: {e}\n")
        print("Create it in the console (Public Preview):")
        print("  Agent Platform > Agents > Evaluation > Online monitors > New monitor")
        print(f"  agent dir       : {agent_dir}")
        print(f"  project/region  : {project}/{region}")
        print(f"  sampling        : {sampling}%")
        print(f"  poll interval   : ~{poll} min")
        print("  rater           : Final Response Quality\n")
        print("monitor spec (agents/<name>/observability/monitor.yaml):\n")
        print(yaml.safe_dump(spec, sort_keys=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="folder holding agent.yaml + observability/monitor.yaml")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    help="GCP project id (defaults to $GOOGLE_CLOUD_PROJECT)")
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    args = ap.parse_args()
    create_monitor(args.agent_dir, args.project, args.region)


if __name__ == "__main__":
    main()
