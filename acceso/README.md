# Acceso con 2FA

Servidor local que protege el mapa con usuario + código de 6 dígitos (TOTP) y sirve la carpeta del repo.

## Uso

```bash
# 1. Crear un usuario (abre una página con el QR para Microsoft/Google Authenticator)
python acceso/add_user.py usuario

# 2. Arrancar el servidor (carpeta a servir, puerto)
python acceso/serve_auth.py . 8001

# 3. Exponerlo, por ejemplo con un túnel SSH
ssh -R 80:localhost:8001 nokey@localhost.run
```

## Notas

- Las claves se guardan en `totp.json` y los QR en `qr/`. Ambos están en `.gitignore`: **no los subas**.
- Para guardar las claves fuera del repo: variable de entorno `COPPEL_TOTP=ruta\totp.json`.
- El servidor responde 404 a cualquier ruta bajo `/acceso`, a `totp.json` y a `/qr/`.
- Borra cada QR de `qr/` cuando la persona lo haya escaneado.
- Tras 5 fallos de un usuario en 5 minutos se bloquea ese usuario temporalmente.
