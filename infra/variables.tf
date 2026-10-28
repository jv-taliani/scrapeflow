variable "environment" {
  type = string
  validation {
    condition     = contains(["local", "aws"], var.environment)
    error_message = "environment deve ser \"local\" ou \"aws\"."
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "bucket_suffix" {
  type    = string
  default = ""
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "budget_limit_usd" {
  type    = string
  default = "1"
}

variable "lambda_zip" {
  type    = string
  default = "../build/lambda.zip"
}

variable "log_retention_days" {
  type    = number
  default = 3
}

variable "raw_expiration_days" {
  type    = number
  default = 30
}

variable "max_depth" {
  type    = number
  default = 3
}

variable "max_pages" {
  type    = number
  default = 50
}

variable "throttle_seconds" {
  type    = number
  default = 1
}

variable "worker_max_concurrency" {
  type    = number
  default = 2
}
