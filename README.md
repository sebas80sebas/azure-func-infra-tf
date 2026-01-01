# Zabbix Metrics Azure Exporter (Multi-Client)

## Overview
This project is a serverless Azure Function application designed to automate performance metric extraction from multiple Zabbix enterprises. It generates styled Excel dashboards for each client and delivers secure download links to targeted Microsoft Teams chats via Power Automate.

### Key Features
*   **Multi-Client Support**: Scalable architecture that processes any number of clients defined in configuration.
*   **Automated Cleanup**: Temporary CSV files are deleted after Excel generation to save space and prevent data corruption.
*   **Historical Preservation**: Reports are timestamped and preserved in Azure Blob Storage for future audit and analysis.
*   **Robust Error Handling**: Graceful recovery; if one client fails, the system continues processing the rest.
*   **Secure Delivery**: Uses Azure Blob SAS tokens (Time-limited) for secure file access.

---

## Architecture
```
┌─────────────────┐
│  Azure Function │
│  (Timer Trigger)│
│  Monthly: Day 1 │
└────────┬────────┘
         │
         ├──► 1. Orchestration (Loop through CLIENTS list)
         │         │
         │         ├──► export_metrics_csv.py (per client)
         │         │     └──► Zabbix API ──► CSVs ──► Blob (client container)
         │         │
         │         ├──► csv_to_excel_dashboard.py (per client)
         │         │     └──► Read CSVs ──► Generate Excel ──► Blob (client container)
         │         │     └──► Cleanup: Delete CSVs
         │         │
         │         └──► send_to_teams.py (per client)
         │               └──► Generate SAS Token ──► Teams Webhook (with Client ID)
```

---

## How the Code Works: Internal Logic

### Step 1: Export Metrics (`export_metrics_csv.py`)
1.  **Authentication**: Logs into each Zabbix API using Key Vault credentials.
2.  **Target Metrics**: Fetches specific keys like `system.cpu.util`, `vm.memory.utilization`, etc.
3.  **Data Retrieval**: Queries `trend.get` (aggregated) or `history.get` (raw) for the last 30 days.
4.  **Export**: Saves one CSV file per host into the client's dedicated container (`metrics-clientid`).

### Step 2: Generate Excel Dashboard (`csv_to_excel_dashboard.py`)
1.  **Filtering**: Reads ONLY `.csv` files, ensuring old reports or metadata are ignored.
2.  **Analysis**: Calculates global averages, summary statistics, and detailed host-group metrics.
3.  **Styling**: Applies conditional formatting (e.g., Red for CPU > 80%).
4.  **Storage**: Uploads the timestamped `.xlsx` report.
5.  **Cleanup**: Deletes all processed CSV files to keep the container clean for next month.

### Step 3: Send Teams Notification (`send_to_teams.py`)
1.  **Secure Links**: Generates a container-level SAS token valid for 168 hours.
2.  **Payload**: Constructs a JSON containing the `client_id` and formatted message.
3.  **Bilingual Support**: Sends both Spanish and English notifications to the Power Automate Webhook.

---

## What the Application Returns

### 1. For Azure Function (Logs)
*   Detailed processing status for each client.
*   Confirmation of Excel uploads and CSV cleanups.
*   Diagnostic error messages for unreachable APIs.

### 2. For End Users (Teams)
*   **Bilingual Messages**: Clear download links and instructions.
*   **Security**: Links that expire automatically after 7 days.

### 3. In Azure Storage
*   `metrics-<client>/`: Contains all historical Excel reports.
*   `azure-webjobs-hosts/`: System logs and state.

---

## Scheduled Execution
The Azure Function runs automatically via a Timer Trigger:
*   **Cron Schedule**: `0 0 1 * *`
*   **Timing**: Day 1 of every month at 00:00 UTC.
*   **Manual Trigger**: Use `az functionapp function invoke` for immediate testing.

---

## Security Best Practices
*   **Identity**: Uses **User Assigned Managed Identity** for resource access.
*   **Vault**: All sensitive URLs and credentials reside in **Azure Key Vault**.
*   **Network**: Employs VNet Integration and Service Endpoints for Storage and Key Vault.
*   **Privacy**: Client data is never committed to Git; it is managed via local `.tfvars`.

---

## Estimated Cost Breakdown
| Service | Estimated Cost |
|---------|----------------|
| Function App (Flex Consumption) | $2 - $10 / month |
| Storage Account (LRS, Hot) | $1 - $3 / month |
| Key Vault (Standard) | < $1 / month |
| **Total** | **~$5 - $15 / month** |

---

## Project Structure
```
zabbix-metrics-exporter/
├── terraform/               # Infrastructure as Code
├── func_app/                # Python Function logic
├── DEPLOYMENT_GUIDE.md      # Setup manual
└── README.md                # This file
```
