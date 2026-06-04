// Per-agent outputs — the root module collects these into maps keyed by agent.

output "service_account" {
  description = "Provisioning/loop service account email for this agent."
  value       = google_service_account.agent.email
}

output "artifact_bucket" {
  description = "Bucket holding this agent's eval artifacts."
  value       = google_storage_bucket.artifacts.name
}

output "loop_trigger_topic" {
  description = "Pub/Sub topic that fires the Continuous-Iteration loop for this agent."
  value       = google_pubsub_topic.loop_trigger.id
}
