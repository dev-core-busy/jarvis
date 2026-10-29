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
import time
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

# Offene Eintraege: Behebung in ANDEREN Releases, Zwischenrelease, Art der
# Nicht-Meldung (der 7zip-Fall vom 2026-10-29). Ueber den Auszug aus einer
# echten gepackten Datei, damit Auszug UND Bewertung gemessen sind.
_sz = {"7zip": {
    "CVE-2026-48092": {"description": "a", "releases": {
        "trixie": {"status": "open", "urgency": "unimportant", "repositories": {},
                   "next_point_update": True},
        "forky": {"status": "resolved", "fixed_version": "26.01+dfsg-1"},
        "sid": {"status": "resolved", "fixed_version": "26.01+dfsg-1"},
        "bookworm": {"status": "resolved", "fixed_version": "22.01+really26.01+dfsg-0+deb12u1"}}},
    "CVE-2026-58052": {"description": "b", "releases": {
        "trixie": {"status": "open", "urgency": "not yet assigned", "repositories": {},
                   "nodsa": "Only affects Windows NTFS", "nodsa_reason": "ignored"},
        "sid": {"status": "resolved", "fixed_version": "26.03+dfsg-1"},
        "bookworm": {"status": "resolved", "fixed_version": "0"},
        # Status entscheidet, nicht das Feld: ein offener Eintrag mit Version
        # ist keine Behebung.
        "forky": {"status": "open", "fixed_version": "26.04+dfsg-1"}}},
    "CVE-2022-47111": {"description": "c", "releases": {
        "trixie": {"status": "open", "urgency": "unimportant", "repositories": {}},
        "sid": {"status": "open"}}}}}
with gzip.open(cve_pruefung.TRACKER_CACHE, "wt", encoding="utf-8") as _f:
    json.dump(_sz, _f)
_bsz = {b["cve"]: b for b in cve_pruefung.debian_bewerten(
    [pk("7zip", "7zip", "25.01+dfsg-1~deb13u1")], cve_pruefung.tracker_auszug({"7zip"}, "trixie"), "trixie")}
check(_bsz.get("CVE-2026-48092", {}).get("klasse") == "offen"
      and _bsz.get("CVE-2026-48092", {}).get("zwischenrelease") is True,
      "offener Eintrag mit next_point_update -> Zwischenrelease markiert")
check(_bsz.get("CVE-2026-48092", {}).get("anderswo") == [
          {"version": "26.01+dfsg-1", "releases": ["forky", "sid"]},
          {"version": "22.01+really26.01+dfsg-0+deb12u1", "releases": ["bookworm"]}],
      "Behebung anderswo: je Version gruppiert, hoechste zuerst",
      str(_bsz.get("CVE-2026-48092", {}).get("anderswo")))
check(_bsz.get("CVE-2026-58052", {}).get("anderswo") == [{"version": "26.03+dfsg-1", "releases": ["sid"]}],
      "fixed_version 0 (nie betroffen) und offene Releases zaehlen nicht als Behebung",
      str(_bsz.get("CVE-2026-58052", {}).get("anderswo")))
check(_bsz.get("CVE-2026-58052", {}).get("nodsa") == "Only affects Windows NTFS"
      and _bsz.get("CVE-2026-58052", {}).get("nodsa_grund") == "ignored",
      "nodsa behaelt die Begruendung, die Art steht getrennt",
      str({k: _bsz.get("CVE-2026-58052", {}).get(k) for k in ("nodsa", "nodsa_grund")}))
check(_bsz.get("CVE-2022-47111", {}).get("anderswo") == []
      and _bsz.get("CVE-2022-47111", {}).get("zwischenrelease") is False,
      "nirgends behoben, nichts eingeplant -> leere Angaben")
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
check(_pl["info"].get("stand") == cve_pruefung.python_stand({"filelock": "3.29.1"}),
      "das Ergebnis traegt den Stand der installierten Pakete (fuer nach_paketwechsel)",
      str(_pl["info"]))
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

# Nach einem Lock-Install prueft niemand neu – Python-Befunde, deren Behebung
# die installierte Fassung traegt, duerfen nicht weiterleben (ECHT 2026-10-29:
# setuptools/sentence-transformers/torch/transformers, alle laengst gehoben).
_pyb = []
for _q, _v, _cve, _fix, _kl in (
        ("setuptools", "74.1.3", "CVE-P1", "78.1.1", "lock"),         # weg: 81.0.0 >= 78.1.1
        ("setuptools", "74.1.3", "CVE-P2", "83.0.0", "ausgenommen"),  # bleibt: 81 < 83
        ("sentence-transformers", "3.4.1", "CVE-P3", "5.6.0", "lock"),  # weg
        ("torch", "2.12.0+cpu", "CVE-P4", "2.13.0", "lock"),          # weg: lokales Suffix
        ("transformers", "4.57.6", "CVE-P5", "", "offen"),            # bleibt: keine Behebung
        ("zahlpaket", "8.0", "CVE-P6", "9.1", "lock"),                # weg: 10.0 > 9.1 numerisch
        ("kaputtpaket", "1.0", "CVE-P7", "1.1", "lock"),              # bleibt: unlesbare Fassung
        ("verschwunden", "1.0", "CVE-P8", "1.1", "lock"),             # bleibt: nicht gefunden
        ("gleichpaket", "2.0", "CVE-P9", "1.0", "lock")):             # bleibt: unveraendert
    _b = {"bereich": "python", "quelle": _q, "cve": _cve, "version": _v, "fix": _fix,
          "klasse": _kl, "kernel": False}
    _b["id"] = cve_pruefung.schluessel(_b)
    _pyb.append(_b)
# Gleicher Name, anderer Bereich: das Debian-Paket "setuptools" ist ein anderes.
_pdeb = {"bereich": "debian", "quelle": "setuptools", "cve": "CVE-P10", "version": "78.1.1-0.1",
         "fix": "78.1.1", "klasse": "offen", "kernel": False}
_pdeb["id"] = cve_pruefung.schluessel(_pdeb)
_perg = {"ts": 6, "befunde": _pyb + [_pdeb],
         "zaehler": {"lock": 6, "ausgenommen": 1, "offen": 2},
         "bereiche": {"python": {"geprueft": True, "lock_modus": True}}}
_ALT = {"setuptools": "74.1.3", "sentence-transformers": "3.4.1", "torch": "2.12.0+cpu",
        "transformers": "4.57.6", "zahlpaket": "8.0", "kaputtpaket": "1.0", "gleichpaket": "2.0",
        "verschwunden": "1.0"}
_NEU = {"setuptools": "81.0.0", "sentence-transformers": "5.7.0", "torch": "2.13.0+cpu",
        "transformers": "5.21.1", "zahlpaket": "10.0", "kaputtpaket": "nicht-pep440!",
        "gleichpaket": "2.0"}
_orig_pi, _orig_ss = cve_pruefung.python_installiert, cve_pruefung._site_stempel
_inst = {"wert": _ALT}
_stempel = {"wert": ("a", 1)}
try:
    cve_pruefung.laufender_kernel = lambda: ""
    cve_pruefung.python_installiert = lambda: _inst["wert"]
    cve_pruefung._site_stempel = lambda: _stempel["wert"]
    cve_pruefung._speichern(_perg)
    _z = cve_pruefung.zustand_ergebnis()
    check(len(_z["befunde"]) == 10 and "nachgefuehrt" not in _z["bereiche"]["python"],
          "Positivkontrolle: unter den Fassungen der Pruefung bleibt alles stehen",
          str(len(_z["befunde"])))
    # Cache: dieselbe Datei, derselbe Stempel -> der gemerkte Stand (gegen
    # diese Kontrolle beweist erst der naechste Schritt den Stempel im Schluessel).
    _inst["wert"] = _NEU
    _z = cve_pruefung.zustand_ergebnis()
    check(len(_z["befunde"]) == 10, "Positivkontrolle: ohne neuen Stempel bleibt der Cache stehen",
          str(len(_z["befunde"])))
    _stempel["wert"] = ("a", 2)
    _z = cve_pruefung.zustand_ergebnis()
    _ids = {b["cve"] for b in _z["befunde"]}
    check(_ids == {"CVE-P2", "CVE-P5", "CVE-P7", "CVE-P8", "CVE-P9", "CVE-P10"},
          "nach dem Paketwechsel (neuer Stempel der site-packages) fallen genau die "
          "nachweislich behobenen Python-Befunde weg", str(sorted(_ids)))
    check("CVE-P4" not in _ids, "Lokales Suffix: 2.13.0+cpu traegt die Behebung 2.13.0")
    check("CVE-P6" not in _ids, "Versionsvergleich numerisch, nicht als Text (10.0 > 9.1)")
    check("CVE-P10" in _ids, "ein Debian-Paket gleichen Namens bleibt unberuehrt")
    check(_z["zaehler"].get("lock") == 3 and _z["zaehler"].get("ausgenommen") == 1
          and _z["zaehler"].get("offen") == 2,
          "Zaehler neu gerechnet", str(_z["zaehler"]))
    check(_z["bereiche"]["python"].get("nachgefuehrt") == sorted([
              "sentence-transformers 3.4.1 → 5.7.0", "setuptools 74.1.3 → 81.0.0",
              "torch 2.12.0+cpu → 2.13.0+cpu", "zahlpaket 8.0 → 10.0"])
          and _z["bereiche"]["python"].get("lock_modus") is True,
          "der Bereich nennt, was angeglichen wurde, und behaelt seine Felder",
          str(_z["bereiche"]["python"]))
    check(not any(p["titel"] in ("sentence-transformers", "torch") for p in cve_pruefung.badge()["posten"]),
          "Badge zaehlt die gehobenen Pakete nicht mehr")
    check(len(json.loads(cve_pruefung.ERGEBNIS.read_text()).get("befunde") or []) == 10,
          "die Datei selbst bleibt unberuehrt (Angleichung nur beim Lesen)")
    _inst["wert"] = None
    _stempel["wert"] = ("a", 3)
    check(len(cve_pruefung.zustand_ergebnis()["befunde"]) == 10,
          "Fassungen nicht ermittelbar -> nichts angeglichen")
finally:
    cve_pruefung.laufender_kernel = _orig_lk
    cve_pruefung.python_installiert, cve_pruefung._site_stempel = _orig_pi, _orig_ss
_echt = cve_pruefung.python_installiert()
check(_echt is None or (isinstance(_echt, dict) and all(isinstance(v, str) for v in _echt.values())),
      "python_installiert liefert Name -> Fassung (oder None)")
check(cve_pruefung.python_stand({"a": "1", "b": "2"}) == cve_pruefung.python_stand({"b": "2", "a": "1"})
      and cve_pruefung.python_stand({"a": "1"}) != cve_pruefung.python_stand({"a": "1.1"}),
      "der Stand haengt an Name+Fassung, nicht an der Reihenfolge")

# nach_paketwechsel: neu pruefen genau dann, wenn der Stand abweicht.
def _npw():
    """Ein Wurf ist ein FAIL, kein Abbruch ohne Bilanz (Register)."""
    try:
        return cve_pruefung.nach_paketwechsel()
    except Exception as e:  # noqa: BLE001
        return f"WURF {type(e).__name__}: {e}"


_abh2 = types.ModuleType("backend.abhaengigkeiten")
_abh2.installiert = lambda: dict(_NEU)
_aufrufe = []
_orig_lauf = cve_pruefung.lauf
_abh_alt = sys.modules.get("backend.abhaengigkeiten")
_attr_alt = getattr(_backend_pkg, "abhaengigkeiten", None)
sys.modules["backend.abhaengigkeiten"] = _abh2
_backend_pkg.abhaengigkeiten = _abh2
try:
    cve_pruefung.lauf = lambda **kw: _aufrufe.append(kw)
    cve_pruefung.ERGEBNIS.unlink()
    check(_npw() is False and not _aufrufe,
          "nie geprueft -> keine Pruefung aus eigenem Antrieb")
    _st = cve_pruefung.python_stand(_NEU)
    cve_pruefung._speichern({"ts": 7, "befunde": [], "bereiche": {"python": {"stand": _st}}})
    check(_npw() is False and not _aufrufe,
          "Positivkontrolle: gleicher Stand -> keine Pruefung")
    cve_pruefung._speichern({"ts": 8, "befunde": [],
                             "bereiche": {"python": {"stand": cve_pruefung.python_stand(_ALT)}}})
    check(_npw() is True
          and _aufrufe == [{"beheben": False, "ausloeser": "paketwechsel"}],
          "anderer Stand -> eine Pruefung OHNE Behebung", str(_aufrufe))
    _aufrufe.clear()
    cve_pruefung._speichern({"ts": 9, "befunde": [], "bereiche": {"python": {"geprueft": True}}})
    check(_npw() is True and len(_aufrufe) == 1,
          "Ergebnis ohne Stand (Altbestand) gilt als gewechselt – unbekannt ist nicht gleich")
    _aufrufe.clear()
    cve_pruefung._status["laeuft"] = True
    check(_npw() is False and not _aufrufe,
          "laeuft schon eine Pruefung -> keine zweite")
finally:
    cve_pruefung._status["laeuft"] = False
    cve_pruefung.lauf = _orig_lauf
    if _abh_alt is not None:
        sys.modules["backend.abhaengigkeiten"] = _abh_alt
    else:
        sys.modules.pop("backend.abhaengigkeiten", None)
    if _attr_alt is not None:
        _backend_pkg.abhaengigkeiten = _attr_alt
    else:
        delattr(_backend_pkg, "abhaengigkeiten")

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

# Nach dem Paket-Abgleich wird neu geprueft – aber nur im Zweig OHNE angesetzten
# Neustart (der kaeme mitten in den Lauf) und NACH dem Skill-Abgleich (der kann
# selbst Pakete wechseln). Regel am Syntaxbaum: echte Aufrufe, keine Woerter.
def _ruft(knoten, name):
    return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
            and (getattr(n.func, "attr", None) == name or getattr(n.func, "id", None) == name
                 or any(getattr(a, "attr", None) == name for a in n.args))]


_weiche = [n for n in ast.walk(_mfn.get("startup_abhaengigkeiten") or ast.Module(body=[]))
           if isinstance(n, ast.If) and any(_ruft(x, "restart_service_delayed") for x in n.body)]
if len(_weiche) != 1:
    print("ABBRUCH: Neustart-Weiche in startup_abhaengigkeiten nicht eindeutig:", len(_weiche))
    ende(2)
_sonst = ast.Module(body=_weiche[0].orelse, type_ignores=[])
_np = _ruft(_sonst, "nach_paketwechsel")
_sk = _ruft(_sonst, "_skill_pakete")
check(len(_np) == 1, "nach_paketwechsel wird im Zweig ohne Neustart aufgerufen", str(len(_np)))
check(not any(_ruft(x, "nach_paketwechsel") for x in _weiche[0].body),
      "nicht im Zweig mit angesetztem Neustart")
check(len(_np) == 1 and len(_sk) == 1 and _sk[0].lineno < _np[0].lineno,
      "erst der Skill-Abgleich, dann die Neupruefung")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("9. Veroeffentlichungsdatum (OSV, dauerhaft gecacht)")
# ═══════════════════════════════════════════════════════════════════════════
# Attrappe mit der ECHTEN Signatur von _osv_datum (Kennung -> "JJJJ-MM-TT" |
# "" unbekannt | None gescheitert) und Zaehler der Abrufe.
_gefragt = []
_antwort = {"CVE-2022-47111": "2025-04-19", "CVE-2099-0001": "", "CVE-2099-0002": None}


def _holen(k):
    _gefragt.append(k)
    return _antwort.get(k, "2024-01-02")


def _bf(cve):
    return {"bereich": "debian", "quelle": "x", "cve": cve, "klasse": "offen"}


cve_pruefung.VEROEFF.unlink(missing_ok=True)
_b = [_bf("CVE-2022-47111"), _bf("CVE-2022-47111"), _bf("CVE-2099-0001"), _bf("CVE-2099-0002")]
_r = cve_pruefung.veroeffentlichung_ergaenzen(_b, holen=_holen)
check(sorted(_gefragt) == ["CVE-2022-47111", "CVE-2099-0001", "CVE-2099-0002"],
      "jede Kennung genau EINMAL gefragt (auch wenn zwei Befunde sie teilen)", str(_gefragt))
check([x["veroeffentlicht"] for x in _b] == ["2025-04-19", "2025-04-19", "", ""],
      "Datum an jedem Befund, unbekannt/gescheitert = leer", str([x["veroeffentlicht"] for x in _b]))
check(_r.get("gescheitert") == 1 and _r.get("ohne_datum") == 2, "Zahlen im Ergebnis", str(_r))
_c = json.loads(cve_pruefung.VEROEFF.read_text(encoding="utf-8"))
check("CVE-2099-0002" not in _c, "ein GESCHEITERTER Abruf wird nicht gemerkt")
check(_c.get("CVE-2099-0001", {}).get("d") == "", "\"unbekannt\" wird gemerkt (mit Zeitpunkt)")

_gefragt.clear()
_b2 = [_bf("CVE-2022-47111"), _bf("CVE-2099-0001"), _bf("CVE-2099-0002")]
cve_pruefung.veroeffentlichung_ergaenzen(_b2, holen=_holen)
check(_gefragt == ["CVE-2099-0002"], "zweiter Lauf fragt nur das Gescheiterte nach", str(_gefragt))
check(_b2[0]["veroeffentlicht"] == "2025-04-19", "bekanntes Datum kommt aus dem Cache")

# "unbekannt" laeuft nach VEROEFF_NEU_S ab – OSV kennt neue CVEs oft erst spaeter.
_c = json.loads(cve_pruefung.VEROEFF.read_text(encoding="utf-8"))
_c["CVE-2099-0001"]["t"] = time.time() - cve_pruefung.VEROEFF_NEU_S - 1
cve_pruefung._schreiben(cve_pruefung.VEROEFF, _c)
_gefragt.clear()
_antwort["CVE-2099-0001"] = "2026-10-01"
cve_pruefung.veroeffentlichung_ergaenzen([_bf("CVE-2099-0001")], holen=_holen)
check(_gefragt == ["CVE-2099-0001"], "abgelaufenes \"unbekannt\" wird neu gefragt", str(_gefragt))

# Ein Abruf, der WIRFT, darf die Pruefung nicht kippen und nicht gecacht werden.
def _wirft(k):
    raise RuntimeError("netz weg")


_b3 = [_bf("CVE-2099-0003")]
_r3 = cve_pruefung.veroeffentlichung_ergaenzen(_b3, holen=_wirft)
check(_b3[0]["veroeffentlicht"] == "" and _r3.get("gescheitert") == 1,
      "werfender Abruf: leeres Datum, als gescheitert gezaehlt", str(_r3))

# Zeitdeckel: was nicht fertig wird, bleibt leer und ungemerkt – der Lauf wartet nicht.
_alt_deckel = cve_pruefung.VEROEFF_DECKEL_S
cve_pruefung.VEROEFF_DECKEL_S = 0.3


def _langsam(k):
    time.sleep(2)
    return "2020-01-01"


_t0 = time.time()
_b4 = [_bf("CVE-2099-0004")]
cve_pruefung.veroeffentlichung_ergaenzen(_b4, holen=_langsam)
_dauer = time.time() - _t0
cve_pruefung.VEROEFF_DECKEL_S = _alt_deckel
check(_dauer < 1.5, "Zeitdeckel haelt den Lauf begrenzt", f"{_dauer:.2f} s")
check(_b4[0]["veroeffentlicht"] == ""
      and "CVE-2099-0004" not in json.loads(cve_pruefung.VEROEFF.read_text(encoding="utf-8")),
      "nicht fertig gewordene Kennung bleibt leer und ungemerkt")

# Die echte Abfrage: Datum aus "published", 404 = unbekannt, anderes = gescheitert.
import io  # noqa: E402
import urllib.error  # noqa: E402
_orig_urlopen = cve_pruefung.urllib.request.urlopen


class _Antw(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_abgerufen = []
_osv = {"DEBIAN-CVE-1": b'{"published": "2025-04-19T21:15:45.217Z"}',
        "CVE-1": b'{"published": "1999-01-01T00:00:00Z"}',
        "CVE-4": b'{"id": "CVE-4"}',
        "CVE-5": b'{"published": "2024-05-06T00:00:00Z"}',
        "GHSA-aaaa-bbbb-cccc": b'{"published": "2023-07-08T00:00:00Z"}'}


def _urlopen(url, timeout=None):
    k = url.rsplit("/", 1)[-1]
    _abgerufen.append(k)
    if k == "DEBIAN-CVE-3":
        raise urllib.error.HTTPError(url, 503, "Busy", {}, None)
    if k not in _osv:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return _Antw(_osv[k])


cve_pruefung.urllib.request.urlopen = _urlopen
try:
    _w = [cve_pruefung._osv_datum(k)
          for k in ("CVE-1", "CVE-2", "CVE-3", "CVE-4", "CVE-5", "GHSA-aaaa-bbbb-cccc")]
finally:
    cve_pruefung.urllib.request.urlopen = _orig_urlopen
check(_w[:4] == ["2025-04-19", "", None, ""],
      "_osv_datum: Debian-Eintrag zuerst / 404 / 503 / ohne Feld", str(_w))
check(_w[4] == "2024-05-06", "ohne Debian-Eintrag gilt die reine Kennung", str(_w))
check(_w[5] == "2023-07-08" and "DEBIAN-GHSA-aaaa-bbbb-cccc" not in _abgerufen,
      "Nicht-CVE-Kennung wird direkt gefragt", str(_abgerufen))

# pruefen() fuellt das Feld – Regel am Syntaxbaum: der Aufruf steht im Rumpf.
_pf = next(n for n in ast.walk(ast.parse(Path(cve_pruefung.__file__).read_text(encoding="utf-8")))
           if isinstance(n, ast.FunctionDef) and n.name == "pruefen")
check(any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "veroeffentlichung_ergaenzen"
          for n in ast.walk(_pf)), "pruefen() ruft veroeffentlichung_ergaenzen")
SP2 = (ROOT / "frontend" / "js" / "syspackages.js").read_text(encoding="utf-8")
check("b.veroeffentlicht" in SP2, "die Befundliste zeigt das Datum (syspackages.js)")
# Der drehende Kreis vor "Pruefung laeuft": syspackages.js laeuft auf JEDER
# Seite, style.css (mit @keyframes spin) nicht – Klasse UND Animation muessen
# deshalb in theme.css stehen, sonst steht dort ein stiller, starrer Ring.
import re as _re  # noqa: E402
TH = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")
_zweig = SP2[SP2.find("if (_cve.laeuft)"):SP2.find("} else if (!erg)")]
check('class="jv-pkg-spin"' in _zweig, "Kreis steht im Zweig \"Pruefung laeuft\"")
_laden = SP2[SP2.find("if (!_cve) {"):SP2.find("var erg = _cve.ergebnis;")]
check('class="jv-pkg-spin"' in _laden and "pkg.cve_laedt" in _laden,
      "Kreis steht im Zweig \"werden geladen\"")
_regel = _re.search(r"\n\.jv-pkg-spin\s*\{([^}]*)\}", TH)
_anim = _re.search(r"animation:\s*([\w-]+)", _regel.group(1)) if _regel else None
check(bool(_anim) and _re.search(r"@keyframes\s+" + _re.escape(_anim.group(1)) + r"\b", TH) is not None,
      "theme.css definiert .jv-pkg-spin samt seiner Keyframes", str(_anim and _anim.group(1)))


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("9. Node.js-Laufzeit und vollstaendige Fremdpaket-Liste")
# ═══════════════════════════════════════════════════════════════════════════
# Anlass (2026-10-29, DEV und ECHT gemessen): nodejs 24.22.2-1nodesource1 war
# nur als "nicht ueber Debian pruefbar" genannt und GAR NICHT geprueft; und
# Fremdpakete ohne Debian-Namen (google-chrome-stable, sentinelagent) standen
# nicht einmal in dieser Liste.
NB = cve_pruefung.node_im_bereich
V = (24, 22, 0)
_faelle = [
    ("22.x || 24.x || 26.x", V, True), ("22.x || 26.x", V, False),
    ("^22.23.4 || ^24.22.1 || ^26.12.1", V, False), ("^24.22.1", (24, 22, 1), True),
    ("^24.22.1", (24, 30, 0), True), ("^24.22.1", (25, 0, 0), False),
    ("^24.1", (24, 0, 9), False), ("^24.1", (24, 9, 0), True),
    ("^0.10.5", (0, 10, 9), True), ("^0.10.5", (0, 11, 0), False),
    ("~24.22.1", (24, 22, 5), True), ("~24.22.1", (24, 23, 0), False),
    ("24.22.x", V, True), ("24.21.x", V, False), ("24.22.0", V, True), ("24.22.1", V, False),
    (">=4.0.0 <4.8.2", (4, 8, 1), True), (">=4.0.0 <4.8.2", (4, 8, 2), False),
    ("<= 4", (4, 9, 9), True), ("<= 4", (5, 0, 0), False),
    (">= 24.22.1", V, False), (">= 24.22.1", (26, 0, 0), True),
    ("*", V, True),
]
_falsch = [f"{a!r} {v}: {NB(a, v)}" for a, v, soll in _faelle if NB(a, v) is not soll]
check(not _falsch, f"semver-Bereiche ({len(_faelle)} Faelle, alle Formen der Datenbank)",
      "; ".join(_falsch))
_unklar = [a for a in ("", "vielleicht 24", "24.x &&& 26.x", ">", "24.x || kaputt")
           if NB(a, V) is not None]
check(not _unklar, "nicht deutbare Bereiche liefern None, nie 'nicht betroffen'", str(_unklar))

_DB = {
    "1": {"cve": ["CVE-2026-100"], "vulnerable": "22.x || 24.x", "patched": "^22.23.4 || ^24.22.1",
          "severity": "high", "description": "Brotli", "ref": "https://nodejs.org/en/blog/x"},
    "2": {"cve": ["CVE-2026-101"], "vulnerable": "24.x || 26.x", "patched": "^26.12.1",
          "severity": "critical", "ref": "http://unsicher.example/"},
    "3": {"cve": ["CVE-2026-102"], "vulnerable": "22.x", "patched": "^22.23.4", "severity": "low"},
    "4": {"cve": ["CVE-2026-103"], "vulnerable": "24.x", "patched": "^24.10.0", "severity": "medium"},
    "5": {"cve": [], "vulnerable": "24.x", "patched": "^24.30.0", "severity": "unknown"},
    "6": {"cve": ["CVE-2026-104"], "vulnerable": "irgendwas", "patched": "^24.30.0"},
    "7": {"cve": ["CVE-2026-100"], "vulnerable": "24.x", "patched": "^24.25.0", "severity": "high"},
}
_PLAN = {"v20": {"lts": "2023-10-24", "end": "2026-04-30"},
         "v22": {"lts": "2024-10-29", "end": "2027-04-30"},
         "v24": {"lts": "2025-10-28", "end": "2028-04-30"},
         "v25": {"end": "2026-06-01"}, "v28": {"lts": "2028-10-01", "end": "2031-04-30"}}
_nb = cve_pruefung.node_bewerten("24.22.0", _DB, _PLAN, "2026-10-29")
_k = {b["cve"]: b for b in _nb["befunde"]}
check(sorted(_k) == ["CVE-2026-100", "CVE-2026-101", "nodejs-core-5"],
      "betroffen nur, was die Version trifft und nicht behoben ist", str(sorted(_k)))
check(_k.get("CVE-2026-100", {}).get("fix") == "24.25.0",
      "doppelte CVE gebuendelt, die hoehere Behebung gilt", str(_k.get("CVE-2026-100")))
check(_k.get("CVE-2026-101", {}).get("fix") == "" and _k["CVE-2026-101"].get("fix_andere") == "26.12.1",
      "nur in anderer Hauptversion behoben -> kein fix, aber fix_andere", str(_k.get("CVE-2026-101")))
check(_k.get("CVE-2026-101", {}).get("einstufung") == "critical"
      and _k.get("nodejs-core-5", {}).get("einstufung") == "",
      "Einstufung uebernommen, 'unknown' gilt als nicht eingestuft")
check(_k.get("CVE-2026-100", {}).get("ref", "").startswith("https://nodejs.org/")
      and _k.get("CVE-2026-101", {}).get("ref") == "", "nur https-Verweise werden uebernommen")
check(_nb["undeutbar"] == ["CVE-2026-104"], "nicht deutbarer Eintrag wird GENANNT", str(_nb["undeutbar"]))
check(_nb["ende"] == "2028-04-30" and not any(b.get("eol") for b in _nb["befunde"]),
      "unterstuetzte Hauptversion: kein EOL-Befund")
_eol = cve_pruefung.node_bewerten("20.19.2", _DB, _PLAN, "2026-10-29")
_e = [b for b in _eol["befunde"] if b.get("eol")]
check(len(_e) == 1 and _e[0]["cve"] == "nodejs-20-eol" and "2026-04-30" in _e[0]["text"],
      "Hauptversion nach ihrem Ende -> eigener Befund", str(_e))
check(bool(_e) and _e[0]["fix_andere"] == "22.x, 24.x",
      "EOL nennt nur unterstuetzte LTS-Linien (keine ungerade, keine kuenftige)", str(_e and _e[0]["fix_andere"]))
check("nicht im Release-Plan" in cve_pruefung.node_bewerten("23.1.0", _DB, _PLAN, "2026-10-29")["hinweis"],
      "Hauptversion ohne Plan-Eintrag: Hinweis statt Schweigen")
check("nicht verfügbar" in cve_pruefung.node_bewerten("24.22.0", _DB, {}, "2026-10-29")["hinweis"],
      "ohne Release-Plan: Hinweis, dass das Ende nicht geprueft ist")

# node_pruefen: Klassen je Installationsart (Paketindex/Netz als Attrappen).
_n_orig = (cve_pruefung.node_installiert, cve_pruefung._node_quelle_holen)
cve_pruefung._node_quelle_holen = lambda url, cache: (_DB if "security-wg" in url else _PLAN, "")


def _np(inst):
    cve_pruefung.node_installiert = lambda rel: inst
    return cve_pruefung.node_pruefen()


try:
    _dpkg = {"paket": "nodejs", "version": "24.22.0-1nodesource1", "status": "ii",
             "kandidat": "24.26.0-1nodesource1", "debian": False}
    _r1 = _np(_dpkg)
    _r2 = _np(dict(_dpkg, kandidat="24.22.0-1nodesource1"))
    _r3 = _np(dict(_dpkg, status="hi"))
    _r4 = _np({"paket": "", "pfad": "/usr/local/bin/node", "version": "v24.22.0", "status": "",
               "kandidat": "", "debian": False})
    _r5 = _np(dict(_dpkg, version="20.19.2+dfsg-1+deb13u3", debian=True))
    _r6 = _np(None)
    _r7 = _np(dict(_dpkg, debian=None))
finally:
    cve_pruefung.node_installiert, cve_pruefung._node_quelle_holen = _n_orig
_kl = lambda r: {b["cve"]: b["klasse"] for b in r["befunde"]}  # noqa: E731
check(_r1["info"].get("geprueft") is True and _r1["info"].get("unterstuetzt_bis") == "2028-04-30",
      "Positivkontrolle: NodeSource-Paket wird geprueft", str(_r1["info"]))
check(_kl(_r1) == {"CVE-2026-100": "behebbar", "CVE-2026-101": "offen", "nodejs-core-5": "nicht_im_index"},
      "Kandidat >= Behebung -> behebbar, darunter -> nicht im Index, ohne Behebung -> offen", str(_kl(_r1)))
_b1 = next((b for b in _r1["befunde"] if b["cve"] == "CVE-2026-100"), {})
check(_b1.get("beheben_mit") == ["nodejs"] and _b1.get("pakete") == ["nodejs"]
      and _b1.get("aus_fremdquelle") is True and _b1.get("aus_sicherheitsquelle") is False,
      "behebbar traegt Paket, Zielpaket und die Fremdquelle", str(_b1))
check(_kl(_r2).get("CVE-2026-100") == "nicht_im_index", "Kandidat = installiert -> nicht im Index")
check(set(_kl(_r3).values()) <= {"zurueckgehalten", "offen"} and "zurueckgehalten" in _kl(_r3).values(),
      "hold -> zurueckgehalten", str(_kl(_r3)))
check(_kl(_r4).get("CVE-2026-100") == "behebbar"
      and all(not b.get("beheben_mit") and b["pakete"] == [] for b in _r4["befunde"]),
      "Node ohne Paketverwaltung: Update verfuegbar, aber nichts zum Heben", str(_r4["befunde"][:1]))
check(_r5["info"].get("entfaellt") is True and not _r5["befunde"],
      "nodejs aus Debian -> Bereich entfaellt (der Tracker prueft es)")
check(_r6["info"].get("entfaellt") is True, "ohne Node.js -> Bereich entfaellt")
check(_r7["info"].get("geprueft") is True,
      "Herkunft unbekannt (keine apt-Auskunft) -> wird geprueft, nicht Debian unterstellt")
check("CVE-2026-104" in _r1["info"].get("hinweis", ""),
      "nicht auswertbare Eintraege stehen im Hinweis des Bereichs", _r1["info"].get("hinweis", ""))

# node_installiert: echte Funktion, dpkg-query/apt/which als Attrappen mit
# der echten Aufrufform (subprocess.run -> CompletedProcess).
class _Lauf:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


_ni_orig = (cve_pruefung.subprocess.run, cve_apt.apt_policy, cve_pruefung.shutil.which)


def _ni(dpkg_out, pol, which=None, version_out=""):
    def run(cmd, **k):
        if cmd[0] == "dpkg-query":
            return _Lauf(0 if dpkg_out else 1, dpkg_out)
        return _Lauf(0, version_out)
    cve_pruefung.subprocess.run = run
    cve_apt.apt_policy = lambda namen: pol
    cve_pruefung.shutil.which = lambda name, path=None: which
    return cve_pruefung.node_installiert("trixie")


try:
    _ns = {"nodejs": {"installiert": "24.22.2-1nodesource1", "kandidat": "24.22.2-1nodesource1",
                      "quellen": {"24.22.2-1nodesource1": ["nodistro/main"]}}}
    _deb = {"nodejs": {"installiert": "20.19.2+dfsg-1+deb13u3", "kandidat": "20.19.2+dfsg-1+deb13u3",
                       "quellen": {"20.19.2+dfsg-1+deb13u3": ["trixie-security/main"]}}}
    _i1 = _ni("ii \t24.22.2-1nodesource1", _ns)
    _i2 = _ni("ii \t20.19.2+dfsg-1+deb13u3", _deb)
    _i3 = _ni("ii \t24.22.2-1nodesource1", {})
    _i4 = _ni("rc \t24.22.2-1nodesource1", {}, which="/usr/local/bin/node", version_out="v24.11.0\n")
    _i5 = _ni("", {}, which=None)
finally:
    cve_pruefung.subprocess.run, cve_apt.apt_policy, cve_pruefung.shutil.which = _ni_orig
check(_i1 and _i1["paket"] == "nodejs" and _i1["debian"] is False
      and _i1["kandidat"] == "24.22.2-1nodesource1", "NodeSource-Paket erkannt, nicht Debian", str(_i1))
check(_i2 and _i2["debian"] is True, "Debians nodejs erkannt", str(_i2))
check(_i3 and _i3["debian"] is None, "ohne apt-Auskunft: Herkunft unbekannt (None), nicht Debian", str(_i3))
check(_i4 and _i4["paket"] == "" and _i4["version"] == "v24.11.0" and _i4["pfad"] == "/usr/local/bin/node",
      "nur Konfigurationsreste (rc) -> node ausserhalb der Paketverwaltung", str(_i4))
check(_i5 is None, "weder Paket noch node -> keine Laufzeit")

# Abruf: gespeicherter Stand mit Hinweis, ohne ihn ein Grund.
_orig_uo = cve_pruefung.urllib.request.urlopen


def _kaputt(*a, **k):
    raise OSError("Netz weg")


cve_pruefung.urllib.request.urlopen = _kaputt
try:
    _cache = SANDKASTEN / "node_probe.json"
    _o1 = cve_pruefung._node_quelle_holen("https://x.example/db.json", _cache)
    cve_pruefung._schreiben(_cache, {"1": {"cve": ["CVE-1"]}})
    _o2 = cve_pruefung._node_quelle_holen("https://x.example/db.json", _cache)
finally:
    cve_pruefung.urllib.request.urlopen = _orig_uo
check(_o1[0] is None and "nicht erreichbar" in _o1[1], "ohne Netz und ohne Stand: kein Ergebnis, mit Grund", str(_o1))
check(_o2[0] == {"1": {"cve": ["CVE-1"]}} and "gespeicherter Stand" in _o2[1],
      "ohne Netz mit Stand: gespeicherter Stand, laut", str(_o2))

# Plan, Einzel-Update, Kurzbericht, Quittierbarkeit
_nerg = {"befunde": [dict(_b1, id="node:x")]}
_pl = cve_pruefung.plan(_nerg, {"schwelle": "alle", "regulaere_quelle": True})
check(_pl["debian"] == [] and _pl["node_von_hand"] == 1,
      "Node.js nie automatisch – auch nicht mit freigegebener regulaerer Quelle", str(_pl))
check(cve_pruefung.einzeln_pakete(_nerg, "nodejs") == ["nodejs"], "Einzel-Update hebt nodejs")
check("Node.js nur von Hand" in cve_pruefung.kurzbericht(
          {"ok": True, "zaehler": {"behebbar": 1}, "beheben": True, "bereiche": {},
           "behebung": {"plan": _pl, "debian": [], "python": None}}),
      "Kurzbericht sagt, warum Node.js nicht gehoben wurde")

# Fremdpaket-Liste ueber ALLE Pakete (nicht nur die mit Befund).
_FP = PAKETE + [pk("google-chrome-stable", "google-chrome-stable", "150.0-1"),
                pk("linux-image-6.12.73+deb13-amd64", "linux-signed-amd64", "6.12.73+1"),
                pk("ohnepolicy", "ohnepolicy", "1.0")]
_echt_pol = cve_apt.apt_policy
_gefragt = []


def _pol(namen):
    _gefragt.extend(namen)
    return {"nodejs": {"installiert": "24.22.2-1nodesource1",
                       "quellen": {"24.22.2-1nodesource1": ["nodistro/main"]}},
            "libfoo1": {"installiert": "2.0-1", "quellen": {"2.0-1": ["trixie/main"]}},
            "google-chrome-stable": {"installiert": "150.0-1", "quellen": {"150.0-1": ["stable/main"]}},
            "linux-image-6.12.73+deb13-amd64": {"installiert": "6.12.73+1", "quellen": {}}}


cve_apt.apt_policy = _pol
try:
    _bf2 = [{"pakete": ["libfoo1"], "cve": "C"}]
    _fr2 = cve_pruefung.herkunft_pruefen(_bf2, _FP, "trixie")
finally:
    cve_apt.apt_policy = _echt_pol
check(_fr2 == ["google-chrome-stable", "nodejs"],
      "Fremdpakete OHNE Befund werden genannt; Kernel-Images und Pakete ohne Auskunft nicht", str(_fr2))
check("linux-image-6.12.73+deb13-amd64" not in _gefragt and "google-chrome-stable" in _gefragt,
      "gefragt werden alle Pakete ausser versionierten Kernelpaketen", str(_gefragt))

# pruefen(): nodejs steht nicht mehr unter "nicht ueber Debian pruefbar",
# wenn der Node-Bereich es geprueft hat.
_p_orig = (cve_pruefung._debian_im_prozess, cve_pruefung.python_pruefen, cve_pruefung.npm_pruefen,
           cve_pruefung.node_pruefen, cve_pruefung.veroeffentlichung_ergaenzen)
cve_pruefung._debian_im_prozess = lambda: {"info": {"geprueft": True,
                                                    "fremd": ["google-chrome-stable", "nodejs"]},
                                           "befunde": []}
cve_pruefung.python_pruefen = lambda: {"info": {"geprueft": True}, "befunde": []}
cve_pruefung.npm_pruefen = lambda: {"info": {"geprueft": False, "entfaellt": True}, "befunde": []}
cve_pruefung.veroeffentlichung_ergaenzen = lambda befunde: {}
try:
    cve_pruefung.node_pruefen = lambda: {"info": {"geprueft": True, "paket": "nodejs"},
                                         "befunde": [dict(_b1), dict(_b1, cve="X", klasse="offen",
                                                                     beheben_mit=None)]}
    _pr = cve_pruefung.pruefen()
    cve_pruefung.node_pruefen = lambda: {"info": {"geprueft": False, "paket": "nodejs",
                                                  "grund": "Netz"}, "befunde": []}
    _pr2 = cve_pruefung.pruefen()
finally:
    (cve_pruefung._debian_im_prozess, cve_pruefung.python_pruefen, cve_pruefung.npm_pruefen,
     cve_pruefung.node_pruefen, cve_pruefung.veroeffentlichung_ergaenzen) = _p_orig
_d = _pr["bereiche"]["debian"]
check(_d.get("fremd") == ["google-chrome-stable"] and _d.get("fremd_geprueft") == ["nodejs"],
      "geprueftes nodejs wandert aus der Fremdliste", str(_d))
check(_pr2["bereiche"]["debian"].get("fremd") == ["google-chrome-stable", "nodejs"],
      "scheitert die Node-Pruefung, bleibt nodejs als nicht pruefbar genannt",
      str(_pr2["bereiche"]["debian"]))
_q = {b["cve"]: b["quittierbar"] for b in _pr["befunde"]}
check(_q == {"CVE-2026-100": False, "X": True}, "Node: behebbar nicht quittierbar, offen schon", str(_q))

# Fehlt die WhatsApp-Bridge, gibt es keinen npm-Bereich – er steht NICHT als
# "nicht geprueft" im Ergebnis (das hatte keinen Informationswert). Die
# Wirkung wird an pruefen() gemessen, Debian/Python/Datum als Attrappen.
abschnitt("npm: fehlende Bridge ist kein Bereich")
_leer = Path(tempfile.mkdtemp(prefix="bridge_", dir=SANDKASTEN))
_orig = (cve_pruefung.BRIDGE, cve_pruefung._debian_im_prozess,
         cve_pruefung.python_pruefen, cve_pruefung.veroeffentlichung_ergaenzen,
         cve_pruefung.node_pruefen)
cve_pruefung._debian_im_prozess = lambda: {"info": {"geprueft": True}, "befunde": []}
cve_pruefung.python_pruefen = lambda: {"info": {"geprueft": True}, "befunde": []}
cve_pruefung.veroeffentlichung_ergaenzen = lambda befunde: {}
cve_pruefung.node_pruefen = lambda: {"info": {"geprueft": False, "entfaellt": True}, "befunde": []}
try:
    cve_pruefung.BRIDGE = _leer
    _ohne = cve_pruefung.pruefen()
    (_leer / "node_modules").mkdir()
    (_leer / "package-lock.json").write_text("{kaputt", encoding="utf-8")
    _mit = cve_pruefung.pruefen()
finally:
    (cve_pruefung.BRIDGE, cve_pruefung._debian_im_prozess,
     cve_pruefung.python_pruefen, cve_pruefung.veroeffentlichung_ergaenzen,
     cve_pruefung.node_pruefen) = _orig
# Positivkontrolle: mit installierter (hier kaputter) Bridge erscheint der
# Bereich – sonst waere die folgende Pruefung trivial wahr.
check(not (_mit["bereiche"].get("npm") or {}).get("geprueft", True),
      "Positivkontrolle: installierte Bridge mit Fehler steht als nicht geprueft da",
      str(_mit["bereiche"].get("npm")))
check("npm" not in _ohne["bereiche"] and set(_ohne["bereiche"]) == {"debian", "python"},
      "ohne Bridge kein npm-Bereich im Ergebnis", str(_ohne["bereiche"]))
check("npm" not in cve_pruefung.kurzbericht(dict(_ohne, ok=True)),
      "Kurzbericht fuehrt npm nicht als nicht geprueft",
      cve_pruefung.kurzbericht(dict(_ohne, ok=True)))

ende()
