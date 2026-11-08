const crypto = require('crypto');
const prisma = require('./prisma');

// Valores que aceptan las restricciones CHECK de 01-init.sql
const ROLES = ['empleada', 'responsable', 'direccion'];
const ESTADOS_ASISTENCIA = ['presente', 'retardo', 'falta', 'incidencia'];
const TIPOS_AVISO = ['cambio_horario', 'reunion', 'recordatorio', 'urgente'];
const DIAS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'];

const ESTADOS_CORRECCION = ['pendiente', 'aprobada', 'rechazada'];

// Un horario sin fecha de fin se guarda hasta esta fecha (vigente_hasta no acepta NULL)
const SIN_FIN = '2099-12-31';

// "Hoy" y los retardos usan la zona horaria de TZ.

const dos = (n) => String(n).padStart(2, '0');

const fechaLocal = (fecha) => `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
const horaLocal = (fecha) => `${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`;

const hoy = () => fechaLocal(new Date());

// Columnas DATE y TIME de Postgres: Prisma las maneja como Date en UTC.
const aFechaDb = (fecha) => new Date(`${fecha}T00:00:00Z`); //  "2026-10-07" -> Date
const deFechaDb = (fecha) => fecha.toISOString().slice(0, 10); // Date -> "2026-10-07"
const aHoraDb = (hora) => new Date(`1970-01-01T${hora}:00Z`); //  "07:00" -> Date
const deHoraDb = (hora) => hora.toISOString().slice(11, 16); //  Date -> "07:00"

function esFecha(texto) {
  if (typeof texto !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(texto)) return false;
  const d = aFechaDb(texto);
  return !Number.isNaN(d.getTime()) && deFechaDb(d) === texto; // descarta "2026-02-31"
}

const esHora = (texto) => typeof texto === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(texto);

function minutos(hora) {
  const [h, m] = hora.split(':').map(Number);
  return h * 60 + m;
}

const nombreDia = (fecha) => DIAS[(aFechaDb(fecha).getUTCDay() + 6) % 7];

const inicioDelDia = (fecha) => new Date(`${fecha}T00:00:00`);
const finDelDia = (fecha) => new Date(`${fecha}T23:59:59.999`);

function sumarDias(fecha, dias) {
  const d = aFechaDb(fecha);
  d.setUTCDate(d.getUTCDate() + dias);
  return deFechaDb(d);
}

function rangoDeFechas(desde, hasta) {
  const fechas = [];
  for (let f = desde; f <= hasta; f = sumarDias(f, 1)) fechas.push(f);
  return fechas;
}

const lunesDeLaSemana = (fecha) => sumarDias(fecha, -DIAS.indexOf(nombreDia(fecha)));

// Lee ?desde=&hasta= del query. Por defecto: de lunes de esta semana a hoy.
function leerPeriodo(query, maxDias = 100) {
  const desde = query.desde ?? lunesDeLaSemana(hoy());
  const hasta = query.hasta ?? hoy();
  if (!esFecha(desde) || !esFecha(hasta)) {
    return { error: 'Las fechas van como AAAA-MM-DD' };
  }
  if (desde > hasta) {
    return { error: '"desde" no puede ser después de "hasta"' };
  }
  if (rangoDeFechas(desde, hasta).length > maxDias) {
    return { error: `El periodo no puede pasar de ${maxDias} días` };
  }
  return { desde, hasta };
}

// fechaHora del body (registro sin conexión que llega después) o ahora; no puede ser del futuro.
function leerFechaHora(valor) {
  if (valor === undefined || valor === null) return new Date();
  const fecha = new Date(valor);
  if (Number.isNaN(fecha.getTime())) return null;
  if (fecha.getTime() > Date.now() + 5 * 60 * 1000) return null; // 5 min de margen por relojes
  return fecha;
}

// Empleada y Responsable solo ven su estancia; Dirección todas o ?estanciaId=
function filtroEstancia(req) {
  if (req.usuario.rol === 'direccion') {
    return req.query.estanciaId ? { estanciaId: Number(req.query.estanciaId) } : {};
  }
  return { estanciaId: req.usuario.estanciaId };
}

const esDeMiEstancia = (req, registro) =>
  req.usuario.rol === 'direccion' || registro.estanciaId === req.usuario.estanciaId;

// Horario vigente en una fecha: el que la cubre; si hay dos, el más nuevo (id mayor).
const incluirDias = { dias: { include: { turno: true, sala: true }, orderBy: { id: 'asc' } } };

function horarioVigente(horarios, fecha) {
  const f = aFechaDb(fecha);
  return (
    horarios
      .filter((h) => h.vigenteDesde <= f && h.vigenteHasta >= f)
      .sort((a, b) => b.id - a.id)[0] ?? null
  );
}

// Turnos que le tocan a la persona ese día: [{ turno, sala, ... }] (vacío = descansa)
function diasDelHorario(horarios, fecha) {
  const horario = horarioVigente(horarios, fecha);
  return horario ? horario.dias.filter((d) => d.diaDeSemana === nombreDia(fecha)) : [];
}

async function turnosDelDia(usuarioId, fecha) {
  const horarios = await prisma.horario.findMany({
    where: { usuarioId, vigenteDesde: { lte: aFechaDb(fecha) }, vigenteHasta: { gte: aFechaDb(fecha) } },
    include: incluirDias,
  });
  return diasDelHorario(horarios, fecha);
}

function revisarPassword(nueva, anterior) {
  const faltan = [];
  if (typeof nueva !== 'string' || nueva.length < 8) faltan.push('Al menos 8 caracteres');
  if (!/[A-Z]/.test(nueva ?? '') || !/[a-z]/.test(nueva ?? '')) faltan.push('Una mayúscula y una minúscula');
  if (!/\d/.test(nueva ?? '')) faltan.push('Un número');
  if (anterior && nueva === anterior) faltan.push('No ser igual a la anterior');
  return faltan;
}

function passwordTemporal() {
  const letras = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
  let texto = '';
  for (let i = 0; i < 8; i++) texto += letras[crypto.randomInt(letras.length)];
  return texto;
}

// Auditoría: todo lo que escriba en registro_entradas, asistencia o correccion_registro va dentro de conAutor,
// así los triggers guardan quién hizo el cambio (SET LOCAL app.id_usuario).
const conAutor = (usuarioId, trabajo) =>
  prisma.$transaction(async (tx) => {
    await tx.$executeRaw`SELECT set_config('app.id_usuario', ${String(usuarioId)}, true)`;
    return trabajo(tx);
  });

function distanciaMetros(lat1, lon1, lat2, lon2) {
  const rad = (g) => (g * Math.PI) / 180;
  const a =
    Math.sin(rad(lat2 - lat1) / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lon2 - lon1) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(a));
}

module.exports = {
  ROLES,
  ESTADOS_ASISTENCIA,
  TIPOS_AVISO,
  ESTADOS_CORRECCION,
  DIAS,
  SIN_FIN,
  fechaLocal,
  horaLocal,
  hoy,
  aFechaDb,
  deFechaDb,
  aHoraDb,
  deHoraDb,
  esFecha,
  esHora,
  minutos,
  nombreDia,
  inicioDelDia,
  finDelDia,
  sumarDias,
  rangoDeFechas,
  leerPeriodo,
  leerFechaHora,
  filtroEstancia,
  esDeMiEstancia,
  incluirDias,
  horarioVigente,
  diasDelHorario,
  turnosDelDia,
  revisarPassword,
  passwordTemporal,
  distanciaMetros,
  conAutor,
};
