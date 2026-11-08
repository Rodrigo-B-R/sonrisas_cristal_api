# API Sonrisas de Cristal

API REST para la app Android de Sonrisas de Cristal. Hecha con **Node.js, Express, Prisma y PostgreSQL**, con login por **JWT** y contraseñas cifradas con **bcrypt**.

Usa la base de datos del repo [`sonrisas_cristal_db`](https://github.com/Rodrigo-B-R/sonrisas_cristal_db) (`init/01-init.sql`, 18 tablas).

## Qué tiene

Tres roles, que salen de la tabla `rol`:

- **empleada**: checa entrada y salida, ve su horario, sus asistencias y sus avisos, y pide correcciones de hora.
- **responsable**: maneja su estancia: personal (altas, bajas, traslados), horarios, salas, asistencias, avisos, correcciones y reportes.
- **direccion**: ve todas las estancias, crea estancias, da de alta Responsables y consulta la auditoría.

| Ruta | Para qué |
|---|---|
| `POST /login`, `GET /perfil` | Iniciar sesión y ver mi perfil |
| `/catalogos` | Roles, puestos, turnos, causas de baja y motivos de ausencia |
| `/estancias`, `/salas` | Estancias con ubicación, y salas con su mínimo de personal |
| `/personal`, `/movimientos` | Personal, altas, bajas y traslados |
| `/horarios` | Horario semanal de cada persona |
| `/registros` | Entradas y salidas (con ubicación y si está dentro de la zona) |
| `/correcciones` | La empleada pide corregir una hora; la Responsable aprueba o rechaza |
| `/asistencias` | Presente, retardo, falta o incidencia (con motivo del catálogo) |
| `/avisos` | Avisos, si requieren confirmación y quién los leyó |
| `/auditoria` | Quién cambió registros, asistencias y correcciones (dirección) |
| `/cobertura`, `/resumen`, `/estadisticas`, `/exportar/asistencias` | Reportes y CSV |

Todas las rutas, salvo `/` y `/login`, piden `Authorization: Bearer <token>`. Los ejemplos de cada una están en `pruebas.http` y en la colección de Postman.

La auditoría la llena la base sola con triggers. La API le dice quién hace cada cambio (`conAutor` en `src/utilidades.js`).

## Cómo prenderla

Necesitas los repos `sonrisas_cristal_api` y `sonrisas_cristal_db` en la misma carpeta. Elige **una** de estas dos formas.

### Opción A: con Render (sin Docker)

Necesitas **Node.js 20.19+**.

1. En Render crea un Postgres gratis y copia la *External Database URL*.
2. Copia `.env.example` como `.env` y pon esa URL en `DATABASE_URL`, con `?sslmode=no-verify` al final.
3. En PowerShell, uno por uno:

```powershell
npm install
npm run db:crear   # crea las tablas con ../sonrisas_cristal_db/init/01-init.sql (solo la primera vez)
npm run seed       # datos de prueba
npm run dev        # API en http://localhost:3000
```

Para ver la base de datos: `npm run db:ver` (abre Prisma Studio).

### Opción B: con Docker

La base de Docker no abre puertos en tu compu: solo se puede entrar desde la red `sonrisas_net`. Por eso la API también corre en Docker, dentro de esa red.

1. Prende la base en `sonrisas_cristal_db` (`docker compose up -d --build`). Ahí las tablas se crean solas.
2. Copia `.env.example` como `.env`. En `DATABASE_URL` usa el `API_DB_PASSWORD` del `.env` de la base:
   ```
   DATABASE_URL="postgresql://api_user:<API_DB_PASSWORD>@postgres:5432/sonrisas_cristal"
   ```
3. En esta carpeta:
   ```powershell
   docker compose up -d --build
   docker compose exec api npm run seed   # datos de prueba, solo la primera vez
   ```
4. La API queda en http://localhost:3000. Para ver qué pasa: `docker compose logs -f api`. Para apagarla: `docker compose down`.

Para ver la base de datos con Docker, usa pgAdmin en http://localhost:5050.

**Cuentas de prueba** (contraseña `Cristal2026`): `ana.torres` (empleada), `marisol.garcia` (responsable), `direccion`.

## Probar con Postman

1. **Import** → **files** → elige `sonrisas_cristal.postman_collection.json`.
2. Manda los 3 logins de la carpeta **0. Inicia sesión primero**. Los tokens se guardan solos.
3. Prueba las demás carpetas, o corre todo con **Run collection**.

Los id de los ejemplos son los de una base recién creada con `npm run seed`. Si corres la colección otra vez, algunas peticiones dan **409** porque esos datos ya existen.
