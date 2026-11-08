// Cálculos para /asistencias y los reportes: junta horario, asistencia y registros de cada día.
const prisma = require('./prisma');
const {
  hoy,
  fechaLocal,
  horaLocal,
  aFechaDb,
  deFechaDb,
  deHoraDb,
  minutos,
  inicioDelDia,
  finDelDia,
  incluirDias,
  diasDelHorario,
} = require('./utilidades');

function agrupar(lista, clave) {
  const mapa = new Map();
  for (const item of lista) {
    const k = clave(item);
    if (!mapa.has(k)) mapa.set(k, []);
    mapa.get(k).push(item);
  }
  return mapa;
}

// Trae personas, horarios, asistencias y registros de un periodo en pocas consultas.
async function cargarDatos(wherePersonas, desde, hasta) {
  const personas = await prisma.usuario.findMany({
    where: {
      rol: { nombre: { not: 'direccion' } },
      OR: [
        { estaActivo: true },
        { movimientos: { some: { tipo: 'baja', fecha: { gte: aFechaDb(desde) } } } },
      ],
      ...wherePersonas,
    },
    include: {
      rol: true,
      puesto: true,
      estancia: true,
      horarios: {
        where: { vigenteDesde: { lte: aFechaDb(hasta) }, vigenteHasta: { gte: aFechaDb(desde) } },
        include: incluirDias,
      },
      movimientos: { where: { tipo: { in: ['alta', 'baja'] } }, orderBy: { fecha: 'asc' } },
    },
    orderBy: { nombre: 'asc' },
  });
  const ids = personas.map((p) => p.id);
  const [asistencias, registros] = await Promise.all([
    prisma.asistencia.findMany({
      where: { usuarioId: { in: ids }, fecha: { gte: aFechaDb(desde), lte: aFechaDb(hasta) } },
      include: { motivo: true },
    }),
    prisma.registroEntrada.findMany({
      where: { usuarioId: { in: ids }, fechaHoraEntrada: { gte: inicioDelDia(desde), lte: finDelDia(hasta) } },
      orderBy: { fechaHoraEntrada: 'asc' },
    }),
  ]);
  return {
    personas,
    asistencias: new Map(asistencias.map((a) => [`${a.usuarioId}|${deFechaDb(a.fecha)}`, a])),
    registros: agrupar(registros, (r) => `${r.usuarioId}|${fechaLocal(r.fechaHoraEntrada)}`),
  };
}

// ¿Ya trabajaba ahí ese día y todavía no se daba de baja? (según movimiento_usuario)
function estabaActiva(persona, fecha) {
  const alta = persona.movimientos.find((m) => m.tipo === 'alta');
  const baja = persona.movimientos.findLast((m) => m.tipo === 'baja');
  if (alta && deFechaDb(alta.fecha) > fecha) return false;
  if (baja && !persona.estaActivo && deFechaDb(baja.fecha) <= fecha) return false;
  return true;
}

// Un día de una persona. estado:
//   presente | retardo | falta | incidencia   (lo guardado en la tabla asistencia)
//   sin_registro (tenía turno y nadie registró nada) | pendiente (hoy, aún no llega)
//   descanso | fuera_de_horario (checó sin turno) | programado (futuro)
function calcularDia(persona, fecha, datos) {
  const turnos = diasDelHorario(persona.horarios, fecha);
  const asistencia = datos.asistencias.get(`${persona.id}|${fecha}`) ?? null;
  const registros = datos.registros.get(`${persona.id}|${fecha}`) ?? [];
  const primero = registros[0] ?? null;
  const ultimo = registros.at(-1) ?? null;

  let estado;
  if (asistencia) estado = asistencia.estado;
  else if (fecha > hoy()) estado = turnos.length ? 'programado' : 'descanso';
  else if (primero) estado = turnos.length ? 'presente' : 'fuera_de_horario';
  else if (turnos.length === 0) estado = 'descanso';
  else estado = fecha < hoy() ? 'sin_registro' : 'pendiente';

  let minutosRetardo = 0;
  if (primero && turnos.length) {
    const turno = turnos.find((t) => t.turnoId === primero.turnoId) ?? turnos[0];
    minutosRetardo = Math.max(0, minutos(horaLocal(primero.fechaHoraEntrada)) - minutos(deHoraDb(turno.turno.horaEntrada)));
  }

  return {
    fecha,
    turnos: turnos.map((t) => ({
      turnoId: t.turnoId,
      turno: t.turno.nombre,
      horaEntrada: deHoraDb(t.turno.horaEntrada),
      horaSalida: deHoraDb(t.turno.horaSalida),
      sala: { id: t.sala.id, nombre: t.sala.nombre },
    })),
    entrada: primero && horaLocal(primero.fechaHoraEntrada),
    salida: ultimo?.fechaHoraSalida ? horaLocal(ultimo.fechaHoraSalida) : null,
    dentroDeZona: registros.every((r) => r.dentroDeZona),
    estado,
    motivo: asistencia?.motivo?.descripcion ?? null,
    motivoId: asistencia?.motivoId ?? null,
    asistenciaId: asistencia?.id ?? null,
    minutosRetardo: estado === 'retardo' ? minutosRetardo : 0,
  };
}

const esFalta = (estado) => estado === 'falta' || estado === 'sin_registro';

function asistenciaDePersona(persona, fechas, datos) {
  const dias = fechas
    .filter((f) => estabaActiva(persona, f))
    .map((f) => calcularDia(persona, f, datos))
    .filter((d) => d.estado !== 'descanso')
    .reverse();
  const { horarios, movimientos, ...datosPersona } = persona;
  return {
    persona: datosPersona,
    resumen: {
      diasTrabajados: dias.filter((d) => d.entrada).length,
      retardos: dias.filter((d) => d.estado === 'retardo').length,
      faltas: dias.filter((d) => esFalta(d.estado)).length,
      incidencias: dias.filter((d) => d.estado === 'incidencia').length,
    },
    dias,
  };
}

// ¿Ese turno ya empezó? Hoy, el vespertino de la mañana todavía no cuenta como faltante.
function turnoEmpezado(fecha, turno) {
  if (fecha < hoy()) return true;
  if (fecha > hoy()) return false;
  return minutos(horaLocal(new Date())) >= minutos(deHoraDb(turno.horaEntrada));
}

// Cobertura de una estancia en un día: por sala y turno, presentes contra el mínimo
function calcularCobertura(estancia, turnos, fecha, datos) {
  const salas = estancia.salas.map((s) => ({
    sala: { id: s.id, nombre: s.nombre },
    minimo: s.minimoPersonal,
    turnos: turnos.map((t) => ({ turnoId: t.id, turno: t.nombre, programados: 0, presentes: 0 })),
  }));
  let programados = 0;
  let presentes = 0;
  let pendientes = 0;

  for (const persona of datos.personas) {
    if (persona.estanciaId !== estancia.id || !estabaActiva(persona, fecha)) continue;
    const dia = calcularDia(persona, fecha, datos);
    const registros = datos.registros.get(`${persona.id}|${fecha}`) ?? [];
    if (registros.length) presentes++;
    if (dia.turnos.length) programados++;
    if (dia.estado === 'pendiente') pendientes++;
    for (const t of dia.turnos) {
      const fila = salas.find((s) => s.sala.id === t.sala.id)?.turnos.find((x) => x.turnoId === t.turnoId);
      if (fila) fila.programados++;
    }
    for (const r of registros) {
      const fila = salas.find((s) => s.sala.id === r.salaId)?.turnos.find((x) => x.turnoId === r.turnoId);
      if (fila) fila.presentes++;
    }
  }

  const alertas = [];
  for (const fila of salas) {
    for (const t of fila.turnos) {
      const turno = turnos.find((x) => x.id === t.turnoId);
      t.empezado = turnoEmpezado(fecha, turno);
      t.sinCubrir = t.programados < fila.minimo;
      t.faltan = Math.max(0, fila.minimo - (t.empezado ? t.presentes : t.programados));
      t.bajoMinimo = t.faltan > 0;
      if (t.bajoMinimo) {
        alertas.push(`Falta${t.faltan > 1 ? 'n' : ''} ${t.faltan} en ${fila.sala.nombre} (${t.turno})`);
      }
    }
  }
  return {
    estancia: { id: estancia.id, nombre: estancia.nombre },
    fecha,
    presentes,
    programados,
    pendientes,
    completa: alertas.length === 0,
    alertas,
    salas,
  };
}

const estanciasCon = (where) =>
  prisma.estancia.findMany({
    where,
    include: { salas: { orderBy: { id: 'asc' } } },
    orderBy: { id: 'asc' },
  });

module.exports = {
  cargarDatos,
  estabaActiva,
  calcularDia,
  asistenciaDePersona,
  calcularCobertura,
  estanciasCon,
  esFalta,
};
