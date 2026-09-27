# Moindre privilège : chaque identité managée ne reçoit que le rôle et la portée dont elle a besoin.

locals {
  portee_conteneur = { for c in local.couches : c => "${azurerm_storage_account.lac.id}/blobServices/default/containers/${c}" }
}

# Azure Data Factory dépose les extraits : écriture sur landing uniquement.
resource "azurerm_role_assignment" "adf_ecrit_landing" {
  scope                = local.portee_conteneur["landing"]
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.ingestion.identity[0].principal_id
}

# Le connecteur d'accès Unity Catalog lit landing et écrit bronze, silver et gold.
resource "azurerm_role_assignment" "uc_lit_landing" {
  scope                = local.portee_conteneur["landing"]
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_databricks_access_connector.unity_catalog.identity[0].principal_id
}

resource "azurerm_role_assignment" "uc_ecrit_couches" {
  for_each             = toset(["bronze", "silver", "gold"])
  scope                = local.portee_conteneur[each.value]
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.unity_catalog.identity[0].principal_id
}

# ADF lit les secrets des connexions sources; les ingénieurs gèrent les secrets.
resource "azurerm_role_assignment" "adf_lit_secrets" {
  scope                = azurerm_key_vault.secrets.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_data_factory.ingestion.identity[0].principal_id
}

resource "azurerm_role_assignment" "ingenieurs_gerent_secrets" {
  scope                = azurerm_key_vault.secrets.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.groupe_ingenieurs_donnees_object_id
}

resource "azurerm_role_assignment" "ingenieurs_lisent_gold" {
  scope                = local.portee_conteneur["gold"]
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = var.groupe_ingenieurs_donnees_object_id
}
