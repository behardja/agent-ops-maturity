// Root inputs. Per-agent settings (model, drift threshold, canary %, eval
// policy) are NOT here — they live in each agents/<name>/agent.yaml and are read
// per agent in main.tf. These variables are project-wide.
//
// Defaults for project/region fall back to ../configs/defaults.yaml; the only
// thing you must supply is the project id (there or via -var).

variable "project_id" {
  type        = string
  description = "GCP project that hosts the agents and their telemetry. Overrides project.id in configs/defaults.yaml."
  default     = ""
}

variable "region" {
  type        = string
  description = "Region for Agent Runtime and telemetry resources. Overrides project.region."
  default     = ""
}

// --- Feature gates (apply to every agent) ------------------------------------
// Native, always-safe infra applies by default. The two capabilities below are
// gated OFF so a first `terraform apply` succeeds on any project.

variable "deploy_agent" {
  type        = bool
  description = "Run the managed Agent Runtime deploy (SDK source/container — populates runtime revisions, same path as NB1/NB3 + cd.yml) via local-exec for each agent. Requires the Python deps + auth where terraform runs."
  default     = false
}

variable "enable_online_monitor" {
  type        = bool
  description = "Create the online Final Response Quality monitor (Preview) for each agent. Leave false until confirmed available; the alert/metric/dashboard still apply."
  default     = false
}

variable "enable_scheduled_eval" {
  type        = bool
  description = "Create each agent's Cloud Scheduler job that fires the loop's lightest trigger — a scheduled offline eval on the golden set."
  default     = true
}

variable "notification_email" {
  type        = string
  description = "Email for the shared drift-alert notification channel. Empty = no channel (alerts still fire, just unrouted)."
  default     = ""
}
