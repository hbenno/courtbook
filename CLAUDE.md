# CourtBook - Project Context for Claude Code

## What This Is

CourtBook is a court and course booking platform being built for Hackney Tennis, a tennis charity operating across 7 parks in Hackney, London (28 bookable courts + 2 mini courts). The long-term vision is a multi-tenant SaaS serving 2,000+ UK tennis venues and eventually a global platform.

The project owner is Howard, who is a cattle futures trader by day and a trustee/volunteer for Hackney Tennis. He codes in Python and is not a beginner. The current booking system is ClubSpark (LTA's platform), which is stagnant and inadequate.

## Architecture

- **Backend:** Python 3.12, FastAPI (async), SQLAlchemy 2.0 async with asyncpg
- **Database:** PostgreSQL 16 (chosen for: ACID transactions for credit ledger, row-level security for multi-tenancy, PostGIS for court discovery at scale, relational joins for fairness solver, jsonb for flexible config)
- **Cache/Queue:** Redis 7, Celery (task queue for fairness solver jobs, notifications)
- **Frontend:** React + TypeScript + Vite + Tailwind (Phase 1, not started yet)
- **Local dev:** Docker Compose (PostgreSQL, Redis, FastAPI with hot-reload, Celery worker, Mailpit for email capture)
- **Solver:** Google OR-Tools CP-SAT for fairness allocation (Phase 4)
- **Payments:** Stripe (cards) + GoCardless (Direct Debit) — Stripe Connect from the start for multi-tenant fund separation
- **Accounting:** Xero API integration (Phase 2)

### Key Architectural Decisions

- **FastAPI over Django:** Async-native, OpenAPI auto-docs, no dead weight (Django admin/templates unnecessary for headless API + PWA)
- **PWA over native apps:** Single codebase, no app store approval, instant updates. React Native WebView wrapper as fallback if App Store presence needed
- **Per-tenant database isolation** for Phase 6 SaaS, but tenant-aware data access layer designed from day one (ContextVar for current_tenant_id)
- **Solver as a service boundary:** Clean API interface even though it runs in-process now, so it can be extracted later
- **Celery over Dramatiq/ARQ:** Battle-tested, well-documented failure modes, same Redis broker
- **Passlib with bcrypt==4.0.1 pinned** due to passlib abandonment / newer bcrypt incompatibility

## Current State (Phase 0 — Complete except ClubSpark investigation)

### Done
- Repository structure (monorepo: /api, /web, /docker, /docs, /scripts)
- Docker Compose environment fully working
- Database models: Organisation, Site, Resource, User, MembershipTier, OrgMembership, Booking
- Async SQLAlchemy with tenant-aware session management
- FastAPI skeleton with OpenAPI docs at /api/v1/docs
- JWT authentication (register, login, refresh, me)
- Alembic configured for async migrations, initial migration applied
- Seed data with correct park/court data (see below)
- **Booking rules enforcement service** (`app/services/booking_rules.py`):
  - Advance booking window (7 days for members, 28 for coaches, opens at 9pm)
  - Max concurrent bookings (7 for members, 999 for coaches)
  - Max daily minutes (120 for members = 2 hours, 240 for coaches = 4 hours)
  - Cancellation deadline (24 hours for members, 36 for coaches)
  - Slot duration validation (60 or 120 minutes)
  - Court conflict detection (no double-booking)
  - All violations returned in one response with clear messages
  - Duration formatting: shows hours when divisible by 60, minutes otherwise
- **RBAC middleware** (`app/core/dependencies.py`):
  - `get_org_membership` — resolves user's membership within org by URL slug
  - `require_org_role(*roles)` — factory returning dependency that checks OrgRole
  - Convenience shortcuts: `require_org_admin`, `require_org_coach`, `require_org_member`
  - Platform admins (UserRole.ADMIN/SUPERADMIN) bypass all org-level checks
  - Demo endpoint: `GET /orgs/{slug}/members` (requires org admin)
- **GitHub Actions CI** (`.github/workflows/ci.yml`):
  - Lint job: ruff check, ruff format --check, mypy
  - Test job: pytest with PostgreSQL 16 service container
  - All passing on main branch
- **CSV import pipeline** (`scripts/import_csv.py`):
  - `python -m scripts.import_csv members <csv> [--dry-run]`
  - `python -m scripts.import_csv bookings <csv> [--dry-run]`
  - Column mappings are configurable dicts at top of file — update when real ClubSpark CSVs are available
  - Deduplication, error reporting, dry-run mode, audit trail in JSONB extra field
  - Tested with sample data, idempotent re-runs

### Not Done Yet (Remaining Phase 0)
- ClubSpark API investigation (manual browser task — use dev tools to map internal endpoints)

### Ready for Phase 1
Phase 1 is "Minimum viable booking" — React PWA frontend, FCFS booking, Stripe test mode, preferences. The backend API is ready.

## Hackney Tennis Data

### Parks and Courts (in display order)

1. **Clissold Park** (N16 9HJ) — 8 courts + 2 mini courts. Courts 2-7 floodlit. All hard.
2. **Hackney Downs** (E5 8ND) — 5 courts (4 bookable). Courts 3-4 floodlit. Court 5 is turn-up-and-play only (marked is_active=False). All hard.
3. **Millfields Park** (E5 0AR) — 4 courts. No floodlights. All hard.
4. **Spring Hill** (E5 9BL) — 3 courts. No floodlights. All hard.
5. **Springfield Park** (E5 9EF) — 5 courts. No floodlights. All hard.
6. **London Fields** (E8 3EU) — 2 courts. No floodlights. All hard.
7. **Joe White Gardens** (E8 1HH) — 1 court. No floodlights. Hard.

Total: 27 bookable courts + 2 mini courts + 1 non-bookable = 30 resources.

Getting floodlights is politically difficult — nearby residents organise protests.

### Membership Tiers

| Tier | Advance Days | Max Concurrent | Daily Limit | Cancel Deadline | Annual Fee |
|------|-------------|----------------|-------------|-----------------|------------|
| Adult Member | 7 | 7 | 2 hours | 24 hours | £45 |
| Junior Member | 7 | 7 | 2 hours | 24 hours | £15 |
| Senior Member | 7 | 7 | 2 hours | 24 hours | £25 |
| Pay and Play | 7 | 7 | 2 hours | 24 hours | £0 (pay per booking) |
| Coach Level 2 | 28 | 999 | 4 hours | 36 hours | £0 |
| Coach Level 3 | 28 | 999 | 4 hours | 36 hours | £0 |
| Coach Level 4 | 28 | 999 | 4 hours | 36 hours | £0 |
| Coach Level 5 | 28 | 999 | 4 hours | 36 hours | £0 |

Members have NO booking privilege over non-members — all get 7-day advance window. The 9pm window opening is the key moment (everyone hits the system simultaneously). Coach advance days will be differentiated by level later (all 28 for now).

### Booking Rules

- Advance window opens at **9pm** the night before (e.g. 9pm Sunday for the following Sunday)
- Slot durations: **60 or 120 minutes**
- Daily limit is **hours-based** not count-based (one 2-hour booking uses the full daily allowance)
- Pay-and-play: peak £9, off-peak £6

## Development Phases

| Phase | What | Cost |
|-------|------|------|
| 0 | Foundation (data model, API, Docker, ClubSpark investigation, CSV import) | £0 |
| 1 | Minimum viable booking (PWA, FCFS, Stripe test mode, preferences) | £0 |
| 2 | Credits, programmes, Xero integration | £0 |
| 3 | Pilot (1 park, 50-100 members, cloud deployment, ClubSpark shadow) | £50-100/mo |
| 4 | Multi-site (7 parks), fairness window, standing groups | £200-250/mo |
| 5 | Leagues, Find a Game, weather integration | unchanged |
| 6 | Multi-tenant SaaS (commercial phase) | scales |

## Key Concepts

- **Fairness window** (Phase 4): 5-minute submission window at peak time. Members submit preferences, constraint solver (OR-Tools CP-SAT) optimises allocation across all members simultaneously using weighted fairness scores. NOT a random lottery — weighted optimisation.
- **Cascading preferences:** Members save a preference list (venue/court/time combos). System tries first choice, falls through to alternatives automatically.
- **Standing groups:** Regular social groups that reserve courts weekly. Must qualify (8 members, 12-week commitment, 75% utilisation). Transparent governance with published criteria.
- **Credit system** (Phase 2): Double-entry ledger, FEFO expiry, mixed payment (credits + card). Materialised view of balances for performance.
- **ClubSpark shadow** (Phase 3+): Block-book courts on ClubSpark to prevent double-booking during parallel operation. Automate if internal API accessible, manual fallback if not.

## Reference Documents

Three comprehensive documents exist (Howard can provide these):
1. **Technical Specification** (~37 pages) — Full system spec including data model, fairness algorithm, all features
2. **Business Case** (~10 pages) — Market analysis, pricing strategy, competitive landscape
3. **Development Plan** (~17 sections, 350 paragraphs) — Phased delivery, scaling strategy, architectural decisions, risk mitigations

## Competitive Landscape

No existing platform addresses this combination: multi-factor fairness scoring with constraint solving, cascading booking preferences, social group reservation management, credit system with FEFO expiry, multi-site park tennis at charity scale, LTA/ClubSpark shadow compatibility, and Xero integration for charity governance. Cobalt Software's lottery system for US country clubs is the closest competitor but fundamentally different (random draw vs weighted optimisation).

## Working Environment

- Howard develops on Windows with WSL (Ubuntu)
- Docker Desktop with WSL 2 backend
- Code lives in ~/courtbook in WSL home directory (NOT in OneDrive/SharePoint)
- Git for version control, pushing to GitHub (github.com/hbenno/courtbook)
- Multiple machines (home, office) synced via GitHub
- Git identity: Howard Bennett, howard@eastmoorcapital.com
- `gh` CLI may or may not be installed — check with `which gh`, install if needed

## Codebase Patterns & Gotchas

### Enums
- All Python enums use `enum.StrEnum` (not `str, enum.Enum`)
- All SQLAlchemy Enum columns use `values_callable=lambda e: [x.value for x in e]` to store lowercase values in PostgreSQL (e.g. `"confirmed"` not `"CONFIRMED"`)
- If you add a new enum or change values, you must regenerate the Alembic migration AND reseed the database

### SQLAlchemy / mypy
- Don't reuse the `result` variable name for multiple queries in one function — mypy narrows the type from the first assignment and gets confused. Use `org_result`, `mem_result`, etc.
- Exception naming: use `Error` suffix (e.g. `BookingViolationError` not `BookingViolation`)

### Timezone
- All booking times are wall-clock London time: `ZoneInfo("Europe/London")`
- Use `datetime.now(LONDON_TZ)` not `datetime.now(UTC)` for booking rule comparisons
- Token expiry in `app/core/auth.py` uses UTC (correct for JWT)

### Ruff / linting
- B008 is ignored (FastAPI `Depends()` in defaults is standard)
- Migrations directory is excluded from ruff
- Run locally: `docker compose -f docker/docker-compose.yml exec api ruff check . && ruff format --check . && mypy app --ignore-missing-imports`

### Docker
- Start: `docker compose -f docker/docker-compose.yml up -d`
- Seed: `docker compose -f docker/docker-compose.yml exec api python -m scripts.seed`
- Reset DB: `docker compose exec db psql -U courtbook -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"` then `docker compose exec api alembic upgrade head` then reseed
- After schema reset, first API request may get `InvalidCachedStatementError` — this is transient, asyncpg auto-recovers

### Test users (from seed)
- Admin: `admin@hackneytennis.org` / `admin123` (platform admin + org admin)
- Member: `member@example.com` / `member123` (regular member)

### API endpoints
- Health: `GET /health`
- Auth: `POST /api/v1/auth/register`, `/login`, `/refresh`, `GET /me`
- Orgs (public): `GET /api/v1/orgs/{slug}`, `/{slug}/sites`, `/{slug}/sites/{site_slug}/courts`
- Orgs (admin): `GET /api/v1/orgs/{slug}/members` (requires org admin JWT)
- Bookings: `POST /api/v1/bookings`, `GET /api/v1/bookings`, `DELETE /api/v1/bookings/{id}`
