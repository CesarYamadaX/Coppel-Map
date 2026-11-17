"""Crea (o regenera) la clave 2FA de un usuario y abre una pagina con su QR.

Uso:  python add_user.py usuario
El QR se escanea con Microsoft Authenticator o Google Authenticator.
La pagina se guarda en la carpeta qr/ : borrala cuando la persona ya lo haya escaneado.
"""
import base64, html, json, os, secrets, sys, webbrowser
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
f = os.environ.get("COPPEL_TOTP", os.path.join(HERE, "totp.json"))
user = sys.argv[1].strip().lower()
if "\\" in user:
    user = user.split("\\", 1)[1]

data = json.load(open(f)) if os.path.exists(f) else {}
secret = data[user] = base64.b32encode(secrets.token_bytes(20)).decode()
json.dump(data, open(f, "w"))

uri = "otpauth://totp/" + quote("Coppel Map:" + user) + "?secret=" + secret + "&issuer=" + quote("Coppel Map")
page = f"""<!doctype html><meta charset=utf-8><title>QR {html.escape(user)}</title>
<style>body{{font:16px system-ui;display:grid;place-items:center;min-height:100vh;margin:0;background:#f1f5f9}}
main{{background:#fff;padding:28px;border-radius:10px;text-align:center;max-width:340px}}
code{{word-break:break-all;display:block;margin:8px 0;font-size:14px}}</style>
<main><h2>Coppel Map</h2><p>Usuario: <b>{html.escape(user)}</b></p>
<div id=qr style="display:inline-block"></div>
<p>Escanéalo con Microsoft o Google Authenticator.</p>
<p>¿No puedes escanear? Clave manual:</p><code>{secret}</code>
<p style="color:#b91c1c;font-size:13px">Este QR es la llave de la cuenta. No lo compartas ni lo dejes guardado.</p></main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>new QRCode(document.getElementById("qr"),{{text:{json.dumps(uri)},width:220,height:220}})</script>"""

os.makedirs(os.path.join(HERE, "qr"), exist_ok=True)
out = os.path.join(HERE, "qr", f"{user}.html")
open(out, "w", encoding="utf-8").write(page)
print("Usuario:", user)
print("Clave manual:", secret)
print("QR abierto en el navegador:", out)
webbrowser.open("file:///" + out.replace("\\", "/"))
