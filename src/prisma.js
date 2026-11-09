const { Pool } = require('pg');
const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');

// Pool propio para poder medir sus conexiones en /metrics
const pool = new Pool({ connectionString: process.env.DATABASE_URL });

const prisma = new PrismaClient({
  adapter: new PrismaPg(pool),
  // El password nunca sale en una respuesta (el login lo pide con omit: { password: false })
  omit: { usuario: { password: true } },
});

module.exports = prisma;
module.exports.pool = pool;
