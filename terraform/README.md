# Importar los recursos existentes al state de Terraform
terraform import azapi_update_resource.function_app_settings "/subscriptions/32f3c387-f40e-43fe-8888-001be33af10d/resourceGroups/rg_zabbix_exporter/providers/Microsoft.Web/sites/func-zabbix-exporter/config/appsettings"


# Ahora aplicar para configurar los valores
terraform apply
