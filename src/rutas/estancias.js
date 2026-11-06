// /estancias  ·  cualquiera con sesión puede verlas; solo Dirección las crea o cambia.
// Cada estancia tiene una ubicación: el punto y el radio (precision, en metros)
// donde la app considera que la persona "está en la estancia".
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');

const router = express.Router();

const incluir = { ubicacion: true, salas: { orderBy: { id: 'asc' } } };

// Revisa latitud, longitud y precision (los que vengan). Regresa el error o null.
function revisarUbicacion({ latitud, longitud, precision }) {
  if (latitud !== undefined && !(typeof latitud === 'number' && latitud >= -90 && latitud <= 90)) {
    return 'latitud es un número entre -90 y 90';
  }
  if (longitud !== undefined && !(typeof longitud === 'number' && longitud >= -180 && longitud <= 180)) {
    return 'longitud es un número entre -180 y 180';
  }
  if (precision !== undefined && !(Number.isInteger(precision) && precision >= 0)) {
    return 'precision es un entero de metros (0 o más)';
  }
  return null;
}

// GET /estancias  ->  todas, con su ubicación y salas
router.get('/', async (req, res) => {
  const estancias = await prisma.estancia.findMany({ orderBy: { id: 'asc' }, include: incluir });
  res.json(estancias);
});

// GET /estancias/:id
router.get('/:id', async (req, res) => {
  const estancia = await prisma.estancia.findUnique({
    where: { id: Number(req.params.id) },
    include: incluir,
  });
  if (!estancia) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  res.json(estancia);
});

// POST /estancias  { nombre, latitud, longitud, precision }  ->  201  (solo dirección)
router.post('/', permitir('direccion'), async (req, res) => {
  const { nombre, latitud, longitud, precision = 150 } = req.body ?? {};
  if (!nombre || latitud === undefined || longitud === undefined) {
    return res.status(400).json({ error: 'Faltan nombre, latitud o longitud' });
  }
  const error = revisarUbicacion({ latitud, longitud, precision });
  if (error) {
    return res.status(400).json({ error });
  }
  const nueva = await prisma.estancia.create({
    data: {
      nombre,
      ubicacion: { create: { nombre: `Estancia ${nombre}`, latitud, longitud, precision } },
    },
    include: incluir,
  });
  res.status(201).json(nueva);
});

// PUT /estancias/:id  { nombre?, latitud?, longitud?, precision? }  (solo dirección)
router.put('/:id', permitir('direccion'), async (req, res) => {
  const id = Number(req.params.id);
  const existe = await prisma.estancia.findUnique({ where: { id } });
  if (!existe) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  const { nombre, latitud, longitud, precision } = req.body ?? {};
  const error = revisarUbicacion({ latitud, longitud, precision });
  if (error) {
    return res.status(400).json({ error });
  }
  const actualizada = await prisma.estancia.update({
    where: { id },
    data: { nombre, ubicacion: { update: { latitud, longitud, precision } } },
    include: incluir,
  });
  res.json(actualizada);
});

module.exports = router;
