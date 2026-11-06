const express = require('express');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const prisma = require('../prisma');
const { SECRET, verificarToken } = require('../middleware/auth');
const { revisarPassword } = require('../utilidades');

const router = express.Router();

// POST /login  { clave, password }  ->  { token, rol, usuario }
router.post('/login', async (req, res) => {
  const { clave, password } = req.body ?? {}; // sin body, Express 5 deja req.body como undefined
  if (!clave || !password) {
    return res.status(400).json({ error: 'Faltan clave o password' });
  }
  const usuario = await prisma.usuario.findUnique({
    where: { clave },
    omit: { password: false }, // aquí sí lo necesitamos, para compararlo
    include: { rol: true },
  });
  // bcrypt.compare saca el hash del texto y lo compara con el guardado
  if (!usuario || !usuario.estaActivo || !(await bcrypt.compare(password, usuario.password))) {
    return res.status(401).json({ error: 'No autorizado' });
  }
  const payload = { id: usuario.id, rol: usuario.rol.nombre, estanciaId: usuario.estanciaId };
  const token = jwt.sign(payload, SECRET, { expiresIn: '1h' });
  res.json({
    token,
    rol: usuario.rol.nombre,
    usuario: { id: usuario.id, nombre: usuario.nombre, estanciaId: usuario.estanciaId },
  });
});

// GET /perfil  ->  el usuario dueño del token, con su rol, puesto y estancia
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

// PUT /perfil/password  { actual, nueva }  ->  { mensaje }
// La usa la pantalla "Crea tu contraseña" y "Mi cuenta".
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
  await prisma.usuario.update({
    where: { id: usuario.id },
    data: { password: await bcrypt.hash(nueva, 10) },
  });
  res.json({ mensaje: 'Contraseña actualizada' });
});

module.exports = router;
