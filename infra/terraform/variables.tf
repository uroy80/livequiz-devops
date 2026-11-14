variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "project" {
  type    = string
  default = "livequiz"
}
variable "instance_type" {
  description = "Graviton (arm64) instance - matches the arm64 image built by Jenkins"
  type        = string
  default     = "t4g.small"
}
variable "admin_cidr" {
  description = "Only this address may SSH to the server (the Jenkins host's public IP /32)"
  type        = string
}
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
