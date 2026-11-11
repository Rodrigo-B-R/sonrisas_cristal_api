# API Sonrisas de Cristal

API REST para la app Android de Sonrisas de Cristal, con **Node.js, Express, Prisma y PostgreSQL**. Login con **JWT** y contraseñas con **bcrypt**.

Usa la base del repo [`sonrisas_cristal_db`](https://github.com/Rodrigo-B-R/sonrisas_cristal_db) (`init/01-init.sql`). Está al día con el commit `6d97ba8` (`master` y `correcciones_bd_s2`): 18 tablas, con motivos de ausencia, correcciones y auditoría.

## Rutas

Roles: **empleada**, **responsable** (su estancia) y **direccion** (todas).

| Ruta | Para qué |
|---|---|
| `POST /login`, `GET /perfil` | Sesión y perfil |
| `/catalogos` | Roles, puestos, turnos, causas de baja y motivos de ausencia |
| `/estancias`, `/salas` | Estancias, ubicación y mínimo de personal por sala |
| `/personal`, `/movimientos` | Personal, altas, bajas y traslados |
| `/horarios` | Horario semanal |
| `/registros` | Entradas y salidas |
| `/correcciones` | Pedir y aprobar correcciones de hora |
| `/asistencias` | Presente, retardo, falta o incidencia |
| `/avisos` | Avisos y confirmación de lectura (dirección puede mandar avisos generales) |
| `/auditoria` | Quién cambió qué (dirección) |
| `/cobertura`, `/resumen`, `/estadisticas`, `/exportar/asistencias` | Reportes y CSV |
| `GET /metrics` | Métricas para Prometheus (con `METRICS_TOKEN`) |

Todo pide `Authorization: Bearer <token>`, menos `/`, `/login` y `/metrics`. Hay ejemplos en `pruebas.http` y en la colección de Postman.

## Seguridad

- **Login:** máximo 5 intentos por minuto por IP (después responde `429`).
- **Token (JWT HS256, 1 h):** en cada petición se revisa que la persona siga activa y se usan su rol y estancia actuales. Si le dan de baja o cambia su contraseña, sus tokens viejos dejan de servir (`PUT /perfil/password` regresa uno nuevo).
- **Cabeceras:** `nosniff`, `X-Frame-Options`, `HSTS`, `CSP`, `Cache-Control: no-store`, sin `X-Powered-By`.
- **Datos:** textos de máximo 255 caracteres, listas de máximo 200 y body de máximo 20 KB. El CSV neutraliza fórmulas de Excel.
- **Base:** se conecta con `api_user`, que no puede borrar ni editar la auditoría.

**Para la app Android:** si cualquier petición responde `401`, manda a la pantalla de login. Al cambiar la contraseña, guarda el `token` nuevo de la respuesta.

## Cómo prenderla

Clona este repo y `sonrisas_cristal_db` en la misma carpeta. Luego copia `.env.example` como `.env`.

**Con Render:** pon la *External Database URL* en `DATABASE_URL`, con `?sslmode=no-verify` al final. Después:

```powershell
npm install
npm run db:crear   # tablas (solo la primera vez)
npm run seed       # datos de prueba
npm run dev        # http://localhost:8000
```

Para ver la base: `npm run db:ver`.

**Con Docker:** primero prende la base con `docker compose up -d --build` en `sonrisas_cristal_db`. Luego, en `.env`, pon `DATABASE_URL="postgresql://api_user:<API_DB_PASSWORD>@postgres:5432/sonrisas_cristal"`. Después:

```powershell
docker compose up -d --build
docker compose exec api npm run seed
```

**Cuentas de prueba** (contraseña `Cristal2026`): `ana.torres`, `marisol.garcia`, `direccion`. El seed es solo para pruebas, no se corre en producción.

Opcionales en `.env`: `PORT` (8000), `LOGIN_INTENTOS_POR_MINUTO` (5) y `TRUST_PROXY=1` si va detrás de Cloudflare o nginx.

## Postman

Importa `sonrisas_cristal.postman_collection.json` (**Import → files**). Manda primero los 3 logins de **0. Inicia sesión primero** y luego prueba las demás carpetas. Si mandas más de 5 logins en un minuto te sale `429`: espera un minuto.

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
