import logging
import azure.functions as func
from export_metrics_csv import export_metrics
from csv_to_excel_dashboard import generate_excel
from send_to_teams import (
    generate_container_sas,
    list_container_files,
    send_to_teams_workflow,
    SAS_EXPIRY_HOURS,
    ONLY_LATEST_FILE
)
import os
from datetime import datetime

app = func.FunctionApp()

@app.schedule(
    schedule="0 0 1 * *",  # Day 1 of each month at 00:00
    arg_name="mytimer",
    run_on_startup=False,
    use_monitor=False
)
def monthly_metrics_export(mytimer: func.TimerRequest) -> None:
    start_time = datetime.now()
    logging.info("Starting Multi-Client Azure Function: monthly metrics extraction")
    
    clients_str = os.getenv('CLIENTS', '')
    if not clients_str:
        logging.error("No CLIENTS configured in environment variables")
        return

    clients = [c.strip() for c in clients_str.split(',') if c.strip()]
    logging.info(f"Processing {len(clients)} clients: {clients}")

    for client in clients:
        logging.info(f"--- Processing Client: {client} ---")
        try:
            # 1. Get client-specific configuration
            zabbix_url = os.getenv(f'ZABBIX_URL_{client.upper()}')
            zabbix_user = os.getenv(f'ZABBIX_USER_{client.upper()}')
            zabbix_password = os.getenv(f'ZABBIX_PASSWORD_{client.upper()}')
            container_name = f"metrics-{client}"

            if not all([zabbix_url, zabbix_user, zabbix_password]):
                logging.error(f"Missing configuration for client {client}. Skipping.")
                continue

            # Step 1: Export metrics
            logging.info(f"[{client}] Exporting metrics to CSV...")
            export_metrics(zabbix_url, zabbix_user, zabbix_password, container_name)
            
            # Step 2: Generate Excel
            logging.info(f"[{client}] Generating Excel file...")
            generate_excel(container_name)
            
            # Step 3: Send to Teams
            logging.info(f"[{client}] Notifying Teams...")
            send_to_teams(client, container_name)
            
            logging.info(f"[{client}] Process completed successfully")
            
        except Exception as e:
            logging.error(f"Error processing client {client}: {e}")
            # Continue with next client
    
    end_time = datetime.now()
    duration = end_time - start_time
    logging.info(f"Multi-Client Azure Function completed in {duration}")


def send_to_teams(client_id: str, container_name: str) -> None:
    """
    Generates SAS token and sends it to Teams via Workflow for a specific client
    """
    connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
    webhook_url = os.getenv('TEAMS_WEBHOOK_URL', '')
    
    if not connection_string:
        logging.error("AZURE_STORAGE_CONNECTION_STRING environment variable not set")
        raise ValueError("Missing AZURE_STORAGE_CONNECTION_STRING")
    
    try:
        # Generate SAS token for container
        container_url, sas_token, expiry_time, account_name = generate_container_sas(
            connection_string=connection_string,
            container_name=container_name,
            expiry_hours=SAS_EXPIRY_HOURS
        )
        
        # List available Excel files
        files = list_container_files(
            connection_string=connection_string,
            container_name=container_name,
            only_latest=ONLY_LATEST_FILE
        )
        
        if not files:
            logging.warning(f"No Excel files found in container {container_name}")
        
        # Send to Teams if webhook is configured
        if webhook_url:
            # Send Spanish message
            send_to_teams_workflow(
                webhook_url=webhook_url,
                container_url=container_url,
                sas_token=sas_token,
                files=files,
                account_name=account_name,
                container_name=container_name,
                expiry_time=expiry_time,
                expiry_hours=SAS_EXPIRY_HOURS,
                client_id=client_id,
                language="es"
            )
            
            # Send English message
            send_to_teams_workflow(
                webhook_url=webhook_url,
                container_url=container_url,
                sas_token=sas_token,
                files=files,
                account_name=account_name,
                container_name=container_name,
                expiry_time=expiry_time,
                expiry_hours=SAS_EXPIRY_HOURS,
                client_id=client_id,
                language="en"
            )
        else:
            logging.info("TEAMS_WEBHOOK_URL not configured, skipping Teams notification")
            
    except Exception as e:
        logging.error(f"Error in send_to_teams for {client_id}: {e}")
        raise
