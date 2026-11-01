variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

variable "project" {
  description = "Name prefix for resources"
  type        = string
  default     = "familydashboard"
}

variable "instance_type" {
  description = "EC2 instance type (tiny is fine for a family app)"
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH (lock this to your own IP, e.g. 1.2.3.4/32)"
  type        = string
}



# Application secrets — provided at apply time (e.g. via a tfvars file that is
# NOT committed, or -var flags). Stored in Secrets Manager, not on the instance.
variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "google_calendar_api_key" {
  type      = string
  sensitive = true
}

variable "google_calendar_id" {
  type      = string
  sensitive = true
}

variable "todoist_api_token" {
  type      = string
  sensitive = true
}

variable "db_password" {
  description = "Password for the Postgres container"
  type        = string
  sensitive   = true
  default     = "change-me-in-tfvars"
}

variable "app_domain" {
  description = "Domain name for the app (e.g. yourfamily.example.com). Caddy provisions a Let's Encrypt cert for this."
  type        = string
}

variable "backup_retention_days" {
  description = "How many days to keep nightly DB backups in S3 before auto-expiry."
  type        = number
  default     = 30
}
