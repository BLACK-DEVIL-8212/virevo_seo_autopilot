# AI SEO Autopilot

A fully-functional autonomous AI SEO optimization platform written entirely in Python.

The application can connect to your website (via Public URL, FTP, SFTP, or SSH), crawl it,
detect the underlying technology, run a comprehensive SEO audit, research keywords, generate
an AI-driven optimization plan, validate every change, create backups, deploy modifications,
verify them publicly, monitor performance, and continuously suggest improvements.

Built with:
- **Flask** for the web framework
- **SQLAlchemy** for the database (SQLite by default; PostgreSQL supported)
- **BeautifulSoup** + custom HTML parser for safe HTML modification
- **Paramiko** for SFTP/SSH
- **APScheduler** for background jobs
- A pluggable **AI provider** abstraction (`mock`, `openai`, `anthropic`, `huggingface`)
- A pluggable **keyword/trend/search-performance/competitor provider** architecture
- 100% server-rendered HTML templates — no JavaScript framework required

## Project structure

```
ai_seo_autopilot/
├── app/
│   ├── main.py                  # Flask app factory and routes
│   ├── config.py                # Environment-driven configuration
│   ├── frontend/                # Jinja2 templates + CSS
│   ├── agents/                  # SEO, planner, orchestrator, risk agents
│   ├── ai/                      # AI provider abstraction
│   ├── connections/             # FTP, SFTP, SSH, public URL clients
│   ├── database/                # SQLAlchemy models
│   ├── deployment/              # Backup, validation, deploy, rollback
│   ├── modifiers/               # HTML modifier engine
│   ├── providers/               # Keyword/trend/competitor provider interfaces
│   ├── seo/                     # SEO audit, sitemap, robots
│   ├── security/                # Credential encryption
│   ├── tasks/                   # Background job system
│   └── website/                 # Crawler, renderer, tech detector, URL mapper
├── tests/                       # Automated tests
├── requirements.txt
├── .env.example
└── run.py                       # Entry point
```

## Installation

```bash
cd ai_seo_autopilot
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Generate an encryption key for stored credentials (optional but recommended):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output into `CREDENTIAL_ENCRYPTION_KEY` in your `.env` file.

Copy the example env:

```bash
cp .env.example .env   # or just copy on Windows
```

## Running locally

```bash
python run.py
```

The application starts at <http://127.0.0.1:5000> and opens directly on the dashboard — no login/signup.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `APP_SECRET_KEY` | Flask session secret | `dev-secret-change-me` |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./ai_seo.db` |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for credential encryption | (none) |
| `AI_PROVIDER` | `mock`, `openai`, `anthropic`, `huggingface` | `mock` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `HUGGINGFACE_API_KEY` | AI API keys | — |
| `AI_MODEL` | Model name | `user052/EDIATH-Q4_K_M` |
| `CRAWL_MAX_PAGES` | Max pages per crawl | `50` |
| `CRAWL_MAX_DEPTH` | Max link depth | `3` |
| `CRAWL_DELAY_SECONDS` | Polite delay between requests | `0.5` |
| `SEO_AUTOMATION_MODE` | `analysis_only`, `safe_autopilot`, `full_autonomous` | `safe_autopilot` |

## Database

Default uses SQLite (`ai_seo.db` in the project root). For production PostgreSQL:

```
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/aiseo
```

## Connecting a website

Open **Connect Website**, choose a connection mode:

- **Public URL only** — works without hosting credentials. The app crawls
  the live website, runs the full SEO audit, builds an AI plan, and shows
  manual deployment steps.
- **FTP / SFTP / SSH** — provides full read/write access for autonomous
  modification. The app can apply safe SEO changes directly to the server
  after creating a backup.

## SEO automation modes

| Mode | Behavior |
|---|---|
| `analysis_only` | No changes are deployed, ever. |
| `safe_autopilot` | Low-risk changes (missing meta description, ALT text, OG tags, etc.) are deployed automatically. Higher-risk changes are queued for review. |
| `full_autonomous` | Low- and medium-risk changes are deployed automatically. |

In every mode:
- **Backups** are created before any modification
- **Validation** runs before any upload
- **Audit logs** capture every action
- **Rollback** restores the exact prior file from the backup

## How analysis works

1. The orchestrator runs the **WebsiteCrawler** with polite delays and `robots.txt` awareness.
2. Each page is parsed to extract titles, descriptions, headings, images, links, structured data, and more.
3. The **SEO audit engine** identifies missing/duplicate/poor metadata, thin content, heading issues, broken links, etc.
4. The **AI planner** transforms these issues into structured actions with confidence scores, risk levels, and a rollback record.
5. The **keyword research provider** produces intent-tagged keyword opportunities.

## How deployment works (Public URL mode)

When a public-only connection is configured, the application can deploy SEO
fixes by:

1. Fetching the page
2. Parsing and modifying it with BeautifulSoup (no string replacement)
3. Validating (HTML well-formedness, JSON-LD, no content loss)
4. Creating a backup of the original content (always; rollback-safe)
5. Recording the change in the database
6. The actual upload to your server requires FTP/SFTP/SSH credentials

When the connection is SFTP/FTP:
- The deployer uploads the modified file in place of the original
- The original is preserved in the local backup store
- A verification HTTP fetch confirms the new metadata is publicly live

## How backups & rollback work

Every modification:

- Creates a `Backup` row with: change ID, server file path, SHA256 hash, byte size, local path
- Stores the actual file in `backups/`
- Records the `before` and `after` HTML in `SEOChange`
- Records the deployment result in `Deployment`

Rollback from the **Changes & Rollback** page restores the exact previous
bytes and (for writeable connections) re-uploads them.

## Running tests

```bash
python tests/test_core.py
python tests/test_backup.py
python tests/test_deploy.py
```

## Current limitations

- The bundled local keyword/trend/competitor providers use heuristic data
  suitable for planning and UI. Plug real APIs (SEMrush, SerpAPI, Google
  Search Console) via the provider interface to get live numbers.
- The crawler uses raw HTTP requests. Install `playwright` and add the
  `browser` for true client-side rendering.
- AI-generated copy from the bundled mock provider is conservative. Set
  `AI_PROVIDER=openai` (or `anthropic`, `huggingface`) with valid API keys to unlock richer
  recommendations.

## Phase coverage

| Phase | Status |
|---|---|
| 1 — Foundation (project, DB, Flask UI, connections) | ✓ |
| 2 — Website intelligence (crawler, tech detection, URL mapping) | ✓ |
| 3 — SEO engine (metadata, content, links, technical) | ✓ |
| 4 — AI system (provider, agents, planner, risk) | ✓ |
| 5 — Server modification (backup, HTML mods, deploy, verify, rollback) | ✓ |
| 6 — Research (keyword/trend/competitor providers) | ✓ (local adapters) |
| 7 — Monitoring (snapshots, provider adapters) | ✓ (data layer + adapters) |

## Security

- Hosting credentials encrypted at rest with Fernet (AES-128 + HMAC).
- Passwords masked in the UI.
- Credentials never logged.
- The AI never modifies files outside the configured website root.
- Every change has a rollback record before deployment.

## License

MIT