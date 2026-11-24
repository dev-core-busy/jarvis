#!/usr/bin/env python3
"""Bedrohungslage der CVE-Pruefung: CISA KEV und EPSS (backend/cve_pruefung.py).

Gemessen ueber den ECHTEN Abrufweg (urllib) gegen einen lokalen HTTP-Server –
keine Attrappe von urlopen, damit If-Modified-Since, 304, Weiterleitung der
Kopfzeilen und Groessen-/Inhaltspruefung wirklich laufen:

  1. Zerlegen: KEV-JSON und EPSS-CSV (Kommentarzeile, Kopf, kaputte Zeilen,
     Werte ausserhalb 0..1).
  2. Abruf: erster Abruf fuellt den Cache, der zweite fragt mit
     If-Modified-Since und nimmt die 304; EPSS fragt innerhalb von
     EPSS_NEU_S gar nicht.
  3. Ein kaputter Abruf (Fehlerseite mit 200, abgeschnittenes gzip) ersetzt
     einen guten Stand NICHT; ohne Stand und ohne Netz: ok=False, Daten None.
  4. Anreicherung: Treffer ueber die Kennung UND ueber Aliase, nicht gelistet =
     False, Katalog fehlt = None (unbekannt ist nicht "nicht ausgenutzt").
  5. Plan: KEV hebt die Schwelle auf, None nicht; die regulaere Quelle bleibt
     eine eigene Entscheidung.
  6. pruefen() traegt das Feld, kurzbericht nennt KEV und dessen Ausfall.
  7. Datensparsamkeit: abgerufen werden nur die ganzen Dateien (kein
     Pfad/Query mit einer Kennung); die Kennungsauskunft fragt gar nicht.

    python3 tests/test_cve_bedrohung.py   Exit 0 gruen, 1 rot, 2 nicht lauffaehig
"""
import ast
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SANDKASTEN = Path(tempfile.mkdtemp(prefix="cve_bedrohung_"))

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


# ── Lokaler Server ──────────────────────────────────────────────────────────
# ROUTEN[pfad] = {"status", "body", "lm"}; jede Anfrage landet in ANFRAGEN.
ROUTEN: dict = {}
ANFRAGEN: list = []


class _H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 – Name vorgegeben
        ANFRAGEN.append({"pfad": self.path, "ims": self.headers.get("If-Modified-Since") or ""})
        r = ROUTEN.get(self.path.split("?")[0])
        if not r:
            self.send_response(404)
            self.end_headers()
            return
        if r.get("lm") and self.headers.get("If-Modified-Since") == r["lm"]:
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(r.get("status", 200))
        if r.get("lm"):
            self.send_header("Last-Modified", r["lm"])
        self.send_header("Content-Length", str(len(r["body"])))
        self.end_headers()
        self.wfile.write(r["body"])

    def log_message(self, *a):
        pass


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
BASIS = f"http://127.0.0.1:{SERVER.server_address[1]}"


def ende(code=None):
    SERVER.shutdown()
    shutil.rmtree(SANDKASTEN, ignore_errors=True)
    if code is not None:
        sys.exit(code)
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(0 if _fail == 0 else 1)


# VOR dem Import: das Modul liest Datenordner und Adressen beim Laden.
os.environ["JARVIS_CVE_DATEN"] = str(SANDKASTEN)
os.environ["JARVIS_CVE_KEV"] = BASIS + "/kev.json"
os.environ["JARVIS_CVE_EPSS"] = BASIS + "/epss.csv.gz"
from backend import cve_pruefung as cp  # noqa: E402

if Path(cp.DATEN) != SANDKASTEN or not cp.KEV_URL.startswith(BASIS) or not cp.EPSS_URL.startswith(BASIS):
    print("ABBRUCH: Datenordner oder Adressen zeigen aus dem Sandkasten heraus:",
          cp.DATEN, cp.KEV_URL, cp.EPSS_URL)
    ende(2)

# ── Testmaterial ────────────────────────────────────────────────────────────
KEV = {"title": "t", "catalogVersion": "2026.11.20", "dateReleased": "2026-11-20T14:00:00.000Z",
       "count": 4, "vulnerabilities": [
           {"cveID": "CVE-2026-1111", "dateAdded": "2026-11-01", "dueDate": "2026-11-22",
            "knownRansomwareCampaignUse": "Known", "vulnerabilityName": "Eins"},
           {"cveID": "cve-2026-2222", "dateAdded": "2026-10-01", "dueDate": "2026-10-22",
            "knownRansomwareCampaignUse": "Unknown", "vulnerabilityName": "Zwei"},
           {"cveID": "CVE-2026-3333", "dateAdded": "2026-09-01", "dueDate": "2026-09-22",
            "vulnerabilityName": "Drei (Alias eines Python-Befunds)"},
           {"cveID": "kein-cve", "dateAdded": "2026-09-01"}]}
KEV_ROH = json.dumps(KEV).encode()
EPSS_TEXT = ("#model_version:v2026.06.15,score_date:2026-11-20T12:00:23Z\n"
             "cve,epss,percentile\n"
             "CVE-2026-1111,0.91000,0.99800\n"
             "CVE-2026-3333,0.00500,0.40000\n"
             "CVE-2026-3334,0.20000,0.90000\n"
             "CVE-2026-4444,kaputt,0.1\n"
             "CVE-2026-5555,1.5,0.5\n"
             "CVE-2026-6666,0.01000,0.60000\n")
EPSS_GZ = gzip.compress(EPSS_TEXT.encode())
LM1 = formatdate(time.time() - 3600, usegmt=True)


def setze_quellen(kev=KEV_ROH, epss=EPSS_GZ, kev_status=200, epss_status=200, lm=LM1):
    ROUTEN.clear()
    ROUTEN["/kev.json"] = {"status": kev_status, "body": kev, "lm": lm}
    ROUTEN["/epss.csv.gz"] = {"status": epss_status, "body": epss, "lm": lm}


def leeren():
    for p in (cp.KEV_CACHE, cp.KEV_META, cp.EPSS_CACHE, cp.EPSS_META):
        p.unlink(missing_ok=True)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.is_file() else ""  # nosec – Vergleich, kein Schutz


# Positivkontrolle: der Server liefert, und der echte Abrufweg erreicht ihn.
setze_quellen()
_info, _d = cp.kev_holen()
if not (_info.get("ok") and _d and ANFRAGEN and ANFRAGEN[-1]["pfad"] == "/kev.json"):
    print("ABBRUCH: lokaler Server nicht erreichbar oder KEV nicht geladen:", _info, ANFRAGEN)
    ende(2)
leeren()
ANFRAGEN.clear()

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Zerlegen")
# ═══════════════════════════════════════════════════════════════════════════
_kev, _stand = cp._kev_aus(gzip.compress(KEV_ROH))
check(set(_kev) == {"CVE-2026-1111", "CVE-2026-2222", "CVE-2026-3333"},
      "KEV: nur CVE-Kennungen, Kleinschreibung normiert", str(sorted(_kev)))
check(_kev["CVE-2026-1111"]["ransomware"] is True and _kev["CVE-2026-2222"]["ransomware"] is False
      and _kev["CVE-2026-3333"]["ransomware"] is False, "Ransomware nur bei \"Known\"")
check(_kev["CVE-2026-1111"]["seit"] == "2026-11-01" and _kev["CVE-2026-1111"]["frist"] == "2026-11-22",
      "Aufnahme und Frist uebernommen", str(_kev["CVE-2026-1111"]))
check(_stand == "2026-11-20", "Katalogstand aus dateReleased", _stand)
for _kap, _was in ((b"<html>Fehler</html>", "HTML statt JSON"),
                   (json.dumps({"vulnerabilities": []}).encode(), "leere Liste"),
                   (json.dumps({"vulnerabilities": [{"cveID": "x"}]}).encode(), "ohne CVE-Kennung")):
    try:
        cp._kev_aus(gzip.compress(_kap))
        check(False, f"KEV {_was} wird abgelehnt")
    except Exception:  # noqa: BLE001
        check(True, f"KEV {_was} wird abgelehnt")
_ep, _est = cp._epss_aus(EPSS_GZ, {"CVE-2026-1111", "CVE-2026-3333", "CVE-2026-4444", "CVE-2026-5555"})
check(_ep == {"CVE-2026-1111": (0.91, 0.998), "CVE-2026-3333": (0.005, 0.4)},
      "EPSS: nur gefragte Kennungen, kaputte und unplausible Zeilen verworfen", str(_ep))
check(_est == "2026-11-20", "EPSS-Stand aus score_date", _est)
for _kap, _was in ((gzip.compress(b"cve,score\nCVE-1,0.1\n"), "fremder Kopf"),
                   (gzip.compress(b"#nur kommentar\n"), "ohne Kopfzeile"),
                   (gzip.compress(b"cve,epss,percentile\n"), "ohne Eintraege"),
                   (EPSS_GZ[:len(EPSS_GZ) // 2], "abgeschnittenes gzip")):
    try:
        cp._epss_pruefen(_kap)
        check(False, f"EPSS {_was} wird abgelehnt")
    except Exception:  # noqa: BLE001
        check(True, f"EPSS {_was} wird abgelehnt")
check(cp.cve_kennungen({"cve": "GHSA-aaaa-bbbb-cccc", "aliase": ["CVE-2026-3333", "PYSEC-1", " cve-2026-9 "]})
      == ["CVE-2026-3333", "CVE-2026-9"], "Kennungen: CVE aus Aliasen, normiert")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2. Abruf und Cache")
# ═══════════════════════════════════════════════════════════════════════════
leeren()
setze_quellen()
ANFRAGEN.clear()
_i1, _k1 = cp.kev_holen()
check(_i1["ok"] and _i1.get("eintraege") == 3 and _k1 and cp.KEV_CACHE.is_file(),
      "erster Abruf: Katalog geladen und gespeichert", str(_i1))
check(gzip.decompress(cp.KEV_CACHE.read_bytes()) == KEV_ROH, "Cache traegt den Katalog unveraendert (gzip)")
check(ANFRAGEN and ANFRAGEN[0]["ims"] == "", "erster Abruf ohne If-Modified-Since", str(ANFRAGEN))
ANFRAGEN.clear()
_i2, _k2 = cp.kev_holen()
check(ANFRAGEN and ANFRAGEN[0]["ims"] == LM1, "zweiter Abruf fragt mit If-Modified-Since", str(ANFRAGEN))
check(_i2["ok"] and not _i2["hinweis"] and _k2 == _k1, "304: gespeicherter Stand gilt, ohne Hinweis", str(_i2))
ANFRAGEN.clear()
_e1, _w1 = cp.epss_holen({"CVE-2026-1111"})
check(_e1["ok"] and _w1 == {"CVE-2026-1111": (0.91, 0.998)} and len(ANFRAGEN) == 1,
      "EPSS: erster Abruf", f"{_e1} {_w1} {ANFRAGEN}")
_e2, _w2 = cp.epss_holen({"CVE-2026-1111"})
check(len(ANFRAGEN) == 1 and _w2 == _w1, "EPSS: innerhalb EPSS_NEU_S keine zweite Anfrage", str(ANFRAGEN))
# Altern lassen: jetzt wird gefragt (304, weil Last-Modified gleich).
_m = json.loads(cp.EPSS_META.read_text())
_m["geholt"] = time.time() - cp.EPSS_NEU_S - 5
cp.EPSS_META.write_text(json.dumps(_m))
cp.epss_holen({"CVE-2026-1111"})
check(len(ANFRAGEN) == 2 and ANFRAGEN[1]["ims"] == LM1, "EPSS: nach Ablauf wieder gefragt, mit If-Modified-Since",
      str(ANFRAGEN))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3. Kaputter Abruf ersetzt keinen guten Stand")
# ═══════════════════════════════════════════════════════════════════════════
_vor = md5(cp.KEV_CACHE)
setze_quellen(kev=b"<html>Wartung</html>", lm=formatdate(time.time(), usegmt=True))
_i3, _k3 = cp.kev_holen()
check(md5(cp.KEV_CACHE) == _vor, "Fehlerseite mit 200: KEV-Cache unveraendert")
check(_i3["ok"] and _k3 == _k1 and "gespeicherter Stand" in _i3["hinweis"],
      "Fehlerseite: alter Stand benutzt, MIT Hinweis", str(_i3))
setze_quellen(kev_status=503, lm="")
_i4, _k4 = cp.kev_holen()
check(_i4["ok"] and "HTTP 503" in _i4["hinweis"] and _k4 == _k1, "503: alter Stand mit Grund", str(_i4))
_vor = md5(cp.EPSS_CACHE)
_m = json.loads(cp.EPSS_META.read_text())
_m["geholt"] = 0
cp.EPSS_META.write_text(json.dumps(_m))
setze_quellen(epss=EPSS_GZ[:len(EPSS_GZ) // 2], lm=formatdate(time.time(), usegmt=True))
_e5, _w5 = cp.epss_holen({"CVE-2026-1111"})
check(md5(cp.EPSS_CACHE) == _vor and _e5["ok"] and _w5 == _w1 and _e5["hinweis"],
      "abgeschnittenes EPSS-gzip: Cache unveraendert, alter Stand mit Hinweis", str(_e5))
leeren()
setze_quellen(kev_status=503, epss_status=503, lm="")
_i6, _k6 = cp.kev_holen()
_e6, _w6 = cp.epss_holen({"CVE-2026-1111"})
check(_i6["ok"] is False and _k6 is None and "503" in _i6["hinweis"], "ohne Stand und Netz: KEV ok=False, None",
      str(_i6))
check(_e6["ok"] is False and _w6 is None, "ohne Stand und Netz: EPSS ok=False, None", str(_e6))
check(not cp.KEV_CACHE.exists() and not cp.EPSS_CACHE.exists(), "ein gescheiterter Abruf legt keinen Cache an")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("4. Anreicherung der Befunde")
# ═══════════════════════════════════════════════════════════════════════════
leeren()
setze_quellen()


def _bef():
    return [{"bereich": "debian", "quelle": "a", "cve": "CVE-2026-1111", "klasse": "offen"},
            {"bereich": "python", "quelle": "b", "cve": "GHSA-aaaa-bbbb-cccc",
             "aliase": ["CVE-2026-3334", "CVE-2026-3333"], "klasse": "offen"},
            {"bereich": "debian", "quelle": "c", "cve": "CVE-2026-6666", "klasse": "offen"},
            {"bereich": "npm", "quelle": "d", "cve": "GHSA-xxxx-yyyy-zzzz", "aliase": [], "klasse": "offen"}]


ANFRAGEN.clear()
_b = _bef()
_inf = cp.bedrohung_ergaenzen(_b)
check(isinstance(_b[0]["kev"], dict) and _b[0]["kev"]["kennung"] == "CVE-2026-1111"
      and _b[0]["kev"]["ransomware"] is True, "Treffer ueber die Kennung", str(_b[0].get("kev")))
check(isinstance(_b[1]["kev"], dict) and _b[1]["kev"]["kennung"] == "CVE-2026-3333",
      "Treffer ueber einen Alias (GHSA mit CVE)", str(_b[1].get("kev")))
check(_b[2]["kev"] is False and _b[3]["kev"] is False, "nicht gelistet bzw. ohne CVE: False",
      str([_b[2]["kev"], _b[3]["kev"]]))
check(_b[0]["epss"] == 0.91 and _b[0]["epss_perzentil"] == 0.998, "EPSS je Kennung", str(_b[0]))
check(_b[1]["epss"] == 0.2 and _b[1]["epss_perzentil"] == 0.9, "EPSS ueber Aliase: der hoechste Wert", str(_b[1]))
check(_b[3]["epss"] is None and _b[3]["epss_perzentil"] is None, "ohne CVE kein EPSS-Wert")
check(_inf["kev"]["ok"] and _inf["kev"]["treffer"] == 2 and _inf["kev"]["stand"] == "2026-11-20"
      and _inf["epss"]["ok"] and _inf["epss"]["mit_wert"] == 3 and _inf["epss"]["stand"] == "2026-11-20",
      "Rueckgabe fuers Ergebnis: Stand und Zahlen", json.dumps(_inf))
check(_inf["kev"].get("link", "").startswith("https://www.cisa.gov/"), "Rueckgabe traegt den Katalog-Link")
check(sorted(a["pfad"] for a in ANFRAGEN) == ["/epss.csv.gz", "/kev.json"],
      "Datensparsamkeit: nur die ganzen Dateien geholt, keine Kennung in der Anfrage", str(ANFRAGEN))
leeren()
setze_quellen(kev_status=503, epss_status=503, lm="")
_b = _bef()
_inf = cp.bedrohung_ergaenzen(_b)
check(all(b["kev"] is None for b in _b), "Katalog fehlt: kev=None an JEDEM Befund (nicht False)",
      str([b["kev"] for b in _b]))
check(all(b["epss"] is None for b in _b) and _inf["kev"]["ok"] is False and _inf["epss"]["ok"] is False,
      "Datei fehlt: epss=None, Ausfall im Ergebnis benannt", json.dumps(_inf))
check(cp.bedrohung_ergaenzen([], kev=lambda: ({"ok": True}, {}), epss=lambda ids: ({"ok": True}, {}))
      ["kev"]["treffer"] == 0, "ohne Befunde: kein Fehler")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("5. Plan: KEV hebt die Schwelle auf")
# ═══════════════════════════════════════════════════════════════════════════
EINST = {"schwelle": "ab_mittel", "regulaere_quelle": False}


def _deb(kev, einst="low", sich=True):
    return {"bereich": "debian", "quelle": "q", "cve": "CVE-2026-1111", "klasse": "behebbar",
            "einstufung": einst, "aus_sicherheitsquelle": sich, "beheben_mit": ["libq1"], "kev": kev}


check(cp.plan({"befunde": [_deb(False)]}, EINST)["debian"] == [], "niedrig ohne KEV: unter der Schwelle")
check(cp.plan({"befunde": [_deb(None)]}, EINST)["debian"] == [], "niedrig, KEV unbekannt: unter der Schwelle")
check(cp.plan({"befunde": [_deb(dict(KEV["vulnerabilities"][0]))]}, EINST)["debian"] == ["libq1"],
      "niedrig MIT KEV: wird behoben")
check(cp.plan({"befunde": [_deb(dict(KEV["vulnerabilities"][0]), einst="unimportant")]},
              dict(EINST, schwelle="ab_niedrig"))["debian"] == ["libq1"], "unwichtig MIT KEV: wird behoben")
_pr = cp.plan({"befunde": [_deb(dict(KEV["vulnerabilities"][0]), sich=False)]}, EINST)
check(_pr["debian"] == [] and _pr["nur_regulaere_quelle"] == 1,
      "KEV aendert nichts an der Freigabe der regulaeren Quelle", str(_pr))
check(cp.plan({"befunde": [dict(_deb(dict(KEV["vulnerabilities"][0])), bereich="python")]}, EINST)["debian"] == [],
      "KEV an einem Python-Befund erzeugt keinen Debian-Plan")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("6. pruefen() und Kurzbericht")
# ═══════════════════════════════════════════════════════════════════════════
_baum = ast.parse(Path(cp.__file__).read_text(encoding="utf-8"))
_pf = [n for n in ast.walk(_baum) if isinstance(n, ast.FunctionDef) and n.name == "pruefen"]
check(len(_pf) == 1 and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "bedrohung_ergaenzen"
                            for n in ast.walk(_pf[0])), "pruefen() ruft bedrohung_ergaenzen")
leeren()
setze_quellen()
_orig = (cp._debian_im_prozess, cp.python_pruefen, cp.npm_pruefen, cp.node_pruefen, cp.veroeffentlichung_ergaenzen)
cp._debian_im_prozess = lambda: {"info": {"geprueft": True}, "befunde": [
    {"bereich": "debian", "quelle": "a", "cve": "CVE-2026-1111", "klasse": "behebbar", "einstufung": "low",
     "pakete": ["liba"], "beheben_mit": ["liba"], "aus_sicherheitsquelle": True}]}
cp.python_pruefen = lambda: {"info": {"geprueft": True}, "befunde": []}
cp.npm_pruefen = lambda: {"info": {"geprueft": False, "entfaellt": True}, "befunde": []}
cp.node_pruefen = lambda: {"info": {"geprueft": False, "entfaellt": True}, "befunde": []}
cp.veroeffentlichung_ergaenzen = lambda befunde: {}
try:
    _erg = cp.pruefen()
    # Die Einordnung darf die Pruefung nicht kippen: eine werfende Quelle.
    _kev_orig = cp.kev_holen
    cp.kev_holen = lambda: (_ for _ in ()).throw(RuntimeError("kaputt"))
    try:
        _erg2 = cp.pruefen()
    finally:
        cp.kev_holen = _kev_orig
finally:
    (cp._debian_im_prozess, cp.python_pruefen, cp.npm_pruefen, cp.node_pruefen,
     cp.veroeffentlichung_ergaenzen) = _orig
check(isinstance(_erg["befunde"][0].get("kev"), dict) and _erg["bedrohung"]["kev"]["ok"],
      "pruefen(): Befund und Ergebnis tragen die Einordnung", json.dumps(_erg.get("bedrohung")))
check(_erg2["befunde"] and _erg2["befunde"][0]["kev"] is None and _erg2["bedrohung"]["kev"]["ok"] is False
      and "kaputt" in _erg2["bedrohung"]["kev"]["hinweis"],
      "werfende Quelle: Pruefung laeuft durch, kev=None, Grund im Ergebnis", json.dumps(_erg2.get("bedrohung")))
_kb = cp.kurzbericht(dict(_erg, ok=True))
check("1 aktiv ausgenutzt (CISA KEV)" in _kb, "Kurzbericht nennt aktiv ausgenutzte Luecken", _kb)
check("CISA KEV nicht verfügbar" in cp.kurzbericht(dict(_erg2, ok=True)),
      "Kurzbericht nennt den Ausfall des Katalogs", cp.kurzbericht(dict(_erg2, ok=True)))
check("KEV" not in cp.kurzbericht({"ok": True, "zaehler": {}, "befunde": []}),
      "Ergebnis ohne Einordnung (aelterer Stand): kein KEV-Satz")
_ausg = dict(_erg, ok=True, befunde=[dict(_erg["befunde"][0], klasse="ausgenommen")])
check("aktiv ausgenutzt" not in cp.kurzbericht(_ausg), "ausgenommene Befunde zaehlen nicht mit")

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("7. Kennungsauskunft: nur gespeicherte Dateien")
# ═══════════════════════════════════════════════════════════════════════════
ANFRAGEN.clear()
_l1 = cp.bedrohung_lokal("CVE-2026-1111")
_l2 = cp.bedrohung_lokal("CVE-2026-9999")
_l3 = cp.bedrohung_lokal("GHSA-aaaa-bbbb-cccc")
check(ANFRAGEN == [], "bedrohung_lokal fragt nicht im Netz", str(ANFRAGEN))
check(isinstance(_l1["kev"], dict) and _l1["epss"] == 0.91, "gelistete Kennung: KEV und EPSS", str(_l1))
check(_l2["kev"] is False and _l2["epss"] is None, "nicht gelistet: False / None", str(_l2))
check(_l3["kev"] is False, "GHSA: nicht KEV-faehig", str(_l3))
leeren()
check(cp.bedrohung_lokal("CVE-2026-1111")["kev"] is None, "ohne Datei: unbekannt (None)")
_ka = [n for n in ast.walk(_baum) if isinstance(n, ast.FunctionDef) and n.name == "kennung_auskunft"]
check(len(_ka) == 1 and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "bedrohung_lokal"
                            for n in ast.walk(_ka[0])), "kennung_auskunft() nimmt bedrohung_lokal")

ende()
