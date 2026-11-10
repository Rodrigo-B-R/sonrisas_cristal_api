# API Sonrisas de Cristal

API REST para la app Android de Sonrisas de Cristal, hecha con **Python, FastAPI, SQLAlchemy y PostgreSQL**. Login con **JWT**, contraseñas con **bcrypt** y validación de datos con **Pydantic**.

Usa la base del repo [`sonrisas_cristal_db`](https://github.com/Rodrigo-B-R/sonrisas_cristal_db) (`init/01-init.sql`). Las tablas las crea ese repo, no la API: SQLAlchemy solo las describe (`app/models.py`).

> Esta rama es la migración de la API que estaba en Node.js + Express + Prisma (sigue en el tag `v1-node`). **Todo el código, las rutas, los campos JSON y los mensajes de error están en inglés.** Lo único que sigue en español son los datos de ejemplo (nombres, puestos, salas) y los valores que guarda la base, que tiene `CHECK` con `empleada`, `responsable`, `presente`, `lunes`, etc.: la API los traduce en la frontera y nunca los muestra.

## Rutas

Roles: **employee**, **manager** (su daycare) y **director** (todas).
"Estancia" ahora es **daycare**, "sala" es **room**, "turno" es **shift**.

| Ruta | Para qué | Antes (Node) |
|---|---|---|
| `POST /login`, `GET /profile`, `PUT /profile/password` | Sesión y perfil | `/login`, `/perfil` |
| `/catalogs` | Roles, puestos, turnos, causas de baja y motivos de ausencia | `/catalogos` |
| `/daycares`, `/rooms` | Estancias, ubicación y mínimo de personal por sala | `/estancias`, `/salas` |
| `/staff`, `/movements` | Personal, altas, bajas (`/terminate`) y traslados (`/transfer`) | `/personal`, `/movimientos` |
| `/schedules` | Horario semanal (`/me` es el propio) | `/horarios` |
| `/time-records` | Entradas y salidas (`/clock-in`, `/clock-out`, `/batch`, `/status`) | `/registros` |
| `/corrections` | Pedir y aprobar correcciones de hora (`/approve`, `/reject`) | `/correcciones` |
| `/attendance` | Presente, retardo, falta o incidencia (`/me` es la propia) | `/asistencias` |
| `/notices` | Avisos: `/inbox` lo que me llegó, `/{id}/read` confirmar lectura | `/avisos` |
| `/audit` | Quién cambió qué (director) | `/auditoria` |
| `/coverage`, `/summary`, `/statistics`, `/export/attendance` | Reportes y CSV | `/cobertura`, `/resumen`, `/estadisticas`, `/exportar/asistencias` |
| `GET /metrics` | Métricas para Prometheus (con `METRICS_TOKEN`) | igual |

Todo pide `Authorization: Bearer <token>`, menos `/`, `/login` y `/metrics`.

**Diferencias con la versión Node** (a propósito):

- Tres rutas que cambiaban de forma según el rol ahora son rutas separadas: `GET /schedules/me`, `GET /attendance/me` y `GET /notices/inbox` (lo propio), frente a `GET /schedules`, `GET /attendance` y `GET /notices` (lo del daycare, para manager y director). Y `GET /schedules/{userId}` y `GET /attendance/{userId}` reemplazan al `?usuarioId=`.
- Los periodos se piden con `?startDate=&endDate=` (antes `desde`/`hasta`).
- Si un manager manda `role` o `daycareId` al crear personal, recibe **403** (antes se ignoraba en silencio). Igual con `role` en `PUT /staff/{id}`.
- Los cuerpos con campos que la ruta no declara dan **400** (no hay *mass assignment*).
- Errores de validación: `400` con `{"error": "Invalid data", "details": [{"in", "field", "message"}]}`.
- `/metrics` queda apagado si no hay `METRICS_TOKEN` (antes quedaba abierto).

La documentación interactiva está en **`/docs`** y **`/redoc`** (solo con `ENVIRONMENT=development`). Hay ejemplos listos en `pruebas.http`.

## Cómo prenderla

Clona este repo y `sonrisas_cristal_db` en la misma carpeta, y copia `.env.example` como `.env`. Necesitas **Python 3.12 o más nuevo** si la corres sin Docker.

### Con Docker (como en la arquitectura)

1. Prende la base: `docker compose up -d --build` en `sonrisas_cristal_db`.
2. En el `.env` de la API pon `DATABASE_URL` con `api_user` y host `postgres`. **Si la contraseña tiene caracteres especiales (`# * ] ! = ^ @ :`) hay que codificarla** en la URL:
   ```powershell
   python -c "import urllib.parse as u; print(u.quote('tu-contraseña', safe=''))"
   ```
3. Prende la API y carga los datos de prueba:
   ```powershell
   docker compose up -d --build
   docker compose exec api python -m scripts.seed
   ```

### Sin Docker

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.create_tables   # solo si la base no la creó sonrisas_cristal_db (usa el usuario postgres)
python -m scripts.seed            # datos de prueba
uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
```

`DATABASE_URL` va con el driver de SQLAlchemy: `postgresql+psycopg://usuario:clave@host:5432/sonrisas_cristal`. Con Render, la *External Database URL* con ese prefijo y `?sslmode=require` al final.

**Cuentas de prueba** (contraseña `Cristal2026`): `ana.torres` (employee), `marisol.garcia` (manager de Cumbres) y `direccion` (director). Solo para desarrollo: nunca corras el seed en producción.

### Variables de entorno

| Variable | Para qué | Por defecto |
|---|---|---|
| `DATABASE_URL` | Conexión a PostgreSQL | obligatoria |
| `JWT_SECRET` | Firma de los tokens (mínimo 32 caracteres; rechaza el valor de ejemplo) | obligatoria |
| `JWT_EXPIRE_MINUTES` | Duración del token | `60` |
| `TZ` | Zona horaria de los daycares (qué día es "hoy", quién llega tarde) | `America/Monterrey` |
| `LATE_TOLERANCE_MINUTES` | Minutos de gracia antes de contar un retardo | `5` |
| `ENVIRONMENT` | `production` apaga `/docs` y activa HSTS | `development` |
| `METRICS_TOKEN` | Token de `/metrics` (sin él, `/metrics` está apagado) | vacío |
| `LOGIN_RATE_LIMIT` / `DEFAULT_RATE_LIMIT` | Límite por IP en `POST /login` / en las demás rutas | `5/minute` / `300/minute` |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_MINUTES` | Fallos de login por usuario antes de bloquear la cuenta, y cuánto dura | `10` / `15` |
| `TRUSTED_PROXIES` | Redes (CIDR) desde las que se cree la IP real del cliente | vacío |
| `SEED_PASSWORD` | Contraseña de las cuentas del seed | `Cristal2026` |

## Seguridad

- **El token solo dice *quién* eres.** El rol, el daycare y si sigues activo se leen de la base **en cada petición** (`get_current_user`). Una baja, un traslado o un cambio de rol aplican en la siguiente petición, sin esperar a que el token expire. Un `role` inventado dentro del token no sirve de nada, y solo se acepta HS256.
- **Permisos por rol** con dependencias, el equivalente de `Depends` que se usa en FastAPI: `ManagerOnly`, `DirectorOnly`, `ManagerOrDirector`... (`app/dependencies.py`). Lo de otro daycare responde **404**, no 403, para no confirmar que existe.
- **Fuerza bruta en el login:** límite por IP (5/min), bloqueo de la cuenta tras 10 fallos en 15 min (responde `429` + `Retry-After`) y respuesta idéntica para usuario inexistente, contraseña mala o cuenta inactiva, también en tiempo.
- **Detrás del túnel de Cloudflare** todas las peticiones llegan desde el contenedor del túnel; la IP real viene en `CF-Connecting-IP`. Esa cabecera solo se cree si la petición viene de `TRUSTED_PROXIES` (pon la subred de `sonrisas_net`: `docker network inspect sonrisas_net`). Sin eso, todos los usuarios compartirían un solo contador de 5 intentos por minuto. Ojo: si publicas el puerto 8000 en la PC, quien llegue directo por ahí también viene "de confianza"; el bloqueo por cuenta sigue protegiendo.
- **Logs en JSON**, una línea por petición (`app.request`: id, método, ruta, status, ms, usuario, IP) y los eventos de seguridad en `app.security`: `login_failed`, `login_success`, `account_locked`, `login_locked`, `rate_limited`, `auth_*`, `access_denied` (403), `password_changed`, `password_reset`, `role_changed`, `staff_created`, `staff_terminated`, `staff_transferred`, `metrics_denied`. Nunca se escribe una contraseña ni un token. Cada respuesta trae `X-Request-ID` para encontrar su línea.
- **Auditoría en la base:** cada escritura en `registro_entradas`, `asistencia` y `correccion_registro` fija antes `app.id_usuario` (`set_audit_user`), así el trigger guarda quién la hizo. `api_user` no puede borrar ni escribir en `auditoria`.
- Los datos de entrada se validan con Pydantic y las consultas pasan por SQLAlchemy (siempre parametrizadas). El CSV neutraliza las celdas que empiezan con `=`, `+`, `-` o `@`.

**Límites conocidos:** el contador de fallos de login vive en memoria, por eso el `Dockerfile` usa **un solo worker** (con varios, cada uno cuenta aparte). Cambiar la contraseña no invalida los tokens ya emitidos (duran 60 min). MinIO aparece en la arquitectura pero la API todavía no lo usa.

## Pruebas

```powershell
pip install -r requirements-dev.txt
pytest
```

Son ~100 pruebas sobre SQLite (no necesitan PostgreSQL): roles, aislamiento entre daycares, tokens, rate limit, bloqueo de cuenta, logging, checadas, correcciones, avisos y reportes.

Lo que SQLite no cubre (triggers de auditoría, restricciones `CHECK`, tipos de PostgreSQL, permisos de `api_user`) lo revisa `tests/e2e_postgres.py` contra la base real, **con una base de desarrollo** (`api_user` no puede borrar, así que deja registros):

```powershell
python -m scripts.seed
python -m tests.e2e_postgres
```

Para probar con Postman: **Import → Link → `http://localhost:8000/openapi.json`**. La colección vieja (`sonrisas_cristal.postman_collection.json`) usa las rutas de Node y ya no sirve.

## Prometheus

Pon `METRICS_TOKEN` en el `.env` de la API (pídelo por privado, no se sube al repo). Prometheus debe estar en la red `sonrisas_net` y usar el mismo token:

```yaml
scrape_configs:
  - job_name: sonrisas_api
    metrics_path: /metrics
    authorization:
      credentials_file: /etc/prometheus/metrics_token   # archivo con el METRICS_TOKEN
    static_configs:
      - targets: ['sonrisas_api:8000']
```

Métricas: `http_requests_total` y `http_request_duration_seconds` (por método, ruta con parámetros y status), `db_pool_connections` (`total`, `in_use`, `idle`) y las del proceso de Python.

## Estructura

```
app/
  main.py            crea la app: rutas, middleware (id, logs, métricas, cabeceras) y errores
  config.py          variables de entorno (pydantic-settings)
  database.py        engine, sesión y set_audit_user
  models.py          tablas (SQLAlchemy), con nombres en inglés sobre las columnas reales
  schemas.py         lo que entra y sale (Pydantic, JSON en camelCase)
  dependencies.py    get_current_user y require_role (autenticación y roles)
  access.py          qué daycare puede ver cada quien
  security.py        bcrypt, JWT, IP real, rate limit y bloqueo de cuentas
  errors.py          un solo formato de error: {"error": "..."}
  logging_config.py  logs en JSON
  metrics.py         /metrics
  constants.py       valores de la API (inglés) <-> valores de la base (español)
  timeutils.py       fechas, zona horaria y periodos
  routers/           un archivo por grupo de rutas
  services/          lógica de negocio: horarios, checadas y cálculo de asistencia/cobertura
scripts/             create_tables.py y seed.py
tests/               pytest (SQLite) y e2e_postgres.py (PostgreSQL real)
```
