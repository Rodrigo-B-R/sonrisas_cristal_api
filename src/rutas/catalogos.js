// /catalogos  ·  las listas para los menús de la app (roles, puestos, turnos, causas de baja, motivos de ausencia).
// Cualquiera con sesión las lee. Dirección puede agregar puestos, causas de baja y motivos.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { esHora, aHoraDb } = require('../utilidades');

const router = express.Router();

const porId = { orderBy: { id: 'asc' } };

// GET /catalogos  ->  { roles, puestos, turnos, causasBaja, motivosAusencia }
router.get('/', async (req, res) => {
  const [roles, puestos, turnos, causasBaja, motivosAusencia] = await Promise.all([
    prisma.rol.findMany(porId),
    prisma.puesto.findMany(porId),
    prisma.turno.findMany(porId),
    prisma.causaBaja.findMany(porId),
    prisma.motivoAusencia.findMany(porId),
  ]);
  res.json({ roles, puestos, turnos, causasBaja, motivosAusencia });
});

// POST /catalogos/motivos-ausencia  { descripcion }  ->  201 · 409 si ya existe
router.post('/motivos-ausencia', permitir('direccion'), async (req, res) => {
  const { descripcion } = req.body ?? {};
  if (!descripcion) {
    return res.status(400).json({ error: 'Falta la descripcion' });
  }
  res.status(201).json(await prisma.motivoAusencia.create({ data: { descripcion } }));
});

// POST /catalogos/puestos  { nombre }  ->  201
router.post('/puestos', permitir('direccion'), async (req, res) => {
  const { nombre } = req.body ?? {};
  if (!nombre) {
    return res.status(400).json({ error: 'Falta el nombre' });
  }
  res.status(201).json(await prisma.puesto.create({ data: { nombre } }));
});

// POST /catalogos/causas-baja  { nombre }  ->  201
router.post('/causas-baja', permitir('direccion'), async (req, res) => {
  const { nombre } = req.body ?? {};
  if (!nombre) {
    return res.status(400).json({ error: 'Falta el nombre' });
  }
  res.status(201).json(await prisma.causaBaja.create({ data: { nombre } }));
});

// PUT /catalogos/turnos/:id  { nombre?, horaEntrada?, horaSalida? }  ("07:00")
router.put('/turnos/:id', permitir('direccion'), async (req, res) => {
  const id = Number(req.params.id);
  const { nombre, horaEntrada, horaSalida } = req.body ?? {};
  if ((horaEntrada !== undefined && !esHora(horaEntrada)) || (horaSalida !== undefined && !esHora(horaSalida))) {
    return res.status(400).json({ error: 'Las horas van como HH:MM' });
  }
  const turno = await prisma.turno.update({
    where: { id },
    data: {
      nombre,
      horaEntrada: horaEntrada && aHoraDb(horaEntrada),
      horaSalida: horaSalida && aHoraDb(horaSalida),
    },
  });
  res.json(turno);
});

module.exports = router;
