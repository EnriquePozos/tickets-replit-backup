# ==============================================================================
# 1. IMPORTACIONES
# ==============================================================================
import os
import logging
import xmlrpc.client
import time
from datetime import datetime, timedelta

import textwrap
import pandas as pd
import numpy as np
import altair as alt
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from apscheduler.schedulers.background import BackgroundScheduler
from auth import user_manager
from datetime import timezone

# ==============================================================================
# 1.5 MODULO DE SIMULACION DE TIEMPO (PARA PRUEBAS)
# ==============================================================================
# Para simular, pon una fecha como string 'YYYY-MM-DD'.
# Para usar la fecha real (en producción), déjalo como None.
# ==============================================================================
# 1.5 MODULO DE SIMULACION DE TIEMPO (PARA PRUEBAS)
# ==============================================================================
# To simulate, set a date string 'YYYY-MM-DD'.
# To use the real date (in production), set it to None.
SIMULATE_DATE_STR = None  # <-- Modify the date here

# Trabajamos siempre en UTC+6 en el servidor
UTC_TIMEZONE = timezone(timedelta(hours=6))

_simulated_time = None
if SIMULATE_DATE_STR:
    try:
        naive_dt = datetime.strptime(SIMULATE_DATE_STR, '%Y-%m-%d')
        _simulated_time = datetime(naive_dt.year,
                                   naive_dt.month,
                                   naive_dt.day,
                                   hour=23,
                                   minute=59,
                                   second=59,
                                   tzinfo=UTC_TIMEZONE)
        logging.warning(
            f"*** TIME SIMULATION ENABLED: Using fixed date {_simulated_time.strftime('%Y-%m-%d %Z')} ***"
        )
    except ValueError:
        logging.error(
            f"Invalid simulation date format: '{SIMULATE_DATE_STR}'. Using real date."
        )
        _simulated_time = None


def get_current_time():
    """
    Returns the simulated date and time if configured;
    otherwise, returns the current UTC+6 date and time.
    """
    if _simulated_time:
        return _simulated_time
    return datetime.now(UTC_TIMEZONE)


# ==============================================================================
# 2. CONFIGURACIÓN Y VARIABLES GLOBALES
# ==============================================================================
# Configuración del logging para monitorear la aplicación
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Inicialización de la aplicación Flask
app = Flask(__name__)

# Configuración del secret key para sesiones
app.secret_key = os.environ.get("SESSION_SECRET",
                                "clave_secreta_para_desarrollo")

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'You need to sign in to view this page.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    return user_manager.get_user(user_id)


# Almacenamiento en memoria (caché) para los datos de Odoo
cached_df = pd.DataFrame()
last_update_info = {"time": None, "user": "Sistema"}


# ==============================================================================
# 3. LÓGICA DE CONEXIÓN Y EXTRACCIÓN DE DATOS DE ODOO
# ==============================================================================
def get_odoo_connection():
    """
    Establece y devuelve una conexión con la API de Odoo utilizando credenciales
    almacenadas como variables de entorno.

    Returns:
        dict or None: Un diccionario con los detalles de la conexión (db, uid, api_key, models)
                      o None si la conexión falla.
    """
    logging.info("Intentando obtener credenciales de Odoo desde el entorno...")
    try:
        url = os.environ.get('ODOO_URL')
        db = os.environ.get('ODOO_DB')
        username = os.environ.get('ODOO_USER')
        api_key = os.environ.get('ODOO_API_KEY')

        if not all([url, db, username, api_key]):
            logging.error(
                "ERROR CRÍTICO: Faltan una o más credenciales de Odoo (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY)."
            )
            return None

        logging.info(
            f"Credenciales encontradas. Conectando a {url} para la DB '{db}'..."
        )
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, api_key, {})

        if not uid:
            logging.error(
                "Autenticación con Odoo fallida. Revisa URL, DB, usuario y API Key."
            )
            return None

        logging.info(f"Autenticación exitosa. UID obtenido: {uid}")
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

        return {"db": db, "uid": uid, "api_key": api_key, "models": models}
    except Exception as e:
        logging.error(f"Excepción al conectar con Odoo: {e}")
        return None

# 3.1. Función principal de extracción y procesamiento de datos
def fetch_and_process_odoo_data(days=30):
    """
    Función principal que se conecta a Odoo, extrae tickets Y la información de
    radiobases de los servicios (uniendo por ID), y los guarda en la caché global.
    
    Args:
        days (int): Número de días hacia atrás para consultar tickets (default: 30)
    """
    global cached_df, last_update_info
    if not cached_df.empty:
        cached_df.drop(cached_df.index, inplace=True)

    print(f"== INICIANDO PROCESO DE ACTUALIZACIÓN DE DATOS ({days} días) ==")
    conn = get_odoo_connection()
    if not conn:
        print(
            "ERROR: No se pudo establecer la conexión con Odoo. Abortando actualización."
        )
        return

    odoo_fields = [
        'id', 'name', 'stage_id', 'priority', 'create_date', 'close_date',
        'partner_id', 'user_id', 'service_id', 'issue', 'close_hours',
        'first_response_hours', 'report', 'solution', 'team_id',
        'ticket_type_id'
    ]

    try:
        # 1. Obtenemos la fecha "ahora" en UTC (real o simulada)
        now_utc = get_current_time()

        # 2. Calculamos la fecha de inicio en UTC (días + 6 horas adicionales)
        start_date_utc = now_utc - timedelta(days=days, hours=6)

        # 3. Odoo trabaja en UTC, enviamos las fechas en UTC
        domain = [
            '&', '&', # Operador "Y" para unir las dos condiciones
            ('create_date', '>=', start_date_utc.strftime('%Y-%m-%d %H:%M:%S')),
            ('create_date', '<=', now_utc.strftime('%Y-%m-%d %H:%M:%S')),
            '&', 
            ('team_id.name', 'ilike', 'Cast'),
            ('team_id.id', 'not in', [41,61]) # HACK: excluismos explicitamente las mesas de ayuda de Luminar Hogar
        ]

        # --- LOGS DE DIAGNÓSTICO ---
        print("=" * 80)
        print(
            f"[DEBUG] 🕐 HORA ACTUAL (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        print("=" * 80)
        print(
            f"[DEBUG] 📅 FECHA INICIO (UTC): {start_date_utc.strftime('%Y-%m-%d %H:%M:%S %Z')} (hace {days} días + 6 horas)"
        )
        print("=" * 80)

        # Calcular y mostrar la diferencia exacta
        diferencia_exacta = (now_utc - start_date_utc).total_seconds() / (24 *
                                                                          3600)
        print(f"[DEBUG] ⏱️  DIFERENCIA EXACTA: {diferencia_exacta:.6f} días")
        print("=" * 80)
        print(f"[DEBUG] 🔍 Domain de consulta a Odoo (fechas en UTC):")
        print(
            f"[DEBUG]    Desde: {start_date_utc.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"[DEBUG]    Hasta: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        # --- FIN LOGS ---

        # --- MEDICIÓN DE LA CONSULTA DE TICKETS ---
        start_time_tickets = time.monotonic()
        print(domain)
        ticket_data = conn['models'].execute_kw(conn['db'], conn['uid'],
                                                conn['api_key'],
                                                'helpdesk.ticket',
                                                'search_read', [domain],
                                                {'fields': odoo_fields})

        end_time_tickets = time.monotonic()
        duration_tickets_ms = (end_time_tickets - start_time_tickets) * 1000
        print(
            f"--- [DEBUG ODOO] Consulta 'helpdesk.ticket' tardó: {duration_tickets_ms:.2f} ms ---"
        )
        print("=" * 80)
        print(f"[DEBUG] 📊 TOTAL DE TICKETS ENCONTRADOS: {len(ticket_data)}")
        print("=" * 80)
        # --- FIN DE LA MEDICIÓN ---

        if not ticket_data:
            cached_df = pd.DataFrame()
            return

        df = pd.DataFrame(ticket_data)
        df['service_id_raw'] = df['service_id']
        df = _process_raw_dataframe(df)

        # Contar tickets sin service_id (cuando es False o None)
        tickets_sin_servicio = df['service_id_raw'].apply(
            lambda s: s is False or s is None or
            (isinstance(s, list) and not s)).sum()
        print(
            f"[DEBUG] 📋 Tickets sin service_id asignado: {tickets_sin_servicio} de {len(df)}"
        )

        all_service_ids_raw = df['service_id_raw'].dropna()
        service_ids_to_query = list({
            s_id[0]
            for s_id in all_service_ids_raw if isinstance(s_id, list) and s_id
        })

        # Manejar service_id que puede ser False, None, o una lista
        df['service_id_num'] = df['service_id_raw'].apply(
            lambda s: s[0] if isinstance(s, list) and s else None)
        df['Delivery Method'] = 'N/A'
        df['Infrastructure'] = 'N/A'
        df['Service Client'] = 'N/A'

        if service_ids_to_query:
            # --- MEDICIÓN DE LA CONSULTA DE SERVICIOS ---
            start_time_services = time.monotonic()

            services_data = conn['models'].execute_kw(
                conn['db'], conn['uid'], conn['api_key'], 'running.services',
                'search_read', [], {
                    'domain': [['id', 'in', service_ids_to_query]],
                    'fields': [
                        'id', 'delivery_type', 'radio_base_id',
                        'providing_company', 'partner_id'
                    ]
                })

            end_time_services = time.monotonic()
            duration_services_ms = (end_time_services -
                                    start_time_services) * 1000
            print(
                f"--- [DEBUG ODOO] Consulta 'running.services' tardó: {duration_services_ms:.2f} ms ---"
            )
            # --- FIN DE LA MEDICIÓN ---

            service_details_map = {}
            for service in services_data:
                # ... (resto de tu lógica de mapeo sin cambios)
                service_id = service['id']
                details = {}
                partner_info = service.get('partner_id')
                if isinstance(partner_info, list) and partner_info:
                    details['service_client_name'] = partner_info[1]
                delivery_method = service.get('delivery_type')
                if delivery_method == 'innet':
                    details['delivery_method'] = 'In-Net'
                    radio_base_info = service.get('radio_base_id')
                    if isinstance(radio_base_info, list) and radio_base_info:
                        details['infrastructure'] = radio_base_info[1]
                elif delivery_method == 'offnet':
                    details['delivery_method'] = 'Off-Net'
                    provider_info = service.get('providing_company')
                    if isinstance(provider_info, list) and provider_info:
                        details['infrastructure'] = provider_info[1]
                service_details_map[service_id] = details

            df['Delivery Method'] = df['service_id_num'].map(
                lambda sid: service_details_map.get(sid, {}).get(
                    'delivery_method', 'N/A'))
            df['Infrastructure'] = df['service_id_num'].map(
                lambda sid: service_details_map.get(sid, {}).get(
                    'infrastructure', 'N/A'))
            df['Service Client'] = df['service_id_num'].map(
                lambda sid: service_details_map.get(sid, {}).get(
                    'service_client_name', 'N/A'))

            print("Información de Servicios unida al DataFrame.")

        cached_df = df
        last_update_info['time'] = get_current_time()
        print(
            f"Procesamiento finalizado. {len(cached_df)} tickets cargados en caché."
        )

    except Exception as e:
        print(f"ERROR: Excepción durante la extracción o procesamiento: {e}")
        import traceback
        traceback.print_exc()  # Esto imprimirá el


# ==============================================================================
# 4. FUNCIONES AUXILIARES DE PROCESAMIENTO DE DATOS
# ==============================================================================
def _process_raw_dataframe(df):
    """
    Toma un DataFrame crudo de Odoo y aplica todas las transformaciones necesarias.
    IMPORTANTE: Las fechas ya vienen en la zona horaria correcta (UTC-6).
    """
    df.rename(columns={
        'id': 'ID',
        'name': 'Asunto',
        'create_date': 'Creado el',
        'close_date': 'Fecha de cierre',
        'priority': 'Prioridad',
        'stage_id': 'Etapa',
        'partner_id': 'Cliente',
        'user_id': 'Asignada a',
        'service_id': 'Servicio Rela',
        'issue': 'Incidencia',
        'team_id': 'Equipo',
        'close_hours': 'Horas Cierre',
        'ticket_type_id': 'Tipo Ticket',
        'first_response_hours': 'Horas Primera Respuesta',
        'report': 'Reporte Cliente',
        'solution': 'Solucion'
    },
              inplace=True)

    def extract_name(field):
        return field[1] if isinstance(field, list) and len(field) > 1 else None

    relational_cols = [
        'Etapa', 'Cliente', 'Asignada a', 'Servicio Rela', 'Incidencia',
        'Equipo', 'Tipo Ticket', 'Reporte Cliente', 'Solucion'
    ]
    for col in relational_cols:
        if col in df.columns:
            df[col] = df[col].apply(extract_name)

    # --- PROCESAMIENTO DE FECHAS EN UTC ---
    for col in ['Creado el', 'Fecha de cierre']:
        if col in df.columns and df[col].notna().any():
            # Paso 1: Parsear las fechas que vienen como strings de Odoo
            df[col] = pd.to_datetime(df[col], errors='coerce')

            # Paso 2: Marcar que estas fechas están en UTC (Odoo trabaja en UTC)
            # Las fechas permanecen en UTC para filtros y cálculos
            df[col] = df[col].dt.tz_localize(UTC_TIMEZONE)
    # --- FIN DEL PROCESAMIENTO ---

    df.sort_values(['Cliente', 'Servicio Rela', 'Creado el'], inplace=True)
    time_diff = df.groupby(['Cliente', 'Servicio Rela'])['Creado el'].diff()
    df['Reincidente'] = time_diff < pd.Timedelta(days=30)
    print(df.sort_values(by="Creado el", ascending=False).head(10))
    print(df.sort_values(by="Creado el", ascending=False).tail(10))

    return df


def _prepare_data_for_altair_timeline(df_original):
    """Prepara el DataFrame para ser usado en el gráfico de timeline de Altair."""
    df = df_original.dropna(subset=['Creado el']).copy()
    if df.empty:
        return pd.DataFrame()

    df.rename(columns={
        'Creado el': 'INICIO',
        'Fecha de cierre': 'TERMINO'
    },
              inplace=True)
    df['INICIO'] = pd.to_datetime(df['INICIO'], errors='coerce')
    df['TERMINO'] = pd.to_datetime(df['TERMINO'], errors='coerce')

    # DEBUG: Mostrar fechas ANTES de restar 6 horas
    print("=" * 80)
    print(
        "[DEBUG TIMELINE] FECHAS ANTES DE RESTAR 6 HORAS (primeros 3 registros):"
    )
    print(df[['INICIO', 'TERMINO']].head(3))
    print("=" * 80)

    # Restar 6 horas para la visualización
    df['INICIO'] = df['INICIO'] - pd.Timedelta(hours=6)
    df['TERMINO'] = df['TERMINO'] - pd.Timedelta(hours=6)

    # DEBUG: Mostrar fechas DESPUÉS de restar 6 horas
    print(
        "[DEBUG TIMELINE] FECHAS DESPUÉS DE RESTAR 6 HORAS (primeros 3 registros):"
    )
    print(df[['INICIO', 'TERMINO']].head(3))
    print("=" * 80)

    mask_abiertos = df['TERMINO'].isna()
    df.loc[mask_abiertos,
           'TERMINO'] = df.loc[mask_abiertos,
                               'INICIO'] + pd.Timedelta(hours=24)

    mismo_dia = df['INICIO'].dt.date == df['TERMINO'].dt.date
    df.loc[mismo_dia, 'INICIO'] = df.loc[mismo_dia, 'INICIO'].dt.normalize()
    df.loc[mismo_dia,
           'TERMINO'] = df.loc[mismo_dia,
                               'TERMINO'].dt.normalize() + pd.Timedelta(
                                   hours=23, minutes=59)

    df['Nombre Servicio'] = df['Servicio Rela'].fillna(
        'Sin Servicio Especificado')
    df['Tipo de Falla'] = np.where(df['Reincidente'] == True, 'Reincidente',
                                   'Único')
    df['Detalle'] = 'Incidencia: ' + df['Incidencia'].fillna('N/A').astype(str)
    df['Ticket'] = 'Ticket #' + df['ID'].astype(str)
    df['Cliente_info'] = df['Cliente'].fillna('Cliente desconocido')
    df['Estado'] = df['Etapa'].fillna('Sin estado')

    top_services = df['Nombre Servicio'].value_counts().head(30).index
    return df[df['Nombre Servicio'].isin(top_services)]


# ==============================================================================
# 5. PLANIFICADOR DE TAREAS (SCHEDULER)
# ==============================================================================
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(fetch_and_process_odoo_data, 'interval', minutes=30)
scheduler.start()

# ==============================================================================
# 6. RUTAS DE LA APLICACIÓN FLASK
# ==============================================================================


# ------------------------------------------------------------------------------
# 6.1. Rutas de Autenticación
# ------------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Maneja el login de usuarios."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please enter your username and password.')
            return render_template('login.html')

        user = user_manager.verify_user(username, password)
        if user:
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(
                url_for('dashboard'))
        else:
            flash('Incorrect username or password.')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Cierra la sesión del usuario."""
    logout_user()
    flash('You have logged out successfully.')
    return redirect(url_for('login'))


# ------------------------------------------------------------------------------
# 6.2. Rutas para renderizar las páginas HTML (PROTEGIDAS)
# ------------------------------------------------------------------------------
@app.route('/')
@login_required
def dashboard():
    """Renderiza el dashboard principal."""
    return render_template('index.html',
                           simulated_date=SIMULATE_DATE_STR,
                           user=current_user)


@app.route('/analysis')
@login_required
def analysis():
    """Renderiza la página de análisis."""
    return render_template('analysis.html',
                           simulated_date=SIMULATE_DATE_STR,
                           user=current_user)


@app.route('/repeat-report')
@login_required
def repeat_report():
    """Renderiza la página de Repeat Report."""
    return render_template('repeat_report.html',
                           simulated_date=SIMULATE_DATE_STR,
                           user=current_user)


@app.route('/tickets')
@login_required
def tickets():
    """Renderiza la página de búsqueda de tickets."""
    return render_template('tickets.html',
                           simulated_date=SIMULATE_DATE_STR,
                           user=current_user)


# ------------------------------------------------------------------------------
# 6.3. Rutas de Administración
# ------------------------------------------------------------------------------
@app.route('/admin')
@login_required
def admin_panel():
    """Panel de administración para gestionar usuarios."""
    if current_user.username != 'admin':
        flash('No tienes permisos para acceder al panel de administración.')
        return redirect(url_for('dashboard'))

    users = user_manager.list_users()
    return render_template('admin.html', users=users, user=current_user)


# ------------------------------------------------------------------------------
# 6.4. Rutas de la API: Estado y Control (PROTEGIDAS)
# ------------------------------------------------------------------------------
@app.route('/api/status')
@login_required
def get_status():
    """Devuelve el estado de la última actualización de datos."""
    if last_update_info["time"]:
        return jsonify({
            "last_updated":
            last_update_info["time"].strftime('%Y-%m-%d %H:%M:%S'),
            "updated_by":
            last_update_info["user"]
        })
    return jsonify({"last_updated": "Nunca", "updated_by": "N/A"})


@app.route('/api/refresh', methods=['GET', 'POST'])
@login_required
def manual_refresh():
    """Inicia una actualización manual de los datos."""

    # Usar el usuario autenticado actual
    user_name = current_user.username if current_user.is_authenticated else 'Usuario Anónimo'
    last_update_info['user'] = user_name

    # Leer el parámetro de días desde la URL (default: 30)
    days_param = request.args.get('days', '30')

    # Manejar el caso especial 'all' (180 días)
    if days_param == 'all':
        days = 180
    else:
        days = int(days_param)

    print(f"[DEBUG] Refresh solicitado con {days} días por {user_name}")

    # Ejecutar la actualización con el número de días especificado
    fetch_and_process_odoo_data(days=days)

    return jsonify({
        "message": f"Actualización iniciada por {user_name} ({days} días).",
        "status": "success"
    })


# ------------------------------------------------------------------------------
# 6.5. Rutas de la API: Datos para el Dashboard (KPIs y Gráficos) (PROTEGIDAS)
# ------------------------------------------------------------------------------
@app.route('/api/kpis')
@login_required
def get_kpis():
    """Calcula y devuelve los KPIs principales del dashboard."""
    if cached_df.empty:
        return jsonify({"error": "No hay datos disponibles."}), 404

    df = cached_df.copy()
    days_param = request.args.get('days', '30')

    # Si el parámetro es 'all', usar todos los tickets sin filtro de fecha
    if days_param == 'all':
        recent_df = df
    else:
        days = int(days_param)
        recent_df = df[df['Creado el'] >= (get_current_time() -
                                           timedelta(days=days)) -
                       pd.Timedelta(hours=6)]
    print(recent_df.sort_values(by="ID").head(10))
    print(recent_df.sort_values(by="ID").tail(10))

    # --- CÁLCULOS BASE ---
    total_tickets = len(recent_df)  # Valor de la primera tarjeta (ej: 1057)

    service_counts = recent_df['Servicio Rela'].value_counts()
    repeated_services = service_counts[service_counts >= 2]
    repeated_services_count = len(
        repeated_services)  # Valor de la segunda tarjeta (ej: 167)

    # --- NUEVO CÁLCULO DE PORCENTAJE (directo, como lo solicitaste) ---
    repeated_tickets_percentage = 0
    if total_tickets > 0:
        # Fórmula: (Número de Servicios Repetidos / Número Total de Tickets) * 100
        repeated_tickets_percentage = (repeated_services_count /
                                       total_tickets) * 100
    # --- FIN DEL NUEVO CÁLCULO ---

    # --- El resto de los KPIs se mantienen igual ---
    open_tickets = len(df[pd.isna(df['Fecha de cierre'])])

    avg_first_response = 0
    if 'Horas Primera Respuesta' in recent_df.columns and recent_df[
            'Horas Primera Respuesta'].notna().any():
        avg_first_response = recent_df['Horas Primera Respuesta'].mean()

    avg_resolution_time = 0
    if 'Horas Cierre' in recent_df.columns and recent_df['Horas Cierre'].notna(
    ).any():
        avg_resolution_time = recent_df['Horas Cierre'].mean()

    return jsonify({
        "total":
        total_tickets,
        "repeated_services":
        repeated_services_count,
        "avg_time_hours":
        round(avg_resolution_time, 1),
        "open_tickets":
        open_tickets,
        "first_response_hours":
        round(avg_first_response, 1),
        "repeated_tickets_percentage":
        round(repeated_tickets_percentage, 1)
    })


@app.route('/api/charts')
@login_required
def get_chart_data():
    """Devuelve los datos para los gráficos del dashboard."""
    if cached_df.empty:
        return jsonify({"error": "No hay datos disponibles."}), 404

    df = cached_df.copy()
    days_param = request.args.get('days', '30')

    # Si el parámetro es 'all', usar todos los tickets sin filtro de fecha
    if days_param == 'all':
        recent_df = df
        days = 180  # Para el gráfico de evolución mensual
    else:
        days = int(days_param)
        recent_df = df[df['Creado el'] >= (get_current_time() -
                                           timedelta(days=days))]

    chart_name = request.args.get('name')
    data = {}

    if chart_name == 'monthly_evolution':
        evolution_days = max(days, 180)
        start_date_evolution = get_current_time() - timedelta(
            days=evolution_days)

        # --- V AQUÍ ESTÁ LA CORRECCIÓN V ---
        # Añadimos .copy() para evitar el SettingWithCopyWarning
        evolution_df = df[df['Creado el'] >= start_date_evolution].copy()

        evolution_df['month'] = evolution_df['Creado el'].dt.to_period('M')
        counts = evolution_df.groupby('month').size()
        data = {
            "labels": [str(m) for m in counts.index],
            "data": [int(v) for v in counts.values]
        }

    elif chart_name == 'by_issue_type':
        counts = recent_df['Incidencia'].value_counts().head(10)
        data = {
            "labels": counts.index.tolist(),
            "data": [int(v) for v in counts.values]
        }

    # ======================= ZONA MODIFICADA =======================
    elif chart_name == 'by_ticket_type':
        # La columna se llama 'Tipo Ticket' después del procesamiento en _process_raw_dataframe
        counts = recent_df['Tipo Ticket'].dropna().value_counts().head(10)
        data = {
            "labels": counts.index.tolist(),
            "data": [int(v) for v in counts.values]
        }

    elif chart_name == 'top_clients':
        # 1. Verificamos si la columna 'Cliente' existe
        if 'Cliente' not in recent_df.columns:
            data = {"labels": [], "data": []}
        else:

            # 3. Realizamos el cálculo
            counts = recent_df['Cliente'].dropna().value_counts().head(10)

            data = {
                "labels": counts.index.tolist(),
                "data": [int(v) for v in counts.values]
            }

    else:
        return jsonify({"error": "Invalid chart name"}), 400

    return jsonify(data)


# ------------------------------------------------------------------------------
# 6.4. Rutas de la API: Datos de Tickets
# ------------------------------------------------------------------------------
@app.route('/api/dashboard-repeat-summary')
@login_required
def get_dashboard_repeat_summary():
    """
    Devuelve un resumen de los 5 servicios más repetidos para el dashboard.
    La respuesta es un array de objetos, cada uno con 'service' y 'count'.
    """
    # 1. Verificación inicial por si no hay datos cargados
    if cached_df.empty:
        logging.warning(
            "Llamada a get_dashboard_repeat_summary pero la caché está vacía.")
        return jsonify([])

    try:
        # 2. Filtrar el DataFrame por el período de tiempo solicitado
        days_param = request.args.get('days', '30')

        if days_param == 'all':
            recent_df = cached_df
        else:
            days = int(days_param)
            start_date = get_current_time() - timedelta(days=days)
            recent_df = cached_df[cached_df['Creado el'] >= start_date]

        if recent_df.empty:
            logging.info(
                f"No se encontraron tickets en los últimos {days} días.")
            return jsonify([])

        # 3. Contar las ocurrencias de cada servicio
        service_counts = recent_df['Servicio Rela'].value_counts()

        # 4. Filtrar para quedarnos solo con los servicios que se repiten (más de 1 vez)
        repeated_services = service_counts[service_counts > 1]

        # 5. Limitar al top 10
        top_5_services = repeated_services.head(5)

        # 6. Construir la lista de respuesta usando una list comprehension (más eficiente)
        response_data = [{
            "service": service_name,
            "count": int(count)
        } for service_name, count in top_5_services.items()]

        return jsonify(response_data)

    except Exception as e:
        # Registrar cualquier error inesperado durante el proceso
        logging.error(
            f"Error al generar el resumen de servicios repetidos: {e}",
            exc_info=True)
        return jsonify({"error":
                        "No se pudo generar el resumen de servicios"}), 500


@app.route('/api/search-tickets')
@login_required
def search_tickets():
    """Busca y filtra tickets según los parámetros de la URL."""
    if cached_df.empty:
        return jsonify([])

    df = cached_df.copy()

    # Aplicar filtros
    if status := request.args.get('status'): df = df[df['Etapa'] == status]
    if priority := request.args.get('priority'):
        df = df[df['Prioridad'] == priority]
    if client := request.args.get('client'): df = df[df['Cliente'] == client]

    # Handle multiple services
    services = request.args.getlist('service')
    if services:
        df = df[df['Servicio Rela'].isin(services)]
    elif service := request.args.get('service'):
        df = df[df['Servicio Rela'] == service]

    if assigned := request.args.get('assigned'):
        df = df[df['Asignada a'] == assigned]
    if start_date := request.args.get('start_date'):
        # Las fechas vienen en UTC desde el cliente
        start_dt = pd.to_datetime(start_date).tz_localize(UTC_TIMEZONE)
        df = df[df['Creado el'] >= start_dt]
    if end_date := request.args.get('end_date'):
        # Las fechas vienen en UTC desde el cliente
        end_dt = pd.to_datetime(end_date).tz_localize(
            UTC_TIMEZONE) + timedelta(days=1) - timedelta(seconds=1)
        df = df[df['Creado el'] <= end_dt]

    df = df.sort_values('Creado el', ascending=False)

    # Formatear resultados para que coincidan con el frontend (claves en minúscula)
    results = []
    debug_counter = 0
    for _, row in df.iterrows():
        # DEBUG: Mostrar primer registro antes y después de la conversión
        if debug_counter == 0 and pd.notna(row['Creado el']):
            print("=" * 80)
            print(f"[DEBUG SEARCH] FECHA ANTES: {row['Creado el']}")
            print(
                f"[DEBUG SEARCH] FECHA DESPUÉS: {row['Creado el'] - pd.Timedelta(hours=6)}"
            )
            print("=" * 80)
            debug_counter += 1

        results.append({
            'id':
            row.get('ID'),
            'subject':
            row.get('Asunto'),
            'client':
            row.get('Cliente'),
            'service':
            row.get('Servicio Rela'),
            'status':
            row.get('Etapa'),
            'priority':
            row.get('Prioridad'),
            'created': (row['Creado el'] -
                        pd.Timedelta(hours=6)).strftime('%Y-%m-%d %H:%M')
            if pd.notna(row['Creado el']) else None,
            'assigned':
            row.get('Asignada a'),
            'recurrent':
            bool(row.get('Reincidente', False))
        })

    return jsonify(results)


@app.route('/api/filter-options')
@login_required
def get_filter_options():
    """Devuelve listas de valores únicos para los filtros del frontend."""
    if cached_df.empty:
        return jsonify({})

    return jsonify({
        'clients':
        sorted(cached_df['Cliente'].dropna().unique().tolist()),
        'services':
        sorted(cached_df['Servicio Rela'].dropna().unique().tolist()),
        'statuses':
        sorted(cached_df['Etapa'].dropna().unique().tolist()),
        'priorities':
        sorted(cached_df['Prioridad'].dropna().unique().tolist()),
        'assigned':
        sorted(cached_df['Asignada a'].dropna().unique().tolist())
    })


@app.route('/api/repeat-report')
@login_required
def get_repeat_report():
    """
    Devuelve el reporte de servicios repetidos en el rango de fechas especificado.
    TODA la información se obtiene del caché, sin llamar a Odoo.
    """
    if cached_df.empty:
        return jsonify({
            "services": [],
            "summary": {},
            "date_range": {
                "start": "",
                "end": ""
            }
        })

    df = cached_df.copy()

    # Obtener parámetros de fecha personalizados o usar valores por defecto
    start_date_param = request.args.get('start_date')
    end_date_param = request.args.get('end_date')

    print(
        f"[DEBUG REPEAT REPORT] Parámetros recibidos - start_date: {start_date_param}, end_date: {end_date_param}"
    )

    if start_date_param and end_date_param:
        # Usar fechas personalizadas en UTC (vienen del cliente ya en UTC)
        start_date_obj = pd.to_datetime(start_date_param).tz_localize(
            UTC_TIMEZONE)
        end_date_obj = pd.to_datetime(end_date_param).tz_localize(
            UTC_TIMEZONE) + timedelta(days=1) - timedelta(seconds=1)
        start_date = start_date_obj.strftime('%d/%m/%Y')
        end_date = end_date_obj.strftime('%d/%m/%Y')
    else:
        # Usar último mes por defecto en UTC
        end_date_obj = get_current_time()
        start_date_obj = end_date_obj - timedelta(days=30)
        end_date = end_date_obj.strftime('%d/%m/%Y')
        start_date = start_date_obj.strftime('%d/%m/%Y')

    # 1. Filtrar tickets por el rango de fechas (todo en UTC)
    print(
        f"[DEBUG REPEAT REPORT] Rango de filtrado (UTC): {start_date_obj} hasta {end_date_obj}"
    )
    print(f"[DEBUG REPEAT REPORT] Total tickets antes del filtro: {len(df)}")

    recent_df = df[(df['Creado el'] >= start_date_obj)
                   & (df['Creado el'] <= end_date_obj)]

    print(
        f"[DEBUG REPEAT REPORT] Total tickets después del filtro: {len(recent_df)}"
    )

    if recent_df.empty:
        print(
            f"[DEBUG REPEAT REPORT] No se encontraron tickets en el rango especificado"
        )
        return jsonify({
            "services": [],
            "summary": {},
            "date_range": {
                "start": start_date,
                "end": end_date
            }
        })

    # 2. Contar repeticiones por servicio y filtrar los que se repiten
    service_counts = recent_df['Servicio Rela'].value_counts()
    repeated_service_names = service_counts[service_counts > 1].index.tolist()

    # Filtrar el DataFrame para obtener solo los tickets de servicios repetidos
    df_repeated = recent_df[recent_df['Servicio Rela'].isin(
        repeated_service_names)]

    # 3. ¡YA NO NECESITAMOS LLAMAR A ODOO! La información del cliente ya está en el caché.
    #    Agrupamos y preparamos la respuesta directamente.

    if df_repeated.empty:
        # Esto puede pasar si hay servicios repetidos pero los datos están incompletos
        services_data_response = []
    else:
        df_report = df_repeated.groupby('Servicio Rela').agg(
            count=('ID', 'size'),
            # Obtenemos el cliente directamente de la nueva columna que creamos
            client=('Service Client', 'first'),
            delivery_method=('Delivery Method', 'first'),
            infrastructure=('Infrastructure', 'first')).reset_index()

        # Convertimos el resultado a formato JSON
        services_data_response = df_report.rename(
            columns={
                'Servicio Rela': 'service',
                'count': 'count',
                'client': 'client',
                'delivery_method': 'delivery_method',
                'infrastructure': 'infrastructure'
            }).to_dict(orient='records')

    # Ordenar por conteo descendente
    services_data_response.sort(key=lambda x: x['count'], reverse=True)

    # 4. Calcular resumen (sin cambios)
    summary = {
        "total_services":
        len(recent_df['Servicio Rela'].dropna().unique()),
        "repeated_services":
        len(repeated_service_names),
        "total_incidents":
        len(recent_df),
        "most_repeated_count":
        int(service_counts.max()) if not service_counts.empty else 0
    }

    return jsonify({
        "services": services_data_response,
        "summary": summary,
        "date_range": {
            "start": start_date,
            "end": end_date
        }
    })


@app.route('/api/analysis-clients')
@login_required
def get_analysis_clients():
    """Return the list of clients for the analysis page."""
    try:
        if cached_df.empty:
            logging.warning("No hay datos en caché para obtener clientes")
            return jsonify([])

        # Get unique clients, sorted alphabetically
        unique_clients = cached_df['Cliente'].dropna().unique().tolist()
        clients = sorted(unique_clients)

        logging.info(f"Obtenidos {len(clients)} clientes únicos para análisis")
        return jsonify(clients)

    except Exception as e:
        logging.error(f"Error getting analysis clients: {str(e)}")
        return jsonify({"error": "Failed to get clients"}), 500


@app.route('/api/client-services/<client_name>')
@login_required
def get_client_services(client_name):
    """Return the list of services for a specific client."""
    try:
        if cached_df.empty:
            logging.warning(
                "No hay datos en caché para obtener servicios del cliente")
            return jsonify([])

        # Filtrar tickets del cliente específico
        client_df = cached_df[cached_df['Cliente'] == client_name]

        if client_df.empty:
            logging.info(
                f"No se encontraron tickets para el cliente: {client_name}")
            return jsonify([])

        # Obtener servicios únicos para este cliente
        unique_services = client_df['Servicio Rela'].dropna().unique().tolist()
        services = sorted(unique_services)

        logging.info(
            f"Obtenidos {len(services)} servicios únicos para el cliente {client_name}"
        )
        return jsonify(services)

    except Exception as e:
        logging.error(
            f"Error getting client services for {client_name}: {str(e)}")
        return jsonify({"error": "Failed to get services"}), 500


@app.route('/api/service-tickets')
@login_required
def get_service_tickets():
    """
    Devuelve los tickets detallados para una combinación de servicio y cliente,
    incluyendo Radio Base e Incidencia, y procesando el Reporte Cliente.
    """
    try:
        if cached_df.empty:
            return jsonify([])

        service_name = request.args.get('service')
        client_name = request.args.get('client')

        if not service_name or not client_name:
            return jsonify(
                {"error": "Service and client parameters are required"}), 400

        filtered_df = cached_df[(cached_df['Servicio Rela'] == service_name) &
                                (cached_df['Cliente'] == client_name)].copy()

        if filtered_df.empty:
            return jsonify([])

        filtered_df.sort_values('Creado el', ascending=False, inplace=True)

        tickets_response = []
        debug_counter = 0
        for _, row in filtered_df.iterrows():
            created_date = row['Creado el']
            close_date = row.get('Fecha de cierre')

            # DEBUG: Mostrar primer registro antes y después de la conversión
            if debug_counter == 0 and pd.notna(created_date):
                print("=" * 80)
                print(f"[DEBUG SERVICE TICKETS] FECHA ANTES: {created_date}")
                print(
                    f"[DEBUG SERVICE TICKETS] FECHA DESPUÉS: {created_date - pd.Timedelta(hours=6)}"
                )
                print("=" * 80)
                debug_counter += 1

            # --- Lógica de duración (sin cambios) ---
            if pd.notna(close_date):
                duration_delta = close_date - created_date
                duration_hours = int(duration_delta.total_seconds() / 3600)
                duration = f"{duration_hours} hours"
                is_open = False
            else:
                duration = "Open"
                is_open = True

            # --- NUEVA LÓGICA PARA PROCESAR EL REPORTE ---
            client_report_raw = row.get('Reporte Cliente', '')
            client_report_display = ''
            if isinstance(client_report_raw,
                          list) and len(client_report_raw) > 1:
                # Si es una lista y tiene al menos 2 elementos, toma el segundo
                client_report_display = client_report_raw[1]
            elif isinstance(client_report_raw, str):
                # Si ya es un string, úsalo directamente
                client_report_display = client_report_raw

            tickets_response.append({
                'id':
                row['ID'],
                'created_date':
                (created_date - pd.Timedelta(hours=6)).strftime('%d/%m/%Y')
                if pd.notna(created_date) else '',
                'duration':
                duration,
                'is_open':
                is_open,
                # Usa el valor procesado
                'client_report':
                client_report_display,
                'solution':
                row.get('Solucion', ''),
                'incident':
                row.get('Incidencia', '')
            })

        return jsonify(tickets_response)

    except Exception as e:
        logging.error(f"Error getting service tickets from cache: {str(e)}")
        return jsonify({"error": "Failed to get service tickets"}), 500


@app.route('/api/kpi/repeat_history')
@login_required
def get_repeat_kpi_history():
    """
    Calcula el histórico diario del KPI de servicios repetidos y su media móvil.
    Para cada día, calcula el KPI usando una ventana de los 30 días anteriores.
    """
    if cached_df.empty:
        return jsonify({"error": "No hay datos disponibles."}), 404

    try:
        df = cached_df.copy()

        df['fecha_dia'] = pd.to_datetime(df['Creado el']).dt.date
        today = get_current_time().date()
        start_period = today - timedelta(days=90)

        daily_kpis = []
        date_range = pd.date_range(start=start_period, end=today, freq='D')

        for current_day in date_range:
            current_day = current_day.date()

            # ======================= ZONA DE LÓGICA MODIFICADA =======================

            # 1. Definir la ventana de 30 días hacia atrás desde el día actual.
            window_start = current_day - timedelta(
                days=29)  # 29 para incluir el día actual (30 días en total)

            # 2. Filtrar el DataFrame principal para obtener solo los tickets de esa ventana.
            window_df = df[(df['fecha_dia'] >= window_start)
                           & (df['fecha_dia'] <= current_day)]

            # 3. Aplicar la misma lógica de las tarjetas, PERO sobre el 'window_df'.
            total_tickets_in_window = len(window_df)

            if total_tickets_in_window == 0:
                daily_kpis.append({'date': current_day, 'percentage': 0})
                continue

            # Contar servicios repetidos (2+ tickets) dentro de la ventana
            service_counts_in_window = window_df['Servicio Rela'].value_counts(
            )
            repeated_services_in_window = service_counts_in_window[
                service_counts_in_window >= 2]
            count_repeated_services_in_window = len(
                repeated_services_in_window)

            # Calcular el porcentaje usando los valores de la ventana
            percentage = (count_repeated_services_in_window /
                          total_tickets_in_window) * 100
            daily_kpis.append({'date': current_day, 'percentage': percentage})
            # ===================== FIN DE ZONA MODIFICADA ====================

        history_df = pd.DataFrame(daily_kpis)
        history_df['moving_average'] = history_df['percentage'].rolling(
            window=7, min_periods=1).mean()

        response = {
            "labels": [d.strftime('%Y-%m-%d') for d in history_df['date']],
            "daily_percentage":
            [round(p, 2) for p in history_df['percentage']],
            "moving_average":
            [round(ma, 2) for ma in history_df['moving_average']]
        }

        return jsonify(response)

    except Exception as e:
        # Usamos print aquí porque sabemos que logging no se muestra en tu consola
        print(f"Error al generar histórico de KPI: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "No se pudo generar el histórico"}), 500


@app.route('/api/kpi/repeat_history/export')
@login_required
def export_repeat_kpi_history():
    """
    Calcula el histórico del KPI de reincidentes y lo devuelve como un archivo CSV.
    """
    if cached_df.empty:
        return "No hay datos disponibles para exportar.", 404

    try:
        df = cached_df.copy()

        df['fecha_dia'] = pd.to_datetime(df['Creado el']).dt.date
        today = get_current_time().date()
        start_period = today - timedelta(days=90)

        daily_kpis = []
        date_range = pd.date_range(start=start_period, end=today, freq='D')

        # La lógica de cálculo es idéntica a la de la gráfica
        for current_day in date_range:
            current_day = current_day.date()
            window_start = current_day - timedelta(days=29)
            window_df = df[(df['fecha_dia'] >= window_start)
                           & (df['fecha_dia'] <= current_day)]

            total_tickets_in_window = len(window_df)
            if total_tickets_in_window == 0:
                daily_kpis.append({'date': current_day, 'percentage': 0})
                continue

            service_counts = window_df['Servicio Rela'].value_counts()
            repeated_services = service_counts[service_counts >= 2]
            count_repeated_services = len(repeated_services)

            percentage = (count_repeated_services /
                          total_tickets_in_window) * 100
            daily_kpis.append({'date': current_day, 'percentage': percentage})

        # --- Creación del archivo CSV en memoria ---
        csv_output = ["Fecha,Porcentaje_Reincidencia\n"]  # Encabezado del CSV
        for kpi in daily_kpis:
            # Formateamos cada línea del CSV
            line = f"{kpi['date'].strftime('%Y-%m-%d')},{kpi['percentage']:.2f}\n"
            csv_output.append(line)

        # Unimos todas las líneas en un solo string
        csv_string = "".join(csv_output)

        # Devolvemos el string como un archivo descargable
        return Response(
            csv_string,
            mimetype="text/csv",
            headers={
                "Content-disposition":
                f"attachment; filename=historico_reincidencia_{today.strftime('%Y-%m-%d')}.csv"
            })

    except Exception as e:
        print(f"Error al generar el exportable de KPI: {e}")
        return "Error al generar el archivo.", 500


@app.route('/api/altair-timeline')
@login_required
def get_altair_timeline():
    """Genera y devuelve el código HTML de un gráfico de timeline con Altair."""
    try:
        alt.data_transformers.disable_max_rows()
        logging.info("--- Iniciando get_altair_timeline ---")

        if cached_df.empty:
            return jsonify({
                "html":
                "<div class='text-center p-4 text-muted'>No hay datos disponibles.</div>"
            })

        # Get filter parameters
        cliente = request.args.get('cliente')
        servicios = request.args.getlist('servicio')

        # Start with a copy of the cached data
        df_filtered = cached_df.copy()

        # Apply client filter
        if cliente:
            df_filtered = df_filtered[df_filtered['Cliente'] == cliente]

        # Apply service filter(s)
        if servicios:
            df_filtered = df_filtered[df_filtered['Servicio Rela'].isin(
                servicios)]

        df_final = _prepare_data_for_altair_timeline(df_filtered)

        if df_final.empty:
            return jsonify({
                "html":
                "<div class='text-center p-4 text-muted'>No se encontraron datos para los filtros aplicados.</div>"
            })

        # --- TÉCNICA DE GRÁFICOS CONCATENADOS ---

        # 1. Preparar las etiquetas con saltos de línea
        df_final['Eje_Y_Label'] = df_final['Nombre Servicio'].apply(
            lambda x: '\n'.join(textwrap.wrap(x, width=70)))

        # 2. Crear un gráfico EXCLUSIVAMENTE para las etiquetas del eje Y
        labels_chart = alt.Chart(df_final).mark_text(
            align='left',
            baseline='middle',
            fontSize=10,
            dx=-10,
            lineBreak='\n').encode(
                text='Eje_Y_Label:N',
                y=alt.Y('Eje_Y_Label:N',
                        sort=alt.EncodingSortField(field='INICIO',
                                                   order='descending'),
                        title='Servicios',
                        axis=alt.Axis(labels=False,
                                      ticks=False,
                                      domain=False,
                                      titlePadding=10))).properties(width=0)

        # 3. Crear el gráfico de barras SIN las etiquetas del eje Y
        end_date = get_current_time()
        start_date = end_date - timedelta(days=180)
        cliente_nombre = df_final['Cliente_info'].iloc[
            0] if not df_final.empty else 'Cliente'

        timeline_chart = alt.Chart(df_final).mark_bar(
            cornerRadius=5,
            opacity=0.85  # Se quita la altura fija de aquí
        ).encode(
            x=alt.X('INICIO:T',
                    title='Línea de Tiempo (Últimos 6 meses)',
                    axis=alt.Axis(format='%b %Y', labelAngle=-45, grid=True),
                    scale=alt.Scale(
                        domain=[start_date.isoformat(),
                                end_date.isoformat()])),
            x2=alt.X2('TERMINO:T'),
            y=alt.Y('Eje_Y_Label:N',
                    sort=alt.EncodingSortField(field='INICIO',
                                               order='descending'),
                    title=None,
                    axis=alt.Axis(labels=False, ticks=False, domain=False)),
            color=alt.Color('Tipo de Falla:N',
                            scale=alt.Scale(domain=['Único', 'Reincidente'],
                                            range=['#2563EB', '#EF4444']),
                            legend=alt.Legend(title="Tipo de Ticket",
                                              orient='top',
                                              titlePadding=10)),
            tooltip=[
                alt.Tooltip('Ticket:N', title='Ticket'),
                alt.Tooltip('Cliente_info:N', title='Cliente'),
                alt.Tooltip('Nombre Servicio:N', title='Servicio'),
                alt.Tooltip('Estado:N', title='Estado'),
                alt.Tooltip('Detalle:N', title='Detalle'),
                alt.Tooltip('INICIO:T',
                            title='Inicio',
                            format='%d/%m/%Y %H:%M'),
                alt.Tooltip('TERMINO:T',
                            title='Término',
                            format='%d/%m/%Y %H:%M')
            ]).properties(height=alt.Step(
                35)  # <-- CORRECCIÓN: La altura se aplica a este gráfico
                          ).interactive()

        # 4. Unir ambos gráficos horizontalmente
        final_chart = alt.hconcat(
            labels_chart, timeline_chart,
            spacing=5).resolve_scale(y='shared').properties(
                # Se quita la altura de aquí
                title=alt.TitleParams(
                    text=f"{cliente_nombre} - Timeline de Servicios",
                    fontSize=14,
                    anchor='start',
                    color='#1E293B')).configure_view(strokeWidth=0)

        embed_options = {'actions': False, 'renderer': 'svg'}
        chart_html = final_chart.to_html(embed_options=embed_options)
        return jsonify({"html": chart_html})

    except Exception as e:
        logging.error(f"Error al generar el gráfico de timeline: {e}",
                      exc_info=True)
        return jsonify({
            "html":
            f"<div class='text-center p-4 text-danger'>Error al generar gráfico: {e}</div>"
        }), 500


@app.route('/api/altair-timeline-new-tab')  # Nueva ruta
@login_required
def get_altair_timeline_new_tab():
    """Genera y devuelve el código HTML de un gráfico de timeline con Altair."""
    try:
        alt.data_transformers.disable_max_rows()
        logging.info("--- Iniciando get_altair_timeline ---")

        if cached_df.empty:
            return jsonify({
                "html":
                "<div class='text-center p-4 text-muted'>No hay datos disponibles.</div>"
            })

        # Get filter parameters
        cliente = request.args.get('cliente')
        servicios = request.args.getlist('servicio')

        # Start with a copy of the cached data
        df_filtered = cached_df.copy()

        # Apply client filter
        if cliente:
            df_filtered = df_filtered[df_filtered['Cliente'] == cliente]

        # Apply service filter(s)
        if servicios:
            df_filtered = df_filtered[df_filtered['Servicio Rela'].isin(
                servicios)]

        df_final = _prepare_data_for_altair_timeline(df_filtered)

        if df_final.empty:
            return jsonify({
                "html":
                "<div class='text-center p-4 text-muted'>No se encontraron datos para los filtros aplicados.</div>"
            })

        # --- TÉCNICA DE GRÁFICOS CONCATENADOS ---

        # 1. Preparar las etiquetas con saltos de línea
        df_final['Eje_Y_Label'] = df_final['Nombre Servicio'].apply(
            lambda x: '\n'.join(textwrap.wrap(x, width=70)))

        # 2. Crear un gráfico EXCLUSIVAMENTE para las etiquetas del eje Y
        labels_chart = alt.Chart(df_final).mark_text(
            align='left', baseline='middle', fontSize=9,
            lineBreak='\n').encode(text='Eje_Y_Label:N',
                                   y=alt.Y('Eje_Y_Label:N',
                                           sort=alt.EncodingSortField(
                                               field='INICIO',
                                               order='descending'),
                                           title='Servicios',
                                           axis=alt.Axis(labels=False,
                                                         ticks=False,
                                                         domain=False,
                                                         titlePadding=10,
                                                         titleAnchor='end')))

        # 3. Crear el gráfico de barras SIN las etiquetas del eje Y
        end_date = get_current_time()
        start_date = end_date - timedelta(days=180)
        cliente_nombre = df_final['Cliente_info'].iloc[
            0] if not df_final.empty else 'Cliente'

        timeline_chart = alt.Chart(df_final).mark_bar(
            cornerRadius=5,
            opacity=0.85  # Se quita la altura fija de aquí
        ).encode(
            x=alt.X('INICIO:T',
                    title='Línea de Tiempo (Últimos 6 meses)',
                    axis=alt.Axis(format='%b %Y', labelAngle=-45, grid=True),
                    scale=alt.Scale(
                        domain=[start_date.isoformat(),
                                end_date.isoformat()])),
            x2=alt.X2('TERMINO:T'),
            y=alt.Y('Eje_Y_Label:N',
                    sort=alt.EncodingSortField(field='INICIO',
                                               order='descending'),
                    title=None,
                    axis=alt.Axis(labels=False, ticks=False, domain=False)),
            color=alt.Color('Tipo de Falla:N',
                            scale=alt.Scale(domain=['Único', 'Reincidente'],
                                            range=['#2563EB', '#EF4444']),
                            legend=alt.Legend(title="Tipo de Ticket",
                                              orient='top',
                                              titlePadding=10)),
            tooltip=[
                alt.Tooltip('Ticket:N', title='Ticket'),
                alt.Tooltip('Cliente_info:N', title='Cliente'),
                alt.Tooltip('Nombre Servicio:N', title='Servicio'),
                alt.Tooltip('Estado:N', title='Estado'),
                alt.Tooltip('Detalle:N', title='Detalle'),
                alt.Tooltip('INICIO:T',
                            title='Inicio',
                            format='%d/%m/%Y %H:%M'),
                alt.Tooltip('TERMINO:T',
                            title='Término',
                            format='%d/%m/%Y %H:%M')
            ]).properties(height=alt.Step(35), width=800).interactive()

        # 4. Unir ambos gráficos horizontalmente
        final_chart = alt.hconcat(
            labels_chart, timeline_chart,
            spacing=5).resolve_scale(y='shared').properties(
                # Se quita la altura de aquí
                title=alt.TitleParams(
                    text=f"{cliente_nombre} - Timeline de Servicios",
                    fontSize=14,
                    anchor='start',
                    color='#1E293B')).configure_view(strokeWidth=0)

        embed_options = {'actions': False, 'renderer': 'svg'}
        chart_html = final_chart.to_html(embed_options=embed_options)
        return jsonify({"html": chart_html})

    except Exception as e:
        logging.error(f"Error al generar el gráfico de timeline: {e}",
                      exc_info=True)
        return jsonify({
            "html":
            f"<div class='text-center p-4 text-danger'>Error al generar gráfico: {e}</div>"
        }), 500


# ==============================================================================
# 7. BLOQUE DE EJECUCIÓN PRINCIPAL
# ==============================================================================
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    logging.info(
        "Realizando la primera carga de datos al arrancar la aplicación...")
    fetch_and_process_odoo_data()

if __name__ == '__main__':
    logging.info(
        "Iniciando la aplicación Flask en modo de desarrollo local...")
    app.run(host='0.0.0.0', port=5000, debug=True)
