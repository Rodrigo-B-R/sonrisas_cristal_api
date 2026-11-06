require('dotenv/config');
const { defineConfig, env } = require('prisma/config');

// Las tablas las crea el script SQL del equipo (npm run db:crear), no las migraciones de Prisma.
module.exports = defineConfig({
  schema: 'prisma/schema.prisma',
  migrations: {
    seed: 'node prisma/seed.js',
  },
  datasource: {
    url: env('DATABASE_URL'),
  },
});
