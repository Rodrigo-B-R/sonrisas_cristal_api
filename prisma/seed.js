// Llena la base con datos de prueba: catálogos, 5 estancias con sus salas y el personal de Cumbres.
// Las tablas ya deben existir (npm run db:crear). Se puede correr varias veces:
// lo que ya existe no se duplica y las contraseñas vuelven a ser SEED_PASSWORD.
require('dotenv/config');
process.env.TZ = process.env.TZ || 'America/Monterrey';
const bcrypt = require('bcryptjs');
const prisma = require('../src/prisma');
const { DIAS, SIN_FIN, aFechaDb, aHoraDb } = require('../src/utilidades');

const FECHA_ALTA = '2025-01-12';

const ROLES = ['empleada', 'responsable', 'direccion'];
const PUESTOS = ['Dirección', 'Responsable de estancia', 'Maestra titular', 'Asistente', 'Auxiliar', 'Cocina', 'Intendencia'];
const CAUSAS_BAJA = ['Renuncia', 'Fin de contrato', 'Abandono de trabajo', 'Otro'];
const TURNOS = [
  ['matutino', '07:00', '15:00'],
  ['vespertino', '12:00', '20:00'],
];

// [nombre, latitud, longitud]  (precision = 150 m)
const ESTANCIAS = [
  ['Cumbres', 25.7447, -100.4036],
  ['San Nicolás', 25.7417, -100.302],
  ['Apodaca', 25.7817, -100.1886],
  ['Guadalupe', 25.6775, -100.2597],
  ['Escobedo', 25.7953, -100.317],
];

// [nombre, mínimo de personal]  (pantalla "Salas y mínimos")
const SALAS = [
  ['Lactantes', 2],
  ['Maternal A', 3],
  ['Maternal B', 3],
  ['Preescolar', 4],
];

// Semana de lunes a domingo: M = matutino, V = vespertino, · = descanso  (pantalla "Horarios")
const PERSONAL_CUMBRES = [
  { clave: 'ana.torres', nombre: 'Ana Torres', puesto: 'Maestra titular', sala: 'Maternal A', semana: 'MMMM···' },
  { clave: 'lucia.herrera', nombre: 'Lucía Herrera', puesto: 'Maestra titular', sala: 'Lactantes', semana: 'M·MMMM·' },
  { clave: 'carmen.ruiz', nombre: 'Carmen Ruiz', puesto: 'Asistente', sala: 'Maternal B', semana: 'VVVV·V·' },
  { clave: 'sofia.diaz', nombre: 'Sofía Díaz', puesto: 'Maestra titular', sala: 'Preescolar', semana: 'MM·MM··' },
  { clave: 'paola.reyes', nombre: 'Paola Reyes', puesto: 'Auxiliar', sala: 'Maternal A', semana: '·MMMM·V' },
  { clave: 'rosa.medina', nombre: 'Rosa Medina', puesto: 'Cocina', sala: 'Lactantes', semana: 'MMMMM··' },
  { clave: 'maria.lopez', nombre: 'María López', puesto: 'Asistente', sala: 'Maternal A', semana: 'MMM·M··' },
];

// Busca por nombre y si no existe lo crea (los catálogos no tienen nombre único)
async function buscarOCrear(modelo, where, data = where) {
  return (await prisma[modelo].findFirst({ where })) ?? prisma[modelo].create({ data });
}

async function main() {
  const password = await bcrypt.hash(process.env.SEED_PASSWORD || 'Cristal2026', 10);

  // Catálogos
  const rol = {};
  for (const nombre of ROLES) rol[nombre] = await buscarOCrear('rol', { nombre });
  const puesto = {};
  for (const nombre of PUESTOS) puesto[nombre] = await buscarOCrear('puesto', { nombre });
  for (const nombre of CAUSAS_BAJA) await buscarOCrear('causaBaja', { nombre });
  const turno = {};
  for (const [nombre, entrada, salida] of TURNOS) {
    turno[nombre] = await buscarOCrear('turno', { nombre }, { nombre, horaEntrada: aHoraDb(entrada), horaSalida: aHoraDb(salida) });
  }

  // Estancias con su ubicación y sus salas
  const estancias = {};
  for (const [nombre, latitud, longitud] of ESTANCIAS) {
    const estancia =
      (await prisma.estancia.findFirst({ where: { nombre } })) ??
      (await prisma.estancia.create({
        data: { nombre, ubicacion: { create: { nombre: `Estancia ${nombre}`, latitud, longitud, precision: 150 } } },
      }));
    estancias[nombre] = { ...estancia, salas: {} };
    for (const [sala, minimoPersonal] of SALAS) {
      estancias[nombre].salas[sala] = await buscarOCrear(
        'sala',
        { nombre: sala, estanciaId: estancia.id },
        { nombre: sala, minimoPersonal, estanciaId: estancia.id },
      );
    }
  }
  const cumbres = estancias['Cumbres'];

  // Crea o actualiza a la persona y, la primera vez, su movimiento de alta
  let direccion = null;
  async function crearUsuario({ clave, nombre, rol: nombreRol, puesto: nombrePuesto }, numero) {
    const datos = {
      nombre,
      correo: `${clave}@sonrisascristal.mx`,
      celular: `81 1000 ${String(numero).padStart(4, '0')}`,
      rolId: rol[nombreRol].id,
      puestoId: puesto[nombrePuesto].id,
      estanciaId: cumbres.id,
    };
    const usuario = await prisma.usuario.upsert({
      where: { clave },
      update: { ...datos, password, estaActivo: true },
      create: { ...datos, clave, password, estaActivo: true },
    });
    if (!(await prisma.movimientoUsuario.findFirst({ where: { usuarioId: usuario.id, tipo: 'alta' } }))) {
      await prisma.movimientoUsuario.create({
        data: {
          tipo: 'alta',
          fecha: aFechaDb(FECHA_ALTA),
          usuarioId: usuario.id,
          hechoPorId: (direccion ?? usuario).id,
          estanciaDestinoId: cumbres.id,
        },
      });
    }
    return usuario;
  }

  // Dirección (ve todas las estancias) y la Responsable de Cumbres
  direccion = await crearUsuario({ clave: 'direccion', nombre: 'Dirección General', rol: 'direccion', puesto: 'Dirección' }, 1);
  const marisol = await crearUsuario(
    { clave: 'marisol.garcia', nombre: 'Marisol García', rol: 'responsable', puesto: 'Responsable de estancia' },
    2,
  );

  // Personal de Cumbres con su horario semanal (solo se crea si aún no tiene)
  const empleadas = [];
  for (const [i, p] of PERSONAL_CUMBRES.entries()) {
    const usuario = await crearUsuario({ ...p, rol: 'empleada' }, i + 3);
    empleadas.push(usuario);
    if (await prisma.horario.findFirst({ where: { usuarioId: usuario.id } })) continue;
    const dias = [...p.semana]
      .map((letra, d) => ({ letra, dia: DIAS[d] }))
      .filter((d) => d.letra !== '·')
      .map(({ letra, dia }) => ({
        diaDeSemana: dia,
        turnoId: turno[letra === 'M' ? 'matutino' : 'vespertino'].id,
        salaId: cumbres.salas[p.sala].id,
      }));
    await prisma.horario.create({
      data: {
        usuarioId: usuario.id,
        vigenteDesde: aFechaDb(FECHA_ALTA),
        vigenteHasta: aFechaDb(SIN_FIN),
        dias: { create: dias },
      },
    });
  }

  // Un aviso de ejemplo para que la pestaña Avisos no salga vacía
  if ((await prisma.aviso.count()) === 0) {
    await prisma.aviso.create({
      data: {
        asunto: 'Bienvenidas a la app',
        mensaje: 'A partir de hoy registramos entrada y salida desde el celular. Cualquier duda, con Marisol.',
        tipoAviso: 'recordatorio',
        autorId: marisol.id,
        lecturas: { create: empleadas.map((e) => ({ usuarioId: e.id })) },
      },
    });
  }

  const total = await prisma.usuario.count();
  console.log(`Seed listo: ${ESTANCIAS.length} estancias, ${total} usuarios.`);
  console.log('Prueba con clave "ana.torres", "marisol.garcia" o "direccion" y la contraseña de SEED_PASSWORD.');
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
