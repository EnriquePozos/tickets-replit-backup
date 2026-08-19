# Ticket Dashboard - Technical Guide

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Odoo Connection & Cache System](#odoo-connection--cache-system)
3. [Full API Catalog](#full-api-catalog)
4. [Odoo Integration Details](#odoo-integration-details)
5. [Frontend-Backend Communication (apiCall)](#frontend-backend-communication-apicall)
6. [Chart Rendering Pattern](#chart-rendering-pattern)
7. [app.js Loading & Initialization](#appjs-loading--initialization)
8. [Date & Timezone Handling](#date--timezone-handling)
9. [Complete Application Flow](#complete-application-flow)
10. [Guide: Adding New Features](#guide-adding-new-features)

---

## Architecture Overview

The project follows a 3-layer architecture:

```
┌──────────────────────────┐
│   Frontend (HTML/JS)     │  templates/*.html + static/app.js
│   - Displays data        │
│   - Renders charts       │
│   - Handles interaction  │
└──────────┬───────────────┘
           │  fetch() / API calls
           ▼
┌──────────────────────────┐
│   Backend (Python/Flask) │  main.py + auth.py
│   - Processes data       │
│   - Exposes JSON APIs    │
│   - Business logic       │
│   - In-memory cache      │
└──────────┬───────────────┘
           │  XML-RPC
           ▼
┌──────────────────────────┐
│   Odoo (Data Source)     │  odoo.wispi.mx
│   - helpdesk.ticket      │
│   - running.services     │
└──────────────────────────┘
```

### Connection Flow Diagram

```
┌─────────────┐    XML-RPC /xmlrpc/2/common     ┌──────────────────┐
│             │ ──────────────────────────────►   │                  │
│  main.py    │    authenticate(db,user,key,{})   │  Odoo            │
│             │ ◄──────────────────────────────   │  (odoo.wispi.mx) │
│             │    returns UID                    │                  │
│             │                                   │                  │
│             │    XML-RPC /xmlrpc/2/object        │                  │
│             │ ──────────────────────────────►   │                  │
│             │    execute_kw('helpdesk.ticket',  │                  │
│             │               'search_read',...)  │                  │
│             │ ◄──────────────────────────────   │                  │
│             │    returns ticket records          │                  │
│             │                                   │                  │
│             │ ──────────────────────────────►   │                  │
│             │    execute_kw('running.services', │                  │
│             │               'search_read',...)  │                  │
│             │ ◄──────────────────────────────   │                  │
│             │    returns service details         │                  │
└─────────────┘                                   └──────────────────┘
       │
       ▼
 ┌─────────────┐
 │  cached_df  │  In-memory Pandas DataFrame
 │  (global)   │  All endpoints read from here
 └─────────────┘
```

### Project Files

| File | Role | Description |
|------|------|-------------|
| `main.py` | Backend | Flask server, all API endpoints, Odoo connection, data processing, scheduler |
| `auth.py` | Authentication | User class, UserManager, password hashing with werkzeug |
| `static/app.js` | Frontend JS | API calls, Chart.js rendering, table population, filtering logic |
| `static/style.css` | Styles | Custom CSS with color palette and responsive design |
| `templates/index.html` | Dashboard | Main page with KPI cards, charts, and latest tickets table |
| `templates/repeat_report.html` | Repeat Report | Recurring service tickets report with date filtering |
| `templates/analysis.html` | Analysis | Service timeline with Altair/Vega interactive charts |
| `templates/tickets.html` | Ticket Search | Search and filter tickets with pagination |
| `templates/login.html` | Login | Authentication page |
| `templates/admin.html` | Admin Panel | User management (admin-only) |

---

## Odoo Connection & Cache System

### Why a Cache?

Endpoints like `/api/kpis` or `/api/search-tickets` **never call Odoo directly**. Instead, they read from an in-memory variable called `cached_df`. This is because:

- Odoo queries are slow (~1-2 seconds per call)
- A cache means endpoints respond instantly
- All users see the same data without overloading Odoo

### The `cached_df` Variable

```python
cached_df = pd.DataFrame()  # Empty DataFrame at startup
```

This global variable is a Pandas DataFrame containing all processed tickets. It is populated automatically and refreshed every 30 minutes.

### The Scheduler (BackgroundScheduler)

```python
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(fetch_and_process_odoo_data, 'interval', minutes=30)
scheduler.start()
```

This creates a background process that runs `fetch_and_process_odoo_data()` every 30 minutes automatically. On first startup, the function also runs immediately via:

```python
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    fetch_and_process_odoo_data()
```

### The `fetch_and_process_odoo_data()` Function

This is the main function that connects to Odoo, downloads data, and stores it in the cache:

```
1. get_odoo_connection()
   → Connects to Odoo using ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY
   → Authenticates via XML-RPC /xmlrpc/2/common
   → Returns connection dict with {db, uid, api_key, models}

2. FIRST ODOO CALL: helpdesk.ticket search_read
   → Domain filter: create_date within last N days, team 'Cast', excluding IDs [41,61]
   → Fields: id, name, stage_id, priority, create_date, close_date, partner_id,
             user_id, service_id, issue, close_hours, first_response_hours,
             report, solution, team_id, ticket_type_id

3. _process_raw_dataframe(df)
   → Renames columns to Spanish labels (create_date → "Creado el", etc.)
   → Extracts names from relational fields ([id, name] → name)
   → Parses dates and localizes to UTC+6 timezone
   → Calculates recurrence (Reincidente): same client+service within 30 days

4. SECOND ODOO CALL: running.services search_read
   → Queries by service IDs found in tickets
   → Fields: id, delivery_type, radio_base_id, providing_company, partner_id

5. Enriches tickets with service details:
   → Delivery Method (In-Net / Off-Net)
   → Infrastructure (radio_base_id name or providing_company name)
   → Service Client (partner_id name from service record)

6. cached_df = df  ← ALL ENDPOINTS READ FROM HERE
```

### Cache System Diagram

```
                BACKGROUND PROCESS (every 30 min)
                ──────────────────────────────────

 Scheduler ──→ fetch_and_process_odoo_data()
                         │
                         │  XML-RPC
                         ▼
                    Odoo (odoo.wispi.mx)
                         │
                         │  Returns ~900 tickets + service details
                         ▼
                    Process data (_process_raw_dataframe)
                         │
                         │  Store in memory
                         ▼
                    cached_df = df  ◄──── THE CACHE
                                              │
                    ──────────────────────────────────────
                    WHEN USER OPENS THE PAGE
                    ──────────────────────────────────────
                                              │
 Browser ──→ fetch('/api/kpis')               │
                         │                    │
                         ▼                    │
                    get_kpis()                │
                         │                    │
                         │  Reads from memory │
                         ▼                    │
                    df = cached_df.copy() ◄───┘  (Reads cache, NOT Odoo)
                         │
                    Calculates KPIs
                         │
                    return jsonify({...})
```

---

## Full API Catalog

All API endpoints require authentication (`@login_required`). All data endpoints read from `cached_df`, never from Odoo directly.

### Authentication Routes

| Method | URL | Function | Description |
|--------|-----|----------|-------------|
| GET, POST | `/login` | `login()` | Renders login form (GET) or processes login (POST). Redirects to dashboard on success. |
| GET | `/logout` | `logout()` | Logs out the current user and redirects to login. |

### Page Routes

| Method | URL | Function | Template | Description |
|--------|-----|----------|----------|-------------|
| GET | `/` | `dashboard()` | `index.html` | Main dashboard with KPIs, charts, tables |
| GET | `/analysis` | `analysis()` | `analysis.html` | Service timeline analysis page |
| GET | `/repeat-report` | `repeat_report()` | `repeat_report.html` | Repeat report page |
| GET | `/tickets` | `tickets()` | `tickets.html` | Ticket search page |
| GET | `/admin` | `admin_panel()` | `admin.html` | Admin panel (admin user only) |

### Status & Control API

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/status` | `get_status()` | None | `{ last_updated: string, updated_by: string }` |
| GET, POST | `/api/refresh` | `manual_refresh()` | `?days=30` (or `all`) | `{ message: string, status: "success" }` — Triggers a full Odoo re-fetch |

### Dashboard API (KPIs & Charts)

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/kpis` | `get_kpis()` | `?days=30` (or `60`, `90`, `180`, `all`) | `{ total, repeated_services, avg_time_hours, open_tickets, first_response_hours, repeated_tickets_percentage }` |
| GET | `/api/charts` | `get_chart_data()` | `?name=<chart>&days=30` | `{ labels: [], data: [] }` |

**Chart names for `/api/charts`:**

| `name` value | Description | Data source |
|--------------|-------------|-------------|
| `monthly_evolution` | Tickets over time (monthly counts, always shows 180+ days) | `cached_df['Creado el']` grouped by month |
| `by_issue_type` | Top 10 issue types | `cached_df['Incidencia']` value counts |
| `by_ticket_type` | Top 10 ticket types | `cached_df['Tipo Ticket']` value counts |
| `top_clients` | Top 10 clients by ticket count | `cached_df['Cliente']` value counts |

### Dashboard Repeat Summary API

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/dashboard-repeat-summary` | `get_dashboard_repeat_summary()` | `?days=30` (or `all`) | Array of `{ service, count }` — Top 5 repeated services |

### Ticket APIs

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/search-tickets` | `search_tickets()` | `?status=`, `?priority=`, `?client=`, `?service=` (multiple), `?assigned=`, `?start_date=`, `?end_date=` | Array of `{ id, subject, client, service, status, priority, created, assigned, recurrent }` |
| GET | `/api/filter-options` | `get_filter_options()` | None | `{ clients: [], services: [], statuses: [], priorities: [], assigned: [] }` |
| GET | `/api/service-tickets` | `get_service_tickets()` | `?service=<name>&client=<name>` (both required) | Array of `{ id, created_date, duration, is_open, client_report, solution, incident }` |

### Repeat Report API

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/repeat-report` | `get_repeat_report()` | `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` (optional, defaults to last 30 days) | `{ services: [{ service, count, client, delivery_method, infrastructure }], summary: { total_services, repeated_services, total_incidents, most_repeated_count }, date_range: { start, end } }` |

### Repeat KPI History API

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/kpi/repeat_history` | `get_repeat_kpi_history()` | None | `{ labels: [dates], daily_percentage: [numbers], moving_average: [numbers] }` — Last 90 days with 30-day rolling window |
| GET | `/api/kpi/repeat_history/export` | `export_repeat_kpi_history()` | None | CSV file download (`Fecha,Porcentaje_Reincidencia`) |

### Analysis API

| Method | URL | Function | Parameters | Response |
|--------|-----|----------|------------|----------|
| GET | `/api/analysis-clients` | `get_analysis_clients()` | None | Array of client names (sorted) |
| GET | `/api/client-services/<client_name>` | `get_client_services(client_name)` | URL path: client name | Array of service names for that client (sorted) |
| GET | `/api/altair-timeline` | `get_altair_timeline()` | `?cliente=<name>&servicio=<name>` (multiple servicio allowed) | `{ html: string }` — Altair chart embedded HTML (for iframe/div injection) |
| GET | `/api/altair-timeline-new-tab` | `get_altair_timeline_new_tab()` | Same as above | `{ html: string }` — Same chart with fixed 800px width for new tab viewing |

---

## Odoo Integration Details

### XML-RPC Protocol

The application connects to Odoo using Python's built-in `xmlrpc.client` module. The connection is established in `get_odoo_connection()`:

```python
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, api_key, {})
models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
```

### Credential Flow

1. Reads `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY` from environment variables
2. Authenticates via `/xmlrpc/2/common` → receives a UID
3. Uses UID + API key for all subsequent `execute_kw` calls via `/xmlrpc/2/object`

### Two Models Queried

#### 1. `helpdesk.ticket` (Primary query)

**Domain filter:**
```python
[
    '&', '&',
    ('create_date', '>=', start_date),
    ('create_date', '<=', now),
    '&',
    ('team_id.name', 'ilike', 'Cast'),
    ('team_id.id', 'not in', [41, 61])  # Exclude specific help desk teams
]
```

**Fields requested:**
`id`, `name`, `stage_id`, `priority`, `create_date`, `close_date`, `partner_id`, `user_id`, `service_id`, `issue`, `close_hours`, `first_response_hours`, `report`, `solution`, `team_id`, `ticket_type_id`

#### 2. `running.services` (Secondary query, by IDs)

Queried only for service IDs found in the ticket data.

**Fields requested:**
`id`, `delivery_type`, `radio_base_id`, `providing_company`, `partner_id`

### Field Mappings (Odoo → Internal DataFrame Columns)

| Odoo Field | DataFrame Column | Type | Notes |
|------------|-----------------|------|-------|
| `id` | `ID` | int | Ticket ID |
| `name` | `Asunto` | string | Ticket subject |
| `stage_id` | `Etapa` | string | Stage name extracted from `[id, name]` |
| `priority` | `Prioridad` | string | Priority level |
| `create_date` | `Creado el` | datetime (UTC+6) | Creation date |
| `close_date` | `Fecha de cierre` | datetime (UTC+6) | Close date (null if open) |
| `partner_id` | `Cliente` | string | Client name extracted from `[id, name]` |
| `user_id` | `Asignada a` | string | Assigned user name |
| `service_id` | `Servicio Rela` | string | Service name extracted from `[id, name]` |
| `issue` | `Incidencia` | string | Issue type name |
| `close_hours` | `Horas Cierre` | float | Hours to close |
| `first_response_hours` | `Horas Primera Respuesta` | float | Hours to first response |
| `report` | `Reporte Cliente` | string | Client report name |
| `solution` | `Solucion` | string | Solution name |
| `team_id` | `Equipo` | string | Team name |
| `ticket_type_id` | `Tipo Ticket` | string | Ticket type name |

### Service Detail Enrichment

For each ticket with a `service_id`, the application queries `running.services` and adds:

| Enriched Column | Source | Logic |
|-----------------|--------|-------|
| `Delivery Method` | `delivery_type` | `"innet"` → `"In-Net"`, `"offnet"` → `"Off-Net"` |
| `Infrastructure` | `radio_base_id` or `providing_company` | If In-Net: radio base name. If Off-Net: provider name. |
| `Service Client` | `partner_id` (from service) | The client associated with the service record |

### Recurrence Calculation

After processing, tickets are sorted by `[Cliente, Servicio Rela, Creado el]` and grouped by `[Cliente, Servicio Rela]`. A ticket is marked as `Reincidente = True` if it was created within 30 days of the previous ticket for the same client+service combination.

---

## Frontend-Backend Communication (apiCall)

### The `apiCall()` Function

```javascript
async function apiCall(endpoint, options = {}) {
    const response = await fetch(endpoint, options);
    return await response.json();
}
```

This is a wrapper around `fetch()`. All frontend functions use it to communicate with the Flask backend. Since the HTML and API are served by the same Flask server on port 5000, relative URLs like `/api/kpis` resolve automatically.

### Request Flow Example

```
 BROWSER (app.js)                              SERVER (main.py)
 ─────────────────                             ──────────────────

 loadKPIs()
     │
     ▼
 apiCall('/api/kpis?days=30')
     │
     ▼
 fetch('/api/kpis?days=30')
     │
     │  ══════════ HTTP GET ══════════►  Flask receives request
     │                                          │
     │                                  @app.route('/api/kpis')
     │                                          │
     │                                  get_kpis() executes
     │                                          │
     │                                  df = cached_df.copy()
     │                                  Calculates KPIs
     │                                          │
     │  ◄══════════ JSON ═══════════   return jsonify({...})
     │
     ▼
 data = await response.json()
     │
 updateElementText('total-tickets', data.total)
```

---

## Chart Rendering Pattern

Each chart follows a 3-step pattern:

### Step 1: HTML Container

```html
<canvas id="repeatKpiHistoryChart"></canvas>
```

### Step 2: JavaScript Function (app.js)

```javascript
async function loadRepeatKpiHistoryChart() {
    const data = await apiCall('/api/kpi/repeat_history');      // 1. Fetch data
    const ctx = document.getElementById('repeatKpiHistoryChart'); // 2. Find canvas
    new Chart(ctx, { type: 'bar', data: { ... } });              // 3. Render chart
}
```

### Step 3: Backend Endpoint (main.py)

```python
@app.route('/api/kpi/repeat_history')
def get_repeat_kpi_history():
    df = cached_df.copy()  # Read from cache
    # Calculate data...
    return jsonify({ "labels": [...], "daily_percentage": [...], "moving_average": [...] })
```

### Chart Flow Diagram

```
Python (main.py)              JavaScript (app.js)              HTML (template)
──────────────────            ─────────────────────            ──────────────────
/api/kpi/repeat_history       loadRepeatKpiHistoryChart()      <canvas id="...">
        │                              │                                │
  Reads cached_df               apiCall() fetches data           Empty canvas
  Calculates data                      │
        │                              │
  Returns JSON ─────────────►  Receives JSON
                                       │
                              new Chart() ──────────────────►  Renders chart
```

---

## app.js Loading & Initialization

The `app.js` file is loaded on every page. It contains a **global `DOMContentLoaded` block** that runs on all pages, plus each template has its own page-specific `DOMContentLoaded` block.

### Global Initialization (app.js — runs on every page)

```javascript
document.addEventListener('DOMContentLoaded', function() {
    loadKPIs();
    loadCharts();
    loadLatestTickets();
    loadTopRepeatedServices(currentTimePeriod);
    loadFilterOptions();
    showInitialMessage();
    loadRepeatKpiHistoryChart();
});
```

These functions execute on every page load. Functions that depend on HTML elements not present on the current page (e.g., `loadKPIs()` on the tickets page) silently skip execution because they check for element existence before rendering.

### Per-Page Initialization (in each template's `<script>` block)

Each template also has its own `DOMContentLoaded` block for page-specific logic:

**Dashboard (index.html):**
```javascript
document.addEventListener('DOMContentLoaded', function() {
    loadKPIs();
    loadCharts();
    loadLatestTickets();
});
```

**Tickets Page (tickets.html):**
```javascript
document.addEventListener('DOMContentLoaded', function() {
    loadFilterOptions();
    searchTickets();
});
```

**Analysis Page (analysis.html):**
```javascript
document.addEventListener('DOMContentLoaded', function() {
    loadFilterOptions();
    loadAnalysisClients();
});
```

**Repeat Report Page (repeat_report.html):**
```javascript
document.addEventListener('DOMContentLoaded', function() {
    // Sets default date range (last 30 days)
    loadRepeatReport();
});
```

Some functions (like `loadKPIs`, `loadFilterOptions`) are called from both the global block and per-page blocks, which means they may execute twice on certain pages. This is functionally harmless since Chart.js instances are destroyed before re-creation and DOM updates are idempotent.

### Functions Triggered by User Interaction

Other functions in `app.js` only execute when:
- The user clicks a button (e.g., search triggers `searchTickets()`)
- Another function calls them (e.g., `loadCharts()` calls `loadMonthlyEvolutionChart()`, `loadIssueTypeChart()`, etc.)
- A dropdown changes (e.g., time period select triggers `updateTimePeriodFromSelect()`)

---

## Date & Timezone Handling

### How Dates Arrive from Odoo

Dates (`create_date`, `close_date`) arrive from Odoo as UTC strings. They are processed in `_process_raw_dataframe()`:

```python
for col in ['Creado el', 'Fecha de cierre']:
    df[col] = pd.to_datetime(df[col], errors='coerce')
    df[col] = df[col].dt.tz_localize(UTC_TIMEZONE)  # UTC+6
```

### Visual Adjustment (-6 Hours)

Dates are stored internally with UTC+6 offset for filters and calculations. A -6 hour adjustment is applied **only when displaying** dates to the user:

| Context | File | What it affects |
|---------|------|-----------------|
| Timeline charts | `main.py` (`_prepare_data_for_altair_timeline`) | INICIO and TERMINO columns |
| Ticket search results | `main.py` (`search_tickets`) | `created` field |
| Service ticket details | `main.py` (`get_service_tickets`) | `created_date` field |

### Example

```
Date in Odoo (UTC):          2025-10-22 18:30:00 UTC
Internal system date:        2025-10-22 18:30:00 UTC+6  (stored for filters)
Date shown to user:          2025-10-22 12:30:00         (-6 hours, display only)
```

### Key Principle

> Internal data always stays in UTC+6 so that date filters, recurrence calculations, and KPIs work correctly. The -6 hour subtraction is purely cosmetic, applied only when formatting dates for the frontend.

### Time Simulation Module

For testing, you can set `SIMULATE_DATE_STR = '2025-10-22'` at the top of `main.py`. This makes `get_current_time()` return a fixed date instead of the real current time. A warning banner appears on all pages when simulation is active.

---

## Complete Application Flow

```
══════════════════════════════════════════════════════════════════════════════════
 PHASE 1: SERVER STARTUP (happens once)
══════════════════════════════════════════════════════════════════════════════════

 gunicorn starts main.py
         │
         ▼
 Flask, Flask-Login initialized
         │
         ▼
 cached_df = pd.DataFrame()  ← Empty cache
         │
         ▼
 BackgroundScheduler starts
         │
         ├──→ Runs fetch_and_process_odoo_data() IMMEDIATELY
         │         │
         │         ├──→ get_odoo_connection() (XML-RPC auth)
         │         ├──→ 1st call: helpdesk.ticket search_read
         │         ├──→ _process_raw_dataframe() (rename, parse, recurrence)
         │         ├──→ 2nd call: running.services search_read
         │         ├──→ Merge tickets + service details
         │         └──→ cached_df = df  ★ CACHE FILLED ★
         │
         └──→ Schedules repeat every 30 minutes
         │
         ▼
 Flask server ready on port 5000

══════════════════════════════════════════════════════════════════════════════════
 PHASE 2: USER OPENS PAGE (happens per visit)
══════════════════════════════════════════════════════════════════════════════════

 User opens https://app-url/
         │
         ▼
 Flask serves templates/index.html + static/app.js
         │
         ▼
 Browser runs DOMContentLoaded
         │
         ├──→ loadKPIs()         → /api/kpis         → KPI cards
         ├──→ loadCharts()       → /api/charts        → Chart.js graphs
         └──→ loadLatestTickets()→ /api/search-tickets → Latest tickets table

══════════════════════════════════════════════════════════════════════════════════
 PHASE 3: USER INTERACTION (on demand)
══════════════════════════════════════════════════════════════════════════════════

 User clicks "Search" or changes filter
         │
         ▼
 searchTickets() → /api/search-tickets?client=X&status=Y
         │
         ▼
 Renders filtered table from cached_df

══════════════════════════════════════════════════════════════════════════════════
 PHASE 4: AUTOMATIC REFRESH (every 30 minutes, background)
══════════════════════════════════════════════════════════════════════════════════

 Scheduler triggers fetch_and_process_odoo_data()
         │
         └──→ Repeats PHASE 1 data fetch silently
              Users see updated data on next API call
```

---

## Guide: Adding New Features

### Adding a New Chart or Table (Standard Pattern)

#### Step 1: Create the endpoint in `main.py`

```python
@app.route('/api/my-new-feature')
@login_required
def my_new_feature():
    if cached_df.empty:
        return jsonify({"error": "No data available."}), 404

    df = cached_df.copy()  # ALWAYS copy, never modify cached_df directly

    # Your logic: filter, calculate, group...
    result = {"key1": value1, "key2": value2}

    return jsonify(result)
```

**Important rules:**
- Always use `cached_df.copy()` (never modify `cached_df` directly)
- Always add `@login_required` to protect the endpoint
- Return JSON with `jsonify()`

#### Step 2: Create the function in `static/app.js`

```javascript
async function loadMyNewFeature() {
    try {
        const data = await apiCall('/api/my-new-feature');

        // Option A: Render a chart
        const ctx = document.getElementById('myNewChart');
        new Chart(ctx, { type: 'bar', data: { labels: data.labels, ... } });

        // Option B: Render a table
        const tbody = document.getElementById('myNewTable');
        tbody.innerHTML = data.items.map(item => `
            <tr><td>${item.name}</td><td>${item.value}</td></tr>
        `).join('');

    } catch (error) {
        console.error('Error:', error);
    }
}
```

#### Step 3: Add the container in the HTML template

```html
<!-- For a chart -->
<canvas id="myNewChart"></canvas>

<!-- For a table -->
<table>
    <thead><tr><th>Name</th><th>Value</th></tr></thead>
    <tbody id="myNewTable"></tbody>
</table>
```

#### Step 4: Decide when it runs

- **On page load:** Add to the `DOMContentLoaded` block in the template's `<script>` tag
- **On click:** Add to an `onclick` attribute on a button

```javascript
// Option A: On page load (in the template's <script> block)
document.addEventListener('DOMContentLoaded', function() {
    // ... existing functions ...
    loadMyNewFeature();  // ← Add here
});

// Option B: On click (in the HTML)
// <button onclick="loadMyNewFeature()">Load Data</button>
```

### Adding a New Odoo Data Source / Model

If you need to query a new Odoo model (e.g., `crm.lead`):

1. **Add the query in `fetch_and_process_odoo_data()`** (after the existing service query):

```python
# Query the new model
new_data = conn['models'].execute_kw(
    conn['db'], conn['uid'], conn['api_key'],
    'your.model.name', 'search_read',
    [domain_filter],
    {'fields': ['field1', 'field2', ...]}
)
```

2. **Process and merge** the new data with the existing DataFrame (or store as a separate global cache variable)

3. **Create endpoints** that read from the new data

### Adding New Fields to the Existing Fetch

If you need additional fields from `helpdesk.ticket`:

1. **Add the field name** to the `odoo_fields` list in `fetch_and_process_odoo_data()`:

```python
odoo_fields = [
    'id', 'name', 'stage_id', ...,
    'your_new_field'  # ← Add here
]
```

2. **If it's a relational field** (returns `[id, name]`), add it to `relational_cols` in `_process_raw_dataframe()`:

```python
relational_cols = [
    'Etapa', 'Cliente', ...,
    'Your New Column'  # ← Add here (after renaming)
]
```

3. **Add the rename mapping** in `_process_raw_dataframe()`:

```python
df.rename(columns={
    ...,
    'your_new_field': 'Your New Column'
}, inplace=True)
```

4. **Restart the server** to trigger a fresh data load

### Adding a New Page with Its Own Routes

1. **Create the template** in `templates/my_page.html` (copy sidebar structure from an existing page)

2. **Add the page route** in `main.py`:

```python
@app.route('/my-page')
@login_required
def my_page():
    return render_template('my_page.html',
                           simulated_date=SIMULATE_DATE_STR,
                           user=current_user)
```

3. **Add API endpoints** for the page's data (following the standard pattern above)

4. **Add a sidebar link** in all templates' `<nav>` sections:

```html
<li class="nav-item">
    <a class="nav-link" href="/my-page">
        <i class="fas fa-icon-name me-2"></i>
        My Page
    </a>
</li>
```

5. **Add initialization** in the template's `<script>` block:

```html
<script>
    document.addEventListener('DOMContentLoaded', function() {
        loadMyPageData();
    });
</script>
```

### Summary Pattern

```
1. main.py     →  @app.route('/api/...')        →  Read cached_df, return JSON
2. app.js      →  async function load...()      →  apiCall(), render in HTML
3. template    →  <canvas> or <tbody>           →  Empty container with unique id
4. DOMContent  →  Add function to init block    →  Runs on page load
```

> All charts, tables, and KPIs in the application follow exactly this pattern. Once understood, any new feature can be built by replicating these steps.
