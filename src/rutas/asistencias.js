// /asistencias: presente/retardo se guardan al checar entrada; falta/incidencia las pone la Responsable.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const {
  ESTADOS_ASISTENCIA,
  hoy,
  esFecha,
  aFechaDb,
  rangoDeFechas,
  leerPeriodo,
  filtroEstancia,
  esDeMiEstancia,
  conAutor,
} = require('../utilidades');
const { cargarDatos, estabaActiva, asistenciaDePersona } = require('../calculos');

const router = express.Router();

const conMotivo = { include: { motivo: true } };

// El motivo sale de motivo_ausencia: se manda motivoId o motivo (descripción). Regresa { motivoId } o { error }.
async function revisar(estado, { motivoId, motivo }) {
  if (!ESTADOS_ASISTENCIA.includes(estado)) {
    return { error: 'Estado no válido', opciones: ESTADOS_ASISTENCIA };
  }
  let encontrado = null;
  if (motivoId !== undefined && motivoId !== null) {
    encontrado = await prisma.motivoAusencia.findUnique({ where: { id: Number(motivoId) || 0 } });
  } else if (motivo !== undefined && motivo !== null) {
    encontrado = await prisma.motivoAusencia.findUnique({ where: { descripcion: String(motivo) } });
  }
  const mandoMotivo = (motivoId ?? motivo ?? null) !== null;
  if ((mandoMotivo && !encontrado) || ((estado === 'falta' || estado === 'incidencia') && !encontrado)) {
    const opciones = await prisma.motivoAusencia.findMany({ orderBy: { id: 'asc' } });
    return {
      error: mandoMotivo ? 'Motivo no válido' : 'Falta e incidencia necesitan motivo (motivoId o motivo)',
      opciones,
    };
  }
  return { motivoId: encontrado?.id ?? null };
}

// GET /asistencias  ?desde=&hasta=  (por defecto, esta semana)
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
    .filter((p) => unaPersona || fechas.some((f) => estabaActiva(p, f)))
    .map((p) => asistenciaDePersona(p, fechas, datos));
  if (unaPersona) {
    if (resultado.length === 0) return res.status(404).json({ error: 'No encontrado' });
    return res.json({ desde, hasta, ...resultado[0] });
  }
  res.json(resultado);
});

// POST /asistencias  { usuarioId, fecha, estado, motivoId? | motivo? }
router.post('/', permitir('responsable'), async (req, res) => {
  const body = req.body ?? {};
  const { usuarioId, fecha, estado } = body;
  if (!usuarioId || !fecha || !estado) {
    return res.status(400).json({ error: 'Faltan usuarioId, fecha o estado' });
  }
  if (!esFecha(fecha)) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const revisado = await revisar(estado, body);
  if (revisado.error) {
    return res.status(400).json(revisado);
  }
  const persona = await prisma.usuario.findUnique({ where: { id: Number(usuarioId) } });
  if (!persona || !esDeMiEstancia(req, persona)) {
    return res.status(404).json({ error: 'Persona no encontrada' });
  }
  const clave = { usuarioId: persona.id, estanciaId: persona.estanciaId, fecha: aFechaDb(fecha) };
  const existente = await prisma.asistencia.findUnique({ where: { usuarioId_estanciaId_fecha: clave } });
  const datos = { estado, motivoId: revisado.motivoId, registradoPorId: req.usuario.id };
  if (existente) {
    const actualizada = await conAutor(req.usuario.id, (tx) =>
      tx.asistencia.update({ where: { id: existente.id }, data: datos, ...conMotivo }),
    );
    return res.json(actualizada);
  }
  const nueva = await conAutor(req.usuario.id, (tx) =>
    tx.asistencia.create({ data: { ...clave, ...datos }, ...conMotivo }),
  );
  res.status(201).json(nueva);
});

// PUT /asistencias/:id  { estado, motivoId? | motivo? }  (la Responsable corrige)
router.put('/:id', permitir('responsable'), async (req, res) => {
  const id = Number(req.params.id);
  const asistencia = await prisma.asistencia.findUnique({ where: { id } });
  if (!asistencia || !esDeMiEstancia(req, asistencia)) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  const body = req.body ?? {};
  const estado = body.estado ?? asistencia.estado;
  const revisado = await revisar(estado, body);
  if (revisado.error) {
    return res.status(400).json(revisado);
  }
  const actualizada = await conAutor(req.usuario.id, (tx) =>
    tx.asistencia.update({
      where: { id },
      data: { estado, motivoId: revisado.motivoId, registradoPorId: req.usuario.id },
      ...conMotivo,
    }),
  );
  res.json(actualizada);
});

module.exports = router;
