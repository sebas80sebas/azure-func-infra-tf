import requests
import csv
import datetime
import io
import os
import json
from azure.storage.blob import BlobServiceClient

# ============================================================
# Zabbix Configuration - retrieved from environment variables
# ============================================================
ZABBIX_URL = os.getenv("ZABBIX_URL")
ZABBIX_USER = os.getenv("ZABBIX_USER")
ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD")

# Create a session with SSL verification enabled
session = requests.Session()
session.verify = True

def zabbix_api(method, params, auth=None):
    """
    Generic function to call any Zabbix API method.
    Handles request structure, errors, and JSON-RPC validation.

    method: Zabbix API method name
    params: dictionary containing method parameters
    auth: authentication token (optional)
    """
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
        "auth": auth
    }

    response = session.post(ZABBIX_URL, headers=headers, json=payload)
    response.raise_for_status()  # raise HTTP errors
    result = response.json()
    
    # Handle Zabbix API-level errors
    if "error" in result:
        error_msg = result["error"].get("message", "Unknown error")
        error_data = result["error"].get("data", "")
        raise Exception(f"Zabbix error: {error_msg} - {error_data}")
    
    # Validate JSON-RPC format
    if "result" not in result:
        raise Exception(f"Unexpected response from Zabbix: {result}")
    
    return result["result"]

def convert_value(value, item_key, item_name):
    """
    Converts raw metric values depending on their type.

    - CPU metrics are already percentages.
    - Memory size values come in bytes, convert them to GB.
    - Memory utilization and pavailable are already percentages.
    """
    try:
        val = float(value)
        
        # Convert memory size from bytes to gigabytes
        if 'vm.memory.size' in item_key and 'pavailable' not in item_key:
            return val / (1024**3)
        
        return val
        
    except (ValueError, TypeError):
        return 0.0  # safe fallback for invalid numeric values

def format_value(value, item_key):
    """
    Formats output values consistently for CSV export.
    Memory values in GB and percentages are formatted with 2 decimals.
    """
    if 'vm.memory.size' in item_key and 'pavailable' not in item_key:
        return f"{value:.2f}"
    else:
        return f"{value:.2f}"

def get_unit_label(item_key):
    """
    Returns a label representing the measurement unit for each item.
    """
    if 'vm.memory.size' in item_key and 'pavailable' not in item_key:
        return "GB"
    elif 'cpu' in item_key.lower() or 'utilization' in item_key or 'pavailable' in item_key:
        return "%"
    else:
        return ""

def export_metrics():
    """
    Main execution function:
    - Connects to Azure Blob Storage
    - Authenticates to Zabbix API
    - Retrieves host groups, hosts and metrics
    - Collects trends or history data
    - Converts data and exports CSV files per host
    - Stores host group mapping in JSON format
    """
    # Azure Blob Storage configuration
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connect_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")
    
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_name = "metrics"
    container_client = blob_service_client.get_container_client(container_name)

    # Create container if missing
    if not container_client.exists():
        container_client.create_container()
        print(f"Container '{container_name}' created")
    else:
        print(f"Container '{container_name}' already exists")

    print("Authenticating to Zabbix...")

    # Attempt user.login with modern and older parameter naming
    try:
        auth_token = zabbix_api("user.login", {"user": ZABBIX_USER, "password": ZABBIX_PASSWORD})
    except:
        auth_token = zabbix_api("user.login", {"username": ZABBIX_USER, "password": ZABBIX_PASSWORD})

    print("Authentication successful")

    # Retrieve Zabbix version to confirm API compatibility
    version_info = zabbix_api("apiinfo.version", {})
    print(f"Zabbix version: {version_info}")

    # Define time range: last 30 days
    end_time = int(datetime.datetime.now().timestamp())
    start_time = int((datetime.datetime.now() - datetime.timedelta(days=30)).timestamp())

    # Metrics to collect
    TARGET_KEYS = [
        "system.cpu.util",
        "system.cpu.util[,idle]",
        "system.cpu.util[,iowait]",
        "system.cpu.util[,system]",
        "system.cpu.util[,user]",
        "system.cpu.util[,steal]",
        "system.cpu.num",
        "vm.memory.utilization",
        "vm.memory.size[available]",
        "vm.memory.size[pavailable]",
        "vm.memory.size[used]",
        "vm.memory.size[total]",
    ]

    # Retrieve all host groups
    print("Getting host groups...")
    host_groups = zabbix_api("hostgroup.get", {"output": ["groupid", "name"]}, auth_token)
    print(f"Found {len(host_groups)} host groups")
    
    # Prepare structure to store host group data
    hostgroup_data = {}
    for group in host_groups:
        hostgroup_data[group['groupid']] = {
            'name': group['name'],
            'hosts': []
        }

    # Retrieve all hosts with their groups
    hosts = zabbix_api("host.get", {
        "output": ["hostid", "host", "name"],
        "selectGroups": ["groupid", "name"]
    }, auth_token)
    
    hosts_processed = 0
    hosts_with_data = 0
    host_to_groups = {}

    # Process each host individually
    for host in hosts:
        host_id = host["hostid"]
        host_name = host["host"]
        
        # Track host's group names
        host_to_groups[host_name] = [g['name'] for g in host.get('groups', [])]
        
        # Map host to groups in the main dict
        for group in host.get('groups', []):
            if group['groupid'] in hostgroup_data:
                hostgroup_data[group['groupid']]['hosts'].append(host_name)

        # Retrieve items belonging to this host
        items = zabbix_api("item.get", {
            "hostids": host_id,
            "output": ["itemid", "name", "key_", "value_type", "units"],
            "filter": {"key_": TARGET_KEYS}
        }, auth_token)

        if not items:
            continue

        # Prepare CSV writer in memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Metric", "Min", "Max", "Avg", "Samples", "Host_Groups", "Unit"])
        has_data = False

        # Process each metric
        for item in items:
            item_id = item["itemid"]
            item_name = item["name"]
            item_key = item["key_"]
            value_type = int(item["value_type"])
            groups_str = ";".join(host_to_groups.get(host_name, []))
            unit_label = get_unit_label(item_key)

            # Attempt trends first
            try:
                trends = zabbix_api("trend.get", {
                    "itemids": item_id,
                    "time_from": start_time,
                    "time_till": end_time,
                    "output": ["min", "max", "avg", "num"]
                }, auth_token)

                # If trend data exists, calculate properly
                if trends and len(trends) > 0:
                    min_val = convert_value(min(float(t["min"]) for t in trends), item_key, item_name)
                    max_val = convert_value(max(float(t["max"]) for t in trends), item_key, item_name)
                    
                    # Weighted average based on sample counts
                    total_sum = sum(convert_value(float(t["avg"]), item_key, item_name) * int(t["num"]) for t in trends)
                    total_count = sum(int(t["num"]) for t in trends)
                    avg_val = total_sum / total_count if total_count > 0 else 0
                    
                    writer.writerow([
                        item_name, 
                        format_value(min_val, item_key), 
                        format_value(max_val, item_key), 
                        format_value(avg_val, item_key), 
                        len(trends), 
                        groups_str,
                        unit_label
                    ])
                    has_data = True
                    print(f"[TRENDS] {host_name} - {item_name}: min={min_val:.2f}, max={max_val:.2f}, avg={avg_val:.2f}")
                    continue
                else:
                    print(f"[WARNING] No trends data for {host_name} - {item_name}, falling back to history")
                    
            except Exception as e:
                print(f"[ERROR] Processing trends for {host_name} - {item_name}: {e}")

            # Fallback to raw history when trends are unavailable
            try:
                # Determine correct history type
                history_type = 0 if value_type == 0 else 3
                history = zabbix_api("history.get", {
                    "itemids": item_id,
                    "time_from": start_time,
                    "time_till": end_time,
                    "output": "extend",
                    "history": history_type,
                    "sortfield": "clock",
                    "sortorder": "ASC",
                    "limit": 10000
                }, auth_token)

                if not history:
                    continue

                # Convert raw values
                values = [convert_value(h["value"], item_key, item_name) for h in history]
                min_val = min(values)
                max_val = max(values)
                avg_val = sum(values) / len(values)
                
                writer.writerow([
                    item_name, 
                    format_value(min_val, item_key), 
                    format_value(max_val, item_key), 
                    format_value(avg_val, item_key), 
                    len(values), 
                    groups_str,
                    unit_label
                ])
                has_data = True
                print(f"[HISTORY] {host_name} - {item_name}: min={min_val:.2f}, max={max_val:.2f}, avg={avg_val:.2f}")
                
            except Exception as e:
                print(f"[ERROR] Processing history for {host_name} - {item_name}: {e}")
                continue

        # Upload CSV to Azure Blob Storage
        if has_data:
            blob_client = container_client.get_blob_client(f"{host_name}.csv")
            blob_client.upload_blob(output.getvalue(), overwrite=True)
            hosts_with_data += 1
        
        hosts_processed += 1

    # Save host group mapping into JSON for additional reference
    groups_info = {
        'groups': {
            gid: {'name': data['name'], 'hosts': data['hosts']} 
            for gid, data in hostgroup_data.items()
        },
        'host_to_groups': host_to_groups,
        'generation_date': datetime.datetime.now().isoformat()
    }
    
    groups_blob = container_client.get_blob_client("_hostgroups_info.json")
    groups_blob.upload_blob(json.dumps(groups_info, indent=2), overwrite=True)
    print("Host groups info saved")

    print(f"\nHosts processed: {hosts_processed}, Hosts with data: {hosts_with_data}")

if __name__ == "__main__":
    export_metrics()
