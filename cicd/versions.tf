# Provider requirements for the cicd/ config (WIF + Artifact Registry).
# pipeline.yml is committed + generic (reads GitHub repo VARIABLES), so this config no longer
# renders a workflow file — it just provisions the keyless CI/CD infra and exposes the WIF outputs.
terraform {
  required_providers {
    google = { source = "hashicorp/google" }
  }
}
