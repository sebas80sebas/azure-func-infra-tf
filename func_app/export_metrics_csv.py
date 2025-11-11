import requests
import csv
import datetime
import io
import os
import json
from azure.storage.blob import BlobServiceClient

# Zabbix Configuration
ZABBIX_URL = os.getenv("ZABBIX_URL")
ZABBIX_USER = os.getenv("ZABBIX_USER")
ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD")

# Session with SSL verification
session = requests.Session()
session.verify = True

def zabbix_api(method, params, auth=None):
    headers = {"Content-Type": "application/json"}
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1, "auth": auth}
    response = session.post(ZABBIX_URL, headers=headers, json=payload)
    response.raise_for_status()
    result = response.json()
    
    if "error" in result:
        error_msg = result["error"].get("message", "Unknown error")
        error_data = result["error"].get("data", "")
        raise Exception(f"Zabbix error: {error_msg} - {error_data}")
    
    if "result" not in result:
        raise Exception(f"Unexpected response from Zabbix: {result}")
    
    return result["result"]

def export_metrics():
    # Blob Configuration
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connect_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")
    
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_name = "metrics"
    container_client = blob_service_client.get_container_client(container_name)

    # Create container if it doesn't exist
    if not container_client.exists():
        container_client.create_container()
        print(f"✅ Container '{container_name}' created")
    else:
        print(f"ℹ️ Container '{container_name}' already exists")

    print("Authenticating to Zabbix...")

    try:
        auth_token = zabbix_api("user.login", {"user": ZABBIX_USER, "password": ZABBIX_PASSWORD})
    except:
        auth_token = zabbix_api("user.login", {"username": ZABBIX_USER, "password": ZABBIX_PASSWORD})

    print("✅ Authentication successful")

    # Get Zabbix version
    version_info = zabbix_api("apiinfo.version", {})
    print(f"📊 Zabbix version: {version_info}")

    # Date range (last month)
    end_time = int(datetime.datetime.now().timestamp())
    start_time = int((datetime.datetime.now() - datetime.timedelta(days=30)).timestamp())

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

    # Get all host groups
    print("📁 Getting host groups...")
    host_groups = zabbix_api("hostgroup.get", {"output": ["groupid", "name"]}, auth_token)
    print(f"✅ Found {len(host_groups)} host groups")
    
    # Create mapping of host groups
    hostgroup_data = {}
    for group in host_groups:
        hostgroup_data[group['groupid']] = {
            'name': group['name'],
            'hosts': []
        }

    # Get hosts with their groups
    hosts = zabbix_api("host.get", {
        "output": ["hostid", "host", "name"],
        "selectGroups": ["groupid", "name"]
    }, auth_token)
    
    hosts_processed = 0
    hosts_with_data = 0
    host_to_groups = {}

    # Process each host
    for host in hosts:
        host_id = host["hostid"]
        host_name = host["host"]
        
        # Store host groups for this host
        host_to_groups[host_name] = [g['name'] for g in host.get('groups', [])]
        
        # Add host to each group
        for group in host.get('groups', []):
            if group['groupid'] in hostgroup_data:
                hostgroup_data[group['groupid']]['hosts'].append(host_name)

        items = zabbix_api("item.get", {
            "hostids": host_id,
            "output": ["itemid", "name", "key_", "value_type"],
            "filter": {"key_": TARGET_KEYS}
        }, auth_token)

        if not items:
            continue

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Metric", "Min", "Max", "Avg", "Samples", "Host_Groups"])
        has_data = False

        for item in items:
            item_id = item["itemid"]
            item_name = item["name"]
            value_type = int(item["value_type"])
            groups_str = ";".join(host_to_groups.get(host_name, []))

            try:
                trends = zabbix_api("trend.get", {
                    "itemids": item_id,
                    "time_from": start_time,
                    "time_till": end_time,
                    "output": ["min", "max", "avg", "num"]
                }, auth_token)

                if trends:
                    min_val = min(float(t["min"]) for t in trends)
                    max_val = max(float(t["max"]) for t in trends)
                    total_sum = sum(float(t["avg"]) * int(t["num"]) for t in trends)
                    total_count = sum(int(t["num"]) for t in trends)
                    avg_val = total_sum / total_count if total_count > 0 else 0
                    writer.writerow([item_name, f"{min_val:.2f}", f"{max_val:.2f}", f"{avg_val:.2f}", len(trends), groups_str])
                    has_data = True
                    continue
            except:
                pass

            try:
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

                values = [float(h["value"]) for h in history]
                min_val = min(values)
                max_val = max(values)
                avg_val = sum(values) / len(values)
                writer.writerow([item_name, f"{min_val:.2f}", f"{max_val:.2f}", f"{avg_val:.2f}", len(values), groups_str])
                has_data = True
            except:
                continue

        if has_data:
            blob_client = container_client.get_blob_client(f"{host_name}.csv")
            blob_client.upload_blob(output.getvalue(), overwrite=True)
            hosts_with_data += 1
        hosts_processed += 1

    # Save host groups information as JSON
    groups_info = {
        'groups': {gid: {'name': data['name'], 'hosts': data['hosts']} 
                   for gid, data in hostgroup_data.items()},
        'host_to_groups': host_to_groups,
        'generation_date': datetime.datetime.now().isoformat()
    }
    
    groups_blob = container_client.get_blob_client("_hostgroups_info.json")
    groups_blob.upload_blob(json.dumps(groups_info, indent=2), overwrite=True)
    print(f"✅ Host groups info saved")

    print(f"🎉 Hosts processed: {hosts_processed}, Hosts with data: {hosts_with_data}")