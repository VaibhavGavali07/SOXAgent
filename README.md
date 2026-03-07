# ITGC SOX Compliance Agent

A production-ready Flask application that continuously monitors IT tickets from JIRA and ServiceNow for ITGC (IT General Controls) compliance violations under SOX §302 and §404. AI-powered audit evidence is generated per violation using your choice of LLM provider.

---

## Features

- **Automated compliance checks** across 9 ITGC controls — access provisioning, segregation of duties, workflow documentation, software controls
- **Dual-source ingestion** — pulls tickets from JIRA and ServiceNow simultaneously in parallel
- **AI-generated audit evidence** — Claude, GPT-4o, Azure OpenAI, or Gemini narrates each violation with full context
- **Evidence Vault** — browse, view, and export evidence packages as JSON or PDF
- **Live dashboard** — compliance score, control coverage, audit readiness KPIs with Chart.js visualizations
- **Custom validation rules** — define field-level compliance rules through the UI with no code required
- **Background scheduler** — continuous auto-monitoring on a configurable interval
- **Notifications** — email (SMTP) and webhook alerts on new violations
- **Real-time progress bar** — live updates during analysis runs via polling

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.x |
| Database | SQLite with WAL mode via Flask-SQLAlchemy |
| Background jobs | APScheduler |
| PDF export | fpdf2 |
| Frontend | Alpine.js + Tailwind CSS + Chart.js |
| LLM (optional) | Anthropic / OpenAI / Azure OpenAI / Google Gemini |

**Python 3.10+** is required.

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd SOXComplianceAgent

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python run.py
```

Open **http://localhost:5000** in your browser.

The SQLite database is created automatically at `~/.itgc_sox_agent/sox_compliance.db` on first run. No migrations are needed.

### Add an LLM API Key (optional)

Navigate to **Connections** → enter your API key → **Save Settings**.

Without a key, the agent still detects all violations via rule-based checks. AI narrative analysis will show a placeholder message until a key is configured.

---

## Configuration

### Environment Variables

Create a `.env` file in the project root (all fields are optional — defaults shown):

```env
SECRET_KEY=your-strong-secret-key-here
DATABASE_URL=sqlite:////path/to/sox_compliance.db
PORT=5000
FLASK_DEBUG=false
```

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `sox-compliance-dev-key-change-in-prod` | Flask session secret — **change in production** |
| `DATABASE_URL` | `~/.itgc_sox_agent/sox_compliance.db` | SQLite database path |
| `PORT` | `5000` | HTTP listen port |
| `FLASK_DEBUG` | `true` | Set to `false` in production |

### Runtime Settings (stored in database)

All integration credentials and operational settings are configured through the **Connections** page in the UI and persisted in the database. No restart is required after changes.

| Category | Settings |
|---|---|
| LLM | Provider, API key, model, temperature |
| JIRA | Instance URL, username, API token |
| ServiceNow | Instance URL, client ID, client secret |
| Monitoring | Enable/disable continuous monitoring, interval (minutes) |
| Notifications | SMTP host/port/credentials, webhook URL, severity threshold |

---

## ITGC Controls

Nine built-in controls are evaluated against every ingested ticket:

| Control ID | Name | Severity | Framework |
|---|---|---|---|
| ITGC-AC-01 | Self-Approval Prevention | High | SOX §404 |
| ITGC-AC-02 | Unauthorized Approver | High | SOX §404 |
| ITGC-AC-03 | Unauthorized Privileged Access | High | SOX §404 / NIST AC-6 |
| ITGC-AC-04 | Missing Approval | High | SOX §404 |
| ITGC-AC-05 | Invalid Approval Timestamp | High | SOX §404 |
| ITGC-WF-01 | Missing Closure Documentation | Medium | SOX §302 |
| ITGC-WF-02 | Missing Implementer Assignment | Medium | SOX §302 |
| ITGC-SOD-01 | Segregation of Duties Violation | High | SOX §404 / COBIT APO01.02 |
| ITGC-SW-01 | Unauthorized Software Installation | Medium | SOX §404 / CIS Control 2 |

Additional controls can be added through the **Validations** page — no code changes required.

---

## Project Structure

```
SOXComplianceAgent/
├── run.py                          # Entry point
├── config.py                       # Controls config, authorized approvers/software lists
├── requirements.txt
└── app/
    ├── __init__.py                 # App factory, SQLite WAL setup, scheduler init
    ├── extensions.py               # SQLAlchemy instance
    ├── scheduler.py                # APScheduler background job
    ├── agent/
    │   ├── checks.py               # Rule-based ITGC compliance checks
    │   ├── compliance_engine.py    # Analysis orchestrator (fetch → check → LLM → notify)
    │   ├── llm_client.py           # Multi-provider LLM wrapper
    │   └── prompts.py              # LLM prompt templates
    ├── models/
    │   └── models.py               # Ticket, Violation, AuditEvidence, CustomRule, Setting
    ├── routes/
    │   ├── main.py                 # HTML page routes
    │   └── api.py                  # REST API endpoints
    ├── services/
    │   ├── jira_service.py         # JIRA REST API integration
    │   ├── snow_service.py         # ServiceNow OAuth2 integration
    │   └── notification_service.py # Email + webhook alerts
    └── templates/
        ├── base.html               # Base layout with nav + Fetch Now button
        ├── dashboard.html          # KPI cards, charts, live alert feed
        ├── tickets.html            # Ticket listing with inline violation tooltips
        ├── violations.html         # Violation viewer with acknowledge/resolve actions
        ├── evidence.html           # Evidence Vault — view, JSON/PDF export
        ├── connections.html        # Integration settings and health checks
        └── validations.html        # Custom rule management
```

---

## Analysis Pipeline

When triggered (manually via the UI or automatically by the scheduler), the engine runs these steps:

```
1. Fetch tickets       JIRA + ServiceNow fetched in parallel
        |
2. Upsert tickets      New tickets inserted; existing tickets updated
        |
3. Run checks          9 built-in ITGC controls + all enabled custom rules
        |
4. Persist violations  Committed per ticket to minimize SQLite lock time
        |
5. Generate evidence   5 parallel LLM calls -> sequential DB writes
        |
6. Send notifications  Email + webhook dispatch for new violations
        |
7. Executive summary   Single LLM call summarising the full run
```

Progress is streamed to the frontend via `GET /api/analyze/progress` so the progress bar updates in real time without blocking the HTTP response.

---

## LLM Providers

The app works fully without an LLM configured — rule-based checks still detect all violations. Adding an API key enables AI-generated audit narratives for each violation.

| Provider | Default Model | Install |
|---|---|---|
| Anthropic (default) | `claude-sonnet-4-6` | `pip install anthropic` |
| OpenAI | `gpt-4o` | `pip install openai` |
| Azure OpenAI | `gpt-4o` | `pip install openai` |
| Google Gemini | `gemini-2.0-flash` | `pip install google-genai` |

Switch providers and test connectivity on the **Connections** page without restarting.

---

## Pages

| URL | Page | Description |
|---|---|---|
| `/` | Dashboard | Compliance score, coverage, readiness KPIs, charts, alert feed |
| `/tickets` | Tickets | All ingested tickets with violation counts and source badges |
| `/violations` | Violations | Full violation list — filter by severity/status, acknowledge or resolve |
| `/evidence` | Evidence Vault | AI-generated audit evidence — view inline, export as JSON or PDF |
| `/connections` | Connections | LLM, JIRA, ServiceNow, SMTP, webhook settings and health checks |
| `/validations` | Validations | Create, edit, enable/disable custom compliance rules |

---

## API Reference

### Analysis

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/analyze` | Trigger full analysis (async — returns `{"started": true}` immediately) |
| `GET` | `/api/analyze/progress` | Poll real-time analysis progress |

### Dashboard

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/stats` | KPIs: compliance score, control coverage, audit readiness |
| `GET` | `/api/alerts` | Latest 25 violations for the live alert feed |

### Violations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/violations` | Paginated list (query params: `severity`, `status`) |
| `POST` | `/api/violations/<id>/acknowledge` | Mark violation as Acknowledged |
| `POST` | `/api/violations/<id>/resolve` | Mark violation as Resolved |

### Evidence

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/evidence` | List all evidence records |
| `GET` | `/api/evidence/<id>` | Single evidence record (JSON) |
| `GET` | `/api/evidence/<id>/export/json` | Download full evidence package as JSON |
| `GET` | `/api/evidence/<id>/export/pdf` | Download formatted audit report as PDF |

### Custom Rules

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/rules` | List all custom validation rules |
| `POST` | `/api/rules` | Create a new rule |
| `PUT` | `/api/rules/<id>` | Update an existing rule |
| `DELETE` | `/api/rules/<id>` | Delete a rule |
| `POST` | `/api/rules/<id>/toggle` | Enable or disable a rule |

### Settings & Health

| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/settings` | Read or save all settings |
| `POST` | `/api/health/llm` | Test LLM API connection |
| `POST` | `/api/health/jira` | Test JIRA connection |
| `POST` | `/api/health/servicenow` | Test ServiceNow connection |
| `POST` | `/api/health/smtp` | Send a test email |
| `POST` | `/api/health/webhook` | Send a test webhook payload |
| `GET` | `/api/scheduler/status` | Scheduler state, next run time, last run status |
| `POST` | `/api/data/reset` | Clear all tickets, violations, and evidence (keeps settings) |

### Trigger analysis via curl

```bash
curl -X POST http://localhost:5000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Integrations

### JIRA

- Authenticates with **Basic Auth** (username + API token)
- Queries issues via JQL from the configured JIRA Cloud or Server instance
- Configure on the Connections page: `jira_url`, `jira_username`, `jira_api_token`

### ServiceNow

- Authenticates with **OAuth 2.0 client credentials** flow
- Queries the `change_request` table via the ServiceNow Table API
- Automatically maps SNOW state codes and priority numbers to human-readable labels
- Configure on the Connections page: `snow_url`, `snow_client_id`, `snow_client_secret`

### Notifications

**Email (SMTP)**
- Sends an HTML violation summary table after each analysis run
- Filters by configurable minimum severity threshold (High / Medium / Low)
- Supports multiple recipients via comma-separated `smtp_to`
- TLS/STARTTLS on port 587 by default; configurable

**Webhooks**
- HTTP POST with a JSON payload to any URL
- Works with Slack Incoming Webhooks, Microsoft Teams, PagerDuty, and similar services

---

## Custom Validation Rules

Beyond the 9 built-in controls, define your own rules through the UI at `/validations`.

**Supported operators:**

| Operator | Behaviour |
|---|---|
| `is_empty` | Field has no value |
| `is_not_empty` | Field has a value |
| `equals` | Field exactly matches the specified value |
| `not_equals` | Field does not match the specified value |
| `contains` | Field contains the value (case-insensitive substring) |
| `not_contains` | Field does not contain the value |

Rules can be scoped to specific ticket statuses or ticket types. They can be toggled on/off at any time without deleting them.

---

## Database Schema

| Table | Purpose |
|---|---|
| `tickets` | Ingested tickets from JIRA / ServiceNow |
| `violations` | Compliance violations detected per ticket |
| `audit_evidence` | AI-generated evidence packages, one per violation |
| `custom_rules` | User-defined validation rules |
| `settings` | Key-value configuration (credentials, toggles) |

The database is created automatically on first run. SQLite WAL journal mode is enabled to support concurrent reads during background analysis jobs without blocking.

---

## Production Deployment

Before going to production:

1. **Set a strong `SECRET_KEY`** in your environment — never use the default dev value
2. **Set `FLASK_DEBUG=false`**
3. **Run behind a reverse proxy** (nginx or Caddy) with HTTPS termination
4. **Add authentication** — the app has no login layer by default; consider Flask-Login or an OAuth reverse proxy
5. **Connect live credentials** for JIRA and ServiceNow on the Connections page
6. **Enable continuous monitoring** on the Connections page and set your preferred interval

Example nginx configuration:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 300s;   # allow time for long analysis runs
    }
}
```

---

## Requirements

```
flask>=3.0.0
flask-sqlalchemy>=3.1.0
fpdf2>=2.7.9
python-dotenv>=1.0.0
requests>=2.31.0
apscheduler>=3.10.0

# LLM providers — install whichever you use
anthropic>=0.40.0
openai>=1.30.0
google-genai>=1.0.0
```

---

## License

For internal use. All audit data is stored locally in the SQLite database — no ticket content or violation data is sent anywhere except to the LLM provider you explicitly configure.
