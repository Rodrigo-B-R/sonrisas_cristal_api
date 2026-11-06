// Reportes calculados a partir de horario, asistencia, registro_entradas y movimiento_usuario:
//   GET /cobertura             "Inicio" de la Responsable: presentes y salas bajo el mínimo
//   GET /resumen               "Resumen" de Dirección: estancias completas o con faltante
//   GET /estadisticas          "Estadísticas" de Dirección
//   GET /exportar/asistencias  CSV para "Exportar"
const express = require('express');
const prisma = require('../prisma');
const { verificarToken, permitir } = require('../middleware/auth');
const { hoy, esFecha, aFechaDb, rangoDeFechas, leerPeriodo, filtroEstancia } = require('../utilidades');
const {
  cargarDatos,
  estabaActiva,
  calcularDia,
  asistenciaDePersona,
  calcularCobertura,
  estanciasCon,
  esFalta,
} = require('../calculos');

const router = express.Router();

const turnosOrdenados = () => prisma.turno.findMany({ orderBy: { id: 'asc' } });

// "desde" por defecto: el primero del mes
function periodoDelMes(query, maxDias) {
  return leerPeriodo({ desde: `${hoy().slice(0, 8)}01`, ...query }, maxDias);
}

// GET /cobertura  ?fecha=  (hoy por defecto; dirección necesita ?estanciaId=)
router.get('/cobertura', verificarToken, permitir('responsable', 'direccion'), async (req, res) => {
  const fecha = req.query.fecha ?? hoy();
  if (!esFecha(fecha)) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const filtro = filtroEstancia(req);
  if (!filtro.estanciaId) {
    return res.status(400).json({ error: 'Falta estanciaId' });
  }
  const [estancia] = await estanciasCon({ id: filtro.estanciaId });
  if (!estancia) {
    return res.status(404).json({ error: 'Estancia no encontrada' });
  }
  const datos = await cargarDatos(filtro, fecha, fecha);
  res.json(calcularCobertura(estancia, await turnosOrdenados(), fecha, datos));
});

// GET /resumen  ?fecha=  ->  { fecha, completas, conFaltante, estancias: [...] }
router.get('/resumen', verificarToken, permitir('direccion'), async (req, res) => {
  const fecha = req.query.fecha ?? hoy();
  if (!esFecha(fecha)) {
    return res.status(400).json({ error: 'La fecha va como AAAA-MM-DD' });
  }
  const [estancias, turnos, datos] = await Promise.all([estanciasCon({}), turnosOrdenados(), cargarDatos({}, fecha, fecha)]);
  const lista = estancias.map((e) => {
    const c = calcularCobertura(e, turnos, fecha, datos);
    return { ...c.estancia, completa: c.completa, alertas: c.alertas, presentes: c.presentes, programados: c.programados };
  });
  res.json({
    fecha,
    completas: lista.filter((e) => e.completa).length,
    conFaltante: lista.filter((e) => !e.completa).length,
    estancias: lista,
  });
});

// GET /estadisticas  ?desde=&hasta=  (por defecto, este mes)  ?estanciaId= (dirección)
router.get('/estadisticas', verificarToken, permitir('responsable', 'direccion'), async (req, res) => {
  const periodo = periodoDelMes(req.query, 400);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  const { desde, hasta } = periodo;
  const filtro = filtroEstancia(req);
  const [estancias, turnos, datos, movimientos] = await Promise.all([
    estanciasCon(filtro.estanciaId ? { id: filtro.estanciaId } : {}),
    turnosOrdenados(),
    cargarDatos(filtro, desde, hasta > hoy() ? hoy() : hasta),
    prisma.movimientoUsuario.findMany({
      where: { fecha: { gte: aFechaDb(desde), lte: aFechaDb(hasta) } },
    }),
  ]);
  const fechasPasadas = rangoDeFechas(desde, hasta).filter((f) => f <= hoy());

  const fechasInsuficientes = new Set(); // días en que al menos una estancia estuvo bajo el mínimo
  const porEstancia = estancias.map((e) => {
    let programados = 0;
    let faltas = 0;
    let retardos = 0;
    for (const p of datos.personas.filter((x) => x.estanciaId === e.id)) {
      for (const f of fechasPasadas) {
        if (!estabaActiva(p, f)) continue;
        const dia = calcularDia(p, f, datos);
        if (dia.turnos.length) programados++;
        if (esFalta(dia.estado)) faltas++;
        if (dia.estado === 'retardo') retardos++;
      }
    }
    const diasInsuficiente = fechasPasadas.filter((f) => {
      if (calcularCobertura(e, turnos, f, datos).completa) return false;
      fechasInsuficientes.add(f);
      return true;
    }).length;
    const cuenta = (tipo, campo) => movimientos.filter((m) => m.tipo === tipo && m[campo] === e.id).length;
    return {
      estancia: { id: e.id, nombre: e.nombre },
      altas: cuenta('alta', 'estanciaDestinoId'),
      bajas: cuenta('baja', 'estanciaOrigenId'),
      trasladosEntrada: cuenta('traslado', 'estanciaDestinoId'),
      trasladosSalida: cuenta('traslado', 'estanciaOrigenId'),
      diasPersonalInsuficiente: diasInsuficiente,
      faltas,
      retardos,
      diasProgramados: programados,
    };
  });

  const suma = (campo) => porEstancia.reduce((total, e) => total + e[campo], 0);
  const programados = suma('diasProgramados');
  res.json({
    desde,
    hasta,
    altas: suma('altas'),
    bajas: suma('bajas'),
    faltas: suma('faltas'),
    retardos: suma('retardos'),
    diasPersonalInsuficiente: fechasInsuficientes.size,
    absentismo: programados ? Math.round((suma('faltas') / programados) * 1000) / 10 : 0, // % con un decimal
    porEstancia,
  });
});

// GET /exportar/asistencias  ?desde=&hasta=  ->  archivo CSV
router.get('/exportar/asistencias', verificarToken, permitir('responsable', 'direccion'), async (req, res) => {
  const periodo = periodoDelMes(req.query, 400);
  if (periodo.error) {
    return res.status(400).json({ error: periodo.error });
  }
  const hasta = periodo.hasta > hoy() ? hoy() : periodo.hasta;
  const desde = periodo.desde > hasta ? hasta : periodo.desde;
  const datos = await cargarDatos(filtroEstancia(req), desde, hasta);
  const fechas = rangoDeFechas(desde, hasta);

  // Comillas en cada campo para que comas o acentos no rompan el archivo
  const campo = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const filas = [
    ['estancia', 'nombre', 'clave', 'puesto', 'fecha', 'turno', 'sala', 'hora_programada', 'entrada', 'salida', 'estado', 'motivo', 'minutos_retardo', 'dentro_de_zona'],
  ];
  for (const p of datos.personas) {
    for (const d of asistenciaDePersona(p, fechas, datos).dias.reverse()) {
      const t = d.turnos[0];
      filas.push([
        p.estancia?.nombre,
        p.nombre,
        p.clave,
        p.puesto?.nombre,
        d.fecha,
        d.turnos.map((x) => x.turno).join(' + '),
        d.turnos.map((x) => x.sala.nombre).join(' + '),
        t ? `${t.horaEntrada}-${t.horaSalida}` : '',
        d.entrada,
        d.salida,
        d.estado,
        d.motivo,
        d.minutosRetardo,
        d.dentroDeZona ? 'si' : 'no',
      ]);
    }
  }
  const csv = '﻿' + filas.map((f) => f.map(campo).join(',')).join('\r\n'); // BOM para que Excel lea los acentos
  res.set('Content-Type', 'text/csv; charset=utf-8');
  res.set('Content-Disposition', `attachment; filename="asistencias_${desde}_${hasta}.csv"`);
  res.send(csv);
});

module.exports = router;
