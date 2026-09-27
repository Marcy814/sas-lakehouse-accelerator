resource "azurerm_storage_account" "lac" {
  #checkov:skip=CKV_AZURE_206:LRS en dev, ZRS en prod (expression sur var.environnement).
  #checkov:skip=CKV_AZURE_43:Nom calculé (st + projet + environnement + lac), 3 à 24 minuscules.
  #checkov:skip=CKV_AZURE_33:Aucune file d'attente (Queue) utilisée.
  #checkov:skip=CKV2_AZURE_1:Clés gérées par Microsoft en dev; clé client (CMK) dans Key Vault selon l'exigence du client en prod.
  name                              = "st${local.nom_compact}lac"
  resource_group_name               = azurerm_resource_group.lakehouse.name
  location                          = azurerm_resource_group.lakehouse.location
  account_tier                      = "Standard"
  account_replication_type          = var.environnement == "prod" ? "ZRS" : "LRS"
  account_kind                      = "StorageV2"
  is_hns_enabled                    = true
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  allow_nested_items_to_be_public   = false
  default_to_oauth_authentication   = true
  infrastructure_encryption_enabled = true
  local_user_enabled                = false

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  blob_properties {
    versioning_enabled = false
    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  tags = local.tags
}

resource "azurerm_storage_container" "couches" {
  #checkov:skip=CKV2_AZURE_21:Journaux StorageRead/Write/Delete envoyés à Log Analytics (azurerm_monitor_diagnostic_setting.lac).
  for_each              = toset(local.couches)
  name                  = each.value
  storage_account_id    = azurerm_storage_account.lac.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "cycle_de_vie" {
  storage_account_id = azurerm_storage_account.lac.id

  rule {
    name    = "landing-vers-froid"
    enabled = true
    filters {
      prefix_match = ["landing/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 30
        delete_after_days_since_modification_greater_than       = 2555
      }
    }
  }
}

resource "azurerm_private_endpoint" "lac_dfs" {
  name                = "pe-${local.nom}-lac-dfs"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  subnet_id           = azurerm_subnet.points_de_terminaison.id

  private_service_connection {
    name                           = "psc-lac-dfs"
    private_connection_resource_id = azurerm_storage_account.lac.id
    subresource_names              = ["dfs"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "dns-dfs"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["privatelink.dfs.core.windows.net"].id]
  }

  tags = local.tags
}

resource "azurerm_monitor_diagnostic_setting" "lac" {
  name                       = "diag-lac"
  target_resource_id         = "${azurerm_storage_account.lac.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.journaux.id

  enabled_log {
    category = "StorageRead"
  }
  enabled_log {
    category = "StorageWrite"
  }
  enabled_log {
    category = "StorageDelete"
  }
}
