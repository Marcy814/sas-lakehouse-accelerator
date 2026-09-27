output "compartiments" {
  value = { for c, b in aws_s3_bucket.couches : c => b.bucket }
}

output "role_pipeline_arn" {
  value = aws_iam_role.pipeline.arn
}

output "cle_kms_arn" {
  value = aws_kms_key.lac.arn
}
