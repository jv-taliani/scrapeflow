terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project     = "scrapeflow"
      environment = var.environment
    }
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  prefix        = "scraper"
  bucket_suffix = var.bucket_suffix != "" ? var.bucket_suffix : random_id.suffix.hex
  bucket_name   = "${local.prefix}-raw-${local.bucket_suffix}"
}
