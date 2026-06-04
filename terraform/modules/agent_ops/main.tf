// Locals for one agent — pull the values the runtime threshold uses out of agent.yaml
// so detection and the loop's decision agree.

locals {
  drift_threshold = try(var.config.monitor.drift_threshold, 0.7)
  eval_policy     = try(var.config.eval.policy, "match")
  canary_traffic  = try(var.config.deploy.canary_traffic, 10)

  // Logging metric names disallow dashes; the agent's kebab name is kept for the
  // log filter (it matches what run_eval emits as jsonPayload.agent).
  metric_name = "${replace(var.agent_name, "-", "_")}_final_response_quality"

  labels = {
    app        = "agent-ops-l1"
    agent      = var.agent_name
    managed_by = "terraform"
  }
}
