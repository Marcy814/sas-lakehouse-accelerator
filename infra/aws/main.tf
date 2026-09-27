locals {
  nom     = "${var.projet}-${var.environnement}"
  couches = ["landing", "bronze", "silver", "gold"]
}

data "aws_caller_identity" "courant" {}

resource "aws_kms_key" "lac" {
  #checkov:skip=CKV_AWS_111:Politique de clé par défaut AWS (délégation à IAM du compte); l'accès réel est donné par les politiques IAM.
  #checkov:skip=CKV_AWS_109:Idem : la racine du compte délègue à IAM, pratique recommandée par AWS.
  #checkov:skip=CKV_AWS_356:Dans une politique de clé KMS, la ressource « * » désigne la clé elle-même.
  description             = "Chiffrement du lakehouse ${local.nom}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.cle_kms.json
}

data "aws_iam_policy_document" "cle_kms" {
  #checkov:skip=CKV_AWS_111:Politique de clé KMS par défaut (délégation à IAM).
  #checkov:skip=CKV_AWS_109:Politique de clé KMS par défaut (délégation à IAM).
  #checkov:skip=CKV_AWS_356:Dans une politique de clé KMS, « * » désigne la clé elle-même.
  statement {
    sid       = "AdministrationParLeCompte"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.courant.account_id}:root"]
    }
  }
}

resource "aws_kms_alias" "lac" {
  name          = "alias/${local.nom}-lac"
  target_key_id = aws_kms_key.lac.key_id
}

resource "aws_s3_bucket" "journaux" {
  #checkov:skip=CKV_AWS_18:Compartiment cible des journaux d'accès; il ne se journalise pas lui-même.
  #checkov:skip=CKV_AWS_145:La livraison des journaux d'accès S3 exige SSE-S3 (SSE-KMS non pris en charge).
  #checkov:skip=CKV_AWS_144:Résidence des données : réplication inter-régions (ca-west-1) à décider en production.
  #checkov:skip=CKV_AWS_21:Journaux immuables par nature; le versionnement n'apporte rien ici.
  #checkov:skip=CKV2_AWS_62:Aucun traitement déclenché par les journaux d'accès.
  bucket = "${local.nom}-journaux-acces-${data.aws_caller_identity.courant.account_id}"
}

resource "aws_s3_bucket_lifecycle_configuration" "journaux" {
  bucket = aws_s3_bucket.journaux.id

  rule {
    id     = "expiration-journaux"
    status = "Enabled"
    filter {}
    expiration {
      days = 365
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "journaux" {
  bucket                  = aws_s3_bucket.journaux.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "journaux" {
  bucket = aws_s3_bucket.journaux.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "couches" {
  #checkov:skip=CKV_AWS_18:Journalisation configurée par aws_s3_bucket_logging.couches (for_each non résolu par checkov).
  #checkov:skip=CKV_AWS_21:Versionnement configuré par aws_s3_bucket_versioning.couches.
  #checkov:skip=CKV_AWS_145:Chiffrement KMS configuré par aws_s3_bucket_server_side_encryption_configuration.couches.
  #checkov:skip=CKV2_AWS_6:Blocage public configuré par aws_s3_bucket_public_access_block.couches.
  #checkov:skip=CKV2_AWS_61:Cycle de vie configuré par aws_s3_bucket_lifecycle_configuration.couches.
  #checkov:skip=CKV2_AWS_62:Notifications configurées sur landing (EventBridge); les autres couches sont écrites par le pipeline.
  #checkov:skip=CKV_AWS_144:Résidence des données : réplication inter-régions (ca-west-1) à décider en production.
  for_each = toset(local.couches)
  bucket   = "${local.nom}-${each.value}-${data.aws_caller_identity.courant.account_id}"
}

resource "aws_s3_bucket_public_access_block" "couches" {
  for_each                = aws_s3_bucket.couches
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "couches" {
  for_each = aws_s3_bucket.couches
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "couches" {
  for_each = aws_s3_bucket.couches
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.lac.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_logging" "couches" {
  for_each      = aws_s3_bucket.couches
  bucket        = each.value.id
  target_bucket = aws_s3_bucket.journaux.id
  target_prefix = "${each.key}/"
}

resource "aws_s3_bucket_policy" "tls_obligatoire" {
  for_each = aws_s3_bucket.couches
  bucket   = each.value.id
  policy   = data.aws_iam_policy_document.tls_obligatoire[each.key].json
}

data "aws_iam_policy_document" "tls_obligatoire" {
  for_each = aws_s3_bucket.couches
  statement {
    sid       = "RefuserSansTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "couches" {
  for_each = aws_s3_bucket.couches
  bucket   = each.value.id

  rule {
    id     = "versions-anterieures"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = each.key == "landing" ? [1] : []
    content {
      id     = "landing-vers-glacier"
      status = "Enabled"
      filter {
        prefix = "extraits/"
      }
      transition {
        days          = 30
        storage_class = "STANDARD_IA"
      }
      transition {
        days          = 180
        storage_class = "GLACIER"
      }
      expiration {
        days = 2555
      }
    }
  }
}

# Chaque fichier déposé dans landing publie un événement EventBridge (déclenchement de l'ingestion,
# équivalent du mode « file notification » d'Auto Loader).
resource "aws_s3_bucket_notification" "landing" {
  bucket      = aws_s3_bucket.couches["landing"].id
  eventbridge = true
}

resource "aws_glue_catalog_database" "couches" {
  for_each     = toset(["bronze", "silver", "gold"])
  name         = "${replace(local.nom, "-", "_")}_${each.value}"
  location_uri = "s3://${aws_s3_bucket.couches[each.value].bucket}/"
}
