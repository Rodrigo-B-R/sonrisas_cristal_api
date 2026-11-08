// /auditoria  ·  quién cambió qué y cuándo en registros, asistencias y correcciones.
// La tabla la llenan solos los triggers de la base; la API solo la lee.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { leerPeriodo, inicioDelDia, finDelDia } = require('../utilidades');

const router = express.Router();

const TABLAS = ['registro_entradas', 'asistencia', 'correccion_registro'];

// GET /auditoria  ?desde=&hasta=&tabla=&registroId=&usuarioId=   (dirección)
//   ->  [ { id, accion, tabla, registroId, datosAnteriores, datosNuevos, creadoEn, usuario } ]
router.get('/', permitir('direccion'), async (req, res) => {
  const periodo = leerPeriodo(req.query);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  const where = { creadoEn: { gte: inicioDelDia(periodo.desde), lte: finDelDia(periodo.hasta) } };
  if (req.query.tabla) {
    if (!TABLAS.includes(req.query.tabla)) {
      return res.status(400).json({ error: 'Tabla no válida', opciones: TABLAS });
    }
    where.tabla = req.query.tabla;
  }
  if (req.query.registroId) where.registroId = Number(req.query.registroId);
  if (req.query.usuarioId) where.usuarioId = Number(req.query.usuarioId);
  const cambios = await prisma.auditoria.findMany({
    where,
    orderBy: { id: 'desc' },
    take: 500,
    include: { usuario: { select: { id: true, nombre: true } } },
  });
  res.json(cambios);
});

module.exports = router;
