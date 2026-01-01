# Deployment Guide: Zabbix Metrics Azure Exporter

This guide provides three alternative methods to deploy the infrastructure required for the Zabbix Metrics Azure Exporter.

## 1. Automated Deployment with Terraform

This is the recommended method for consistency and speed.

### Version Information
*   **Terraform Required Version:** `>= 1.0`
*   **AzureRM Provider:** `~> 4.0`
*   **AzAPI Provider:** `~> 2.0`

### Steps
1.  Navigate to the `terraform/` directory.
2.  Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in your Zabbix and Teams credentials.
3.  Execute the following commands:
    ```bash
    terraform init
    terraform plan
    terraform apply
    ```

---

## 2. Manual Deployment via Azure CLI (CLI/ARM Alternative)

If you prefer using the command line without Terraform, follow these steps using the Azure CLI.

### 2.1. Resource Group & Networking
```bash
# Create Resource Group
az group create \
  --name "rg_zabbix_exporter" \
  --location "westeurope"

# Create VNet
az network vnet create \
  --name vnet-zabbix-exporter \
  --resource-group rg_zabbix_exporter \
  --location westeurope \
  --address-prefix 10.0.0.0/16

# Create 'default' subnet
az network vnet subnet create \
  --name default \
  --resource-group rg_zabbix_exporter \
  --vnet-name vnet-zabbix-exporter \
  --address-prefix 10.0.0.0/24

# Create 'functions' subnet with delegation and service endpoint
az network vnet subnet create \
  --name functions \
  --resource-group rg_zabbix_exporter \
  --vnet-name vnet-zabbix-exporter \
  --address-prefix 10.0.1.0/24 \
  --service-endpoints Microsoft.Storage \
  --delegations Microsoft.App/environments
```

### 2.2. Azure Storage Account
```bash
# Declare Constants
RESOURCE_GROUP="rg_zabbix_exporter"
STORAGE_ACCOUNT="stzabbixexporter"
LOCATION="westeurope"
VNET_NAME="vnet-zabbix-exporter"
SUBNET_NAME="functions"

# Create Storage Account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2 \
  --access-tier Hot \
  --https-only true \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --allow-shared-key-access true \
  --enable-large-file-share

# Enable Retention Policies for Blob
az storage account blob-service-properties update \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --enable-delete-retention true \
  --delete-retention-days 7 \
  --enable-container-delete-retention true \
  --container-delete-retention-days 7

# Enable Retention Policy for File Share
az storage account file-service-properties update \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --enable-delete-retention true \
  --delete-retention-days 7

# Configure Network Rules (Firewall)
az storage account update \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --default-action Allow

# Add VNet Subnet
az storage account network-rule add \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --subnet $SUBNET_NAME

# Obtain Account Key
ACCOUNT_KEY=$(az storage account keys list \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query '[0].value' -o tsv)

# Create Blob Containers
az storage container create --name azure-webjobs-hosts --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
az storage container create --name azure-webjobs-secrets --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
az storage container create --name metrics --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
```

### 2.3. Azure Key Vault
```bash
# Declare Constants
KEY_VAULT_NAME="kv-zabbix-exporter"
TENANT_ID=$(az account show --query tenantId -o tsv)
CURRENT_USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)

# Create Key Vault
az keyvault create \
  --name $KEY_VAULT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku standard \
  --retention-days 7 \
  --enable-purge-protection false \
  --default-action Allow \
  --bypass AzureServices

# Add subnet to Key Vault network rules
az keyvault network-rule add \
  --name $KEY_VAULT_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --subnet $SUBNET_NAME

# Access policy for current user
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $CURRENT_USER_OBJECT_ID \
  --secret-permissions get list set delete purge recover

# Access policy for Managed Identity (Defined in later steps)
# az keyvault set-policy --name $KEY_VAULT_NAME --object-id $IDENTITY_PRINCIPAL_ID --secret-permissions get list
```

### 2.4. Azure Function & Identity Setup
```bash
# Declare Constants
FUNCTION_APP_NAME="func-zabbix-exporter"
MANAGED_IDENTITY_NAME="func-zabbix-exporter-uami"

# Create Managed Identity (User Assigned)
az identity create \
  --name $MANAGED_IDENTITY_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Obtain Identity IDs
IDENTITY_ID=$(az identity show --name $MANAGED_IDENTITY_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)
IDENTITY_PRINCIPAL_ID=$(az identity show --name $MANAGED_IDENTITY_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv)

# Apply Key Vault policy for the Managed Identity
az keyvault set-policy --name $KEY_VAULT_NAME --object-id $IDENTITY_PRINCIPAL_ID --secret-permissions get list

# Assign permissions to Managed Identity over Storage Account
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"

# Create Application Insights (optional)
APP_INSIGHTS_NAME="func-zabbix-exporter"
az monitor app-insights component create \
  --app $APP_INSIGHTS_NAME \
  --location $LOCATION \
  --resource-group $RESOURCE_GROUP \
  --application-type web

# Obtain App Insights Connection String
APP_INSIGHTS_KEY=$(az monitor app-insights component show \
  --app $APP_INSIGHTS_NAME \
  --resource-group $RESOURCE_GROUP \
  --query connectionString -o tsv)

# Obtain Subnet ID
SUBNET_ID=$(az network vnet subnet show \
  --resource-group $RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --name $SUBNET_NAME \
  --query id -o tsv)

# Create Function App (Flex Consumption)
az functionapp create \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --storage-account $STORAGE_ACCOUNT \
  --assign-identity $IDENTITY_ID \
  --https-only true \
  --os-type linux \
  --flexconsumption-location $LOCATION

# Configure instance memory size
az functionapp update \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set functionAppConfig.scaleAndConcurrency.instanceMemoryMB=2048

# Configure Application Insights
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_KEY"

# Integrate with VNet
az functionapp vnet-integration add \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet $VNET_NAME \
  --subnet $SUBNET_NAME

# Enable VNet route all
az functionapp config set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet-route-all-enabled true

# Disable basic publishing credentials (FTP and SCM)
az functionapp deployment user set --user-name "" --password "" 2>/dev/null || true
az resource update --resource-group $RESOURCE_GROUP --name ftp --resource-type basicPublishingCredentialsPolicies --namespace Microsoft.Web --parent sites/$FUNCTION_APP_NAME --set properties.allow=false
az resource update --resource-group $RESOURCE_GROUP --name scm --resource-type basicPublishingCredentialsPolicies --namespace Microsoft.Web --parent sites/$FUNCTION_APP_NAME --set properties.allow=false

# Configure CORS (allow Azure Portal)
az functionapp cors add \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --allowed-origins "https://portal.azure.com"
```

### 2.5. Key Vault Secrets & Function Settings
```bash
# Set Secrets in Key Vault
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "ZABBIX-URL" --value "https://your-zabbix/api_jsonrpc.php"
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "ZABBIX-USER" --value "your-user"
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "ZABBIX-PASSWORD" --value "your-password"
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "TEAMS-WEBHOOK-URL" --value "your-webhook-url"

# Obtain Connection String
STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query connectionString -o tsv)

az keyvault secret set --vault-name $KEY_VAULT_NAME --name "AZURE-STORAGE-CONNECTION-STRING" --value "$STORAGE_CONNECTION_STRING"

# Get URIs for Key Vault References
ZABBIX_URL_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "ZABBIX-URL" --query id -o tsv)
ZABBIX_USER_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "ZABBIX-USER" --query id -o tsv)
ZABBIX_PASSWORD_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "ZABBIX-PASSWORD" --query id -o tsv)
TEAMS_WEBHOOK_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "TEAMS-WEBHOOK-URL" --query id -o tsv)
STORAGE_CONN_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "AZURE-STORAGE-CONNECTION-STRING" --query id -o tsv)

# Configure Key Vault Reference Identity
az functionapp config set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --generic-configurations "{\"keyVaultReferenceIdentity\":\"$IDENTITY_ID\"}"

# Add Environment Variables to Function App with Key Vault References
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
  CONTAINER_NAME="metrics" \
  TEAMS_WEBHOOK_URL="@Microsoft.KeyVault(SecretUri=$TEAMS_WEBHOOK_URI)" \
  AZURE_STORAGE_CONNECTION_STRING="@Microsoft.KeyVault(SecretUri=$STORAGE_CONN_URI)" \
  ZABBIX_URL="@Microsoft.KeyVault(SecretUri=$ZABBIX_URL_URI)" \
  ZABBIX_USER="@Microsoft.KeyVault(SecretUri=$ZABBIX_USER_URI)" \
  ZABBIX_PASSWORD="@Microsoft.KeyVault(SecretUri=$ZABBIX_PASSWORD_URI)" \
  SAS_EXPIRY_HOURS="168" \
  ONLY_LATEST_FILE="true"
```

---

## 3. Manual Deployment via Azure Portal

For users who prefer a graphical interface.

### 3.1. Resource Group & Networking
1.  **Create Resource Group**:
    *   Search for **Resource Groups** -> **Create**.
    *   Project Details: `rg_zabbix_exporter`. Region: `West Europe`.
2.  **Create Virtual Network**:
    *   Search for **Virtual Networks** -> **Create**.
    *   Name: `vnet-zabbix-exporter`.
    *   Address Space: `10.0.0.0/16`.
    *   **Subnets**:
        *   `default`: `10.0.0.0/24`.
        *   `functions`: `10.0.1.0/24`. Select **Subnet delegation**: `Microsoft.App/environments`. Enable **Service Endpoints**: `Microsoft.Storage` and `Microsoft.KeyVault`.

### 3.2. Azure Storage Account
1.  **Create Storage Account**:
    *   Search for **Storage accounts** -> **Create**.
    *   Name: `stzabbixexporter`. Performance: `Standard`. Redundancy: `LRS`.
    *   **Advanced**: Ensure "Allow Shared Key access" is enabled.
2.  **Data Protection**:
    *   Enable **Soft delete for blobs** (7 days).
    *   Enable **Soft delete for containers** (7 days).
    *   Enable **Soft delete for file shares** (7 days).
3.  **Networking**:
    *   Connectivity method: "Public endpoint (selected networks)".
    *   Add existing virtual network -> `vnet-zabbix-exporter` -> `functions` subnet.
4.  **Create Containers**:
    *   Navigate to **Containers** under Data Storage.
    *   Create: `azure-webjobs-hosts`, `azure-webjobs-secrets`, and `metrics`. All with "Private" access level.

### 3.3. Identity & Role Assignment
1.  **Create User Assigned Managed Identity**:
    *   Search for **Managed Identities** -> **Create**.
    *   Name: `func-zabbix-exporter-uami`.
2.  **Role Assignment**:
    *   Go to your **Storage Account** -> **Access Control (IAM)** -> **Add role assignment**.
    *   Role: `Storage Blob Data Owner`.
    *   Assign access to: `Managed identity`. Select your identity: `func-zabbix-exporter-uami`.

### 3.4. Azure Key Vault
1.  **Create Key Vault**:
    *   Search for **Key vaults** -> **Create**.
    *   Name: `kv-zabbix-exporter`. Pricing tier: `Standard`.
2.  **Access Configuration**:
    *   Permission model: `Vault access policy`.
    *   Add access policy for **yourself**: Full Secret management.
    *   Add access policy for **Identity**: Select `func-zabbix-exporter-uami`. Secret permissions: `Get`, `List`.
3.  **Networking**:
    *   Connectivity method: "Public endpoint (selected networks)".
    *   Add existing virtual network -> `vnet-zabbix-exporter` -> `functions` subnet.
4.  **Secrets**:
    *   Navigate to **Secrets** -> **Generate/Import**.
    *   Create: `ZABBIX-URL`, `ZABBIX-USER`, `ZABBIX-PASSWORD`, `TEAMS-WEBHOOK-URL`, and `AZURE-STORAGE-CONNECTION-STRING`.

### 3.5. Application Insights & Function App
1.  **Create Application Insights**:
    *   Search for **Application Insights** -> **Create**.
    *   Name: `func-zabbix-exporter`. Application Type: `Web`.
2.  **Create Function App**:
    *   Search for **Function App** -> **Create**.
    *   Hosting: `Flex Consumption`.
    *   Runtime stack: `Python 3.12`. OS: `Linux`. Region: `West Europe`.
    *   **Networking**: Enable **VNet integration** and select the `functions` subnet.
3.  **Configure Function App**:
    *   **Identity**: Settings -> Identity -> User assigned. Add `func-zabbix-exporter-uami`.
    *   **Environment variables**: Settings -> Environment variables -> App settings.
        *   Set `CONTAINER_NAME` = `metrics`.
        *   Set Key Vault references for Zabbix and Storage using the format `@Microsoft.KeyVault(SecretUri=...)`.
    *   **CORS**: Settings -> CORS. Add `https://portal.azure.com`.
    *   **Deployment**: Under Configuration -> Authentication, disable "Basic Authentication" for FTP and SCM if possible (or via Resource Explorer).

---

## 4. Power Automate Workflow

To receive the notifications in Teams:
1.  In Teams, go to **Workflows** -> **Create from blank**.
2.  Trigger: **"When a Teams webhook request is received"**.
3.  Copy the generated URL and save it as `TEAMS_WEBHOOK_URL` in your Azure Function settings (or Key Vault).
4.  Action: **"Post a message in a chat or channel"**.
5.  Message content: Use the dynamic expression `@{triggerBody()?['mensaje_completo']}`.