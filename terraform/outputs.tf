output "project_id" {
  value       = local.project_id
  description = "Resolved project (from var or configs/defaults.yaml)."
}

output "region" {
  value = local.region
}

output "agents" {
  value       = keys(local.agents)
  description = "Every agent discovered under agents/ and provisioned."
}

output "agent_service_accounts" {
  value       = { for k, m in module.agent_ops : k => m.service_account }
  description = "Per-agent SA backing provisioning + the loop's eval/deploy calls."
}

output "artifact_buckets" {
  value       = { for k, m in module.agent_ops : k => m.artifact_bucket }
  description = "Per-agent bucket for eval results, comparisons, optimizer outputs."
}

output "loop_trigger_topics" {
  value       = { for k, m in module.agent_ops : k => m.loop_trigger_topic }
  description = "Per-agent Pub/Sub topic to publish to (drift alert, scheduler, or manual) to kick the loop."
}

output "next_steps" {
  value = <<-EOT
    Infra is up for agents: ${join(", ", keys(local.agents))}
    Next:
      1. (if deploy_agent=false) deploy one: python deployment/deploy_agent.py --agent-dir agents/<name> --project ${local.project_id} --region ${local.region}
      2. Walk the demo notebooks in notebooks/ (01 deploy · 02 monitor · 03 run the loop).
      3. Online monitor is Preview — enable with -var enable_online_monitor=true once confirmed.
      4. Add another agent: create agents/<new-name>/ (app/agent.py + agent.yaml + eval/ + observability/ — see agents/README.md) and re-apply.
  EOT
}
