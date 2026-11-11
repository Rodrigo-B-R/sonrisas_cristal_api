// Cabeceras HTTP de seguridad (defensa en profundidad)
function cabeceras(req, res, next) {
  res.set({
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    // La API solo responde JSON: no debe cargar nada
    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
    'Referrer-Policy': 'no-referrer',
    // Que celulares y proxies no guarden datos del personal
    'Cache-Control': 'no-store',
  });
  next();
}

// Límite de intentos de login por IP (contra fuerza bruta)
const LIMITE = Number(process.env.LOGIN_INTENTOS_POR_MINUTO) || 5;
const VENTANA_MS = 60 * 1000;
const intentos = new Map();

setInterval(() => {
  const ahora = Date.now();
  for (const [ip, dato] of intentos) {
    if (ahora - dato.inicio > VENTANA_MS) intentos.delete(ip);
  }
}, VENTANA_MS).unref();

function limiteLogin(req, res, next) {
  const ahora = Date.now();
  let dato = intentos.get(req.ip);
  if (!dato || ahora - dato.inicio > VENTANA_MS) {
    dato = { inicio: ahora, cuenta: 0 };
    intentos.set(req.ip, dato);
  }
  dato.cuenta += 1;
  if (dato.cuenta > LIMITE) {
    const segundos = Math.ceil((dato.inicio + VENTANA_MS - ahora) / 1000);
    res.set('Retry-After', String(segundos));
    return res.status(429).json({ error: `Demasiados intentos. Espera ${segundos} segundos.` });
  }
  next();
}

// Textos de máximo 255 (lo que aguantan las columnas) y listas de máximo 200
const MAX_TEXTO = 255;
const MAX_LISTA = 200;

function buscarExceso(valor) {
  if (typeof valor === 'string') return valor.length > MAX_TEXTO ? `Un texto pasa de ${MAX_TEXTO} caracteres` : null;
  if (Array.isArray(valor)) {
    if (valor.length > MAX_LISTA) return `Una lista pasa de ${MAX_LISTA} elementos`;
    for (const v of valor) {
      const error = buscarExceso(v);
      if (error) return error;
    }
  } else if (valor && typeof valor === 'object') {
    for (const v of Object.values(valor)) {
      const error = buscarExceso(v);
      if (error) return error;
    }
  }
  return null;
}

function revisarBody(req, res, next) {
  const error = buscarExceso(req.body);
  if (error) return res.status(400).json({ error });
  next();
}

// Evita que Excel ejecute fórmulas metidas en un texto (=, +, -, @)
function celdaCsv(v) {
  let texto = String(v ?? '');
  if (typeof v === 'string' && /^[=+\-@\t\r]/.test(texto)) texto = `'${texto}`;
  return `"${texto.replaceAll('"', '""')}"`;
}

module.exports = { cabeceras, limiteLogin, revisarBody, celdaCsv };
