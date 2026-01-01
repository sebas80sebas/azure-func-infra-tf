"""
Script to generate secure Azure Blob Storage container SAS tokens
and send download links to Teams
"""

from azure.storage.blob import BlobServiceClient, generate_container_sas as azure_generate_container_sas, ContainerSasPermissions
from datetime import datetime, timedelta, timezone
import os
import requests
import json

# Configuration from environment variables (Azure Functions)
TEAMS_WEBHOOK_URL = os.getenv('TEAMS_WEBHOOK_URL', '')
SAS_EXPIRY_HOURS = int(os.getenv('SAS_EXPIRY_HOURS', '168'))  # Token valid for 168 hours (7 days)
ONLY_LATEST_FILE = os.getenv('ONLY_LATEST_FILE', 'true').lower() == 'true'  # Show only the latest Excel file


def generate_container_sas(
    connection_string: str,
    container_name: str,
    expiry_hours: int = 168
) -> tuple:
    """
    Generates a SAS token for the entire container with read-only permissions.
    """
    
    # Extract information from connection string
    conn_parts = dict(item.split('=', 1) for item in connection_string.split(';') if '=' in item)
    account_name = conn_parts.get('AccountName')
    account_key = conn_parts.get('AccountKey')
    
    if not account_name or not account_key:
        raise ValueError("Invalid connection string: missing AccountName or AccountKey")
    
    # Create client to verify container exists
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    
    if not container_client.exists():
        raise FileNotFoundError(f"Container '{container_name}' does not exist")
    
    # Configure SAS token permissions (read-only and list)
    sas_permissions = ContainerSasPermissions(read=True, list=True)
    
    # Define expiration time
    expiry_time = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
    
    # Generate SAS token for container
    sas_token = azure_generate_container_sas(
        account_name=account_name,
        container_name=container_name,
        account_key=account_key,
        permission=sas_permissions,
        expiry=expiry_time
    )
    
    # Build container URL (without SAS)
    container_url = f"https://{account_name}.blob.core.windows.net/{container_name}"
    
    return container_url, sas_token, expiry_time, account_name


def list_container_files(connection_string: str, container_name: str, only_latest: bool = False) -> list:
    """
    Lists Excel files in the container.
    """
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    
    excel_files = []
    blob_list = container_client.list_blobs()
    
    # Collect Excel files with their last modified time
    excel_blobs = []
    for blob in blob_list:
        if blob.name.lower().endswith(('.xlsx', '.xls')):
            excel_blobs.append({
                'name': blob.name,
                'last_modified': blob.last_modified
            })
    
    if not excel_blobs:
        return []
    
    if only_latest:
        # Sort by last_modified and return only the most recent
        latest_blob = sorted(excel_blobs, key=lambda x: x['last_modified'], reverse=True)[0]
        return [latest_blob['name']]
    else:
        # Return all files sorted by last_modified (newest first)
        sorted_blobs = sorted(excel_blobs, key=lambda x: x['last_modified'], reverse=True)
        return [blob['name'] for blob in sorted_blobs]

def send_to_teams_workflow(
    webhook_url: str,
    container_url: str,
    sas_token: str,
    files: list,
    account_name: str,
    container_name: str,
    expiry_time: datetime,
    expiry_hours: int,
    client_id: str,
    language: str = "es"
) -> bool:
    """
    Sends download links to Teams via Workflow.
    """
    
    if not webhook_url:
        print("Teams Workflow webhook is not configured")
        return False
    
    generation_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    expiry_str = expiry_time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Build message text based on language
    if language == "en":
        # English message
        files_text = ""
        if files:
            files_text = "\n\n**Available:**\n\n"
            for i, file in enumerate(files, 1):
                file_url = f"{container_url}/{file}?{sas_token}"
                files_text += f"{i}. **{file}**  \n"
                files_text += f"   [Download Excel File]({file_url})\n\n"
        
        full_message = f"""**📊 Zabbix Monitoring Report ({client_id.upper()}) - Ready for Download**

**Information:**
- Client: {client_id.upper()}
- Generated: {generation_date} UTC
- Link expires: {expiry_str} UTC
- Validity: {expiry_hours} hours

{files_text}

**How to download:**
1. Click on any "Download Excel File" link above
2. The file will download automatically
3. Open it in Microsoft Excel to view all charts and data

**Important:** Download links expire in {expiry_hours} hours
"""
    else:
        # Spanish message
        files_text = ""
        if files:
            files_text = "\n\n**Disponible:**\n\n"
            for i, file in enumerate(files, 1):
                file_url = f"{container_url}/{file}?{sas_token}"
                files_text += f"{i}. **{file}**  \n"
                files_text += f"   [Descargar archivo Excel]({file_url})\n\n"
        
        full_message = f"""**📊 Informe de Monitorización Zabbix ({client_id.upper()}) - Listo para Descargar**

**Información:**
- Cliente: {client_id.upper()}
- Generado: {generation_date} UTC
- Enlaces expiran: {expiry_str} UTC
- Validez: {expiry_hours} horas

{files_text}

**Cómo descargar:**
1. Haz clic en cualquier enlace "Descargar archivo Excel" de arriba
2. El archivo se descargará automáticamente
3. Ábrelo en Microsoft Excel para ver todos los gráficos y datos

**Importante:** Los enlaces de descarga expiran en {expiry_hours} horas
"""
    
    payload = {
        "client": client_id,
        "titulo": f"📊 Informe Zabbix ({client_id.upper()})" if language == "es" else f"📊 Zabbix Report ({client_id.upper()})",
        "cuenta": account_name,
        "contenedor": container_name,
        "fecha": generation_date,
        "expira": expiry_str,
        "validez_horas": expiry_hours,
        "url_contenedor": container_url,
        "sas_token": sas_token,
        "archivos": files,
        "full_message": full_message,
        "language": language
    }
    
    try:
        response = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload, default=str)
        )
        
        if response.status_code in [200, 202]:
            print(f"Message for {client_id} ({language}) sent successfully to Teams")
            return True
        else:
            print(f"Error sending message for {client_id} to Teams. Status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error sending message for {client_id} to Teams: {e}")
        return False
