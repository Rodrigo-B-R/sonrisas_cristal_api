// Sin DELETE: api_user no tiene permiso de borrar.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const { filtroEstancia, esDeMiEstancia } = require('../utilidades');

const router = express.Router();

const esMinimo = (n) => n === undefined || (Number.isInteger(n) && n >= 0);

// GET /salas  (?estanciaId= solo para dirección)  ->  salas de la estancia
router.get('/', async (req, res) => {
  const salas = await prisma.sala.findMany({
    where: filtroEstancia(req),
    orderBy: { id: 'asc' },
  });
  res.json(salas);
});

// GET /salas/:id
router.get('/:id', async (req, res) => {
  const sala = await prisma.sala.findUnique({ where: { id: Number(req.params.id) } });
  if (!sala || !esDeMiEstancia(req, sala)) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  res.json(sala);
});

router.use(permitir('responsable'));

// POST /salas  { nombre, minimoPersonal }  ->  201
router.post('/', async (req, res) => {
  const { nombre, minimoPersonal } = req.body ?? {};
  if (!nombre || minimoPersonal === undefined) {
    return res.status(400).json({ error: 'Faltan nombre o minimoPersonal' });
  }
  if (!esMinimo(minimoPersonal)) {
    return res.status(400).json({ error: 'minimoPersonal es un entero de 0 en adelante' });
  }
  const nueva = await prisma.sala.create({
    data: { nombre, minimoPersonal, estanciaId: req.usuario.estanciaId },
  });
  res.status(201).json(nueva);
});

// PUT /salas/:id  { nombre?, minimoPersonal? }
router.put('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const sala = await prisma.sala.findUnique({ where: { id } });
  if (!sala || !esDeMiEstancia(req, sala)) {
    return res.status(404).json({ error: 'No encontrada' });
  }
  const { nombre, minimoPersonal } = req.body ?? {};
  if (!esMinimo(minimoPersonal)) {
    return res.status(400).json({ error: 'minimoPersonal es un entero de 0 en adelante' });
  }
  const actualizada = await prisma.sala.update({ where: { id }, data: { nombre, minimoPersonal } });
  res.json(actualizada);
});

module.exports = router;
