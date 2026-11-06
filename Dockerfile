# Imagen de la API de Sonrisas de Cristal.
# Construir y prender:  docker compose up -d --build   (ver README)
FROM node:22-slim

# openssl lo pide Prisma; tzdata para que TZ=America/Monterrey funcione
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends openssl tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Primero solo lo necesario para instalar, así Docker reutiliza esta capa si no cambian las dependencias
COPY package.json package-lock.json prisma.config.js ./
COPY prisma ./prisma

# npm ci corre "prisma generate", que lee DATABASE_URL. Aquí va una falsa:
# la real llega al prender el contenedor (desde .env).
RUN DATABASE_URL="postgresql://build:build@localhost:5432/build" npm ci

COPY . .

ENV NODE_ENV=production \
    PORT=3000
EXPOSE 3000

# No correr como root
USER node

CMD ["node", "src/index.js"]
