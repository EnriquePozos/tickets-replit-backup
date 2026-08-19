import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from dateutil import parser

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key_for_development")

# Google Sheets configuration
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
SHEET_NAME = "Datos2491_1"

def get_google_sheet():
    """Connect to Google Sheets and return the worksheet"""
    try:
        # Get credentials from environment variable
        creds_json = os.environ.get('GABRIEL_GOOGLE_CREDS')
        if not creds_json:
            logging.error("GABRIEL_GOOGLE_CREDS environment variable not found")
            return None
        
        # Parse the JSON credentials
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        
        # Connect to Google Sheets
        client = gspread.authorize(creds)
        
        # Get the spreadsheet (assumes the sheet URL or name is in environment)
        sheet_id = os.environ.get('GABRIEL_GOOGLE_SHEET_ID')
        if sheet_id:
            spreadsheet = client.open_by_key(sheet_id)
        else:
            # Fallback to opening by name if ID not provided
            sheet_name = os.environ.get('GABRIEL_GOOGLE_SHEET_NAME', 'Ticket Dashboard')
            spreadsheet = client.open(sheet_name)
        
        worksheet = spreadsheet.worksheet(SHEET_NAME)
        return worksheet
    except Exception as e:
        logging.error(f"Error connecting to Google Sheets: {str(e)}")
        return None

def get_dataframe():
    """Get data from Google Sheets and return as pandas DataFrame"""
    try:
        worksheet = get_google_sheet()
        if not worksheet:
            return pd.DataFrame()
        
        # Get all values and handle duplicate headers
        values = worksheet.get_all_values()
        if not values:
            return pd.DataFrame()
        
        # Get headers from first row and handle duplicates
        headers = values[0]
        cleaned_headers = []
        header_counts = {}
        
        for header in headers:
            if header == '':
                header = 'Empty_Column'
            
            if header in header_counts:
                header_counts[header] += 1
                cleaned_header = f"{header}_{header_counts[header]}"
            else:
                header_counts[header] = 0
                cleaned_header = header
            
            cleaned_headers.append(cleaned_header)
        
        # Create DataFrame with cleaned headers
        data_rows = values[1:]  # Skip header row
        df = pd.DataFrame(data_rows, columns=cleaned_headers)
        
        if df.empty:
            return df
        
        # Convert date columns
        date_columns = ['Creado el', 'Fecha de cierre']
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Create simplified column names for compatibility
        if 'Asignada a/Nombre (Spanish)' in df.columns:
            df['Asignada a'] = df['Asignada a/Nombre (Spanish)']
        if 'Nombre del cliente' in df.columns:
            df['Cliente'] = df['Nombre del cliente']
        if 'Incidencia/Nombre mostrado' in df.columns:
            df['Incidencia'] = df['Incidencia/Nombre mostrado']
        if 'Etapa/Nombre' in df.columns:
            df['Etapa'] = df['Etapa/Nombre']
        if 'Servicio Relacionado/Nombre mostrado' in df.columns:
            df['Servicio Rela'] = df['Servicio Relacionado/Nombre mostrado']
        if 'DUPLICADOS' in df.columns:
            df['Reincidente'] = df['DUPLICADOS'] == 'Repetido'
        
        # Set default priority if not present
        if 'Prioridad' not in df.columns:
            df['Prioridad'] = 'Medium'
        
        return df
    except Exception as e:
        logging.error(f"Error getting dataframe: {str(e)}")
        return pd.DataFrame()

def calculate_resolution_time(created_date, closed_date):
    """Calculate resolution time in hours"""
    try:
        if pd.isna(created_date) or pd.isna(closed_date):
            return None
        return (closed_date - created_date).total_seconds() / 3600
    except:
        return None

@app.route('/')
def dashboard():
    """Serve the main dashboard page"""
    return render_template('index.html')

@app.route('/analysis')
def analysis():
    """Serve the service analysis page"""
    return render_template('analysis.html')

@app.route('/tickets')
def tickets():
    """Serve the ticket search page"""
    return render_template('tickets.html')

@app.route('/api/kpis')
def get_kpis():
    """Get KPI data for the last 30 days"""
    try:
        df = get_dataframe()
        if df.empty:
            return jsonify({"error": "No data available"}), 404
        
        # Filter for last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        recent_df = df[df['Creado el'] >= thirty_days_ago]
        
        # Calculate KPIs
        total_tickets = len(recent_df)
        recurrent_tickets = len(recent_df[recent_df.get('Reincidente', False) == True])
        
        # Calculate average resolution time
        closed_tickets = recent_df[recent_df['Etapa'] == 'Closed']
        resolution_times = []
        if not closed_tickets.empty:
            for _, ticket in closed_tickets.iterrows():
                res_time = calculate_resolution_time(ticket['Creado el'], ticket['Fecha de cierre'])
                if res_time is not None:
                    resolution_times.append(res_time)
        
        avg_resolution_time = sum(resolution_times) / len(resolution_times) if resolution_times else 0
        
        # Calculate SLA compliance (assuming 24 hours SLA)
        sla_hours = 24
        sla_compliant = sum(1 for time in resolution_times if time <= sla_hours)
        sla_compliance = (sla_compliant / len(resolution_times) * 100) if resolution_times else 100
        
        return jsonify({
            "total": total_tickets,
            "recurrent": recurrent_tickets,
            "avg_time_hours": round(avg_resolution_time, 1),
            "sla_percent": round(sla_compliance, 1)
        })
    except Exception as e:
        logging.error(f"Error calculating KPIs: {str(e)}")
        return jsonify({"error": "Failed to calculate KPIs"}), 500

@app.route('/api/charts')
def get_chart_data():
    """Get chart data based on chart name"""
    try:
        chart_name = request.args.get('name')
        df = get_dataframe()
        
        if df.empty:
            return jsonify({"error": "No data available"}), 404
        
        if chart_name == 'monthly_evolution':
            # Group by month
            df['month'] = df['Creado el'].dt.to_period('M')
            monthly_counts = df.groupby('month').size()
            
            labels = [str(month) for month in monthly_counts.index]
            data = [int(x) for x in monthly_counts.values]  # Convert to native Python int
            
        elif chart_name == 'by_issue_type':
            # Group by issue type
            issue_counts = df['Incidencia'].value_counts()
            labels = issue_counts.index.tolist()
            data = [int(x) for x in issue_counts.values]  # Convert to native Python int
            
        elif chart_name == 'recurrent_distribution':
            # Count recurrent vs non-recurrent tickets
            recurrent_counts = df['Reincidente'].value_counts()
            labels = ['Non-Recurrent', 'Recurrent']
            data = [
                int(recurrent_counts.get(False, 0)),  # Convert to native Python int
                int(recurrent_counts.get(True, 0))   # Convert to native Python int
            ]
            
        else:
            return jsonify({"error": "Invalid chart name"}), 400
        
        return jsonify({
            "labels": labels,
            "data": data
        })
    except Exception as e:
        logging.error(f"Error getting chart data: {str(e)}")
        return jsonify({"error": "Failed to get chart data"}), 500

@app.route('/api/latest-tickets')
def get_latest_tickets():
    """Get the 10 most recent tickets"""
    try:
        df = get_dataframe()
        if df.empty:
            return jsonify([])
        
        # Sort by creation date and get top 10
        latest_df = df.sort_values('Creado el', ascending=False).head(10)
        
        # Convert to list of dictionaries using native Python types
        tickets = []
        if not latest_df.empty:
            # Convert DataFrame to dict records to ensure native Python types
            records = latest_df.to_dict(orient='records')
            for record in records:
                ticket = {
                    'id': str(record.get('ID', '')),
                    'subject': str(record.get('Asunto', '')),
                    'client': str(record.get('Cliente', '')),
                    'status': str(record.get('Etapa', '')),
                    'priority': str(record.get('Prioridad', 'Medium')),
                    'created': record['Creado el'].strftime('%Y-%m-%d %H:%M') if pd.notna(record['Creado el']) else '',
                    'assigned': str(record.get('Asignada a', ''))
                }
                tickets.append(ticket)
        
        return jsonify(tickets)
    except Exception as e:
        logging.error(f"Error getting latest tickets: {str(e)}")
        return jsonify({"error": "Failed to get latest tickets"}), 500

@app.route('/api/failure-analysis')
def get_failure_analysis():
    """Get failure analysis data filtered by client and service"""
    try:
        cliente = request.args.get('cliente')
        servicio = request.args.get('servicio')
        
        df = get_dataframe()
        if df.empty:
            return jsonify([])
        
        # Apply filters
        if cliente:
            df = df[df['Cliente'] == cliente]
        if servicio:
            df = df[df['Servicio Rela'] == servicio]
        
        # Convert to analysis format using native Python types
        analysis_data = []
        if not df.empty:
            # Convert DataFrame to dict records to ensure native Python types
            records = df.to_dict(orient='records')
            for record in records:
                data_point = {
                    'date': record['Creado el'].strftime('%Y-%m-%d') if pd.notna(record['Creado el']) else '',
                    'issue': str(record.get('Incidencia', '')),
                    'priority': str(record.get('Prioridad', '')),
                    'client': str(record.get('Cliente', '')),
                    'service': str(record.get('Servicio Rela', ''))
                }
                analysis_data.append(data_point)
        
        return jsonify(analysis_data)
    except Exception as e:
        logging.error(f"Error getting failure analysis: {str(e)}")
        return jsonify({"error": "Failed to get failure analysis"}), 500

@app.route('/api/search-tickets')
def search_tickets():
    """Search tickets with multiple filters"""
    try:
        df = get_dataframe()
        if df.empty:
            return jsonify([])
        
        # Get filter parameters
        status = request.args.get('status')
        priority = request.args.get('priority')
        client = request.args.get('client')
        service = request.args.get('service')
        assigned = request.args.get('assigned')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Apply filters
        if status:
            df = df[df['Etapa'] == status]
        if priority:
            df = df[df['Prioridad'] == priority]
        if client:
            df = df[df['Cliente'] == client]
        if service:
            df = df[df['Servicio Rela'] == service]
        if assigned:
            df = df[df['Asignada a'] == assigned]
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            df = df[df['Creado el'] >= start_dt]
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            df = df[df['Creado el'] <= end_dt]
        
        # Convert to list of dictionaries using native Python types
        tickets = []
        if not df.empty:
            # Convert DataFrame to dict records to ensure native Python types
            records = df.to_dict(orient='records')
            for record in records:
                ticket = {
                    'id': str(record.get('ID', '')),
                    'subject': str(record.get('Asunto', '')),
                    'client': str(record.get('Cliente', '')),
                    'service': str(record.get('Servicio Rela', '')),
                    'status': str(record.get('Etapa', '')),
                    'priority': str(record.get('Prioridad', 'Medium')),
                    'created': record['Creado el'].strftime('%Y-%m-%d %H:%M') if pd.notna(record['Creado el']) else '',
                    'closed': record['Fecha de cierre'].strftime('%Y-%m-%d %H:%M') if pd.notna(record['Fecha de cierre']) else '',
                    'assigned': str(record.get('Asignada a', '')),
                    'recurrent': bool(record.get('Reincidente', False))
                }
                tickets.append(ticket)
        
        return jsonify(tickets)
    except Exception as e:
        logging.error(f"Error searching tickets: {str(e)}")
        return jsonify({"error": "Failed to search tickets"}), 500

@app.route('/api/filter-options')
def get_filter_options():
    """Get unique values for filter dropdowns"""
    try:
        df = get_dataframe()
        if df.empty:
            return jsonify({})
        
        options = {
            'clients': [str(x) for x in sorted(df['Cliente'].dropna().unique().tolist())],
            'services': [str(x) for x in sorted(df['Servicio Rela'].dropna().unique().tolist())],
            'statuses': [str(x) for x in sorted(df['Etapa'].dropna().unique().tolist())],
            'priorities': [str(x) for x in sorted(df['Prioridad'].dropna().unique().tolist())],
            'assigned': [str(x) for x in sorted(df['Asignada a'].dropna().unique().tolist())]
        }
        
        return jsonify(options)
    except Exception as e:
        logging.error(f"Error getting filter options: {str(e)}")
        return jsonify({"error": "Failed to get filter options"}), 500

@app.route('/api/timeline-chart')
def get_timeline_chart():
    """Get timeline chart data for Service Analysis page"""
    try:
        cliente = request.args.get('cliente')
        servicio = request.args.get('servicio')
        
        df = get_dataframe()
        if df.empty:
            return jsonify({"error": "No data available"}), 404
        
        # Apply filters
        if cliente:
            df = df[df['Cliente'] == cliente]
        if servicio:
            df = df[df['Servicio Rela'] == servicio]
        
        # Prepare timeline data
        timeline_data = []
        if not df.empty:
            # Convert DataFrame to dict records to ensure native Python types
            records = df.to_dict(orient='records')
            for record in records:
                start_date = record.get('Creado el')
                end_date = record.get('Fecha de cierre')
                
                # Handle dates
                if pd.notna(start_date):
                    start_str = start_date.strftime('%Y-%m-%d %H:%M') if hasattr(start_date, 'strftime') else str(start_date)
                else:
                    start_str = ''
                
                if pd.notna(end_date):
                    end_str = end_date.strftime('%Y-%m-%d %H:%M') if hasattr(end_date, 'strftime') else str(end_date)
                else:
                    # If no end date, use start date + 24 hours for visualization
                    if pd.notna(start_date) and hasattr(start_date, 'strftime'):
                        end_date_calc = start_date + pd.Timedelta(hours=24)
                        end_str = end_date_calc.strftime('%Y-%m-%d %H:%M')
                    else:
                        end_str = start_str
                
                timeline_item = {
                    'id': str(record.get('ID', '')),
                    'service': str(record.get('Servicio Rela', '')),
                    'client': str(record.get('Cliente', '')),
                    'issue': str(record.get('Incidencia', '')),
                    'priority': str(record.get('Prioridad', 'Medium')),
                    'status': str(record.get('Etapa', '')),
                    'start': start_str,
                    'end': end_str,
                    'recurrent': bool(record.get('Reincidente', False)),
                    'assigned': str(record.get('Asignada a', ''))
                }
                timeline_data.append(timeline_item)
        
        return jsonify(timeline_data)
    except Exception as e:
        logging.error(f"Error getting timeline chart: {str(e)}")
        return jsonify({"error": "Failed to get timeline chart"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
