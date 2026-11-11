const express = require('express');
const bcrypt = require('bcryptjs');
const prisma = require('../prisma');
const { verificarToken, firmarToken } = require('../middleware/auth');
const { revisarPassword } = require('../utilidades');
const { limiteLogin } = require('../seguridad');

const router = express.Router();

// Si la clave no existe se compara contra este hash, para que tarde lo mismo
// y no se pueda saber qué claves existen midiendo el tiempo
const HASH_FALSO = bcrypt.hashSync('no-es-una-contraseña-real', 10);

// POST /login  { clave, password }  ->  { token, rol, usuario }   (máximo 5 intentos por minuto)
router.post('/login', limiteLogin, async (req, res) => {
  const { clave, password } = req.body ?? {}; // sin body, Express 5 deja req.body como undefined
  if (!clave || !password) {
    return res.status(400).json({ error: 'Faltan clave o password' });
  }
  const usuario = await prisma.usuario.findUnique({
    where: { clave },
    omit: { password: false }, // aquí sí lo necesitamos, para compararlo
    include: { rol: true },
  });
  const correcta = await bcrypt.compare(String(password), usuario?.password ?? HASH_FALSO);
  if (!usuario || !usuario.estaActivo || !correcta) {
    return res.status(401).json({ error: 'No autorizado' });
  }
  res.json({
    token: firmarToken(usuario),
    rol: usuario.rol.nombre,
    usuario: { id: usuario.id, nombre: usuario.nombre, estanciaId: usuario.estanciaId },
  });
});

// GET /perfil
router.get('/perfil', verificarToken, async (req, res) => {
  const usuario = await prisma.usuario.findUnique({
    where: { id: req.usuario.id },
    include: { rol: true, puesto: true, estancia: { include: { ubicacion: true } } },
  });
  if (!usuario) {
    return res.status(404).json({ error: 'No encontrado' });
  }
  res.json(usuario);
});

// PUT /perfil/password  { actual, nueva }  ->  { mensaje, token }
// Los tokens anteriores dejan de servir; se regresa uno nuevo
router.put('/perfil/password', verificarToken, async (req, res) => {
  const { actual, nueva } = req.body ?? {};
  if (!actual || !nueva) {
    return res.status(400).json({ error: 'Faltan actual o nueva' });
  }
  const usuario = await prisma.usuario.findUnique({
    where: { id: req.usuario.id },
    omit: { password: false },
  });
  if (!usuario || !(await bcrypt.compare(actual, usuario.password))) {
    return res.status(401).json({ error: 'La contraseña actual no es correcta' });
  }
  const faltan = revisarPassword(nueva, actual);
  if (faltan.length > 0) {
    return res.status(400).json({ error: 'La contraseña no cumple los requisitos', faltan });
  }
  const actualizado = await prisma.usuario.update({
    where: { id: usuario.id },
    data: { password: await bcrypt.hash(nueva, 10) },
    omit: { password: false },
    include: { rol: true },
  });
  res.json({ mensaje: 'Contraseña actualizada', token: firmarToken(actualizado) });
});

module.exports = router;
