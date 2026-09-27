locals {
  nom         = "${var.projet}-${var.environnement}"
  nom_compact = replace(local.nom, "-", "")
  couches     = ["landing", "bronze", "silver", "gold"]
  tags = {
    projet        = var.projet
    environnement = var.environnement
    gere_par      = "terraform"
    donnees       = "confidentielles"
  }
}

data "azurerm_client_config" "courant" {}

resource "azurerm_resource_group" "lakehouse" {
  name     = "rg-${local.nom}-lakehouse"
  location = var.region
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "journaux" {
  name                = "log-${local.nom}"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  sku                 = "PerGB2018"
  retention_in_days   = 90
  tags                = local.tags
}
