# Deployment Guide: Multi-Client Zabbix Metrics Azure Exporter

This guide provides three alternative methods to deploy the infrastructure required for the multi-client Zabbix Metrics Azure Exporter.

## 1. Automated Deployment with Terraform (Recommended)

This is the fastest and most reliable method to deploy the entire multi-client infrastructure.

### Version Information
*   **Terraform Required Version:** `>= 1.0`
*   **AzureRM Provider:** `~> 4.0`
*   **AzAPI Provider:** `~> 2.0`

### Steps
1.  Navigate to the `terraform/` directory.
2.  Populate `terraform.tfvars` with your client list and credentials (the file is ignored by Git for security).
3.  Execute the deployment:
    ```bash
    terraform init
    terraform plan
    terraform apply
    ```

---

## 2. Manual Deployment via Azure CLI (CLI/ARM Alternative)

Use these commands if you prefer manual execution via terminal. All comments are provided in English.

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

# Create 'functions' subnet with delegation and service endpoints
az network vnet subnet create \
  --name functions \
  --resource-group rg_zabbix_exporter \
  --vnet-name vnet-zabbix-exporter \
  --address-prefix 10.0.1.0/24 \
  --service-endpoints Microsoft.Storage Microsoft.KeyVault \
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

# Create the Storage Account
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

# Enable Retention Policies for Blobs
az storage account blob-service-properties update \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --enable-delete-retention true \
  --delete-retention-days 7 \
  --enable-container-delete-retention true \
  --container-delete-retention-days 7

# Enable Retention Policy for File Shares
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

# Add VNet Subnet to Storage rules
az storage account network-rule add \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --subnet $SUBNET_NAME

# Obtain the Account Key
ACCOUNT_KEY=$(az storage account keys list \
  --account-name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query '[0].value' -o tsv)

# Create system containers
az storage container create --name azure-webjobs-hosts --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
az storage container create --name azure-webjobs-secrets --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off

# Create metric containers per client (Repeat for each client)
az storage container create --name metrics-dibaq --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
az storage container create --name metrics-saba --account-name $STORAGE_ACCOUNT --account-key $ACCOUNT_KEY --public-access off
```

### 2.3. Azure Key Vault
```bash
# Declare Constants
KEY_VAULT_NAME="kv-zabbix-exporter"
TENANT_ID=$(az account show --query tenantId -o tsv)
CURRENT_USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)

# Create the Key Vault
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

# Set Access Policy for the current user (Deployment Admin)
az keyvault set-policy \
  --name $KEY_VAULT_NAME \
  --object-id $CURRENT_USER_OBJECT_ID \
  --secret-permissions get list set delete purge recover

# Note: Access policy for Managed Identity is added after identity creation
```

### 2.4. Azure Function & Identity Setup
```bash
# Declare Constants
FUNCTION_APP_NAME="func-zabbix-exporter"
MANAGED_IDENTITY_NAME="func-zabbix-exporter-uami"

# Create User Assigned Managed Identity
az identity create \
  --name $MANAGED_IDENTITY_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Obtain Identity IDs
IDENTITY_ID=$(az identity show --name $MANAGED_IDENTITY_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)
IDENTITY_PRINCIPAL_ID=$(az identity show --name $MANAGED_IDENTITY_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv)

# Apply Key Vault Access Policy for the Managed Identity
az keyvault set-policy --name $KEY_VAULT_NAME --object-id $IDENTITY_PRINCIPAL_ID --secret-permissions get list

# Assign Storage permissions to the Managed Identity
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"

# Create Application Insights
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

# Create the Function App (Flex Consumption)
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

# Configure instance memory
az functionapp update \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set functionAppConfig.scaleAndConcurrency.instanceMemoryMB=2048

# Configure Application Insights setting
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_KEY"

# Enable VNet Integration
az functionapp vnet-integration add \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet $VNET_NAME \
  --subnet $SUBNET_NAME

# Enable VNet route all for egress traffic
az functionapp config set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet-route-all-enabled true

# Disable Basic Authentication for security (FTP/SCM)
az resource update --resource-group $RESOURCE_GROUP --name ftp --resource-type basicPublishingCredentialsPolicies --namespace Microsoft.Web --parent sites/$FUNCTION_APP_NAME --set properties.allow=false
az resource update --resource-group $RESOURCE_GROUP --name scm --resource-type basicPublishingCredentialsPolicies --namespace Microsoft.Web --parent sites/$FUNCTION_APP_NAME --set properties.allow=false

# Configure CORS for Azure Portal access
az functionapp cors add \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --allowed-origins "https://portal.azure.com"
```

### 2.5. Multi-Client Configuration
Repeat the following for each client to add their secrets and reference them in the Function App:

```bash
# 1. Set Client Secrets in Key Vault
az keyvault secret set --vault-name $KEY_VAULT_NAME --name "ZABBIX-URL-DIBAQ" --value "https://dibaq-monitoring.myclouddoor.com/"
# ... Repeat for USER and PASSWORD

# 2. Get Secret IDs for references
DIBAQ_URL_URI=$(az keyvault secret show --vault-name $KEY_VAULT_NAME --name "ZABBIX-URL-DIBAQ" --query id -o tsv)

# 3. Update Function Settings
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
  CLIENTS="dibaq,saba,..." \
  ZABBIX_URL_DIBAQ="@Microsoft.KeyVault(SecretUri=$DIBAQ_URL_URI)"
```

---

## 3. Manual Deployment via Azure Portal

1.  **Resource Group**: Create `rg_zabbix_exporter` in `West Europe`.
2.  **VNet**: Create `vnet-zabbix-exporter`. Add subnet `functions` with delegation to `Microsoft.App/environments` and Service Endpoints for `Storage` and `Key Vault`.
3.  **Storage**: Create `stzabbixexporter`. Enable Soft Delete. Create containers: `azure-webjobs-hosts`, `azure-webjobs-secrets`, and `metrics-<client_id>` for each client.
4.  **Identity**: Create a User Assigned Managed Identity. Give it `Storage Blob Data Owner` on the Storage Account.
5.  **Key Vault**: Create `kv-zabbix-exporter`. Add access policies for yourself and the Managed Identity. Add secrets for each client.
6.  **Function App**: Create using the **Flex Consumption** plan. Enable VNet Integration. Add the Managed Identity. Set Environment Variables using Key Vault references.

---

## 4. Power Automate Workflow

Follow these steps to set up the flow and route notifications to your specific Teams chats:

### Step 1: Trigger
Select **"When a Teams webhook request is received"**.

- Set **"Who can trigger the flow?"** to **Anyone**.
- **Action Required**: Once saved, copy your unique HTTP URL and use it in your application settings.

### Step 2: Condition
Add a **Condition** step to filter by client using the following expression:
```
triggerBody()?['client']
```

### Step 3: Branching Logic
Configure the condition branches as follows:

- **If equal to `client1`** → Configure it to post in your specific Client 1 Chat.
- **If equal to `client2`** → Configure it to post in your specific Client 2 Chat.

### Step 4: Action
Use the **"Post message in a chat or channel"** action.

- **Content**: Use the expression `triggerBody()?['full_message']` to populate the message text.

> [!IMPORTANT]  
> Ensure you update the Chat IDs and the Webhook URL with your own environment values to make the workflow functional.

For a more detailed step-by-step guide, including screenshots and advanced configuration, visit this repository: [Teams Webhook Workflow Documentation](https://github.com/sebas80sebas/teams-webhook-workflow)



