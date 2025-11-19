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

# Color styles used throughout the Excel workbook
HEADER_FILL = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
CPU_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
MEM_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GROUP_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")


def generate_excel():
    """
    Main function responsible for:
    - Connecting to Azure Blob Storage
    - Downloading CSV metric files
    - Loading optional host group information
    - Creating an Excel workbook containing:
        * A summary sheet (Dashboard)
        * A global sheet with all hosts and metrics
        * A sheet grouped by host groups
    - Uploading the final Excel report back to Azure Blob Storage
    """

    # Retrieve Azure connection string
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connect_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")

    # Initialize blob client
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_name = "metrics"
    container_client = blob_service_client.get_container_client(container_name)

    # Create container if not exists
    try:
        container_client.create_container()
    except:
        pass  # Ignore if container already exists

    # Attempt to load host groups information (if exists)
    try:
        groups_blob = container_client.get_blob_client("_hostgroups_info.json")
        groups_info = json.loads(groups_blob.download_blob().content_as_text())
        host_to_groups = groups_info.get('host_to_groups', {})
        groups_data = groups_info.get('groups', {})
    except:
        print("No host groups info found, continuing without group data")
        host_to_groups = {}
        groups_data = {}

    host_count = 0
    csv_data = {}
    
    # Download all CSV metric files (only CSVs not starting with "_")
    for blob in container_client.list_blobs():
        if blob.name.endswith(".csv") and not blob.name.startswith("_"):
            blob_client = container_client.get_blob_client(blob.name)
            stream = io.StringIO(blob_client.download_blob().content_as_text())
            csv_data[blob.name] = pd.read_csv(stream)
            host_count += 1

    # =====================================================================
    # Create Excel workbook
    # =====================================================================
    wb = Workbook()
    ws_all = wb.active
    ws_all.title = "All Hosts"

    # Column headers for the main sheet
    headers = ["Host", "Metric", "Min", "Max", "Avg", "Unit", "Samples", "Groups"]
    ws_all.append(headers)

    # Apply header styling
    for col in range(1, len(headers) + 1):
        cell = ws_all.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    row_count = 2
    group_metrics = {}   # Dictionary storing all metrics grouped by host group

    # =====================================================================
    # Populate "All Hosts" sheet and build per-group metric dictionary
    # =====================================================================
    for csv_name, df in csv_data.items():
        host_name = csv_name.replace(".csv", "")
        groups_str = ";".join(host_to_groups.get(host_name, ["Unknown"]))
        
        for _, row in df.iterrows():
            unit = row.get('Unit', '')

            # Append full metric row
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

            # Collect this metric under each group the host belongs to
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
            
            # Highlight CPU metrics
            metric_lower = row['Metric'].lower()
            if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                metric_cell.fill = CPU_FILL
            
            # Highlight memory metrics
            elif 'mem' in metric_lower and ('utilization' in metric_lower or 'pavailable' in metric_lower):
                metric_cell.fill = MEM_FILL
            
            row_count += 1

    # =====================================================================
    # DASHBOARD SHEET
    # =====================================================================
    ws_dashboard = wb.create_sheet("Dashboard", 0)

    # Title and timestamp
    ws_dashboard['B2'] = "ZABBIX MONITORING REPORT"
    ws_dashboard['B2'].font = Font(size=16, bold=True, color="2E75B6")
    ws_dashboard.merge_cells('B2:G2')

    ws_dashboard['B3'] = f"Generated: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws_dashboard['B3'].font = Font(size=10, italic=True)

    # Statistics summary
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

    # =====================================================================
    # HOST GROUPS SUMMARY TABLE + CHARTS
    # =====================================================================
    groups_chart_row = row_start + len(stats) + 2

    # Compute statistics per host group
    group_stats = []
    for group_name, hosts_data in sorted(group_metrics.items()):
        total_hosts = len(hosts_data)
        
        cpu_values = []
        mem_values = []
        
        # Aggregate CPU/memory averages
        for host_name, metrics in hosts_data.items():
            for metric in metrics:
                metric_lower = metric['metric'].lower()
                try:
                    avg_val = float(metric['avg'])
                    if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                        cpu_values.append(avg_val)
                    elif 'mem' in metric_lower and ('utilization' in metric_lower or 'pavailable' in metric_lower):
                        mem_values.append(avg_val)
                except:
                    pass
        
        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
        avg_mem = sum(mem_values) / len(mem_values) if mem_values else 0
        group_stats.append((group_name, total_hosts, avg_cpu, avg_mem))

    # Draw summary table and charts if groups found
    if group_stats:
        ws_dashboard.cell(groups_chart_row, 2, "METRICS BY HOST GROUP").font = Font(bold=True, size=13, color="4472C4")
        ws_dashboard.merge_cells(f'B{groups_chart_row}:H{groups_chart_row}')
        groups_chart_row += 2

        headers = ["Host Group", "Total Hosts", "Avg CPU %", "Avg Memory %"]
        for j, header in enumerate(headers, start=2):
            cell = ws_dashboard.cell(groups_chart_row, j, header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT

        groups_data_start = groups_chart_row + 1
        for i, (group_name, hosts, avg_cpu, avg_mem) in enumerate(group_stats, start=groups_data_start):
            ws_dashboard.cell(i, 2, group_name)
            ws_dashboard.cell(i, 3, hosts)
            ws_dashboard.cell(i, 4, avg_cpu).number_format = '0.00'
            ws_dashboard.cell(i, 5, avg_mem).number_format = '0.00'

        groups_data_end = groups_data_start + len(group_stats) - 1

        # CPU chart
        cpu_group_chart = BarChart()
        cpu_group_chart.title = "Average CPU by Host Group"
        cpu_group_chart.y_axis.title = "CPU Avg (%)"
        cpu_group_chart.x_axis.title = "Host Group"
        cpu_group_chart.add_data(Reference(ws_dashboard, min_col=4, min_row=groups_data_start, max_row=groups_data_end))
        cpu_group_chart.set_categories(Reference(ws_dashboard, min_col=2, min_row=groups_data_start, max_row=groups_data_end))
        cpu_group_chart.height = 10
        cpu_group_chart.width = 15
        cpu_group_chart.legend = None
        ws_dashboard.add_chart(cpu_group_chart, f"J{groups_data_start - 1}")

        # Memory chart
        mem_group_chart = BarChart()
        mem_group_chart.title = "Average Memory by Host Group"
        mem_group_chart.y_axis.title = "Memory Avg (%)"
        mem_group_chart.x_axis.title = "Host Group"
        mem_group_chart.add_data(Reference(ws_dashboard, min_col=5, min_row=groups_data_start, max_row=groups_data_end))
        mem_group_chart.set_categories(Reference(ws_dashboard, min_col=2, min_row=groups_data_start, max_row=groups_data_end))
        mem_group_chart.height = 10
        mem_group_chart.width = 15
        mem_group_chart.legend = None
        ws_dashboard.add_chart(mem_group_chart, f"T{groups_data_start - 1}")

    # =====================================================================
    # BY HOST GROUPS SHEET
    # =====================================================================
    ws_groups = wb.create_sheet("By Host Groups", 1)
    ws_groups['B2'] = "METRICS BY HOST GROUP"
    ws_groups['B2'].font = Font(size=14, bold=True, color="4472C4")
    ws_groups.merge_cells('B2:J2')
    
    group_row = 4

    # One section per host group
    for group_name, hosts_data in sorted(group_metrics.items()):

        # Group title row
        ws_groups.cell(group_row, 2, f"{group_name}")
        ws_groups.cell(group_row, 2).fill = GROUP_HEADER_FILL
        ws_groups.cell(group_row, 2).font = Font(color="FFFFFF", bold=True, size=12)
        ws_groups.merge_cells(f'B{group_row}:I{group_row}')
        group_row += 1
        
        # Summary of each group
        total_metrics = sum(len(metrics) for metrics in hosts_data.values())
        ws_groups.cell(group_row, 2, "Total Hosts:").font = Font(bold=True)
        ws_groups.cell(group_row, 4, len(hosts_data))
        ws_groups.cell(group_row, 5, "Total Metrics:").font = Font(bold=True)
        ws_groups.cell(group_row, 7, total_metrics)
        group_row += 2
        
        # Table headers
        metric_headers = ["Host", "Metric", "Min", "Max", "Avg", "Unit", "Samples"]
        for col_idx, header in enumerate(metric_headers, start=2):
            cell = ws_groups.cell(group_row, col_idx, header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
        group_row += 1
        
        # Insert all metrics for the group
        for host_name in sorted(hosts_data.keys()):
            for metric in hosts_data[host_name]:
                ws_groups.cell(group_row, 2, host_name)
                metric_cell = ws_groups.cell(group_row, 3, metric['metric'])
                ws_groups.cell(group_row, 4, metric['min'])
                ws_groups.cell(group_row, 5, metric['max'])
                ws_groups.cell(group_row, 6, metric['avg'])
                ws_groups.cell(group_row, 7, metric['unit'])
                ws_groups.cell(group_row, 8, metric['samples'])
                
                # Apply color coding according to metric type
                metric_lower = metric['metric'].lower()
                if 'cpu' in metric_lower and ('util' in metric_lower or 'usage' in metric_lower):
                    metric_cell.fill = CPU_FILL
                elif 'mem' in metric_lower and ('utilization' in metric_lower or 'pavailable' in metric_lower):
                    metric_cell.fill = MEM_FILL
                
                group_row += 1
        
        group_row += 2  # Blank space between groups

    # =====================================================================
    # SAVE AND UPLOAD FINAL EXCEL REPORT
    # =====================================================================
    excel_output = io.BytesIO()
    wb.save(excel_output)

    filename = f"Zabbix_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    excel_blob_client = container_client.get_blob_client(filename)
    excel_blob_client.upload_blob(excel_output.getvalue(), overwrite=True)

    print(f"Excel '{filename}' uploaded with Dashboard, Groups analysis and individual host sheets")


if __name__ == "__main__":
    generate_excel()
