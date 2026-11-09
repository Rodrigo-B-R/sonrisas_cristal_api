// Métricas para Prometheus en GET /metrics.
// Si METRICS_TOKEN está en .env, Prometheus debe mandar Authorization: Bearer <METRICS_TOKEN>.
const crypto = require('crypto');
const client = require('prom-client');
const { pool } = require('./prisma');

const registro = new client.Registry();
client.collectDefaultMetrics({ register: registro }); // CPU, memoria y event loop de Node

const peticiones = new client.Counter({
  name: 'http_requests_total',
  help: 'Peticiones atendidas por la API',
  labelNames: ['method', 'route', 'status'],
  registers: [registro],
});

const duracion = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Tiempo de respuesta de la API en segundos',
  labelNames: ['method', 'route', 'status'],
  buckets: [0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5],
  registers: [registro],
});

new client.Gauge({
  name: 'db_pool_connections',
  help: 'Conexiones a PostgreSQL: total, libres y peticiones esperando una',
  labelNames: ['estado'],
  registers: [registro],
  collect() {
    this.set({ estado: 'total' }, pool.totalCount);
    this.set({ estado: 'libres' }, pool.idleCount);
    this.set({ estado: 'esperando' }, pool.waitingCount);
  },
});

// Se usa la ruta con sus parámetros (/personal/:id), no la URL real, para no crear una serie por cada id
function medir(req, res, next) {
  const terminar = duracion.startTimer();
  res.on('finish', () => {
    let route = req.route ? `${req.baseUrl}${req.route.path}` : req.baseUrl;
    if (route.length > 1) route = route.replace(/\/$/, ''); // /catalogos/ -> /catalogos
    if (!route) route = res.statusCode === 404 ? 'no_encontrada' : 'otra';
    const etiquetas = { method: req.method, route, status: String(res.statusCode) };
    peticiones.inc(etiquetas);
    terminar(etiquetas);
  });
  next();
}

function tokenValido(header) {
  const esperado = Buffer.from(`Bearer ${process.env.METRICS_TOKEN}`);
  const recibido = Buffer.from(header ?? '');
  return recibido.length === esperado.length && crypto.timingSafeEqual(recibido, esperado);
}

async function exponer(req, res) {
  if (process.env.METRICS_TOKEN && !tokenValido(req.headers.authorization)) {
    return res.status(401).json({ error: 'Token de métricas no válido' });
  }
  res.set('Content-Type', registro.contentType);
  res.send(await registro.metrics());
}

module.exports = { medir, exponer };
