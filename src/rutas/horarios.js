// /horarios  ·  pantalla "Horarios" (Responsable) y "Mi horario" (empleada).
// Un horario es la semana de una persona, válida desde una fecha.
// Cambiarlo NO borra el anterior: se cierra (vigenteHasta = día anterior) y se crea uno nuevo.
// Así se sabe qué horario tenía la persona en cualquier fecha pasada.
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const {
  DIAS,
  SIN_FIN,
  hoy,
  esFecha,
  aFechaDb,
  sumarDias,
  filtroEstancia,
  incluirDias,
  horarioVigente,
} = require('../utilidades');

const router = express.Router();

// Trae los horarios que cubren esa fecha y deja solo el vigente
async function horarioDe(usuarioId, fecha) {
  const horarios = await prisma.horario.findMany({
    where: { usuarioId, vigenteDesde: { lte: aFechaDb(fecha) }, vigenteHasta: { gte: aFechaDb(fecha) } },
    include: incluirDias,
  });
  return horarioVigente(horarios, fecha);
}

// GET /horarios  ?fecha= (hoy por defecto)
//   empleada                ->  su horario vigente (o null)
//   ?usuarioId=             ->  el de esa persona
//   responsable/dirección   ->  [ { persona, horario } ] del personal activo de la estancia
router.get('/', async (req, res) => {
  const fecha = req.query.fecha ?? hoy();
  if (!esFecha(fecha)) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  if (req.usuario.rol === 'empleada') {
    return res.json(await horarioDe(req.usuario.id, fecha));
  }
  const where = { ...filtroEstancia(req), estaActivo: true, rol: { nombre: { not: 'direccion' } } };
  if (req.query.usuarioId) where.id = Number(req.query.usuarioId);
  const personas = await prisma.usuario.findMany({
    where,
    select: { id: true, nombre: true, puesto: true },
    orderBy: { nombre: 'asc' },
  });
  const lista = [];
  for (const persona of personas) {
    lista.push({ persona, horario: await horarioDe(persona.id, fecha) });
  }
  if (req.query.usuarioId) {
    if (lista.length === 0) return res.status(404).json({ error: 'No encontrado' });
    return res.json(lista[0]);
  }
  res.json(lista);
});

// PUT /horarios/:usuarioId  { desde?, dias: [{ dia, turnoId, salaId }] }  ->  201 horario nuevo
//   dia: "lunes" ... "domingo" (sin acentos). Día que no venga = descanso.
//   desde: a partir de cuándo vale (hoy por defecto).
router.put('/:usuarioId', permitir('responsable'), async (req, res) => {
  const usuarioId = Number(req.params.usuarioId);
  const persona = await prisma.usuario.findUnique({ where: { id: usuarioId } });
  if (!persona || persona.estanciaId !== req.usuario.estanciaId) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  const { dias, desde = hoy() } = req.body ?? {};
  if (!esFecha(desde)) {
    return res.status(400).json({ error: 'desde va como AAAA-MM-DD' });
  }
  if (!Array.isArray(dias)) {
    return res.status(400).json({ error: 'Falta dias: [{ dia, turnoId, salaId }]' });
  }
  const turnos = await prisma.turno.findMany();
  const salas = await prisma.sala.findMany({ where: { estanciaId: req.usuario.estanciaId } });
  for (const d of dias) {
    if (!DIAS.includes(d?.dia)) {
      return res.status(400).json({ error: 'dia no válido', opciones: DIAS });
    }
    if (!turnos.some((t) => t.id === d.turnoId)) {
      return res.status(400).json({ error: `turnoId ${d.turnoId} no existe (ver GET /catalogos)` });
    }
    if (!salas.some((s) => s.id === d.salaId)) {
      return res.status(400).json({ error: `salaId ${d.salaId} no es de tu estancia` });
    }
  }
  const repetido = dias.find(
    (d, i) => dias.findIndex((o) => o.dia === d.dia && o.turnoId === d.turnoId && o.salaId === d.salaId) !== i,
  );
  if (repetido) {
    return res.status(400).json({ error: `El ${repetido.dia} viene repetido` });
  }

  const nuevo = await prisma.$transaction(async (tx) => {
    // Cierra los horarios que empezaron antes y seguían vigentes en "desde"
    await tx.horario.updateMany({
      where: { usuarioId, vigenteDesde: { lt: aFechaDb(desde) }, vigenteHasta: { gte: aFechaDb(desde) } },
      data: { vigenteHasta: aFechaDb(sumarDias(desde, -1)) },
    });
    // Los que empezaban ese mismo día o después quedan tapados por el nuevo (id mayor)
    return tx.horario.create({
      data: {
        usuarioId,
        vigenteDesde: aFechaDb(desde),
        vigenteHasta: aFechaDb(SIN_FIN),
        dias: { create: dias.map((d) => ({ diaDeSemana: d.dia, turnoId: d.turnoId, salaId: d.salaId })) },
      },
      include: incluirDias,
    });
  });
  res.status(201).json(nuevo);
});

module.exports = router;
