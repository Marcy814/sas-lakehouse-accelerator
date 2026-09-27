resource "azurerm_key_vault" "secrets" {
  name                          = "kv-${local.nom}-lac"
  location                      = azurerm_resource_group.lakehouse.location
  resource_group_name           = azurerm_resource_group.lakehouse.name
  tenant_id                     = data.azurerm_client_config.courant.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = false

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
  }

  tags = local.tags
}

resource "azurerm_private_endpoint" "secrets" {
  name                = "pe-${local.nom}-kv"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  subnet_id           = azurerm_subnet.points_de_terminaison.id

  private_service_connection {
    name                           = "psc-kv"
    private_connection_resource_id = azurerm_key_vault.secrets.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "dns-kv"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["privatelink.vaultcore.azure.net"].id]
  }

  tags = local.tags
}

resource "azurerm_monitor_diagnostic_setting" "secrets" {
  name                       = "diag-kv"
  target_resource_id         = azurerm_key_vault.secrets.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.journaux.id

  enabled_log {
    category = "AuditEvent"
  }
}
