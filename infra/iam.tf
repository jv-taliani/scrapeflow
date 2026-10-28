data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

locals {
  queue_arns = [for q in aws_sqs_queue.main : q.arn]

  lambda_statements = {
    producer = [
      { actions = ["sqs:SendMessage"], resources = local.queue_arns },
      { actions = ["dynamodb:PutItem"], resources = [aws_dynamodb_table.seen.arn] },
    ]
    worker = [
      {
        actions = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        resources = [aws_sqs_queue.main["urls"].arn]
      },
      { actions = ["sqs:SendMessage"], resources = local.queue_arns },
      { actions = ["s3:PutObject"], resources = ["${aws_s3_bucket.raw.arn}/raw/*"] },
      { actions = ["dynamodb:PutItem"], resources = [aws_dynamodb_table.items.arn] },
      {
        actions   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        resources = [aws_dynamodb_table.seen.arn]
      },
    ]
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = local.functions
  name               = "${local.prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  for_each = local.functions

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = lookup(local.lambda_statements, each.key, [])
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  name     = "${local.prefix}-${each.key}"
  role     = aws_iam_role.lambda[each.key].id
  policy   = data.aws_iam_policy_document.lambda[each.key].json
}
