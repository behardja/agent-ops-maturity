// Per-agent observability — the detection half of L1 for this agent. All three
// resources apply on any project (no Preview dependency): a log-based Task
// Success metric, the drift alert that fires the loop, and the overview
// dashboard (sourced from the agent's own dashboard.json). The Preview online
// monitor is gated separately in agent.tf.

// Log-based metric: extracts the Final Response Quality score this agent's eval emits as
// structured logs. Always-available signal source, so the alert never depends on
// Preview. The filter matches what run_eval emits (jsonPayload.agent = the
// agent's kebab name).
resource "google_logging_metric" "final_response_quality" {
  name   = local.metric_name
  filter = "jsonPayload.metric=\"final_response_quality\" jsonPayload.agent=\"${var.agent_name}\""

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "DISTRIBUTION"
    unit         = "1"
    display_name = "${var.agent_name} — Final Response Quality (per scored case)"
  }

  value_extractor = "EXTRACT(jsonPayload.score)"

  bucket_options {
    explicit_buckets {
      bounds = [0.0, 0.25, 0.5, 0.7, 0.85, 1.0]
    }
  }
}

// Automatic trigger: rolling 1h mean Final Response Quality below this agent's
// threshold (from its agent.yaml), so detection and the loop's decision agree.
resource "google_monitoring_alert_policy" "final_response_quality_drift" {
  display_name = "${var.agent_name} — Final Response Quality drift"
  combiner     = "OR"

  conditions {
    display_name = "Rolling 1h mean Final Response Quality < ${local.drift_threshold}"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.final_response_quality.name}\" resource.type=\"global\""
      comparison      = "COMPARISON_LT"
      threshold_value = local.drift_threshold
      duration        = "0s"
      aggregations {
        alignment_period     = "3600s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_MEAN"
      }
    }
  }

  notification_channels = var.notification_channels

  documentation {
    content   = "Final Response Quality for ${var.agent_name} dropped below ${local.drift_threshold}. Fires the Continuous-Iteration loop (loop/run_ct_loop.py --agent-dir agents/${var.agent_name}). Route a channel to a webhook/Cloud Function to run the loop unattended."
    mime_type = "text/markdown"
  }
}

// Overview dashboard — sourced from the agent's own dashboard.json so that file
// stays the single definition (importable standalone too). The _comment key is
// stripped (the Dashboards API rejects unknown fields) and displayName is forced
// unique per agent.
resource "google_monitoring_dashboard" "overview" {
  dashboard_json = jsonencode(merge(
    {
      for k, v in jsondecode(file("${var.agent_path}/observability/dashboard.json")) :
      k => v if k != "_comment"
    },
    { displayName = "Agent Ops L1 — ${var.agent_name}" }
  ))
}
