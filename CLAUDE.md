# CourtBook - Project Context for Claude Code

## What This Is

CourtBook is a court and course booking platform being built for Hackney Tennis, a tennis charity operating across 7 parks in Hackney, London (28 bookable courts + 2 mini courts). The long-term vision is a multi-tenant SaaS serving 2,000+ UK tennis venues and eventually a global platform.

The project owner is Howard, who is a cattle futures trader by day and a trustee/volunteer for Hackney Tennis. He codes in Python and is not a beginner. The current booking system is ClubSpark (LTA's platform), which is stagnant and inadequate.

## Project tracking

Living project state is in
`/mnt/e/Eastmoor Capital/UMGAS - Documents/Python_Code/claude_sessions/tracking/courtbook.md`
(SharePoint-synced, readable from SIXLEIGH1 and EM1). Covers both
code and specs streams of CourtBook work.

On session start, read that file — `## Status`, `## Next session`,
`## Open questions`. On session end, update it alongside the session
summary.

### Journals

For ongoing CourtBook work threads spanning multiple sessions,
journals live in `docs/session_summaries/journal_<topic>.md` —
append-only, dated entries. At session start, scan for journals
and ask whether continuing one. At session end, `/session-summary`
prompts for the choice.

## Architecture

- **Backend:** Python 3.12, FastAPI (async), SQLAlchemy 2.0 async with asyncpg
- **Database:** PostgreSQL 16 (chosen for: ACID transactions for credit ledger, row-level security for multi-tenancy, PostGIS for court discovery at scale, relational joins for fairness solver, jsonb for flexible config)
- **Cache/Queue:** Redis 7, Celery (task queue for fairness solver jobs, notifications)
- **Frontend:** React 19 + TypeScript + Vite 7 + Tailwind CSS v4 (PWA with vite-plugin-pwa)
- **Local dev:** Docker Compose (PostgreSQL, Redis, FastAPI with hot-reload, Celery worker, Vite dev server, Mailpit for email capture)
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

## Current State (Phase 0 Complete, Phase 1 Substantially Complete)

### Phase 0 — Foundation (Complete)
- Repository structure (monorepo: /api, /web, /docker, /docs, /scripts)
- Docker Compose environment fully working (api, web, db, redis, worker, mailpit)
- Database models: Organisation, Site, Resource, User, MembershipTier, OrgMembership, Booking, CreditTransaction, UserPreference
- Async SQLAlchemy with tenant-aware session management
- FastAPI with OpenAPI docs at /api/v1/docs
- JWT authentication (register, login, refresh, me, forgot-password, reset-password)
- Alembic configured for async migrations
- Seed data with correct park/court data (see below)
- **Booking rules enforcement service** (`app/services/booking_rules.py`):
  - Advance booking window (7 days for members, 28 for coaches, opens at configurable time per tier — default 21:00)
  - Max concurrent bookings (7 for members, 999 for coaches)
  - Max daily minutes (120 for members = 2 hours, 240 for coaches = 4 hours)
  - Cancellation deadline (24 hours for members, 36 for coaches)
  - Slot duration validation (60 or 120 minutes)
  - Court conflict detection (composite partial unique index `ix_bookings_no_double`)
  - All violations returned in one response with clear messages
- **RBAC middleware** (`app/core/dependencies.py`):
  - `get_org_membership` — resolves user's membership within org by URL slug
  - `require_org_role(*roles)` — factory returning dependency that checks OrgRole
  - Convenience shortcuts: `require_org_admin`, `require_org_coach`, `require_org_member`
  - Platform admins (UserRole.ADMIN/SUPERADMIN) bypass all org-level checks
  - OrgRole enum includes: MEMBER, COACH, ADMIN, TREASURER
- **Operating hours service** (`app/services/operating_hours.py`):
  - Opens 07:00, max close 21:00, 60-minute slots
  - Uses `astral` library for sunset calculation at Hackney centroid (51.545, -0.056)
  - Non-floodlit outdoor courts close at sunset (floored to hour, capped at 21:00)
  - Floodlit/indoor courts always open until 21:00
  - `generate_slots()` returns all time slots with `is_available` flag
- **Pricing service** (`app/services/pricing.py`):
  - Four price bands: early, offpeak, peak, floodlight
  - Default boundaries: weekday early end 10:00, weekday peak start 18:00, weekend early end 09:00
  - All boundaries overridable per-org via `org.config` JSONB
  - Floodlight band: court has lights AND booking extends past dusk
  - Weekend: only early/peak (no offpeak band)
  - Fees stored per-hour on MembershipTier, scaled linearly by duration
- **Credit system** (`app/services/credit.py`, `app/models/credit.py`):
  - Double-entry ledger: TransactionTypes GRANT, BOOKING_PAYMENT, CANCELLATION_CREDIT, ADMIN_ADJUSTMENT, PAYMENT_REVERSAL
  - Cached balance on `OrgMembership.credit_balance_pence` (`SELECT FOR UPDATE` for race prevention)
  - Admin endpoints for balance viewing, transaction history, credit granting
- **Stripe integration** (`app/services/stripe_service.py`, `app/routes/webhooks.py`):
  - Stripe customer management (get or create, stored on User model)
  - PaymentIntent creation for bookings requiring payment
  - Webhook handler: `payment_intent.succeeded` → mark PAID; `payment_intent.payment_failed` → cancel booking + reverse credit
  - Mixed payment: credits deducted first, remaining charged via Stripe
- **Email service** (`app/services/email.py`):
  - Async SMTP via `aiosmtplib`, wired to Mailpit in dev
  - Password reset email with configurable frontend URL
- **Preferences** (`app/routes/preferences.py`, `app/models/preference.py`):
  - GET / PUT (bulk replace, max 10) / DELETE
  - Priority-ordered with site/resource/day/time/duration fields for Phase 4 fairness solver
- **GitHub Actions CI** (`.github/workflows/ci.yml`):
  - `lint` job: ruff check, ruff format --check, mypy
  - `lint-web` job: npm ci, tsc --noEmit (TypeScript check)
  - `test` job: pytest with PostgreSQL 16 service container
- **CSV import pipeline** (`scripts/import_csv.py`):
  - `python -m scripts.import_csv members <csv> [--dry-run]`
  - `python -m scripts.import_csv bookings <csv> [--dry-run]`
  - Column mappings are configurable dicts — update when real ClubSpark CSVs are available

### Phase 0 — Not Done Yet
- **ClubSpark API investigation** — blocked pending Howard getting admin login credentials

### Phase 1 — Minimum Viable Booking (Substantially Complete)
All backend endpoints built. React PWA frontend built and running.

#### What's Done
- React 19 + TypeScript + Vite 7 + Tailwind CSS v4 PWA in `/web`
- Auth: login, register, forgot password, reset password pages
- Court browser: park list → site availability grid (all courts at a site in a ClubSpark-style grid)
- FCFS booking: select slot from grid → confirm page with Stripe Elements (when payment required)
- My bookings: view upcoming/past, cancel with credit refund info
- Booking preferences: add/remove/reorder up to 10 preferences
- Mobile-first with bottom nav tabs, responsive layout
- TanStack Query for server state (with stale times and cache)
- API client with JWT auto-refresh on 401
- Docker Compose `web` service (Node 20 Alpine, Vite dev server on :5173)
- Vite proxy: `/api` → configurable backend URL (`API_URL` env var for Docker, `localhost:8000` for local)

#### What Still Needs Testing/Polish
- End-to-end Stripe payment flow in browser (needs `VITE_STRIPE_PUBLISHABLE_KEY` set)
- PWA icons (pwa-192x192.png, pwa-512x512.png referenced in manifest but not created)
- Error boundaries
- `CourtListPage.tsx` exists on disk but is not routed (grid view replaced the intermediate court list)

### CSV Import — Verification Needed Before Production Use
- Column mappings in `scripts/import_csv.py` (`MEMBER_COLUMNS` dict) are based on a screenshot of a ClubSpark **test club** export — NOT the real Hackney Tennis data
- **Before importing real data:** Open the Hackney Tennis CSV in a text editor (NOT Excel — Excel may hide encoding issues) and verify the exact column headers match `MEMBER_COLUMNS` values
- `TIER_MAP` currently includes test club tier names (`"friendly 2"`, `"all test"`, `"import"`, `"additional"`) that map to `"adult"` as fallback — review these once real tier names are known
- ClubSpark export uses `"Venue ID"` as the member identifier (not a separate "Member ID" column) — this gets stored as `legacy_id` on the User model
- Bookings CSV column mappings (`BOOKING_COLUMNS`) have NOT been verified against real ClubSpark data — they're still based on test data
- Always run with `--dry-run` first to validate before committing to DB

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
- **Credit system** (built): Double-entry ledger with cached balances on OrgMembership. Mixed payment: credits deducted first, remainder via Stripe. Admin endpoints for grant/view/history. FEFO expiry not yet implemented.
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
- Node 20 LTS installed via nvm (required by Vite 7). Run `nvm use 20` if node version is wrong
- Shell CWD often resets to `/mnt/e/Eastmoor Capital/...` (OneDrive mount). Use `npm run --prefix /home/hbennett/courtbook/web` or `git -C /home/hbennett/courtbook` for commands

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
- Services: api (:8000), web (:5173), db (:5432), redis (:6379), worker (Celery), mailpit (:8025 UI, :1025 SMTP)
- Stripe env vars: `CB_STRIPE_SECRET_KEY`, `CB_STRIPE_WEBHOOK_SECRET`, `VITE_STRIPE_PUBLISHABLE_KEY`

### Test users (from seed)
- Admin: `admin@hackneytennis.org` / `admin123` (platform admin + org admin)
- Member: `member@example.com` / `member123` (regular member)

### API endpoints
- Health: `GET /health`
- Auth: `POST /api/v1/auth/register`, `/login`, `/refresh`, `/forgot-password`, `/reset-password`, `GET /me`
- Orgs (public): `GET /api/v1/orgs/{slug}`, `/{slug}/sites`, `/{slug}/sites/{site_slug}/courts`
- Availability (public): `GET /api/v1/orgs/{slug}/sites/{site_slug}/availability?date=YYYY-MM-DD` (site-wide grid), `GET .../courts/{court_id}/availability?date=YYYY-MM-DD` (single court)
- Bookings (auth): `POST /api/v1/bookings`, `GET /api/v1/bookings`, `DELETE /api/v1/bookings/{id}`
- Preferences (auth): `GET /api/v1/orgs/{slug}/preferences`, `PUT` (bulk replace), `DELETE`
- Credit (org admin): `GET /api/v1/orgs/{slug}/members/{id}/credit`, `GET .../credit/transactions`, `POST .../credit` (grant)
- Members (org admin): `GET /api/v1/orgs/{slug}/members`
- Webhooks: `POST /api/v1/webhooks/stripe`

### Frontend structure
```
web/src/
  api/client.ts, endpoints.ts     # Fetch wrapper with JWT auto-refresh + typed API calls
  auth/AuthContext.tsx, ProtectedRoute.tsx
  components/layout/AppLayout.tsx, Navbar.tsx, BottomNav.tsx
  components/ui/Button.tsx, Input.tsx, Card.tsx, LoadingSpinner.tsx, ErrorMessage.tsx
  hooks/useSites.ts, useCourts.ts, useAvailability.ts, useSiteAvailability.ts,
        useBookings.ts, usePreferences.ts, useResourceLookup.ts
  pages/LoginPage, RegisterPage, ForgotPasswordPage, ResetPasswordPage
  pages/parks/ParkListPage, AvailabilityPage (grid view)
  pages/bookings/BookingConfirmPage (Stripe Elements), MyBookingsPage
  pages/preferences/PreferencesPage
  types/api.ts, lib/constants.ts, lib/format.ts, lib/storage.ts
```

### Frontend routes
| Path | Page | Auth |
|------|------|------|
| `/login`, `/register`, `/forgot-password`, `/reset-password` | Auth pages | No |
| `/` | Redirect → `/parks` | No |
| `/parks` | ParkListPage (7 park cards) | No |
| `/parks/:siteSlug` | AvailabilityPage (courts×times grid) | No |
| `/parks/:siteSlug/book` | BookingConfirmPage | Yes |
| `/bookings` | MyBookingsPage | Yes |
| `/preferences` | PreferencesPage | Yes |
