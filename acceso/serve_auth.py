import base64, datetime, hashlib, hmac, html, json, os, secrets, struct, sys, threading, time
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


# ── CAPA: ventas (unidades sell-out) por tienda Coppel desde SQL Server ──
# Cadena ODBC en la variable COPPEL_SQL o en acceso/sql.txt (en .gitignore: no la subas).
SQL_FILE = os.path.join(HERE, "sql.txt")
CAPA_SQL = """
SELECT c.num, MIN(c.nombre) nombre,
       SUM(CASE WHEN r.Date > DATEADD(day, -7, m.mx) THEN r.Qty ELSE 0 END) semana,
       SUM(CASE WHEN r.Date > DATEADD(day, -30, m.mx) THEN r.Qty ELSE 0 END) mes,
       SUM(r.Qty) ano,
       SUM(CASE WHEN r.Date >= m.ws THEN r.Qty ELSE 0 END) semana_cal,
       SUM(CASE WHEN r.Date >= m.ms THEN r.Qty ELSE 0 END) mes_cal,
       -- unidades Honor en los mismos periodos (market share = Honor / total)
       SUM(CASE WHEN r.Brand = 'HONOR' AND r.Date > DATEADD(day, -7, m.mx) THEN r.Qty ELSE 0 END) h_semana,
       SUM(CASE WHEN r.Brand = 'HONOR' AND r.Date > DATEADD(day, -30, m.mx) THEN r.Qty ELSE 0 END) h_mes,
       SUM(CASE WHEN r.Brand = 'HONOR' THEN r.Qty ELSE 0 END) h_ano,
       SUM(CASE WHEN r.Brand = 'HONOR' AND r.Date >= m.ws THEN r.Qty ELSE 0 END) h_semana_cal,
       SUM(CASE WHEN r.Brand = 'HONOR' AND r.Date >= m.ms THEN r.Qty ELSE 0 END) h_mes_cal
FROM [GTM BI Database].dbo.B2BHonorGeneralReport r WITH (NOLOCK)
-- número de tienda -> ID (APSMX…) con el catálogo; las ventas se filtran por ID
JOIN (SELECT ID, [Coppel Name] nombre, LEFT([Coppel Name], CHARINDEX(' ', [Coppel Name] + ' ') - 1) num
      FROM [GTM BI Database].dbo.CustomerStores_VW
      WHERE RetailName = 'COPPEL' AND ({filtro})) c ON c.ID = r.ID
-- fechas de corte calculadas en Python (ver cortes()); se pasan como parámetros date
CROSS JOIN (SELECT CAST(? AS date) mx, CAST(? AS date) ws, CAST(? AS date) ms) m
WHERE r.Retail = 'Coppel' AND r.DATA_TYPE = 'SO' AND r.Date > DATEADD(day, -365, m.mx)
GROUP BY c.num
"""
MAX_SQL = """SELECT CAST(MAX(Date) AS date) FROM [GTM BI Database].dbo.B2BHonorGeneralReport WITH (NOLOCK)
WHERE Retail = 'Coppel' AND DATA_TYPE = 'SO'"""
capa_cache = {}  # "36,1111" -> (expira, resultado)
mx_cache = [0, None]  # [expira, último día con ventas]: recorrer la tabla para el MAX cuesta ~la mitad de cada consulta


def cortes(cur):
    """Último día con ventas (en caché 30 min), lunes de su semana ISO y día 1 de su mes."""
    with lock:
        exp, mx = mx_cache
    if not mx or exp < time.time():
        mx = cur.execute(MAX_SQL).fetchone()[0]
        if isinstance(mx, str):
            mx = datetime.date.fromisoformat(mx[:10])
        with lock:
            mx_cache[:] = [time.time() + 1800, mx]
    # weekday(): lunes=0 … domingo=6, así el domingo cae en la semana que termina (ISO)
    return mx, mx - datetime.timedelta(days=mx.weekday()), mx.replace(day=1)


def sql_conn_str():
    s = os.environ.get("COPPEL_SQL", "").strip()
    if not s and os.path.exists(SQL_FILE):
        with open(SQL_FILE, encoding="utf-8") as f:
            s = f.read().strip()
    return s


def capa(t):
    nums = [n for n in t.split(",") if n.isdigit() and len(n) <= 5][:3]
    if not nums:
        return {"error": "Tienda no válida."}
    key = ",".join(nums)
    with lock:
        hit = capa_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    cs = sql_conn_str()
    if not cs:
        return {"error": "Falta la conexión a SQL (COPPEL_SQL o acceso/sql.txt)."}
    try:
        import pyodbc
        with pyodbc.connect(cs, timeout=10) as cn:
            cur = cn.cursor()
            mx, ws, ms = cortes(cur)
            cur.execute(CAPA_SQL.format(filtro=" OR ".join(["[Coppel Name] LIKE ?"] * len(nums))),
                        [n + " %" for n in nums] + [mx, ws, ms])
            rows = cur.fetchall()
    except Exception:
        return {"error": "No se pudo consultar SQL."}
    by = {r.num: r for r in rows}
    tiendas = []
    for n in nums:
        r = by.get(n)
        nombre = r.nombre.split(" ", 1)[1].lstrip("•· ").strip() if r and " " in r.nombre else ""
        t = {"num": n, "nombre": nombre}
        for k in ("semana", "mes", "ano", "semana_cal", "mes_cal"):
            t[k] = int(getattr(r, k) or 0) if r else 0
            t["h_" + k] = int(getattr(r, "h_" + k) or 0) if r else 0
        tiendas.append(t)
    # fechas en None si no hubo ventas en 365 días
    out = {"tiendas": tiendas, "hasta": None, "ini_sem": None, "ini_mes": None, "isow": None}
    if rows:
        out.update(hasta=mx.isoformat(), ini_sem=ws.isoformat(), ini_mes=ms.isoformat(), isow=mx.isocalendar()[1])
    with lock:
        capa_cache[key] = (time.time() + 1800, out)
    return out


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

    def json_out(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?", 1)[0].lower()
        if p == "/api/capa":
            if not self.authed():
                return self.page(401)
            q = parse_qs(self.path.partition("?")[2]).get("t", [""])[0]
            return self.json_out(capa(q))
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
