"""Live-Probe (DEV): Dateifilter im Destillat + Tags der Confluence-Einbindung.

Laeuft AUF DEM SERVER (sys.path /opt/jarvis) gegen den laufenden Dienst und
das ECHTE Confluence. Misst:

A. Dateifilter (/api/wissen/destillat/filter)
   - GET/PUT gehen durch, PUT normiert (trimmt, Leerzeilen/Dubletten weg),
   - die Ablage liegt unter data/destillat_filter/<pfad_teil>.json, gehoert
     dem Dienstbenutzer und traegt GENAU das Gepruefte,
   - ein ungueltiger Rumpf (String statt Liste) -> 400, Ablage unveraendert,
   - ein untergeschobener Benutzer im Rumpf legt KEINE fremde Ablage an.
   Der vorgefundene Zustand wird am Ende byte-gleich wiederhergestellt.

B. Tags der Einbindung
   - ⚠ POSITIVKONTROLLE AM ECHTEN CONFLUENCE: die Seitenliste mit
     with_labels=True liefert fuer JEDE Seite eine Liste (nicht None). Sonst
     bliebe jeder getaggte Eintrag als "Tags nicht lesbar" liegen.
   - gibt es im Bereich ein Label, findet tags_filtern genau die Seiten damit,
   - ein ungueltiger Tag wird vom Endpunkt mit 400 abgewiesen (vor dem Speichern),
   - ein Eintrag mit Tag wird gespeichert (normiert) und kommt in der Liste an;
     er traegt einen Tag, den es NICHT gibt – der Abgleich holt also nichts.
     Am Ende wird er geloescht; die Ablage ist danach byte-gleich.

Aufruf: sudo -u jarvis python3 tests/live_destillat_filter_cfb_tags_dev.py
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import benutzer as B                                  # noqa: E402

BENUTZER = os.environ.get("DEST_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
if not M._editable_groups_for(BENUTZER):
    print("ABBRUCH: %r hat keinen Wissensbereich (403) – NICHT PRUEFBAR" % BENUTZER)
    sys.exit(2)


def rufe(methode, pfad, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    req = urllib.request.Request(BASIS + pfad, data=daten, method=methode, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


ROOT = Path("/opt/jarvis")

# ════════════════════════════════════════════════════════════════════════════
print("\nA. Dateifilter")
ABL = ROOT / "data" / "destillat_filter" / (B.pfad_teil(BENUTZER, "unbekannt") + ".json")
FREMD = ROOT / "data" / "destillat_filter" / "probe-fremd-x.json"
vorher = ABL.read_bytes() if ABL.is_file() else None
fremd_vorher = FREMD.exists()
try:
    s, d = rufe("GET", "/api/wissen/destillat/filter")
    check("(Positivkontrolle) GET 200 und ok", s == 200 and d.get("ok") is True, "%s %s" % (s, d))
    s, d = rufe("PUT", "/api/wissen/destillat/filter",
                {"weiss": [" *.pdf ", "", "*.pdf", "*.docx"], "schwarz": ["*entwurf*"],
                 "user": "probe-fremd-x"})
    check("PUT 200", s == 200 and d.get("ok") is True, "%s %s" % (s, d))
    check("PUT antwortet normiert",
          d.get("weiss") == ["*.pdf", "*.docx"] and d.get("schwarz") == ["*entwurf*"], str(d))
    roh = json.loads(ABL.read_text(encoding="utf-8")) if ABL.is_file() else None
    check("die Ablage traegt GENAU das Gepruefte",
          roh == {"weiss": ["*.pdf", "*.docx"], "schwarz": ["*entwurf*"]}, str(roh))
    st = ABL.stat() if ABL.is_file() else None
    import pwd
    check("die Ablage gehoert dem Dienstbenutzer",
          st is not None and pwd.getpwuid(st.st_uid).pw_name == "jarvis",
          pwd.getpwuid(st.st_uid).pw_name if st else "fehlt")
    check("⚠ ein untergeschobener Benutzer legt KEINE fremde Ablage an",
          FREMD.exists() == fremd_vorher)
    s, d = rufe("GET", "/api/wissen/destillat/filter")
    check("GET liefert den gespeicherten Filter",
          d.get("weiss") == ["*.pdf", "*.docx"] and d.get("schwarz") == ["*entwurf*"], str(d))
    davor = ABL.read_bytes()
    s, d = rufe("PUT", "/api/wissen/destillat/filter", {"weiss": "*.pdf", "schwarz": []})
    check("⚠ String statt Liste -> 400 mit Grund", s == 400 and "Whitelist" in (d.get("error") or ""),
          "%s %s" % (s, d))
    check("⚠ und die Ablage ist unveraendert", ABL.read_bytes() == davor)
finally:
    if vorher is None:
        if ABL.exists():
            ABL.unlink()
    else:
        ABL.write_bytes(vorher)
    nachher = ABL.read_bytes() if ABL.is_file() else None
    check("(Aufraeumen) vorgefundener Filter-Zustand byte-gleich wiederhergestellt", nachher == vorher)

# ════════════════════════════════════════════════════════════════════════════
print("\nB. Tags der Confluence-Einbindung")
skill, conf = M._cfb_aktiv()
if not (skill and conf):
    print("  NICHT PRUEFBAR: Confluence-Skill aus oder nicht konfiguriert")
    print("\nErgebnis: %d/%d (Teil B nicht pruefbar)" % (_ok, _ok + _fail))
    sys.exit(2 if not _fail else 1)

import backend.confluence_bindung as cfb                           # noqa: E402
import backend.confluence_abgleich as cfa                          # noqa: E402
from backend.confluence_client import ConfluenceClient             # noqa: E402

eintraege = cfb.liste()
key = next((a.get("key") for e in eintraege for a in (e.get("auswahl") or []) if a.get("key")), None)
if not key:
    sp = ConfluenceClient().spaces_detailed(5)
    key = sp[0]["key"] if sp else None
check("(Positivkontrolle) ein echter Bereich zum Messen", bool(key), str(key))
liste = ConfluenceClient().pages_in_space(key, 3000, with_parent=True, with_version=True,
                                          with_labels=True) if key else []
check("(Positivkontrolle) die Seitenliste ist nicht leer", len(liste) > 0, "%s: %d" % (key, len(liste)))
unbekannt = [p.get("id") for p in liste if p.get("labels") is None]
check("⚠ das ECHTE Confluence liefert fuer JEDE Seite Labels (nicht None)",
      liste and not unbekannt, "%d von %d ohne Labels" % (len(unbekannt), len(liste)))
alle = {}
for p in liste:
    for lab in (p.get("labels") or []):
        alle.setdefault(lab, set()).add(str(p.get("id")))
print("    Bereich %s: %d Seiten, %d verschiedene Labels%s" % (
    key, len(liste), len(alle),
    (" (haeufigstes: %s, %d Seiten)" % max(((k, len(v)) for k, v in alle.items()), key=lambda x: x[1]))
    if alle else ""))
if alle:
    lab, ids = max(alle.items(), key=lambda x: len(x[1]))
    alle_ids = {str(p.get("id")) for p in liste}
    treffer = cfa.tags_filtern(alle_ids, liste, [lab.upper()])
    check("tags_filtern findet am echten Bestand GENAU die Seiten mit dem Label",
          treffer == ids, "%s: %s vs %s" % (lab, len(treffer or ()), len(ids)))
    check("… und ein Label, das es nicht gibt, findet nichts",
          cfa.tags_filtern(alle_ids, liste, ["gibt-es-nicht-" + uuid.uuid4().hex[:6]]) == set())
else:
    print("    (keine Labels im Bereich – Treffer-Messung entfaellt, Form bleibt gemessen)")

gruppe = (M._editable_groups_for(BENUTZER) or [{}])[0].get("id")
ABL_B = cfb._pfad()
b_vorher = ABL_B.read_bytes() if ABL_B.is_file() else None
neu_id = None
try:
    s, d = rufe("POST", "/api/wissen/confluence/bindung",
                {"auswahl": [{"key": key, "start": True}], "groups": [gruppe], "tags": ["zwei worte"]})
    check("⚠ ungueltiger Tag -> 400 mit Grund", s == 400 and "Tag" in (d.get("error") or ""), "%s %s" % (s, d))
    check("… und es wurde nichts gespeichert",
          (ABL_B.read_bytes() if ABL_B.is_file() else None) == b_vorher)
    probe_tag = "Jarvis-Probe-" + uuid.uuid4().hex[:8]
    s, d = rufe("POST", "/api/wissen/confluence/bindung",
                {"auswahl": [{"key": key, "start": True}], "groups": [gruppe], "tags": ["#" + probe_tag]})
    neu_id = (d.get("bereich") or {}).get("id")
    check("Eintrag mit Tag wird angelegt", s == 200 and bool(neu_id), "%s %s" % (s, d))
    check("⚠ der Tag steht normiert im Eintrag (klein, ohne #)",
          (d.get("bereich") or {}).get("tags") == [probe_tag.lower()], str(d.get("bereich")))
    s, d = rufe("GET", "/api/wissen/confluence/bindung")
    zeile = next((b for b in (d.get("bereiche") or []) if b.get("id") == neu_id), None)
    check("die Liste liefert den Eintrag MIT Tags", bool(zeile) and zeile.get("tags") == [probe_tag.lower()],
          str(zeile))
finally:
    if neu_id:
        s, d = rufe("DELETE", "/api/wissen/confluence/bindung/" + neu_id)
        check("(Aufraeumen) Probe-Eintrag geloescht", s == 200, "%s %s" % (s, d))
    check("(Aufraeumen) die Einbindungs-Ablage ist byte-gleich",
          (ABL_B.read_bytes() if ABL_B.is_file() else None) == b_vorher)

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
