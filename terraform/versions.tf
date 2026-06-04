// Provider + Terraform version pins for the Agent Ops L1 platform.
terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
  // For team use, point this at a GCS bucket so state is shared + locked.
  // backend "gcs" {
  //   bucket = "YOUR_PROJECT-agent-ops-tfstate"
  //   prefix = "agent-ops-l1"
  // }
}

provider "google" {
  project = local.project_id
  region  = local.region
}
