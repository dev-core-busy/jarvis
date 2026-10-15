#!/usr/bin/env python3
"""Waechter: der WebDAV-Mount haengt an a2wsgi, nicht am abgekuendigten Starlette-Modul.

DER ANLASS (2026-10-01): Nach dem Sprung auf Starlette 1.7.0 (CVE-2026-48710,
BadHost) meldete der Dienst beim Start

    StarletteDeprecationWarning: starlette.middleware.wsgi is deprecated and will
    be removed in a future release. Please refer to
    https://github.com/abersheeran/a2wsgi as a replacement.

Eine Deprecation-Warnung ist ein Termin, kein Hinweis: beim naechsten Sprung waere
der WebDAV-Mount mit ImportError gestorben – und zwar im breiten ``except`` des
Startup-Hooks, also mit einer Zeile im Journal und ohne weitere Folge. Der Mount
benutzt jetzt a2wsgi.

GEMESSEN WIRD NICHT NUR DER IMPORT. Drei Zusagen haengen daran:

  1. ``starlette.middleware.wsgi`` ist im Backend NIRGENDS mehr importiert
     (am Syntaxbaum, exakt – ein Teilstring waere keine Identitaet).
  2. ``a2wsgi`` ist deklariert. Der Import steht in einem ``try``/``except
     ImportError``; genau dort stand 2026-08-12 auch pypdf, das auf ECHT
     gefehlt hat (siehe tests/test_dependency_declarations.py).
  3. Das VERHALTEN bleibt: 503 wenn abgeschaltet, Weiterleitung wenn an, und der
     enabled-Status wird bei JEDEM Request gelesen.

Dazu die Falle, die a2wsgi mitbringt und die Starlette nicht hatte: a2wsgi legt im
Konstruktor einen EIGENEN ThreadPoolExecutor an. Eine Bruecke je Umschaltvorgang
zu bauen (so lief der alte Cache) wuerde bei jedem Aus-/Einschalten von WebDAV
einen Threadpool liegen lassen. Deshalb wird gezaehlt: ueber einen ganzen
Aus-/Ein-Zyklus darf die Bruecke GENAU EINMAL gebaut werden, waehrend die
WsgiDAV-App darunter neu entstehen muss (sonst griffe ein geaendertes Kennwort
nie).

Die Attrappe bildet die echte Form nach (``WSGIMiddleware(app, workers=10,
send_queue_size=10)`` mit ``.executor``); ist a2wsgi installiert, wird die Form
gegen das echte Paket geprueft und ein echter Durchlauf gemessen – sonst waere die
Attrappe nur die Annahme ihres Autors.

Der Test braucht Starlette NICHT: der Abschalt-Zweig antwortet mit ASGI-Nachrichten
statt mit starlette.responses.Response. Er laeuft damit lokal wie auf jedem Server.

Lauf:  python3 tests/test_webdav_a2wsgi.py [WURZEL]
       (WURZEL nur fuer die Gegenprobe – Vorgabe ist das Repo selbst)
"""
import asyncio
import ast
import importlib.util
import inspect
import re
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WURZEL = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent

VERBOTEN = "starlette.middleware.wsgi"
ERSATZ = "a2wsgi"

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def abbruch(grund):
    print(f"\n\033[31mABBRUCH (Exit 2): {grund}\033[0m")
    print("  'konnte nicht laufen' ist nicht 'bestanden'.")
    sys.exit(2)


# ── Erkenner (am Syntaxbaum, nicht am Text) ──────────────────────────────────

def importierte_module(quelle: str) -> set:
    """Alle importierten Modulpfade einer Datei – voll qualifiziert.

    Bewusst der ganze Pfad und nicht nur der oberste Name: gesucht ist
    ``starlette.middleware.wsgi``, und ``starlette`` selbst bleibt erlaubt.
    """
    raus = set()
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for a in knoten.names:
                raus.add(a.name)
        elif isinstance(knoten, ast.ImportFrom):
            if knoten.level or not knoten.module:
                continue
            raus.add(knoten.module)
    return raus


def nennt_modul(quelle: str, modul: str) -> bool:
    """Wird ``modul`` (oder etwas darunter) importiert?"""
    for name in importierte_module(quelle):
        if name == modul or name.startswith(modul + "."):
            return True
    return False


def holt_namen_aus(quelle: str, modul: str, name: str) -> bool:
    """Steht ein ``from <modul> import <name>`` in der Datei?"""
    for knoten in ast.walk(ast.parse(quelle)):
        if isinstance(knoten, ast.ImportFrom) and not knoten.level:
            if knoten.module == modul and any(a.name == name for a in knoten.names):
                return True
    return False


# ── Attrappe der a2wsgi-Bruecke ──────────────────────────────────────────────

class StubBruecke:
    """Attrappe von a2wsgi.WSGIMiddleware – gleiche Signatur, gleiche Rollen.

    Sie fuehrt die WSGI-App WIRKLICH aus (sonst waere die Weiterleitung nur
    behauptet) und legt wie das Original einen eigenen ThreadPoolExecutor an,
    damit sich das Zaehlen der Bruecken an derselben Eigenschaft aufhaengt wie
    die Leck-Gefahr.
    """

    gebaut: list = []

    def __init__(self, app, workers: int = 10, send_queue_size: int = 10) -> None:
        self.app = app
        self.send_queue_size = send_queue_size
        self.executor = ThreadPoolExecutor(thread_name_prefix="WSGI", max_workers=workers)
        StubBruecke.gebaut.append(self)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        kopf = {}

        def start_response(status, headers, exc_info=None):
            kopf["status"] = int(status.split(" ", 1)[0])
            kopf["headers"] = list(headers)

        wurzel = scope.get("root_path", "")
        pfad = scope["path"]
        environ = {
            "REQUEST_METHOD": scope["method"],
            "SCRIPT_NAME": wurzel,
            "PATH_INFO": pfad[len(wurzel):] if pfad.startswith(wurzel) else pfad,
            "QUERY_STRING": scope["query_string"].decode("ascii"),
            "SERVER_PROTOCOL": "HTTP/1.1",
            "SERVER_NAME": "test",
            "SERVER_PORT": "443",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": scope.get("scheme", "https"),
            "wsgi.input": None,
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": True,
            "wsgi.multiprocess": True,
            "wsgi.run_once": False,
        }
        teile = list(self.app(environ, start_response))
        await send({"type": "http.response.start", "status": kopf["status"],
                    "headers": [(k.lower().encode("latin-1"), v.encode("latin-1"))
                                for k, v in kopf["headers"]]})
        await send({"type": "http.response.body", "body": b"".join(teile)})

    @classmethod
    def aufraeumen(cls):
        for b in cls.gebaut:
            b.executor.shutdown(wait=False)
        cls.gebaut = []


# ── ASGI-Treiber ─────────────────────────────────────────────────────────────

def scope_http(pfad="/webdav/", method="GET"):
    return {"type": "http", "method": method, "path": pfad, "root_path": "/webdav",
            "query_string": b"", "http_version": "1.1", "headers": [],
            "scheme": "https", "server": ("test", 443), "client": ("test", 1)}


async def _fahre(dav, scope):
    gesendet = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(nachricht):
        gesendet.append(nachricht)

    await dav(scope, receive, send)
    return gesendet


def anfrage(dav, pfad="/webdav/", method="GET"):
    """(status, rumpf, kopfzeilen) – kopfzeilen als dict aus bytes."""
    gesendet = asyncio.run(_fahre(dav, scope_http(pfad, method)))
    start = [m for m in gesendet if m.get("type") == "http.response.start"]
    rumpf = b"".join(m.get("body", b"") for m in gesendet
                     if m.get("type") == "http.response.body")
    if not start:
        return None, rumpf, {}
    kopf = {k.lower(): v for k, v in start[0].get("headers", [])}
    return start[0].get("status"), rumpf, kopf


def anfrage_roh(dav, scope):
    return asyncio.run(_fahre(dav, scope))


# ── Modul laden (backend.config NUR als Attrappe) ────────────────────────────

class _CfgAttrappe:
    """Nur die eine Auskunft, die backend/webdav.py braucht.

    Der ECHTE backend.config schreibt beim Import die Live-settings.json zurueck –
    er hat in einem Test nichts zu suchen.
    """

    def __init__(self):
        self.states = {}

    def get_skill_states(self):
        return self.states


def lade_webdav(wurzel: Path):
    pfad = wurzel / "backend" / "webdav.py"
    paket = types.ModuleType("backend")
    paket.__path__ = [str(pfad.parent)]
    cfg_modul = types.ModuleType("backend.config")
    cfg_modul.config = _CfgAttrappe()
    sys.modules["backend"] = paket
    sys.modules["backend.config"] = cfg_modul
    spec = importlib.util.spec_from_file_location("backend.webdav", pfad)
    modul = importlib.util.module_from_spec(spec)
    sys.modules["backend.webdav"] = modul
    spec.loader.exec_module(modul)
    return modul


class AppAttrappe:
    """Nur das, was mount_webdav anfasst: mount() und state."""

    def __init__(self):
        self.mounts = []
        self.state = types.SimpleNamespace()

    def mount(self, pfad, app):
        self.mounts.append((pfad, app))


def wsgi_app(text: str):
    """Minimale WSGI-App, die ihren Text und PATH_INFO zurueckgibt."""

    def app(environ, start_response):
        roh = f"{text}|{environ.get('SCRIPT_NAME')}|{environ.get('PATH_INFO')}".encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/plain"),
                                  ("Content-Length", str(len(roh)))])
        return [roh]

    return app


# ══ 0) Grundlage – ohne die ist unten alles trivial wahr ═════════════════════
abschnitt("0) Grundlage")

MAIN = WURZEL / "backend" / "main.py"
DAV = WURZEL / "backend" / "webdav.py"
REQ = WURZEL / "requirements.txt"

for p in (MAIN, DAV, REQ):
    if not p.exists():
        abbruch(f"{p} fehlt")

quellen = {}
for datei in sorted(WURZEL.glob("backend/**/*.py")) + sorted(WURZEL.glob("skills/**/*.py")):
    if "__pycache__" in datei.parts or "venv" in datei.parts:
        continue
    try:
        quellen[datei] = datei.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue

if MAIN not in quellen or DAV not in quellen:
    abbruch("backend/main.py bzw. backend/webdav.py nicht eingelesen – "
            "der Durchlauf unten wuerde ins Leere greifen")

# Positivkontrolle des Erkenners: er MUSS einen gebauten Verstoss finden. Ohne
# das koennte er blind sein, und jede Pruefung darunter waere trivial gruen.
PROBE_VERBOTEN = "from starlette.middleware.wsgi import WSGIMiddleware\n"
PROBE_ERSATZ = "from a2wsgi import WSGIMiddleware\n"
if not nennt_modul(PROBE_VERBOTEN, VERBOTEN):
    abbruch("der Erkenner findet den gebauten Verstoss nicht – Messwerkzeug kaputt")
if nennt_modul(PROBE_ERSATZ, VERBOTEN):
    abbruch("der Erkenner meldet a2wsgi als Starlette-Import – Messwerkzeug kaputt")
if not holt_namen_aus(PROBE_ERSATZ, ERSATZ, "WSGIMiddleware"):
    abbruch("der Erkenner findet den a2wsgi-Import nicht – Messwerkzeug kaputt")
if nennt_modul("import starlette\nfrom starlette.responses import Response\n", VERBOTEN):
    abbruch("der Erkenner verwechselt starlette mit starlette.middleware.wsgi")

pruefe(f"{len(quellen)} Python-Dateien eingelesen (inkl. main.py und webdav.py)",
       len(quellen) >= 2)
pruefe("der Erkenner findet gebaute Verstoesse (Positivkontrolle)", True)

try:
    webdav = lade_webdav(WURZEL)
except Exception as e:
    abbruch(f"backend/webdav.py laedt nicht: {e!r}")

for name in ("DynamicWebDAV", "mount_webdav", "is_webdav_enabled", "get_webdav_app"):
    if not hasattr(webdav, name):
        abbruch(f"backend/webdav.py bringt kein '{name}' mit")
pruefe("backend/webdav.py laedt mit backend.config-Attrappe und bringt "
       "DynamicWebDAV + mount_webdav mit", True)

# ══ 1) Das abgekuendigte Modul ist weg ═══════════════════════════════════════
abschnitt("1) starlette.middleware.wsgi ist nirgends mehr importiert")

treffer = []
for datei, quelle in quellen.items():
    try:
        if nennt_modul(quelle, VERBOTEN):
            treffer.append(datei.relative_to(WURZEL).as_posix())
    except SyntaxError:
        continue
pruefe(f"kein Import von {VERBOTEN} unter backend/ und skills/", not treffer,
       "noch in: " + ", ".join(treffer) if treffer else "")

# ══ 2) Der Ersatz ist der benutzte Weg – und deklariert ══════════════════════
abschnitt("2) a2wsgi ist der benutzte Weg und deklariert")

pruefe("backend/webdav.py holt WSGIMiddleware aus a2wsgi",
       holt_namen_aus(quellen[DAV], ERSATZ, "WSGIMiddleware"))


def deklariert(req_text: str, name: str) -> bool:
    """PEP-503-normalisierter Vergleich – 'sse-starlette' ist nicht 'starlette'."""
    gesucht = re.sub(r"[-_.]+", "-", name).lower()
    for zeile in req_text.splitlines():
        z = zeile.split("#")[0].strip()
        if not z or z.startswith("-"):
            continue
        verteilung = re.sub(r"[-_.]+", "-", re.split(r"[<>=!\[; ]", z)[0]).lower()
        if verteilung == gesucht:
            return True
    return False


req_text = REQ.read_text(encoding="utf-8")
pruefe("a2wsgi steht in requirements.txt", deklariert(req_text, ERSATZ),
       "Der Import steht in try/except ImportError – das entschuldigt nichts "
       "(tests/test_dependency_declarations.py)")
pruefe("Gegenkontrolle: der Deklarations-Leser erfindet nichts",
       not deklariert(req_text, "a2wsgi-gibt-es-nicht"))

# ══ 3) Verhalten – mit Attrappe in echter Form ═══════════════════════════════
abschnitt("3) Verhalten: 503 wenn aus, Weiterleitung wenn an")

echtes_a2wsgi = None
try:
    import a2wsgi as echtes_a2wsgi  # noqa: F401  (nur fuer Abschnitt 4)
except ImportError:
    pass

stub_modul = types.ModuleType("a2wsgi")
stub_modul.WSGIMiddleware = StubBruecke
sys.modules["a2wsgi"] = stub_modul

zustand = {"an": True, "apps": [], "gefragt": 0}


def _enabled():
    zustand["gefragt"] += 1
    return zustand["an"]


def _get_app():
    app = wsgi_app(f"dav{len(zustand['apps'])}")
    zustand["apps"].append(app)
    return app


webdav.is_webdav_enabled = _enabled
webdav.get_webdav_app = _get_app
StubBruecke.gebaut = []

dav = webdav.DynamicWebDAV()

# Positivkontrolle ZUERST: laeuft die Weiterleitung ueberhaupt? Ohne sie waere
# "503 wenn abgeschaltet" erfuellt, weil gar nichts funktioniert.
status, rumpf, kopf = anfrage(dav, "/webdav/unterordner/")
if status != 200 or b"dav0" not in rumpf:
    detail = (f"aktiviertes WebDAV antwortet {status} / {rumpf[:120]!r} "
              f"statt 200 mit dem Rumpf der WSGI-App")
    if fehler:
        # Oben steht schon ein Befund – dann ist das hier die FOLGE davon und
        # kein Abbruchgrund. Ein Exit 2 wuerde den Befund verschlucken.
        pruefe("aktiviert: 200 und der Rumpf kommt aus der WsgiDAV-App "
               "(Positivkontrolle)", False, detail)
        print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
        print("   Abschnitt 3 abgebrochen – die Befunde oben erklaeren es.")
        sys.exit(1)
    abbruch("Positivkontrolle fehlgeschlagen: " + detail)
pruefe("aktiviert: 200 und der Rumpf kommt aus der WsgiDAV-App "
       "(Positivkontrolle)", True)
pruefe("SCRIPT_NAME/PATH_INFO werden aus root_path und path gebildet "
       "(/webdav + /unterordner/)", rumpf.endswith(b"|/webdav|/unterordner/"),
       rumpf.decode("utf-8", "replace"))

status2, rumpf2, _ = anfrage(dav, "/webdav/")
pruefe("zweiter Request: dieselbe WsgiDAV-App (Cache greift)",
       status2 == 200 and b"dav0" in rumpf2 and len(zustand["apps"]) == 1,
       f"{len(zustand['apps'])} App(s) gebaut")
pruefe("eine Bruecke fuer beide Requests", len(StubBruecke.gebaut) == 1,
       f"{len(StubBruecke.gebaut)} Bruecken")

# Abschalten: derselbe Mount, nur der Schalter wandert
zustand["an"] = False
status, rumpf, kopf = anfrage(dav)
pruefe("abgeschaltet: Status 503", status == 503, str(status))
pruefe("abgeschaltet: Rumpf nennt den Grund", rumpf == "WebDAV deaktiviert".encode("utf-8"),
       repr(rumpf))
pruefe("abgeschaltet: Content-Length passt zum Rumpf",
       kopf.get(b"content-length") == str(len(rumpf)).encode("latin-1"),
       repr(kopf))

# Wieder an: die WsgiDAV-App MUSS neu entstehen (geaendertes Kennwort), die
# Bruecke darueber NICHT (sonst bleibt je Zyklus ein Threadpool liegen).
zustand["an"] = True
status, rumpf, _ = anfrage(dav)
pruefe("wieder an: 200 und eine NEUE WsgiDAV-App",
       status == 200 and b"dav1" in rumpf and len(zustand["apps"]) == 2,
       f"status={status} rumpf={rumpf[:80]!r} apps={len(zustand['apps'])}")
pruefe("ueber den ganzen Aus-/Ein-Zyklus: GENAU EINE Bruecke (kein Threadpool-Leck)",
       len(StubBruecke.gebaut) == 1, f"{len(StubBruecke.gebaut)} Bruecken gebaut")

# Der Schalter wird je Request gelesen – nicht einmal beim Mount.
zustand["an"] = False
status_aus, _, _ = anfrage(dav)
zustand["an"] = True
status_an, _, _ = anfrage(dav)
pruefe("der enabled-Status wird bei JEDEM Request gelesen",
       status_aus == 503 and status_an == 200, f"{status_aus} / {status_an}")

# WebDAV an, aber die App laesst sich nicht bauen (z. B. wsgidav fehlt)
webdav.get_webdav_app = lambda: None
dav2 = webdav.DynamicWebDAV()
status, rumpf, _ = anfrage(dav2)
pruefe("an, aber get_webdav_app() -> None: 503 mit eigener Begruendung",
       status == 503 and rumpf == "WebDAV konnte nicht gestartet werden".encode("utf-8"),
       f"{status} / {rumpf!r}")

# Nicht-HTTP darf nichts beantworten (Websocket/Lifespan laufen nicht ueber
# WebDAV). Gemessen wird nicht nur "keine Antwort" – das waere auch wahr, wenn der
# Scope bis zur Bruecke durchliefe und DIE ihn verwirft. Gemessen wird, dass der
# Rueckweg VOR allem anderen liegt: der Schalter wird gar nicht erst gelesen.
for typ in ("websocket", "lifespan"):
    vor = zustand["gefragt"]
    gesendet = anfrage_roh(dav, {"type": typ, "path": "/webdav/"})
    pruefe(f"Scope '{typ}': keine Antwort, und der Schalter wird nicht gelesen",
           gesendet == [] and zustand["gefragt"] == vor,
           f"gesendet={gesendet!r}, Schalter {zustand['gefragt'] - vor}x gelesen")

# Die Weiche selbst: sie haengt UNTER der Bruecke und wird dort aus einem
# Threadpool gerufen. Steht ihr Ziel auf None (abgeschaltet zwischen Pruefung und
# Weiterleitung), muss sie fail-closed antworten statt mit TypeError zu sterben.
weiche = webdav._Weiche()
kopf_wsgi = {}


def _sr(status, headers, exc_info=None):
    kopf_wsgi["status"] = status
    kopf_wsgi["headers"] = list(headers)


weiche.ziel = wsgi_app("ziel")
teile = b"".join(weiche({"SCRIPT_NAME": "/webdav", "PATH_INFO": "/"}, _sr))
pruefe("_Weiche mit Ziel: leitet weiter (Positivkontrolle)",
       kopf_wsgi.get("status", "").startswith("200") and b"ziel" in teile,
       f"{kopf_wsgi} / {teile!r}")
weiche.ziel = None
teile = b"".join(weiche({"SCRIPT_NAME": "/webdav", "PATH_INFO": "/"}, _sr))
pruefe("_Weiche ohne Ziel: fail-closed 503 statt TypeError im Threadpool",
       kopf_wsgi.get("status", "").startswith("503") and b"deaktiviert" in teile,
       f"{kopf_wsgi} / {teile!r}")

# mount_webdav verdrahtet den Invalidierer
webdav.get_webdav_app = _get_app
app_attr = AppAttrappe()
dav3 = webdav.mount_webdav(app_attr)
pruefe("mount_webdav haengt /webdav ein",
       [p for p, _ in app_attr.mounts] == ["/webdav"], repr(app_attr.mounts))
pruefe("mount_webdav legt invalidate_dav_cache auf app.state",
       callable(getattr(app_attr.state, "invalidate_dav_cache", None)))

vorher = len(zustand["apps"])
anfrage(dav3)
bruecken_vorher = len(StubBruecke.gebaut)
app_attr.state.invalidate_dav_cache()
status, rumpf, _ = anfrage(dav3)
pruefe("invalidate_dav_cache(): naechster Request baut die WsgiDAV-App neu",
       status == 200 and len(zustand["apps"]) == vorher + 2,
       f"status={status} apps={len(zustand['apps'])} (vorher {vorher})")
pruefe("invalidate_dav_cache(): die Bruecke bleibt stehen",
       len(StubBruecke.gebaut) == bruecken_vorher,
       f"{len(StubBruecke.gebaut)} statt {bruecken_vorher}")

# ══ 4) Bildet die Attrappe die ECHTE Form nach? ══════════════════════════════
abschnitt("4) Abgleich mit dem echten a2wsgi")

if echtes_a2wsgi is None:
    print("   a2wsgi ist hier nicht installiert – der Formabgleich und der echte")
    print("   Durchlauf laufen nur dort, wo das Paket liegt (DEV/ECHT). Die")
    print("   Abschnitte 1-3 sind davon unberuehrt.")
else:
    echt = echtes_a2wsgi.WSGIMiddleware
    sig_echt = inspect.signature(echt.__init__)
    sig_stub = inspect.signature(StubBruecke.__init__)
    pruefe(f"a2wsgi {getattr(echtes_a2wsgi, '__version__', '?')}: Signatur der "
           f"Attrappe stimmt mit dem Original",
           [(p.name, p.default) for p in sig_echt.parameters.values()]
           == [(p.name, p.default) for p in sig_stub.parameters.values()],
           f"echt: {sig_echt}\n      stub: {sig_stub}")

    probe_echt = echt(wsgi_app("echt"))
    pruefe("das Original traegt einen eigenen ThreadPoolExecutor "
           "(Grund fuer die Einmal-Bruecke)",
           isinstance(getattr(probe_echt, "executor", None), ThreadPoolExecutor),
           repr(getattr(probe_echt, "executor", None)))

    sys.modules["a2wsgi"] = echtes_a2wsgi
    webdav.is_webdav_enabled = lambda: True
    webdav.get_webdav_app = lambda: wsgi_app("echt")
    dav_echt = webdav.DynamicWebDAV()
    status, rumpf, _ = anfrage(dav_echt, "/webdav/unterordner/")
    pruefe("echter a2wsgi-Durchlauf: 200 und der Rumpf der WSGI-App",
           status == 200 and b"echt" in rumpf, f"{status} / {rumpf[:120]!r}")
    pruefe("echter a2wsgi-Durchlauf: SCRIPT_NAME=/webdav, PATH_INFO=/unterordner/",
           rumpf.endswith(b"|/webdav|/unterordner/"), rumpf.decode("utf-8", "replace"))
    webdav.is_webdav_enabled = lambda: False
    status, rumpf, _ = anfrage(dav_echt)
    pruefe("echter a2wsgi-Durchlauf: abgeschaltet bleibt 503",
           status == 503 and rumpf == "WebDAV deaktiviert".encode("utf-8"),
           f"{status} / {rumpf!r}")
    probe_echt.executor.shutdown(wait=False)
    getattr(dav_echt, "_bruecke").executor.shutdown(wait=False)

StubBruecke.aufraeumen()

print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
sys.exit(1 if fehler else 0)
