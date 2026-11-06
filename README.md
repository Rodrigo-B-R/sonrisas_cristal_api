# API Sonrisas de Cristal

API REST para la app Android de Sonrisas de Cristal. Hecha con **Node.js, Express, Prisma y PostgreSQL**, con login por **JWT** y contraseñas cifradas con **bcrypt**.

Usa la base de datos del repo [`sonrisas_cristal_db`](https://github.com/Rodrigo-B-R/sonrisas_cristal_db) (`init/01-init.sql`, 15 tablas).

## Qué tiene

Tres roles, que salen de la tabla `rol`:

- **empleada**: checa entrada y salida, y ve su horario, sus asistencias y sus avisos.
- **responsable**: maneja su estancia: personal (altas, bajas, traslados), horarios, salas, asistencias, avisos y reportes.
- **direccion**: ve todas las estancias, crea estancias y da de alta Responsables.

| Ruta | Para qué |
|---|---|
| `POST /login`, `GET /perfil` | Iniciar sesión y ver mi perfil |
| `/catalogos` | Roles, puestos, turnos y causas de baja |
| `/estancias`, `/salas` | Estancias con ubicación, y salas con su mínimo de personal |
| `/personal`, `/movimientos` | Personal, altas, bajas y traslados |
| `/horarios` | Horario semanal de cada persona |
| `/registros` | Entradas y salidas (con ubicación y si está dentro de la zona) |
| `/asistencias` | Presente, retardo, falta o incidencia |
| `/avisos` | Avisos y quién los leyó |
| `/cobertura`, `/resumen`, `/estadisticas`, `/exportar/asistencias` | Reportes y CSV |

Todas las rutas, salvo `/` y `/login`, piden `Authorization: Bearer <token>`. Los ejemplos de cada una están en `pruebas.http` y en la colección de Postman.

## Cómo prenderla

Necesitas **Node.js 20.19+**, y los repos `sonrisas_cristal_api` y `sonrisas_cristal_db` en la misma carpeta.

**1. Base de datos.** Necesitas una de estas dos:
- **Render**: crea un Postgres gratis y copia la *External Database URL*.
- **Docker**: corre `docker compose up -d --build` en `sonrisas_cristal_db`.

**2. Archivo `.env`.** Copia `.env.example` como `.env` y pon tu URL en `DATABASE_URL`. Si es de Render, agrégale `?sslmode=no-verify` al final.

**3. Comandos** (en PowerShell, uno por uno):

```powershell
npm install
npm run db:crear   # crea las tablas (solo la primera vez; con Docker no hace falta)
npm run seed       # datos de prueba
npm run dev        # API en http://localhost:3000
```

Para ver la base de datos: `npm run db:ver` (abre Prisma Studio).

### Con Docker

Si tienes Docker Desktop, la API también se puede prender en un contenedor. No necesitas `npm install`.

1. Prende la base en `sonrisas_cristal_db` (`docker compose up -d --build`).
2. En el `.env` de la API, la URL de esa base lleva **`host.docker.internal`** en lugar de `localhost`. La contraseña es la de `POSTGRES_PASSWORD` en el `.env` de la base:
   ```
   DATABASE_URL="postgresql://postgres:<POSTGRES_PASSWORD>@host.docker.internal:5432/sonrisas_cristal"
   ```
3. En esta carpeta:
   ```powershell
   docker compose up -d --build
   docker compose exec api npm run seed   # datos de prueba, solo la primera vez
   ```
4. La API queda en http://localhost:3000. Para ver qué pasa: `docker compose logs -f api`. Para apagarla: `docker compose down`.

> Si ya tienes `npm run dev` prendido, apágalo antes: los dos usan el puerto 3000.

**Cuentas de prueba** (contraseña `Cristal2026`): `ana.torres` (empleada), `marisol.garcia` (responsable), `direccion`.

## Probar con Postman

1. **Import** → **files** → elige `sonrisas_cristal.postman_collection.json`.
2. Manda los 3 logins de la carpeta **0. Inicia sesión primero**. Los tokens se guardan solos.
3. Prueba las demás carpetas, o corre todo con **Run collection**.
