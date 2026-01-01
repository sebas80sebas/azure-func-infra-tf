import datetime
import io
import os
import json
import pandas as pd
from azure.storage.blob import BlobServiceClient
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.utils.dataframe import dataframe_to_rows

# --- Excel Style Definitions ---
# Color styles used throughout the Excel workbook for headers and metric highlighting
HEADER_FILL = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
FILL = PatternFill(start_color="a4f114", end_color="a4f114", fill_type="solid") # Light red for CPU metrics
GROUP_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid") # Blue for Group headers


def generate_excel(container_name):
    """
    Main function responsible for:
    1. Connecting to Azure Blob Storage and setting up the container.
    2. Downloading host group information (optional JSON file).
    3. Downloading and processing all CSV metric files into a consolidated structure.
    4. Creating an Excel workbook with two sheets:
        a) Dashboard: Summary statistics and detailed host group metrics (starting at column I).
        b) All Hosts: Raw, consolidated metrics from all hosts.
    5. Styling and formatting the data in the Excel sheets.
    6. Uploading the final Excel report back to Azure Blob Storage.
    """

    # --- Azure Connection and Setup ---
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connect_str:
        # Stop execution if connection string is missing
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")

    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service_client.get_container_client(container_name)

    # Attempt to create container (it will pass if container already exists)
    try:
        container_client.create_container()
    except:
        pass

    # --- Load Host Group Information (Optional) ---
    try:
        groups_blob = container_client.get_blob_client("_hostgroups_info.json")
        groups_info = json.loads(groups_blob.download_blob().content_as_text())
        host_to_groups = groups_info.get('host_to_groups', {})
        groups_data = groups_info.get('groups', {})
    except:
        # If the groups file is not found or fails to load, proceed without group data
        print("No host groups info found, continuing without group data")
        host_to_groups = {}
        groups_data = {}

    # --- Download and Process CSV Metric Files ---
    host_count = 0
    csv_data = {}

    for blob in container_client.list_blobs():
        # Only process files ending with .csv and not starting with '_'
        if blob.name.endswith(".csv") and not blob.name.startswith("_"):
            blob_client = container_client.get_blob_client(blob.name)
            # Download and read CSV content directly into a pandas DataFrame
            stream = io.StringIO(blob_client.download_blob().content_as_text())
            csv_data[blob.name] = pd.read_csv(stream)
            host_count += 1

    # --- Create Workbook and "All Hosts" Sheet ---
    wb = Workbook()
    ws_all = wb.active # Get the default sheet
    ws_all.title = "All Hosts"

    headers = ["Host", "Metric", "Min", "Max", "Avg", "Unit", "Samples", "Groups"]
    ws_all.append(headers)

    # Apply styling to the header row
    for col in range(1, len(headers) + 1):
        cell = ws_all.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    row_count = 2
    group_metrics = {} # Dictionary to aggregate metrics by host group

    # Populate "All Hosts" sheet and aggregate group metrics
    for csv_name, df in csv_data.items():
        host_name = csv_name.replace(".csv", "")
        groups_str = ";".join(host_to_groups.get(host_name, ["Unknown"]))

        for _, row in df.iterrows():
            unit = row.get('Unit', '')

            # Append metric data to "All Hosts" sheet
            ws_all.append([
                host_name,
                row['Metric'],
                row['Min'],
                row['Max'],
                row['Avg'],
                unit,
                row['Samples'],
                groups_str
            ])

            metric_cell = ws_all.cell(row_count, 2)

            # Aggregate data for the Group Metrics structure
            for group in host_to_groups.get(host_name, ["Unknown"]):
                group_metrics.setdefault(group, {})
                group_metrics[group].setdefault(host_name, [])
                group_metrics[group][host_name].append({
                    'metric': row['Metric'],
                    'min': row['Min'],
                    'max': row['Max'],
                    'avg': row['Avg'],
                    'unit': unit,
                    'samples': row['Samples']
                })


            row_count += 1

    # --- Create "Dashboard" Sheet ---
    ws_dashboard = wb.create_sheet("Dashboard", 0)

    # --- General Report Section (Columns B to F) ---
    ws_dashboard['B2'] = "ZABBIX MONITORING REPORT"
    ws_dashboard['B2'].font = Font(size=16, bold=True, color="2E75B6")
    ws_dashboard.merge_cells('B2:F2')

    ws_dashboard['B3'] = f"Generated: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws_dashboard['B3'].font = Font(size=10, italic=True)

    # Summary Statistics
    stats = [
        ["Total Hosts", host_count],
        ["Total Metrics", row_count - 2],
        ["Total Host Groups", len(group_metrics)],
        ["Period", "Last 30 days"]
    ]

    row_start = 5
    for i, row in enumerate(stats, start=row_start):
        ws_dashboard.cell(i, 2, row[0]).font = Font(bold=True)
        ws_dashboard.cell(i, 4, row[1]).font = Font(size=11)

    # Calculate Global Average CPU and Memory
    global_cpu_values = []
    global_mem_values = []

    for df in csv_data.values():
        for _, row in df.iterrows():
            metric_lower = row['Metric'].lower()
            try:
                val = float(row['Avg'])
                if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                    global_cpu_values.append(val)
                elif 'mem' in metric_lower and ('utilization' in metric_lower or 'pavailable' in metric_lower):
                    global_mem_values.append(val)
            except:
                pass # Ignore non-numeric 'Avg' values

    global_avg_cpu = sum(global_cpu_values) / len(global_cpu_values) if global_cpu_values else 0
    global_avg_mem = sum(global_mem_values) / len(global_mem_values) if global_mem_values else 0

    # Display Global Averages
    ws_dashboard.cell(row_start + len(stats) + 1, 2, "Global CPU Avg (%)").font = Font(bold=True)
    ws_dashboard.cell(row_start + len(stats) + 1, 4, global_avg_cpu).number_format = '0.00'

    ws_dashboard.cell(row_start + len(stats) + 2, 2, "Global Memory Avg (%)").font = Font(bold=True)
    ws_dashboard.cell(row_start + len(stats) + 2, 4, global_avg_mem).number_format = '0.00'

    groups_chart_row = row_start + len(stats) + 5

    # Prepare Group Summary Statistics
    group_stats = []
    for group_name, hosts_data in sorted(group_metrics.items()):
        total_hosts = len(hosts_data)
        cpu_values = []
        mem_values = []

        for metrics in hosts_data.values():
            for metric in metrics:
                metric_lower = metric['metric'].lower()
                try:
                    avg_val = float(metric['avg'])
                    if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                        cpu_values.append(avg_val)
                    elif 'mem' in metric_lower and ('used' in metric_lower or 'total' in metric_lower):
                        mem_values.append(avg_val)
                except:
                    pass

        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
        avg_mem = sum(mem_values) / len(mem_values) if mem_values else 0
        group_stats.append((group_name, total_hosts, avg_cpu, avg_mem))

    if group_stats:
        # Group Summary Table Title (Columns B-E)
        ws_dashboard.cell(groups_chart_row, 2, "METRICS BY HOST GROUP").font = Font(bold=True, size=13, color="4472C4")
        ws_dashboard.merge_cells(f'B{groups_chart_row}:E{groups_chart_row}')
        groups_chart_row += 2

        # Group Summary Table Headers (Columns B-E)
        headers = ["Host Group", "Total Hosts", "Avg CPU %", "Avg Memory %"]
        for j, header in enumerate(headers, start=2):
            cell = ws_dashboard.cell(groups_chart_row, j, header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT

        # Group Summary Table Data (Columns B-E)
        groups_data_start = groups_chart_row + 1
        for i, (group_name, hosts, avg_cpu, avg_mem) in enumerate(group_stats, start=groups_data_start):
            ws_dashboard.cell(i, 2, group_name)
            ws_dashboard.cell(i, 3, hosts)
            ws_dashboard.cell(i, 4, avg_cpu).number_format = '0.00'
            ws_dashboard.cell(i, 5, avg_mem).number_format = '0.00'


    # Group Metrics Section 
    group_col_start = 9 # Column I
    group_row = 2

    # Detailed Section Title (Starts at I2 and merges across 7 columns)
    ws_dashboard.cell(group_row, group_col_start, "DETAILED METRICS BY HOST GROUP")
    ws_dashboard.cell(group_row, group_col_start).font = Font(size=14, bold=True, color="4472C4")
    ws_dashboard.merge_cells(start_row=group_row, start_column=group_col_start, end_row=group_row, end_column=group_col_start + 6)
    group_row += 2

    # Loop through each aggregated group to display detailed data
    for group_name, hosts_data in sorted(group_metrics.items()):

        # Group Header
        ws_dashboard.cell(group_row, group_col_start, f"{group_name}")
        ws_dashboard.cell(group_row, group_col_start).fill = GROUP_HEADER_FILL
        ws_dashboard.cell(group_row, group_col_start).font = Font(color="FFFFFF", bold=True, size=12)
        ws_dashboard.merge_cells(start_row=group_row, start_column=group_col_start, end_row=group_row, end_column=group_col_start + 6)
        group_row += 1

        # Group Summary Info (Hosts and Total Metrics)
        total_metrics = sum(len(metrics) for metrics in hosts_data.values())
        ws_dashboard.cell(group_row, group_col_start, "Total Hosts:").font = Font(bold=True)
        ws_dashboard.cell(group_row, group_col_start + 2, len(hosts_data))
        ws_dashboard.cell(group_row, group_col_start + 4, "Total Metrics:").font = Font(bold=True)
        ws_dashboard.cell(group_row, group_col_start + 6, total_metrics)
        group_row += 2

        # Metric Table Headers
        metric_headers = ["Host", "Metric", "Min", "Max", "Avg", "Unit", "Samples"]
        for col_idx, header in enumerate(metric_headers, start=group_col_start):
            cell = ws_dashboard.cell(group_row, col_idx, header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
        group_row += 1

        # Metric Table Data (Host by Host)
        for host_name in sorted(hosts_data.keys()):
            for metric in hosts_data[host_name]:
                ws_dashboard.cell(group_row, group_col_start, host_name)
                metric_cell = ws_dashboard.cell(group_row, group_col_start + 1, metric['metric'])
                ws_dashboard.cell(group_row, group_col_start + 2, metric['min'])
                ws_dashboard.cell(group_row, group_col_start + 3, metric['max'])
                ws_dashboard.cell(group_row, group_col_start + 4, metric['avg'])
                ws_dashboard.cell(group_row, group_col_start + 5, metric['unit'])
                ws_dashboard.cell(group_row, group_col_start + 6, metric['samples'])

                # Apply conditional formatting based on metric type
                metric_lower = metric['metric'].lower()
                if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                    metric_cell.fill = FILL
                elif 'mem' in metric_lower and ('used' in metric_lower or 'total' in metric_lower):
                    metric_cell.fill = FILL

                group_row += 1

        group_row += 2 # Add space after each host group table

    # --- Save and Upload Excel File ---
    excel_output = io.BytesIO()
    wb.save(excel_output)

    # Define filename with timestamp
    filename = f"Zabbix_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    excel_blob_client = container_client.get_blob_client(filename)
    excel_blob_client.upload_blob(excel_output.getvalue(), overwrite=True)

    print(f"Excel '{filename}' uploaded successfully to container '{container_name}'.")


if __name__ == "__main__":


    CONTAINER_NAME = os.getenv("CONTAINER_NAME", "metrics")


    generate_excel(CONTAINER_NAME)

