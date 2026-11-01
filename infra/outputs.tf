output "instance_public_ip" {
  description = "Stable (Elastic) public IP of the app instance"
  value       = aws_eip.app.public_ip
}

output "app_url" {
  description = "URL to reach the dashboard"
  value       = "https://${var.app_domain}"
}

output "ssh_command" {
  description = "Convenience SSH command"
  value       = "ssh -i <your-key.pem> ubuntu@${aws_eip.app.public_ip}"
}

output "ecr_repository_url" {
  description = "Push the app image here before/after apply"
  value       = aws_ecr_repository.app.repository_url
}

output "backup_bucket" {
  description = "S3 bucket holding nightly database backups."
  value       = aws_s3_bucket.backups.bucket
}
