#!/usr/bin/env python3
"""Waechter fuer das Aktivitaetsprotokoll (backend/aktivitaet.py, 2026-11-04).

Anlass: "wer hat den Wissensordner X angelegt?" liess sich nur ueber Zeitstempel
erschliessen, kein Endpunkt hielt seinen Ausloeser fest.

1. Modul im Sandkasten: schreiben, kappen, lesen (Filter VOR dem Deckel, Suche
   auch in den Details), Frist, ein Schreibfehler wirft nicht.
2. ``_aktivitaet`` aus main.py GESCHNITTEN UND AUSGEFUEHRT: IP aus dem Halter der
   Middleware, ``rechte=True`` schreibt zusaetzlich ins Sicherheitsprotokoll,
   ohne nicht; ein Fehler im Protokoll kippt den Endpunkt nicht.
3. REGEL am Syntaxbaum: jeder aendernde Endpunkt im Geltungsbereich ruft
   ``_aktivitaet`` – oder steht mit GRUND in ``AUSNAHMEN``. Eine gepflegte Liste
   der protokollierten Endpunkte gibt es bewusst nicht: ein neuer Endpunkt waere
   sonst still ungeprueft. Dazu: Bereich/Aktion sind Literale aus bekannten
   Mengen, kein Geheimnis-Feldname in den Details, kein ganzer Anfragekoerper,
   und die Rechte-Endpunkte setzen ``rechte``.
4. Jede Aktion und jeder Bereich hat einen Text in DE und EN.
5. Verdrahtung: Lese-Endpunkt nur fuer Administratoren, Aufbewahrungsfrist,
   Middleware-Halter traegt die IP, Abschnitt in settings.html/protokolle.js.

Ohne fastapi; backend.config nur als Attrappe; nichts im echten Bestand.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""

import ast
import contextvars
import json
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
SAND = Path(tempfile.mkdtemp(prefix="akt_test_"))

# ═══ 1. Modul ═══════════════════════════════════════════════════════════════
print("\n== 1. backend/aktivitaet.py im Sandkasten")
from backend import aktivitaet as AK  # noqa: E402

AK.DATEI = SAND / "logs" / "aktivitaet.jsonl"
if not str(AK.DATEI).startswith(str(SAND)):
    abbruch("Protokolldatei zeigt aus dem Sandkasten heraus")

e1 = AK.eintragen("anna", "wissen", "ordner_angelegt", "data/rag/Test/contoso",
                  ip="192.0.2.5", gruppen=["contoso"], leer="", nichts=None, null=0, aus=False)
pruefe(AK.DATEI.exists(), "Positivkontrolle: die Datei entsteht im Sandkasten")
zeilen = AK.DATEI.read_text(encoding="utf-8").splitlines()
roh = json.loads(zeilen[0]) if zeilen else {}
pruefe(roh.get("benutzer") == "anna" and roh.get("bereich") == "wissen"
       and roh.get("aktion") == "ordner_angelegt" and roh.get("objekt") == "data/rag/Test/contoso",
       "Kernfelder stehen in der Zeile")
d = roh.get("details") or {}
pruefe("leer" not in d and "nichts" not in d, "leere Werte werden weggelassen")
pruefe(d.get("null") == 0 and d.get("aus") is False, "0 und False bleiben stehen (keine Falsyness)")
pruefe(isinstance(roh.get("ts"), int), "Zeitstempel als Zahl")

lang = AK.eintragen("bert", "cron", "auftrag_angelegt", "x" * 5000,
                    liste=list(range(AK.LISTE_MAX + 7)))
pruefe(len(lang["objekt"]) <= AK.WERT_MAX + 1, "ueberlanger Gegenstand wird gekappt")
li = lang["details"]["liste"]
pruefe(len(li) == AK.LISTE_MAX + 1 and "7 weitere" in str(li[-1]),
       "ueberlange Liste gekappt UND die Kappung beziffert")
AK.eintragen("carla", "skills", "skill_eingeschaltet", "sap")
AK.eintragen("anna", "wissen", "datei_gruppen_gesetzt", "data/rag/a.pdf", gruppen=["contoso"])

r = AK.lesen(limit=200)
pruefe([e["benutzer"] for e in r["eintraege"]] == ["anna", "carla", "bert", "anna"],
       "juengste zuerst")
pruefe(r["bereiche"] == ["cron", "skills", "wissen"], "Bereiche aus dem Bestand, sortiert")
r = AK.lesen(limit=200, suche="CONTOSO")
pruefe(r["gesamt"] == 2, "Suche trifft Gegenstand UND Details, ohne Gross/Klein (%d)" % r["gesamt"])
r = AK.lesen(limit=1, suche="contoso")
pruefe(len(r["eintraege"]) == 1 and r["gesamt"] == 2,
       "Deckel nach dem Filter, gesamt zaehlt alle Treffer")
r = AK.lesen(limit=200, bereich="skills")
pruefe(r["gesamt"] == 1 and r["bereiche"] == ["cron", "skills", "wissen"],
       "Bereichsfilter – die Bereichsliste bleibt vollstaendig (sonst verschwaende die Auswahl)")
r = AK.lesen(limit=200, benutzer="ANN")
pruefe(r["gesamt"] == 2, "Benutzerfilter als Teilstring ohne Gross/Klein")

with AK.DATEI.open("a", encoding="utf-8") as f:
    f.write("kaputt\n" + json.dumps({"aktion": "ohne_ts"}) + "\n")
pruefe(AK.lesen()["gesamt"] == 5, "eine kaputte Zeile bricht das Lesen nicht ab")
weg = AK.prune_older_than(roh["ts"] + 10 ** 9)
pruefe(weg == 4, "Frist entfernt die vier datierten Eintraege (%d)" % weg)
rest = [z for z in AK.DATEI.read_text(encoding="utf-8").splitlines() if z.strip()]
pruefe(len(rest) == 2 and any("ohne_ts" in z for z in rest),
       "ohne Zeitstempel kein Altersbeweis: bleibt stehen (fail-closed)")

_alt = AK.DATEI
AK.DATEI = SAND / "datei_statt_ordner" / "x.jsonl"
(SAND / "datei_statt_ordner").write_text("blockiert")
try:
    AK.eintragen("anna", "wissen", "ordner_angelegt", "y")
    pruefe(True, "ein Schreibfehler wirft nicht (wird nur gemeldet)")
except Exception as e:  # noqa: BLE001
    pruefe(False, "ein Schreibfehler wirft nicht – geworfen: %r" % e)
AK.DATEI = _alt

# ═══ 2. _aktivitaet ausgefuehrt ═════════════════════════════════════════════
print("\n== 2. _aktivitaet aus main.py, geschnitten und ausgefuehrt")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
if "_aktivitaet" not in FN:
    abbruch("_aktivitaet fehlt in main.py")

sicher = []
ns = {"_admin_anfrage": contextvars.ContextVar("h", default=None),
      "_sicherheits_log": types.SimpleNamespace(
          ereignis=lambda art, **kw: sicher.append((art, kw)))}
exec(compile(ast.Module([FN["_aktivitaet"]], []), "main._aktivitaet", "exec"), ns)
akt = ns["_aktivitaet"]
AK.DATEI = SAND / "logs2" / "aktivitaet.jsonl"

marke = ns["_admin_anfrage"].set({"ip": "192.0.2.9"})
akt("anna", "wissen", "gruppe_geaendert", "contoso", rechte=True, editors_users="x.y")
akt("anna", "wissen", "ordner_angelegt", "data/rag/b")
ns["_admin_anfrage"].reset(marke)
ge = AK.lesen()["eintraege"]
pruefe(len(ge) == 2, "Positivkontrolle: beide Aufrufe landen im Protokoll")
ge_rechte = next((e for e in ge if e.get("aktion") == "gruppe_geaendert"), {})
pruefe((ge_rechte.get("details") or {}).get("ip") == "192.0.2.9",
       "IP kommt aus dem Halter der Middleware")
pruefe((ge_rechte.get("details") or {}).get("rechte") is True,
       "die Rechte-Markierung steht im Eintrag (die Ansicht hebt sie hervor)")
pruefe(len(sicher) == 1 and sicher[0][0] == "rechte_aenderung"
       and sicher[0][1].get("objekt") == "contoso" and sicher[0][1].get("ip") == "192.0.2.9",
       "rechte=True schreibt GENAU EINEN Eintrag ins Sicherheitsprotokoll")
pruefe(not any(k in sicher[0][1] for k in ("editors_users",)) if sicher else False,
       "ins Sicherheitsprotokoll gehen keine Details (nur Bereich/Aktion/Gegenstand)")
akt("anna", "wissen", "x", "ohne Halter")
pruefe(len(sicher) == 1, "ohne rechte kein Sicherheitseintrag; ohne Halter kein Absturz")

_ein = AK.eintragen
AK.eintragen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Platte voll"))
ns["_sicherheits_log"].ereignis = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("weg"))
try:
    akt("anna", "wissen", "y", "z", rechte=True)
    pruefe(True, "ein Fehler in BEIDEN Protokollen kippt den Endpunkt nicht")
except Exception as e:  # noqa: BLE001
    pruefe(False, "ein Fehler im Protokoll kippt den Endpunkt nicht – geworfen: %r" % e)
AK.eintragen = _ein

sys.path.insert(0, str(ROOT / "tests" / "lib"))
import aktivitaet_attrappe as _att  # noqa: E402
pruefe(_att.signatur_passt(),
       "die Attrappe fuer fremde Pruefstaende (tests/lib) hat die echte Signatur")

# ═══ 3. Regel: Abdeckung der aendernden Endpunkte ═══════════════════════════
print("\n== 3. Jeder aendernde Endpunkt im Geltungsbereich protokolliert")
GELTUNG = ("/api/knowledge/", "/api/wissen/", "/api/wissensgraph/", "/api/cron",
           "/api/skills/", "/api/profiles", "/api/llm/profiles/", "/api/agent_roles",
           "/api/instructions/", "/api/jira/assist/vorlagen", "/api/info_files")
BEREICHE = {"wissen", "wissensgraph", "cron", "skills", "profile", "rollen",
            "anweisungen", "jira", "portal"}
# (Methode, Pfad) -> Grund. Ein Endpunkt steht hier nur, wenn er den gemeinsamen
# Bestand NICHT aendert – sonst gehoert ein _aktivitaet-Aufruf hinein.
AUSNAHMEN = {
    ("POST", "/api/profiles/zertifikat/probe"): "misst nur das Zertifikat einer Formular-Adresse",
    ("POST", "/api/profiles/test"): "testet ungespeicherte Formularwerte",
    ("POST", "/api/profiles/capabilities"): "liest Modell-Metadaten",
    ("POST", "/api/profiles/capabilities/probe"): "Mini-Anfragen ans Modell, nichts gespeichert",
    ("POST", "/api/profiles/models"): "listet Modelle fuer Formularwerte",
    ("POST", "/api/llm/profiles/{profile_id}/activate"): "persoenliche Profilwahl, betrifft nur den Benutzer",
    ("POST", "/api/skills/reload"): "laedt Skills neu, aendert keinen Bestand",
    ("POST", "/api/jira/assist/vorlagen/standard"): "persoenlicher Standard (Stern), betrifft nur den Benutzer",
    ("POST", "/api/wissensgraph/rueckmeldung"): "persoenliche Rueckmeldung, betrifft nur den eigenen Blick",
    ("DELETE", "/api/wissensgraph/rueckmeldung"): "setzt die eigenen Rueckmeldungen zurueck",
    ("POST", "/api/knowledge/open-folder"): "oeffnet nur eine Ansicht auf dem Server-Desktop",
    ("POST", "/api/knowledge/sync/probe"): "testet einen Standort vor dem Speichern",
    ("POST", "/api/wissen/extract"): "eigener Entwurf (created_by), erst die Uebernahme aendert den Bestand",
    ("POST", "/api/wissen/extract/upload"): "eigener Entwurf (created_by)",
    ("PATCH", "/api/wissen/pending/{doc_id}"): "eigener Entwurf (created_by)",
    ("DELETE", "/api/wissen/pending/{doc_id}"): "eigener Entwurf (created_by)",
    ("POST", "/api/wissen/extract/confluence"): "eigene Entwuerfe (created_by)",
    ("POST", "/api/wissen/extract/cancel"): "bricht den eigenen Abruf ab",
    ("PUT", "/api/wissen/destillat/filter"): "persoenlicher Dateifilter",
    ("POST", "/api/wissen/destillat/extract"): "liest hochgeladene Dateien, speichert nichts",
    ("POST", "/api/wissen/destillat/lauf"): "Modellaufruf, speichert nichts",
    ("POST", "/api/wissen/destillat/uebernehmen"): "legt einen eigenen Entwurf an (created_by)",
    ("POST", "/api/knowledge/extract"): "Entwurf; die Uebernahme wird protokolliert",
    ("POST", "/api/knowledge/extract/cancel"): "bricht einen Abruf ab",
    ("POST", "/api/knowledge/extract/upload"): "Entwurf; die Uebernahme wird protokolliert",
    ("POST", "/api/knowledge/extract/confluence"): "Entwuerfe; die Uebernahme wird protokolliert",
    ("POST", "/api/knowledge/cleanup/analyse"): "Vorschlag, schreibt nichts (/apply protokolliert)",
    ("POST", "/api/knowledge/cleanup/prompt"): "rechnet nur, aendert nichts",
    ("POST", "/api/knowledge/cleanup/regeln"): "Modellaufruf, schreibt nichts",
    ("POST", "/api/knowledge/cleanup/abgleich"): "Modellaufruf, schreibt nichts",
    ("POST", "/api/knowledge/cleanup/konflikte"): "Modellaufruf, schreibt nichts",
    ("POST", "/api/knowledge/cleanup/behebbar"): "rechnet nur, aendert nichts",
    ("POST", "/api/knowledge/mounts/{idx}/diagnose"): "misst nur, aendert nichts",
}
# Endpunkte, die WER-DARF-WAS aendern: ihr Aufruf muss `rechte` setzen
RECHTE_PFLICHT = {
    ("PATCH", "/api/knowledge/groups/{gid}"), ("DELETE", "/api/knowledge/groups/{gid}"),
    ("POST", "/api/knowledge/shares"), ("PATCH", "/api/knowledge/shares/{share_id}"),
    ("POST", "/api/knowledge/shares/{share_id}/rotate"),
    ("DELETE", "/api/knowledge/shares/{share_id}"), ("POST", "/api/knowledge/webdav/config"),
    ("POST", "/api/cron/{job_id}/claim"), ("PUT", "/api/profiles/{profile_id}"),
}
# Feldnamen, die nie in den Details stehen duerfen (Geheimnisse, Inhalte)
VERBOTEN = {"password", "passwort", "kennwort", "token", "api_key", "secret", "geheimnis",
            "content", "inhalt", "text", "prompt", "markdown", "body", "data", "task"}

routen = {}
for n in BAUM.body:
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for dek in n.decorator_list:
        if (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)
                and isinstance(dek.func.value, ast.Name) and dek.func.value.id == "app"
                and dek.func.attr in ("post", "put", "patch", "delete") and dek.args
                and isinstance(dek.args[0], ast.Constant)
                and str(dek.args[0].value).startswith(GELTUNG)):
            routen[(dek.func.attr.upper(), dek.args[0].value)] = n


def aufrufe(fn):
    return [c for c in ast.walk(fn) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name) and c.func.id == "_aktivitaet"]


pruefe(len(routen) >= 100, "Positivkontrolle: Geltungsbereich erfasst %d Endpunkte" % len(routen))
pruefe(("POST", "/api/knowledge/folders") in routen and ("POST", "/api/cron") in routen,
       "Positivkontrolle: der Anlass (Ordner anlegen) und Cron sind im Geltungsbereich")
if len(routen) < 50:
    abbruch("Geltungsbereich leer – Suchmuster blind")

fehlt = sorted(k for k, fn in routen.items() if not aufrufe(fn) and k not in AUSNAHMEN)
pruefe(not fehlt, "jeder aendernde Endpunkt ruft _aktivitaet oder ist begruendet ausgenommen"
       + ("" if not fehlt else " – fehlt: " + ", ".join(f"{m} {p}" for m, p in fehlt)))
veraltet = sorted(k for k in AUSNAHMEN if k not in routen)
pruefe(not veraltet, "keine Ausnahme fuer einen Endpunkt, den es nicht gibt"
       + ("" if not veraltet else ": " + str(veraltet)))
doppelt = sorted(k for k in AUSNAHMEN if k in routen and aufrufe(routen[k]))
pruefe(not doppelt, "keine Ausnahme fuer einen Endpunkt, der doch protokolliert"
       + ("" if not doppelt else ": " + str(doppelt)))
pruefe(all(len(g) >= 10 for g in AUSNAHMEN.values()), "jede Ausnahme traegt einen Grund")

def koerper_namen(fn):
    """Namen, denen in diesem Endpunkt der ANFRAGEKOERPER zugewiesen wird
    (``x = await request.json()`` / ``x = await _json_objekt(request)``).
    Gemessen wird die Herkunft, nicht der Variablenname – ``b`` ist im
    Trennen-Endpunkt ein Begriff, in den Jira-Vorlagen der Koerper."""
    aus = set()
    for st in ast.walk(fn):
        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Await) \
                and isinstance(st.value.value, ast.Call):
            f = st.value.value.func
            if (isinstance(f, ast.Attribute) and f.attr == "json") or \
                    (isinstance(f, ast.Name) and f.id == "_json_objekt"):
                aus |= {t.id for t in st.targets if isinstance(t, ast.Name)}
    return aus


pruefe(koerper_namen(routen.get(("POST", "/api/knowledge/folders"), ast.parse(""))) == {"data"},
       "Positivkontrolle: die Koerper-Erkennung findet `data` im Ordner-Endpunkt")
alle = []
for fn in [n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
    kn = koerper_namen(fn)
    alle += [(c, kn) for c in aufrufe(fn)]
AKTIONEN = set()
nicht_literal, fremd_bereich, verboten, ganz = [], [], [], []
for c, kn in alle:
    if len(c.args) < 3 or not all(isinstance(a, ast.Constant) and isinstance(a.value, str)
                                  for a in c.args[1:3]):
        nicht_literal.append(c.lineno)
        continue
    if c.args[1].value not in BEREICHE:
        fremd_bereich.append((c.lineno, c.args[1].value))
    AKTIONEN.add(c.args[2].value)
    for kw in c.keywords:
        if kw.arg and kw.arg.lower() in VERBOTEN:
            verboten.append((c.lineno, kw.arg))
        if isinstance(kw.value, ast.Name) and kw.value.id in kn:
            ganz.append((c.lineno, kw.arg or "**" + kw.value.id))
pruefe(len(alle) >= 80, "Positivkontrolle: %d Aufrufe gefunden" % len(alle))
pruefe(not nicht_literal, "Bereich und Aktion sind Literale (Texte und Filter haengen daran)"
       + ("" if not nicht_literal else f" – Zeilen {nicht_literal}"))
pruefe(not fremd_bereich, "nur bekannte Bereiche" + ("" if not fremd_bereich else f": {fremd_bereich}"))
pruefe(not verboten, "kein Geheimnis-/Inhalts-Feldname in den Details"
       + ("" if not verboten else f": {verboten}"))
pruefe(not ganz, "nie der ganze Anfragekoerper als Detail" + ("" if not ganz else f": {ganz}"))

ohne_rechte = sorted(k for k in RECHTE_PFLICHT
                     if k not in routen or not any(any(kw.arg == "rechte" for kw in c.keywords)
                                                   for c in aufrufe(routen[k])))
pruefe(not ohne_rechte, "Rechte-Endpunkte setzen `rechte`"
       + ("" if not ohne_rechte else ": " + str(ohne_rechte)))

# ═══ 4. Texte ═══════════════════════════════════════════════════════════════
print("\n== 4. Jede Aktion und jeder Bereich hat einen Text (DE und EN)")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
schl = re.findall(r"^\s*'(plog\.akt\.[a-z_]+)'\s*:", I18N, re.M)
zahl = {k: schl.count(k) for k in set(schl)}
pruefe(zahl.get("plog.akt.titel") == 2, "Positivkontrolle: Abschnittstitel in beiden Sprachen")
ohne = sorted(a for a in AKTIONEN if zahl.get("plog.akt.a_" + a) != 2)
pruefe(not ohne, "jede Aktion in DE und EN" + ("" if not ohne else ": " + ", ".join(ohne)))
ohne_b = sorted(b for b in BEREICHE if zahl.get("plog.akt.b_" + b) != 2)
pruefe(not ohne_b, "jeder Bereich in DE und EN" + ("" if not ohne_b else ": " + ", ".join(ohne_b)))

# ═══ 5. Verdrahtung ═════════════════════════════════════════════════════════
print("\n== 5. Verdrahtung")
lese = FN.get("protokoll_aktivitaet")
pruefe(lese is not None and any(ast.unparse(d) == "app.get('/api/logs/aktivitaet')"
                                for d in lese.decorator_list),
       "Lese-Endpunkt GET /api/logs/aktivitaet")
pruefe(lese is not None and "Depends(require_local_auth)" in ast.unparse(lese.args),
       "Lesen nur fuer Administratoren")
pruefe(lese is not None and not any(ast.unparse(d).startswith("app.delete")
                                    for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef)
                                    for d in n.decorator_list
                                    if "/api/logs/aktivitaet" in ast.unparse(d)),
       "kein Loesch-Endpunkt (nur die Frist entfernt Zeilen)")
mw = FN.get("_sicherheits_protokoll_mw")
pruefe(mw is not None and re.search(r"halter\s*:\s*dict\s*=\s*\{'ip'", ast.unparse(mw)) is not None,
       "die Middleware legt die IP in den Halter")
RET = (ROOT / "backend" / "log_retention.py").read_text(encoding="utf-8")
pruefe('("aktivitaet", _prune_aktivitaet)' in RET and "aktivitaet.prune_older_than" in RET,
       "Aktivitaetsprotokoll unterliegt der Aufbewahrungsfrist")
HTML = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
pruefe('data-plog="akt"' in HTML and 'id="plog-akt-tbody"' in HTML and 'id="plog-akt-bereich"' in HTML,
       "Abschnitt in settings.html")
PJS = (ROOT / "frontend" / "js" / "protokolle.js").read_text(encoding="utf-8")
pruefe(re.search(r"\n\s+akt:\s*\{", PJS) is not None and "/api/logs/aktivitaet" in PJS,
       "Quelle in protokolle.js")
TJS = (ROOT / "frontend" / "js" / "telemetry.js").read_text(encoding="utf-8")
pruefe("['akt', " in TJS, "'Alles aktualisieren' erfasst den Abschnitt")

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
