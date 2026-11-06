# API PARA APLICACION ANDROID SONRISAS DE CRISTAL

API REST con **Node.js + Express 5 + Prisma 7 + PostgreSQL**, protegida con **JWT** y contraseñas con **bcrypt**. Sigue la misma estructura que la API de ejemplo de la clase ([jorflores/api-usuarios-2026](https://github.com/jorflores/api-usuarios-2026)). La consume la app Android `access_tracker_android` con Retrofit.

**La base de datos es la del repo `sonrisas_cristal_db`** (`init/01-init.sql`, 15 tablas). La API no crea ni cambia tablas: solo las usa. Tampoco borra nada, porque el usuario `api_user` de la base solo tiene permiso de leer, insertar y actualizar.

## Roles

| Rol | Quién es | Qué puede hacer |
|---|---|---|
| `empleada` | Personal de una estancia | Checar entrada/salida, ver su horario, sus asistencias y sus avisos |
| `responsable` | Encargada de **una** estancia | Todo lo de su estancia: personal, horarios, salas, asistencias, avisos, exportar |
| `direccion` | Dirección general | Ver **todas** las estancias (resumen, estadísticas), crear estancias, dar de alta Responsables, trasladar personal |

Los roles salen de la tabla `rol`. El token guarda `{ id, rol, estanciaId }`. La Responsable solo ve y cambia lo de su estancia. Lo que no es suyo responde **404**, como si no existiera.

## Qué tabla usa cada cosa

| Tabla | En la API |
|---|---|
| `rol`, `puesto`, `turno`, `causa_baja` | `GET /catalogos` (para los menús de la app) |
| `ubicacion`, `estancia`, `sala` | `/estancias`, `/salas` |
| `usuario` | `/login`, `/perfil`, `/personal` |
| `movimiento_usuario` | se llena solo en alta, baja y traslado · `GET /movimientos` |
| `horario`, `horario_dia` | `/horarios` |
| `registro_entradas` | `/registros` (entrada y salida en la misma fila) |
| `asistencia` | se llena sola al checar entrada (presente o retardo) · `/asistencias` para faltas e incidencias |
| `aviso`, `aviso_usuario` | `/avisos` |

## Endpoints

Todo pide `Authorization: Bearer <token>` menos `/` y `/login`. Sin token o con token vencido: **401**. Con un rol que no puede: **403**.

**Sesión y catálogos**

| Método | Ruta | Rol | Body | Responde |
|---|---|---|---|---|
| GET | `/` | — | — | 200 `{ mensaje }` |
| POST | `/login` | — | `{ clave, password }` | 200 `{ token, rol, usuario }` · 401 |
| GET | `/perfil` | cualquiera | — | 200 usuario con `rol`, `puesto` y `estancia` |
| PUT | `/perfil/password` | cualquiera | `{ actual, nueva }` | 200 · 400 `{ faltan: [...] }` · 401 |
| GET | `/catalogos` | cualquiera | — | 200 `{ roles, puestos, turnos, causasBaja }` |
| POST | `/catalogos/puestos` · `/catalogos/causas-baja` | direccion | `{ nombre }` | 201 |
| PUT | `/catalogos/turnos/:id` | direccion | `{ nombre?, horaEntrada?, horaSalida? }` | 200 |

**Estancias, salas y personal**

| Método | Ruta | Rol | Body | Responde |
|---|---|---|---|---|
| GET | `/estancias` · `/estancias/:id` | cualquiera | — | 200 con `ubicacion` y `salas` |
| POST · PUT | `/estancias` · `/estancias/:id` | direccion | `{ nombre, latitud, longitud, precision? }` | 201 / 200 |
| GET | `/salas` · `/salas/:id` | cualquiera | `?estanciaId=` (dirección) | 200 |
| POST · PUT | `/salas` · `/salas/:id` | responsable | `{ nombre, minimoPersonal }` | 201 / 200 |
| GET | `/personal` | responsable, direccion | `?activo=false\|todos` | 200 lista |
| GET | `/personal/:id` | responsable, direccion | — | 200 con `horarioVigente` y `movimientos` · 404 |
| POST | `/personal` | responsable, direccion | `{ nombre, clave, correo, celular, puestoId, password?, fecha? }` (dirección: `rol`, `estanciaId`) | 201 + `passwordTemporal` · 409 |
| PUT | `/personal/:id` | responsable, direccion | `{ nombre?, clave?, correo?, celular?, puestoId? }` | 200 |
| POST | `/personal/:id/baja` | responsable, direccion | `{ causaBajaId, fecha?, observaciones? }` | 200 · 409 si ya era baja |
| POST | `/personal/:id/traslado` | responsable, direccion | `{ estanciaId, fecha?, observaciones? }` | 200 |
| POST | `/personal/:id/password` | responsable, direccion | — | 200 `{ passwordTemporal }` |
| GET | `/movimientos` | responsable, direccion | `?desde=&hasta=&tipo=alta\|baja\|traslado` | 200 historial |

**Día a día**

| Método | Ruta | Rol | Body | Responde |
|---|---|---|---|---|
| GET | `/horarios` | cualquiera | `?fecha=&usuarioId=` | empleada: su horario · otros: `[{ persona, horario }]` |
| PUT | `/horarios/:usuarioId` | responsable | `{ desde?, dias: [{ dia, turnoId, salaId }] }` | 201 horario nuevo |
| GET | `/registros/estado` | cualquiera | — | 200 `{ dentro, registroAbierto, turnosHoy, ubicacion }` |
| GET | `/registros` | cualquiera | `?desde=&hasta=&usuarioId=&dentroDeZona=false` | 200 |
| POST | `/registros/entrada` | empleada, responsable | `{ uuid?, fechaHora?, latitud?, longitud?, dentroDeZona?, salaId?, turnoId? }` | 201 `{ registro, asistencia }` · 200 si el `uuid` ya llegó · 409 si ya hay entrada abierta |
| POST | `/registros/salida` | empleada, responsable | `{ fechaHora? }` | 200 · 409 si no hay entrada abierta |
| POST | `/registros/turno` | responsable | `{ usuarioIds, fechaHora?, salaId?, turnoId? }` | 201 `{ registradas, omitidas }` |
| PUT | `/registros/:id` | responsable | `{ fechaHoraEntrada?, fechaHoraSalida? }` | 200 |
| GET | `/asistencias` | cualquiera | `?desde=&hasta=&usuarioId=` | `{ persona, resumen, dias }` (o una lista para la estancia) |
| POST | `/asistencias` | responsable | `{ usuarioId, fecha, estado, motivo? }` | 201 (o 200 si ese día ya tenía y se corrigió) |
| PUT | `/asistencias/:id` | responsable | `{ estado, motivo? }` | 200 |
| GET | `/avisos` | cualquiera | — | empleada: los suyos con `leido` · otros: con `destinatarios` y `confirmaron` |
| GET | `/avisos/:id` | cualquiera | — | empleada: con `leido` · otros: `confirmados` y `pendientes` |
| POST | `/avisos` | responsable | `{ asunto, mensaje, tipoAviso, destino, turnoId?, salaId?, usuarioIds? }` | 201 |
| POST | `/avisos/:id/lectura` | cualquiera | — | 200 `{ avisoId, leido, leidoEn }` · 404 si no es para ti |

**Reportes** (se calculan al momento)

| Método | Ruta | Rol | Query | Responde |
|---|---|---|---|---|
| GET | `/cobertura` | responsable, direccion | `?fecha=` (dirección: `&estanciaId=`) | por sala y turno: mínimo, programados, presentes, faltan |
| GET | `/resumen` | direccion | `?fecha=` | estancias completas y con faltante |
| GET | `/estadisticas` | responsable, direccion | `?desde=&hasta=&estanciaId=` | altas, bajas, faltas, retardos, días con personal insuficiente, absentismo |
| GET | `/exportar/asistencias` | responsable, direccion | `?desde=&hasta=` | archivo CSV |

**Valores permitidos** (son los CHECK de `01-init.sql`)

- Fechas: `"AAAA-MM-DD"`. Horas: `"HH:MM"`. `fechaHora`: ISO 8601 (`"2026-11-04T07:02:00-06:00"`).
- `dia` de horario: `lunes`, `martes`, `miercoles`, `jueves`, `viernes`, `sabado`, `domingo` (sin acentos).
- Asistencia `estado`: `presente`, `retardo`, `falta`, `incidencia`. `motivo`: `enfermedad`, `permiso`, `personal`, `transporte` u `otro` (falta e incidencia lo necesitan).
- Aviso `tipoAviso`: `cambio_horario`, `reunion`, `recordatorio` o `urgente`. `asunto` y `mensaje` de máximo 255 caracteres.
- `retardo` = llegar más de `TOLERANCIA_MINUTOS` después de la hora de entrada del turno.
- En `/asistencias`, un día con turno y sin nada registrado sale como `sin_registro` (cuenta como falta en las estadísticas). Hoy, antes de llegar: `pendiente`.
- Fuera de zona: si la app manda `latitud` y `longitud`, la API calcula si está dentro del radio (`precision`, en metros) de la ubicación de la estancia. Se guarda igual; la Responsable lo revisa con `?dentroDeZona=false`.
- `uuid`: lo genera el celular para cada checada. Si se reenvía (por ejemplo, al volver el internet), la API regresa la que ya tenía y no la duplica.
- Nueva contraseña: mínimo 8 caracteres, con mayúscula, minúscula y número.
- **El password nunca sale en una respuesta**: el cliente de Prisma lo omite siempre (ver `src/prisma.js`).

## Estructura

```
sonrisas_cristal_api/
├── prisma/
│   ├── schema.prisma          # describe las 15 tablas de 01-init.sql (no las crea)
│   └── seed.js                # catálogos, estancias, salas y personal de prueba
├── scripts/
│   └── crear-tablas.js        # npm run db:crear: corre el 01-init.sql del equipo
├── src/
│   ├── index.js               # Express: middleware, monta las rutas y manejo de errores
│   ├── prisma.js              # PrismaClient con el adaptador de pg
│   ├── utilidades.js          # fechas, alcance por estancia, horario vigente, contraseñas
│   ├── calculos.js            # arma cada día (horario + asistencia + registros) y la cobertura
│   ├── middleware/auth.js     # verificarToken y permitir(...roles)
│   └── rutas/                 # un Router de Express por recurso
│       ├── sesion.js  catalogos.js  estancias.js  salas.js
│       ├── personal.js  movimientos.js  horarios.js
│       ├── registros.js  asistencias.js  avisos.js
│       └── reportes.js        #   /cobertura, /resumen, /estadisticas, /exportar
├── prisma.config.js           # Prisma 7: dónde está el schema y DATABASE_URL
├── pruebas.http               # peticiones listas para probar (REST Client de VS Code)
├── sonrisas_cristal.postman_collection.json   # las mismas, para importar en Postman
└── .env.example               # copia como .env
```

## Correr en tu computadora (paso a paso)

### Qué necesitas

- **Node.js 20.19 o más nuevo.** Revisa con `node -v`. Si no lo tienes, descarga la versión LTS de https://nodejs.org.
- **Git.**
- **Postman**, para probar (opcional).
- **Los dos repos en la misma carpeta**, uno al lado del otro. La API toma el script de las tablas de `../sonrisas_cristal_db/init/01-init.sql`:

```
sonrisas_cristal/
├── sonrisas_cristal_api/   ← este repo
└── sonrisas_cristal_db/    ← el repo de la base de datos
```

En PowerShell, una línea a la vez. En PowerShell 5 no funciona `&&`.

```powershell
mkdir sonrisas_cristal
cd sonrisas_cristal
git clone https://github.com/Rodrigo-B-R/sonrisas_cristal_api.git
git clone https://github.com/Rodrigo-B-R/sonrisas_cristal_db.git
cd sonrisas_cristal_api
```

Si ya los tenías clonados, entra a cada uno y corre `git pull` para traer lo último.

### Paso 1. Consigue una base de datos

Elige **una** opción.

**A) Render (recomendado: gratis y no instalas nada)**
1. Entra a https://render.com con tu cuenta de GitHub.
2. **New → Postgres**. Ponle un nombre, elige el plan **Free** y da **Create Database**.
3. Cuando diga **Available**, copia la **External Database URL**.

> Si alguien del equipo ya creó la base en Render, puede pasarles la URL **por privado** (nunca en el repo). Así todos ven los mismos datos y se saltan `db:crear` y `seed` en el paso 4.

**B) Docker (si tienes Docker Desktop)**
1. En `../sonrisas_cristal_db` sigue su README (`docker compose up -d --build`).
2. Ahí las tablas se crean solas, así que en el paso 4 te saltas `npm run db:crear`.
3. Tu URL es `postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5432/sonrisas_cristal`. La contraseña es la del `.env` de ese repo.

### Paso 2. Crea tu archivo `.env`

```powershell
copy .env.example .env
notepad .env
```

Cambia **solo** la línea `DATABASE_URL` por tu URL:

- **Render:** agrega `?sslmode=no-verify` al final, pegado y antes de la comilla. Sin esto sale el error `SSL/TLS required`.
  ```
  DATABASE_URL="postgresql://usuario:clave@dpg-xxxx.oregon-postgres.render.com/nombre_db?sslmode=no-verify"
  ```
- **Docker:**
  ```
  DATABASE_URL="postgresql://postgres:cambia_esta_clave@localhost:5432/sonrisas_cristal"
  ```

Guarda con **Ctrl + S**. El `.env` **no se sube a GitHub** porque está en `.gitignore`. No lo compartan en el repo.

### Paso 3. Instala las dependencias

```powershell
npm install
```

Solo la primera vez, o cuando alguien agregue paquetes nuevos.

### Paso 4. Crea las tablas y los datos de prueba (solo la primera vez)

```powershell
npm run db:crear
npm run seed
```

- `db:crear` corre `../sonrisas_cristal_db/init/01-init.sql` y debe decir `Listo: 15 tablas creadas`. Si las tablas ya existen, avisa y no toca nada. Si el script está en otro lado: `npm run db:crear -- C:\ruta\al\script.sql`.
- `seed` llena los catálogos, 5 estancias, sus salas y el personal de prueba. Debe decir `Seed listo`. Volver a correrlo no duplica nada.

### Paso 5. Prende la API

```powershell
npm run dev
```

Debe decir **`API en http://localhost:3000`**. **Deja esa terminal abierta**: si la cierras, se apaga la API. Para probar que está viva, abre http://localhost:3000 en el navegador.

### Paso 6. Ve la base de datos (opcional)

En **otra** terminal, dentro de `sonrisas_cristal_api`:

```powershell
npm run db:ver
```

Se abre **Prisma Studio** en el navegador (http://localhost:5555). A la izquierda están las tablas: da clic en una para ver sus filas, y recarga después de cada prueba para ver los cambios. Se cierra con **Ctrl + C**. Con Docker también tienes pgAdmin en http://localhost:5050.

### Cada vez que vuelvas a trabajar

Solo necesitas:

```powershell
cd sonrisas_cristal_api
git pull
npm install
npm run dev
```

Cuentas del seed (contraseña = `SEED_PASSWORD`, por defecto `Cristal2026`):

| Clave | Rol | Estancia |
|---|---|---|
| `direccion` | direccion | registrada en Cumbres, ve todas |
| `marisol.garcia` | responsable | Cumbres |
| `ana.torres`, `lucia.herrera`, `carmen.ruiz`, `sofia.diaz`, `paola.reyes`, `rosa.medina`, `maria.lopez` | empleada | Cumbres |

> Volver a correr `npm run seed` no duplica nada y regresa esas cuentas a su contraseña de prueba.

## Probar con Postman

1. Con la API prendida (`npm run dev`), abre Postman → **Import** → **files** (no *folders*) → elige `sonrisas_cristal.postman_collection.json`.
   > Si ya la habías importado antes, bórrala primero en Postman (clic derecho → **Delete**) para traer la versión nueva.
2. Abre la carpeta **0. Inicia sesión primero** y da **Send** a los 3 logins. Cada uno debe dar **200**. Postman guarda solo el token de cada rol, no tienes que copiar nada.
3. Después manda cualquier petición de las demás carpetas. O todo junto: clic derecho en la colección → **Run collection** → **Run**.
4. Si la API está en otro puerto o en Render, cambia la variable `base` (clic en la colección → **Variables**). Arriba a la derecha puede quedar **No Environment**.

El token dura 1 hora. Si empiezan a salir **401**, vuelve a mandar los logins.

| Código | Significa |
|---|---|
| 200 / 201 | Funcionó |
| 400 | Falta un dato o está mal (la respuesta dice cuál) |
| 401 | Sin sesión o token vencido |
| 403 | Ese rol no tiene permiso (en la carpeta *Errores* es lo esperado) |
| 404 | No existe, o no es de tu estancia |
| 409 | Ya existe (por ejemplo, una clave repetida) |

Los id de los ejemplos son los que deja el seed en una base nueva. Si corres la colección dos veces, las altas responden 409 porque esas claves ya existen. Es lo esperado.

## Problemas comunes

| Mensaje | Qué hacer |
|---|---|
| `SSL/TLS required` | A la URL de Render en `.env` le falta `?sslmode=no-verify` al final. |
| `Falta DATABASE_URL en tu .env` | No creaste el `.env` (paso 2) o no estás en la carpeta `sonrisas_cristal_api`. |
| `No encontré el script SQL en ...` | El repo `sonrisas_cristal_db` no está al lado de la API. Clónalo ahí o pasa la ruta: `npm run db:crear -- C:\ruta\01-init.sql`. |
| `El puerto 3000 ya está ocupado` | Otra cosa usa ese puerto. Corre lo que el mensaje sugiere, por ejemplo `$env:PORT=3001; npm run dev`, y cambia `base` en Postman a `http://localhost:3001`. |
| `'&&' no es un separador válido` | PowerShell 5 no acepta `&&`. Escribe los comandos uno por uno. |
| Postman: `ECONNRESET` o `connect ECONNREFUSED` | La API no está prendida o se estaba reiniciando. Revisa que la terminal diga `API en http://localhost:3000` y vuelve a dar **Send**. |
| Postman: `401` en todo | No has hecho los logins o pasó 1 hora. Repite la carpeta **0. Inicia sesión primero**. |
| La primera petición tarda mucho | La base gratuita de Render se "duerme". Espera y vuelve a intentar. |
| `npm` o `node` no se reconoce | Instala Node.js LTS y abre una terminal nueva. |

## Desplegar en Render

1. **Base de datos:** New → Postgres → plan Free.
   > La base gratuita vence 30 días después de crearla (más 14 días de gracia antes de borrar los datos).
2. **Crea las tablas desde tu compu**, con la External Database URL en tu `.env`: `npm run db:crear` y `npm run seed`.
3. **Sube este proyecto a GitHub** (el `.gitignore` ya excluye `node_modules` y `.env`).
4. **API:** New → Web Service → conecta el repositorio.
   - Build Command: `npm install`
   - Start Command: `npm start`
   - Environment:
     - `DATABASE_URL` = la **Internal** Database URL del paso 1
     - `JWT_SECRET` = un texto largo y secreto
     - `TZ` = `America/Monterrey` (Render corre en UTC; sin esto los retardos salen mal)
5. Abre `https://<tu-servicio>.onrender.com/` y en Postman cambia la variable `base` a esa URL.

> El plan gratuito se duerme tras 15 minutos sin tráfico; la primera petición tarda cerca de un minuto. Ábrela en el navegador antes de la demo.

## Desde Android (Retrofit)

- URL base: `https://<tu-servicio>.onrender.com/` (con `/` al final). Local desde el emulador: `http://10.0.2.2:3000/` + `usesCleartextTraffic="true"` solo en desarrollo.
- Login: `@POST("login") suspend fun login(@Body datos: LoginRequest): LoginResponse` con `LoginRequest(clave, password)` y `LoginResponse(token, rol, usuario)`. Con `rol` decides qué grafo abrir.
- Rutas protegidas: `@Header("Authorization") auth: String` y mandar `"Bearer $token"`.
- Checar: genera un `UUID.randomUUID().toString()` por checada y mándalo como `uuid` con `latitud` y `longitud`. Sin internet, guárdala con su `fechaHora` y reenvíala igual después.
- El CSV de `/exportar/asistencias` llega como texto: declara `ResponseBody` y guárdalo como archivo.

## Atajos de clase (no para producción)

- Dirección necesita una estancia (`usuario.id_estancia` no acepta NULL); el seed la registra en Cumbres, pero ve todas.
- Un horario sin fin se guarda con `vigente_hasta = 2099-12-31` (la columna no acepta NULL).
- Una persona dada de baja no puede iniciar sesión, pero un token que ya tenía sigue sirviendo hasta que vence (1 hora).
- La contraseña temporal viaja en la respuesta del alta para que la Responsable se la dé a la persona.
- No hay notificaciones push.
