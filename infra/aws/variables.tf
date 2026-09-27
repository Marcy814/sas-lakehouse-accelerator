variable "projet" {
  type    = string
  default = "assurance"
}

variable "environnement" {
  type    = string
  default = "dev"

  validation {
    condition     = contains(["dev", "qa", "prod"], var.environnement)
    error_message = "environnement doit valoir dev, qa ou prod."
  }
}

variable "region" {
  description = "ca-central-1 pour la résidence des données au Canada."
  type        = string
  default     = "ca-central-1"
}

variable "budget_mensuel_usd" {
  type    = number
  default = 1000
}

variable "courriels_alertes_budget" {
  type = list(string)
}
