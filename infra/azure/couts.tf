resource "azurerm_monitor_action_group" "finops" {
  name                = "ag-${local.nom}-finops"
  resource_group_name = azurerm_resource_group.lakehouse.name
  short_name          = "finops"

  dynamic "email_receiver" {
    for_each = var.courriels_alertes_budget
    content {
      name          = "courriel-${email_receiver.key}"
      email_address = email_receiver.value
    }
  }

  tags = local.tags
}

resource "azurerm_consumption_budget_resource_group" "lakehouse" {
  name              = "budget-${local.nom}"
  resource_group_id = azurerm_resource_group.lakehouse.id
  amount            = var.budget_mensuel_cad
  time_grain        = "Monthly"

  time_period {
    start_date = var.date_debut_budget
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_groups = [azurerm_monitor_action_group.finops.id]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_groups = [azurerm_monitor_action_group.finops.id]
  }
}
