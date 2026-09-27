# Rôle d'exécution du pipeline (Glue, EMR ou Databricks sur AWS) : moindre privilège par couche.

data "aws_iam_policy_document" "approbation_glue" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${local.nom}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.approbation_glue.json
}

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "LectureLanding"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.couches["landing"].arn, "${aws_s3_bucket.couches["landing"].arn}/*"]
  }

  statement {
    sid     = "EcritureCouchesMedaillon"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = flatten([
      for c in ["bronze", "silver", "gold"] : [aws_s3_bucket.couches[c].arn, "${aws_s3_bucket.couches[c].arn}/*"]
    ])
  }

  statement {
    sid       = "ChiffrementKMS"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.lac.arn]
  }

  statement {
    sid     = "CatalogueGlue"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable", "glue:GetPartitions", "glue:BatchCreatePartition"]
    resources = concat(
      ["arn:aws:glue:${var.region}:${data.aws_caller_identity.courant.account_id}:catalog"],
      [for db in aws_glue_catalog_database.couches : db.arn],
      [for db in aws_glue_catalog_database.couches : "arn:aws:glue:${var.region}:${data.aws_caller_identity.courant.account_id}:table/${db.name}/*"],
    )
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "${local.nom}-pipeline"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}
