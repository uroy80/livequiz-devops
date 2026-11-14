output "public_ip" { value = aws_eip.app.public_ip }
output "app_url" { value = "http://${aws_eip.app.public_ip}" }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "instance_id" { value = aws_instance.app.id }
output "db_password" {
  value     = random_password.db.result
  sensitive = true
}
output "admin_password" {
  value     = random_password.admin.result
  sensitive = true
}
output "secret_key" {
  value     = random_password.secret_key.result
  sensitive = true
}
