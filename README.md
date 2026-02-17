# CourtBook

Court and course booking platform for tennis charities and clubs.

## Quick Start (Windows with WSL)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL 2 backend enabled
- Git (in WSL: `sudo apt install git`)

### First Run

```bash
# Clone the repo (inside WSL terminal)
git clone <your-repo-url> courtbook
cd courtbook

# Start everything
cd docker
docker compose up --build

# Wait for the build to complete and services to start.
# You'll see "Uvicorn running on http://0.0.0.0:8000" when ready.
```

### Seed the Database

In a second WSL terminal:

```bash
cd courtbook
docker compose -f docker/docker-compose.yml exec api python -m scripts.seed
```

This creates:
- **Hackney Tennis** organisation with 7 parks and 28 courts
- 4 membership tiers (Adult, Junior, Senior, Pay-and-Play)
- 2 test users:
  - `admin@hackneytennis.org` / `admin123` (admin)
  - `member@example.com` / `member123` (member)

### What's Running

| Service | URL | Purpose |
|---------|-----|---------|
| API | http://localhost:8000/api/v1/docs | FastAPI with interactive Swagger docs |
| Health | http://localhost:8000/health | Health check endpoint |
| PostgreSQL | localhost:5432 | Database (user: courtbook, pass: courtbook) |
| Redis | localhost:6379 | Cache and task queue broker |
| Mailpit | http://localhost:8025 | Email capture UI (SMTP on port 1025) |

### Try It

```bash
# Register a new user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123","first_name":"Test","last_name":"User"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@hackneytennis.org","password":"admin123"}'

# Use the access_token from the response to hit authenticated endpoints
# Or just open http://localhost:8000/api/v1/docs and use the Authorize button
```

### Day-to-Day

```bash
# Start
cd docker && docker compose up

# Stop
docker compose down

# Reset everything (wipes database)
docker compose down -v

# Re-seed after reset
docker compose up -d
docker compose exec api python -m scripts.seed

# Run migrations (after model changes)
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head

# Run tests
docker compose exec api pytest

# Lint
docker compose exec api ruff check .
docker compose exec api ruff format --check .
```

## Project Structure

```
courtbook/
├── api/                    # Python/FastAPI backend
│   ├── app/
│   │   ├── core/           # Config, database, auth, dependencies
│   │   ├── models/         # SQLAlchemy models
│   │   ├── routes/         # API route handlers
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   ├── services/       # Business logic (booking rules, etc.)
│   │   ├── main.py         # FastAPI app
│   │   └── worker.py       # Celery worker
│   ├── migrations/         # Alembic database migrations
│   ├── scripts/            # Seed data, CSV import, utilities
│   └── tests/
├── web/                    # React/TypeScript frontend (Phase 1)
├── docker/
│   ├── docker-compose.yml
│   └── api.Dockerfile
├── docs/                   # Architecture decisions, runbooks
└── .env.example
```

## Data Model

```
Organisation (Hackney Tennis)
 └── Site (London Fields, Clissold Park, ...)
      └── Resource (Court 1, Court 2, ...)

User (global identity)
 └── OrgMembership (links user to org with tier and role)
      └── MembershipTier (Adult, Junior, Senior, Pay-and-Play)

Booking (resource + user + date/time)
```

## Phase 0 Checklist

- [x] Repository structure
- [x] Docker Compose environment
- [x] Database models (Organisation, Site, Resource, User, MembershipTier, OrgMembership, Booking)
- [x] Async SQLAlchemy with tenant-aware session management
- [x] FastAPI skeleton with OpenAPI docs
- [x] Authentication (register, login, JWT)
- [x] Seed data (Hackney Tennis, 7 parks, 28 courts, tiers, test users)
- [ ] Alembic initial migration
- [ ] RBAC middleware (org-level role checks)
- [ ] Booking rules enforcement (advance window, max concurrent, cancellation deadline)
- [ ] ClubSpark API investigation
- [ ] CSV import pipeline
- [ ] GitHub Actions CI (lint, type-check, tests)
