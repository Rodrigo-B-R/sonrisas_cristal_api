FROM node:22-slim

# openssl lo pide Prisma; tzdata para que TZ=America/Monterrey funcione
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends openssl tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json prisma.config.js ./
COPY prisma ./prisma

# prisma generate pide DATABASE_URL; la real llega desde .env al prender el contenedor
RUN DATABASE_URL="postgresql://build:build@localhost:5432/build" npm ci

COPY . .

ENV NODE_ENV=production \
    PORT=8000
EXPOSE 8000

USER node

CMD ["node", "src/index.js"]
