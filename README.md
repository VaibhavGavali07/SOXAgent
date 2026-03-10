# ITGC SOX Compliance Monitoring Agent

An LLM-powered compliance automation system for SOX Section 404 IT General Controls (ITGC). It connects to ServiceNow, fetches closed and resolved tickets, evaluates them against 4 mandatory SOX controls using a real LLM, stores all results in SQLite, and surfaces findings in a React dashboard with live progress streaming.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Backend Setup](#backend-setup)
- [UI Setup](#ui-setup)
- [Environment Variables](#environment-variables)
- [LLM Provider Configuration](#llm-provider-configuration)
- [ServiceNow Configuration](#servicenow-configuration)
- [SOX Controls Evaluated](#sox-controls-evaluated)
- [How Analysis Works](#how-analysis-works)
- [API Reference](#api-reference)
- [Database Models](#database-models)
- [UI Pages](#ui-pages)
- [Running Tests](#running-tests)
- [Notes](#notes)

---

## Overview

`itgc-sox-agent` automates the manual work of SOX ITGC ticket auditing. Instead of having auditors review hundreds of ServiceNow tickets by hand, the agent:

1. Fetches all closed/resolved tickets from ServiceNow via OAuth 2.0
2. Enriches each ticket with comment history and approval records
3. Sends each ticket to an LLM with a structured SOX audit prompt
4. Parses the LLM's JSON verdict into pass/fail/needs-review per control
5. Stores violations as alerts and streams progress to the UI in real time

> **LLM-first by design.** All control decisions are made by the LLM. If no LLM is configured, the system refuses to run rather than falling back to heuristics.

---

## Features

- **4 core SOX ITGC rules** evaluated per ticket (self-approval, missing documentation, unauthorized software, missing approval)
- **ServiceNow integration** — OAuth 2.0 client credentials, batch comment and approval enrichment, closed/resolved tickets only (`state=6` or `state=7`)
- **Pluggable LLM providers** — OpenAI, Azure OpenAI, Google Gemini; all configured from the UI, no hardcoded keys
- **Strict Pydantic validation** of LLM JSON output with automatic repair for malformed/incomplete responses
- **Real-time SSE progress stream** at `/api/runs/{run_id}/events`
- **Run mode choice** — "Clean & Run" (wipe existing data first) or "Fetch New Tickets" (append) before every run
- **Approved software list** — configurable per-deployment from the Rules page, injected into the LLM prompt for ITGC-SW-01 checks
- **Compliance dashboard** — score, readiness %, severity breakdown chart, control breakdown chart, recent alert feed
- **Clickable ServiceNow links** — every ticket number links directly to the source ServiceNow record
- **Sticky sidebar navigation** with persistent layout
- **SQLite persistence** — full audit trail of runs, evaluations, rule results, alerts, and reports
- **Lightweight cosine-similarity retrieval** from SQLite embeddings for similar violation context

---

## Architecture

```
ServiceNow REST API
        │
        ▼
ServiceNowConnector          ← OAuth token, table query, batch
  ├── _fetch_activity()         journal comments (sys_journal_field)
  └── _fetch_approvals()        approval records (sysapproval_approver)
        │
        ▼
normalize_servicenow_ticket() ← canonical ticket model
        │
        ▼
AnalyzerService.run()
  ├── create_ticket() in SQLite
  ├── build_ticket_prompt()    ← system instructions + metadata + software list +
  │                              controls + comment trail + return schema
  ├── LLMEvaluator.evaluate_ticket()
  │     └── chat_provider.complete_json()   ← real LLM only (error if mock)
  │           └── _parse_new_schema()       ← maps checks[] → RuleResultRecord
  ├── replace_rule_results()
  ├── create_alerts_for_failures()
  └── SSE publish → /api/runs/{run_id}/events
```

---

## Project Structure

```
itgc-sox-agent/
├── backend/
│   ├── api/
│   │   ├── routes_config.py       # LLM / ServiceNow / notification config + test endpoints
│   │   ├── routes_dashboard.py    # Dashboard summary and SSE event stream
│   │   ├── routes_fetch.py        # Trigger fetch + analysis runs
│   │   ├── routes_rules.py        # Rule management
│   │   ├── routes_tickets.py      # Ticket queries
│   │   └── routes_violations.py   # Violations / alerts queries
│   ├── connectors/
│   │   ├── servicenow_connector.py  # OAuth, table query, comment + approval enrichment
│   │   └── normalize.py             # Canonical ticket normalization
│   ├── llm/
│   │   ├── chat_client.py           # OpenAI / AzureOpenAI / Gemini / Mock providers
│   │   ├── embed_client.py          # SHA256 embeddings + cosine similarity
│   │   ├── llm_evaluator.py         # Prompt dispatch, response parsing, rule catalog
│   │   ├── prompts.py               # SOX audit prompt builder
│   │   ├── provider_factory.py      # Loads saved LLM config from DB
│   │   └── rule_ids.py              # Canonical rule ID normalization
│   ├── services/
│   │   ├── analyzer_service.py      # Main pipeline, RunStateStore (SSE), background jobs
│   │   ├── evidence_service.py      # Timeline builder, policy snippets
│   │   └── notification_service.py  # Webhook / email notifications
│   ├── storage/
│   │   ├── db.py                    # SQLAlchemy engine and session factory
│   │   ├── models.py                # ORM models + Pydantic contracts
│   │   └── crud.py                  # All database operations
│   ├── tests/
│   │   ├── test_analysis_pipeline_mock_llm.py
│   │   ├── test_llm_config_usage.py
│   │   └── test_llm_payload_contracts.py
│   └── main.py                      # FastAPI app, router registration, CORS
├── ui/
│   ├── src/
│   │   ├── api/client.js            # Fetch-based typed API client
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx        # Metrics, charts, alert feed
│   │   │   ├── TicketInfo.jsx       # Ticket list + detail with rule results
│   │   │   ├── Violations.jsx       # Violations table with filters
│   │   │   ├── Rules.jsx            # Rule list + approved software editor
│   │   │   └── Connections.jsx      # LLM / ServiceNow / notifications config
│   │   ├── components/
│   │   │   ├── RunModeModal.jsx     # Clean & Run vs Fetch New Tickets chooser
│   │   │   ├── RealtimeStatus.jsx   # SSE event log display
│   │   │   ├── SidebarNav.jsx       # Sticky sidebar navigation
│   │   │   ├── ConnectionForms.jsx  # Config forms with test buttons
│   │   │   └── ...
│   │   └── App.jsx                  # Root component, global state, SSE listener
│   ├── package.json
│   └── vite.config.js
├── requirements.txt
├── .env.example
└── README.md
```

---

## Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- A ServiceNow developer instance (or PDI) with OAuth app registered
- One of: OpenAI API key, Azure OpenAI deployment, or Google Gemini API key

---

## Backend Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and edit environment config
cp .env.example .env
# Edit .env — set at minimum DB_PATH and leave MOCK_LLM=true until you have an LLM key

# 4. Start the API server
uvicorn backend.main:app --reload
```

The backend runs on `http://127.0.0.1:8000`.

Useful URLs:
| URL | Description |
|-----|-------------|
| `http://127.0.0.1:8000/` | Service status |
| `http://127.0.0.1:8000/api/health` | Health check |
| `http://127.0.0.1:8000/docs` | Swagger UI |

---

## UI Setup

```bash
cd ui
npm install
npm run dev
```

The Vite dev server runs on `http://127.0.0.1:5173` and proxies API calls to `http://127.0.0.1:8000` by default.

To point the UI at a different backend:

```bash
# ui/.env
VITE_API_BASE_URL=http://your-backend-host:8000
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values you need.

```env
# ── Database ──────────────────────────────────────────────
DB_PATH=./itgc_sox_agent.db

# ── Feature flags ─────────────────────────────────────────
MOCK_LLM=true               # true = raise error if no real LLM configured
ENABLE_EMBEDDINGS=true      # enable cosine similarity for similar violation lookup

# ── LLM provider (overridden by UI config when saved) ─────
LLM_PROVIDER=mock           # mock | openai | azure_openai | gemini

# ── OpenAI ────────────────────────────────────────────────
OPENAI_API_KEY=
OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini

# ── Azure OpenAI ──────────────────────────────────────────
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1-mini
AZURE_OPENAI_API_VERSION=2024-02-01      # optional — defaults to 2024-02-01

# ── Google Gemini ─────────────────────────────────────────
GEMINI_API_KEY=
GEMINI_DEPLOYMENT_NAME=gemini-2.0-flash

# ── ServiceNow ────────────────────────────────────────────
SERVICENOW_INSTANCE_URL=
SERVICENOW_CLIENT_ID=
SERVICENOW_CLIENT_SECRET=

# ── Notifications ─────────────────────────────────────────
NOTIFICATION_WEBHOOK_URL=
NOTIFICATION_EMAIL_TO=audit@example.com
```

> All connection credentials can also be configured from the **Connections** page in the UI. Values saved through the UI are stored in SQLite and take precedence over `.env` values. Secret fields (keys, tokens, passwords) are never returned to the frontend after saving.

---

## LLM Provider Configuration

Configure from the UI at **Connections → LLM Provider**, or via `.env`.

| Provider | Required fields |
|----------|----------------|
| `openai` | API key, deployment name (model) |
| `azure_openai` | API key, endpoint URL, deployment name, API version (optional, defaults to `2024-02-01`) |
| `gemini` | API key, model name |

> If no real LLM provider is configured, the system returns an error when analysis is triggered — it does not fall back to programmatic checks.

Use **Test** on the Connections page to verify credentials before running analysis.

---

## ServiceNow Configuration

Configure from **Connections → ServiceNow**, or via `.env`.

| Field | Description |
|-------|-------------|
| `instance_url` | Full URL of your ServiceNow instance, e.g. `https://dev12345.service-now.com` |
| `client_id` | OAuth application Client ID |
| `client_secret` | OAuth application Client Secret |
| `table` | Table to query: `incident` (default), `sc_request`, or `change_request` |

The connector:
- Authenticates via OAuth 2.0 `client_credentials` grant (`/oauth_token.do`)
- Queries only `state=6` (Resolved) or `state=7` (Closed) tickets
- Batch-fetches comment history from `sys_journal_field`
- Batch-fetches approval records from `sysapproval_approver` (approved/rejected decisions only)

---

## SOX Controls Evaluated

All 4 controls are evaluated by the LLM per ticket. The approved software list for ITGC-SW-01 is editable from the **Rules** page.

| Rule ID | Name | Severity | SOX Mapping | Description |
|---------|------|----------|-------------|-------------|
| `ITGC-AC-01` | Self-Approval Prevention | HIGH | SOX ITGC AC-1 | The ticket requestor and the approver must be different people |
| `ITGC-WF-01` | Missing Closure Documentation | MEDIUM | SOX ITGC OP-5 | Closed/resolved tickets must contain meaningful closure evidence, not just a generic note |
| `ITGC-SW-01` | Unauthorized Software Installation | MEDIUM | SOX ITGC CM-1 | Software mentioned in software-related tickets must appear on the approved software list |
| `ITGC-AC-04` | Missing Approval | HIGH | SOX ITGC AC-4 | Closed tickets must show approval evidence from a comment, workflow record, or referenced proof |

Each rule result includes:
- `status` — `PASS`, `FAIL`, or `NEEDS_REVIEW`
- `confidence` — float 0–1
- `why` — concise auditor-style explanation
- `evidence` — list of evidence items (comment snippet, approval record, field value)
- `recommended_action` — remediation guidance

---

## How Analysis Works

### Run modes

Every time you trigger an analysis (from the header button or the Tickets page), a modal appears with two options:

| Mode | Behaviour |
|------|-----------|
| **Clean & Run** | Deletes all existing tickets, results, and alerts from SQLite, then fetches fresh data and analyses |
| **Fetch New Tickets** | Fetches tickets from ServiceNow and analyses without touching existing data |

### Pipeline steps

1. **Fetch** — `ServiceNowConnector.fetch()` calls the ServiceNow REST API, enriches each ticket with journal comments and approval records, and normalises the result into a canonical schema.
2. **Persist** — Each ticket is saved to `TicketRecord`. A `LLMRunRecord` tracks overall run progress.
3. **Prompt** — `build_ticket_prompt()` constructs a structured SOX audit prompt containing: system role, ticket metadata, approved software list, the 4 control definitions, the full comment trail, and the expected JSON return schema.
4. **Evaluate** — The prompt is sent to the configured LLM provider via `chat.completions.create()` with `response_format={"type": "json_object"}`. The response is parsed by `_parse_new_schema()`.
5. **Store** — Rule results are written to `RuleResultRecord`. Failures create `AlertRecord` entries.
6. **Stream** — SSE events are published after each ticket, showing ticket ID, progress count, and any failed rules. The UI displays live progress in the header bar.
7. **Report** — On completion, `AuditReportRecord` is written with run-level counts and the dashboard summary is refreshed.

### Re-running a single ticket

On the **Tickets** page, select any ticket and click **Re-run LLM Evaluation**. This re-sends that ticket's canonical JSON through the full prompt and evaluation pipeline using the latest LLM config.

---

## API Reference

### Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/configs` | List all saved configurations |
| `POST` | `/api/configs` | Save or update a configuration |
| `POST` | `/api/llm/test` | Test LLM provider connection |
| `POST` | `/api/servicenow/test` | Test ServiceNow connection |
| `POST` | `/api/notifications/test` | Validate notification settings |
| `POST` | `/api/data/clear` | Delete compliance data (optionally including configs) |

### Analysis

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/fetch/servicenow` | Start a ServiceNow fetch + analysis run (background) |
| `POST` | `/api/analyze/ticket/{id}` | Re-run analysis on a single ticket |

### Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/summary` | Compliance metrics, charts data, recent alerts |
| `GET` | `/api/runs/{run_id}/events` | SSE stream of run progress events |

### Tickets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tickets` | List tickets (`?source=`, `?status=`, `?ticket_type=`, `?q=`) |
| `GET` | `/api/tickets/{id}` | Ticket detail with all rule results and LLM response |

### Violations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/violations` | List violations (`?severity=`, `?rule_id=`, `?source=`, `?date_from=`, `?date_to=`) |
| `GET` | `/api/violations/{id}` | Violation detail with related ticket context |

### Rules

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/rules` | List default and custom rules |
| `POST` | `/api/rules` | Create a custom rule |

### Utility

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service status |
| `GET` | `/api/health` | Health check |

---

## Database Models

| Table | Purpose |
|-------|---------|
| `configs` | LLM, ServiceNow, notification, and compliance settings |
| `raw_records` | Unmodified API payloads from connectors |
| `tickets` | Normalised tickets with canonical JSON |
| `embeddings` | SHA256-based vectors for cosine similarity lookup |
| `llm_runs` | Run metadata — status, progress counts, timestamps |
| `llm_responses` | Full LLM prompts and JSON responses per ticket |
| `rule_results` | Per-rule evaluation outcome for each ticket/run |
| `alerts` | Compliance violations (one per FAIL result) |
| `audit_reports` | Aggregated run summaries |
| `notifications` | Queued and sent notification records |

---

## UI Pages

### Dashboard
- Compliance score (passed / total checks × 100)
- Audit readiness score (weighted — needs_review counts half)
- Control Coverage (total rule evaluations run)
- Tickets Analysed, High Risk, Medium Risk counts (clickable — filters ticket view)
- Violations by Severity (pie chart)
- Violations by Control Type (bar chart)
- Live Compliance Alert Feed (5 most recent)
- Real-time run progress bar with SSE event log

### Tickets
- Searchable, filterable ticket table (source, status, type, priority, min failed checks)
- Ticket number links directly to the ServiceNow record
- Detail panel on row click: canonical JSON viewer + per-rule verdict cards
- **Refresh & Analyze** triggers the run mode modal
- **Re-run LLM Evaluation** for individual tickets

### Violations
- Filterable violations list (severity, rule, source, date range)
- Violation detail with evidence snippets and recommended action

### Rules
- List of all 4 default controls with severity and control mapping
- **Edit list** inline expander on the ITGC-SW-01 row to manage the approved software list
- Custom rule creation form (rule_id, name, severity, description, recommended action, control mapping)

### Connections
- **LLM Provider** — provider selector, deployment name, API key, endpoint, API version (optional)
- **ServiceNow** — instance URL, client ID, client secret, table
- **Notifications** — webhook URL, email recipient
- **Test** button per section, **Save** persists to SQLite
- **Clear Compliance Data** — destructive action with optional config deletion

---

## Running Tests

```bash
pytest backend/tests -q
```

Tests force `MOCK_LLM=true` and validate:
- Full API pipeline (fetch → persist → evaluate → alert)
- LLM config loading and provider selection
- Pydantic output contract enforcement (evidence required for FAIL/NEEDS_REVIEW)

---

## Notes

- Secrets are never hardcoded. All credentials are stored in SQLite via the `configs` table and never returned to the frontend after saving.
- ServiceNow uses OAuth `client_credentials` — register an OAuth application in your ServiceNow instance and use the generated `client_id` and `client_secret`.
- Rule IDs follow ITGC naming: `ITGC-AC-01`, `ITGC-WF-01`, `ITGC-SW-01`, `ITGC-AC-04`.
- The LLM is the sole source of control decisions. There are no programmatic fallback checks.
- The `api_version` field for Azure OpenAI is optional and defaults to `2024-02-01`.
- The `temperature` parameter is not sent to the LLM to ensure compatibility with reasoning models (o-series) that only support the default value.
