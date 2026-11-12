# CLAUDE.md — Sonrisas de Cristal API

Context for a new session. Read it before changing anything. The README (Spanish) is for people; this file is for the next Claude session.

## 1. What this is

REST API for the Android app of **Sonrisas de Cristal**, a group of daycares ("estancias") in Monterrey, Mexico. It manages staff, weekly schedules, clock-in/clock-out with GPS, attendance, time corrections, notices, coverage reports and an audit trail.

It is a **migration of a Node.js + Express + Prisma API** (still available at tag `v1-node` and on `main`) to **Python + FastAPI + SQLAlchemy**. The Android app is **not implemented yet**, so the API contract is free to change.

- **Everything is in English**: code, comments, routes, JSON fields, error messages. The README is the exception (Spanish, like the rest of the team's docs). Sample data in the seed (names, positions, room names) is Spanish on purpose.
- Domain words: `estancia` = **daycare**, `sala` = **room**, `turno` = **shift**, `responsable` = **manager**, `direccion` = **director**, `empleada` = **employee**, `registro de entrada` = **time record**, `aviso` = **notice**, `horario` = **schedule**, `asistencia` = **attendance**, `correccion` = **correction**, `personal` = **staff**, `movimiento` = **movement** (hire/termination/transfer).

## 2. Repository and git state

- Repo: `github.com/Rodrigo-B-R/sonrisas_cristal_api`. Database repo (separate): `github.com/Rodrigo-B-R/sonrisas_cristal_db`, locally at `C:\Users\rbeta\sonrisas_cristal_db`.
- **Branch `fastapi`** holds this implementation. It was created with `git switch --orphan` (no shared history with `main`). **`main` still has the Node version.** Tag `v1-node` marks the last Node commit (`6aea375`).
- Commits on `fastapi`: `552ac4a` (initial), `723b0d3` (API v1), `870f05e` (logout).
- Plan to make it the main branch without `--force`: `git switch main; git pull; git rm -r -q .; git checkout fastapi -- .; git commit; git push`. Not done yet. A `git stash` with old Docker/.env edits from before the migration may still exist (`git stash drop` is safe).
- **The user runs git commits/pushes themself.** Do not commit or push unless asked.
- The user writes Spanish. Answer in Spanish. When asked for "only the essentials", do exactly that and offer the rest.
- Windows 11. Shells: Git Bash (`Bash` tool) and PowerShell. Python 3.13 on the host (the Docker image uses 3.12; both pass the tests).

## 3. Stack (versions are pinned in `requirements.txt`)

| Area | Library |
|---|---|
| Web | FastAPI 0.162, Starlette 1.10, uvicorn 0.54 |
| ORM / driver | SQLAlchemy 2.1 (sync), psycopg 3 (`postgresql+psycopg://`) |
| Validation / settings | Pydantic 2.14, pydantic-settings, email-validator |
| Security | PyJWT (HS256), bcrypt 5, slowapi (rate limit) |
| Metrics | prometheus-client |
| Time zones | tzdata (zoneinfo needs it on Windows and slim images) |
| Tests | pytest, httpx (in `requirements-dev.txt`) |

Sync SQLAlchemy was chosen on purpose (simple; routes are plain `def`, FastAPI runs them in a thread pool). Alembic is not used: the schema belongs to `sonrisas_cristal_db`.

## 4. Architecture of the deployment

Docker network `sonrisas_net` (created by the DB repo's compose): Prometheus, Grafana (port 3000), PostgreSQL 17 (hostname `postgres`, no published port), **this API** (port 8000), MinIO (S3 storage, **not used by the API yet**), and a **Cloudflare tunnel** (HTTPS) in front of the API. Planned deployment: a VM, as a demo with the seed accounts (the user accepted keeping the seed; see §11).

## 5. Layout

```
app/
  main.py            FastAPI app, middleware (request id, JSON request log, metrics, headers), routers, error handlers
  config.py          Settings (pydantic-settings). Validates JWT_SECRET (>=32 chars, rejects example value)
  database.py        engine, SessionLocal (expire_on_commit=False), get_db, set_audit_user
  models.py          18 tables with English names over the real Spanish columns; UTCDateTime type
  schemas.py         Pydantic: `In` (requests, extra="forbid", camelCase) and `Out` (responses, from_attributes)
  dependencies.py    get_current_user, require_role, aliases (ManagerOnly, DirectorOnly, ManagerOrDirector, EmployeeOrManager, CurrentUser, DbSession)
  access.py          daycare_scope, can_access_daycare, require_found (isolation between daycares)
  security.py        bcrypt, JWT (+jti), TokenDenylist, get_client_ip, limiter (slowapi), LoginGuard
  errors.py          ApiError and every exception handler; common_headers
  logging_config.py  JSON logs; loggers app.request / app.security / app.error; security_event()
  metrics.py         /metrics + Prometheus counters
  constants.py       API (English) <-> DB (Spanish) value maps; weekdays; NO_END
  timeutils.py       TZ helpers, read_period, read_timestamp
  routers/           session, catalogs, daycares, rooms, staff, movements, schedules, time_records,
                     attendance, notices, audit, reports
  services/          schedules.py, records.py (clock-in/out, manager fixes), calculations.py (attendance/coverage/statistics)
scripts/             create_tables.py, seed.py
tests/               conftest.py, factories.py, test_*.py (SQLite), e2e_postgres.py (real PostgreSQL, not collected by pytest)
requirements.txt / requirements-dev.txt / pytest.ini / Dockerfile / docker-compose.yml / .env.example
pruebas.http         REST Client requests (English routes, tokens captured automatically)
```

Docker image: copies only `app/`, `scripts/`, `requirements.txt`; runs as user `app` (uid 1000), `ENVIRONMENT=production`, **one uvicorn worker** (in-memory counters), HEALTHCHECK on `GET /`.

## 6. Roles and endpoints

Roles in the API: `employee`, `manager`, `director`. Manager = scoped to **their own daycare**. Director = all daycares. Employees only see their own data.

Legend: **Any** = any authenticated user · **E/M** = employee or manager · **M** = manager only · **M/D** = manager or director · **D** = director only.
Query periods use `?startDate=&endDate=` (YYYY-MM-DD). Directors can filter with `?daycareId=` where noted; for everyone else that parameter is ignored (always their own daycare).

### Public
| Method | Path | Notes |
|---|---|---|
| GET | `/` | Health: `{"message": "..."}` |
| GET | `/metrics` | Needs `Authorization: Bearer <METRICS_TOKEN>`; **404 if METRICS_TOKEN is empty** |
| POST | `/login` | `{username, password}` → `{token, tokenType, expiresIn, role, user{id,name,daycareId}}`. Rate-limited (5/min/IP) and account lockout |

### Session (Any)
| Method | Path | Notes |
|---|---|---|
| POST | `/logout` | Revokes THIS token (jti). 401 `Token revoked` afterwards |
| GET | `/profile` | User with role, position, daycare (+location, rooms) |
| PUT | `/profile/password` | `{currentPassword, newPassword}`; 400 with `missing: [...]` if weak |

### Catalogs
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/catalogs` | Any | roles (English names), positions, shifts, terminationReasons, absenceReasons |
| POST | `/catalogs/positions` | D | `{name}` → 201 |
| POST | `/catalogs/termination-reasons` | D | `{name}` → 201 |
| POST | `/catalogs/absence-reasons` | D | `{description}` → 201, 409 if repeated |
| PUT | `/catalogs/shifts/{id}` | D | `{name?, startTime?, endTime?}` ("HH:MM") |

### Daycares and rooms
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/daycares`, `/daycares/{id}` | Any | with location and rooms |
| POST | `/daycares` | D | `{name, latitude, longitude, radiusMeters=150}` → 201 |
| PUT | `/daycares/{id}` | D | partial |
| GET | `/rooms`, `/rooms/{id}` | Any | scoped to the caller's daycare (`?daycareId=` director) |
| POST | `/rooms` | M | `{name, minStaff}`; always in the manager's daycare |
| PUT | `/rooms/{id}` | M | partial |

No DELETE anywhere: the DB user cannot delete.

### Staff and movements (M/D)
| Method | Path | Notes |
|---|---|---|
| GET | `/staff` | `?active=true\|false\|all` (default true), `?daycareId=` (director). Managers never see directors |
| GET | `/staff/{id}` | Profile + `currentSchedule` + `movements` history |
| POST | `/staff` | `{name, username, email, phone, positionId, password?, hireDate?, role?, daycareId?}` → 201 with `temporaryPassword` (shown once). Manager sending `role`/`daycareId` ≠ own → **403**. Creates a `hire` movement in the same transaction |
| PUT | `/staff/{id}` | partial; `role` only by director (403 otherwise). A manager can only modify employees |
| POST | `/staff/{id}/terminate` | `{terminationReasonId, date?, notes?}`; 409 if already terminated; 400 if self |
| POST | `/staff/{id}/transfer` | `{daycareId, date?, notes?}`; 400 if same daycare |
| POST | `/staff/{id}/password` | resets → `{temporaryPassword}` |
| GET | `/movements` | `?startDate,endDate,type=hire\|termination\|transfer,daycareId`; default period = this month, max 400 days |

### Schedules
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/schedules/me` | Any | my schedule on `?date=` (default today) or `null` |
| GET | `/schedules` | M/D | `[{person, schedule}]` of active staff on `?date=` |
| GET | `/schedules/{userId}` | M/D | one person; 404 if not visible |
| PUT | `/schedules/{userId}` | M | `{validFrom?, days:[{day:"monday", shiftId, roomId}]}` → 201. Closes the previous schedule (`validUntil = validFrom - 1`), creates a new one valid until 2099-12-31. Days not listed = day off. Rooms must belong to the manager's daycare |

### Time records (clock-in/out)
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/time-records/status` | Any | `{inside, openRecord, todayShifts, location}` |
| GET | `/time-records` | Any | employee: own; manager: daycare; director: all. `?startDate,endDate,userId,withinZone,daycareId` |
| POST | `/time-records/clock-in` | E/M | `{uuid?, occurredAt?, latitude?, longitude?, withinZone?, roomId?, shiftId?}` → 201 `{record, attendance, repeated:false}`; **same uuid again → 200 `repeated:true`**; `roomId` and `shiftId` together or neither. Also creates the day's attendance (present/late) |
| POST | `/time-records/clock-out` | E/M | `{occurredAt?}`; same-second exit is saved +1 s (DB needs out > in) |
| POST | `/time-records/batch` | M | `{userIds, occurredAt?, roomId?, shiftId?}` → 201 `{recorded, skipped}` |
| PUT | `/time-records/{id}` | M | `{clockInAt?, clockOutAt?}`; `clockOutAt: null` removes it; the before/after is kept by the audit triggers |

### Attendance
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/attendance/me` | Any | `{startDate, endDate, person, summary, days}` |
| GET | `/attendance` | M/D | list of the same shape per person |
| GET | `/attendance/{userId}` | M/D | one person |
| POST | `/attendance` | M | `{userId, date, status: present\|late\|absent\|incident, absenceReasonId? \| absenceReason?}` → 201, or 200 if it corrected the day. `absent`/`incident` **require a reason** (400 with `options`) |
| PUT | `/attendance/{id}` | M | partial, same reason rule |

Day statuses in reports: `present, late, absent, incident` (stored) plus computed `no_record, pending, day_off, outside_schedule, scheduled`. Absences = `absent` + `no_record`.

### Notices
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/notices/inbox` · `/notices/inbox/{id}` | Any | what reached me, with `read`/`readAt` |
| POST | `/notices/{id}/read` | Any | confirm reading (first time is kept) |
| GET | `/notices` | M/D | `recipientCount`, `confirmedCount`; manager sees own daycare + general notices |
| GET | `/notices/{id}` | M/D | `confirmed[]` and `pending[]` (manager only counts readers from own daycare) |
| POST | `/notices` | M/D | `{subject, message, noticeType: schedule_change\|meeting\|reminder\|urgent, target: all\|shift\|room\|people, shiftId?, roomId?, userIds?, requiresConfirmation?, daycareId?}`. Director without `daycareId` = **general notice** (`daycareId: null`, all daycares). Recipients: active, non-director, not the author |

### Reports
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/coverage` | M/D | `?date, daycareId` (**required for director**): present vs minimum per room and shift, with `alerts` |
| GET | `/summary` | D | every daycare on a date: complete vs understaffed |
| GET | `/statistics` | M/D | period (default this month, max 400 days): hires, terminations, absences, lates, understaffedDays, absenteeism %, byDaycare |
| GET | `/export/attendance` | M/D | CSV (UTF-8 BOM, all fields quoted, formula-injection safe) |
| GET | `/audit` | D | `?startDate,endDate,table,recordId,userId`; last 500 changes |

Node → FastAPI route names: `/personal`→`/staff`, `/registros`→`/time-records` (`/entrada`→`/clock-in`, `/salida`→`/clock-out`, `/turno`→`/batch`, `/estado`→`/status`), `/estancias`→`/daycares`, `/salas`→`/rooms`, `/horarios`→`/schedules`, `/correcciones`→`/corrections` (`aprobar/rechazar`→`approve/reject`), `/asistencias`→`/attendance`, `/avisos`→`/notices` (`/lectura`→`/read`), `/auditoria`→`/audit`, `/catalogos`→`/catalogs`, `/perfil`→`/profile`, `/cobertura|resumen|estadisticas|exportar`→`/coverage|summary|statistics|export`.
Deliberate deviations from Node: role-polymorphic routes were split (`/me`, `/inbox`); periods use `startDate/endDate`; 403 instead of silently ignoring forbidden fields; unknown body fields → 400; `/metrics` off without token; `POST /logout` is new.

## 7. Design decisions you must not undo by accident

**Two vocabularies.** The DB has CHECK constraints on Spanish values (`empleada/responsable/direccion`, `presente/retardo/falta/incidencia`, `lunes…`, `alta/baja/traslado`, `pendiente/aprobada/rechazada`, `app/responsable`, `cambio_horario/reunion/recordatorio/urgente`). The API speaks English. **`app/constants.py` is the only place that translates** (`*_TO_DB` / `*_FROM_DB`). Output schemas translate with a `field_validator(mode="before")`. Never compare an API value with a DB value.

**Authentication.** JWT HS256 with only `sub` (user id), `jti`, `iat`, `exp` (60 min). `jti` is **required**. No role/daycare in the token. `get_current_user` decodes (algorithm fixed to HS256), checks the denylist, then **loads the user from the DB on every request** (one PK query with the role joined) and rejects inactive users with 401. So terminations, transfers and role changes apply on the very next request. Old Node tokens are invalid (they had no `sub`/`jti`).

**Authorization = three layers.** (1) `get_current_user` → 401. (2) `require_role(...)` aliases → 403 `Your role cannot do this`. (3) data scope via `access.py` → **404 (not 403)** for another daycare's data, so existence is not confirmed. Every router except `session` and `metrics` also declares `dependencies=[Depends(get_current_user)]` or a `require_role(...)` dependency (secure by default: a new route in them is authenticated even if you forget the parameter). Managers never see directors; managers only modify employees (director: anyone).

**Validation.** Pydantic `In` models: camelCase aliases, `extra="forbid"` (no mass assignment), stripped strings. Validation errors → `400 {"error":"Invalid data","details":[{"in","field","message"}]}` (input values are never echoed). Domain errors raise `ApiError(status, message, **extra)`. One format everywhere: `{"error": "..."}`. IntegrityError (UNIQUE→409, FK→409, CHECK/NOT NULL→400), DataError→400, unhandled→500 `{"error":"Internal error","requestId"}` (stack only in the log).

**Audit trail.** Triggers in the DB audit `registro_entradas` and `asistencia` into `auditoria` and read the author from `current_setting('app.id_usuario')`. **Every write to those three tables must call `set_audit_user(db, user_id)` before writing and commit in the same transaction** (`SELECT set_config('app.id_usuario', :id, true)`; no-op on SQLite). Writes without it are audited with `NULL` author. `auditoria` is read-only for `api_user`.

**Time.** Timestamps are stored/returned in UTC; responses format them as `2026-11-04T13:05:00.000Z` (`UtcTimestamp`). Times are `"HH:MM"` (`ShortTime`). Dates are `YYYY-MM-DD`. "Today", lateness and attendance days use `TZ` (default `America/Monterrey`, UTC-6, no DST). A client timestamp without offset is read in `TZ`; it cannot be more than 5 minutes in the future. Clock-ins carry a client-made `uuid` so offline retries never duplicate.

**Late rule.** Late if arrival is more than `LATE_TOLERANCE_MINUTES` (5) after the shift start. Attendance for the day is created at clock-in and left alone if it already exists. Room/shift come from the person's schedule (closest shift to arrival) unless both are sent.

**Active/inactive history.** `was_active(person, day)` uses the `hire`/`termination` movements, so reports stay correct after terminations. Nothing is ever deleted.

**Responses never include the password hash** (`UserOut` has no such field; a test checks it).

## 8. Security measures (OWASP Top 10:2025 work done)

- **A01 Broken access control:** role + scope + 404 pattern above; token never stale; `extra="forbid"`; managers cannot set `role`/`daycareId`; manager cannot touch other managers.
- **A02 Misconfiguration:** `/docs`, `/redoc`, `/openapi.json` only when `ENVIRONMENT != production`; HSTS in production; `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `X-Request-ID` on **every** response (including 500s: `common_headers` in `errors.py`); `/metrics` disabled without token; non-root Docker user.
- **A04 Crypto:** bcrypt cost 12 (tests lower it to 4), 72-byte limit handled, HS256 only, `JWT_SECRET` ≥ 32 chars and not the example value.
- **A05 Injection:** SQLAlchemy only (no raw SQL except `set_config`, parameterized); CSV cells starting with `= + - @` are prefixed with `'`.
- **A07 Authentication:** per-IP rate limit on `/login` (`LOGIN_RATE_LIMIT`, 5/min) and on every route (`DEFAULT_RATE_LIMIT`, 300/min, per route); **account lockout** after `LOGIN_MAX_FAILURES` (10) failures per username → 15 min (429 + `Retry-After`); identical 401 and **equal timing** for unknown user / wrong password / inactive (dummy bcrypt check); password policy (8+ chars, upper+lower, digit, differs from previous; also enforced on a manager-supplied initial password); `POST /logout` with a `jti` denylist.
- **A09 Logging:** JSON, one line per request (`app.request`: request_id, method, path, status, duration_ms, user_id, ip) and security events (`app.security`): `login_success, login_failed(reason), account_locked, login_locked, rate_limited, logout, auth_missing_token, auth_invalid_token, auth_expired_token, auth_revoked_token, auth_inactive_user, access_denied, password_changed, password_change_failed, password_reset, role_changed, staff_created, staff_terminated, staff_transferred, metrics_denied`. Passwords/tokens never logged; JSON escaping prevents log forging; user-supplied strings are clipped.
- **A10 Exceptional conditions:** global handlers, generic 500 with `requestId`.

**Client IP behind the Cloudflare tunnel.** All requests arrive from the tunnel container. `get_client_ip` only believes `CF-Connecting-IP` (or the last `X-Forwarded-For`) when the TCP peer is inside `TRUSTED_PROXIES` (CIDRs; `.env.example` suggests `172.16.0.0/12`; use the real `sonrisas_net` subnet). Empty `TRUSTED_PROXIES` behind the tunnel would make all users share one 5/min login limit. Anyone reaching port 8000 directly from a trusted range could spoof the header (only bypasses the IP limit; the account lockout still protects).

## 9. Database facts (repo `sonrisas_cristal_db`)

- PostgreSQL 17, 18 tables, schema in `init/01-init.sql` (run only on a fresh volume). Ids are `BIGINT GENERATED BY DEFAULT AS IDENTITY`. Container `sonrisas_postgres`, db name in that repo's `.env`.
- The API connects as **`api_user`**: `SELECT, INSERT, UPDATE` only (**no DELETE, no DDL**), read-only on `auditoria`. Use the owner (`postgres`) only for `scripts/create_tables.py`.
- Key constraints the API relies on: one attendance per (user, daycare, date); `absent`/`incident` need `id_motivo_ausencia`; `movimiento_usuario` fields per type (hire: destination only; termination: origin + reason; transfer: origin ≠ destination); `registro_entradas.uuid` unique and `clock_out > clock_in`; `aviso_usuario.leido = (leido_en IS NOT NULL)`; corrections: pending has no resolver, resolved has both resolver and time; `usuario.usuario_login` and `correo` unique.
- Catalogs are created **empty**; `scripts/seed.py` fills them for demos (5 daycares, 9 users, schedules, a welcome notice).
- **`DATABASE_URL` passwords with special characters (`# * ] ! = ^ @ :`) must be percent-encoded.** The real `api_user` password has such characters. `python -c "import os,urllib.parse as u;print(u.quote(os.environ['API_DB_PASSWORD'],safe=''))"`. **Never print secrets**: a connection error can echo the URL (it happened once in this project).

## 10. Environment variables (`app/config.py`, `.env.example`)

`DATABASE_URL`*, `JWT_SECRET`*, `JWT_EXPIRE_MINUTES`=60, `TZ`=America/Monterrey, `LATE_TOLERANCE_MINUTES`=5, `ENVIRONMENT`=development, `METRICS_TOKEN`, `LOGIN_RATE_LIMIT`=5/minute, `DEFAULT_RATE_LIMIT`=300/minute, `LOGIN_MAX_FAILURES`=10, `LOGIN_LOCKOUT_MINUTES`=15, `RATE_LIMIT_ENABLED`=true, `TRUSTED_PROXIES`, `SEED_PASSWORD`=Cristal2026, `API_PORT` (compose only). (* required.) Old Node names (`ENTORNO`, `TOLERANCIA_MINUTOS`) no longer exist; unknown variables in `.env` are ignored. `postgres://` and `postgresql://` URLs are rewritten to `postgresql+psycopg://`.

## 11. Commands

```powershell
# Run locally
python -m venv .venv ; .venv\Scripts\Activate.ps1 ; pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000          # /docs when ENVIRONMENT=development
python -m scripts.seed                               # demo data (accounts below)
pytest                                               # 110 tests, SQLite, ~30 s, no PostgreSQL needed
python -m pyflakes app scripts tests                 # must print nothing
```

Seed accounts (password = `SEED_PASSWORD`, default `Cristal2026`): `ana.torres` (employee), `marisol.garcia` (manager of Cumbres), `direccion` (director). In a fresh seeded DB: users 1 `direccion`, 2 `marisol.garcia`, 3 `ana.torres` … 9 `maria.lopez`; daycare 1 = Cumbres; shifts 1 matutino / 2 vespertino. Ana works Monday–Thursday mornings.

**Seed is intentionally kept in the production image** (the user decided: it is for demo users on a VM). Advice already given: set a private `SEED_PASSWORD` in the VM's `.env`, `ENVIRONMENT=production`, own `JWT_SECRET`/`METRICS_TOKEN`, real `TRUSTED_PROXIES`, do not expose port 8000. `seed.py` also resets passwords/reactivates its accounts when re-run.

**Real-PostgreSQL end-to-end check (44 checks)** — how it was run: rebuild the DB (`docker compose down -v; docker compose up -d --build` in the DB repo; the user explicitly authorized this once because that DB has no data), then run a throwaway `python:3.12-slim` container **on `sonrisas_net`** with the project mounted read-only: copy `app scripts tests requirements*.txt` into `/app`, `pip install -r requirements-dev.txt`, set `DATABASE_URL` (api_user, host `postgres`, password percent-encoded), `JWT_SECRET`, `METRICS_TOKEN`, then `python -m pytest tests`, `python -m scripts.seed`, `python -m tests.e2e_postgres`. `api_user` cannot delete, so **the e2e is not repeatable on the same data: rebuild the DB between runs.** Filter output so the password never appears. The e2e covers: audit authors via `set_config`, CHECK/UNIQUE constraints, UTC timestamps, token invalidation on termination, transfer scoping, `/metrics` pool gauge.

Docker: building/running the image was verified (healthy, non-root, no `/docs` in production). Do not run `docker compose up` in this repo casually: an old Node container `sonrisas_api` (port 3000) may exist and share the name.

## 12. Gotchas learned (save yourself time)

- **Pydantic + field named `date`:** in a class body `date: date | None = None` evaluates the default first, so the annotation sees `None`. `schemas.py` imports `from datetime import date as Date` and annotates with `Date`. Keep that.
- FastAPI 0.162: `app.routes` contains `_IncludedRouter` objects without `.path`. To list routes use `app.openapi()["paths"]`.
- slowapi: decorated routes need a `request: Request` parameter; `limiter.reset()`; tests disable it with `limiter.enabled = False` (the `fresh_database` fixture) and enable it per test. Use different usernames per attempt in rate-limit tests or the account lockout (10 failures) interferes.
- Tests that need a specific peer IP: `TestClient(app, client=("10.1.2.3", 5000))`.
- SQLAlchemy: `expire_on_commit=False`; after a commit set relationships manually or `db.refresh(obj)` (e.g. when a FK changed). `selectinload(User.schedules.and_(...))` fills the collection with a **filtered** list in the identity map (used in `load_data` and the schedules list); do not expect full collections from those User objects in the same session.
- `models.py` `UTCDateTime` returns aware UTC datetimes on PostgreSQL and SQLite; `BigId` is `BigInteger` with an `Integer` variant for SQLite autoincrement.
- Tests run on SQLite, so triggers, CHECK constraints and `set_config` are **not** exercised there. Anything touching them needs the real-PostgreSQL e2e.
- `security.BCRYPT_ROUNDS = 4` in tests only (module global read at call time).
- Reading a request body field that was sent as `null` vs omitted: use `body.model_fields_set` (see `clock_out_at` in time-records).
- Attendance report lists every person employed in the period (a manager with no schedule appears with empty `days`); this matches the Node behavior.
- `starlette.testclient` prints a deprecation about httpx; filtered in `pytest.ini`.

## 13. How to add an endpoint

1. Request/response models in `app/schemas.py` (`In` / `Out`; translate DB values with `_translate`; `Date` alias for dates).
2. Route in the right `app/routers/*.py`: take the role alias (`ManagerOnly`...) and `DbSession`; scope every query with `daycare_scope`/`can_access_daycare` and answer 404 for other daycares; raise `ApiError`.
3. If it writes to `registro_entradas` or `asistencia`: `set_audit_user(db, user.id)` first, commit in the same transaction.
4. If it changes staff/security state: `security_event(...)` with who/target/ip.
5. Business rules shared by several routes go to `app/services/`.
6. Tests in `tests/` (role matrix, cross-daycare 404, validation), run `pytest` and `pyflakes`; add a request to `pruebas.http`; update README and this file.
7. If it touches DB-specific behavior, run the real-PostgreSQL e2e.

## 14. Known limits and pending work

- **In-memory state** (rate limit counters, login lockout, logout denylist): lost on restart, per worker; hence one worker. Move to Redis before scaling. A restart re-enables tokens closed with `/logout` until they expire (max 60 min).
- Changing or resetting a password does **not** revoke open sessions (would need Redis or a DB column such as a session version, which lives in `sonrisas_cristal_db`). The user was offered "revoke all sessions on password change" and chose to leave it out for now.
- No refresh tokens; no pagination on list endpoints (Node had none either); `/statistics` recomputes day by day (fine for 5 daycares).
- **MinIO is in the architecture but unused**; ask the user what it is for before building anything.
- Error messages are English strings; if the Android app shows them, consider adding stable error codes.
- `pruebas.http` does not yet have a `POST /logout` request.
- `sonrisas_cristal.postman_collection.json` is **obsolete** (Node routes). Use Postman → Import → `http://localhost:8000/openapi.json` (needs `ENVIRONMENT=development`). Delete the old file when the user agrees.
- Images `Arquitectura del sistema@1x (1).png` and `base_datos.jpeg` are in the repo root (could move to `docs/`).
- The `fastapi` branch has not been merged into `main` yet (see §2).
- No CI yet. Suggested: GitHub Actions running `pytest` and the e2e against a Postgres service container (init SQL from the DB repo).
