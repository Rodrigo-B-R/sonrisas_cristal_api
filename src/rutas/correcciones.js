// /correcciones: la empleada pide corregir la hora de un registro; la Responsable aprueba o rechaza.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { ESTADOS_CORRECCION, filtroEstancia, esDeMiEstancia, conAutor } = require('../utilidades');
const { leerCorreccion, incluirRegistro } = require('./registros');

const router = express.Router();

const incluir = {
  registro: { include: incluirRegistro },
  solicitadaPor: { select: { id: true, nombre: true } },
  resueltaPor: { select: { id: true, nombre: true } },
};

// GET /correcciones  ?estado=pendiente|aprobada|rechazada
router.get('/', async (req, res) => {
  const where = {};
  if (req.query.estado) {
    if (!ESTADOS_CORRECCION.includes(req.query.estado)) {
      return res.status(400).json({ error: 'Estado no válido', opciones: ESTADOS_CORRECCION });
    }
    where.estado = req.query.estado;
  }
  if (req.usuario.rol === 'empleada') where.registro = { usuarioId: req.usuario.id };
  else where.registro = { usuario: filtroEstancia(req) };
  const correcciones = await prisma.correccionRegistro.findMany({
    where,
    orderBy: { creadaEn: 'desc' },
    include: incluir,
  });
  res.json(correcciones);
});

// POST /correcciones  { registroId, fechaHoraEntrada?, fechaHoraSalida?, motivo }
router.post('/', permitir('empleada', 'responsable'), async (req, res) => {
  const body = req.body ?? {};
  if (!body.registroId || !body.motivo) {
    return res.status(400).json({ error: 'Faltan registroId o motivo' });
  }
  const registro = await prisma.registroEntrada.findUnique({
    where: { id: Number(body.registroId) || 0 },
    include: { usuario: true },
  });
  const esSuyo =
    registro && (req.usuario.rol === 'empleada' ? registro.usuarioId === req.usuario.id : esDeMiEstancia(req, registro.usuario));
  if (!esSuyo) {
    return res.status(404).json({ error: 'Registro no encontrado' });
  }
  const pendiente = await prisma.correccionRegistro.findFirst({
    where: { registroId: registro.id, estado: 'pendiente' },
  });
  if (pendiente) {
    return res.status(409).json({ error: 'Ese registro ya tiene una corrección pendiente', correccionId: pendiente.id });
  }
  const propuesta = leerCorreccion(registro, body);
  if (propuesta.error) {
    return res.status(400).json({ error: propuesta.error });
  }
  const correccion = await conAutor(req.usuario.id, (tx) =>
    tx.correccionRegistro.create({
      data: { ...propuesta.datos, motivo: String(body.motivo), solicitadaPorId: req.usuario.id },
      include: incluir,
    }),
  );
  res.status(201).json(correccion);
});

// Al aprobar, la hora del registro cambia en la misma transacción.
async function resolver(req, res, estado) {
  const id = Number(req.params.id);
  const correccion = await prisma.correccionRegistro.findUnique({
    where: { id },
    include: { registro: { include: { usuario: true } } },
  });
  if (!correccion || !esDeMiEstancia(req, correccion.registro.usuario)) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  if (correccion.estado !== 'pendiente') {
    return res.status(409).json({ error: `Ya estaba ${correccion.estado}` });
  }
  const resuelta = await conAutor(req.usuario.id, async (tx) => {
    if (estado === 'aprobada') {
      await tx.registroEntrada.update({
        where: { id: correccion.registroId },
        data: { fechaHoraEntrada: correccion.entradaPropuesta, fechaHoraSalida: correccion.salidaPropuesta },
      });
    }
    return tx.correccionRegistro.update({
      where: { id },
      data: { estado, resueltaPorId: req.usuario.id, resueltaEn: new Date() },
      include: incluir,
    });
  });
  res.json(resuelta);
}

// POST /correcciones/:id/aprobar
router.post('/:id/aprobar', permitir('responsable'), (req, res) => resolver(req, res, 'aprobada'));

// POST /correcciones/:id/rechazar
router.post('/:id/rechazar', permitir('responsable'), (req, res) => resolver(req, res, 'rechazada'));

module.exports = router;
