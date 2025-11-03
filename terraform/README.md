# Zabbix Metrics Exporter

## 📋 Overview

This project is a serverless Azure Function application that:
1. **Exports metrics** from Zabbix monitoring system to CSV files
2. **Generates Excel dashboards** with charts and analysis
3. **Sends notifications** to Microsoft Teams with secure download links

---

## 🏗️ Architecture
```
┌─────────────────┐
│  Azure Function │
│  (Timer Trigger)│
│  Monthly: Day 1 │
└────────┬────────┘
         │
         ├──► 1. export_metrics_csv.py
         │         │
         │         └──► Zabbix API ──► CSV files ──► Blob Storage
         │
         ├──► 2. csv_to_excel_dashboard.py
         │         │
         │         └──► Read CSVs ──► Generate Excel ──► Blob Storage
         │
         └──► 3. send_to_teams.py
                   │
                   ├──► Generate SAS Token
                   └──► Send to Teams Workflow (ES + EN)
```

---

## 🚀 Infrastructure Deployment with Terraform

### Prerequisites

Before deploying the Azure Function, you need to set up the required Azure resources using Terraform.

#### Required Tools

```bash
# Install Terraform
# https://developer.hashicorp.com/terraform/downloads

# Install Azure CLI
# https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

# Verify installations
terraform --version
az --version

# Login to Azure
az login

# Set your subscription (if you have multiple)
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

---

### Project Structure

```
zabbix-metrics-exporter/
├── terraform/
│   ├── main.tf                    # Main infrastructure configuration
│   ├── variables.tf               # Variable definitions
│   ├── outputs.tf                 # Output values
│   ├── terraform.tfvars.example   # Example variables file
│   ├── terraform.tfvars           # Your actual values (DO NOT COMMIT)
│   ├── .gitignore                 # Git ignore rules
│   └── README.md                  # Terraform documentation
├── function_app/
│   ├── function_app.py            # Azure Function code
│   ├── export_metrics_csv.py
│   ├── csv_to_excel_dashboard.py
│   ├── send_to_teams.py
│   ├── requirements.txt
│   └── host.json
└── README.md                      # This file
```

---

### Terraform Configuration Files

#### 1. Create `.gitignore`

**Critical:** Protect sensitive files from being committed to Git.

```bash
# terraform/.gitignore

# Terraform state files
*.tfstate
*.tfstate.*
*.tfstate.backup

# Variable files with secrets
*.tfvars
!terraform.tfvars.example

# Terraform directories
.terraform/
.terraform.lock.hcl

# Crash log files
crash.log
crash.*.log

# Override files
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# CLI configuration files
.terraformrc
terraform.rc

# Environment files
.env
.env.*
```

---

#### 2. Create `terraform.tfvars.example`

**Purpose:** Template file that can be safely committed to Git.

```hcl
# terraform/terraform.tfvars.example
# Copy this file to terraform.tfvars and fill in your actual values

# Azure Configuration
azure_subscription_id = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
azure_location        = "westeurope"
resource_group_name   = "rg-zabbix-exporter"

# Naming Configuration
project_name    = "zabbix-exporter"
environment     = "prod"

# Storage Account Configuration
storage_account_tier        = "Standard"
storage_account_replication = "LRS"

# Function App Configuration
function_app_plan_sku = "Y1"  # Consumption plan

# Zabbix Configuration
zabbix_url      = "https://your-zabbix-server.com/api_jsonrpc.php"
zabbix_user     = "your_zabbix_username"
zabbix_password = "your_zabbix_password"

# Teams Configuration
teams_webhook_url = "https://prod-XX.westeurope.logic.azure.com:443/workflows/..."

# SAS Token Configuration
sas_expiry_hours  = "72"
only_latest_file  = "true"

# Network Configuration (Optional)
allowed_ip_addresses = [
  "XX.XX.XX.XX",
  "YY.YY.YY.YY"
]

# Tags
tags = {
  Project     = "Zabbix Metrics Exporter"
  Environment = "Production"
  ManagedBy   = "Terraform"
  CostCenter  = "IT-Monitoring"
}
```

---

### Deployment Steps

#### Step 1: Initialize Terraform

Navigate to the Terraform directory and initialize the working directory:

```bash
cd terraform/

# Initialize Terraform (downloads providers and modules)
terraform init

# Expected output:
# Terraform has been successfully initialized!
```

---

#### Step 2: Configure Your Variables

```bash
# Copy the example file
cp terraform.tfvars.example terraform.tfvars

# Edit with your actual values
nano terraform.tfvars  # or use your preferred editor

# IMPORTANT: Ensure terraform.tfvars contains real credentials
# This file should NEVER be committed to Git
```

**Required variables to configure:**
- `azure_subscription_id` - Your Azure subscription ID
- `zabbix_url` - Your Zabbix API endpoint
- `zabbix_user` - Zabbix API username
- `zabbix_password` - Zabbix API password
- `teams_webhook_url` - Your Teams workflow webhook URL

---

#### Step 3: Validate Configuration

```bash
# Check for syntax errors
terraform validate

# Expected output:
# Success! The configuration is valid.

# Preview the infrastructure changes
terraform plan

# Review the output carefully:
# - Resources to be created
# - Configuration values
# - Estimated costs
```

**What `terraform plan` shows:**
```
Terraform will perform the following actions:

  # azurerm_resource_group.main will be created
  + resource "azurerm_resource_group" "main" {
      + name     = "rg-zabbix-exporter"
      + location = "westeurope"
    }

  # azurerm_storage_account.main will be created
  + resource "azurerm_storage_account" "main" {
      + name                     = "stzabbixexporter"
      + resource_group_name      = "rg-zabbix-exporter"
      + location                 = "westeurope"
      + account_tier             = "Standard"
      + account_replication_type = "LRS"
    }

  # ... more resources

Plan: 8 to add, 0 to change, 0 to destroy.
```

---

#### Step 4: Deploy Infrastructure

```bash
# Apply the Terraform configuration
terraform apply

# Terraform will show the plan again and ask for confirmation
# Type 'yes' to proceed

# Deployment takes approximately 3-5 minutes
```

**Deployment progress:**
```
azurerm_resource_group.main: Creating...
azurerm_resource_group.main: Creation complete after 2s
azurerm_storage_account.main: Creating...
azurerm_storage_account.main: Still creating... [10s elapsed]
azurerm_storage_account.main: Creation complete after 23s
azurerm_storage_container.metrics: Creating...
...
Apply complete! Resources: 8 added, 0 changed, 0 destroyed.
```

---

#### Step 5: Verify Outputs

```bash
# View all outputs
terraform output

# Example output:
# function_app_name = "func-zabbix-exporter-prod"
# storage_account_name = "stzabbixexporter"
# resource_group_name = "rg-zabbix-exporter"

# Get specific output value
terraform output function_app_name

# Get outputs in JSON format (useful for scripts)
terraform output -json > outputs.json
```

**Important outputs:**
```json
{
  "function_app_name": {
    "value": "func-zabbix-exporter-prod"
  },
  "function_app_default_hostname": {
    "value": "func-zabbix-exporter-prod.azurewebsites.net"
  },
  "storage_account_name": {
    "value": "stzabbixexporter"
  },
  "storage_connection_string": {
    "sensitive": true,
    "value": "DefaultEndpointsProtocol=https;..."
  },
  "resource_group_name": {
    "value": "rg-zabbix-exporter"
  }
}
```

---

### Post-Deployment: Deploy Function Code

After Terraform creates the infrastructure, deploy your Python code:

#### Option 1: Using Azure Functions Core Tools

```bash
# Navigate to your function code directory
cd ../function_app/

# Install Azure Functions Core Tools if not already installed
# https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local

# Get the function app name from Terraform
FUNCTION_APP_NAME=$(cd ../terraform && terraform output -raw function_app_name)

# Deploy the function code
func azure functionapp publish $FUNCTION_APP_NAME --python

# Expected output:
# Getting site publishing info...
# Uploading package...
# Upload completed successfully.
# Deployment completed successfully.
```

#### Option 2: Using Azure CLI

```bash
# Get function app name and resource group
FUNCTION_APP_NAME=$(cd ../terraform && terraform output -raw function_app_name)
RESOURCE_GROUP=$(cd ../terraform && terraform output -raw resource_group_name)

# Create deployment package
cd function_app/
zip -r ../function.zip .

# Deploy
az functionapp deployment source config-zip \
  --resource-group $RESOURCE_GROUP \
  --name $FUNCTION_APP_NAME \
  --src ../function.zip
```

---

### Verify Deployment

```bash
# Check Function App status
az functionapp show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query state

# View Function App logs
az functionapp log tail \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP

# Test the function manually (trigger timer function)
az functionapp function invoke \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --function-name monthly_metrics_export
```

---

### Infrastructure Management

#### Update Infrastructure

```bash
# Modify terraform.tfvars or .tf files as needed

# Preview changes
terraform plan

# Apply changes
terraform apply
```

#### View Current State

```bash
# List all resources
terraform state list

# Show details of a specific resource
terraform state show azurerm_storage_account.main
```

#### Destroy Infrastructure

```bash
# CAUTION: This will delete all resources!
terraform destroy

# Terraform will show what will be destroyed
# Type 'yes' to confirm
```

---

### Terraform Outputs Reference

| Output | Description | Usage |
|--------|-------------|-------|
| `resource_group_name` | Resource group name | For Azure CLI commands |
| `storage_account_name` | Storage account name | For blob operations |
| `storage_connection_string` | Connection string (sensitive) | For application configuration |
| `function_app_name` | Function app name | For deployments |
| `function_app_default_hostname` | Function app URL | For testing |
| `container_name` | Blob container name | For file access |

---

### Troubleshooting Terraform

#### Issue: "Error: Subscription not found"
```bash
# Solution: Verify your Azure login
az account show
az account list --output table

# Set the correct subscription
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

#### Issue: "Error: storage account name already exists"
```bash
# Solution: Storage account names must be globally unique
# Modify the name in terraform.tfvars:
storage_account_name = "stzabbixexporter2024"
```

#### Issue: "Error: Insufficient permissions"
```bash
# Solution: Ensure your Azure account has required roles
az role assignment list --assignee YOUR_EMAIL

# Required role: Contributor or Owner on the subscription
```

#### Issue: State file is locked
```bash
# Solution: If another process crashed, force-unlock
terraform force-unlock LOCK_ID

# Get LOCK_ID from the error message
```

#### Reset and start fresh
```bash
# Remove local state (CAUTION: only if safe to do so)
rm -rf .terraform/
rm -rf .terraform.lock.hcl
rm -rf terraform.tfstate*

# Re-initialize
terraform init
```

---

### Best Practices

✅ **Security**
- Never commit `terraform.tfvars` to Git
- Use Azure Key Vault for sensitive values (advanced setup)
- Rotate credentials regularly
- Enable Terraform state encryption

✅ **State Management**
- Store Terraform state in Azure Storage (remote backend)
- Enable state locking to prevent concurrent modifications
- Regularly backup state files

✅ **Code Organization**
- Use separate `.tfvars` files per environment (dev, staging, prod)
- Modularize Terraform code for reusability
- Document all variables and outputs

✅ **Version Control**
- Tag releases in Git
- Use semantic versioning for infrastructure changes
- Maintain a CHANGELOG.md

---

## ⚙️ Azure Storage Account Configuration

### 1. Basic Settings

These settings are automatically configured by Terraform:

| Setting | Value | Description |
|---------|-------|-------------|
| **Account Name** | `stzabbixexporter` | Unique storage account name |
| **Location** | `West Europe` | Azure region |
| **Performance** | `Standard` | Standard performance tier |
| **Replication** | `LRS (Locally Redundant)` | Data redundancy strategy |
| **Account Kind** | `StorageV2` | General-purpose v2 |
| **Access Tier** | `Hot` | Optimized for frequent access |

### 2. Security Configuration

#### 2.1 Network Rules
```json
{
  "defaultAction": "Allow",
  "bypass": "Logging, Metrics, AzureServices",
  "virtualNetworkRules": [
    {
      "subnet": "/subscriptions/.../vnet-zabbix-exporter/subnets/functions",
      "action": "Allow"
    }
  ],
}
```

**Configuration:**
- Allow Azure Services to bypass firewall
- Restrict access to specific VNet subnet (for Azure Functions)
- Whitelist specific public IPs for external access

#### 2.2 Encryption & Security

| Setting | Value |
|---------|-------|
| **Minimum TLS Version** | `TLS 1.2` |
| **HTTPS Only** | `Enabled` |
| **Public Blob Access** | `Disabled` |
| **Shared Key Access** | `Enabled` (for SAS tokens) |
| **Infrastructure Encryption** | `Disabled` |

### 3. Required Blob Containers

These containers are automatically created by Terraform:

| Container Name | Purpose | Public Access |
|----------------|---------|---------------|
| `metrics` | Stores CSV files and Excel reports | Private |
| `azure-webjobs-hosts` | Azure Functions runtime data | Private |
| `azure-webjobs-secrets` | Azure Functions secrets | Private |
| `app-package-*` | Function deployment packages | Private |

#### Container Retention Policies
```json
{
  "containerDeleteRetentionPolicy": {
    "enabled": true,
    "days": 7
  },
  "deleteRetentionPolicy": {
    "enabled": true,
    "days": 7
  }
}
```

### 4. Environment Variables

These are automatically configured by Terraform in the Function App:

```bash
# Azure Storage
AZURE_STORAGE_CONNECTION_STRING="<automatically_set_by_terraform>"
AZURE_CONTAINER_NAME="metrics"

# Zabbix API
ZABBIX_URL="<from_terraform.tfvars>"
ZABBIX_USER="<from_terraform.tfvars>"
ZABBIX_PASSWORD="<from_terraform.tfvars>"

# Teams Notification
TEAMS_WEBHOOK_URL="<from_terraform.tfvars>"

# SAS Token Configuration
SAS_EXPIRY_HOURS="72"
ONLY_LATEST_FILE="true"
```

---

## 📊 How the Code Works

### Execution Flow

#### **Step 1: Export Metrics (`export_metrics_csv.py`)**
```python
# 1. Authenticate with Zabbix API
auth_token = zabbix_api("user.login", {...})

# 2. Get all monitored hosts
hosts = zabbix_api("host.get", {...})

# 3. For each host, fetch target metrics:
TARGET_KEYS = [
    "system.cpu.util",           # CPU utilization
    "system.cpu.util[,idle]",    # CPU idle time
    "system.cpu.util[,iowait]",  # CPU I/O wait
    "vm.memory.utilization",     # Memory usage
    "vm.memory.size[available]", # Available memory
    # ... more metrics
]

# 4. Query historical data (last 30 days)
trends = zabbix_api("trend.get", {...})  # Aggregated data
history = zabbix_api("history.get", {...})  # Raw data

# 5. Calculate statistics: Min, Max, Avg, Samples
# 6. Save each host's data to CSV file in Blob Storage
```

**Output:** One CSV file per host in `metrics` container
```
host1.csv
host2.csv
host3.csv
```

**CSV Format:**
```csv
Metric,Min,Max,Avg,Samples
CPU utilization,5.23,89.45,42.18,1440
Memory utilization,32.10,78.90,55.23,1440
```

---

#### **Step 2: Generate Excel Dashboard (`csv_to_excel_dashboard.py`)**
```python
# 1. Download all CSV files from Blob Storage
csv_data = {}
for blob in container_client.list_blobs():
    csv_data[blob.name] = pd.read_csv(stream)

# 2. Create Excel Workbook with multiple sheets:
wb = Workbook()

# Sheet 1: "Dashboard" - Executive Summary
- Total hosts count
- Total metrics count
- Top 10 CPU usage (with conditional formatting)
- Top 10 Memory usage (with conditional formatting)
- Bar charts for Top 10 visualizations

# Sheet 2: "All Hosts" - Consolidated data
- All metrics from all hosts in one table
- Color-coded rows (CPU = red, Memory = green)

# Sheet 3+: Individual host sheets
- One sheet per host with detailed metrics
- Line charts for CPU trends
- Line charts for Memory trends

# 3. Upload Excel file to Blob Storage
filename = f"Zabbix_Report_20241021_143022.xlsx"
```

**Excel Structure:**
```
📊 Zabbix_Report_20241021_143022.xlsx
│
├── 📄 Dashboard
│   ├── Summary statistics
│   ├── Top 10 CPU (table + chart)
│   └── Top 10 Memory (table + chart)
│
├── 📄 All Hosts
│   └── Complete metrics table (all hosts)
│
├── 📄 host1
│   ├── Metrics table
│   ├── CPU trends chart
│   └── Memory trends chart
│
├── 📄 host2
│   └── ...
```

**Conditional Formatting:**
- 🔴 **Red (>80%)**: Critical usage
- 🟡 **Orange (60-80%)**: Warning level
- ⚪ **White (<60%)**: Normal

---

#### **Step 3: Send Teams Notification (`send_to_teams.py`)**
```python
# 1. Generate SAS Token for secure access
sas_token = azure_generate_container_sas(
    account_name="stzabbixexporter",
    container_name="metrics",
    permission=ContainerSasPermissions(read=True, list=True),
    expiry=datetime.now() + timedelta(hours=72)
)

# 2. Build container URL with SAS
container_url = f"https://{account_name}.blob.core.windows.net/metrics"
full_url = f"{container_url}?{sas_token}"

# 3. List Excel files in container
files = ["Zabbix_Report_20241021_143022.xlsx"]

# 4. Send to Teams Workflow (bilingual)
# - Spanish message
# - English message
# Each contains:
#   - Direct download links
#   - Expiration time
#   - Instructions
```

**Teams Message Format:**
```markdown
📊 Zabbix Monitoring Report - Ready for Download

ℹ️ Information:
- Generated: 2024-10-21 14:30:22 UTC
- Link expires: 2024-10-24 14:30:22 UTC
- Validity: 72 hours

📊 Available Excel Reports:

1. **Zabbix_Report_20241021_143022.xlsx**
   📥 [Download Excel File](https://stzabbixexporter.blob.core.windows.net/metrics/Zabbix_Report_20241021_143022.xlsx?sv=2024-05-04&st=2024-10-21T14:30:22Z&se=2024-10-24T14:30:22Z&sr=c&sp=rl&sig=...)

📥 How to download:
1. Click on "Download Excel File" link above
2. File downloads automatically
3. Open in Microsoft Excel

⚠️ Important: Links expire in 72 hours
```

---

## 🔄 Scheduled Execution

The Azure Function runs automatically:
```python
@app.schedule(
    schedule="0 0 1 * *",  # Day 1 of each month at 00:00 UTC
    arg_name="mytimer",
    run_on_startup=False
)
def monthly_metrics_export(mytimer):
    export_metrics()      # Step 1
    generate_excel()      # Step 2
    send_to_teams()       # Step 3
```

**Cron Schedule:** `0 0 1 * *`
- Executes on the 1st day of every month
- At midnight (00:00 UTC)

---

## 📤 What the Application Returns

### For Azure Function (Logs)
```
Starting Azure Function: monthly metrics extraction
Authenticating to Zabbix...
✅ Authentication successful
📊 Zabbix version: 6.0.15
🎉 Hosts processed: 45, Hosts with data: 42
Generating Excel file...
✅ Excel 'Zabbix_Report_20241021_143022.xlsx' uploaded
Generating SAS token...
Found 1 Excel file(s)
📤 Sending notifications to Teams...
✅ Both notifications sent successfully (Spanish and English)
Process completed
```

### For End Users (Teams)

- 📧 **2 Teams messages** (Spanish + English)
- 🔗 **Direct download links** with SAS tokens
- ⏰ **Expiration warning** (72 hours)
- 📊 **Excel file** with:
  - Executive dashboard
  - Top 10 rankings
  - Charts and visualizations
  - Individual host analysis

### For Storage Account
```
metrics/
├── host1.csv
├── host2.csv
├── host3.csv
├── ...
└── Zabbix_Report_20241021_143022.xlsx
```

---

## 🔒 Security Best Practices

✅ **Implemented:**
- TLS 1.2 minimum
- VNet integration
- IP whitelisting
- SAS token expiration (72h)
- Private blob containers
- Soft delete enabled (7 days)
- Infrastructure as Code (Terraform)
- Secrets management via Azure Function App Settings

---

## 📝 Troubleshooting

### Common Issues

**Issue:** `AZURE_STORAGE_CONNECTION_STRING is not configured`
- **Solution:** Run `terraform apply` to ensure environment variables are set

**Issue:** `Container 'metrics' does not exist`
- **Solution:** Container is auto-created by Terraform

**Issue:** `Zabbix error: Session terminated`
- **Solution:** Check Zabbix credentials in `terraform.tfvars`

**Issue:** Teams notification not received
- **Solution:** Verify `TEAMS_WEBHOOK_URL` in `terraform.tfvars`

**Issue:** Function deployment fails
- **Solution:** Ensure infrastructure is deployed first with Terraform

---

## 📚 Dependencies

### Terraform Providers
```hcl
terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}
```

### Python Dependencies
```txt
azure-functions==1.18.0
azure-storage-blob==12.19.0
pandas==2.1.4
openpyxl==3.1.2
requests==2.31.0
```

---

## 📞 Support

For issues or questions:
1. Check Terraform outputs: `terraform output`
2. Review Azure Function logs in Application Insights
3. Verify all environment variables are set
4. Test storage account connectivity
5. Validate Zabbix API access
6. Check Terraform state: `terraform state list`
 
---
