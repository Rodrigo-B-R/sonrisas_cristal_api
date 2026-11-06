const jwt = require('jsonwebtoken');

const SECRET = process.env.JWT_SECRET;

// Revisa el gafete: ¿la petición trae un token válido?
function verificarToken(req, res, next) {
  const header = req.headers.authorization;
  if (!header) {
    return res.status(401).json({ error: 'Falta el token' });
  }
  const token = header.split(' ')[1]; // "Bearer eyJ..." -> "eyJ..."
  try {
    req.usuario = jwt.verify(token, SECRET); // { id, rol, estanciaId, iat, exp }
    next();
  } catch {
    res.status(401).json({ error: 'Token no válido' });
  }
}

// Va DESPUÉS de verificarToken: ya sabemos quién es, ¿su rol puede hacerlo?
// Uso: permitir('responsable')  o  permitir('responsable', 'direccion')
function permitir(...roles) {
  return (req, res, next) => {
    if (!roles.includes(req.usuario.rol)) {
      return res.status(403).json({ error: 'Tu rol no puede hacer esto' });
    }
    next();
  };
}

module.exports = { SECRET, verificarToken, permitir };
