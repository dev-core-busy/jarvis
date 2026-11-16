#!/usr/bin/env python3
"""Waechter: die Confluence-Werkzeuge sagen, was der Zugang WIRKLICH sieht.

Anlass (ECHT 2026-11-13/16, Chat eines Benutzers zum Bereich NXPT):
1. ``confluence_list_spaces`` holte EINE Seite zu 50 aus 489 Bereichen,
   alphabetisch – NXPT stand dahinter, das Modell schloss "kein Zugriff".
2. Es gab keinen Weg, EINEN Bereich gezielt zu pruefen.
3. ``confluence_get_page`` lieferte eine Startseite aus Makros als nacktes
   "400" (ein Makro-Parameter) – gelesen als HTTP 400.
4. Der Verbindungstest zaehlte 25, die Liste 50 – keine Zahl war die wahre.

Ausgefuehrt werden die ECHTEN Werkzeuge und die ECHTE Blaetterlogik des
Clients (``spaces_detailed``, ``space``, ``get_page`` …); ersetzt wird nur
``_request`` durch eine nachgebaute Confluence-API mit derselben Signatur und
Antwortform (``results``, ``start``, ``limit``, ``_links.next``).

Dateien ueber CF_CLIENT / CF_SKILL austauschbar (Gegenprobe).
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(os.environ.get("CF_CLIENT") or ROOT / "backend" / "confluence_client.py")
SKILL = Path(os.environ.get("CF_SKILL") or ROOT / "skills" / "confluence" / "main.py")

_ok = _fail = 0


def check(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (("  -> " + str(detail)[:400]) if detail else ""))


def section(t):
    print("\n== " + t)


# ── Module laden – backend.config NUR als Attrappe: der echte Import schreibt
# die Live-settings.json zurueck. ConfluenceClient() ohne Argument und
# zugang_info() lesen die Skill-Config; ohne Attrappe zoege das den echten
# Import nach (beim Bau dieses Waechters genau so passiert, lokal ohne Folgen).
sys.path.insert(0, str(ROOT))
STUB_CONFIG = types.ModuleType("backend.config")
STUB_CONFIG.config = types.SimpleNamespace(get_skill_states=lambda: {},
                                           get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = STUB_CONFIG
try:
    sys.modules.setdefault("backend", types.ModuleType("backend")).__path__ = [str(ROOT / "backend")]
    spec = importlib.util.spec_from_file_location("backend.confluence_client", CLIENT)
    cc = importlib.util.module_from_spec(spec)
    sys.modules["backend.confluence_client"] = cc
    spec.loader.exec_module(cc)
    spec2 = importlib.util.spec_from_file_location("cf_skill_unter_test", SKILL)
    sk = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(sk)
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: Module nicht ladbar: %r" % e)
    sys.exit(2)
if sys.modules.get("backend.config") is not STUB_CONFIG:
    print("ABBRUCH: backend.config ist nicht die Attrappe – der Test darf die Live-Konfiguration nicht laden")
    sys.exit(2)


class Server:
    """Nachgebaute Confluence-REST-API (Server/DC-Antwortform)."""

    def __init__(self, keys, seiten=None, endlos=False, user_fehler=None):
        self.keys = list(keys)
        self.seiten = seiten or {}
        self.endlos = endlos
        self.user_fehler = user_fehler
        self.aufrufe = []

    def __call__(self, method, path, *, params=None, json=None, headers=None,
                 files=None, data=None, ausnahme=""):
        params = params or {}
        self.aufrufe.append((method, path, dict(params)))
        if method != "GET":
            raise cc.ConfluenceError(0, "nur GET")
        if path == "/rest/api/user/current":
            if self.user_fehler:
                raise cc.ConfluenceError(self.user_fehler, "user")
            return {"displayName": "DP Test", "username": "dp.test"}
        if path == "/rest/api/space":
            start = int(params.get("start", 0))
            lim = min(int(params.get("limit", 25)), 50)   # Server kappt wie echt
            if self.endlos:
                res = [{"key": "E%06d" % (start + i), "name": "Endlos"} for i in range(lim)]
                return {"results": res, "start": start, "limit": lim, "size": lim,
                        "_links": {"base": "https://cf.beispiel.de", "next": "/x"}}
            res = [{"key": k, "name": "Bereich " + k, "type": "global",
                    "_links": {"webui": "/display/" + k}}
                   for k in self.keys[start:start + lim]]
            links = {"base": "https://cf.beispiel.de"}
            if start + lim < len(self.keys):
                links["next"] = "/rest/api/space?start=%d" % (start + lim)
            return {"results": res, "start": start, "limit": lim, "size": len(res),
                    "_links": links}
        if path.startswith("/rest/api/space/"):
            k = path.rsplit("/", 1)[1]
            if k == "VERBOTEN":
                raise cc.ConfluenceError(401, "Unauthorized")
            if k not in self.keys:
                raise cc.ConfluenceError(404, "No space found with key : %s" % k)
            return {"key": k, "name": "Bereich " + k, "type": "global",
                    "homepage": {"id": 4711},
                    "_links": {"base": "https://cf.beispiel.de", "webui": "/display/" + k}}
        if path.startswith("/rest/api/content/") and path.endswith("/child/page"):
            pid = path.split("/")[4]
            kinder = self.seiten.get(pid, {}).get("kinder", [])
            return {"results": [{"id": i, "title": t} for i, t in kinder]}
        if path.startswith("/rest/api/content/"):
            pid = path.rsplit("/", 1)[1]
            if pid not in self.seiten:
                raise cc.ConfluenceError(404, "No content found with id: %s" % pid)
            s = self.seiten[pid]
            return {"id": pid, "title": s["titel"], "space": {"key": s["space"]},
                    "version": {"number": 3},
                    "body": {"storage": {"value": s["storage"]}}}
        raise cc.ConfluenceError(404, "unbekannt: " + path)


def client_mit(server):
    c = cc.ConfluenceClient({"base_url": "https://cf.beispiel.de", "api_token": "x"})
    c._request = server
    return c


def lauf(werkzeug, server, **kw):
    c = client_mit(server)
    alt = sk._client
    sk._client = lambda: c
    try:
        return asyncio.run(werkzeug.execute(**kw))
    finally:
        sk._client = alt


def werkzeug(name):
    for t in sk.get_tools():
        if t.name == name:
            return t
    return None


# Bestand wie auf DEV gemessen: 489 Bereiche, NXPT alphabetisch weit hinten.
KEYS = sorted(["24H", "AIST", "ESPAD"] + ["K%03d" % i for i in range(485)] + ["NXPT"])
check(len(KEYS) == 489 and KEYS.index("NXPT") > 50,
      "Positivkontrolle: 489 Bereiche, NXPT jenseits der ersten Seite", KEYS.index("NXPT"))

LISTE = werkzeug("confluence_list_spaces")
TEST = werkzeug("confluence_test_connection")
SEITE = werkzeug("confluence_get_page")
if not (LISTE and TEST and SEITE):
    print("ABBRUCH: Werkzeuge nicht gefunden")
    sys.exit(2)

# ═════════════════════════════════════════════════════════════════════════
section("1. Liste blaettert und nennt die GESAMTZAHL")
srv = Server(KEYS)
out = lauf(LISTE, srv)
check("489 Bereich(e)" in out, "Gesamtzahl 489 steht in der Antwort", out[:200])
zeilen = [z for z in out.splitlines() if z.startswith("- ")]
check(len(zeilen) == 50, "Vorgabe: 50 Eintraege gezeigt", len(zeilen))
check("GEKUERZT" in out and "439 weitere" in out, "Kuerzung beziffert (439 weitere)", out[:300])
pos_hinweis = out.find("GEKUERZT")
pos_liste = out.find("\n- ")
check(0 <= pos_hinweis < pos_liste, "Kuerzungshinweis steht VOR der Liste", (pos_hinweis, pos_liste))
check('key="' in out, "Hinweis nennt den Weg key=\"…\"")
check(sum(1 for a in srv.aufrufe if a[1] == "/rest/api/space") >= 10,
      "mehrere Seiten abgerufen (489/50)", len(srv.aufrufe))

out = lauf(LISTE, srv, limit=500)
check(sum(1 for z in out.splitlines() if z.startswith("- ")) == 200 and "GEKUERZT" in out,
      "limit wird auf 200 gedeckelt und die Kuerzung genannt")

klein = Server(["AAA", "BBB", "CCC"])
out = lauf(LISTE, klein)
check("3 Bereich(e)" in out and "alle 3" in out and "GEKUERZT" not in out,
      "vollstaendige kurze Liste: keine Kuerzungsmeldung", out)

# ═════════════════════════════════════════════════════════════════════════
section("2. suche filtert ueber den GANZEN Bestand")
# Gemischte Schreibweise: mit "nxpt" waere Gross/Klein nicht beobachtbar,
# weil die Schluessel ohnehin gefaltet verglichen werden (Gegenprobe war stumm).
out = lauf(LISTE, Server(KEYS), suche="nXpT")
check("- NXPT —" in out, "NXPT wird gefunden, obwohl jenseits der ersten Seite", out)
check("Treffer fuer 'nXpT': 1" in out, "Trefferzahl genannt, Gross/Klein egal", out)
out = lauf(LISTE, Server(KEYS), suche="gibtsnicht")
check("Kein Bereich passt" in out and "489" in out, "kein Treffer: Gesamtzahl trotzdem genannt", out)

# ═════════════════════════════════════════════════════════════════════════
section("3. key prueft GENAU einen Bereich")
srv = Server(KEYS)
out = lauf(LISTE, srv, key="NXPT")
check(out.startswith("✅") and "NXPT" in out, "sichtbarer Bereich: ✅", out)
check("4711" in out, "Startseite wird genannt", out)
check([a[1] for a in srv.aufrufe] == ["/rest/api/space/NXPT"],
      "genau EIN gezielter Abruf, keine Liste", srv.aufrufe)
out = lauf(LISTE, Server(KEYS), key="FREMD")
check("NICHT sichtbar" in out and "404" in out and "Leseberechtigung" in out,
      "404: nicht sichtbar, mit dem Hinweis auf fehlende Leseberechtigung", out)
out = lauf(LISTE, Server(KEYS), key="VERBOTEN")
check("NICHT sichtbar" not in out and "401" in out,
      "401 wird NICHT als 'nicht sichtbar' ausgegeben", out)

# ═════════════════════════════════════════════════════════════════════════
section("4. Verbindungstest und Liste zaehlen gleich")
out_t = lauf(TEST, Server(KEYS))
out_l = lauf(LISTE, Server(KEYS))
check("489 Bereich(e)" in out_t and "489 Bereich(e)" in out_l,
      "beide nennen 489", (out_t[:160], out_l[:80]))
check("dp.test" in out_t, "Verbindungstest nennt das verbundene Konto", out_t)
out_t = lauf(TEST, Server(KEYS, user_fehler=404))
check(out_t.startswith("✅") and "489" in out_t,
      "fehlt /user/current, bleibt der Test erfolgreich", out_t)

alt_max = sk.MAX_SPACES_ABRUF
sk.MAX_SPACES_ABRUF = 120
try:
    out_t = lauf(TEST, Server([], endlos=True))
    out_l = lauf(LISTE, Server([], endlos=True))
finally:
    sk.MAX_SPACES_ABRUF = alt_max
# spaces_detailed laedt in ganzen Seiten zu 50 – bei Grenze 120 kommen 150.
# Geprueft wird die Eigenschaft ("mindestens", Zahl >= Grenze), nicht die Zahl.
import re as _re
m_t = _re.search(r"mindestens (\d+) Bereich", out_t)
m_l = _re.search(r"mindestens (\d+) Bereich", out_l)
check(bool(m_t and m_l) and int(m_t.group(1)) >= 120 and int(m_l.group(1)) >= 120,
      "erreichte Abrufgrenze heisst 'mindestens'", (out_t[:120], out_l[:120]))

# ═════════════════════════════════════════════════════════════════════════
section("5. Seite: Erfolg ist als Erfolg erkennbar, Makro-Parameter sind kein Text")
MAKRO = ('<ac:structured-macro ac:name="children" ac:schema-version="2">'
         '<ac:parameter ac:name="depth">400</ac:parameter></ac:structured-macro>'
         '<ac:structured-macro ac:name="pagetree"><ac:parameter ac:name="root">'
         '@self</ac:parameter></ac:structured-macro>')
seiten = {
    "96703123": {"titel": "ONE Projekttechnik", "space": "NXPT", "storage": MAKRO,
                 "kinder": [("101", "Netzplan"), ("102", "Server")]},
    "555": {"titel": "Lang", "space": "AAA",
            "storage": "<p>" + ("Inhalt mit Substanz. " * 30) + "</p>"},
}
srv = Server(KEYS, seiten)
out = lauf(SEITE, srv, page_id="96703123")
check("erfolgreich" in out, "Erfolg steht ausdruecklich da", out[:200])
check(not any(z.strip() == "400" for z in out.splitlines()) and "@self" not in out,
      "Makro-Parameter (400, @self) erscheinen nicht als Text", out)
check("KEIN Fliesstext" in out, "leerer Inhalt wird benannt", out)
check("children" in out and "pagetree" in out, "Makros werden benannt", out)
check("Netzplan (ID 101)" in out and "Server (ID 102)" in out,
      "Unterseiten mit ID werden angeboten", out)

srv = Server(KEYS, seiten)
out = lauf(SEITE, srv, page_id="555")
check("Seiteninhalt (" in out and "Inhalt mit Substanz" in out, "normaler Inhalt mit Laenge", out[:200])
check(not any(a[1].endswith("/child/page") for a in srv.aufrufe),
      "bei echtem Inhalt KEIN zusaetzlicher Unterseiten-Abruf", srv.aufrufe)

out = lauf(SEITE, Server(KEYS, seiten), page_id="999")
check("404" in out and "nicht lesen" in out,
      "404 nennt auch die fehlende Leseberechtigung", out)

# ═════════════════════════════════════════════════════════════════════════
section("6. Werkzeugbeschreibung")
schema = LISTE.parameters_schema().get("properties", {})
check("key" in schema and "suche" in schema, "Parameter key und suche angeboten", list(schema))
check("KEIN Beleg" in LISTE.description, "Beschreibung warnt vor gekuerzter Liste")

# ═════════════════════════════════════════════════════════════════════════
section("7. Jedes Ergebnis nennt den verwendeten Zugang")
import ast as _ast  # noqa: E402
_baum = _ast.parse(SKILL.read_text(encoding="utf-8"))
_eigene = [k.name for k in _baum.body if isinstance(k, _ast.ClassDef) and k.name != "_Base"
           and any(isinstance(f, _ast.AsyncFunctionDef) and f.name == "execute" for f in k.body)]
_werkzeuge = sk.get_tools()
check(len(_werkzeuge) >= 6, "Positivkontrolle: alle Werkzeuge geladen", len(_werkzeuge))
check(not _eigene, "kein Werkzeug hat eine eigene execute (Zeile ginge dort verloren)", _eigene)


def lauf_mit_zugang(werkzeug_obj, zugang, **kw):
    srv = Server(KEYS, seiten)
    c = client_mit(srv)
    c.zugang = zugang
    alt = sk._client
    sk._client = lambda: c
    try:
        return asyncio.run(werkzeug_obj.execute(**kw))
    finally:
        sk._client = alt


SAMMEL_NICHT_ANGEMELDET = {"quelle": "sammel", "benutzer": "m.mustermann",
                           "hinweis": "Du bist bei Confluence nicht persoenlich angemeldet – "
                                      "es gilt der gemeinsame Zugang."}
out = lauf_mit_zugang(LISTE, SAMMEL_NICHT_ANGEMELDET, key="FREMD")
erste = out.splitlines()[0] if out else ""
check(erste.startswith("ℹ Confluence-Zugang: GEMEINSAMER"), "gemeinsamer Zugang steht in Zeile 1", out[:200])
check("nicht persoenlich angemeldet" in erste and "m.mustermann" in erste,
      "… mit Grund und Benutzer", erste)
check("NICHT sichtbar" in out, "das eigentliche Ergebnis folgt", out)

out = lauf_mit_zugang(SEITE, {"quelle": "persoenlich", "benutzer": "m.mustermann",
                              "hinweis": ""}, page_id="555")
check(out.startswith("ℹ Confluence-Zugang: persoenlicher Zugang von 'm.mustermann'"),
      "persoenlicher Zugang wird genannt", out[:150])
check("GEMEINSAMER" not in out, "… ohne Gemeinsam-Warnung", out[:200])

out = lauf_mit_zugang(TEST, {"quelle": "sammel", "benutzer": "wa:4917", "hinweis": ""})
check(out.startswith("ℹ Confluence-Zugang: gemeinsamer Zugang.\n"),
      "Kanal ohne Person: knappe Zeile ohne Benutzer-Hinweis", out[:150])

out = lauf(LISTE, Server(KEYS), key="NXPT")
check(out.startswith("✅"), "ohne Zugangsangabe am Client: keine geratene Zeile", out[:80])

for w in _werkzeuge:
    kw = {"page_id": "555"} if "page" in w.name or "attachment" in w.name else {}
    if w.name == "confluence_search":
        kw = {"query": "x"}
    try:
        out = lauf_mit_zugang(w, SAMMEL_NICHT_ANGEMELDET, **kw)
    except Exception as e:  # noqa: BLE001
        out = "WURF %r" % e
    check(out.startswith("ℹ Confluence-Zugang: GEMEINSAMER"),
          "%s: Zugangszeile vorn" % w.name, out[:120])

# ═════════════════════════════════════════════════════════════════════════
section("8. Sitzungsanmeldung schreibt Journal-Zeilen (ohne Token)")
import contextlib  # noqa: E402
import io  # noqa: E402
CA_DATEI = Path(os.environ.get("CF_ACCOUNTS") or ROOT / "backend" / "confluence_accounts.py")
try:
    spec3 = importlib.util.spec_from_file_location("backend.confluence_accounts", CA_DATEI)
    ca = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(ca)
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: confluence_accounts nicht ladbar: %r" % e)
    sys.exit(2)
import tempfile  # noqa: E402
_SANDKASTEN = Path(tempfile.mkdtemp(prefix="cfw_konten_"))
ca.DATA_DIR = _SANDKASTEN
ca.KONTEN_DATEI = _SANDKASTEN / "confluence_accounts.json"
ca.SCHLUESSEL_DATEI = _SANDKASTEN / ".confluencekey"
ca.persoenlich_erlaubt = lambda cfg=None: False
ca.basis_url = lambda: "https://cf.beispiel.de"
GEHEIM = "PAT-GEHEIM-0815"


def _pruefen_ok(basis, tok):
    return ("Max Mustermann", "m.mustermann@beispiel.de")


def _pruefen_nein(basis, tok):
    raise ca.ConfluenceKontoFehler("Confluence lehnt den Token ab: 401")


for name, pruef, erwartet_ok in (("Erfolg", _pruefen_ok, True), ("Fehlschlag", _pruefen_nein, False)):
    ca._token_pruefen = pruef
    puffer = io.StringIO()
    geworfen = None
    with contextlib.redirect_stdout(puffer):
        try:
            ca.sitzung_anmelden("FIRMA\\m.mustermann", GEHEIM)
        except Exception as e:  # noqa: BLE001
            geworfen = e
    log = puffer.getvalue()
    check(GEHEIM not in log, "%s: Token steht NICHT im Journal" % name, log)
    if erwartet_ok:
        check(geworfen is None and "Sitzungsanmeldung erfolgreich: 'm.mustermann'" in log
              and "m.mustermann@beispiel.de" in log,
              "Erfolg: Zeile mit Benutzer und Confluence-Konto", (geworfen, log))
        check(ca.aufloesen("m.mustermann")["quelle"] == ca.QUELLE_PERSOENLICH,
              "Positivkontrolle: die Anmeldung wirkt (persoenlicher Zugang)")
        z = ca.client_fuer_lauf("m.mustermann")
        check(getattr(z, "zugang", {}).get("quelle") == ca.QUELLE_PERSOENLICH
              and z.zugang.get("benutzer") == "m.mustermann",
              "client_fuer_lauf traegt die Zugangsangabe", getattr(z, "zugang", None))
        check(sk._zugang_kopf(z).startswith("ℹ Confluence-Zugang: persoenlicher"),
              "Kopfzeile passt zu den ECHTEN Konstanten des Konten-Moduls", sk._zugang_kopf(z))
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer):
            ca.sitzung_beenden("m.mustermann")
        check("Sitzung beendet: 'm.mustermann'" in puffer.getvalue(),
              "Abmelden schreibt eine Zeile", puffer.getvalue())
    else:
        check(isinstance(geworfen, ca.ConfluenceKontoFehler),
              "Fehlschlag wird unveraendert weitergereicht", repr(geworfen))
        check("Sitzungsanmeldung FEHLGESCHLAGEN fuer 'm.mustermann'" in log and "401" in log,
              "Fehlschlag: Zeile mit Benutzer und Grund", log)

check(sys.modules.get("backend.config") is STUB_CONFIG,
      "die Live-Konfiguration wurde nie geladen (Attrappe hielt)")
import shutil  # noqa: E402
shutil.rmtree(_SANDKASTEN, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
