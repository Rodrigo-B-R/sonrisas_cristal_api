const jwt = require('jsonwebtoken');

const SECRET = process.env.JWT_SECRET;

function verificarToken(req, res, next) {
  const header = req.headers.authorization;
  if (!header) {
    return res.status(401).json({ error: 'Falta el token' });
  }
  const token = header.split(' ')[1];
  try {
    req.usuario = jwt.verify(token, SECRET); // { id, rol, estanciaId, iat, exp }
    next();
  } catch {
    res.status(401).json({ error: 'Token no válido' });
  }
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

module.exports = { SECRET, verificarToken, permitir };
