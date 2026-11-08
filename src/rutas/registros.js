// /registros  ·  pestaña "Checar" (empleada) y "Entrada de turno completo" (responsable).
// Tabla registro_entradas: cada fila es una entrada; la salida se llena en la misma fila.
// Al registrar la entrada también se guarda la asistencia del día (presente o retardo).
const crypto = require('crypto');
const express = require('express');
const prisma = require('../prisma');
const { permitir } = require('../middleware/auth');
const {
  fechaLocal,
  horaLocal,
  hoy,
  aFechaDb,
  deHoraDb,
  minutos,
  inicioDelDia,
  finDelDia,
  leerPeriodo,
  leerFechaHora,
  filtroEstancia,
  esDeMiEstancia,
  turnosDelDia,
  distanciaMetros,
  conAutor,
} = require('../utilidades');

const router = express.Router();

const tolerancia = () => Number(process.env.TOLERANCIA_MINUTOS ?? 5);
const esUuid = (texto) => typeof texto === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(texto);
// La base guarda la hora sin milisegundos: se compara por segundos
const segundos = (fecha) => Math.round(fecha.getTime() / 1000);
const incluir = { sala: true, turno: true, usuario: { select: { id: true, nombre: true } } };

// La entrada que sigue abierta (sin salida), si hay
const registroAbierto = (usuarioId) =>
  prisma.registroEntrada.findFirst({
    where: { usuarioId, fechaHoraSalida: null },
    orderBy: { fechaHoraEntrada: 'desc' },
    include: incluir,
  });

// ¿A qué sala y turno corresponde esta entrada?
// Del horario del día; si ese día tiene dos turnos, el más cercano a la hora de llegada.
// Si no tiene horario, se pueden mandar salaId y turnoId en el body.
async function salaYTurno(persona, fechaHora, body) {
  if (body.salaId && body.turnoId) {
    const [sala, turno] = await Promise.all([
      prisma.sala.findUnique({ where: { id: Number(body.salaId) } }),
      prisma.turno.findUnique({ where: { id: Number(body.turnoId) } }),
    ]);
    if (!sala || sala.estanciaId !== persona.estanciaId || !turno) return null;
    return { sala, turno };
  }
  const dias = await turnosDelDia(persona.id, fechaLocal(fechaHora));
  if (dias.length === 0) return null;
  const llegada = minutos(horaLocal(fechaHora));
  const [mejor] = dias.sort(
    (a, b) => Math.abs(minutos(deHoraDb(a.turno.horaEntrada)) - llegada) - Math.abs(minutos(deHoraDb(b.turno.horaEntrada)) - llegada),
  );
  return { sala: mejor.sala, turno: mejor.turno };
}

// ¿Está dentro del círculo de la estancia? Si la app manda latitud/longitud se calcula aquí;
// si no, se usa dentroDeZona del body (true por defecto).
function revisarZona(ubicacion, body) {
  const { latitud, longitud, dentroDeZona } = body;
  if (typeof latitud === 'number' && typeof longitud === 'number') {
    return distanciaMetros(latitud, longitud, ubicacion.latitud, ubicacion.longitud) <= ubicacion.precision;
  }
  return dentroDeZona ?? true;
}

// Guarda la asistencia del día al llegar. Si ya había una (por ejemplo, una incidencia), no la toca.
async function marcarAsistencia(tx, persona, fechaHora, turno, registradoPorId) {
  const fecha = aFechaDb(fechaLocal(fechaHora));
  const existente = await tx.asistencia.findUnique({
    where: { usuarioId_estanciaId_fecha: { usuarioId: persona.id, estanciaId: persona.estanciaId, fecha } },
  });
  if (existente) return existente;
  const retraso = minutos(horaLocal(fechaHora)) - minutos(deHoraDb(turno.horaEntrada));
  return tx.asistencia.create({
    data: {
      fecha,
      estado: retraso > tolerancia() ? 'retardo' : 'presente',
      usuarioId: persona.id,
      registradoPorId,
      estanciaId: persona.estanciaId,
    },
  });
}

// Crea la entrada + asistencia. Regresa { registro, asistencia } o { error, status }.
async function registrarEntrada({ persona, fechaHora, body, registradoPorId, origen }) {
  const uuid = body.uuid ?? crypto.randomUUID();
  if (!esUuid(uuid)) {
    return { status: 400, error: 'uuid no válido' };
  }
  // Si el celular reenvía la misma checada (se fue el internet), regresa la que ya estaba
  const repetido = await prisma.registroEntrada.findUnique({ where: { uuid }, include: incluir });
  if (repetido) {
    if (repetido.usuarioId !== persona.id) return { status: 409, error: 'Ese uuid ya se usó' };
    return { status: 200, registro: repetido, repetido: true };
  }
  if (await registroAbierto(persona.id)) {
    return { status: 409, error: 'Ya hay una entrada abierta: registra la salida primero' };
  }
  const destino = await salaYTurno(persona, fechaHora, body);
  if (!destino) {
    return { status: 400, error: 'No tiene horario ese día: manda salaId y turnoId de su estancia' };
  }
  const { ubicacion } = await prisma.estancia.findUnique({
    where: { id: persona.estanciaId },
    include: { ubicacion: true },
  });
  return conAutor(registradoPorId, async (tx) => {
    const registro = await tx.registroEntrada.create({
      data: {
        uuid,
        fechaHoraEntrada: fechaHora,
        origenRegistro: origen,
        dentroDeZona: revisarZona(ubicacion, body),
        usuarioId: persona.id,
        registradoPorId,
        ubicacionId: ubicacion.id,
        salaId: destino.sala.id,
        turnoId: destino.turno.id,
      },
      include: incluir,
    });
    const asistencia = await marcarAsistencia(tx, persona, fechaHora, destino.turno, registradoPorId);
    return { status: 201, registro, asistencia };
  });
}

// GET /registros/estado  ->  { dentro, registroAbierto, turnosHoy, ubicacion }   (pantalla Checar)
router.get('/estado', async (req, res) => {
  const persona = await prisma.usuario.findUnique({
    where: { id: req.usuario.id },
    include: { estancia: { include: { ubicacion: true } } },
  });
  const abierto = await registroAbierto(req.usuario.id);
  res.json({
    dentro: !!abierto,
    registroAbierto: abierto,
    turnosHoy: await turnosDelDia(req.usuario.id, hoy()),
    ubicacion: persona.estancia.ubicacion, // para que la app dibuje el círculo
  });
});

// GET /registros  ?desde=&hasta=&usuarioId=&dentroDeZona=false
//   empleada: solo los suyos. Responsable: su estancia. Dirección: todos o ?estanciaId=
router.get('/', async (req, res) => {
  const periodo = leerPeriodo(req.query);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  const where = {
    fechaHoraEntrada: { gte: inicioDelDia(periodo.desde), lte: finDelDia(periodo.hasta) },
  };
  if (req.usuario.rol === 'empleada') {
    where.usuarioId = req.usuario.id;
  } else {
    where.usuario = filtroEstancia(req);
    if (req.query.usuarioId) where.usuarioId = Number(req.query.usuarioId);
  }
  if (req.query.dentroDeZona) where.dentroDeZona = req.query.dentroDeZona === 'true';
  const registros = await prisma.registroEntrada.findMany({
    where,
    orderBy: { fechaHoraEntrada: 'desc' },
    include: incluir,
  });
  res.json(registros);
});

// POST /registros/entrada  { uuid?, fechaHora?, latitud?, longitud?, dentroDeZona?, salaId?, turnoId? }
//   ->  201 { registro, asistencia }
// La persona checa por sí misma. Fuera de zona se guarda igual (no se bloquea)
// para que la Responsable lo revise.
router.post('/entrada', permitir('empleada', 'responsable'), async (req, res) => {
  const body = req.body ?? {};
  const fechaHora = leerFechaHora(body.fechaHora);
  if (!fechaHora) {
    return res.status(400).json({ error: 'fechaHora no válida (ISO 8601 y no del futuro)' });
  }
  if (body.dentroDeZona !== undefined && typeof body.dentroDeZona !== 'boolean') {
    return res.status(400).json({ error: 'dentroDeZona es true o false' });
  }
  const persona = await prisma.usuario.findUnique({ where: { id: req.usuario.id } });
  const { status, error, ...resultado } = await registrarEntrada({
    persona,
    fechaHora,
    body,
    registradoPorId: req.usuario.id,
    origen: 'app',
  });
  if (error) {
    return res.status(status).json({ error });
  }
  res.status(status).json(resultado);
});

// POST /registros/salida  { fechaHora? }  ->  el registro con su salida
router.post('/salida', permitir('empleada', 'responsable'), async (req, res) => {
  const fechaHora = leerFechaHora(req.body?.fechaHora);
  if (!fechaHora) {
    return res.status(400).json({ error: 'fechaHora no válida (ISO 8601 y no del futuro)' });
  }
  const abierto = await registroAbierto(req.usuario.id);
  if (!abierto) {
    return res.status(409).json({ error: 'No hay una entrada abierta' });
  }
  if (segundos(fechaHora) < segundos(abierto.fechaHoraEntrada)) {
    return res.status(400).json({ error: 'La salida debe ser después de la entrada' });
  }
  // Salida en el mismo segundo que la entrada: se guarda un segundo después (la base pide salida > entrada)
  const salida = segundos(fechaHora) === segundos(abierto.fechaHoraEntrada)
    ? new Date((segundos(abierto.fechaHoraEntrada) + 1) * 1000)
    : fechaHora;
  const registro = await conAutor(req.usuario.id, (tx) =>
    tx.registroEntrada.update({
      where: { id: abierto.id },
      data: { fechaHoraSalida: salida },
      include: incluir,
    }),
  );
  res.json(registro);
});

// POST /registros/turno  { usuarioIds: [..], fechaHora?, salaId?, turnoId? }  ->  201 { registradas, omitidas }
// La Responsable registra la entrada de varias personas a la vez.
router.post('/turno', permitir('responsable'), async (req, res) => {
  const body = req.body ?? {};
  const { usuarioIds } = body;
  if (!Array.isArray(usuarioIds) || usuarioIds.length === 0) {
    return res.status(400).json({ error: 'Falta usuarioIds (arreglo con al menos un id)' });
  }
  const fechaHora = leerFechaHora(body.fechaHora);
  if (!fechaHora) {
    return res.status(400).json({ error: 'fechaHora no válida (ISO 8601 y no del futuro)' });
  }
  const personas = await prisma.usuario.findMany({
    where: { id: { in: usuarioIds.map(Number) }, estaActivo: true, estanciaId: req.usuario.estanciaId },
  });
  const registradas = [];
  const omitidas = [];
  for (const id of usuarioIds.map(Number)) {
    const persona = personas.find((p) => p.id === id);
    if (!persona) {
      omitidas.push({ usuarioId: id, motivo: 'No es personal activo de tu estancia' });
      continue;
    }
    const resultado = await registrarEntrada({
      persona,
      fechaHora,
      body: { salaId: body.salaId, turnoId: body.turnoId, dentroDeZona: true },
      registradoPorId: req.usuario.id,
      origen: 'responsable',
    });
    if (resultado.error) omitidas.push({ usuarioId: id, motivo: resultado.error });
    else registradas.push(resultado.registro);
  }
  res.status(201).json({ registradas, omitidas });
});

// PUT /registros/:id  { fechaHoraEntrada?, fechaHoraSalida?, motivo? }  (la Responsable corrige un registro)
// Queda en correccion_registro como corrección aprobada por ella, con las horas de antes.
// Si la corrección la pide la empleada, va por POST /correcciones y la Responsable la aprueba.
router.put('/:id', permitir('responsable'), async (req, res) => {
  const id = Number(req.params.id);
  const registro = await prisma.registroEntrada.findUnique({ where: { id }, include: { usuario: true } });
  if (!registro || !esDeMiEstancia(req, registro.usuario)) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  const propuesta = leerCorreccion(registro, req.body ?? {});
  if (propuesta.error) {
    return res.status(400).json({ error: propuesta.error });
  }
  const actualizado = await conAutor(req.usuario.id, async (tx) => {
    await tx.correccionRegistro.create({
      data: {
        ...propuesta.datos,
        motivo: req.body?.motivo || 'Corregido por la Responsable',
        solicitadaPorId: req.usuario.id,
        estado: 'aprobada',
        resueltaPorId: req.usuario.id,
        resueltaEn: new Date(),
      },
    });
    return tx.registroEntrada.update({
      where: { id },
      data: { fechaHoraEntrada: propuesta.datos.entradaPropuesta, fechaHoraSalida: propuesta.datos.salidaPropuesta },
      include: incluir,
    });
  });
  res.json(actualizado);
});

// Lee { fechaHoraEntrada?, fechaHoraSalida? } y arma la corrección: horas de antes y propuestas.
// Lo que no venga se queda igual; "fechaHoraSalida": null quita la salida.
// Regresa { datos } o { error }. También lo usa /correcciones.
function leerCorreccion(registro, body) {
  const entrada = body.fechaHoraEntrada === undefined ? registro.fechaHoraEntrada : leerFechaHora(body.fechaHoraEntrada);
  let salida = registro.fechaHoraSalida;
  if (body.fechaHoraSalida === null) salida = null;
  else if (body.fechaHoraSalida !== undefined) salida = leerFechaHora(body.fechaHoraSalida);
  if (!entrada || (body.fechaHoraSalida !== undefined && body.fechaHoraSalida !== null && !salida)) {
    return { error: 'Fechas no válidas (ISO 8601 y no del futuro)' };
  }
  if (body.fechaHoraEntrada === undefined && body.fechaHoraSalida === undefined) {
    return { error: 'Manda fechaHoraEntrada o fechaHoraSalida' };
  }
  if (salida && segundos(salida) <= segundos(entrada)) {
    return { error: 'La salida debe ser después de la entrada' };
  }
  return {
    datos: {
      registroId: registro.id,
      entradaAnterior: registro.fechaHoraEntrada,
      salidaAnterior: registro.fechaHoraSalida,
      entradaPropuesta: entrada,
      salidaPropuesta: salida,
    },
  };
}

module.exports = router;
module.exports.leerCorreccion = leerCorreccion;
module.exports.incluirRegistro = incluir;
