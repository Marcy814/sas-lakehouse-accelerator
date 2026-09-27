terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40, < 7.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      projet        = var.projet
      environnement = var.environnement
      gere_par      = "terraform"
      donnees       = "confidentielles"
    }
  }
}
