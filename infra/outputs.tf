output "bucket" {
  value = aws_s3_bucket.raw.bucket
}

output "items_table" {
  value = aws_dynamodb_table.items.name
}

output "seen_table" {
  value = aws_dynamodb_table.seen.name
}

output "queue_urls" {
  value = { for k, q in aws_sqs_queue.main : k => q.url }
}

output "dlq_urls" {
  value = { for k, q in aws_sqs_queue.dlq : k => q.url }
}

output "functions" {
  value = { for k, f in aws_lambda_function.fn : k => f.function_name }
}
