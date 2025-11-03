# Guía de Despliegue - Zabbix Exporter Function
## Requisitos previos
```bash
# Instalar Terraform
https://developer.hashicorp.com/terraform/downloads

# Instalar Azure CLI
https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

# Login en Azure
az login
```
## Estructura de archivos
terraform/
├── main.tf              # Configuración principal
├── terraform.tfvars     # Variables (NO SUBIR A GIT)
├── .gitignore          # Ignorar archivos sensibles
└── README.md

## Archivo .gitignore
```bash
# Terraform
*.tfstate
*.tfstate.*
*.tfvars
.terraform/
.terraform.lock.hcl
crash.log
override.tf
override.tf.json
*_override.tf
*_override.tf.json
```
## Pasos de despliegue
1. Inicializar Terraform
```bash
cd terraform/
terraform init
```
2. Crear archivo terraform.tfvars
```bash
cp terraform.tfvars.example terraform.tfvars
# Editar con tus valores reales
nano terraform.tfvars
```
3. Validar configuración
```bash
terraform validate
terraform plan
```
4. Desplegar
```bash
terraform apply
```
5. Ver outputs
```bash
terraform output
terraform output -json
```
