// Crea las tablas corriendo el script SQL del equipo (repo sonrisas_cristal_db).
// Uso:  npm run db:crear                       (usa ../sonrisas_cristal_db/init/01-init.sql)
//       npm run db:crear -- ruta/a/otro.sql    (si tu script está en otro lado)
// Solo se corre UNA vez, con la base vacía. Si las tablas ya existen, avisa y no toca nada.
require('dotenv/config');
const fs = require('fs');
const path = require('path');
const { Client } = require('pg');

const archivo = path.resolve(process.argv[2] ?? path.join(__dirname, '..', '..', 'sonrisas_cristal_db', 'init', '01-init.sql'));

async function main() {
  if (!process.env.DATABASE_URL) {
    throw new Error('Falta DATABASE_URL en tu .env');
  }
  if (!fs.existsSync(archivo)) {
    throw new Error(`No encontré el script SQL en ${archivo}\nPásalo así: npm run db:crear -- C:\\ruta\\al\\script.sql`);
  }
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();
  try {
    const { rows } = await client.query("SELECT to_regclass('public.usuario') AS existe");
    if (rows[0].existe) {
      console.log('Las tablas ya existen: no hice nada. Sigue con: npm run seed');
      return;
    }
    console.log(`Corriendo ${archivo} ...`);
    await client.query('BEGIN');
    await client.query(fs.readFileSync(archivo, 'utf8'));
    await client.query('COMMIT');
    const tablas = await client.query(
      "SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'",
    );
    console.log(`Listo: ${tablas.rows[0].n} tablas creadas. Sigue con: npm run seed`);
  } catch (error) {
    await client.query('ROLLBACK').catch(() => {});
    throw error;
  } finally {
    await client.end();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
