#!/usr/bin/env python3
"""Waechter: der Schnitt im LLM-Verlauf trifft die richtige Stelle.

DIE MELDUNG (ECHT, 2026-08-29): "es werden manchmal Context Inhalte vermischt
und doppelte Ergebnisse generiert – Vermutung: bei zwischenzeitlichem Loeschen
verrutscht der Context."

GEMESSEN in `data/chats/nexusandreas.bender/dbcbe98a0f9d/context.json`:

    [16] user   text            'generiere ein 300 auf 300 Pixel Comic Bild einer … Maus'
    [17] model  function_call   ->delegate
    [18] user   text            'generiere … eine gruene Kuh …'

Ein `function_call` OHNE `function_response`, davor eine Frage ohne Antwort –
und beides stand seit DREI TAGEN dort (Maus-Lauf 26.08. 19:17, Kuh-Lauf 29.08.
09:45). Im Transkript fehlte die Maus-Frage: der Benutzer hatte sie geloescht.

URSACHE: `_truncate_history_to_user_index` zaehlte `role == "user"`. Diese Rolle
tragen im Verlauf aber auch die WERKZEUG-ERGEBNISSE (`function_response`), der
Auto-Learning-Hinweis, der Zusammenfassungs-Eintrag der Kontext-Komprimierung
und die Anhang-Notiz. Der Client zaehlt seine sichtbaren Sprechblasen – beide
Seiten meinten dieselbe Zahl und meinten Verschiedenes.

Dieser Test fuehrt die ECHTEN Funktionen aus (per `ast` aus `backend/main.py`
und `backend/agent.py` geschnitten – ein Import zoege `backend.config` und
schriebe die Live-settings.json zurueck).

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import sys
import textwrap
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN_PY = WURZEL / "backend" / "main.py"
AGENT_PY = WURZEL / "backend" / "agent.py"

_ok = 0
_fail = 0


def pruef(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def abbruch(text):
    print(f"KONNTE NICHT LAUFEN: {text}")
    sys.exit(2)


for _p in (MAIN_PY, AGENT_PY):
    if not _p.exists():
        abbruch(f"{_p} fehlt")


def _lade(pfad, namen, klasse=None):
    """Holt Funktionen/Konstanten per `ast` aus einer Datei in einen Namensraum."""
    quelle = pfad.read_text(encoding="utf-8")
    zeilen = quelle.splitlines()
    baum = ast.parse(quelle)
    koerper = baum.body
    if klasse:
        kls = next((n for n in ast.walk(baum)
                    if isinstance(n, ast.ClassDef) and n.name == klasse), None)
        if kls is None:
            abbruch(f"Klasse {klasse} nicht in {pfad.name}")
        koerper = kls.body
    ns = {"print": lambda *a, **k: None}
    for name in namen:
        knoten = None
        for n in koerper:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
                knoten = n
            elif isinstance(n, ast.Assign) and any(
                    getattr(z, "id", "") == name for z in n.targets):
                knoten = n
        if knoten is None:
            abbruch(f"{name} fehlt in {pfad.name} – Fix nicht vorhanden?")
        start = min([knoten.lineno]
                    + [d.lineno for d in getattr(knoten, "decorator_list", [])])
        stueck = textwrap.dedent("\n".join(zeilen[start - 1:knoten.end_lineno]))
        if klasse:
            exec("class _H:\n" + textwrap.indent(stueck, "    "), ns)
            ns[name] = getattr(ns["_H"], name)
        else:
            exec(stueck, ns)
    return ns


# Die Frage-Erkennung lebt in agent.py (dort entstehen die internen Eintraege);
# main.py holt sie sich von dort. Der Test laedt sie ebenso aus EINER Quelle –
# eine zweite Fassung hier wuerde denselben Drift pruefen, der behoben wurde.
AG = _lade(AGENT_PY, ("INTERNE_VERLAUFS_MARKEN", "ist_benutzerfrage"))
M = _lade(MAIN_PY, ("_FORGET_MIN_LEN", "_eintrag_text", "_texte_passen",
                    "_entferne_offene_toolaufrufe",
                    "_truncate_history_to_user_index"))
M["_ist_benutzerfrage"] = AG["ist_benutzerfrage"]
M2 = _lade(MAIN_PY, ("_kontext_zuege", "_kontext_zuege_entfernen"))
for _n in ("_ist_benutzerfrage", "_eintrag_text", "_texte_passen", "_FORGET_MIN_LEN"):
    M2[_n] = M.get(_n, AG["ist_benutzerfrage"] if _n == "_ist_benutzerfrage" else None)
M2["_ist_benutzerfrage"] = AG["ist_benutzerfrage"]
A = _lade(AGENT_PY, ("_verlauf_reparieren",), klasse="JarvisAgent")
A["ist_benutzerfrage"] = AG["ist_benutzerfrage"]
zuege = M2["_kontext_zuege"]
vergessen = M2["_kontext_zuege_entfernen"]

trunc = M["_truncate_history_to_user_index"]
ist_frage = AG["ist_benutzerfrage"]
reparieren = A["_verlauf_reparieren"]


# ── Verlaufs-Attrappen: genau die Formen, die agent.py wirklich ablegt ───────
class P:
    def __init__(self, text=None, fc=None, fr=None, inline=None):
        self.text = text
        self.function_call = fc
        self.function_response = fr
        self.inline_data = inline


class C:
    def __init__(self, role, parts, mark=""):
        self.role, self.parts, self.mark = role, list(parts), mark

    def __repr__(self):
        return self.mark or f"<{self.role}>"


def frage(t, mark=None):
    return C("user", [P(text=t)], mark or f"?{t}")


def antwort(t, mark=None):
    return C("model", [P(text=t)], mark or f"!{t}")


def aufruf(name="delegate"):
    return C("model", [P(fc=name)], "fc")


def ergebnis(name="delegate"):
    return C("user", [P(fr=name)], "fr")


def marken(e):
    return [x.mark for x in e]


# ═══════════════════════════════════════════════════════════════════════════
print("1. Was als BENUTZERFRAGE zaehlt – und was nicht")
pruef(ist_frage(frage("Hallo")), "eine echte Frage zaehlt nicht")
pruef(not ist_frage(ergebnis()),
      "ein Werkzeug-Ergebnis zaehlt als Benutzerfrage – das ist der gemeldete Fehler")
pruef(not ist_frage(antwort("Text")), "eine Modell-Antwort zaehlt als Benutzerfrage")
for mark in AG["INTERNE_VERLAUFS_MARKEN"]:
    pruef(not ist_frage(C("user", [P(text=mark + " …")])),
          f"interner Eintrag zaehlt als Frage: {mark!r}")
pruef(not ist_frage(C("user", [P(text="\n\nWICHTIG – AUTO-LEARNING: Du hast …")])),
      "der Auto-Learning-Hinweis zaehlt als Benutzerfrage (fuehrender Leerraum)")
pruef(ist_frage(C("user", [P(inline=object())])),
      "eine Frage, die NUR aus einem Bild-Anhang besteht, zaehlt nicht mit")
pruef(not ist_frage(C("user", [])), "ein leerer Eintrag zaehlt als Frage")

print("\n2. DER GEMELDETE FALL: Schnitt mitten in einem Werkzeug-Turn")
# Ein Zug mit EINEM Werkzeugschritt. Der Client sieht: Frage1=0, Frage2=1.
def bau():
    return [frage("Frage1"), aufruf(), ergebnis(), antwort("Antwort1"),
            C("user", [P(text="\n\nWICHTIG – AUTO-LEARNING: …")], "lernhinweis"),
            frage("Frage2"), antwort("Antwort2"),
            frage("Frage3"), antwort("Antwort3")]


h = bau()
trunc(h, 1)   # "behalte den ersten Frage/Antwort-Zug"
pruef("!Antwort1" in marken(h),
      f"die Antwort auf Frage1 wurde mit weggeschnitten: {marken(h)}")
pruef("fr" in marken(h),
      f"das Werkzeug-Ergebnis wurde weggeschnitten, der Aufruf blieb: {marken(h)}")
pruef("?Frage2" not in marken(h), f"Frage2 haette weg gemusst: {marken(h)}")
pruef(not (marken(h) and marken(h)[-1] == "fc"),
      "der Verlauf endet auf einem offenen function_call")

h = bau()
trunc(h, 2)
pruef("?Frage2" in marken(h) and "!Antwort2" in marken(h),
      f"bei keep=2 fehlt der zweite Zug: {marken(h)}")
pruef("?Frage3" not in marken(h), f"bei keep=2 blieb Frage3 stehen: {marken(h)}")

h = bau()
pruef(trunc(h, 3) == 0, "bei keep=3 (= alle Fragen) wurde trotzdem geschnitten")
pruef(len(h) == 9, f"bei keep=3 wurden Eintraege entfernt: {marken(h)}")

print("   …und keep=0 leert wirklich alles")
h = bau()
trunc(h, 0)
pruef(h == [], f"keep=0 laesst etwas stehen: {marken(h)}")

print("\n3. Offene Werkzeug-Aufrufe ueberleben den Schnitt nicht")
h = [frage("F1"), antwort("A1"), frage("F2"), aufruf()]
weg = trunc(h, 2)
pruef(marken(h) == ["?F1", "!A1", "?F2"] or "fc" not in marken(h),
      f"der offene Aufruf blieb stehen: {marken(h)}")
pruef(weg >= 1, "die Entfernung wurde nicht gezaehlt")

print("\n4. Reparatur eines bereits beschaedigten Kontexts (ECHT-Form)")
echt = [frage("Nixe"), antwort("AntwortNixe"),
        frage("Maus"), aufruf(),            # <- der gemessene Rest
        frage("Kuh"), aufruf(), ergebnis(), antwort("Bild da")]
n = reparieren(echt)
pruef(n == 2, f"erwartet 2 entfernte Eintraege, entfernt: {n}")
pruef(marken(echt) == ["?Nixe", "!AntwortNixe", "?Kuh", "fc", "fr", "!Bild da"],
      f"die Reparatur trifft nicht die richtigen Eintraege: {marken(echt)}")

print("   …ein GESUNDER Verlauf bleibt unangetastet (Positivkontrolle)")
gesund = [frage("F1"), aufruf(), ergebnis(), antwort("A1"),
          C("user", [P(text="[Zusammenfassung des bisherigen Gesprächs]…")], "zus"),
          frage("F2"), antwort("A2")]
vorher = list(gesund)
pruef(reparieren(gesund) == 0, f"gesunder Verlauf wurde veraendert: {marken(gesund)}")
pruef(gesund == vorher, "die Liste wurde trotz 0 Treffern angefasst")

print("   …und die drei Formen einzeln")
f1 = [frage("F"), aufruf(), frage("G"), antwort("A")]          # call ohne response
pruef(reparieren(f1) >= 1 and "fc" not in marken(f1), f"Form 1 nicht erkannt: {marken(f1)}")
f2 = [frage("F"), ergebnis(), antwort("A")]                    # response ohne call
pruef(reparieren(f2) >= 1 and "fr" not in marken(f2), f"Form 2 nicht erkannt: {marken(f2)}")
f3 = [frage("F"), frage("G"), antwort("A")]                    # Frage ohne Antwort
n3 = reparieren(f3)
pruef(n3 == 1 and marken(f3) == ["?G", "!A"], f"Form 3 nicht erkannt: {marken(f3)} ({n3})")

print("   …eine unbeantwortete Frage am ENDE faellt ebenfalls")
f4 = [frage("F"), antwort("A"), frage("offen")]
pruef(reparieren(f4) == 1 and marken(f4) == ["?F", "!A"],
      f"die abgerissene letzte Frage blieb stehen: {marken(f4)}")

print("\n5. Die Reparatur laeuft NUR beim Laden, nicht in jedem Lauf")
# Der Hauptagent ist geteilt: waehrend ein Lauf auf sein Werkzeug wartet, ist
# ein offener function_call der Normalzustand. Wer dann repariert, wirft den
# laufenden Turn des anderen Benutzers weg.
_q = AGENT_PY.read_text(encoding="utf-8")
_baum = ast.parse(_q)
_zeilen = _q.splitlines()
_aufrufer = []
for _fn in ast.walk(_baum):
    if not isinstance(_fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for _k in ast.walk(_fn):
        if (isinstance(_k, ast.Call) and isinstance(_k.func, ast.Attribute)
                and _k.func.attr == "_verlauf_reparieren"):
            _aufrufer.append(_fn.name)
# ⚠ 2026-08-30 UMGESTELLT: geprueft wird die EIGENSCHAFT ("nur beim Laden"),
# nicht mehr die STELLE ("in run_task"). Die Lade-und-Heil-Logik ist nach
# `geheilter_sitzungskontext` gewandert, weil sie an DREI weiteren Ladestellen
# fehlte – und genau daran ist der Schutz gescheitert (Maus statt Kuh, siehe
# tests/test_kontext_laden.py). Ein Test, der die alte Stelle festschreibt,
# meldet die Reparatur dieses Fehlers als Fehler. Register: die Eigenschaft
# pruefen, nicht die Schreibweise.
pruef(_aufrufer == ["geheilter_sitzungskontext"],
      f"_verlauf_reparieren wird an unerwarteter Stelle gerufen: {_aufrufer} "
      f"(erwartet: ausschliesslich die eine Ladefunktion)")
_gh = next((n for n in ast.walk(_baum)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "geheilter_sitzungskontext"), None)
pruef(_gh is not None, "geheilter_sitzungskontext fehlt")
if _gh is not None:
    _rumpf = "\n".join(_zeilen[_gh.lineno - 1:_gh.end_lineno])
    _i_load = _rumpf.find("load_context(")
    _i_rep = _rumpf.find("_verlauf_reparieren(")
    pruef(_i_load != -1 and _i_rep != -1 and _i_load < _i_rep,
          "die Reparatur laeuft nicht unmittelbar nach dem Laden des Kontexts")
# Und der Lade-Zweig in run_task muss diese Funktion wirklich benutzen –
# sonst waere die Auslagerung eine Verschiebung ins Leere.
_rt = next(n for n in ast.walk(_baum)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "run_task")
_rt_rumpf = "\n".join(_zeilen[_rt.lineno - 1:_rt.end_lineno])
pruef("geheilter_sitzungskontext(" in _rt_rumpf,
      "run_task laedt den Sitzungs-Kontext nicht ueber die Heilfunktion")

print("\n6. Der Protokoll-Block sagt, worueber gezaehlt wird")
# Alle Clients (Web, Android, Windows) setzen diesen Algorithmus um. Stand dort
# "nur Rolle==user zaehlen", baut die naechste Portierung den Fehler nach.
_m = MAIN_PY.read_text(encoding="utf-8")
_block = _m[_m.index("# PROTOCOL: truncate_user_msg_index"):
            _m.index("def _truncate_history_to_user_index")]
pruef("SICHTBAREN" in _block or "sichtbar" in _block.lower(),
      "der Protokoll-Block nennt nicht, dass nur SICHTBARE Sprechblasen zaehlen")
pruef("function_response" in _block,
      "der Protokoll-Block warnt nicht davor, dass Werkzeug-Ergebnisse role=user tragen")
pruef("_ist_benutzerfrage" in _block,
      "der Protokoll-Block nennt die serverseitige Entscheidung nicht")

print("\n7. EINE Quelle: main.py baut die Frage-Erkennung nicht nach")
_mq = MAIN_PY.read_text(encoding="utf-8")
pruef("ist_benutzerfrage" in _mq and "from backend.agent import ist_benutzerfrage" in _mq,
      "main.py holt die Entscheidung nicht aus agent.py")
pruef("_INTERNE_USER_MARKEN" not in _mq,
      "main.py haelt eine ZWEITE Markenliste – genau der Drift, der den Fehler erzeugt hat")
_aq = AGENT_PY.read_text(encoding="utf-8")
pruef(_aq.count("INTERNE_VERLAUFS_MARKEN = (") == 1,
      "die Markenliste steht mehr als einmal in agent.py")

print("\n8. Geloeschte Nachricht faellt auch aus dem KONTEXT (ganzer Zug)")
def bau2():
    return [frage("Wie geht LDT-Import?"), aufruf(), ergebnis(), antwort("So geht das."),
            frage("Und die Hauptstadt von Italien?"), antwort("Rom."),
            frage("Danke, und Spanien?"), antwort("Madrid.")]

h = bau2()
pruef([z[2] for z in zuege(h)] == ["Wie geht LDT-Import?",
                                   "Und die Hauptstadt von Italien?",
                                   "Danke, und Spanien?"],
      f"die Zuege werden falsch abgegrenzt: {[z[2] for z in zuege(h)]}")

weg = vergessen(h, ["Und die Hauptstadt von Italien?"])
pruef(weg == 2, f"erwartet 2 entfernte Eintraege, entfernt {weg}")
pruef(marken(h) == ["?Wie geht LDT-Import?", "fc", "fr", "!So geht das.",
                    "?Danke, und Spanien?", "!Madrid."],
      f"der falsche Zug wurde entfernt: {marken(h)}")

print("   …der ganze Zug inkl. Werkzeugschritten")
h = bau2()
vergessen(h, ["Wie geht LDT-Import?"])
pruef("fc" not in marken(h) and "fr" not in marken(h),
      f"die Werkzeugschritte des Zugs blieben stehen: {marken(h)}")
pruef(reparieren(h) == 0, "nach dem Entfernen bleibt ein unvollstaendiger Zug zurueck")

print("   …mehrere auf einmal, und die Reihenfolge stimmt")
h = bau2()
vergessen(h, ["Wie geht LDT-Import?", "Danke, und Spanien?"])
pruef(marken(h) == ["?Und die Hauptstadt von Italien?", "!Rom."],
      f"Mehrfach-Entfernen trifft daneben: {marken(h)}")

print("   …unbekannter Text entfernt NICHTS")
h = bau2()
pruef(vergessen(h, ["gibt es nicht"]) == 0, "ein unbekannter Text entfernt Eintraege")
pruef(vergessen(h, []) == 0 and vergessen(h, ["", "  "]) == 0,
      "eine leere Liste entfernt Eintraege")
pruef(len(h) == 8, f"der Verlauf wurde trotzdem veraendert: {marken(h)}")

print("   …Zusatz am Text (Anhang-Marke / vorangestellter Text) trifft trotzdem")
h = [frage("Beschreibe das Bild bitte genau"), antwort("Ein Muster.")]
pruef(vergessen(list(h), ["Beschreibe das Bild bitte genau [🖼️ 3194f18ff7b1]"]) == 2,
      "die Anhang-Marke der Sprechblase verhindert den Treffer")
h2 = [frage("[Transkript von a.ogg]: … Beschreibe das Bild bitte genau"),
      antwort("Ein Muster.")]
pruef(vergessen(h2, ["Beschreibe das Bild bitte genau"]) == 2,
      "ein vorangestellter Transkript-Block verhindert den Treffer")

print("   …aber kurze Texte NUR exakt (sonst traefe 'ja' jede Frage)")
pruef(M["_texte_passen"]("ja", "ja"), "gleiche kurze Texte passen nicht")
pruef(not M["_texte_passen"]("ja bitte alles loeschen", "ja"),
      "ein kurzer Text trifft unscharf – damit faellt der falsche Zug")
pruef(M["_FORGET_MIN_LEN"] >= 8, "die Untergrenze fuer unscharfe Treffer ist zu klein")

print("   …und was VOR der ersten Frage steht, bleibt stehen")
h = [C("user", [P(text="[Zusammenfassung des bisherigen Gesprächs] …")], "zus"),
     frage("Erste echte Frage hier"), antwort("Antwort.")]
vergessen(h, ["Erste echte Frage hier"])
pruef(marken(h) == ["zus"], f"der Zusammenfassungs-Eintrag ging mit: {marken(h)}")

print("\n9. Der Client ruft den Weg wirklich auf")
CHAT_JS = WURZEL / "frontend" / "js" / "chat.js"
_c = CHAT_JS.read_text(encoding="utf-8")
pruef("context/forget" in _c, "chat.js ruft den Vergessen-Endpunkt nicht")
pruef(_c.count("_forgetInContext(") >= 3,
      "nicht beide Loeschwege (einzeln UND Mehrfachauswahl) melden den Kontext")
# Der Fragetext muss VOR dem Entfernen der Zeile gelesen werden – danach hat sie
# keine Vorgaenger mehr, und bei einer Antwort waere er leer.
_i_lese = _c.find("const _frage = _fragetextVon(row)")
_i_weg = _c.find("row.parentNode.removeChild(row)")
pruef(_i_lese != -1 and _i_weg != -1 and _i_lese < _i_weg,
      "der Fragetext wird erst NACH dem Entfernen der Zeile gelesen")
_i_sam = _c.find("checked.map(_fragetextVon)")
_i_del = _c.find("checked.forEach(row => { if (row.parentNode)")
pruef(_i_sam != -1 and _i_del != -1 and _i_sam < _i_del,
      "die Mehrfachauswahl liest die Texte erst nach dem Entfernen")
pruef("dataset.rawText" in _c[_c.find("function _fragetextVon"):
                              _c.find("function _fragetextVon") + 700],
      "der Fragetext kommt nicht aus dem ROHEN Text der Zeile")

print("\n10. Beim Loeschen einer Sitzung wird der RAM-Kontext des HAUPTAGENTEN verworfen")
_mq2 = MAIN_PY.read_text(encoding="utf-8")
_blk = _mq2[_mq2.index('@app.delete("/api/chat/sessions/{sid}")'):]
_blk = _blk[:_blk.index("@app.get(")]
pruef("agent_manager.main_agent" in _blk,
      "die Sitzungs-Loeschung raeumt den Verlauf des falschen Agenten")
pruef("agent_instance._user_histories" not in _blk,
      "es wird weiterhin agent_instance benutzt – dort liegen die Chat-Verlaeufe nicht")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
