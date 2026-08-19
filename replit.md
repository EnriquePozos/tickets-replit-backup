# Ticket Dashboard Application

## Overview

A web-based ticket management dashboard that fetches and visualizes live helpdesk ticket data from Odoo via XML-RPC. The application provides four main views: a dashboard overview with KPIs and charts, a repeat report for recurring service tickets, a service timeline analysis with Altair/Vega visualizations, and a ticket search interface. Built as a Flask monolith with a Bootstrap/Chart.js frontend.

## User Preferences

Preferred communication style: Simple, everyday language.
Authentication: Simple login system with controlled access via username/password.

## System Architecture

### Data Source
- **Odoo ERP** (odoo.wispi.mx) connected via XML-RPC (`xmlrpc.client`)
- Two Odoo models queried: `helpdesk.ticket` and `running.services`
- Data cached in-memory as a Pandas DataFrame (`cached_df`), refreshed every 30 minutes by APScheduler

### Backend Architecture
- **Framework**: Flask (Python web framework), single monolith in `main.py`
- **Data Processing**: Pandas for DataFrame manipulation, NumPy for calculations
- **Visualization (server-side)**: Altair for interactive timeline charts (rendered as Vega-Lite HTML)
- **Scheduler**: APScheduler `BackgroundScheduler` runs `fetch_and_process_odoo_data()` every 30 minutes
- **User Authentication**: Flask-Login with simple username/password system (defined in `auth.py`)
- **Session Management**: Flask sessions with `SESSION_SECRET` environment variable
- **Access Control**: All dashboard and API routes protected with `@login_required`

### Frontend Architecture
- **Technology Stack**: HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3.0
- **Charts**: Chart.js for bar/line/pie charts, Vega/Vega-Lite/Vega-Embed for Altair timeline rendering
- **Icons**: Font Awesome 6.4.0
- **Fonts**: Inter font family
- **Structure**: Multi-page app with shared `app.js` and per-page `DOMContentLoaded` initialization

## File Structure

```
/
├── main.py                    # Flask backend: all routes, Odoo connection, data processing, API endpoints
├── auth.py                    # Authentication: User class, UserManager, password hashing
├── main_backup.py             # Backup copy of main.py
├── readme.md                  # Technical guide (detailed architecture, API catalog, developer guide)
├── replit.md                  # This file (project summary for agent context)
├── templates/
│   ├── index.html             # Dashboard page (KPIs, charts, latest tickets)
│   ├── repeat_report.html     # Repeat report page (recurring service tickets)
│   ├── analysis.html          # Service timeline analysis page (Altair/Vega charts)
│   ├── tickets.html           # Ticket search and filtering page
│   ├── login.html             # Login page
│   └── admin.html             # Admin panel for user management
└── static/
    ├── app.js                 # All frontend JavaScript (API calls, charts, tables, filtering)
    └── style.css              # Custom CSS with color palette and responsive design
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ODOO_URL` | Odoo instance URL (e.g., `https://odoo.wispi.mx`) |
| `ODOO_DB` | Odoo database name |
| `ODOO_USER` | Odoo username for XML-RPC authentication |
| `ODOO_API_KEY` | Odoo API key for XML-RPC authentication |
| `SESSION_SECRET` | Flask session encryption key |
| `AUTHORIZED_USERS` | Optional comma-separated `username:password` pairs (overrides default admin user) |

## Data Flow

1. **Startup**: Flask initializes, APScheduler starts, `fetch_and_process_odoo_data()` runs immediately
2. **Odoo Fetch**: Connects via XML-RPC, authenticates, queries `helpdesk.ticket` (with date/team filters) and `running.services` (by service IDs from tickets)
3. **Processing**: Raw Odoo data is converted to a Pandas DataFrame, columns renamed to Spanish labels, dates parsed and timezone-adjusted (UTC+6), relational fields extracted, recurrence calculated
4. **Cache**: Processed DataFrame stored in global `cached_df` variable; refreshed every 30 minutes
5. **API Endpoints**: All `/api/*` routes read from `cached_df.copy()`, never call Odoo directly
6. **Frontend**: JavaScript functions call API endpoints via `fetch()`, render data using Chart.js or DOM manipulation

## Key Dependencies

### Python (actively used at runtime)
- Flask, Flask-Login (web framework + auth)
- pandas, numpy (data processing)
- altair (server-side timeline chart generation)
- xmlrpc.client (stdlib, Odoo XML-RPC connection)
- APScheduler (background data refresh)
- gunicorn (production WSGI server)

Note: `pyproject.toml` may still list legacy packages (e.g., `gspread`, `oauth2client`) from a previous Google Sheets integration. These are no longer used at runtime but remain installed.

### Frontend (CDN)
- Bootstrap 5.3.0 (CSS framework)
- Chart.js (charting)
- Vega 5 / Vega-Lite 5 / Vega-Embed 6 (Altair chart rendering on analysis page)
- Font Awesome 6.4.0 (icons)
- Google Fonts Inter (typography)

## Deployment

- Designed for Replit deployment with gunicorn on port 5000
- All credentials stored as environment variables (never hardcoded)
- No external database required; data lives in-memory cache refreshed from Odoo
- Static files served through Flask's static file handling
- Time simulation module available (`SIMULATE_DATE_STR` in main.py) for testing with fixed dates
