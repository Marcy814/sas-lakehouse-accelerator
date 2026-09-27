resource "azurerm_virtual_network" "lakehouse" {
  name                = "vnet-${local.nom}"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  address_space       = [var.plage_reseau]
  tags                = local.tags
}

resource "azurerm_subnet" "databricks_hote" {
  name                 = "snet-databricks-hote"
  resource_group_name  = azurerm_resource_group.lakehouse.name
  virtual_network_name = azurerm_virtual_network.lakehouse.name
  address_prefixes     = [cidrsubnet(var.plage_reseau, 6, 0)]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action",
      ]
    }
  }
}

resource "azurerm_subnet" "databricks_conteneurs" {
  name                 = "snet-databricks-conteneurs"
  resource_group_name  = azurerm_resource_group.lakehouse.name
  virtual_network_name = azurerm_virtual_network.lakehouse.name
  address_prefixes     = [cidrsubnet(var.plage_reseau, 6, 1)]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action",
      ]
    }
  }
}

resource "azurerm_subnet" "points_de_terminaison" {
  name                 = "snet-points-de-terminaison-prives"
  resource_group_name  = azurerm_resource_group.lakehouse.name
  virtual_network_name = azurerm_virtual_network.lakehouse.name
  address_prefixes     = [cidrsubnet(var.plage_reseau, 8, 16)]
}

resource "azurerm_network_security_group" "databricks" {
  name                = "nsg-${local.nom}-databricks"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  tags                = local.tags
}

resource "azurerm_subnet_network_security_group_association" "databricks_hote" {
  subnet_id                 = azurerm_subnet.databricks_hote.id
  network_security_group_id = azurerm_network_security_group.databricks.id
}

resource "azurerm_subnet_network_security_group_association" "databricks_conteneurs" {
  subnet_id                 = azurerm_subnet.databricks_conteneurs.id
  network_security_group_id = azurerm_network_security_group.databricks.id
}

resource "azurerm_network_security_group" "points_de_terminaison" {
  name                = "nsg-${local.nom}-points-de-terminaison"
  location            = azurerm_resource_group.lakehouse.location
  resource_group_name = azurerm_resource_group.lakehouse.name
  tags                = local.tags
}

resource "azurerm_subnet_network_security_group_association" "points_de_terminaison" {
  subnet_id                 = azurerm_subnet.points_de_terminaison.id
  network_security_group_id = azurerm_network_security_group.points_de_terminaison.id
}

resource "azurerm_private_dns_zone" "zones" {
  for_each            = toset(["privatelink.dfs.core.windows.net", "privatelink.vaultcore.azure.net"])
  name                = each.value
  resource_group_name = azurerm_resource_group.lakehouse.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "liens" {
  for_each              = azurerm_private_dns_zone.zones
  name                  = "lien-${replace(each.key, ".", "-")}"
  resource_group_name   = azurerm_resource_group.lakehouse.name
  private_dns_zone_name = each.value.name
  virtual_network_id    = azurerm_virtual_network.lakehouse.id
  registration_enabled  = false
  tags                  = local.tags
}
