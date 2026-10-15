#!/usr/bin/env python3
"""Probe auf DEV: der WebDAV-Mount traegt ueber a2wsgi – und die Warnung ist weg.

LAEUFT AUF DEM SERVER (DEV), nicht lokal: sie misst den laufenden Dienst ueber
HTTPS und liest dessen Journal.

WARUM UEBER DEN ECHTEN WEG. Der a2wsgi-Tausch (2026-10-01) sieht nach einem
Importwechsel aus, aendert aber die Bauform der WSGI-Eingabe: Starlette hat den
Rumpf vorher komplett in einen BytesIO gelesen, a2wsgi STREAMT ihn aus einem
Threadpool heraus (``asyncio.run_coroutine_threadsafe``). Ein GET haette das nie
gezeigt. Gemessen werden deshalb PROPFIND und PUT – die beiden Methoden, bei denen
WsgiDAV ``wsgi.input`` wirklich liest.

Der vorgefundene Zustand wird wiederhergestellt: ob WebDAV an oder aus ist,
entscheidet der Betreiber, nicht diese Probe. Ein- und ausgeschaltet wird ueber
``POST /api/knowledge/webdav/config`` – also den Weg, den die Oberflaeche geht,
samt der Cache-Invalidierung, die daran haengt.

Die Probedatei traegt eine Endung, die NICHT indizierbar ist (gemessen gegen
``knowledge.alle_endungen()``), damit sie nicht in der Wissensbasis landet, und
wird per DELETE ueber WebDAV wieder abgeraeumt.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

Lauf (auf DEV):  /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_webdav_a2wsgi_dev.py
"""
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/opt/jarvis")
os.chdir("/opt/jarvis")

BASIS = "https://127.0.0.1"
KTX = ssl.create_default_context()
KTX.check_hostname = False
KTX.verify_mode = ssl.CERT_NONE

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
    sys.exit(2)


def ruf(pfad, method="GET", token=None, daten=None, basic=None, kopf=None):
    """(status, rumpf-bytes, kopfzeilen-dict) – wirft nie."""
    url = BASIS + pfad
    rumpf = None
    kopfzeilen = dict(kopf or {})
    if daten is not None:
        rumpf = daten if isinstance(daten, bytes) else json.dumps(daten).encode("utf-8")
        kopfzeilen.setdefault("Content-Type", "application/json")
    if token:
        # So liest es der Endpunkt (Authorization: Bearer), nicht als Cookie.
        kopfzeilen["Authorization"] = f"Bearer {token}"
    if basic:
        roh = base64.b64encode(f"{basic[0]}:{basic[1]}".encode("utf-8")).decode("ascii")
        kopfzeilen["Authorization"] = f"Basic {roh}"
    anfrage = urllib.request.Request(url, data=rumpf, headers=kopfzeilen, method=method)
    try:
        with urllib.request.urlopen(anfrage, context=KTX, timeout=30) as a:
            return a.status, a.read(), dict(a.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return None, str(e).encode(), {}


# ══ 0) Grundlage ═════════════════════════════════════════════════════════════
abschnitt("0) Grundlage – laeuft der Dienst, und ist a2wsgi ueberhaupt da?")

status, _, _ = ruf("/api/health")
if status != 200:
    abbruch(f"/api/health antwortet {status} – der Dienst laeuft nicht")
pruefe("Dienst antwortet auf /api/health", True)

try:
    import a2wsgi
except ImportError as e:
    abbruch(f"a2wsgi ist auf diesem Server nicht installiert ({e}) – "
            f"'/opt/jarvis/venv/bin/pip install a2wsgi'")
pruefe(f"a2wsgi {a2wsgi.__version__} installiert", True)

from backend.tools.knowledge import alle_endungen  # noqa: E402

ENDUNG = ".a2wsgiprobe"
if ENDUNG.lstrip(".") in {e.lstrip(".").lower() for e in alle_endungen()}:
    abbruch(f"{ENDUNG} ist indizierbar – die Probedatei wuerde in der "
            f"Wissensbasis landen. Andere Endung waehlen.")
pruefe(f"die Endung der Probedatei ({ENDUNG}) ist NICHT indizierbar", True)

from backend import main as M  # noqa: E402

token = M.generate_token("jarvis")
if not token:
    abbruch("kein Sitzungstoken fuer den lokalen Administrator")
pruefe("Sitzungstoken erzeugt (der Weg, den /api/login nach der Anmeldung geht)", True)

status, roh, _ = ruf("/api/knowledge/webdav/status", token=token)
if status != 200:
    abbruch(f"/api/knowledge/webdav/status antwortet {status}: {roh[:200]!r}")
zustand = json.loads(roh)
VORGEFUNDEN = bool(zustand.get("enabled"))
NUTZER = zustand.get("username") or "jarvis"
KENNWORT = zustand.get("password") or "jarvis"
print(f"   vorgefundener Zustand: WebDAV ist "
      f"{'AN' if VORGEFUNDEN else 'AUS'} – wird am Ende wiederhergestellt")


def schalte(an: bool) -> bool:
    """Ueber den echten Endpunkt schalten (samt Cache-Invalidierung)."""
    s, r, _ = ruf("/api/knowledge/webdav/config", "POST", token=token,
                  daten={"enabled": an})
    return s == 200 and json.loads(r).get("enabled") is an


probedatei = f"probe-{uuid.uuid4().hex[:8]}{ENDUNG}"
geschrieben = False
try:
    # ══ 1) Abgeschaltet: 503 ══════════════════════════════════════════════════
    abschnitt("1) WebDAV abgeschaltet -> 503")
    if not schalte(False):
        abbruch("WebDAV liess sich nicht abschalten")
    status, rumpf, _ = ruf("/webdav/")
    pruefe("GET /webdav/ -> 503", status == 503, str(status))
    pruefe("… und der Rumpf nennt den Grund",
           rumpf == "WebDAV deaktiviert".encode("utf-8"), repr(rumpf[:120]))

    # ══ 2) Eingeschaltet: der Mount traegt ════════════════════════════════════
    abschnitt("2) WebDAV eingeschaltet -> die Bruecke traegt")
    if not schalte(True):
        abbruch("WebDAV liess sich nicht einschalten")

    # Positivkontrolle ZUERST: ohne eine erreichbare Freigabe waere alles
    # darunter trivial wahr.
    status, rumpf, kopf = ruf("/webdav/", basic=(NUTZER, KENNWORT),
                              kopf={"Accept": "text/html"})
    if status != 200:
        abbruch(f"Positivkontrolle fehlgeschlagen: GET /webdav/ mit Anmeldung "
                f"antwortet {status}: {rumpf[:200]!r}")
    pruefe("GET /webdav/ mit Anmeldung -> 200 (Positivkontrolle)", True)
    pruefe("… und es ist der gestylte Jarvis-Browser, nicht die WsgiDAV-Seite",
           b"Jarvis WebDAV" in rumpf and b"WsgiDAV" not in rumpf,
           rumpf[:200].decode("utf-8", "replace"))

    status, rumpf, _ = ruf("/webdav/")
    pruefe("GET /webdav/ OHNE Anmeldung -> 401", status == 401, str(status))

    # ── PROPFIND: der echte WebDAV-Weg, mit Rumpf (liest wsgi.input) ─────────
    propfind = (b'<?xml version="1.0" encoding="utf-8"?>'
                b'<D:propfind xmlns:D="DAV:"><D:prop>'
                b'<D:displayname/><D:resourcetype/></D:prop></D:propfind>')
    status, rumpf, _ = ruf("/webdav/", "PROPFIND", basic=(NUTZER, KENNWORT),
                           daten=propfind,
                           kopf={"Depth": "1", "Content-Type": "application/xml"})
    pruefe("PROPFIND /webdav/ -> 207 Multi-Status", status == 207, str(status))
    pruefe("… die Antwort ist eine DAV-Mehrfachantwort",
           b"multistatus" in rumpf.lower(), rumpf[:200].decode("utf-8", "replace"))

    # ── PUT/GET/DELETE: genau der Pfad, der sich bei a2wsgi anders verhaelt ──
    abschnitt("3) Schreibzugriff – a2wsgi streamt wsgi.input (Starlette pufferte)")
    inhalt = (f"a2wsgi-Probe {uuid.uuid4()}\n" * 40).encode("utf-8")
    status, rumpf, _ = ruf(f"/webdav/{probedatei}", "PUT", basic=(NUTZER, KENNWORT),
                           daten=inhalt,
                           kopf={"Content-Type": "application/octet-stream"})
    geschrieben = status in (200, 201, 204)
    pruefe(f"PUT /webdav/{probedatei} ({len(inhalt)} Bytes) -> 201/204",
           status in (201, 204), f"{status}: {rumpf[:160]!r}")

    status, zurueck, _ = ruf(f"/webdav/{probedatei}", basic=(NUTZER, KENNWORT))
    pruefe("GET derselben Datei -> 200", status == 200, str(status))
    pruefe("⚠ der Rumpf ist BYTE-GLEICH mit dem geschriebenen "
           f"({len(inhalt)} Bytes)", zurueck == inhalt,
           f"zurueck {len(zurueck)} Bytes")

    status, _, _ = ruf(f"/webdav/{probedatei}", "DELETE", basic=(NUTZER, KENNWORT))
    pruefe("DELETE derselben Datei -> 204", status in (200, 204), str(status))
    if status in (200, 204):
        geschrieben = False
    status, _, _ = ruf(f"/webdav/{probedatei}", basic=(NUTZER, KENNWORT))
    pruefe("… danach ist sie weg (404)", status == 404, str(status))

    # ══ 4) Umschalten wirkt im laufenden Dienst ═══════════════════════════════
    abschnitt("4) Umschalten wirkt ohne Neustart (Cache-Invalidierung)")
    if not schalte(False):
        abbruch("WebDAV liess sich nicht wieder abschalten")
    status, rumpf, _ = ruf("/webdav/", basic=(NUTZER, KENNWORT))
    pruefe("nach dem Abschalten: 503, auch mit gueltiger Anmeldung",
           status == 503 and rumpf == "WebDAV deaktiviert".encode("utf-8"),
           f"{status} / {rumpf[:120]!r}")
    if not schalte(True):
        abbruch("WebDAV liess sich nicht erneut einschalten")
    status, _, _ = ruf("/webdav/", basic=(NUTZER, KENNWORT))
    pruefe("nach dem Wiedereinschalten: wieder 200 (neue WsgiDAV-App)",
           status == 200, str(status))

finally:
    # ── Vorgefundenen Zustand wiederherstellen, komme was will ───────────────
    if geschrieben:
        ruf(f"/webdav/{probedatei}", "DELETE", basic=(NUTZER, KENNWORT))
    if not schalte(VORGEFUNDEN):
        print(f"\n\033[31m⚠ ACHTUNG: WebDAV konnte NICHT auf den vorgefundenen "
              f"Zustand ({'AN' if VORGEFUNDEN else 'AUS'}) zurueckgestellt werden – "
              f"bitte von Hand pruefen.\033[0m")
        fehler += 1
    else:
        s, r, _ = ruf("/api/knowledge/webdav/status", token=token)
        jetzt = bool(json.loads(r).get("enabled")) if s == 200 else None
        pruefe(f"vorgefundener Zustand wiederhergestellt "
               f"(WebDAV {'AN' if VORGEFUNDEN else 'AUS'})", jetzt is VORGEFUNDEN,
               f"jetzt {jetzt}")

# ══ 5) Die Warnung, die der Anlass war ═══════════════════════════════════════
abschnitt("5) Keine StarletteDeprecationWarning mehr beim Start")

p = subprocess.run(["journalctl", "-u", "jarvis.service", "--since", "-30 min",
                    "--no-pager"], capture_output=True, text=True, timeout=60)
journal = p.stdout + p.stderr
# Positivkontrolle: wurde ueberhaupt etwas gelesen? Ein leeres Journal macht
# "keine Warnung darin" trivial wahr.
if "WebDAV-Route registriert" not in journal:
    abbruch("im Journal der letzten 30 Minuten steht kein Start des Dienstes – "
            "'keine Warnung' waere trivial wahr. Erst neu starten, dann messen.")
pruefe("Positivkontrolle: das Journal enthaelt einen Start des Dienstes", True)
pruefe("keine StarletteDeprecationWarning im Journal",
       "StarletteDeprecationWarning" not in journal,
       "\n      ".join(z for z in journal.splitlines()
                       if "StarletteDeprecationWarning" in z)[:400])
pruefe("kein Import von starlette.middleware.wsgi im Journal",
       "starlette.middleware.wsgi" not in journal)

print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
sys.exit(1 if fehler else 0)
