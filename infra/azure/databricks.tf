resource "azurerm_databricks_workspace" "lakehouse" {
  #checkov:skip=CKV_AZURE_158:Connectivité sécurisée des clusters (aucune IP publique, VNet injection); Private Link complet prévu en prod.
  #checkov:skip=CKV2_AZURE_48:Clé client (CMK) pour DBFS selon l'exigence du client en prod.
  name                                  = "dbw-${local.nom}"
  resource_group_name                   = azurerm_resource_group.lakehouse.name
  location                              = azurerm_resource_group.lakehouse.location
  sku                                   = "premium"
  managed_resource_group_name           = "rg-${local.nom}-databricks-gere"
  public_network_access_enabled         = true
  network_security_group_rules_required = "AllRules"
  infrastructure_encryption_enabled     = true

  custom_parameters {
    no_public_ip                                         = true
    virtual_network_id                                   = azurerm_virtual_network.lakehouse.id
    public_subnet_name                                   = azurerm_subnet.databricks_hote.name
    private_subnet_name                                  = azurerm_subnet.databricks_conteneurs.name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.databricks_hote.id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.databricks_conteneurs.id
  }

  tags = local.tags
}

resource "azurerm_databricks_access_connector" "unity_catalog" {
  name                = "dbac-${local.nom}-uc"
  resource_group_name = azurerm_resource_group.lakehouse.name
  location            = azurerm_resource_group.lakehouse.location

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_data_factory" "ingestion" {
  #checkov:skip=CKV_AZURE_103:Intégration Git configurée sur l'usine de dev seulement; qa et prod reçoivent les pipelines par CI/CD.
  #checkov:skip=CKV2_AZURE_15:Clé client (CMK) selon l'exigence du client en prod.
  name                            = "adf-${local.nom}"
  location                        = azurerm_resource_group.lakehouse.location
  resource_group_name             = azurerm_resource_group.lakehouse.name
  managed_virtual_network_enabled = true
  public_network_enabled          = false

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}
