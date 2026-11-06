// /asistencias  ·  "Mis asistencias" (empleada) y "Asistencia" (Responsable).
// La tabla asistencia guarda una fila por persona y día: presente | retardo | falta | incidencia.
// presente/retardo se guardan solos al registrar la entrada; falta/incidencia las pone la Responsable.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const {
  ESTADOS_ASISTENCIA,
  MOTIVOS_ASISTENCIA,
  hoy,
  esFecha,
  aFechaDb,
  rangoDeFechas,
  leerPeriodo,
  filtroEstancia,
  esDeMiEstancia,
} = require('../utilidades');
const { cargarDatos, estabaActiva, asistenciaDePersona } = require('../calculos');

const router = express.Router();

// Revisa estado y motivo. Regresa el error o null.
function revisar(estado, motivo) {
  if (!ESTADOS_ASISTENCIA.includes(estado)) {
    return { error: 'Estado no válido', opciones: ESTADOS_ASISTENCIA };
  }
  if (motivo !== undefined && motivo !== null && !MOTIVOS_ASISTENCIA.includes(motivo)) {
    return { error: 'Motivo no válido', opciones: MOTIVOS_ASISTENCIA };
  }
  if ((estado === 'falta' || estado === 'incidencia') && !motivo) {
    return { error: 'Falta e incidencia necesitan motivo', opciones: MOTIVOS_ASISTENCIA };
  }
  return null;
}

// GET /asistencias  ?desde=&hasta=  (por defecto, esta semana)
//   empleada, o con ?usuarioId=          ->  { desde, hasta, persona, resumen, dias }
//   responsable/dirección sin usuarioId  ->  [ { persona, resumen, dias }, ... ]
// Cada día junta horario + asistencia + registros. Ver estados en src/calculos.js
router.get('/', async (req, res) => {
  const periodo = leerPeriodo(req.query, 400);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  const hasta = periodo.hasta > hoy() ? hoy() : periodo.hasta;
  const desde = periodo.desde > hasta ? hasta : periodo.desde;

  const unaPersona = req.usuario.rol === 'empleada' || req.query.usuarioId;
  let where;
  if (req.usuario.rol === 'empleada') where = { id: req.usuario.id };
  else if (req.query.usuarioId) where = { id: Number(req.query.usuarioId), ...filtroEstancia(req) };
  else where = filtroEstancia(req);

  const datos = await cargarDatos(where, desde, hasta);
  const fechas = rangoDeFechas(desde, hasta);
  const resultado = datos.personas
    .filter((p) => unaPersona || fechas.some((f) => estabaActiva(p, f))) // sin quien no trabajó en el periodo
    .map((p) => asistenciaDePersona(p, fechas, datos));
  if (unaPersona) {
    if (resultado.length === 0) return res.status(404).json({ error: 'No encontrado' });
    return res.json({ desde, hasta, ...resultado[0] });
  }
  res.json(resultado);
});

// POST /asistencias  { usuarioId, fecha, estado, motivo? }  ->  201 (o 200 si ya había y se corrigió)
// La Responsable marca una falta o incidencia, o corrige el estado de un día.
router.post('/', permitir('responsable'), async (req, res) => {
  const { usuarioId, fecha, estado, motivo } = req.body ?? {};
  if (!usuarioId || !fecha || !estado) {
    return res.status(400).json({ error: 'Faltan usuarioId, fecha o estado' });
  }
  if (!esFecha(fecha)) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const error = revisar(estado, motivo);
  if (error) {
    return res.status(400).json(error);
  }
  const persona = await prisma.usuario.findUnique({ where: { id: Number(usuarioId) } });
  if (!persona || !esDeMiEstancia(req, persona)) {
    return res.status(404).json({ error: 'Persona no encontrada' });
  }
  const clave = { usuarioId: persona.id, estanciaId: persona.estanciaId, fecha: aFechaDb(fecha) };
  const existente = await prisma.asistencia.findUnique({ where: { usuarioId_estanciaId_fecha: clave } });
  const datos = { estado, motivo: motivo ?? null, registradoPorId: req.usuario.id };
  if (existente) {
    return res.json(await prisma.asistencia.update({ where: { id: existente.id }, data: datos }));
  }
  res.status(201).json(await prisma.asistencia.create({ data: { ...clave, ...datos } }));
});

// PUT /asistencias/:id  { estado, motivo? }  (la Responsable corrige)
router.put('/:id', permitir('responsable'), async (req, res) => {
  const id = Number(req.params.id);
  const asistencia = await prisma.asistencia.findUnique({ where: { id } });
  if (!asistencia || !esDeMiEstancia(req, asistencia)) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  const { estado = asistencia.estado, motivo } = req.body ?? {};
  const error = revisar(estado, motivo);
  if (error) {
    return res.status(400).json(error);
  }
  const actualizada = await prisma.asistencia.update({
    where: { id },
    data: { estado, motivo: motivo ?? null, registradoPorId: req.usuario.id },
  });
  res.json(actualizada);
});

module.exports = router;
