locals {
  worker_timeout     = 30
  visibility_timeout = 6 * local.worker_timeout
  queues             = toset(["urls", "urls-js"])
}

resource "aws_sqs_queue" "dlq" {
  for_each                  = local.queues
  name                      = "${local.prefix}-${each.key}-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "main" {
  for_each                   = local.queues
  name                       = "${local.prefix}-${each.key}"
  visibility_timeout_seconds = local.visibility_timeout
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 3
  })
}
