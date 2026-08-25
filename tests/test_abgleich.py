#!/usr/bin/env python3
"""Waechter fuer deploy/abgleich.py – die Auswertung, ohne Netz und ohne Server.

Geprueft wird die Logik, an der das Werkzeug seinen Wert hat: dass es Drift
ueber den INHALT findet (nicht ueber die mtime), dass sparse-checkout kein
Fehlbefund wird, dass Server-Hoheit unangetastet bleibt und dass gitignorete
Laufzeitdateien nicht als „verirrt" gemeldet werden.

Der gemeldete Vorfall (DEV 2026-08-25, settings.html ohne icons.js) steht als
eigener Fall drin.

Aufruf: python3 tests/test_abgleich.py     Exit 0 = alles gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import os
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
sys.path.insert(0, os.path.join(WURZEL, "deploy"))

try:
    import abgleich
except Exception as e:                                   # pragma: no cover
    # Exit 2, nicht 1: „konnte nicht laufen" darf nie wie „bestanden" aussehen.
    sys.stderr.write("ABBRUCH: deploy/abgleich.py nicht importierbar: %s\n" % e)
    sys.exit(2)

_ok = _fail = 0


def pruefe(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % text)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s" % text)


# ── 1 · sparse-checkout ────────────────────────────────────────────────────
print("\n1 · sparse-checkout wird als Absicht erkannt, nicht als Fehlbefund")

DATEI = "/*\n!/tests/\n!/android/\n!/windows-app-go/\n"
p = abgleich.sparse_praefixe(DATEI)
pruefe(set(p) == {"tests/", "android/", "windows-app-go/"},
       "die drei Negationen werden gelesen (%r)" % sorted(p))
pruefe(abgleich.sparse_praefixe("") == [] and abgleich.sparse_praefixe(None) == [],
       "ohne sparse-checkout-Datei ist die Liste leer")
pruefe("/*" not in p, "das einschliessende /* wird NICHT als Ausblendung gelesen")
pruefe(abgleich.ist_ausgeblendet("tests/test_x.py", p), "tests/test_x.py gilt als ausgeblendet")
pruefe(not abgleich.ist_ausgeblendet("backend/main.py", p), "backend/main.py gilt NICHT als ausgeblendet")
pruefe(not abgleich.ist_ausgeblendet("testsuite/x.py", p),
       "testsuite/x.py wird nicht mitgerissen (Praefix endet an der Ordnergrenze)")

# ── 2 · der gemeldete Vorfall ──────────────────────────────────────────────
print("\n2 · Vorfall DEV 2026-08-25: settings.html weicht ab, JS ist gleich")

repo = {
    "frontend/settings.html": "aaa",
    "frontend/js/skills.js":  "bbb",
    "frontend/js/icons.js":   "ccc",
}
server = {
    "frontend/settings.html": "ZZZ",   # alter Stand, spaeter geschrieben
    "frontend/js/skills.js":  "bbb",
    "frontend/js/icons.js":   "ccc",
}
b = abgleich.vergleiche(repo, server)
pruefe(b["verschieden"] == ["frontend/settings.html"],
       "genau die eine abweichende Datei wird gemeldet")
pruefe(b["fehlt"] == [], "nichts faelschlich als fehlend gemeldet")

# ── 3 · fehlend vs. ausgeblendet ───────────────────────────────────────────
print("\n3 · fehlend und ausgeblendet werden auseinandergehalten")

repo3 = {"backend/main.py": "a", "tests/test_x.py": "b", "frontend/neu.js": "c"}
server3 = {"backend/main.py": "a", "tests/test_x.py": None, "frontend/neu.js": None}
b3 = abgleich.vergleiche(repo3, server3, sparse=["tests/"])
pruefe(b3["fehlt"] == ["frontend/neu.js"], "nur die echte Luecke steht unter -fehlt-")
pruefe(b3["ausgeblendet"] == ["tests/test_x.py"], "die sparse-Datei steht unter -ausgeblendet-")
b3o = abgleich.vergleiche(repo3, server3, sparse=[])
pruefe(sorted(b3o["fehlt"]) == ["frontend/neu.js", "tests/test_x.py"],
       "OHNE sparse-Info waeren es zwei – die Unterscheidung haengt wirklich daran")

# ── 4 · Server-Hoheit ──────────────────────────────────────────────────────
print("\n4 · pro Server gepflegte Dateien werden NICHT verglichen")

repo4 = {"data/instructions/x.md": "a", "settings.json": "a", "backend/main.py": "a"}
server4 = {"data/instructions/x.md": "ANDERS", "settings.json": "ANDERS", "backend/main.py": "a"}
b4 = abgleich.vergleiche(repo4, server4)
pruefe(b4["verschieden"] == [],
       "abweichende Instruktionen/settings.json sind KEIN Drift (der Server ist dort die Wahrheit)")
pruefe(sorted(b4["server_hoheit"]) == ["data/instructions/x.md", "settings.json"],
       "sie werden aber ausgewiesen, nicht verschwiegen")
b4o = abgleich.vergleiche(repo4, server4, hoheit=())
pruefe(len(b4o["verschieden"]) == 2, "ohne die Ausnahmeliste waeren es zwei Fehlbefunde")

# ── 5 · verirrte Dateien ───────────────────────────────────────────────────
print("\n5 · verirrt nur, was nicht schon .gitignore deckt")

kandidaten = ["frontend/i18n.js", "data/memory.json", "venv/x.py"]
ignoriert = {"data/memory.json", "venv/x.py"}
v = abgleich.verirrt_filtern(kandidaten, ignoriert)
pruefe(v == ["frontend/i18n.js"], "die echte Fehlkopie bleibt uebrig (%r)" % v)
pruefe(abgleich.verirrt_filtern([], set()) == [], "leere Eingabe ergibt leere Ausgabe")

# ── 6 · der Agent laeuft wirklich ──────────────────────────────────────────
print("\n6 · abgleich_agent.py wird ausgefuehrt, nicht nur gelesen")

import tempfile
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, "unter"))
    with open(os.path.join(tmp, "a.txt"), "w") as f:
        f.write("hallo")
    with open(os.path.join(tmp, "unter", "fremd.txt"), "w") as f:
        f.write("nicht im repo")
    liste = os.path.join(tmp, "liste.bin")
    with open(liste, "wb") as f:
        f.write(b"a.txt\0fehlt.txt")

    agent = os.path.join(WURZEL, "deploy", "abgleich_agent.py")
    r = subprocess.run([sys.executable, agent, "hashes", tmp, liste],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    aus = r.stdout.decode()
    # md5("hallo") = 598d4c200461b81522a3328565c25f7c
    pruefe("598d4c200461b81522a3328565c25f7c\ta.txt" in aus,
           "md5 der vorhandenen Datei stimmt")
    pruefe("-\tfehlt.txt" in aus, "fehlende Datei wird als - gemeldet, nicht verschwiegen")

    r2 = subprocess.run([sys.executable, agent, "fremde", tmp, liste],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    aus2 = r2.stdout.decode()
    pruefe("unter/fremd.txt" in aus2, "unbekannte Datei wird als Kandidat gefunden")
    pruefe("a.txt" not in aus2.replace("unter/fremd.txt", ""),
           "die bekannte Datei taucht dort NICHT auf")

    r3 = subprocess.run([sys.executable, agent, "hashes", tmp + "/gibtsnicht", liste],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pruefe(r3.returncode == 2, "fehlendes Zielverzeichnis endet mit Exit 2, nicht 0")

    # Laufzeitablage darf NICHT durchsucht werden – auch dann nicht, wenn sie
    # als STARTPUNKT uebergeben wird. "data" steht in der Praefixliste, weil
    # data/instructions_default/ git-verfolgt ist; ohne die Pruefung am
    # Startpunkt lief der Suchlauf mitten in data/ los und meldete auf DEV
    # gemessene 197 Laufzeitdateien als "verirrt".
    os.makedirs(os.path.join(tmp, "data", "knowledge", "learned"))
    with open(os.path.join(tmp, "data", "memory.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(tmp, "data", "knowledge", "learned", "conv_1.md"), "w") as f:
        f.write("x")
    r4 = subprocess.run([sys.executable, agent, "fremde", tmp, liste, "data", "unter"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    aus4 = r4.stdout.decode()
    pruefe("data/memory.json" not in aus4 and "conv_1.md" not in aus4,
           "data/ wird als Startpunkt uebersprungen (keine Laufzeitdatei gemeldet)")
    pruefe("unter/fremd.txt" in aus4,
           "ein NICHT uebergangener Startpunkt liefert weiterhin seinen Fund "
           "(sonst waere der Filter zu breit)")

# ── 7 · das Werkzeug aendert von sich aus nichts ───────────────────────────
print("\n7 · ohne --nachziehen wird nichts geschrieben (funktional, nicht per Quelltext)")

# Die Ablage liegt im HOME des ANMELDENDEN Benutzers, nicht in /tmp (1777) –
# und NICHT fest unter /root: bis 2026-08-25 stand dort "/root/.jarvis-abgleich",
# und auf ECHT (Anmeldung als `nxadmin`) scheiterte damit JEDER Lauf mit
# "mkdir: cannot create directory '/root'". Ausgerechnet der Server, auf dem
# Drift am teuersten ist, war nicht pruefbar.
pruefe(not abgleich.ABLAGE_NAME.startswith("/"),
       "der Ablagename ist RELATIV, das HOME kommt vom Server: %s" % abgleich.ABLAGE_NAME)
pruefe("/tmp" not in abgleich.ABLAGE_NAME,
       "die Ablage liegt nicht in /tmp (dort 1777, jeder koennte unterschieben)")
_quelle_ab = open(os.path.join(WURZEL, "deploy", "abgleich.py"), encoding="utf-8").read()
_code_ab = "\n".join(z for z in _quelle_ab.splitlines() if not z.lstrip().startswith("#"))
pruefe('"/root' not in _code_ab,
       "kein fest verdrahtetes /root mehr im Code (bricht bei nicht-root-Anmeldung)")
pruefe('"$HOME"' in _code_ab,
       "das HOME wird auf dem Server erfragt statt geraten")

# Der Server wird durch eine Attrappe ersetzt, die absichtlich Drift meldet.
# So laeuft main() wirklich durch – ein Quelltext-Grep haette hier nur die
# eigene Begruendung im Kommentar gelesen.
gerufen = []
echt_lesen, echt_ziehen = abgleich.server_lesen, abgleich.nachziehen


def _attrappe_lesen(server, key, ziel, dateien, praefixe):
    # jede Datei weicht ab -> maximaler Drift, der Nachziehen ausloesen WUERDE
    return ({d: "abweichend" for d in dateien}, [], "", [])


def _attrappe_ziehen(*a, **k):
    gerufen.append(a)
    return "/root/attrappe", 1      # (Sicherungspfad, Anzahl gesicherter Dateien)


abgleich.server_lesen = _attrappe_lesen
abgleich.nachziehen = _attrappe_ziehen
alt_argv, alt_out = sys.argv, sys.stdout
try:
    import io
    sys.argv = ["abgleich.py", "--nur", "deploy/"]
    sys.stdout = io.StringIO()
    rc_ohne = abgleich.main()
    nach_erstem = len(gerufen)      # VOR dem zweiten Lauf festhalten
    sys.stdout = io.StringIO()
    sys.argv = ["abgleich.py", "--nur", "deploy/", "--nachziehen"]
    rc_mit = abgleich.main()
finally:
    sys.argv, sys.stdout = alt_argv, alt_out
    abgleich.server_lesen, abgleich.nachziehen = echt_lesen, echt_ziehen

pruefe(rc_ohne == 1, "Drift ohne --nachziehen endet mit Exit 1 (nicht 0, nicht 2)")
pruefe(nach_erstem == 0, "ohne --nachziehen wurde KEINE schreibende Funktion gerufen")
pruefe(rc_mit == 1 and len(gerufen) == nach_erstem + 1,
       "mit --nachziehen wird sie genau einmal gerufen (Gegenprobe: der Test misst wirklich etwas)")

print("\n\033[1mErgebnis: %d/%d\033[0m" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
