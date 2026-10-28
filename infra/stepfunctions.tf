data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "reprocess" {
  name               = "${local.prefix}-reprocess-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "reprocess" {
  statement {
    actions = ["lambda:InvokeFunction"]
    resources = [
      for name in ["list_raw", "reparse", "summary"] : aws_lambda_function.fn[name].arn
    ]
  }
}

resource "aws_iam_role_policy" "reprocess" {
  name   = "${local.prefix}-reprocess-sfn"
  role   = aws_iam_role.reprocess.id
  policy = data.aws_iam_policy_document.reprocess.json
}

resource "aws_sfn_state_machine" "reprocess" {
  name     = "${local.prefix}-reprocess"
  role_arn = aws_iam_role.reprocess.arn
  definition = templatefile("${path.module}/stepfunctions/reprocess.asl.json", {
    list_raw_arn = aws_lambda_function.fn["list_raw"].arn
    reparse_arn  = aws_lambda_function.fn["reparse"].arn
    summary_arn  = aws_lambda_function.fn["summary"].arn
  })
}
