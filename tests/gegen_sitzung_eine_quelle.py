#!/usr/bin/env python3
"""Gegenprobe: beissen die drei Waechter zum Vorfall vom 2026-10-01?

Geprueft werden
  tests/test_sitzung_eine_quelle.js        (die REGEL: eine Quelle, richtige Reihenfolge)
  tests/test_dlkey_token_schluessel.js     (die WIRKUNG: der Chip traegt ein Token)
  tests/test_abruf_401_protokoll.py        (der 401 hinterlaesst eine Zeile mit Grund)

WAS DIESES SKRIPT AUS DEM REGISTER UEBERNIMMT – jede Zeile ist dort bezahlt:
  * **Gruener Basislauf ZUERST.** Ohne gruene Basis ist keine Gegenprobe
    deutbar: jede Probe zaehlte sonst eine FAIL zu viel.
  * **Sicherung auf PLATTE, nicht im Speicher**, und beim naechsten Start
    zurueckgenommen (Laufmarke). Ein von `timeout` abgeschossener Lauf laesst
    die Sabotage sonst im Arbeitsbaum liegen – der naechste Waechterlauf meldet
    dann Fehler, die es im Code nicht gibt.
  * **Nach dem Wiederherstellen md5 vergleichen**, nicht annehmen.
  * **Die Dateiliste wird als REGEL geprueft** (jede von einer Probe angefasste
    Datei muss gesichert sein), nicht gepflegt.
  * **`PYTHONDONTWRITEBYTECODE=1`**: Sabotage und Wiederherstellung in derselben
    Sekunde bei gleicher Groesse laden sonst aus der `.pyc` die SABOTAGE.
  * **Jede Sabotage muss die Datei WIRKLICH aendern.** Eine Probe, die ihr Ziel
    verfehlt, sieht wie ein zahnloser Waechter aus – sie wird hier getrennt
    gemeldet ("PROBE VERFEHLT"), damit niemand den Waechter beschuldigt.

NICHT in einem Sammellauf mitlaufen lassen – dieses Skript patcht Dateien.

Aufruf: python3 tests/gegen_sitzung_eine_quelle.py
Exit 0 = alle Proben beissen · 1 = mindestens eine nicht · 2 = konnte nicht laufen
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SICHERUNG = os.path.expanduser("~/.gegen-sitzung-sicherung")
MARKE = os.path.expanduser("~/.gegen-sitzung-marke")

UMGEBUNG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

W_REGEL = "tests/test_sitzung_eine_quelle.js"
W_WIRKUNG = "tests/test_dlkey_token_schluessel.js"
W_PROTOKOLL = "tests/test_abruf_401_protokoll.py"

WAECHTER = {
    W_REGEL: ["node", W_REGEL],
    W_WIRKUNG: ["node", W_WIRKUNG],
    W_PROTOKOLL: [sys.executable, W_PROTOKOLL],
}

DATEIEN = [
    "frontend/js/sitzung.js",
    "frontend/js/dlkey.js",
    "frontend/js/knowledge_sync.js",
    "frontend/chat.html",
    "backend/main.py",
    "backend/download_key.py",
]


def md5(pfad):
    with open(pfad, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def lies(rel):
    return open(os.path.join(WURZEL, rel), encoding="utf-8").read()


def schreib(rel, text):
    with open(os.path.join(WURZEL, rel), "w", encoding="utf-8") as fh:
        fh.write(text)


# ── Sicherung / Wiederherstellung ────────────────────────────────────────
def sichern():
    """Sicherung bei JEDEM Lauf erneuern – eine alte stellt sonst einen
    veralteten Stand her und macht fertige Arbeit zunichte (Register)."""
    os.makedirs(SICHERUNG, exist_ok=True)
    for rel in DATEIEN:
        quelle = os.path.join(WURZEL, rel)
        if not os.path.exists(quelle):
            print("ABBRUCH (Exit 2): %s fehlt – Sicherung unmoeglich." % rel)
            sys.exit(2)
        ziel = os.path.join(SICHERUNG, rel.replace("/", "__"))
        shutil.copy2(quelle, ziel)
    print("  gesichert: %d Dateien nach %s" % (len(DATEIEN), SICHERUNG))


def zurueck(still=False):
    fehler = []
    for rel in DATEIEN:
        ziel = os.path.join(WURZEL, rel)
        quelle = os.path.join(SICHERUNG, rel.replace("/", "__"))
        if not os.path.exists(quelle):
            continue
        shutil.copy2(quelle, ziel)
        if md5(quelle) != md5(ziel):
            fehler.append(rel)
    if fehler:
        print("\033[31mWARNUNG: nicht byte-gleich wiederhergestellt: %s\033[0m"
              % ", ".join(fehler))
        return False
    if not still:
        print("  wiederhergestellt und md5-geprueft: %d Dateien" % len(DATEIEN))
    return True


# ── Waechterlauf ─────────────────────────────────────────────────────────
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BILANZ_OKFAIL = re.compile(r"Ergebnis:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL")
_BILANZ_BRUCH = re.compile(r"Ergebnis:\s*(\d+)\s*/\s*(\d+)")


def lauf(name):
    """(exitcode, FAIL-Anzahl oder None, Ausgabe) eines Waechters.

    ⚠ DIE ZAHL WIRD AUS DER BILANZZEILE GELESEN, NICHT GEZAEHLT. Ein
    `aus.count("FAIL")` traf im Register schon die OK-Zahl und haette JEDE
    Probe als "beisst" gemeldet, solange ueberhaupt etwas gruen war. Und die
    ANSI-Escapes muessen vorher weg – ein Muster auf "Ergebnis" trifft sonst
    nicht (ebenfalls Register). `None` heisst KEINE Bilanz: ein stiller
    Abbruch, der von "bestanden" unterscheidbar bleiben muss.
    """
    erg = subprocess.run(WAECHTER[name], cwd=WURZEL, env=UMGEBUNG,
                         capture_output=True, text=True, timeout=180)
    aus = _ANSI.sub("", erg.stdout + erg.stderr)
    m = _BILANZ_OKFAIL.search(aus)
    if m:
        return erg.returncode, int(m.group(2)), aus
    m = _BILANZ_BRUCH.search(aus)
    if m:
        return erg.returncode, int(m.group(2)) - int(m.group(1)), aus
    return erg.returncode, None, aus


# ── Die Proben ───────────────────────────────────────────────────────────
def p_dlkey_blind():
    """Der ORIGINALFEHLER: dlkey.js liest wieder nur jarvis_token."""
    t = lies("frontend/js/dlkey.js")
    alt = "    function tok() { return window.JarvisSitzung.token(); }"
    neu = ("    function tok() { try { return localStorage.getItem('jarvis_token') "
           "|| ''; } catch (e) { return ''; } }")
    if alt not in t:
        return None
    schreib("frontend/js/dlkey.js", t.replace(alt, neu))
    return [W_WIRKUNG, W_REGEL]


def p_kette_einelementig():
    """sitzung.js fuehrt nur noch EINEN Token-Schluessel."""
    t = lies("frontend/js/sitzung.js")
    alt = "var TOKEN_SCHLUESSEL = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];"
    neu = "var TOKEN_SCHLUESSEL = ['jarvis_token'];"
    if alt not in t:
        return None
    schreib("frontend/js/sitzung.js", t.replace(alt, neu))
    return [W_WIRKUNG]


def p_vorrang_weg():
    """Der eigene Schluessel der Seite hat keinen Vorrang mehr."""
    t = lies("frontend/js/sitzung.js")
    alt = """            if (bevorzugt) {
                var b = localStorage.getItem(bevorzugt);
                if (b) return b;
            }
"""
    if alt not in t:
        return None
    schreib("frontend/js/sitzung.js", t.replace(alt, ""))
    return [W_WIRKUNG]


def p_quelle_leer():
    """sitzung.js ist da, tut aber nichts – Positivkontrolle des Waechters."""
    t = lies("frontend/js/sitzung.js")
    if "window.JarvisSitzung" not in t:
        return None
    schreib("frontend/js/sitzung.js", "/* leer */\n")
    return [W_REGEL]


def p_einbindung_weg():
    """chat.html laedt sitzung.js nicht mehr."""
    t = lies("frontend/chat.html")
    import re
    neu = re.sub(r'<script src="/static/js/sitzung\.js\?v=\d+"></script>\n', "", t)
    if neu == t:
        return None
    schreib("frontend/chat.html", neu)
    return [W_REGEL]


def p_einbindung_zu_spaet():
    """sitzung.js steht in chat.html HINTER den Konsumenten."""
    import re
    t = lies("frontend/chat.html")
    m = re.search(r'<script src="/static/js/sitzung\.js\?v=\d+"></script>\n', t)
    if not m:
        return None
    tag = m.group(0)
    ohne = t.replace(tag, "", 1)
    # ganz an das Ende der Skriptliste haengen
    neu = ohne.replace("</body>", tag + "</body>", 1)
    if neu == t or tag not in neu:
        return None
    schreib("frontend/chat.html", neu)
    return [W_REGEL]


def p_zweite_liste():
    """Eine zweite Schluessel-Liste kehrt zurueck (die Drift-Ursache)."""
    t = lies("frontend/js/knowledge_sync.js")
    alt = """    function token() {
        return window.JarvisSitzung.token();
    }"""
    neu = """    function token() {
        for (const k of ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token']) {
            const v = localStorage.getItem(k);
            if (v) return v;
        }
        return '';
    }"""
    if alt not in t:
        return None
    schreib("frontend/js/knowledge_sync.js", t.replace(alt, neu))
    return [W_REGEL]


def p_protokoll_weg():
    """Der 401 wird wieder still – der Zustand, der die Suche gekostet hat."""
    t = lies("backend/main.py")
    alt = "    _prot_abruf_abgewiesen(request)\n    raise HTTPException(status_code=401, detail=\"Nicht authentifiziert\")"
    neu = "    raise HTTPException(status_code=401, detail=\"Nicht authentifiziert\")"
    if alt not in t:
        return None
    schreib("backend/main.py", t.replace(alt, neu, 1))
    return [W_PROTOKOLL]


def p_grund_konstant():
    """grund() sagt immer dasselbe – richtig und nutzlos (Register)."""
    t = lies("backend/download_key.py")
    alt = '    if not wert:\n        return "kein Token in der Adresse"'
    neu = '    return "nicht authentifiziert"\n    if not wert:\n        return "kein Token in der Adresse"'
    if alt not in t:
        return None
    schreib("backend/download_key.py", t.replace(alt, neu, 1))
    return [W_PROTOKOLL]


def p_grund_verraet_schluessel():
    """grund() schreibt das Zugangsmerkmal ins Protokoll."""
    t = lies("backend/download_key.py")
    alt = '    if not wert:\n        return "kein Token in der Adresse"'
    neu = '    if not wert:\n        return "kein Token in der Adresse"\n    return "abgewiesen: " + wert'
    if alt not in t:
        return None
    schreib("backend/download_key.py", t.replace(alt, neu, 1))
    return [W_PROTOKOLL]


PROBEN = [
    ("dlkey.js liest wieder nur jarvis_token (DER VORFALL)", p_dlkey_blind),
    ("sitzung.js fuehrt nur einen Schluessel", p_kette_einelementig),
    ("der eigene Schluessel der Seite hat keinen Vorrang", p_vorrang_weg),
    ("sitzung.js ist leer (Positivkontrolle)", p_quelle_leer),
    ("chat.html laedt sitzung.js nicht", p_einbindung_weg),
    ("sitzung.js steht hinter den Konsumenten", p_einbindung_zu_spaet),
    ("eine zweite Schluessel-Liste kehrt zurueck", p_zweite_liste),
    ("der 401 wird wieder still protokolliert", p_protokoll_weg),
    ("der Grund ist konstant", p_grund_konstant),
    ("der Grund verraet den Schluessel", p_grund_verraet_schluessel),
]


# ── Regel: jede angefasste Datei ist gesichert ───────────────────────────
def pruefe_dateiliste():
    """Die Liste wird GEPRUEFT, nicht gepflegt: jede Datei, die eine Probe
    anfasst, muss in DATEIEN stehen. Ermittelt aus dem eigenen Quelltext –
    sonst fehlt genau die Datei, die zuletzt dazukam (Register)."""
    import ast
    eigen = ast.parse(open(os.path.abspath(__file__), encoding="utf-8").read())
    angefasst = set()
    for k in ast.walk(eigen):
        if isinstance(k, ast.Call):
            name = getattr(k.func, "id", "")
            if name in ("schreib", "lies") and k.args and isinstance(k.args[0], ast.Constant):
                angefasst.add(k.args[0].value)
    fehlen = angefasst - set(DATEIEN)
    if fehlen:
        print("ABBRUCH (Exit 2): Proben fassen Dateien an, die NICHT gesichert "
              "werden: %s" % ", ".join(sorted(fehlen)))
        sys.exit(2)
    return angefasst


# ── Hauptlauf ────────────────────────────────────────────────────────────
def main():
    print("\n\033[1mGegenprobe: Sitzungstoken aus einer Quelle\033[0m")

    # Rueckstand eines abgeschossenen Laufs zuerst zurueknehmen.
    if os.path.exists(MARKE):
        print("\n\033[33mLaufmarke gefunden – ein frueherer Lauf wurde "
              "abgebrochen. Nehme den Rueckstand zurueck.\033[0m")
        zurueck()
        os.remove(MARKE)

    angefasst = pruefe_dateiliste()
    print("  Dateiliste geprueft: %d angefasst, alle gesichert" % len(angefasst))

    print("\n\033[1m0. Basislauf – ohne gruene Basis ist keine Probe deutbar\033[0m")
    basis = {}
    for name in WAECHTER:
        code, fails, aus = lauf(name)
        basis[name] = fails
        print("  %-42s Exit %d, %s FAIL" % (name, code, fails))
        if code != 0 or fails:
            print("\033[31mABBRUCH (Exit 2): %s ist nicht gruen – "
                  "Gegenproben waeren nicht deutbar.\033[0m" % name)
            print(aus[-2000:])
            sys.exit(2)

    sichern()
    open(MARKE, "w").write("laeuft\n")

    beissen = verfehlt = stumm = 0
    try:
        print("\n\033[1m1. Die Proben\033[0m")
        for titel, probe in PROBEN:
            betroffene = probe()
            if betroffene is None:
                print("  \033[33m⚠ PROBE VERFEHLT\033[0m %s" % titel)
                print("      (der Anker trifft nicht mehr – Proben-Mangel, "
                      "KEIN zahnloser Waechter)")
                verfehlt += 1
                zurueck(still=True)
                continue
            treffer, gebissen = [], True
            for name in betroffene:
                code, fails, _ = lauf(name)
                # Der Waechter hat gebissen, wenn er NICHT gruen endet.
                # Exit 2 zaehlt dazu und wird benannt: fuer die Positivkontrolle
                # ("die Quelle ist leer") ist genau das die richtige Antwort.
                if code == 0:
                    gebissen = False
                    treffer.append("%s: \033[31mGRUEN (stumm)\033[0m"
                                   % os.path.basename(name))
                elif code == 2:
                    treffer.append("%s: Exit 2 (konnte nicht laufen – gewollt)"
                                   % os.path.basename(name))
                else:
                    treffer.append("%s: %s FAIL" % (os.path.basename(name),
                                                    "?" if fails is None else fails))
                    if fails == 0:
                        gebissen = False
                        treffer[-1] += " \033[31m(Exit 1 ohne FAIL – nachsehen)\033[0m"
            zurueck(still=True)
            if gebissen:
                beissen += 1
                print("  \033[32m✓ beisst\033[0m   %-52s %s" % (titel, " | ".join(treffer)))
            else:
                stumm += 1
                print("  \033[31m✗ STUMM\033[0m   %-52s %s" % (titel, " | ".join(treffer)))
    finally:
        print("\n\033[1m2. Arbeitsbaum zuruecksetzen\033[0m")
        gut = zurueck()
        if os.path.exists(MARKE):
            os.remove(MARKE)
        if gut:
            shutil.rmtree(SICHERUNG, ignore_errors=True)

    print("\n\033[1m3. Basislauf NACH den Proben (der Arbeitsbaum muss wieder "
          "gruen sein)\033[0m")
    nachher_gut = True
    for name in WAECHTER:
        code, fails, _ = lauf(name)
        gleich = fails == basis[name] and code == 0
        print("  %-42s Exit %d, %s FAIL%s"
              % (name, code, fails, "" if gleich else "  \033[31m<-- ABWEICHUNG\033[0m"))
        nachher_gut = nachher_gut and gleich

    print("\n" + "=" * 70)
    print("\033[1mBilanz: %d beissen, %d stumm, %d Proben verfehlt\033[0m"
          % (beissen, stumm, verfehlt))
    if not nachher_gut:
        print("\033[31mArbeitsbaum NICHT sauber zurueckgesetzt – nachsehen!\033[0m")
    sys.exit(0 if (stumm == 0 and verfehlt == 0 and nachher_gut) else 1)


if __name__ == "__main__":
    main()
