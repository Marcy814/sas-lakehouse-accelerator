variable "projet" {
  description = "Préfixe des ressources."
  type        = string
  default     = "assurance"
}

variable "environnement" {
  description = "dev, qa ou prod."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "qa", "prod"], var.environnement)
    error_message = "environnement doit valoir dev, qa ou prod."
  }
}

variable "region" {
  description = "Région Azure : Canada Central pour la résidence des données au Canada."
  type        = string
  default     = "canadacentral"
}

variable "plage_reseau" {
  description = "Espace d'adressage du réseau virtuel."
  type        = string
  default     = "10.40.0.0/16"
}

variable "groupe_ingenieurs_donnees_object_id" {
  description = "Object ID Entra ID du groupe des ingénieurs de données."
  type        = string
}

variable "budget_mensuel_cad" {
  description = "Budget mensuel du groupe de ressources, en dollars."
  type        = number
  default     = 1500
}

variable "courriels_alertes_budget" {
  description = "Destinataires des alertes de budget."
  type        = list(string)
}

variable "date_debut_budget" {
  description = "Premier jour du mois de début du budget (AAAA-MM-01T00:00:00Z)."
  type        = string
  default     = "2026-10-01T00:00:00Z"
}
