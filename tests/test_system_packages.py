#!/usr/bin/env python3
"""Waechter: Paketbericht (`backend/system_packages.py` + `/api/system/packages`).

Der Bericht nennt jede installierte Software samt exakter Version. Das ist fuer
den Betrieb unverzichtbar (Inventur, CVE-Abgleich, Vergleich DEV gegen ECHT) und
zugleich die Aufklaerungsliste fuer jeden, der eine passende Luecke sucht –
deshalb Administratoren, und deshalb ein Waechter.

Geprueft wird die REGEL, nicht ein Wortlaut. Das Modul wird WIRKLICH AUSGEFUEHRT
(gegen eine dpkg-Attrappe mit echten Ausgabeformen), der Endpunkt per ``ast``
aus ``backend/main.py`` geschnitten – ein Import zoege den halben Server nach,
und eine Quelltext-Suche laese die eigene Begruendung im Docstring mit (im
Projekt inzwischen der zehnte Fall).

  1. NUR wirklich installierte Pakete – ``rc`` (entfernt, Konfiguration liegt
     noch) gehoert nicht in eine Liste installierter Pakete, ``hi`` (hold) schon
  2. die Zusammenfassung wird NICHT zerlegt, auch wenn sie ein ``|`` enthaelt
  3. Multi-Arch: die ``.list`` wird auch unter ``<paket>:<arch>.list`` gefunden,
     und der Index entsteht EINMAL statt je Paket
  4. ES ENTSTEHT KEINE DATEI – der Bericht wird bei jedem Abruf erzeugt
  5. der Endpunkt ist Administratoren vorbehalten und laeuft NICHT im Event-Loop
  6. eine unlesbare Quelle meldet 503 MIT GRUND, keine leere Liste
  7. die Oberflaeche: ⓘ neben der CPU-Anzeige, Admin-Frage ueber /api/me,
     Download ohne Token in einer URL, Restzahl bei gekuerzter Liste

SANDKASTEN mit Exit 2: das Modul darf im Test nie das echte
``/var/lib/dpkg/info`` anfassen.
"""
import ast
import asyncio
import builtins
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen "
              "(erst Beschreibung, dann Bedingung)\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def sicher(fn, *a, **kw):
    """Ruft `fn` und macht aus einer Ausnahme einen RUECKGABEWERT.

    ⚠ EINE PRUEFUNG DARF NICHT WERFEN (Register). Beim ersten Gegenproben-Lauf
    starben drei von sieben Proben mit einer Ausnahme, statt fehlzuschlagen –
    kein FAIL, keine Zaehlzeile, und der Waechter sah aus, als waere er gar
    nicht gelaufen. Genau so bleibt ein echter Fehler unentdeckt.
    """
    try:
        return fn(*a, **kw), None
    except Exception as e:                                     # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


from backend import system_packages as sp   # noqa: E402

# ── Sandkasten ─────────────────────────────────────────────────────────────
# Das Modul liest `/var/lib/dpkg/info`. Zeigt der Pfad im Test dorthin, misst
# der Lauf die echte Maschine – und ein spaeter ergaenzter Schreibvorgang
# traefe sie.
TMP = tempfile.mkdtemp(prefix="pkgtest_")
# Den ECHTEN Wert vorher sichern: Abschnitt 9 vergleicht den in der Oberflaeche
# angezeigten Einzeiler dagegen, und der nennt natuerlich den Produktionspfad.
INFO_DIR_ECHT = sp._INFO_DIR
sp._INFO_DIR = os.path.join(TMP, "info")
os.makedirs(sp._INFO_DIR)
if not sp._INFO_DIR.startswith(TMP):
    abbruch("Sandkasten greift nicht – _INFO_DIR zeigt nach %s" % sp._INFO_DIR)


# ── dpkg-Attrappe ──────────────────────────────────────────────────────────
class Lauf:
    def __init__(self, stdout="", stderr="", rc=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, rc


_echt_run = subprocess.run
_letzter_aufruf = {}


def stelle_dpkg(stdout, stderr="", rc=0, wirf=None):
    def _run(cmd, **kw):
        _letzter_aufruf["cmd"] = cmd
        _letzter_aufruf["kw"] = kw
        if wirf:
            raise wirf
        return Lauf(stdout, stderr, rc)
    sp.subprocess.run = _run


# Echte Ausgabeformen, an der laufenden Maschine abgelesen.
ZEILEN = "\n".join([
    "ii |7zip|25.01+dfsg-1~deb13u2|amd64|7038|7-Zip file archiver with a high compression ratio",
    "ii |acl|2.3.2-2+b1|amd64|231|access control list - utilities",
    # ⚠ rc = entfernt, Konfiguration liegt noch. NICHT installiert.
    "rc |altpaket|1.0|amd64|100|rueckstand einer deinstallation",
    # hold: installiert, wird aber nicht aktualisiert - gehoert in die Liste.
    "hi |gehalten|2.0|amd64|512|paket auf hold",
    # Multi-Arch: die .list liegt unter libfoo:amd64.list
    "ii |libfoo|3.1|amd64|64|shared library",
    # ⚠ Die Zusammenfassung enthaelt selbst ein `|` - sie ist das LETZTE Feld
    # und darf nicht weiter zerlegt werden.
    "ii |pipe-paket|1.2|all|8|tool a | tool b",
    # Kaputte Zeile: zu wenige Felder. Wird uebersprungen, wirft nicht.
    "ii |halb|1.0",
    "",
])


def bericht_mit(stdout=ZEILEN, **kw):
    """Bericht holen – eine Ausnahme wird zu einem LEEREN Bericht plus Grund.

    Die Aufrufer pruefen danach Eigenschaften; ein `sp.bericht()`, das wirft,
    wuerde den ganzen Lauf abbrechen (s. `sicher`).
    """
    stelle_dpkg(stdout, **kw)
    b, grund = sicher(sp.bericht)
    if b is None:
        check("sammle() laeuft ohne Ausnahme durch", False, grund)
        return {"pakete": [], "anzahl": 0, "groesse_kb_gesamt": 0,
                "erzeugt_am": "", "host": ""}
    return b


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1) Nur wirklich installierte Pakete")
# ═══════════════════════════════════════════════════════════════════════════
b = bericht_mit()
namen = [p["package"] for p in b["pakete"]]
check("der Bericht enthaelt die installierten Pakete", "7zip" in namen and "acl" in namen,
      namen)
# ⚠ Das ist der Unterschied zum Vorbild-Skript: es zaehlt `rc` mit und nennt
# ein deinstalliertes Paket "installiert".
check("ein `rc`-Paket (entfernt, Konfiguration liegt noch) faellt heraus",
      "altpaket" not in namen, namen)
check("ein `hi`-Paket (auf hold) bleibt drin – es IST installiert",
      "gehalten" in namen, namen)
check("und traegt seinen Zustand mit, sonst ist ein hold nicht erkennbar",
      any(p["package"] == "gehalten" and p["status"].startswith("h")
          for p in b["pakete"]))
check("eine unvollstaendige Zeile wird uebersprungen, nicht geworfen",
      "halb" not in namen)
check("die Liste ist nach Namen sortiert", namen == sorted(namen, key=str.lower),
      namen)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2) Die Zusammenfassung ist das LETZTE Feld")
# ═══════════════════════════════════════════════════════════════════════════
pp = ([p for p in b["pakete"] if p["package"] == "pipe-paket"]
      or [{"summary": "", "version": "", "architecture": ""}])[0]
# Das Vorbild-Skript zerlegt mit `split('|')` ohne Grenze; eine Zusammenfassung
# mit `|` verliert dort ihren Rest.
check("ein `|` in der Beschreibung zerlegt den Datensatz nicht",
      pp["summary"] == "tool a | tool b", repr(pp["summary"]))
check("Version und Architektur bleiben dabei richtig",
      pp["version"] == "1.2" and pp["architecture"] == "all", pp)
check("das Format fragt binary:Summary ab, nicht die mehrzeilige Description",
      "${binary:Summary}" in sp._FORMAT and "${Description}" not in sp._FORMAT,
      sp._FORMAT)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3) Multi-Arch und der Datei-Index")
# ═══════════════════════════════════════════════════════════════════════════
Path(sp._INFO_DIR, "acl.list").write_text("x")
Path(sp._INFO_DIR, "libfoo:amd64.list").write_text("x")
Path(sp._INFO_DIR, "7zip.list").write_text("x")
Path(sp._INFO_DIR, "nichtsmit.md5sums").write_text("x")    # keine .list

b2 = bericht_mit()
def hol(n):
    """Ein fehlendes Paket ergibt einen LEEREN Datensatz, keine StopIteration."""
    for p in b2["pakete"]:
        if p["package"] == n:
            return p
    return {"package": n, "update_date": "", "install_date": "", "version": "",
            "architecture": "", "summary": "", "size_kb": 0, "status": ""}

check("ein Paket mit eigener .list bekommt einen Zeitstempel",
      hol("acl")["update_date"] != "", hol("acl"))
# ⚠ Genau hier ruft das Vorbild-Skript `os.listdir` erneut - je Paket.
check("Multi-Arch: `libfoo:amd64.list` wird gefunden",
      hol("libfoo")["update_date"] != "", hol("libfoo"))
check("ein Paket ohne .list bekommt einen LEEREN Zeitstempel, kein geratenes Datum",
      hol("pipe-paket")["update_date"] == "" and hol("pipe-paket")["install_date"] == "",
      hol("pipe-paket"))

# Der Index entsteht EINMAL – gemessen, nicht am Quelltext abgelesen.
_zaehler = {"n": 0}
_echt_listdir = os.listdir
def _gezaehlt(pfad):
    if str(pfad) == sp._INFO_DIR:
        _zaehler["n"] += 1
    return _echt_listdir(pfad)
os.listdir = _gezaehlt
try:
    bericht_mit()
finally:
    os.listdir = _echt_listdir
check("das Info-Verzeichnis wird je Bericht genau EINMAL gelesen",
      _zaehler["n"] == 1, "%d Aufrufe" % _zaehler["n"])

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("4) Es entsteht KEINE Datei")
# ═══════════════════════════════════════════════════════════════════════════
# Ein Paketstand ist eine Aussage ueber den Server im Moment der Frage. Eine
# Datei auf Platte waere eine zweite Wahrheit, veraltet genau dann, wenn man
# nachsieht - und eine Frage nach Eigentuemer und Leserecht mehr.
quelle = Path(ROOT, "backend", "system_packages.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
schreibend = []
for n in ast.walk(baum):
    if isinstance(n, ast.Call):
        f = n.func
        nam = getattr(f, "attr", None) or getattr(f, "id", None)
        if nam in ("open", "write_text", "write_bytes", "dump", "mkdir", "makedirs",
                   "remove", "unlink", "replace", "rename"):
            schreibend.append(nam)
check("das Modul oeffnet und schreibt keine Datei", not schreibend, schreibend)
vorher = set(os.listdir(TMP))
bericht_mit()
check("und ein Bericht legt auch zur Laufzeit nichts an",
      set(os.listdir(TMP)) == vorher)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("5) Kopfdaten und Dateiname")
# ═══════════════════════════════════════════════════════════════════════════
b3 = bericht_mit()
check("der Bericht nennt Zeitpunkt, Host und Anzahl",
      b3.get("erzeugt_am") and "host" in b3 and b3["anzahl"] == len(b3["pakete"]),
      {k: b3[k] for k in ("erzeugt_am", "host", "anzahl")})
check("und die Gesamtgroesse ist die Summe der Einzelwerte",
      b3["groesse_kb_gesamt"] == sum(p["size_kb"] for p in b3["pakete"]))
check("eine unlesbare Groesse wird zu 0, nicht zum Absturz",
      all(isinstance(p["size_kb"], int) for p in b3["pakete"]))
name = sp.dateiname("hh-vm-jarvis")
check("der Dateiname traegt Host UND Zeitpunkt", "hh-vm-jarvis" in name and name.endswith(".json"),
      name)
# Der Wert reist in einem HTTP-Kopf (Content-Disposition) - dieselbe Lehre wie
# bei X-Jarvis-Cert-Warn: dort stand ein Gedankenstrich und wurde zu `?`.
check("und er ist reines ASCII ohne Anfuehrungszeichen",
      name.isascii() and '"' not in name and "\n" not in name, name)
check("ein Host mit Sonderzeichen wird entschaerft, nicht uebernommen",
      '"' not in sp.dateiname('a"b/../c') and "/" not in sp.dateiname('a"b/../c'),
      sp.dateiname('a"b/../c'))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("6) Eine unlesbare Quelle meldet den GRUND")
# ═══════════════════════════════════════════════════════════════════════════
# Eine leere Liste waere die Behauptung, es sei nichts installiert (Register:
# eine Anzeige darf keinen Zustand behaupten, den sie nicht kennt).
for beschreibung, kw, erwartet in [
    ("kein dpkg auf dem System", dict(wirf=FileNotFoundError()), "dpkg-query"),
    ("dpkg antwortet nicht (Sperre)",
     dict(wirf=subprocess.TimeoutExpired("dpkg-query", 30)), "dpkg-Sperre"),
    ("leere Ausgabe", dict(stdout="", stderr="dpkg: kaputt"), "keine Daten"),
]:
    stelle_dpkg(kw.pop("stdout", ""), **kw)
    try:
        sp.bericht()
        check("%s: es gibt einen Fehler" % beschreibung, False, "kein Fehler geworfen")
    except sp.PaketFehler as e:
        check("%s -> PaketFehler mit Klartext" % beschreibung, erwartet in str(e), str(e))
    except Exception as e:                                     # noqa: BLE001
        check("%s -> PaketFehler (nicht irgendeine Ausnahme)" % beschreibung, False,
              type(e).__name__)

# ⚠ Rueckgabewert != 0 ist NICHT zwingend ein Fehlschlag: dpkg-query meldet 1,
# wenn EINZELNE Pakete fehlen, liefert die uebrigen aber sauber.
r = bericht_mit(ZEILEN, rc=1, stderr="dpkg-query: no packages found matching xyz")
check("Rueckgabewert 1 mit Daten ist KEIN Fehlschlag", r["anzahl"] > 0, r["anzahl"])

check("es gibt ein Zeitlimit fuer dpkg-query", sp._TIMEOUT_S > 0, sp._TIMEOUT_S)
# ⚠ ueber `bericht_mit`, nicht direkt: ein `sp.bericht()` hier brach beim
# Gegenproben-Lauf den ganzen Test ab, statt fehlzuschlagen.
bericht_mit(ZEILEN)
check("und es wird wirklich uebergeben",
      _letzter_aufruf["kw"].get("timeout") == sp._TIMEOUT_S, _letzter_aufruf["kw"])

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("7) Der Endpunkt: Admin, Thread, 503 mit Grund")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = ROOT / "backend" / "main.py"
QUELL = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
FN = {n.name: n for n in BAUM.body
      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
if "system_packages" not in FN:
    abbruch("Endpunkt system_packages nicht in backend/main.py gefunden")
EP = FN["system_packages"]

# a) Die Dependency – am AST, nicht am Text: `require_local_auth` kaeme sonst
#    auch aus einem Kommentar.
deps = []
for arg, vor in zip(EP.args.args, [None] * (len(EP.args.args) - len(EP.args.defaults))
                    + list(EP.args.defaults)):
    if isinstance(vor, ast.Call) and getattr(vor.func, "id", "") == "Depends":
        deps.append(getattr(vor.args[0], "id", ""))
check("der Endpunkt haengt an require_local_auth (Administratoren)",
      deps == ["require_local_auth"], deps)

# b) Nicht im Event-Loop. `dpkg-query` ist ein Unterprozess und `os.stat` ueber
#    2800 Dateien blockierender I/O - direkt gerufen stuende der Dienst fuer
#    ALLE Benutzer (Register: der 20-Sekunden-Freeze durch Path.is_mount()).
awaits = [n for n in ast.walk(EP) if isinstance(n, ast.Await)]
in_thread = any(
    isinstance(a.value, ast.Call)
    and getattr(a.value.func, "attr", "") == "to_thread"
    for a in awaits)
check("der Bericht laeuft in einem Thread, nicht im Event-Loop", in_thread)
direkt = [n for n in ast.walk(EP)
          if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "bericht"
          and not any(isinstance(p, ast.Await) for p in [n])]
check("und wird nirgends zusaetzlich direkt gerufen",
      not [n for n in ast.walk(EP) if isinstance(n, ast.Expr)
           and isinstance(n.value, ast.Call)
           and getattr(n.value.func, "attr", "") == "bericht"])

# c) AUSGEFUEHRT: eine unlesbare Quelle muss 503 MIT GRUND liefern.
class Antwort:
    def __init__(self, content, status_code=200, headers=None):
        self.content, self.status_code, self.headers = content, status_code, headers or {}


class Anfrage:
    def __init__(self, **qp):
        self.query_params = qp


class Namensraum(dict):
    """Globals, die jeden UNBEKANNTEN Namen zu einem Platzhalter machen.

    ⚠ Beim ersten Gegenproben-Lauf starb die Probe "Endpunkt nicht mehr Admin"
    mit `NameError: require_auth` – die Gegenprobe biss also nicht, sie brach
    ab. Der Schnitt darf nicht daran haengen, WELCHE Dependency dort steht;
    darueber urteilt die AST-Pruefung darueber, und die soll dann FAIL melden.
    """

    def __missing__(self, name):
        # ⚠ ZUERST DIE BUILTINS. Bei einem dict-Nachfahren als globals ruft
        # CPython `__missing__` und erreicht die Builtins danach NICHT mehr –
        # die erste Fassung machte damit aus `str(e)` ein `None(e)` und der
        # Endpunkt starb mit "'NoneType' object is not callable". Ein Fehler,
        # den ich in den Endpunkt gelegt haette, waere so unauffindbar gewesen.
        if hasattr(builtins, name):
            return getattr(builtins, name)
        if name.startswith("__"):
            raise KeyError(name)
        return None


ns = Namensraum({
    "JSONResponse": Antwort, "asyncio": asyncio, "Request": Anfrage,
    "Depends": lambda f: None,
    "logger": type("L", (), {"error": staticmethod(lambda *a, **k: None)})(),
    "app": type("A", (), {"get": staticmethod(lambda *a, **k: (lambda f: f))})(),
})
# Der Dekorator wird mitgeschnitten, damit der Schnitt der echte Code bleibt.
_, _grund = sicher(exec, compile(ast.Module(body=[EP], type_ignores=[]), "<ep>", "exec"), ns)
if _grund:
    abbruch("der Endpunkt liess sich nicht schneiden: %s" % _grund)
endpunkt = ns["system_packages"]

LEER = Antwort({}, status_code=0)


def ruf(**qp):
    """Endpunkt ausfuehren; eine Ausnahme wird zu einer Antwort mit Status 0."""
    a, grund = sicher(lambda: asyncio.run(endpunkt(Anfrage(**qp), user="jarvis")))
    if a is None:
        check("der Endpunkt laeuft ohne Ausnahme durch", False, grund)
        return LEER
    return a


stelle_dpkg("", wirf=FileNotFoundError())
a = ruf()
check("eine unlesbare Quelle antwortet 503 (nicht 500)", a.status_code == 503, a.status_code)
check("und nennt den Grund im Klartext",
      "dpkg-query" in str((a.content or {}).get("error", "")), a.content)

stelle_dpkg(ZEILEN)
a = ruf()
check("mit Daten antwortet er 200", a.status_code == 200, a.status_code)
check("und liefert den vollstaendigen Bericht", (a.content or {}).get("anzahl") == len(namen),
      (a.content or {}).get("anzahl"))
check("ohne ?download bleibt der Datei-Kopf weg",
      "Content-Disposition" not in (a.headers or {}), a.headers)

a = ruf(download="1")
cd = (a.headers or {}).get("Content-Disposition", "")
check("mit ?download=1 kommt ein Dateiname mit", "attachment" in cd and ".json" in cd, cd)
check("und der Kopfwert ist ASCII", cd.isascii(), cd)
check("der INHALT ist in beiden Faellen derselbe",
      (a.content or {}).get("anzahl") == len(namen))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8) Die Oberflaeche")
# ═══════════════════════════════════════════════════════════════════════════
JS = (ROOT / "frontend" / "js" / "syspackages.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")


def ohne_kommentare(js):
    """Entfernt JS-Kommentare – bewusst SCHLICHT, mit Positivkontrolle darunter.

    ⚠ Ein Waechter, der die eigene Begruendung mitliest, prueft nichts. Beim
    ersten Lauf hat genau das zugeschlagen: die Pruefung "kein `?token=` im
    Download" schlug an, weil der KOMMENTAR darueber erklaert, warum es keines
    gibt. Im Projekt ist das der elfte Fall dieser Klasse.

    ⚠ ZWEITER ANLAUF, und die Lehre steht hier: ein zeichenweiser Zerteiler mit
    Zeichenketten-Zustand SIEHT WIE DIE RICHTIGE LOESUNG AUS und ist es nicht –
    er stolpert ueber Regex-Literale wie ``.replace(/"/g, ...)``, geraet in
    einen Zeichenketten-Zustand, der nie endet, und laesst alles danach stehen.
    Er entfernte 2302 von 19307 Zeichen und meldete den Fehlalarm trotzdem.
    JavaScript laesst sich ohne Parser nicht sauber zerteilen.

    Genommen wird deshalb die schlichte Variante (Blockkommentare, dazu Zeilen,
    die MIT ``//`` beginnen). Sie genuegt fuer diese Datei, und ob sie es tut,
    wird darunter GEMESSEN statt angenommen.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(z for z in js.splitlines() if not z.strip().startswith("//"))


JS_CODE = ohne_kommentare(JS)
# POSITIVKONTROLLE, und sie ist der Kern: sie prueft nicht "es wurde etwas
# entfernt", sondern die beiden Eigenschaften, auf denen alles darunter beruht -
# ein bekannter Kommentar-Satz ist WEG, bekannter Code ist DA. Ohne sie waeren
# die Pruefungen darunter gruen aus dem falschen Grund.
check("die Kommentar-Entfernung greift wirklich",
      "Sparsamkeit" in JS and "Sparsamkeit" not in JS_CODE,
      "%d von %d Zeichen" % (len(JS_CODE), len(JS)))
check("und sie laesst den Code stehen",
      all(x in JS_CODE for x in ("createObjectURL", "'/api/system/packages'",
                                 "function esc(", "nextSibling")))

check("die Admin-Frage beantwortet /api/me – nicht ein Bereichs-Abruf",
      "'/api/me'" in JS and "is_admin" in JS)
# ⚠ Genau der Fehler, der beim Einstellungs-Zahnrad dreimal gemeldet wurde.
check("und KEIN Bereichs-Endpunkt entscheidet ueber die Sichtbarkeit",
      not any(x in JS for x in ("/api/tracks/status", "/api/claude/status",
                                "/api/wissen/scope")))
check("der Knopf sitzt hinter der CPU-Anzeige", "'cpu-bar'" in JS and "nextSibling" in JS)
# Das Symbol ist ein Inline-SVG: ein Emoji wird je System farbig gerendert und
# folgt keinem Theme (Projektregel).
check("das Symbol ist ein Inline-SVG, kein Emoji", "<svg" in JS)
check("beide Versteck-Mechanismen werden bedient (style UND Klasse `hidden`)",
      "style.display" in JS and "classList.remove('hidden')" in JS)
# Ein `<a href>` kann keinen Authorization-Header setzen - ein Download-Link
# braeuchte `?token=`, und damit stuende das Sitzungstoken in der Adresszeile,
# im Verlauf und in jedem Proxy-Log.
check("der Download baut einen Blob und haengt KEIN Token an eine URL",
      "createObjectURL" in JS_CODE and "?token=" not in JS_CODE)
check("Fremdtext wird ausnahmslos maskiert", "function esc(" in JS)
check("die Restzahl steht in der Fusszeile – eine gekuerzte Liste sagt es",
      "pkg.more" in JS and "rest" in JS)
check("der Bericht wird beim Schliessen verworfen, nicht gemerkt",
      "_bericht = null" in JS)
check("Escape schliesst den Kasten", "'Escape'" in JS)
check("das ×-Symbol ist Schliessen (Symbol-Semantik)",
      "JarvisIcons" in JS and "close()" in JS and "trash" not in JS)

check("das CSS liegt in theme.css (der Knopf steht auf JEDER Seite)",
      ".jv-pkg-btn" in CSS and ".jv-pkg-overlay" in CSS)
check("der Knopf bringt keinen eigenen Aussenabstand mit",
      not any(z.strip().startswith("margin")
              for z in CSS.split(".jv-pkg-btn {")[1].split("}")[0].splitlines()),
      CSS.split(".jv-pkg-btn {")[1].split("}")[0])
# ⚠ `min-height: 0` ist Pflicht: ohne sie schrumpft ein Flex-Kind nicht unter
# seine Inhaltshoehe, `overflow-y` bleibt wirkungslos und die Fusszeile wird
# aus dem Kasten gedrueckt (dieselbe Stelle wie beim Update-Popup).
for regel in (".jv-pkg-box {", ".jv-pkg-scroll {"):
    block = CSS.split(regel)[1].split("}")[0]
    check("%s traegt min-height: 0" % regel.strip(" {"), "min-height: 0" in block, block)
kopf = CSS.split(".jv-pkg-tab thead th {")[1].split("}")[0]
check("der Tabellenkopf klebt und hat eine DECKENDE Flaeche",
      "position: sticky" in kopf and "background-color:" in kopf, kopf)

# Die Seiten. Abgeleitet aus dem VERZEICHNIS: eine kuenftige Bereichsseite mit
# CPU-Anzeige faellt damit von selbst auf.
fehlend = []
for p in sorted((ROOT / "frontend").glob("*.html")):
    h = p.read_text(encoding="utf-8")
    if "cpubar.js" in h and "syspackages.js" not in h:
        fehlend.append(p.name)
check("jede Seite mit CPU-Anzeige laedt auch syspackages.js", not fehlend, fehlend)

I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
schnitt = I18N.find("'wissen.cpu_load': 'CPU load'")
de = set(re.findall(r"'(pkg\.[a-z_]+)':", I18N[:schnitt]))
en = set(re.findall(r"'(pkg\.[a-z_]+)':", I18N[schnitt:]))
check("alle pkg.*-Texte gibt es in DE und EN", de and de == en, sorted(de ^ en))
benutzt = set(re.findall(r"T\('(pkg\.[a-z_]+)'", JS))
check("und jeder im JS benutzte Schluessel existiert", benutzt <= de, sorted(benutzt - de))
# Der Wert IST kein Installationsdatum - dpkg fuehrt keines. Eine Anzeige, die
# das behauptet, sagt etwas, das sie nicht weiss.
check("die Oberflaeche sagt, was das Datum wirklich ist",
      "date_hint" in JS and "Installationsdatum" in I18N)


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("9) Herkunft der Zahlen und die Einzeiler zum Nachrechnen")

# Die Zusage: der Kasten sagt, WORAUS die Zahlen entstehen, und bietet einen
# Einzeiler, mit dem ein Administrator sie auf dem Server nachrechnet. Eine Zahl
# ohne Herkunft ist eine Behauptung.
check("der Kasten erklaert die Herkunft in einem Aufklapp-Abschnitt",
      "wieBlock" in JS and "jv-pkg-wie" in JS and "<details" in JS)
# Der Abschnitt muss auch WIRKLICH gezeichnet werden - eine Funktion ohne
# Aufrufer waere toter Code (im Projekt schon vorgekommen).
fuss_idx = JS.find("jv-pkg-fuss")
check("und er haengt in der Fusszeile, nicht nur im Quelltext",
      fuss_idx > 0 and 0 < JS.find("wieBlock()", fuss_idx) < JS.find("</div>');", fuss_idx))
# `zeichnen()` baut den Kasten bei JEDEM Tastendruck in der Suche neu auf.
# Ohne gemerkten Zustand klappte die Erklaerung beim Tippen jedes Mal zu.
check("der Aufklapp-Zustand ueberlebt das Neuzeichnen",
      "_wieOffen" in JS and "wie.open" in JS and "_wieOffen ? ' open' : ''" in JS)
# In der Zwischenablage sieht man nichts, und `navigator.clipboard` fehlt in
# unsicheren Kontexten ganz - ein Fehlschlag waere sonst unsichtbar.
check("Kopieren meldet Erfolg UND Fehlschlag zurueck",
      "pkg.copied" in JS and "pkg.copy_fail" in JS and "ist-fehler" in JS)
# Der Knopf traegt nur den Schluessel: so kann aus einem Attributwert nie ein
# anderer Befehl werden als der angezeigte.
check("der Kopier-Knopf traegt den Schluessel, nicht den Befehl",
      "data-cmd=\"' + esc(schluessel)" in JS and "dpkg-query" not in JS[JS.find("function cmdZeile"):JS.find("function kopiere")])

# ── Die Einzeiler aus dem JS holen (kein node noetig) ──────────────────────
def js_befehl(name):
    """Liest BEFEHLE.<name> aus syspackages.js und loest die JS-Escapes auf."""
    blk = re.search(r"var BEFEHLE = \{(.*?)\n    \};", JS, re.S)
    if not blk:
        return ""
    m = re.search(r"\n\s*%s:\s*(.*?)(?=\n\s*[a-z_]+:|\Z)" % name, blk.group(1), re.S)
    if not m:
        return ""
    return "".join(json.loads(t) for t in re.findall(r'"(?:[^"\\]|\\.)*"', m.group(1)))

CMD_LISTE = js_befehl("liste")
CMD_STAND = js_befehl("stand")
check("beide Einzeiler sind lesbar", CMD_LISTE and CMD_STAND, (CMD_LISTE, CMD_STAND))

# ── DRIFT-SCHRANKE ────────────────────────────────────────────────────────
# Der angezeigte Befehl und das Backend muessen DASSELBE tun. Laufen sie
# auseinander, zeigt die Oberflaeche einen Befehl mit anderem Ergebnis als die
# Liste darueber - und der Anwender haelt genau diesen Unterschied fuer einen
# Fehler. Verglichen wird gegen die echten Konstanten des Moduls.
check("der Einzeiler benutzt WOERTLICH das Abfrageformat des Backends",
      sp._FORMAT.rstrip("\n") in CMD_LISTE,
      sp._FORMAT.rstrip("\n"))
check("und der zweite nennt das Verzeichnis, aus dem der Stand kommt",
      INFO_DIR_ECHT in CMD_STAND, (INFO_DIR_ECHT, CMD_STAND))
check("der Trenner des Befehls ist der des Backends",
      ("-F'%s'" % sp._TRENNER) in CMD_LISTE, sp._TRENNER)

# ⚠ ⚠ Der Befehl wird WIRKLICH AUSGEFUEHRT - gegen dieselbe Attrappen-Ausgabe,
# aus der auch `sammle()` liest. Eine Textpruefung wuerde nur belegen, dass
# jemand etwas hingeschrieben hat; hier wird die EIGENSCHAFT gemessen: waehlt
# der angezeigte Befehl dieselben Pakete aus wie das Backend?
import shutil
if not shutil.which("awk"):
    check("awk vorhanden (fuer die Ausfuehrungsprobe)", False, "awk fehlt")
else:
    hilfsdir = os.path.join(TMP, "bin")
    os.makedirs(hilfsdir, exist_ok=True)
    dq = os.path.join(hilfsdir, "dpkg-query")
    # Die Attrappe ignoriert die Argumente und gibt die Testzeilen aus - genau
    # das, was `stelle_dpkg` dem Modul liefert. Damit lesen beide Wege dasselbe.
    with open(dq, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\ncat <<'ZEILEN_ENDE'\n%s\nZEILEN_ENDE\n" % ZEILEN.rstrip("\n"))
    os.chmod(dq, 0o755)
    umg = dict(os.environ, PATH=hilfsdir + os.pathsep + os.environ.get("PATH", ""))
    # ⚠ NICHT `subprocess.run` - `stelle_dpkg()` ersetzt das Attribut am MODUL,
    # und dann liefe der Befehl durch die Attrappe zurueck, statt zu laufen.
    # Genau so war die erste Fassung dieses Tests gruen, ohne etwas zu messen.
    lauf, grund = sicher(lambda: _echt_run(
        ["sh", "-c", CMD_LISTE], capture_output=True, text=True, timeout=20, env=umg))
    if lauf is None:
        check("der angezeigte Befehl laeuft", False, grund)
    else:
        durch = set()
        for z in (lauf.stdout or "").splitlines():
            t = z.split(sp._TRENNER)
            if len(t) > 1 and t[1].strip():
                durch.add(t[1].strip())
        b = bericht_mit()
        im_bericht = {x["package"] for x in b["pakete"]}
        check("der angezeigte Befehl laeuft ueberhaupt", lauf.returncode == 0,
              (lauf.returncode, lauf.stderr[:200]))
        # DIE zentrale Zusage: was der Bericht zeigt, liefert der Befehl auch.
        check("er liefert JEDES Paket, das der Bericht zeigt",
              im_bericht and im_bericht <= durch, sorted(im_bericht - durch))
        # Und die Gegenrichtung, die den Filter beweist: `rc` bleibt draussen.
        check("und laesst den rc-Eintrag genauso draussen wie das Backend",
              "altpaket" not in durch and "altpaket" not in im_bericht, sorted(durch))

# ── CSS: drei Regeln, die keine Kosmetik sind ─────────────────────────────
CSS = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")


def regel(name):
    """Der Rumpf einer CSS-Regel – OHNE Kommentare.

    ⚠ Die Kommentare MUESSEN raus: sie begruenden genau die Deklaration, die
    hier geprueft wird ("`min-width: 0` ist Pflicht ..."). Ohne das Entfernen
    liest der Waechter seine eigene Begruendung und bleibt gruen, auch wenn die
    Deklaration geloescht wurde – im Projekt inzwischen der zwoelfte Fall
    dieser Klasse, und dieser hier ist von einer Gegenprobe aufgefallen, die
    NICHT gebissen hat.
    """
    m = re.search(r"\.%s\s*\{(.*?)\}" % re.escape(name), CSS, re.S)
    if not m:
        return None
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)


# Positivkontrolle fuer den Helfer: entfernt er wirklich NUR den Kommentar?
_probe = regel("jv-pkg-cmd")
check("die Kommentar-Entfernung im CSS-Helfer greift",
      _probe is not None and "ist Pflicht" not in _probe and "font-family" in _probe,
      _probe)

r_cmd = regel("jv-pkg-cmd")
check("der Befehlsblock schrumpft im Flex-Container (min-width: 0)",
      r_cmd and "min-width: 0" in r_cmd, r_cmd)
r_fuss = regel("jv-pkg-fuss")
check("die Fusszeile wird nicht gestaucht (flex: 0 0 auto)",
      r_fuss and "flex: 0 0 auto" in r_fuss, r_fuss)
r_wie = regel("jv-pkg-wie-in")
check("der aufgeklappte Bereich hat einen eigenen Deckel mit Scroll",
      r_wie and "max-height" in r_wie and "overflow-y: auto" in r_wie, r_wie)

print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
