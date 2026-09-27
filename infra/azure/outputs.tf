output "compte_stockage" {
  description = "Compte ADLS Gen2 du lakehouse."
  value       = azurerm_storage_account.lac.name
}

output "chemins_abfss" {
  description = "Chemins abfss:// de chaque couche, à déclarer comme external locations Unity Catalog."
  value       = { for c in local.couches : c => "abfss://${c}@${azurerm_storage_account.lac.name}.dfs.core.windows.net/" }
}

output "espace_databricks_url" {
  value = azurerm_databricks_workspace.lakehouse.workspace_url
}

output "connecteur_unity_catalog_id" {
  description = "À déclarer comme storage credential dans Unity Catalog."
  value       = azurerm_databricks_access_connector.unity_catalog.id
}

output "key_vault_uri" {
  value = azurerm_key_vault.secrets.vault_uri
}
