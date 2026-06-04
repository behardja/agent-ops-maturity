// Inputs for one agent's ops stack. The root module passes these per agent
// (for_each over agents/). `config` is the parsed agents/<name>/agent.yaml.

variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "agent_name" {
  type        = string
  description = "Folder name under agents/ (kebab-case, matches Agent Registry naming)."
}

variable "agent_path" {
  type        = string
  description = "Path to the agent folder (for file() reads of its specs)."
}

variable "config" {
  type        = any
  description = "Parsed agent.yaml (model, eval, monitor, deploy sections)."
}

variable "staging_bucket" {
  type        = string
  description = "Shared, project-level GCS bucket the SDK deploy stages the packaged agent to (bucket name, no gs:// prefix)."
}

variable "enable_scheduled_eval" {
  type    = bool
  default = true
}

variable "deploy_agent" {
  type    = bool
  default = false
}

variable "enable_online_monitor" {
  type    = bool
  default = false
}

variable "notification_channels" {
  type    = list(string)
  default = []
}
