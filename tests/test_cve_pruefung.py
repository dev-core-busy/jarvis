#!/usr/bin/env python3
"""Sicherheitsluecken-Pruefung (backend/cve_pruefung.py, backend/cve_apt.py).

Geprueft wird die WIRKUNG, wo sie ausfuehrbar ist, und die Regel am
Syntaxbaum, wo sie es nicht ist:

  1. Versionsvergleich = ``dpkg --compare-versions`` (Positivkontrolle: dpkg
     muss da sein, sonst Exit 2 – ohne Referenz ist der Vergleich nicht
     deutbar).
  2. Bewertung gegen einen Tracker-Auszug: Quellpaket statt Binaerpaket,
     behoben/nicht behoben/offen, Release-Grenze, Kernel (laufender Kernel,
     Neustart statt Update).
  3. Schwelle und Plan: nicht Eingestuftes zaehlt immer, die regulaere Quelle
     nur mit Schalter, Python im Lock-Modus nie.
  4. Beheben (Broker-Seite) mit Attrappe fuer apt/dpkg: Namensmuster, hold,
     nur Sicherheitsquelle, Abbruch bei geplanter Entfernung, und der echte
     Aufruf traegt ``--only-upgrade --no-remove`` und nur die Zielpakete.
  5. Auftragsart: in der Whitelist von add_job, Zweig VOR dem Agenten,
     ``payload``/``kind`` nicht ueber den PUT aenderbar, Optionen geprueft.
  6. Broker: Op registriert, als lange Op gefuehrt, cve_apt nur Stdlib.
  7. Badge: je Paket, Quittiertes zaehlt nicht, "behebbar" ist nicht
     quittierbar.

    python3 tests/test_cve_pruefung.py      Exit 0 gruen, 1 rot, 2 nicht lauffaehig
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SANDKASTEN = Path(tempfile.mkdtemp(prefix="cve_test_"))
# VOR dem Import: das Modul liest seinen Datenordner beim Laden.
os.environ["JARVIS_CVE_DATEN"] = str(SANDKASTEN)

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" - {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n{t}")


def ende(code=None):
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    if code is not None:
        sys.exit(code)
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(0 if _fail == 0 else 1)


from backend import cve_apt, cve_pruefung  # noqa: E402

if Path(cve_pruefung.DATEN) != SANDKASTEN:
    print("ABBRUCH: Datenordner zeigt aus dem Sandkasten heraus:", cve_pruefung.DATEN)
    ende(2)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Versionsvergleich wie dpkg")
# ═══════════════════════════════════════════════════════════════════════════
if not shutil.which("dpkg"):
    print("ABBRUCH: dpkg fehlt – ohne Referenz ist der Vergleich nicht messbar")
    ende(2)
PAARE = [
    ("1.0", "1.0"), ("1.0", "1.1"), ("1.10", "1.9"), ("1.0~rc1", "1.0"),
    ("1.0~~", "1.0~"), ("1:0.1", "2.0"), ("0:1.0", "1.0"), ("1.0-1", "1.0-1+b1"),
    ("1.1.0-2+b7", "1.1.0-2+deb13u1"), ("2.41-12+deb13u4", "2.41-12+deb13u3"),
    ("6.12.107-1", "6.12.113-1"), ("6.12.113-1", "6.12.113+1"), ("1.0a", "1.0b"),
    ("1.0+dfsg-1", "1.0-1"), ("1.0.0", "1.0"), ("1.0-1~bpo13+1", "1.0-1"),
    ("20250419", "20250419+deb13u1"), ("1:9.20.30-1~deb13u1", "1:9.20.29-1"),
    ("8.4.27-1~deb13u1", "8.4.27-1"), ("3.0.11-1+deb13u4", "3.0.11-1+deb13u10"),
    ("1.2.3", "1.2.3."), ("a", "b"), ("1.0-0", "1.0"), ("0", "0.0"),
]
dpkg_ok = 0
abweichend = []
for a, b in PAARE:
    for x, y in ((a, b), (b, a)):
        # stderr leise: dpkg warnt bei "a"/"b" (Syntax), vergleicht aber trotzdem.
        lt = subprocess.run(["dpkg", "--compare-versions", x, "lt", y],
                            stderr=subprocess.DEVNULL).returncode == 0
        eq = subprocess.run(["dpkg", "--compare-versions", x, "eq", y],
                            stderr=subprocess.DEVNULL).returncode == 0
        soll = -1 if lt else (0 if eq else 1)
        r = cve_apt.vergleiche(x, y)
        ist = -1 if r < 0 else (0 if r == 0 else 1)
        if ist == soll:
            dpkg_ok += 1
        else:
            abweichend.append(f"{x} ? {y}: soll {soll}, ist {ist}")
# Positivkontrolle der Referenz: dpkg muss die bekannten Faelle selbst so sehen.
ref = subprocess.run(["dpkg", "--compare-versions", "1.0~rc1", "lt", "1.0"]).returncode == 0
check(ref, "Referenz: dpkg sieht 1.0~rc1 < 1.0")
check(not abweichend, f"alle {len(PAARE) * 2} Vergleiche wie dpkg", "; ".join(abweichend[:5]))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2. Bewertung gegen den Tracker-Auszug")
# ═══════════════════════════════════════════════════════════════════════════


def pk(paket, quelle, qv, status="ii", arch="amd64"):
    return {"paket": paket, "arch": arch, "version": qv, "quelle": quelle,
            "quell_version": qv, "status": status}


def eintrag(status, fix="", urgency="not yet assigned", repos=None, **extra):
    r = {"status": status, "urgency": urgency, "repositories": repos or {}}
    if fix:
        r["fixed_version"] = fix
    r.update(extra)
    return {"r": r, "text": "Beschreibung"}


PAKETE = [
    pk("libbrotli1", "brotli", "1.1.0-2+b7"),
    pk("brotli", "brotli", "1.1.0-2+b7"),
    pk("libfoo1", "foo", "2.0-1"),
    pk("nodejs", "nodejs", "20.19.2+dfsg-1+deb13u2"),
]
AUSZUG = {
    "brotli": {"CVE-2026-111497": eintrag("resolved", "1.1.0-2+deb13u1",
                                          repos={"trixie": "1.1.0-2+b7",
                                                 "trixie-security": "1.1.0-2+deb13u1"})},
    "foo": {"CVE-2026-1": eintrag("resolved", "1.9-1"),          # schon behoben
            "CVE-2026-2": eintrag("resolved", "0"),              # nie betroffen
            "CVE-2026-3": eintrag("resolved", "2.0-2", urgency="low", next_point_update=True)},
    "nodejs": {"CVE-2026-111497": eintrag("open", urgency="unimportant")},
}
# Ein Eintrag unter dem BINAERnamen darf nichts finden: Debian fuehrt Quellpakete.
AUSZUG_BIN = {"libbrotli1": AUSZUG["brotli"]}
bef = cve_pruefung.debian_bewerten(PAKETE, AUSZUG, "trixie")
je = {(b["quelle"], b["cve"]): b for b in bef}
check(("brotli", "CVE-2026-111497") in je, "Quellpaket brotli wird ueber libbrotli1 gefunden")
check(sorted(je.get(("brotli", "CVE-2026-111497"), {}).get("pakete", [])) == ["brotli", "libbrotli1"],
      "der Befund nennt die betroffenen BINAERpakete")
check(not cve_pruefung.debian_bewerten(PAKETE, AUSZUG_BIN, "trixie"),
      "ein Eintrag unter dem Binaernamen trifft nichts (Zuordnung laeuft ueber die Quelle)")
check(je.get(("brotli", "CVE-2026-111497"), {}).get("aus_sicherheitsmeldung") is True,
      "Behebung in trixie-security wird als Sicherheitsmeldung erkannt")
check(("foo", "CVE-2026-1") not in je, "installiert >= behoben -> kein Befund")
check(("foo", "CVE-2026-2") not in je, "fixed_version 0 (nie betroffen) -> kein Befund")
check(je.get(("foo", "CVE-2026-3"), {}).get("klasse") == "fix"
      and je.get(("foo", "CVE-2026-3"), {}).get("zwischenrelease") is True,
      "aelter als behoben -> Klasse fix, Zwischenrelease markiert")
check(je.get(("nodejs", "CVE-2026-111497"), {}).get("klasse") == "offen"
      and je.get(("nodejs", "CVE-2026-111497"), {}).get("einstufung") == "unimportant",
      "keine Behebung im Release -> offen, Einstufung uebernommen (der nodejs-Fall)")
# Die Release-Grenze zieht der AUSZUG (tracker_auszug), nicht die Bewertung –
# deshalb hier an einer echten gepackten Tracker-Datei gemessen.
import gzip  # noqa: E402
_fake = {"brotli": {"CVE-2026-5": {"description": "x" * 400, "releases": {
             "bookworm": {"status": "open", "urgency": "low", "repositories": {}}}},
                    "CVE-2026-6": {"description": "y", "releases": {
             "trixie": {"status": "open", "urgency": "low", "repositories": {}}}}},
         "fremd": {"CVE-2026-4": {"releases": {"trixie": {"status": "open"}}}}}
cve_pruefung.TRACKER_CACHE.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(cve_pruefung.TRACKER_CACHE, "wt", encoding="utf-8") as _f:
    json.dump(_fake, _f)
_aus = cve_pruefung.tracker_auszug({"brotli"}, "trixie")
check(list(_aus) == ["brotli"] and list(_aus["brotli"]) == ["CVE-2026-6"],
      "Auszug: nur installierte Quellen und nur Eintraege fuer DIESES Release", str(_aus)[:200])
check(len(_aus["brotli"]["CVE-2026-6"]["text"]) <= 240, "Beschreibung gekuerzt")

KERNEL_PAKETE = [pk("linux-image-6.12.107+deb13-amd64", "linux", "6.12.107-1"),
                 pk("linux-image-6.12.113+deb13-amd64", "linux", "6.12.113-1"),
                 pk("linux-image-amd64", "linux-signed-amd64", "6.12.113+1")]
K_AUSZUG = {"linux": {"CVE-2026-9": eintrag("resolved", "6.12.111-1"),
                      "CVE-2026-8": eintrag("resolved", "6.12.120-1"),
                      "CVE-2026-7": eintrag("resolved", "6.12.100-1")}}
kb = {b["cve"]: b for b in cve_pruefung.debian_bewerten(KERNEL_PAKETE, K_AUSZUG, "trixie",
                                                         "6.12.107-1")}
check(kb.get("CVE-2026-9", {}).get("klasse") == "neustart",
      "Kernel: Behebung installiert, laeuft aber nicht -> Neustart")
check(kb.get("CVE-2026-8", {}).get("klasse") == "fix", "Kernel: noch nicht installiert -> fix")
check("CVE-2026-7" not in kb, "Kernel: laufende Version schon behoben -> kein Befund")
kb2 = cve_pruefung.debian_bewerten(KERNEL_PAKETE, K_AUSZUG, "trixie", "6.12.113-1")
check(sorted(b["cve"] for b in kb2) == ["CVE-2026-8"],
      "Kernel: massgeblich ist der LAUFENDE Kernel, nicht das aelteste installierte Image",
      str([b["cve"] for b in kb2]))

FH = cve_pruefung.fremde_herkunft
check(FH({"installiert": "24.22.2-1nodesource1",
          "quellen": {"24.22.2-1nodesource1": ["nodistro/main"],
                      "20.19.2+dfsg-1+deb13u2": ["trixie/main"]}}, "trixie"),
      "NodeSource-Stand gilt als fremd, obwohl Debian dasselbe Quellpaket fuehrt")
check(not FH({"installiert": "1.0-1", "quellen": {"1.0-2": ["trixie/main"]}}, "trixie"),
      "veralteter Debian-Stand (nur dpkg-Status) gilt NICHT als fremd")
check(not FH({"installiert": "1.0-1+deb13u1",
              "quellen": {"1.0-1+deb13u1": ["trixie-security/main"]}}, "trixie"),
      "Stand aus trixie-security ist Debian")
check(FH({"installiert": "1.0", "quellen": {}}, "trixie"),
      "in keinem Paketindex (lokal installiert) -> nicht ueber Debian pruefbar")
_echt_pol = cve_apt.apt_policy
cve_apt.apt_policy = lambda namen: {
    "nodejs": {"installiert": "24.22.2-1nodesource1",
               "quellen": {"24.22.2-1nodesource1": ["nodistro/main"]}},
    "libfoo1": {"installiert": "2.0-1", "quellen": {"2.0-1": ["trixie/main"]}}}
cve_apt._ARCH = "amd64"
try:
    _bf = [{"pakete": ["nodejs"], "cve": "A"}, {"pakete": ["libfoo1", "nodejs"], "cve": "B"}]
    _fr = cve_pruefung.herkunft_pruefen(_bf, PAKETE, "trixie")
finally:
    cve_apt.apt_policy = _echt_pol
check(_fr == ["nodejs"], "fremde Pakete werden genannt", str(_fr))
check([b["cve"] for b in _bf] == ["B"] and _bf[0]["pakete"] == ["libfoo1"],
      "nur-fremde Befunde fallen weg, gemischte behalten die Debian-Pakete", str(_bf))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3. Schwelle und Plan")
# ═══════════════════════════════════════════════════════════════════════════
E = cve_pruefung.erreicht_schwelle
check(E("", "ab_mittel") and E("", "alle"), "nicht eingestuft erreicht jede Schwelle")
check(not E("unimportant", "ab_niedrig") and E("unimportant", "alle"), "unwichtig nur bei 'alle'")
check(not E("low", "ab_mittel") and E("low", "ab_niedrig"), "niedrig ab 'ab_niedrig'")


def befund(klasse, einst="", sich=True, mit=("a",), bereich="debian"):
    return {"bereich": bereich, "klasse": klasse, "einstufung": einst,
            "aus_sicherheitsquelle": sich, "beheben_mit": list(mit)}


ERG = {"befunde": [befund("behebbar", mit=("p1",)),
                   befund("behebbar", "unimportant", mit=("p2",)),
                   befund("behebbar", sich=False, mit=("p3",)),
                   befund("offen", mit=("p4",)),
                   befund("nicht_im_index", "unimportant", mit=("p5",)),
                   befund("behebbar", bereich="python", mit=())],
       "bereiche": {"python": {"lock_modus": False}}}
p1 = cve_pruefung.plan(ERG, {"schwelle": "ab_niedrig", "regulaere_quelle": False})
check(p1["debian"] == ["p1"], "Vorgabe: nur Sicherheitsquelle, ohne unwichtig", str(p1["debian"]))
check(p1["nur_regulaere_quelle"] == 1, "nicht behobene regulaere Faelle werden gezaehlt")
check(p1["index"] is False, "Index-Fall unter der Schwelle loest kein Update des Index aus")
p2 = cve_pruefung.plan(ERG, {"schwelle": "ab_niedrig", "regulaere_quelle": True})
check(p2["debian"] == ["p1", "p3"], "mit Schalter auch die regulaere Quelle", str(p2["debian"]))
p3 = cve_pruefung.plan(ERG, {"schwelle": "ab_niedrig", "regulaere_quelle": False}, "alle")
check(p3["debian"] == ["p1", "p2"] and p3["index"] is True,
      "Auftrags-Schwelle 'alle' ueberstimmt die Vorgabe", str(p3))
check(p1["python"] is True, "Python-Behebung im Plan")
# Lock-Modus: python_pruefen mit einer Attrappe von abhaengigkeiten, die die
# ECHTEN Namen und Rueckgabeformen stellt (installiert/schwachstellen/lock_modus).
import types  # noqa: E402
_abh = types.ModuleType("backend.abhaengigkeiten")
_abh.installiert = lambda: {"filelock": "3.29.1"}
_abh.schwachstellen = lambda inst: [
    {"paket": "filelock", "version": "3.29.1", "id": "GHSA-x", "aliase": ["CVE-2026-1", "GHSA-x"],
     "behoben_in": "4.2.1", "ausgenommen": False},
    {"paket": "filelock", "version": "3.29.1", "id": "GHSA-y", "aliase": ["GHSA-y"],
     "behoben_in": None, "ausgenommen": False},
    # Derselbe Fund wie GHSA-x unter seiner PYSEC-Kennung (OSV fuehrt beide).
    {"paket": "filelock", "version": "3.29.1", "id": "PYSEC-x", "aliase": ["CVE-2026-1", "PYSEC-x"],
     "behoben_in": "4.10.0", "ausgenommen": False},
    # Zweimal dieselbe Luecke, nur der ZWEITE Eintrag bewertet -> die Luecke gilt
    # als bewertet (der zweite, damit "erster gewinnt" auffaellt).
    {"paket": "torch", "version": "2.12.0", "id": "PYSEC-t", "aliase": ["CVE-2026-2", "PYSEC-t"],
     "behoben_in": None, "ausgenommen": False},
    {"paket": "torch", "version": "2.12.0", "id": "GHSA-t", "aliase": ["CVE-2026-2", "GHSA-t"],
     "behoben_in": "2.13.0", "ausgenommen": True}]
_abh_alt = sys.modules.get("backend.abhaengigkeiten")
sys.modules["backend.abhaengigkeiten"] = _abh
import backend as _backend_pkg  # noqa: E402
_attr_alt = getattr(_backend_pkg, "abhaengigkeiten", None)
_backend_pkg.abhaengigkeiten = _abh
try:
    _abh.lock_modus = lambda: True
    _pl = cve_pruefung.python_pruefen()
    _abh.lock_modus = lambda: False
    _pf = cve_pruefung.python_pruefen()
finally:
    if _abh_alt is not None:
        sys.modules["backend.abhaengigkeiten"] = _abh_alt
    else:
        sys.modules.pop("backend.abhaengigkeiten", None)
    if _attr_alt is not None:
        _backend_pkg.abhaengigkeiten = _attr_alt
    else:
        delattr(_backend_pkg, "abhaengigkeiten")
check([b["klasse"] for b in _pl["befunde"]] == ["lock", "offen", "ausgenommen"],
      "Lock-Modus: Python-Behebung heisst 'lock', nicht 'behebbar'", str([b["klasse"] for b in _pl["befunde"]]))
check([b["klasse"] for b in _pf["befunde"]] == ["behebbar", "offen", "ausgenommen"],
      "ohne Lock-Modus bleibt es 'behebbar'")
_fl = [b for b in _pf["befunde"] if b["cve"] == "CVE-2026-1"]
check(len(_fl) == 1, "GHSA- und PYSEC-Eintrag derselben CVE sind EIN Befund", str(len(_fl)))
check(len(_fl) == 1 and _fl[0]["fix"] == "4.10.0"
      and {"GHSA-x", "PYSEC-x"} <= set(_fl[0]["aliase"]),
      "gebuendelt gilt die hoehere Behebung (numerisch, nicht als Text) und beide Kennungen",
      str(_fl))
_ids = [cve_pruefung.schluessel(b) for b in _pf["befunde"]]
check(len(_ids) == len(set(_ids)), "keine Befund-ID doppelt", str(_ids))
_erg_lock = {"befunde": _pl["befunde"], "bereiche": {"python": _pl["info"]}}
check(cve_pruefung.plan(_erg_lock, cve_pruefung.VORGABEN)["python"] is False,
      "im Lock-Modus wird Python nie automatisch gehoben")
_z = {"lock": 1, "behebbar": 0}
_kb = cve_pruefung.kurzbericht({"ok": True, "zaehler": _z, "beheben": True, "bereiche": {},
                                "behebung": {"plan": {"nur_regulaere_quelle": 3}, "debian": []}})
check("Lock-Datei" in _kb and "regulären Quelle" in _kb,
      "der Kurzbericht nennt, WARUM nichts gehoben wurde", _kb)
check(not any(b["klasse"] == "offen" and "p4" in cve_pruefung.plan(ERG, cve_pruefung.VORGABEN)["debian"]
              for b in ERG["befunde"]), "offene Luecken (ohne Behebung) stehen nie im Plan")

_ein = {"befunde": [
    {"bereich": "debian", "quelle": "brotli", "klasse": "behebbar", "beheben_mit": ["libbrotli1", "brotli"]},
    {"bereich": "debian", "quelle": "brotli", "klasse": "offen", "beheben_mit": ["fremd1"]},
    {"bereich": "debian", "quelle": "anders", "klasse": "behebbar", "beheben_mit": ["anders1"]},
    {"bereich": "python", "quelle": "brotli", "klasse": "behebbar", "beheben_mit": ["pip1"]}]}
check(cve_pruefung.einzeln_pakete(_ein, "brotli") == ["brotli", "libbrotli1"],
      "Einzel-Update: genau die behebbaren Pakete DIESES Debian-Quellpakets",
      str(cve_pruefung.einzeln_pakete(_ein, "brotli")))
check(cve_pruefung.einzeln_pakete(_ein, "gibtsnicht") == [] and cve_pruefung.einzeln_pakete(None, "brotli") == [],
      "unbekanntes Quellpaket oder kein Ergebnis -> nichts")
_lr = ""
for _n in ast.walk(ast.parse((ROOT / "backend" / "cve_pruefung.py").read_text(encoding="utf-8"))):
    if isinstance(_n, ast.FunctionDef) and _n.name == "lauf_einzeln":
        _lr = ast.unparse(_n)
check("einzeln_pakete(" in _lr and "_sperre.acquire(blocking=False)" in _lr,
      "lauf_einzeln nimmt nur Pakete aus dem Ergebnis und haelt die Laufsperre")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("4. Beheben (Broker-Seite) mit Attrappe fuer apt/dpkg")
# ═══════════════════════════════════════════════════════════════════════════
POLICY = """foo:
  Installed: 1.0-1
  Candidate: 1.0-1+deb13u1
  Version table:
     1.0-1+deb13u1 500
        500 http://security.debian.org/debian-security trixie-security/main amd64 Packages
 *** 1.0-1 500
        500 http://deb.debian.org/debian trixie/main amd64 Packages
        100 /var/lib/dpkg/status
bar:
  Installed: 2.0-1
  Candidate: 2.0-2
  Version table:
     2.0-2 500
        500 http://deb.debian.org/debian trixie/main amd64 Packages
 *** 2.0-1 100
        100 /var/lib/dpkg/status
held:
  Installed: 1.0-1
  Candidate: 1.0-2
  Version table:
     1.0-2 500
        500 http://security.debian.org/debian-security trixie-security/main amd64 Packages
"""
aufrufe = []
SIM = {"text": "Inst foo [1.0-1] (1.0-1+deb13u1 Debian-Security:13/stable-security [amd64])\n"}


class _R:
    def __init__(self, out="", rc=0):
        self.stdout, self.stderr, self.returncode = out, "", rc


def attrappe(cmd, timeout=120, env=None):
    aufrufe.append(list(cmd))
    if cmd[0] == "dpkg-query":
        return _R("ii\tfoo:amd64\tfoo\nii\tbar:amd64\tbar\nhi\theld:amd64\theld\n")
    if cmd[:2] == ["apt-cache", "policy"]:
        return _R(POLICY)
    if cmd[0] == "apt-get" and "-s" in cmd:
        return _R(SIM["text"])
    if cmd[0] == "apt-get":
        return _R("ok")
    return _R("")


_echt_run = cve_apt._run
cve_apt._run = attrappe
cve_apt._ARCH = "amd64"
try:
    r = cve_apt.beheben(["foo; rm -rf /"], True)
    check(r["ok"] is False and "Ungueltiger Paketname" in r["fehler"], "Namensmuster greift")
    r = cve_apt.beheben(["p%d" % i for i in range(cve_apt.MAX_PAKETE + 1)], True)
    check(r["ok"] is False, "zu viele Pakete werden abgelehnt")
    r = cve_apt.beheben("foo", True)
    check(r["ok"] is False, "ein String statt einer Liste wird abgelehnt")
    aufrufe.clear()
    r = cve_apt.beheben(["foo", "bar", "held", "fehlt"], True)
    echt = [c for c in aufrufe if c[0] == "apt-get" and "-s" not in c]
    check(r["ok"] is True and [i["paket"] for i in r["installiert"]] == ["foo"],
          "nur foo wird gehoben", json.dumps(r)[:200])
    check(r["uebersprungen"].get("held", "").startswith("zurueckgehalten"), "hold wird nicht angefasst")
    check("regulaeren" in r["uebersprungen"].get("bar", ""),
          "nur Sicherheitsquelle: bar (regulaer) wird uebersprungen")
    check(r["uebersprungen"].get("fehlt") == "nicht installiert", "nicht installiert wird uebersprungen")
    check(len(echt) == 1 and "--only-upgrade" in echt[0] and "--no-remove" in echt[0],
          "der echte Aufruf traegt --only-upgrade und --no-remove", str(echt))
    check(len(echt) == 1 and echt[0][echt[0].index("--") + 1:] == ["foo"],
          "der echte Aufruf nennt GENAU die Zielpakete", str(echt))
    check(not any("autoremove" in c for c in aufrufe), "kein autoremove")
    aufrufe.clear()
    r = cve_apt.beheben(["foo", "bar"], nur_sicherheit=False)
    echt = [c for c in aufrufe if c[0] == "apt-get" and "-s" not in c]
    check(len(echt) == 1 and echt[0][echt[0].index("--") + 1:] == ["foo", "bar"],
          "mit regulaerer Quelle auch bar", str(echt))
    aufrufe.clear()
    SIM["text"] = "Inst foo [1.0-1] (1.0-1+deb13u1)\nRemv wichtig [3.0]\n"
    r = cve_apt.beheben(["foo"], True)
    echt = [c for c in aufrufe if c[0] == "apt-get" and "-s" not in c]
    check(r["ok"] is False and not echt, "plant apt eine Entfernung, wird NICHT installiert")
    aufrufe.clear()
    r = cve_apt.beheben([], True, index=True)
    check(any(c[-1] == "update" for c in aufrufe) and r["index"] is True,
          "index=True aktualisiert den Paketindex")
finally:
    cve_apt._run = _echt_run

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("5. Auftragsart cve_pruefung")
# ═══════════════════════════════════════════════════════════════════════════
SCHED = (ROOT / "backend" / "scheduler.py").read_text(encoding="utf-8")
baum = ast.parse(SCHED)
fn = {n.name: n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
whitelist = set()
for n in ast.walk(fn.get("add_job") or ast.Module(body=[], type_ignores=[])):
    if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "kind" \
            and isinstance(n.ops[0], ast.In) and isinstance(n.comparators[0], ast.Tuple):
        whitelist |= {e.value for e in n.comparators[0].elts if isinstance(e, ast.Constant)}
check("cve_pruefung" in whitelist, "cve_pruefung steht in der Whitelist von add_job",
      str(sorted(whitelist)))


def kette(knoten):
    """If/elif-Kette als Liste der Bedingungen (Quelltext), in Reihenfolge."""
    erg = []
    while isinstance(knoten, ast.If):
        erg.append(ast.unparse(knoten.test))
        knoten = knoten.orelse[0] if len(knoten.orelse) == 1 else None
    return erg


bedingungen = []
for n in ast.walk(fn.get("_execute") or ast.Module(body=[], type_ignores=[])):
    if isinstance(n, ast.If) and "reminder" in ast.unparse(n.test):
        bedingungen = kette(n)
        break
i_cve = next((i for i, b in enumerate(bedingungen) if "'cve_pruefung'" in b), -1)
i_agent = next((i for i, b in enumerate(bedingungen) if "_agent_manager" in b), -1)
check(i_cve >= 0 and i_agent >= 0 and i_cve < i_agent,
      "_execute: der cve-Zweig steht VOR dem Agenten-Zweig", str(bedingungen))
uf = set()
for n in ast.walk(baum):
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "UPDATABLE_FIELDS" for t in n.targets):
        uf = {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
check(uf and not ({"kind", "payload"} & uf), "kind/payload bleiben aus UPDATABLE_FIELDS", str(uf))
setp = ast.unparse(fn.get("set_cve_payload") or ast.Pass())
check("!= 'cve_pruefung'" in setp and "raise ValueError" in setp,
      "set_cve_payload lehnt jede andere Art ab")
check(cve_pruefung.auftrag_payload({"beheben": "ja"})["beheben"] is False,
      "nur ein echtes True behebt (\"ja\" nicht)")
check(cve_pruefung.auftrag_payload({"beheben": True, "schwelle": "alle"})
      == {"beheben": True, "schwelle": "alle"}, "gueltige Optionen kommen durch")
try:
    cve_pruefung.auftrag_payload({"schwelle": "kritisch"})
    check(False, "unbekannte Schwelle wird abgelehnt")
except ValueError:
    check(True, "unbekannte Schwelle wird abgelehnt")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("6. Broker")
# ═══════════════════════════════════════════════════════════════════════════
OPS = (ROOT / "backend" / "broker" / "ops.py").read_text(encoding="utf-8")
DAEMON = (ROOT / "backend" / "broker" / "daemon.py").read_text(encoding="utf-8")
reg = None
for n in ast.walk(ast.parse(OPS)):
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_REGISTRY" for t in n.targets):
        reg = n.value
schl = [k.value for k in (reg.keys if isinstance(reg, ast.Dict) else []) if isinstance(k, ast.Constant)]
check("cve_beheben" in schl, "Op cve_beheben ist registriert")
lange = set()
for n in ast.walk(ast.parse(DAEMON)):
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "LANGE_OPS" for t in n.targets):
        lange = {c.value for c in ast.walk(n.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
check("cve_beheben" in lange, "cve_beheben laeuft als lange Op (sonst Abbruch nach 900 s)")
op_rumpf = ""
for n in ast.walk(ast.parse(OPS)):
    if isinstance(n, ast.FunctionDef) and n.name == "_op_cve_beheben":
        op_rumpf = ast.unparse(n)
check("is not False" in op_rumpf, "nur_sicherheit ist fail-closed (nur ein echtes False oeffnet)")
STDLIB = set(sys.stdlib_module_names) | {"__future__", "backend"}
fremd = []
for n in ast.walk(ast.parse((ROOT / "backend" / "cve_apt.py").read_text(encoding="utf-8"))):
    if isinstance(n, ast.Import):
        fremd += [a.name for a in n.names if a.name.split(".")[0] not in STDLIB]
    elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] not in STDLIB:
        fremd.append(n.module)
check(not fremd, "cve_apt importiert nur die Standardbibliothek (Broker = System-Python)", str(fremd))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("7. Badge und Quittung")
# ═══════════════════════════════════════════════════════════════════════════
bef7 = [
    {"bereich": "debian", "quelle": "nodejs", "cve": "CVE-1", "klasse": "offen"},
    {"bereich": "debian", "quelle": "nodejs", "cve": "CVE-2", "klasse": "offen"},
    {"bereich": "debian", "quelle": "brotli", "cve": "CVE-3", "klasse": "behebbar"},
    {"bereich": "python", "quelle": "jinja2", "cve": "CVE-4", "klasse": "ausgenommen"},
]
for b in bef7:
    b["id"] = cve_pruefung.schluessel(b)
    b["quittierbar"] = b["klasse"] in cve_pruefung.QUITTIERBAR
cve_pruefung._speichern({"ts": 1, "befunde": bef7})
b0 = cve_pruefung.badge()
check(b0["anzahl"] == 2, "je PAKET gezaehlt, ausgenommene nicht", json.dumps(b0)[:200])
check(b0["posten"] and b0["posten"][0]["titel"] == "brotli", "behebbar steht zuoberst")
n = cve_pruefung.quittieren(alle=True)
check(n == 2, "alle quittierbaren (zwei offene) quittiert", str(n))
b1 = cve_pruefung.badge()
check(b1["anzahl"] == 1 and b1["posten"][0]["titel"] == "brotli",
      "nach Quittung bleibt nur das Behebbare", json.dumps(b1)[:200])
cve_pruefung.quittieren(ids=[bef7[2]["id"]])
check(cve_pruefung.badge()["anzahl"] == 1, "behebbar laesst sich NICHT quittieren")
_lk = {"bereich": "python", "quelle": "filelock", "cve": "CVE-5", "klasse": "lock"}
_lk["id"] = cve_pruefung.schluessel(_lk)
_lk["quittierbar"] = _lk["klasse"] in cve_pruefung.QUITTIERBAR
check(_lk["quittierbar"] is False, "Lock-Fall ist nicht als gesehen markierbar (Vorgabe 2026-10-29)")
cve_pruefung._speichern({"ts": 3, "befunde": bef7 + [_lk]})
cve_pruefung.quittieren(alle=True)
cve_pruefung.quittieren(ids=[_lk["id"]])
check(any(x["titel"] == "filelock" for x in cve_pruefung.badge()["posten"]),
      "Lock-Fall bleibt nach 'alle als gesehen' in der Badge")
neu = dict(bef7[0], cve="CVE-9")
neu["id"] = cve_pruefung.schluessel(neu)
cve_pruefung._speichern({"ts": 2, "befunde": bef7 + [neu]})
check(cve_pruefung.badge()["anzahl"] == 2, "eine NEUE Luecke im quittierten Paket erscheint wieder")

# Nach einem Neustart prueft niemand neu – die Klasse "neustart" darf dann
# nicht aus dem gespeicherten Ergebnis weiterleben (ECHT 2026-10-29: 672).
_kb = []
for _cve, _fix, _kl in (("CVE-K1", "6.12.113-1", "neustart"), ("CVE-K2", "6.12.112-1", "neustart"),
                        ("CVE-K3", "6.12.120-1", "behebbar"), ("CVE-K4", "", "offen")):
    _b = {"bereich": "debian", "quelle": "linux", "cve": _cve, "klasse": _kl, "fix": _fix,
          "kernel": True}
    _b["id"] = cve_pruefung.schluessel(_b)
    _kb.append(_b)
_kd = {"bereich": "debian", "quelle": "brotli", "cve": "CVE-K5", "klasse": "behebbar",
       "fix": "1.0", "kernel": False}
_kd["id"] = cve_pruefung.schluessel(_kd)
_kerg = {"ts": 4, "befunde": _kb + [_kd], "zaehler": {"neustart": 2, "offen": 1, "behebbar": 2},
         "bereiche": {"debian": {"kernel": "6.12.111-1", "neustart_noetig": True}}}
_orig_lk = cve_pruefung.laufender_kernel
try:
    cve_pruefung.laufender_kernel = lambda: "6.12.111-1"
    cve_pruefung._speichern(_kerg)
    _z = cve_pruefung.zustand_ergebnis()
    check(_z["zaehler"].get("neustart") == 2,
          "Positivkontrolle: unter dem Kernel der Pruefung bleibt 'neustart' stehen",
          str(_z["zaehler"]))
    cve_pruefung.laufender_kernel = lambda: "6.12.113-1"
    cve_pruefung._speichern(dict(_kerg, ts=5))
    _z = cve_pruefung.zustand_ergebnis()
    _ids = {b.get("cve") for b in _z.get("befunde") or []}
    check(_z["zaehler"].get("neustart") == 0,
          "nach dem Neustart auf den behobenen Kernel: 0 'neustart'", str(_z["zaehler"]))
    check(_ids == {"CVE-K3", "CVE-K4", "CVE-K5"},
          "nur Kernel-Befunde mit Fix <= laufendem Kernel fallen weg", str(sorted(_ids)))
    check(_z["zaehler"].get("offen") == 1 and _z["zaehler"].get("behebbar") == 2,
          "uebrige Zaehler bleiben", str(_z["zaehler"]))
    check(_z["bereiche"]["debian"]["kernel"] == "6.12.113-1"
          and _z["bereiche"]["debian"].get("kernel_bei_pruefung") == "6.12.111-1",
          "Anzeige nennt den laufenden und den gepruefen Kernel")
    check(not any(p["titel"] == "linux" and p["zaehler"].get("neustart")
                  for p in cve_pruefung.badge()["posten"]),
          "Badge zaehlt keinen erledigten Neustart mehr")
    check(json.loads(cve_pruefung.ERGEBNIS.read_text()).get("zaehler", {}).get("neustart") == 2,
          "die Datei selbst bleibt unberuehrt (Angleichung nur beim Lesen)")
finally:
    cve_pruefung.laufender_kernel = _orig_lk

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8. Ort der Badge: am Paket-Symbol, nicht am Zahnrad")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_mfn = {n.name: n for n in ast.walk(ast.parse(MAIN))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _rumpf(name):
    """Rumpf OHNE Docstring – ein Waechter, der seine Begruendung liest, prueft nichts."""
    f = _mfn.get(name)
    if not f:
        return ""
    k = list(f.body)
    if k and isinstance(k[0], ast.Expr) and isinstance(getattr(k[0], "value", None), ast.Constant):
        k = k[1:]
    return "\n".join(ast.unparse(x) for x in k)


_gear = _rumpf("_admin_badge_messen")
check(bool(_gear) and "cve_pruefung" not in _gear, "das Zahnrad zaehlt KEINE Sicherheitsluecken")
_me = _rumpf("get_me")
check("'cve_badge': cve_badge" in _me, "/api/me liefert cve_badge")
_i_admin, _i_call = _me.find("if ist_admin:"), _me.find("_cve.badge")
check(0 <= _i_admin < _i_call, "cve_badge wird nur im Admin-Zweig gefuellt", f"{_i_admin}/{_i_call}")
SP = (ROOT / "frontend" / "js" / "syspackages.js").read_text(encoding="utf-8")
check("d.cve_badge" in SP and "jv-pkg-badge" in SP, "syspackages.js malt die Badge aus cve_badge")
SB = (ROOT / "frontend" / "js" / "settings_btn.js").read_text(encoding="utf-8")
check("cve" not in SB.lower(), "settings_btn.js (Zahnrad) kennt keine CVE-Posten mehr")

ende()
