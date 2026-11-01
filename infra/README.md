# Infrastructure (Terraform)

Provisions a single small EC2 instance that runs the whole app via
docker-compose (Flask app container + Postgres container).

## What it creates
- A VPC with one public subnet (or uses the default VPC — see `variables.tf`)
- A security group allowing SSH (your IP) and HTTP on the app port
- An EC2 instance (default `t3.micro`) with Docker + docker-compose installed
- An IAM role letting the instance read the app secret from Secrets Manager
- A Secrets Manager secret holding the API keys + DB password

## Prerequisites
- Terraform >= 1.6
- AWS credentials configured (the `AWS_*` keys in `git.env`, or `aws configure`)
- An EC2 key pair for SSH (set `key_name`)

## Usage
```bash
cd infra
terraform init
terraform plan -out tfplan      # review carefully — this creates billable resources
terraform apply tfplan
```

The app image is built on the instance from the cloned repo (simplest for a
single box). `terraform output app_url` prints the URL once it's up.

## Cost
Roughly a single t3.micro (~£7–9/month on-demand, less with a savings plan or
if free-tier eligible) plus a small EBS volume. Destroy with `terraform destroy`
when not needed.
