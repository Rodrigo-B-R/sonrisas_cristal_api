require('dotenv/config');
process.env.TZ = process.env.TZ || 'America/Monterrey'; // antes de usar cualquier fecha

if (!process.env.DATABASE_URL || !process.env.JWT_SECRET) {
  console.error('Faltan variables de entorno: DATABASE_URL y JWT_SECRET (revisa tu .env)');
  process.exit(1);
}

const express = require('express');
const { verificarToken } = require('./middleware/auth');
const { medir, exponer } = require('./metricas');

const app = express();

app.use(medir);
app.use(express.json());

// Las columnas DATE y TIME se responden cortas: "2026-11-04" y "07:00".
const CAMPOS_FECHA = ['fecha', 'vigenteDesde', 'vigenteHasta'];
const CAMPOS_HORA = ['horaEntrada', 'horaSalida'];
app.set('json replacer', (clave, valor) => {
  if (typeof valor !== 'string') return valor;
  if (CAMPOS_FECHA.includes(clave) && /T00:00:00.000Z$/.test(valor)) return valor.slice(0, 10);
  if (CAMPOS_HORA.includes(clave) && valor.startsWith('1970-01-01T')) return valor.slice(11, 16);
  return valor;
});

app.use((req, res, next) => {
  console.log(`${req.method} ${req.url}`);
  next();
});

app.get('/', (req, res) => {
  res.json({ mensaje: 'API de Sonrisas de Cristal funcionando' });
});

// Para Prometheus (protegido con METRICS_TOKEN si está en .env)
app.get('/metrics', exponer);

// POST /login, y con token: GET /perfil, PUT /perfil/password
app.use(require('./rutas/sesion'));

// Todo lo de abajo pide token
app.use('/catalogos', verificarToken, require('./rutas/catalogos'));
app.use('/estancias', verificarToken, require('./rutas/estancias'));
app.use('/salas', verificarToken, require('./rutas/salas'));
app.use('/personal', verificarToken, require('./rutas/personal'));
app.use('/movimientos', verificarToken, require('./rutas/movimientos'));
app.use('/horarios', verificarToken, require('./rutas/horarios'));
app.use('/registros', verificarToken, require('./rutas/registros'));
app.use('/correcciones', verificarToken, require('./rutas/correcciones'));
app.use('/asistencias', verificarToken, require('./rutas/asistencias'));
app.use('/avisos', verificarToken, require('./rutas/avisos'));
app.use('/auditoria', verificarToken, require('./rutas/auditoria'));
// GET /cobertura, /resumen, /estadisticas, /exportar/asistencias
// (cada ruta pide el token por su cuenta, para que una ruta inexistente dé 404 y no 401)
app.use(require('./rutas/reportes'));

app.use((req, res) => {
  res.status(404).json({ error: 'Ruta no encontrada' });
});

// Express 5 manda aquí cualquier error de una ruta async.
app.use((err, req, res, next) => {
  if (err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: 'El body no es JSON válido' });
  }
  if (err.code === 'P2002') {
    return res.status(409).json({ error: 'Ya existe un registro con ese dato (por ejemplo, clave o correo repetido)' });
  }
  if (err.code === 'P2003') {
    return res.status(409).json({ error: 'No se puede: tiene datos relacionados' });
  }
  if (err.code === 'P2025') {
    return res.status(404).json({ error: 'No encontrado' });
  }
  if (err.code === '23514' || err.meta?.driverAdapterError?.cause?.kind === 'CheckViolation' || /check constraint/i.test(err.message ?? '')) {
    return res.status(400).json({ error: 'Los datos no cumplen las reglas de la base de datos' });
  }
  if (err.name === 'PrismaClientValidationError') {
    return res.status(400).json({ error: 'Datos no válidos' });
  }
  console.error(err);
  res.status(500).json({ error: 'Error interno' });
});

const PORT = process.env.PORT || 8000;
app.listen(PORT, (error) => {
  if (error) {
    console.error(
      error.code === 'EADDRINUSE'
        ? `El puerto ${PORT} ya está ocupado por otro programa. Ciérralo o usa otro puerto: $env:PORT=${Number(PORT) + 1}; npm run dev`
        : error,
    );
    process.exit(1);
  }
  console.log(`API en http://localhost:${PORT}`);
});
