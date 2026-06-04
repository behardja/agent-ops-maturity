// Per-agent loop trigger plumbing — the "fire the loop" half of L1.
//
// The Pub/Sub topic is the seam the drift alert routes to (wire a channel to a
// webhook/Cloud Function that runs loop/run_ct_loop.py --agent-dir
// agents/<name>). The Cloud Scheduler job is the lightest-entry signal source:
// an offline golden-set eval on a cron, independent of Preview online
// monitoring. Both reach the same four loop steps.

// Loop trigger topic — message here = "iterate this agent now". The alert and
// the scheduler both publish to it.
resource "google_pubsub_topic" "loop_trigger" {
  name   = "${var.agent_name}-loop-trigger"
  labels = local.labels
}

// Scheduled offline eval — the always-available trigger source. Publishes to the
// loop topic on a cron; gated so a project can opt out (e.g. online-monitor-only
// setups). Payload carries the agent so the subscriber knows which folder to run.
resource "google_cloud_scheduler_job" "scheduled_eval" {
  count    = var.enable_scheduled_eval ? 1 : 0
  name     = "${var.agent_name}-scheduled-eval"
  region   = var.region
  schedule = try(var.config.eval.schedule, "0 * * * *")

  pubsub_target {
    topic_name = google_pubsub_topic.loop_trigger.id
    data       = base64encode(jsonencode({ agent = var.agent_name, source = "scheduled-eval" }))
  }
}
