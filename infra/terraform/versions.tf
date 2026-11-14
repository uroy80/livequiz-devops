terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    tls    = { source = "hashicorp/tls", version = "~> 4.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
    local  = { source = "hashicorp/local", version = "~> 2.5" }
  }
  # State location is passed by Jenkins:  terraform init -backend-config="path=..."
  backend "local" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "LiveQuiz", ManagedBy = "Terraform", Owner = "Usham Roy (RA2311003011574)" }
  }
}
