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

## CAPA (ventas por tienda desde SQL)

Al dar click en una tienda Coppel, la ficha pide `/api/capa` y muestra las unidades vendidas (sell-out, todas las marcas) de los últimos 7, 30 y 365 días y de la semana ISO (lun–dom) y el mes en curso, con el % que fue Honor (market share), hasta el último día con datos en `[GTM BI Database].dbo.B2BHonorGeneralReport`.

Requiere `pip install pyodbc` y la cadena ODBC en la variable `COPPEL_SQL` o en `acceso/sql.txt` (en `.gitignore`: **no la subas**), por ejemplo:

```
DRIVER={ODBC Driver 18 for SQL Server};SERVER=host;UID=usuario;PWD=clave;TrustServerCertificate=yes
```

## Notas

- Las claves se guardan en `totp.json` y los QR en `qr/`. Ambos están en `.gitignore`: **no los subas**.
- Para guardar las claves fuera del repo: variable de entorno `COPPEL_TOTP=ruta\totp.json`.
- El servidor responde 404 a cualquier ruta bajo `/acceso`, a `totp.json` y a `/qr/`.
- Borra cada QR de `qr/` cuando la persona lo haya escaneado.
- Tras 5 fallos de un usuario en 5 minutos se bloquea ese usuario temporalmente.
