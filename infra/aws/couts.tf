resource "aws_budgets_budget" "lakehouse" {
  name         = "budget-${local.nom}"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_mensuel_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:projet$%s", var.projet)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.courriels_alertes_budget
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.courriels_alertes_budget
  }
}
