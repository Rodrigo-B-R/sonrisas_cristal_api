const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });

const prisma = new PrismaClient({
  adapter,
  // El password nunca sale en una respuesta (el login lo pide con omit: { password: false })
  omit: { usuario: { password: true } },
});

module.exports = prisma;
