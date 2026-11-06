// /personal  ·  pantallas "Personal", "Perfil", "Alta de personal" y "Dar de baja".
// La Responsable maneja a la gente de su estancia. Dirección ve todo y además
// puede dar de alta Responsables (de otro modo nadie podría crearlas).
// Cada alta, baja o traslado queda en movimiento_usuario (el historial de la persona).
const express = require('express');
const bcrypt = require('bcryptjs');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const {
  ROLES,
  esFecha,
  hoy,
  aFechaDb,
  filtroEstancia,
  esDeMiEstancia,
  incluirDias,
  horarioVigente,
  passwordTemporal,
} = require('../utilidades');

const router = express.Router();

router.use(permitir('responsable', 'direccion')); // la empleada no ve a las demás

const incluir = { rol: true, puesto: true, estancia: true };

// La Responsable no ve a Dirección aunque esté registrada en su estancia
const sinDireccion = (req) => (req.usuario.rol === 'direccion' ? {} : { rol: { nombre: { not: 'direccion' } } });

// Busca a una persona, pero solo si es de la estancia de quien pregunta
async function buscar(req, id) {
  const persona = await prisma.usuario.findUnique({
    where: { id, ...sinDireccion(req) },
    include: {
      ...incluir,
      horarios: { include: incluirDias, orderBy: { id: 'desc' } },
      movimientos: { include: { causaBaja: true }, orderBy: { id: 'desc' } },
    },
  });
  return persona && esDeMiEstancia(req, persona) ? persona : null;
}

// La Responsable solo modifica empleadas; Dirección a cualquiera
const puedeModificar = (req, persona) => req.usuario.rol === 'direccion' || persona.rol.nombre === 'empleada';

const rolPorNombre = (nombre) => prisma.rol.findFirst({ where: { nombre } });

// Fecha del body o hoy. Regresa null si no es válida.
const leerFecha = (fecha = hoy()) => (esFecha(fecha) ? fecha : null);

// GET /personal  ?activo=false (bajas) | ?activo=todos  ?estanciaId= (dirección)
router.get('/', async (req, res) => {
  const where = { ...filtroEstancia(req), ...sinDireccion(req) };
  if (req.query.activo !== 'todos') where.estaActivo = req.query.activo !== 'false';
  const personal = await prisma.usuario.findMany({
    where,
    include: incluir,
    orderBy: { nombre: 'asc' },
  });
  res.json(personal);
});

// GET /personal/:id  ->  perfil con su horario de hoy y su historial
router.get('/:id', async (req, res) => {
  const persona = await buscar(req, Number(req.params.id));
  if (!persona) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  const { horarios, ...datos } = persona;
  res.json({ ...datos, horarioVigente: horarioVigente(horarios, hoy()) });
});

// POST /personal  { nombre, clave, correo, celular, puestoId, password?, fecha? }
//   ->  201 + persona + passwordTemporal
// Dirección además manda rol ("empleada" | "responsable" | "direccion") y estanciaId.
// Si no mandas password se genera una temporal que la persona cambia después.
router.post('/', async (req, res) => {
  const body = req.body ?? {};
  const { nombre, clave, correo, celular, puestoId, password } = body;
  const esDireccion = req.usuario.rol === 'direccion';
  const nombreRol = esDireccion ? (body.rol ?? 'empleada') : 'empleada';
  const estanciaId = esDireccion ? body.estanciaId : req.usuario.estanciaId;
  const fecha = leerFecha(body.fecha);

  if (!nombre || !clave || !correo || !celular || !puestoId) {
    return res.status(400).json({ error: 'Faltan nombre, clave, correo, celular o puestoId' });
  }
  if (!ROLES.includes(nombreRol)) {
    return res.status(400).json({ error: 'Rol no válido', opciones: ROLES });
  }
  if (!estanciaId) {
    return res.status(400).json({ error: 'Falta estanciaId' });
  }
  if (!fecha) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const [rol, puesto, estancia] = await Promise.all([
    rolPorNombre(nombreRol),
    prisma.puesto.findUnique({ where: { id: Number(puestoId) } }),
    prisma.estancia.findUnique({ where: { id: Number(estanciaId) } }),
  ]);
  if (!rol || !puesto || !estancia) {
    return res.status(400).json({ error: 'Rol, puesto o estancia no existen' });
  }

  const temporal = password || passwordTemporal();
  const nueva = await prisma.$transaction(async (tx) => {
    const persona = await tx.usuario.create({
      data: {
        nombre,
        clave,
        correo,
        celular,
        estaActivo: true,
        rolId: rol.id,
        puestoId: puesto.id,
        estanciaId: estancia.id,
        password: await bcrypt.hash(temporal, 10),
      },
      include: incluir,
    });
    await tx.movimientoUsuario.create({
      data: {
        tipo: 'alta',
        fecha: aFechaDb(fecha),
        usuarioId: persona.id,
        hechoPorId: req.usuario.id,
        estanciaDestinoId: estancia.id,
      },
    });
    return persona;
  });
  // La temporal se muestra UNA vez para que la Responsable se la dé a la persona
  res.status(201).json({ ...nueva, passwordTemporal: temporal });
});

// PUT /personal/:id  { nombre?, clave?, correo?, celular?, puestoId? }  (dirección también rol)
router.put('/:id', async (req, res) => {
  const id = Number(req.params.id);
  const persona = await buscar(req, id);
  if (!persona) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  if (!puedeModificar(req, persona)) {
    return res.status(403).json({ error: 'Solo Dirección puede modificar a otra Responsable' });
  }
  const body = req.body ?? {};
  const { nombre, clave, correo, celular, puestoId } = body;
  let rolId;
  if (req.usuario.rol === 'direccion' && body.rol !== undefined) {
    const rol = ROLES.includes(body.rol) && (await rolPorNombre(body.rol));
    if (!rol) {
      return res.status(400).json({ error: 'Rol no válido', opciones: ROLES });
    }
    rolId = rol.id;
  }
  if (puestoId !== undefined && !(await prisma.puesto.findUnique({ where: { id: Number(puestoId) } }))) {
    return res.status(400).json({ error: 'Ese puesto no existe' });
  }
  const actualizada = await prisma.usuario.update({
    where: { id },
    data: { nombre, clave, correo, celular, rolId, puestoId: puestoId && Number(puestoId) },
    include: incluir,
  });
  res.json(actualizada);
});

// POST /personal/:id/baja  { causaBajaId, fecha?, observaciones? }  ->  persona dada de baja
// No se borra: sale de la plantilla activa y su historial se conserva.
router.post('/:id/baja', async (req, res) => {
  const id = Number(req.params.id);
  const persona = await buscar(req, id);
  if (!persona) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  if (!puedeModificar(req, persona)) {
    return res.status(403).json({ error: 'Solo Dirección puede dar de baja a una Responsable' });
  }
  if (!persona.estaActivo) {
    return res.status(409).json({ error: 'Ya estaba dada de baja' });
  }
  if (id === req.usuario.id) {
    return res.status(400).json({ error: 'No puedes darte de baja a ti misma' });
  }
  const { causaBajaId, observaciones } = req.body ?? {};
  const fecha = leerFecha(req.body?.fecha);
  if (!fecha) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const causa = causaBajaId && (await prisma.causaBaja.findUnique({ where: { id: Number(causaBajaId) } }));
  if (!causa) {
    return res.status(400).json({ error: 'Falta causaBajaId o no existe (ver GET /catalogos)' });
  }
  const [actualizada] = await prisma.$transaction([
    prisma.usuario.update({ where: { id }, data: { estaActivo: false }, include: incluir }),
    prisma.movimientoUsuario.create({
      data: {
        tipo: 'baja',
        fecha: aFechaDb(fecha),
        observaciones,
        usuarioId: id,
        hechoPorId: req.usuario.id,
        causaBajaId: causa.id,
        estanciaOrigenId: persona.estanciaId,
      },
    }),
  ]);
  res.json(actualizada);
});

// POST /personal/:id/traslado  { estanciaId, fecha?, observaciones? }  ->  persona en su nueva estancia
router.post('/:id/traslado', async (req, res) => {
  const id = Number(req.params.id);
  const persona = await buscar(req, id);
  if (!persona) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  if (!puedeModificar(req, persona)) {
    return res.status(403).json({ error: 'Solo Dirección puede trasladar a una Responsable' });
  }
  if (!persona.estaActivo) {
    return res.status(409).json({ error: 'Está dada de baja' });
  }
  const { estanciaId, observaciones } = req.body ?? {};
  const fecha = leerFecha(req.body?.fecha);
  if (!fecha) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const destino = estanciaId && (await prisma.estancia.findUnique({ where: { id: Number(estanciaId) } }));
  if (!destino) {
    return res.status(400).json({ error: 'Falta estanciaId o no existe' });
  }
  if (destino.id === persona.estanciaId) {
    return res.status(400).json({ error: 'Ya está en esa estancia' });
  }
  const [actualizada] = await prisma.$transaction([
    prisma.usuario.update({ where: { id }, data: { estanciaId: destino.id }, include: incluir }),
    prisma.movimientoUsuario.create({
      data: {
        tipo: 'traslado',
        fecha: aFechaDb(fecha),
        observaciones,
        usuarioId: id,
        hechoPorId: req.usuario.id,
        estanciaOrigenId: persona.estanciaId,
        estanciaDestinoId: destino.id,
      },
    }),
  ]);
  res.json(actualizada);
});

// POST /personal/:id/password  ->  { passwordTemporal }
// "¿Olvidaste tu contraseña? Pídela a tu Responsable."
router.post('/:id/password', async (req, res) => {
  const id = Number(req.params.id);
  const persona = await buscar(req, id);
  if (!persona) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  if (!puedeModificar(req, persona)) {
    return res.status(403).json({ error: 'Solo Dirección puede restablecer la contraseña de una Responsable' });
  }
  const temporal = passwordTemporal();
  await prisma.usuario.update({
    where: { id },
    data: { password: await bcrypt.hash(temporal, 10) },
  });
  res.json({ passwordTemporal: temporal });
});

module.exports = router;
