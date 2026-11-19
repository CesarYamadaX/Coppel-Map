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


# Ventas de todas las tiendas en los últimos 30 días (para el tamaño de los puntos del mapa)
VENTAS_SQL = """
SELECT c.num, SUM(r.Qty) qty
FROM [GTM BI Database].dbo.B2BHonorGeneralReport r WITH (NOLOCK)
JOIN (SELECT ID, LEFT([Coppel Name], CHARINDEX(' ', [Coppel Name] + ' ') - 1) num
      FROM [GTM BI Database].dbo.CustomerStores_VW WHERE RetailName = 'COPPEL') c ON c.ID = r.ID
WHERE r.Retail = 'Coppel' AND r.DATA_TYPE = 'SO' AND r.Date > DATEADD(day, -30, CAST(? AS date))
GROUP BY c.num
"""
ventas_cache = [0, None]  # [expira, resultado]


def ventas():
    with lock:
        exp, out = ventas_cache
    if out and exp > time.time():
        return out
    cs = sql_conn_str()
    if not cs:
        return {"error": "Falta la conexión a SQL (COPPEL_SQL o acceso/sql.txt).", "code": "nosql"}
    try:
        import pyodbc
        with pyodbc.connect(cs, timeout=10) as cn:
            cur = cn.cursor()
            mx = cortes(cur)[0]
            rows = cur.execute(VENTAS_SQL, [mx]).fetchall()
    except Exception:
        return {"error": "No se pudo consultar SQL.", "code": "sql"}
    out = {"hasta": mx.isoformat(), "dias": 30, "t": {r.num: int(r.qty or 0) for r in rows if r.num and r.num.isdigit()}}
    with lock:
        ventas_cache[:] = [time.time() + 1800, out]
    return out


def capa(t):
    nums = [n for n in t.split(",") if n.isdigit() and len(n) <= 5][:3]
    if not nums:
        return {"error": "Tienda no válida.", "code": "bad"}
    key = ",".join(nums)
    with lock:
        hit = capa_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    cs = sql_conn_str()
    if not cs:
        return {"error": "Falta la conexión a SQL (COPPEL_SQL o acceso/sql.txt).", "code": "nosql"}
    try:
        import pyodbc
        with pyodbc.connect(cs, timeout=10) as cn:
            cur = cn.cursor()
            mx, ws, ms = cortes(cur)
            cur.execute(CAPA_SQL.format(filtro=" OR ".join(["[Coppel Name] LIKE ?"] * len(nums))),
                        [n + " %" for n in nums] + [mx, ws, ms])
            rows = cur.fetchall()
    except Exception:
        return {"error": "No se pudo consultar SQL.", "code": "sql"}
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
:root{--a:#2f6fe0;--b:#ffd500}
*{box-sizing:border-box}
body{font:15px/1.4 Inter,system-ui,"Segoe UI",sans-serif;color:#e8edf7;display:grid;place-items:center;min-height:100vh;margin:0;overflow:hidden;
  background:radial-gradient(1200px 700px at 15%% 10%%,#163a7a 0,transparent 60%%) no-repeat,radial-gradient(900px 600px at 90%% 90%%,#4a3a05 0,transparent 60%%) no-repeat,#0b1220}
body::before,body::after{content:"";position:fixed;width:420px;height:420px;border-radius:50%%;filter:blur(80px);opacity:.45;z-index:-1;animation:float 14s ease-in-out infinite}
body::before{background:var(--a);top:-120px;left:-100px}
body::after{background:var(--b);bottom:-160px;right:-120px;opacity:.28;animation-delay:-7s}
@keyframes float{50%%{transform:translate(60px,40px) scale(1.15)}}
form{position:relative;background:rgba(19,28,46,.72);-webkit-backdrop-filter:blur(20px) saturate(1.4);backdrop-filter:blur(20px) saturate(1.4);
  border:1px solid rgba(255,255,255,.08);padding:30px 28px 24px;border-radius:20px;width:min(360px,92vw);display:grid;gap:14px;
  box-shadow:0 30px 60px -20px rgba(0,0,0,.6);animation:in .6s cubic-bezier(.2,.8,.2,1) backwards}
form::before{content:"";position:absolute;top:0;left:26px;right:26px;height:3px;border-radius:0 0 3px 3px;background:linear-gradient(90deg,var(--b),var(--a),var(--b));background-size:200%% 100%%;animation:sheen 5s linear infinite}
@keyframes in{from{opacity:0;transform:translateY(18px) scale(.97)}}
@keyframes sheen{to{background-position:-200%% 0}}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;color:#12264f;background:linear-gradient(135deg,#ffe24a,#ffb800);box-shadow:0 6px 18px rgba(255,190,0,.35);animation:bob 3.2s ease-in-out infinite}
.logo svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
@keyframes bob{50%%{transform:translateY(-3px)}}
h1{font-size:20px;margin:0;letter-spacing:-.01em;background:linear-gradient(90deg,#fff,#9cc2ff);-webkit-background-clip:text;background-clip:text;color:transparent}
input,button{font:inherit;padding:12px 14px;border-radius:12px;border:1.5px solid #2c3a57;background:rgba(11,18,32,.6);color:inherit;transition:border-color .2s,box-shadow .25s,transform .2s cubic-bezier(.34,1.56,.64,1),filter .15s}
input::placeholder{color:#7d8ba6}
input:focus{outline:0;border-color:#7fb0ff;box-shadow:0 0 0 4px rgba(127,176,255,.18)}
form>button{background:linear-gradient(135deg,#0a4cad,#2f6fe0 60%%,#3d8bff);border-color:transparent;font-weight:600;cursor:pointer;box-shadow:0 10px 24px -10px rgba(47,111,224,.8)}
form>button:hover{transform:translateY(-1px);filter:brightness(1.08)}
form>button:active{transform:scale(.97)}
p{margin:0;color:#fca5a5;font-size:14px;padding:9px 12px;border-radius:10px;background:rgba(217,45,32,.12);border:1px solid rgba(255,107,94,.25);animation:shake .4s}
@keyframes shake{25%%{transform:translateX(-6px)}50%%{transform:translateX(5px)}75%%{transform:translateX(-3px)}}
small{color:#94a3b8;text-align:center}
.lg{display:flex;gap:2px;padding:3px;border-radius:10px;background:rgba(11,18,32,.6)}
.lg button{padding:4px 9px;font-size:12px;font-weight:600;background:transparent;border:0;border-radius:8px;color:#94a3b8;cursor:pointer}
.lg button:hover{color:#e8edf7}
.lg button[aria-pressed=true]{background:#2a3a5c;color:#fff}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
</style>
<form method=post action=/login>
<div class=top><div class=brand><span class=logo aria-hidden=true><svg viewBox="0 0 24 24"><path d="M12 21s-7-6.1-7-11.5a7 7 0 0 1 14 0C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg></span><h1>Coppel Map</h1></div><div class=lg role=group aria-label="Idioma · Language · 语言"><button type=button data-l=es>ES</button><button type=button data-l=en>EN</button><button type=button data-l=zh>中文</button></div></div>
<input name=user placeholder="Usuario" data-t=user autocomplete=username required>
<input name=code inputmode=numeric pattern="[0-9]{6}" maxlength=6 placeholder="Código de 6 dígitos" data-t=code autocomplete=one-time-code required>
%s<button data-t=enter>Entrar</button>
<small data-t=hint>El código lo da tu app Authenticator.</small>
</form>
<script>
// misma preferencia que el mapa (coppel-map:lang), para que el idioma se conserve al entrar
const T={es:{loc:"es-MX",user:"Usuario",code:"Código de 6 dígitos",enter:"Entrar",hint:"El código lo da tu app Authenticator.",err:"Usuario o código incorrectos."},
en:{loc:"en-US",user:"Username",code:"6-digit code",enter:"Sign in",hint:"Get the code from your Authenticator app.",err:"Wrong username or code."},
zh:{loc:"zh-CN",user:"用户名",code:"6 位验证码",enter:"登录",hint:"验证码来自你的 Authenticator 应用。",err:"用户名或验证码错误。"}};
function setL(l){
  if(!T[l])l="es";try{localStorage.setItem("coppel-map:lang",l)}catch(e){}
  document.documentElement.lang=T[l].loc;
  document.querySelectorAll("[data-t]").forEach(e=>{const v=T[l][e.dataset.t];if(e.tagName==="INPUT")e.placeholder=v;else e.textContent=v});
  document.querySelectorAll("[data-l]").forEach(b=>b.setAttribute("aria-pressed",b.dataset.l===l));
}
document.querySelector(".lg").addEventListener("click",e=>{const b=e.target.closest("[data-l]");if(b)setL(b.dataset.l)});
let saved="es";try{saved=localStorage.getItem("coppel-map:lang")||"es"}catch(e){}
setL(saved);
</script>"""


class Auth(SimpleHTTPRequestHandler):
    def authed(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                with lock:
                    return sessions.get(v, 0) > time.time()
        return False

    def page(self, status, err=""):
        body = (PAGE % (f"<p data-t=err>{html.escape(err)}</p>" if err else "")).encode()
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
        if p == "/api/ventas":
            if not self.authed():
                return self.page(401)
            return self.json_out(ventas())
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
