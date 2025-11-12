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

# Colors
HEADER_FILL = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
CPU_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
MEM_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
GROUP_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")


def generate_excel():
    # Blob connection
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connect_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not configured")
    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_name = "metrics"
    container_client = blob_service_client.get_container_client(container_name)

    try:
        container_client.create_container()
    except:
        pass

    # Load host groups info
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
    
    # Download CSVs
    for blob in container_client.list_blobs():
        if blob.name.endswith(".csv") and not blob.name.startswith("_"):
            blob_client = container_client.get_blob_client(blob.name)
            stream = io.StringIO(blob_client.download_blob().content_as_text())
            csv_data[blob.name] = pd.read_csv(stream)
            host_count += 1

    # Create Excel
    wb = Workbook()
    ws_all = wb.active
    ws_all.title = "All Hosts"
    headers = ["Host", "Metric", "Min", "Max", "Avg", "Samples", "Groups"]
    ws_all.append(headers)

    for col in range(1, len(headers)+1):
        cell = ws_all.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    row_count = 2
    cpu_data = []
    mem_data = []
    
    # Data by group
    group_metrics = {}

    # Fill main sheet and collect metrics
    for csv_name, df in csv_data.items():
        host_name = csv_name.replace(".csv", "")
        groups_str = ";".join(host_to_groups.get(host_name, ["Unknown"]))
        
        for _, row in df.iterrows():
            ws_all.append([
                host_name,
                row['Metric'],
                row['Min'],
                row['Max'],
                row['Avg'],
                row['Samples'],
                groups_str
            ])
            metric_cell = ws_all.cell(row_count, 2)
            
            # Collect data by group
            for group in host_to_groups.get(host_name, ["Unknown"]):
                if group not in group_metrics:
                    group_metrics[group] = {'cpu': [], 'mem': [], 'hosts': set()}
                group_metrics[group]['hosts'].add(host_name)
            
            if 'cpu' in row['Metric'].lower():
                metric_cell.fill = CPU_FILL
                cpu_data.append((host_name, row['Avg'], groups_str))
                for group in host_to_groups.get(host_name, ["Unknown"]):
                    group_metrics[group]['cpu'].append((host_name, row['Avg']))
                    
            elif 'mem' in row['Metric'].lower():
                metric_cell.fill = MEM_FILL
                mem_data.append((host_name, row['Avg'], groups_str))
                for group in host_to_groups.get(host_name, ["Unknown"]):
                    group_metrics[group]['mem'].append((host_name, row['Avg']))
            row_count += 1

    # Main dashboard
    ws_dashboard = wb.create_sheet("Dashboard", 0)
    ws_dashboard['B2'] = "ZABBIX MONITORING REPORT"
    ws_dashboard['B2'].font = Font(size=16, bold=True, color="2E75B6")
    ws_dashboard.merge_cells('B2:G2')
    ws_dashboard['B3'] = f"Generated: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws_dashboard['B3'].font = Font(size=10, italic=True)

    stats = [
        ["Total Hosts", host_count],
        ["Total Metrics", row_count-2],
        ["Total Host Groups", len(group_metrics)],
        ["Period", "Last 30 days"]
    ]
    
    row_start = 5
    for i, row in enumerate(stats, start=row_start):
        cell_label = ws_dashboard.cell(i, 2, row[0])
        cell_value = ws_dashboard.cell(i, 3, row[1])
        cell_label.font = Font(bold=True)
        cell_value.font = Font(size=11)

    # Top 10 CPU
    current_row = row_start + len(stats) + 2
    ws_dashboard.cell(current_row, 2, "Top 10 CPU Avg").font = Font(bold=True, size=12)
    ws_dashboard.cell(current_row, 2).fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    
    cpu_data_sorted = sorted(cpu_data, key=lambda x: x[1], reverse=True)[:10]
    cpu_start_row = current_row + 1
    
    for i, (host, avg, groups) in enumerate(cpu_data_sorted, start=cpu_start_row):
        ws_dashboard.cell(i, 2, host)
        cell = ws_dashboard.cell(i, 3, avg)
        cell.number_format = '0.00'
        ws_dashboard.cell(i, 4, groups).font = Font(size=8, italic=True)
        
        if avg > 80:
            cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)
        elif avg > 60:
            cell.fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")

    # Top 10 Memory
    ws_dashboard.cell(current_row, 6, "Top 10 Memory Avg").font = Font(bold=True, size=12)
    ws_dashboard.cell(current_row, 6).fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    
    mem_data_sorted = sorted(mem_data, key=lambda x: x[1], reverse=True)[:10]
    mem_start_row = current_row + 1
    
    for i, (host, avg, groups) in enumerate(mem_data_sorted, start=mem_start_row):
        ws_dashboard.cell(i, 6, host)
        cell = ws_dashboard.cell(i, 7, avg)
        cell.number_format = '0.00'
        ws_dashboard.cell(i, 8, groups).font = Font(size=8, italic=True)
        
        if avg > 80:
            cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)
        elif avg > 60:
            cell.fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")

    # Top 10 CPU Chart
    cpu_chart = BarChart()
    cpu_chart.title = "Top 10 CPU Usage (%)"
    cpu_chart.y_axis.title = "CPU Avg (%)"
    cpu_chart.x_axis.title = "Host"
    cpu_values = Reference(ws_dashboard, min_col=3, min_row=cpu_start_row, max_row=cpu_start_row+9)
    cpu_categories = Reference(ws_dashboard, min_col=2, min_row=cpu_start_row, max_row=cpu_start_row+9)
    cpu_chart.add_data(cpu_values, titles_from_data=False)
    cpu_chart.set_categories(cpu_categories)
    cpu_chart.height = 10
    cpu_chart.width = 15
    cpu_chart.legend = None
    ws_dashboard.add_chart(cpu_chart, f"I{cpu_start_row - 2}")

    # Top 10 Memory Chart (placed just below CPU chart dynamically)
    mem_chart = BarChart()
    mem_chart.title = "Top 10 Memory Usage (%)"
    mem_chart.y_axis.title = "Memory Avg (%)"
    mem_chart.x_axis.title = "Host"
    mem_values = Reference(ws_dashboard, min_col=7, min_row=mem_start_row, max_row=mem_start_row+9)
    mem_categories = Reference(ws_dashboard, min_col=6, min_row=mem_start_row, max_row=mem_start_row+9)
    mem_chart.add_data(mem_values, titles_from_data=False)
    mem_chart.set_categories(mem_categories)
    mem_chart.height = 10
    mem_chart.width = 15
    mem_chart.legend = None
    ws_dashboard.add_chart(mem_chart, f"T{cpu_start_row - 2}")  # adds space dynamically

    # HOST GROUPS CHARTS IN DASHBOARD
    groups_chart_row = max(cpu_start_row + 20, mem_start_row + 20)

    # Prepare data for host groups charts
    group_stats = []
    for group_name, metrics in sorted(group_metrics.items()):
        avg_cpu = sum(avg for _, avg in metrics['cpu']) / len(metrics['cpu']) if metrics['cpu'] else 0
        avg_mem = sum(avg for _, avg in metrics['mem']) / len(metrics['mem']) if metrics['mem'] else 0
        group_stats.append((group_name, len(metrics['hosts']), avg_cpu, avg_mem))

    if group_stats:
        ws_dashboard.cell(groups_chart_row, 2, "METRICS BY HOST GROUP").font = Font(bold=True, size=13, color="4472C4")
        ws_dashboard.merge_cells(f'B{groups_chart_row}:H{groups_chart_row}')
        groups_chart_row += 2

        # Headers
        headers = ["Host Group", "Total Hosts", "Avg CPU %", "Avg Memory %"]
        for j, header in enumerate(headers, start=2):
            ws_dashboard.cell(groups_chart_row, j, header)
            ws_dashboard.cell(groups_chart_row, j).fill = HEADER_FILL
            ws_dashboard.cell(groups_chart_row, j).font = HEADER_FONT

        groups_data_start = groups_chart_row + 1
        for i, (group_name, hosts, avg_cpu, avg_mem) in enumerate(group_stats, start=groups_data_start):
            ws_dashboard.cell(i, 2, group_name)
            ws_dashboard.cell(i, 3, hosts)
            ws_dashboard.cell(i, 4, avg_cpu).number_format = '0.00'
            ws_dashboard.cell(i, 5, avg_mem).number_format = '0.00'
        groups_data_end = groups_data_start + len(group_stats) - 1

        # Charts side by side, no overlap
        cpu_group_chart = BarChart()
        cpu_group_chart.title = "Average CPU by Host Group"
        cpu_group_chart.y_axis.title = "CPU Avg (%)"
        cpu_group_chart.x_axis.title = "Host Group"
        cpu_group_values = Reference(ws_dashboard, min_col=4, min_row=groups_data_start, max_row=groups_data_end)
        cpu_group_cats = Reference(ws_dashboard, min_col=2, min_row=groups_data_start, max_row=groups_data_end)
        cpu_group_chart.add_data(cpu_group_values)
        cpu_group_chart.set_categories(cpu_group_cats)
        cpu_group_chart.height = 10
        cpu_group_chart.width = 15
        ws_dashboard.add_chart(cpu_group_chart, f"I{groups_data_start - 1}")

        mem_group_chart = BarChart()
        mem_group_chart.title = "Average Memory by Host Group"
        mem_group_chart.y_axis.title = "Memory Avg (%)"
        mem_group_chart.x_axis.title = "Host Group"
        mem_group_values = Reference(ws_dashboard, min_col=5, min_row=groups_data_start, max_row=groups_data_end)
        mem_group_cats = Reference(ws_dashboard, min_col=2, min_row=groups_data_start, max_row=groups_data_end)
        mem_group_chart.add_data(mem_group_values)
        mem_group_chart.set_categories(mem_group_cats)
        mem_group_chart.height = 10
        mem_group_chart.width = 15
        ws_dashboard.add_chart(mem_group_chart, f"T{groups_data_start - 1}")


    # 📊 Create summary by group sheet
    ws_groups = wb.create_sheet("By Host Groups", 1)
    ws_groups['B2'] = "METRICS BY HOST GROUP"
    ws_groups['B2'].font = Font(size=14, bold=True, color="4472C4")
    ws_groups.merge_cells('B2:H2')
    
    group_row = 4
    for group_name, metrics in sorted(group_metrics.items()):
        # Group header
        ws_groups.cell(group_row, 2, f"{group_name}").font = Font(bold=True, size=12)
        ws_groups.cell(group_row, 2).fill = GROUP_HEADER_FILL
        ws_groups.cell(group_row, 2).font = Font(color="FFFFFF", bold=True, size=12)
        ws_groups.merge_cells(f'B{group_row}:H{group_row}')
        group_row += 1
        
        # Stats
        ws_groups.cell(group_row, 2, "Total Hosts:").font = Font(bold=True)
        ws_groups.cell(group_row, 3, len(metrics['hosts']))
        ws_groups.cell(group_row, 4, "CPU Metrics:").font = Font(bold=True)
        ws_groups.cell(group_row, 5, len(metrics['cpu']))
        ws_groups.cell(group_row, 6, "Memory Metrics:").font = Font(bold=True)
        ws_groups.cell(group_row, 7, len(metrics['mem']))
        group_row += 1
        
        # Top 5 CPU in group - Header
        ws_groups.cell(group_row, 2, "Top 5 CPU").font = Font(bold=True, size=10)
        
        # Top 5 Memory in group - Header (SAME ROW)
        ws_groups.cell(group_row, 5, "Top 5 Memory").font = Font(bold=True, size=10)
        group_row += 1
        
        cpu_start_row = group_row
        mem_start_row = group_row  # SAME ROW
        
        # Top 5 CPU data
        if metrics['cpu']:
            top_cpu = sorted(metrics['cpu'], key=lambda x: x[1], reverse=True)[:5]
            for idx, (host, avg) in enumerate(top_cpu):
                current_row = cpu_start_row + idx
                ws_groups.cell(current_row, 2, host)
                cell = ws_groups.cell(current_row, 3, avg)
                cell.number_format = '0.00'
                if avg > 80:
                    cell.fill = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")
                elif avg > 60:
                    cell.fill = PatternFill(start_color="FFD93D", end_color="FFD93D", fill_type="solid")
        
        # Top 5 Memory data (ALIGNED)
        if metrics['mem']:
            top_mem = sorted(metrics['mem'], key=lambda x: x[1], reverse=True)[:5]
            for idx, (host, avg) in enumerate(top_mem):
                current_row = mem_start_row + idx
                ws_groups.cell(current_row, 5, host)
                cell = ws_groups.cell(current_row, 6, avg)
                cell.number_format = '0.00'
                if avg > 80:
                    cell.fill = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")
                elif avg > 60:
                    cell.fill = PatternFill(start_color="FFD93D", end_color="FFD93D", fill_type="solid")
        
        # Move to next group (after the longest list)
        max_items = max(len(metrics['cpu']), len(metrics['mem']), 5)
        group_row = cpu_start_row + min(max_items, 3) + 2


    # Create one sheet per host with charts
    for csv_name, df in csv_data.items():
        host_name = csv_name.replace(".csv", "")
        ws_host = wb.create_sheet(title=host_name[:30])
        ws_host.append(df.columns.tolist())
        for _, r in df.iterrows():
            ws_host.append(r.tolist())

        # Apply header styles
        for col in range(1, len(df.columns)+1):
            cell = ws_host.cell(1, col)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")

        # CPU Chart
        cpu_rows = df[df['Metric'].str.contains('cpu', case=False)]
        if not cpu_rows.empty:
            chart = LineChart()
            chart.title = f"CPU Metrics - {host_name}"
            chart.y_axis.title = "Value (%)"
            chart.x_axis.title = "Metric"
            data_col = df.columns.get_loc('Avg') + 1
            data = Reference(ws_host, min_col=data_col, min_row=2, max_row=ws_host.max_row)
            cats = Reference(ws_host, min_col=1, min_row=2, max_row=ws_host.max_row)
            chart.add_data(data, titles_from_data=False)
            chart.set_categories(cats)
            chart.height = 12
            chart.width = 20
            chart.legend = None
            ws_host.add_chart(chart, "H2")

        # Memory Chart
        mem_rows = df[df['Metric'].str.contains('mem', case=False)]
        if not mem_rows.empty:
            chart = LineChart()
            chart.title = f"Memory Metrics - {host_name}"
            chart.y_axis.title = "Value"
            chart.x_axis.title = "Metric"
            data_col = df.columns.get_loc('Avg') + 1
            data = Reference(ws_host, min_col=data_col, min_row=2, max_row=ws_host.max_row)
            cats = Reference(ws_host, min_col=1, min_row=2, max_row=ws_host.max_row)
            chart.add_data(data, titles_from_data=False)
            chart.set_categories(cats)
            chart.height = 12
            chart.width = 20
            chart.legend = None
            ws_host.add_chart(chart, "H22")

    # Save and upload
    excel_output = io.BytesIO()
    wb.save(excel_output)
    filename = f"Zabbix_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    excel_blob_client = container_client.get_blob_client(filename)
    excel_blob_client.upload_blob(excel_output.getvalue(), overwrite=True)

    print(f"Excel '{filename}' uploaded with Dashboard, Groups analysis and individual host sheets")


if __name__ == "__main__":
    generate_excel()