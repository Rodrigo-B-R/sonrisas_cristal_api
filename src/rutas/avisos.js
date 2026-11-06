// /avisos  ·  La Responsable envía avisos y ve quién confirmó la lectura.
// La empleada ve los suyos y confirma que los leyó (aviso_usuario.leido / leido_en).
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { TIPOS_AVISO, hoy, aFechaDb } = require('../utilidades');

const router = express.Router();

const DESTINOS = ['todos', 'turno', 'sala', 'personas'];
const conAutor = { autor: { select: { id: true, nombre: true, estanciaId: true } } };

// Responsable: avisos que mandó alguien de su estancia. Dirección: todos o ?estanciaId=
function filtroAvisos(req) {
  if (req.usuario.rol === 'direccion') {
    return req.query.estanciaId ? { autor: { estanciaId: Number(req.query.estanciaId) } } : {};
  }
  return { autor: { estanciaId: req.usuario.estanciaId } };
}

// Cuenta confirmados para la lista de la Responsable: "9 de 14 confirmaron"
function conConteo({ lecturas, ...aviso }) {
  return {
    ...aviso,
    destinatarios: lecturas.length,
    confirmaron: lecturas.filter((l) => l.leido).length,
  };
}

// Personas con horario vigente hoy que tenga ese turno o esa sala
const conHorarioHoy = (dias) => ({
  horarios: { some: { vigenteDesde: { lte: aFechaDb(hoy()) }, vigenteHasta: { gte: aFechaDb(hoy()) }, dias: { some: dias } } },
});

// GET /avisos
//   empleada              ->  los que le llegaron, con leido y leidoEn
//   responsable/dirección ->  los de la estancia, con destinatarios y confirmaron
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
    include: { ...conAutor, lecturas: true },
    orderBy: { id: 'desc' },
  });
  res.json(avisos.map(conConteo));
});

// GET /avisos/:id
//   empleada              ->  el aviso + su leido/leidoEn
//   responsable/dirección ->  el aviso + confirmados y pendientes ("Estado de lectura")
router.get('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const aviso = await prisma.aviso.findUnique({
    where: { id },
    include: {
      ...conAutor,
      lecturas: {
        include: { usuario: { select: { id: true, nombre: true } } },
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
  if (req.usuario.rol !== 'direccion' && aviso.autor.estanciaId !== req.usuario.estanciaId) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  res.json({
    ...datos,
    destinatarios: lecturas.length,
    confirmados: lecturas.filter((l) => l.leido).map((l) => ({ ...l.usuario, leidoEn: l.leidoEn })),
    pendientes: lecturas.filter((l) => !l.leido).map((l) => l.usuario),
  });
});

// POST /avisos  ->  201
// { asunto, mensaje, tipoAviso, destino, turnoId?, salaId?, usuarioIds? }
//   destino "todos"    -> todo el personal activo de la estancia
//   destino "turno"    -> quien tenga ese turno en su horario vigente
//   destino "sala"     -> quien tenga esa sala en su horario vigente
//   destino "personas" -> los usuarioIds
router.post('/', permitir('responsable'), async (req, res) => {
  const { asunto, mensaje, tipoAviso, destino = 'todos', turnoId, salaId, usuarioIds } = req.body ?? {};
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

  const where = {
    estaActivo: true,
    estanciaId: req.usuario.estanciaId,
    id: { not: req.usuario.id },
    rol: { nombre: { not: 'direccion' } },
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
      autorId: req.usuario.id,
      lecturas: { create: destinatarios.map((d) => ({ usuarioId: d.id })) },
    },
    include: { ...conAutor, lecturas: true },
  });
  res.status(201).json(conConteo(aviso));
});

// POST /avisos/:id/lectura  ->  { avisoId, leido, leidoEn }   (la empleada confirma que lo leyó)
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
