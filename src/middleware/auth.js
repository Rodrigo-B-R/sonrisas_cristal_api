const crypto = require('crypto');
const jwt = require('jsonwebtoken');
const prisma = require('../prisma');

const SECRET = process.env.JWT_SECRET;
const ALGORITMO = 'HS256';

// Huella del hash de la contraseña: si la contraseña cambia, los tokens viejos dejan de servir
const huella = (hash) => crypto.createHash('sha256').update(hash).digest('base64url').slice(0, 16);

// usuario debe traer rol y password (hash)
function firmarToken(usuario) {
  const payload = { id: usuario.id, rol: usuario.rol.nombre, estanciaId: usuario.estanciaId, pv: huella(usuario.password) };
  return jwt.sign(payload, SECRET, { algorithm: ALGORITMO, expiresIn: '1h' });
}

// Zero Trust: en cada petición se revisa en la base que la persona siga activa,
// y se usan su rol y estancia actuales (no los que traía el token)
async function verificarToken(req, res, next) {
  const [tipo, token] = (req.headers.authorization ?? '').split(' ');
  if (tipo !== 'Bearer' || !token) {
    return res.status(401).json({ error: 'Falta el token' });
  }
  let datos;
  try {
    datos = jwt.verify(token, SECRET, { algorithms: [ALGORITMO] });
  } catch {
    return res.status(401).json({ error: 'Token no válido' });
  }
  const usuario = Number.isInteger(datos.id)
    ? await prisma.usuario.findUnique({ where: { id: datos.id }, omit: { password: false }, include: { rol: true } })
    : null;
  if (!usuario || !usuario.estaActivo || datos.pv !== huella(usuario.password)) {
    return res.status(401).json({ error: 'Tu sesión ya no es válida, vuelve a iniciar sesión' });
  }
  req.usuario = { id: usuario.id, rol: usuario.rol.nombre, estanciaId: usuario.estanciaId };
  next();
}

// Va después de verificarToken: permitir('responsable', 'direccion')
function permitir(...roles) {
  return (req, res, next) => {
    if (!roles.includes(req.usuario.rol)) {
      return res.status(403).json({ error: 'Tu rol no puede hacer esto' });
    }
    next();
  };
}

module.exports = { verificarToken, permitir, firmarToken };
