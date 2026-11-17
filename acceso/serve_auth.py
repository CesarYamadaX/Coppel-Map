import base64, hashlib, hmac, html, json, os, secrets, struct, sys, threading, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
TOTP_FILE = os.environ.get("COPPEL_TOTP", os.path.join(HERE, "totp.json"))   # {"usuario": "SECRETO_BASE32"}
SESSION_TTL = 8 * 3600
MAX_FAILS, WINDOW = 5, 300  # 5 fallos por usuario en 5 min => bloqueo temporal

lock = threading.Lock()
sessions = {}   # token -> expiry
fails = {}      # usuario -> [timestamps]
last_step = {}  # usuario -> ultimo contador TOTP usado (evita reutilizar un codigo)


def totp_step(secret_b32, step):
    key = base64.b32decode(secret_b32)
    h = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def totp_ok(user, code):
    try:
        with open(TOTP_FILE) as f:
            secret = json.load(f).get(user)
    except Exception:
        return False
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    now = int(time.time() // 30)
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(totp_step(secret, step), code):
            with lock:
                if last_step.get(user, 0) >= step:
                    return False
                last_step[user] = step
            return True
    return False


def try_login(user, code):
    user = user.strip().lower()
    if "\\" in user:
        user = user.split("\\", 1)[1]
    if not user or len(user) > 64:
        return False
    now = time.time()
    with lock:
        recent = [t for t in fails.get(user, []) if now - t < WINDOW]
        fails[user] = recent
        if len(recent) >= MAX_FAILS:
            return False
    good = totp_ok(user, code.strip())
    if not good:
        with lock:
            fails[user].append(now)
    return good


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Coppel Map</title>
<style>
body{font:16px system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;min-height:100vh;margin:0}
form{background:#1e293b;padding:28px;border-radius:10px;width:min(320px,90vw);display:grid;gap:12px}
h1{font-size:18px;margin:0 0 4px}input,button{font:inherit;padding:10px;border-radius:6px;border:1px solid #475569;background:#0f172a;color:inherit}
button{background:#2563eb;border-color:#2563eb;cursor:pointer}p{margin:0;color:#fca5a5;font-size:14px}small{color:#94a3b8}
</style>
<form method=post action=/login>
<h1>Coppel Map</h1>
<input name=user placeholder="Usuario" autocomplete=username required>
<input name=code inputmode=numeric pattern="[0-9]{6}" maxlength=6 placeholder="Código de 6 dígitos" autocomplete=one-time-code required>
%s<button>Entrar</button>
<small>El código lo da tu app Authenticator.</small>
</form>"""


class Auth(SimpleHTTPRequestHandler):
    def authed(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                with lock:
                    return sessions.get(v, 0) > time.time()
        return False

    def page(self, status, err=""):
        body = (PAGE % (f"<p>{html.escape(err)}</p>" if err else "")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?", 1)[0].lower()
        if p.startswith("/acceso") or p.endswith("totp.json") or "/qr/" in p:
            self.send_response(404)  # nunca servir scripts, claves ni QR
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.authed():
            return super().do_GET()
        self.page(401)

    do_HEAD = do_GET

    def do_POST(self):
        if self.path != "/login":
            return self.page(401)
        n = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
        f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        if try_login(f.get("user", ""), f.get("code", "")):
            tok = secrets.token_urlsafe(32)
            with lock:
                sessions[tok] = time.time() + SESSION_TTL
            self.send_response(303)
            self.send_header("Set-Cookie", f"sid={tok}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}")
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.page(401, "Usuario o código incorrectos.")

    def log_message(self, *a):  # sin registros: no guardar usuarios ni cabeceras
        pass


root, port = sys.argv[1], int(sys.argv[2])
ThreadingHTTPServer(("127.0.0.1", port), partial(Auth, directory=root)).serve_forever()
