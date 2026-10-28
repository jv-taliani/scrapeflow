locals {
  functions = {
    producer = { handler = "scraper.handlers.producer.handler", timeout = 10 }
    worker   = { handler = "scraper.handlers.worker.handler", timeout = local.worker_timeout }
    list_raw = { handler = "scraper.handlers.list_raw.handler", timeout = 10 }
    reparse  = { handler = "scraper.handlers.reparse.handler", timeout = 10 }
    summary  = { handler = "scraper.handlers.summary.handler", timeout = 10 }
  }

  lambda_env = {
    SCRAPER_BUCKET           = aws_s3_bucket.raw.bucket
    SCRAPER_ITEMS_TABLE      = aws_dynamodb_table.items.name
    SCRAPER_SEEN_TABLE       = aws_dynamodb_table.seen.name
    SCRAPER_QUEUE_URL        = aws_sqs_queue.main["urls"].url
    SCRAPER_JS_QUEUE_URL     = aws_sqs_queue.main["urls-js"].url
    MAX_DEPTH                = tostring(var.max_depth)
    MAX_PAGES                = tostring(var.max_pages)
    SCRAPER_THROTTLE_SECONDS = tostring(var.throttle_seconds)
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "${local.prefix}-${replace(each.key, "_", "-")}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  memory_size      = 256
  timeout          = each.value.timeout

  environment {
    variables = local.lambda_env
  }

  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn        = aws_sqs_queue.main["urls"].arn
  function_name           = aws_lambda_function.fn["worker"].arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}
