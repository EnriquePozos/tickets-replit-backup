# Comprehensive Documentation Overhaul

## What & Why
The readme.md and replit.md need a major update to serve as complete technical references for the project. Current docs are partially outdated (reference Google Sheets instead of Odoo, incomplete API catalog, no environment/deployment details, no connection diagrams for services). The goal is to make both files accurate, thorough, and useful for any developer joining the project.

## Done looks like
- **readme.md** is a complete technical guide covering: architecture diagrams (3-layer + connection flow), full API catalog (all 22 endpoints with parameters/responses), Odoo integration details (XML-RPC connection, two data models queried, field mappings), cache system documentation, scheduler behavior, date/timezone handling, frontend-backend communication pattern, and a step-by-step guide for adding new features or integrating new Odoo models
- **replit.md** is an accurate project summary covering: correct file structure (main.py monolith, auth.py, templates/, static/), real dependencies (Flask, pandas, xmlrpc, APScheduler — not gspread/oauth2client), Odoo as the data source (not Google Sheets), environment variables catalog (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY, SESSION_SECRET, AUTHORIZED_USERS), deployment notes, and data flow description matching the actual cache-based architecture
- Both files reflect the actual current codebase with no stale references

## Out of scope
- Code refactoring (the documentation describes the codebase as-is)
- Adding new features or endpoints
- Changing application behavior

## Tasks
1. **Update replit.md** — Replace all outdated references (Google Sheets → Odoo, gspread → xmlrpc.client), update file structure to match reality, document all environment variables, correct the data flow to reflect the Odoo XML-RPC + cache pattern, and list actual Python/frontend dependencies.

2. **Rewrite readme.md architecture section** — Update the 3-layer diagram to accurately reflect current modules, add a connection diagram showing Odoo XML-RPC flow (authentication → ticket query → service query → cache), and document the BackgroundScheduler lifecycle.

3. **Add full API catalog to readme.md** — Document all 22 endpoints organized by category (Auth, Pages, Admin, Status/Control, Dashboard, Tickets, Reports, Analysis) with HTTP method, URL, query parameters, response shape, and which cache data each reads.

4. **Add live environment & services section to readme.md** — Document how the Odoo connection works (XML-RPC protocol, credential flow, two models queried: helpdesk.ticket and running.services), field mappings from Odoo to internal DataFrame columns, and the service detail enrichment process (delivery_type, radio_base_id, providing_company).

5. **Update the "new feature" guide in readme.md** — Expand the existing guide to also cover: how to add a new Odoo data source/model, how to add new fields to the existing fetch, and how to create a new page with its own routes and frontend functions.

## Relevant files
- `readme.md`
- `replit.md`
- `main.py`
- `auth.py`
- `static/app.js`
- `templates/index.html`
- `templates/analysis.html`
- `templates/tickets.html`
- `templates/repeat_report.html`
