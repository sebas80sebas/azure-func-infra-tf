# Zabbix Metrics Azure Exporter (Multi-Client)

## Overview

This project is a serverless Azure Function application that:
1. **Exports metrics** from multiple Zabbix monitoring systems to individual CSV files per client.
2. **Generates Excel dashboards** with charts and analysis for each client.
3. **Sends notifications** to specific Microsoft Teams chats via a Power Automate workflow with secure download links.

---

## Architecture
```
┌─────────────────┐
│  Azure Function │
│  (Timer Trigger)│
│  Monthly: Day 1 │
└────────┬────────┘
         │
         ├──► 1. Orchestration (Loop through CLIENTS)
         │         │
         │         ├──► export_metrics_csv.py (per client)
         │         │     └──► Zabbix API ──► CSVs ──► Blob (client container)
         │         │
         │         ├──► csv_to_excel_dashboard.py (per client)
         │         │     └──► Read CSVs ──► Excel ──► Blob (client container)
         │         │
         │         └──► send_to_teams.py (per client)
         │               └──► SAS Token ──► Teams Webhook (with client ID)
```

---

## Infrastructure Deployment

For a comprehensive guide covering multiple deployment methods (Terraform, Azure CLI/ARM, and Azure Portal), please refer to the **[Deployment Guide](./DEPLOYMENT_GUIDE.md)**.

### Quick Start with Terraform

1. **Initialize**:
   ```bash
   cd terraform/
   terraform init
   ```

2. **Configure Variables**:
   Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in your private client data:
   ```hcl
   clients = {
     "client_a" = {
       url  = "https://zabbix.client-a.com/api_jsonrpc.php"
       user = "zabbix_user"
       pass = "zabbix_password"
     }
   }
   ```

3. **Deploy**:
   ```bash
   terraform apply
   ```

---

## Project Structure

```
zabbix-metrics-exporter/
├── terraform/               # Infrastructure as Code
├── func_app/                # Azure Function (Python)
├── DEPLOYMENT_GUIDE.md      # Detailed setup instructions
└── README.md                # This file
```

---

## Security Best Practices

*   **Secrets**: All credentials (Zabbix, Teams) are stored in **Azure Key Vault**.
*   **Networking**: VNet integration and Service Endpoints are used to secure traffic.
*   **Identity**: User Assigned Managed Identity is used for passwordless access to Azure resources.
*   **Privacy**: Client-specific data is kept out of version control via `.tfvars` and `.env` files.