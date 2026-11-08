const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { leerPeriodo, aFechaDb, hoy } = require('../utilidades');

const router = express.Router();

const TIPOS = ['alta', 'baja', 'traslado'];
const nombre = { select: { id: true, nombre: true } };

// GET /movimientos  ?desde=&hasta= (por defecto, este mes)  ?tipo=alta|baja|traslado  ?estanciaId= (dirección)
router.get('/', permitir('responsable', 'direccion'), async (req, res) => {
  const periodo = leerPeriodo({ desde: `${hoy().slice(0, 8)}01`, ...req.query }, 400);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  if (req.query.tipo && !TIPOS.includes(req.query.tipo)) {
    return res.status(400).json({ error: 'Tipo no válido', opciones: TIPOS });
  }
  const where = {
    fecha: { gte: aFechaDb(periodo.desde), lte: aFechaDb(periodo.hasta) },
    tipo: req.query.tipo,
  };
  const estanciaId = req.usuario.rol === 'direccion' ? Number(req.query.estanciaId) || null : req.usuario.estanciaId;
  if (estanciaId) {
    where.OR = [{ estanciaOrigenId: estanciaId }, { estanciaDestinoId: estanciaId }];
  }
  const movimientos = await prisma.movimientoUsuario.findMany({
    where,
    include: {
      usuario: nombre,
      hechoPor: nombre,
      causaBaja: true,
      estanciaOrigen: nombre,
      estanciaDestino: nombre,
    },
    orderBy: [{ fecha: 'desc' }, { id: 'desc' }],
  });
  res.json(movimientos);
});

module.exports = router;
