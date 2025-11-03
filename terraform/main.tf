terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azapi" {}

# Variables
variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
  default     = "32f3c387-f40e-43fe-8888-001be33af10d"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "westeurope"
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
  default     = "rg_zabbix_exporter"
}

variable "storage_account_name" {
  description = "Storage account name (must be globally unique)"
  type        = string
  default     = "stzabbixexporter"
}

variable "function_app_name" {
  description = "Function app name"
  type        = string
  default     = "func-zabbix-exporter"
}

variable "zabbix_url" {
  description = "Zabbix API URL"
  type        = string
  sensitive   = true
}

variable "zabbix_user" {
  description = "Zabbix username"
  type        = string
  sensitive   = true
}

variable "zabbix_password" {
  description = "Zabbix password"
  type        = string
  sensitive   = true
}

variable "teams_webhook_url" {
  description = "Microsoft Teams webhook URL"
  type        = string
  sensitive   = true
}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
}

# Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = "vnet-zabbix-exporter"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = ["10.0.0.0/16"]
}

# Subnet Default
resource "azurerm_subnet" "default" {
  name                 = "default"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.0.0/24"]
}

# Subnet Functions
resource "azurerm_subnet" "functions" {
  name                 = "functions"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]
  service_endpoints    = ["Microsoft.Storage"]

  delegation {
    name = "delegation"
    service_delegation {
      name = "Microsoft.App/environments"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action"
      ]
    }
  }
}

# Storage Account
resource "azurerm_storage_account" "main" {
  name                            = var.storage_account_name
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true
  large_file_share_enabled        = true

  blob_properties {
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  share_properties {
    retention_policy {
      days = 7
    }
  }

  network_rules {
    default_action             = "Allow"
    virtual_network_subnet_ids = [azurerm_subnet.functions.id]
  }
}

# Storage Containers
resource "azurerm_storage_container" "webjobs_hosts" {
  name                  = "azure-webjobs-hosts"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "webjobs_secrets" {
  name                  = "azure-webjobs-secrets"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "metrics" {
  name                  = "metrics"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

# User Assigned Managed Identity
resource "azurerm_user_assigned_identity" "main" {
  name                = "${var.function_app_name}-uami"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

# Role Assignment - Storage Blob Data Owner
resource "azurerm_role_assignment" "storage_blob_owner" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_user_assigned_identity.main.principal_id
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = var.function_app_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
}

# Service Plan (Flex Consumption)
resource "azurerm_service_plan" "main" {
  name                = "asp-${var.function_app_name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = "FC1"
}

# Function App (Flex Consumption) usando AzAPI
resource "azapi_resource" "function_app" {
  type      = "Microsoft.Web/sites@2023-12-01"
  name      = var.function_app_name
  location  = azurerm_resource_group.main.location
  parent_id = azurerm_resource_group.main.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.main.id]
  }

  body = {
    kind = "functionapp,linux"
    properties = {
      serverFarmId = azurerm_service_plan.main.id
      httpsOnly    = true
      
      functionAppConfig = {
        deployment = {
          storage = {
            type  = "blobContainer"
            value = "${azurerm_storage_account.main.primary_blob_endpoint}${azurerm_storage_container.webjobs_hosts.name}"
            authentication = {
              type               = "StorageAccountConnectionString"
              storageAccountConnectionStringName = "AzureWebJobsStorage"
            }
          }
        }
        scaleAndConcurrency = {
          maximumInstanceCount = 100
          instanceMemoryMB     = 2048
        }
        runtime = {
          name    = "python"
          version = "3.12"
        }
      }

      siteConfig = {
        vnetRouteAllEnabled = true
        cors = {
          allowedOrigins = ["https://portal.azure.com"]
          supportCredentials = false
        }
      }

      virtualNetworkSubnetId = azurerm_subnet.functions.id

      publicNetworkAccess = "Enabled"
    }
  }

  response_export_values = ["properties.defaultHostName", "properties.outboundIpAddresses"]

  depends_on = [
    azurerm_role_assignment.storage_blob_owner,
    azurerm_storage_container.webjobs_hosts,
    azurerm_storage_container.webjobs_secrets
  ]
}

# App Settings - IMPORTANTE: Cambiar de azapi_resource a azapi_update_resource
resource "azapi_update_resource" "function_app_settings" {
  type        = "Microsoft.Web/sites@2023-12-01"
  resource_id = azapi_resource.function_app.id

  body = {
    properties = {
      siteConfig = {
        appSettings = [
          {
            name  = "AzureWebJobsStorage"
            value = azurerm_storage_account.main.primary_connection_string
          },
          {
            name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
            value = azurerm_application_insights.main.connection_string
          },
          {
            name  = "CONTAINER_NAME"
            value = "metrics"
          },
          {
            name  = "TEAMS_WEBHOOK_URL"
            value = var.teams_webhook_url
          },
          {
            name  = "AZURE_STORAGE_CONNECTION_STRING"
            value = azurerm_storage_account.main.primary_connection_string
          },
          {
            name  = "ZABBIX_URL"
            value = var.zabbix_url
          },
          {
            name  = "ZABBIX_USER"
            value = var.zabbix_user
          },
          {
            name  = "ZABBIX_PASSWORD"
            value = var.zabbix_password
          },
          {
            name  = "SAS_EXPIRY_HOURS"
            value = "72"
          },
          {
            name  = "ONLY_LATEST_FILE"
            value = "true"
          },
          {
            name  = "FUNCTIONS_EXTENSION_VERSION"
            value = "~4"
          }
          # NOTA: FUNCTIONS_WORKER_RUNTIME NO se incluye porque ya está definido
          # en functionAppConfig.runtime del recurso azapi_resource.function_app
        ]
      }
    }
  }

  depends_on = [
    azapi_resource.function_app
  ]
}

# Deshabilitar credenciales básicas FTP
resource "azapi_update_resource" "ftp_policy" {
  type      = "Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01"
  name      = "ftp"
  parent_id = azapi_resource.function_app.id

  body = {
    properties = {
      allow = false
    }
  }
}

# Deshabilitar credenciales básicas SCM
resource "azapi_update_resource" "scm_policy" {
  type      = "Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01"
  name      = "scm"
  parent_id = azapi_resource.function_app.id

  body = {
    properties = {
      allow = false
    }
  }
}

# Outputs
output "function_app_name" {
  value = var.function_app_name
}

output "function_app_default_hostname" {
  value = azapi_resource.function_app.output.properties.defaultHostName
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "resource_group_name" {
  value = azurerm_resource_group.main.name
}
