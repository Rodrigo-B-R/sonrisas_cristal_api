const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { TIPOS_AVISO, hoy, aFechaDb } = require('../utilidades');

const router = express.Router();

const DESTINOS = ['todos', 'turno', 'sala', 'personas'];
const conAutor = { autor: { select: { id: true, nombre: true, estanciaId: true } } };

// Responsable: los de su estancia y los generales (estanciaId null). Dirección: todos o ?estanciaId=
function filtroAvisos(req) {
  if (req.usuario.rol === 'direccion') {
    return req.query.estanciaId ? { estanciaId: Number(req.query.estanciaId) } : {};
  }
  return { OR: [{ estanciaId: req.usuario.estanciaId }, { estanciaId: null }] };
}

// De un aviso general, la Responsable solo ve las lecturas de su estancia
const lecturasVisibles = (req) =>
  req.usuario.rol === 'direccion' ? true : { where: { usuario: { estanciaId: req.usuario.estanciaId } } };

// Conteo "9 de 14 confirmaron" y, si quien pregunta también lo recibió, su propia lectura
function conConteo({ lecturas, ...aviso }, req) {
  const mia = req && lecturas.find((l) => l.usuarioId === req.usuario.id);
  return {
    ...aviso,
    destinatarios: lecturas.length,
    confirmaron: lecturas.filter((l) => l.leido).length,
    ...(mia && { leido: mia.leido, leidoEn: mia.leidoEn }),
  };
}

function puedeVer(req, aviso) {
  return req.usuario.rol === 'direccion' || aviso.estanciaId === null || aviso.estanciaId === req.usuario.estanciaId;
}

const conHorarioHoy = (dias) => ({
  horarios: { some: { vigenteDesde: { lte: aFechaDb(hoy()) }, vigenteHasta: { gte: aFechaDb(hoy()) }, dias: { some: dias } } },
});

// GET /avisos
router.get('/', async (req, res) => {
  if (req.usuario.rol === 'empleada') {
    const lecturas = await prisma.avisoUsuario.findMany({
      where: { usuarioId: req.usuario.id },
      include: { aviso: { include: conAutor } },
      orderBy: { avisoId: 'desc' },
    });
    return res.json(lecturas.map(({ aviso, leido, leidoEn }) => ({ ...aviso, leido, leidoEn })));
  }
  const avisos = await prisma.aviso.findMany({
    where: filtroAvisos(req),
    include: { ...conAutor, lecturas: lecturasVisibles(req) },
    orderBy: { id: 'desc' },
  });
  res.json(avisos.map((a) => conConteo(a, req)));
});

// GET /avisos/:id
router.get('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const aviso = await prisma.aviso.findUnique({
    where: { id },
    include: {
      ...conAutor,
      lecturas: {
        include: { usuario: { select: { id: true, nombre: true, estanciaId: true } } },
        orderBy: { leidoEn: 'asc' },
      },
    },
  });
  if (!aviso) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  const { lecturas, ...datos } = aviso;
  if (req.usuario.rol === 'empleada') {
    const mia = lecturas.find((l) => l.usuarioId === req.usuario.id);
    if (!mia) {
      return res.status(404).json({ error: 'No encontrado' });
    }
    return res.json({ ...datos, leido: mia.leido, leidoEn: mia.leidoEn });
  }
  if (!puedeVer(req, aviso)) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  const visibles =
    req.usuario.rol === 'direccion' ? lecturas : lecturas.filter((l) => l.usuario.estanciaId === req.usuario.estanciaId);
  const persona = ({ id, nombre }) => ({ id, nombre });
  res.json({
    ...datos,
    destinatarios: visibles.length,
    confirmados: visibles.filter((l) => l.leido).map((l) => ({ ...persona(l.usuario), leidoEn: l.leidoEn })),
    pendientes: visibles.filter((l) => !l.leido).map((l) => persona(l.usuario)),
  });
});

// POST /avisos  { asunto, mensaje, tipoAviso, destino: todos|turno|sala|personas, turnoId?, salaId?, usuarioIds?, requiereConfirmacion? }
//   Responsable: a su estancia. Dirección: a una estancia con estanciaId, o general (sin estanciaId) a todas.
router.post('/', permitir('responsable', 'direccion'), async (req, res) => {
  const { asunto, mensaje, tipoAviso, destino = 'todos', turnoId, salaId, usuarioIds, requiereConfirmacion = false } =
    req.body ?? {};
  if (!asunto || !mensaje || !tipoAviso) {
    return res.status(400).json({ error: 'Faltan asunto, mensaje o tipoAviso' });
  }
  if (asunto.length > 255 || mensaje.length > 255) {
    return res.status(400).json({ error: 'asunto y mensaje son de máximo 255 caracteres' });
  }
  if (!TIPOS_AVISO.includes(tipoAviso)) {
    return res.status(400).json({ error: 'Tipo no válido', opciones: TIPOS_AVISO });
  }
  if (!DESTINOS.includes(destino)) {
    return res.status(400).json({ error: 'Destino no válido', opciones: DESTINOS });
  }
  if (typeof requiereConfirmacion !== 'boolean') {
    return res.status(400).json({ error: 'requiereConfirmacion es true o false' });
  }

  let estanciaId = req.usuario.estanciaId;
  if (req.usuario.rol === 'direccion') {
    estanciaId = req.body.estanciaId == null ? null : Number(req.body.estanciaId);
    if (estanciaId !== null && !(await prisma.estancia.findUnique({ where: { id: estanciaId || 0 } }))) {
      return res.status(400).json({ error: 'Estancia no encontrada' });
    }
  }

  const where = {
    estaActivo: true,
    id: { not: req.usuario.id },
    rol: { nombre: { not: 'direccion' } },
    ...(estanciaId !== null && { estanciaId }),
  };
  if (destino === 'turno') {
    if (!turnoId) return res.status(400).json({ error: 'Falta turnoId' });
    Object.assign(where, conHorarioHoy({ turnoId: Number(turnoId) }));
  }
  if (destino === 'sala') {
    if (!salaId) return res.status(400).json({ error: 'Falta salaId' });
    Object.assign(where, conHorarioHoy({ salaId: Number(salaId) }));
  }
  if (destino === 'personas') {
    if (!Array.isArray(usuarioIds) || usuarioIds.length === 0) {
      return res.status(400).json({ error: 'Falta usuarioIds (arreglo con al menos un id)' });
    }
    where.id = { in: usuarioIds.map(Number), not: req.usuario.id };
  }
  const destinatarios = await prisma.usuario.findMany({ where, select: { id: true } });
  if (destinatarios.length === 0) {
    return res.status(400).json({ error: 'Nadie recibiría este aviso' });
  }

  const aviso = await prisma.aviso.create({
    data: {
      asunto,
      mensaje,
      tipoAviso,
      requiereConfirmacion,
      autorId: req.usuario.id,
      estanciaId, // null = general
      lecturas: { create: destinatarios.map((d) => ({ usuarioId: d.id })) },
    },
    include: { ...conAutor, lecturas: true },
  });
  res.status(201).json(conConteo(aviso, req));
});

// POST /avisos/:id/lectura
router.post('/:id/lectura', async (req, res) => {
  const avisoId = Number(req.params.id);
  const clave = { avisoId_usuarioId: { avisoId, usuarioId: req.usuario.id } };
  const lectura = await prisma.avisoUsuario.findUnique({ where: clave });
  if (!lectura) {
    return res.status(404).json({ error: 'Este aviso no es para ti' });
  }
  const actualizada = lectura.leido
    ? lectura // si ya lo había confirmado, se queda la primera hora
    : await prisma.avisoUsuario.update({ where: clave, data: { leido: true, leidoEn: new Date() } });
  res.json({ avisoId, leido: actualizada.leido, leidoEn: actualizada.leidoEn });
});

module.exports = router;
