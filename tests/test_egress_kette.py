#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Waechter: die veraltete Egress-Kette wird erkannt, gemeldet und nachgezogen.

DER VORFALL DAHINTER (2026-09-04/05): der Fix "meta skuid <uid> drop" steckt im
RENDERER, die laufenden nft-Regeln entstehen aber nur bei egress_setup - und das
laeuft ausschliesslich auf Knopfdruck. Weder git pull noch Update-Pille noch ein
Dienst-Neustart fassen sie an. Auf jedem Server mit aktiver Sperre blieb der Fix
damit wirkungslos, und jede SMB-/NFS-Freigabe scheiterte mit einer Meldung, die
in die falsche Richtung zeigt.

GEMESSEN WIRD DIE EIGENSCHAFT, nicht ein Vorkommen: kette_veraltet() laeuft
WIRKLICH gegen echte nft-Ausgaben (die beiden Formen, die es real gibt).
"""
import ast
import re
import subprocess
import sys
import tokenize
from io import StringIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OK = FAIL = 0


def check(name, bedingung):
    global OK, FAIL
    if not isinstance(bedingung, bool):
        sys.exit(f"ABBRUCH: check('{name}') bekam {type(bedingung).__name__} statt bool")
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}")


def ohne_kommentar(text: str) -> str:
    """Kommentare raus - sonst liest der Waechter seine eigene Begruendung.

    Dreizehnter Fall dieser Klasse im Projekt; die Positivkontrolle darunter
    ist Pflicht, sonst prueft man einen leeren String.
    """
    aus = []
    try:
        for tok in tokenize.generate_tokens(StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                continue
            aus.append(tok)
        return tokenize.untokenize(aus)
    except Exception:                                         # noqa: BLE001
        return text


def ohne_doc(quelle: str) -> str:
    """Docstrings raus. Kommentare entfernt ``tokenize``, Docstrings NICHT -
    sie sind Stringliterale. Genau daran sind hier vier Pruefungen falsch
    angeschlagen: die Begruendung nennt woertlich, was der Code nicht mehr tun
    soll (``skuid``, ``egress_setup``)."""
    baum = ast.parse(quelle)
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef, ast.Module)):
            k = getattr(n, "body", [])
            if k and isinstance(k[0], ast.Expr) and isinstance(k[0].value, ast.Constant) \
                    and isinstance(k[0].value.value, str):
                n.body = k[1:] or [ast.Pass()]
    return ast.unparse(baum)


# ── 1. Die Messung selbst, gegen ECHTE nft-Ausgaben ────────────────────────
print("\033[1m1. kette_veraltet(): erkennt sie die alte Regel?\033[0m")
from backend import egress_guard as eg                        # noqa: E402

# Wortlaut wie 'nft list table' ihn wirklich ausgibt.
ALT = """table inet jarvis_egress {
	chain out {
		type filter hook output priority filter; policy accept;
		meta skuid != 998 accept
		ip daddr 127.0.0.0/8 accept
		ip daddr { 10.0.0.0/8 } accept
		drop
	}
}"""
NEU = ALT.replace("\t\tdrop", "\t\tmeta skuid 998 drop")


class _R:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def messe(ausgabe, rc=0):
    """kette_veraltet() mit gestellter nft-Ausgabe WIRKLICH ausfuehren."""
    echt = eg._run
    eg._run = lambda *a, **k: _R(rc, ausgabe)
    try:
        return eg.kette_veraltet()
    finally:
        eg._run = echt


v, z = messe(ALT)
check("die ALTE Kette gilt als veraltet", v is True)
check("und die beanstandete Zeile wird genannt", "drop" in z)
v2, _ = messe(NEU)
check("die NEUE Kette gilt als aktuell", v2 is False)
v3, _ = messe("", rc=1)
check("⚠ KEINE Kette ist NICHT dasselbe wie 'in Ordnung' (None)", v3 is None)
v4, _ = messe("")
check("leere Ausgabe ebenfalls None", v4 is None)
# Gegenrichtung: ein Kommentar mit dem Wort 'drop' darf nichts ausloesen.
v5, _ = messe(NEU.replace("\tchain out {", "\t# kein nacktes drop hier\n\tchain out {"))
check("ein Kommentar mit 'drop' loest keinen Fehlalarm aus", v5 is False)

# ── 2. Der Status traegt das Ergebnis - sonst sieht es niemand ─────────────
print("\n\033[1m2. status() gibt die Messung heraus\033[0m")
# ⚠ AUSGEFUEHRT, nicht im Quelltext gesucht: eine Suche nach "kernel_drop"
# bleibt wahr, solange IRGENDEINE Zeile das Wort enthaelt - die Gegenprobe
# "Status verschweigt das Ergebnis" biss damit nicht.
import types                                                   # noqa: E402
_stub = types.ModuleType("backend.config")
_stub.config = types.SimpleNamespace(get_setting=lambda *a, **k: "",
                                     save_setting=lambda *a, **k: None)
sys.modules.setdefault("backend.config", _stub)


def status_mit(ausgabe, rc=0):
    echt = eg._run
    eg._run = lambda *a, **k: _R(rc, ausgabe)
    try:
        return eg.status()
    finally:
        eg._run = echt


st_alt = status_mit(ALT)
check("status() liefert das Feld kernel_drop", "kernel_drop" in st_alt)
check("und meldet die alte Kette als veraltet", st_alt.get("kernel_drop") is True)
check("die beanstandete Zeile ist dabei",
      "drop" in (st_alt.get("kernel_drop_zeilen") or ""))
check("bei aktueller Kette meldet er False",
      status_mit(NEU).get("kernel_drop") is False)
check("⚠ ohne Kette bleibt es None (nicht False)",
      status_mit("", rc=1).get("kernel_drop") is None)

# ── 3. EINE Fassung der Messung, nicht zwei ───────────────────────────────
print("\n\033[1m3. Drift-Schranke: die Messung liegt an EINER Stelle\033[0m")
OPS = ohne_doc(ohne_kommentar((REPO / "backend/broker/ops.py").read_text(encoding="utf-8")))
check("Positivkontrolle: Kommentare UND Docstrings sind weg",
      "def _op_egress_status" in OPS and "Hintergrund im Register" not in OPS)
check("ops.py baut die Regel NICHT selbst nach (kein eigenes skuid-Muster)",
      "skuid" not in OPS and "kette_veraltet" in OPS)

# ── 4. Gemeldet wird beim Backend-Start ───────────────────────────────────
print("\n\033[1m4. Warnung: der Startup-Hook\033[0m")
HAUPT = (REPO / "backend/main.py").read_text(encoding="utf-8")
hb = ast.parse(HAUPT)
hook = None
for n in ast.walk(hb):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "startup_egress_kette":
        hook = n
check("es gibt einen Startup-Hook fuer die Kette", hook is not None)
if hook is None:
    # ⚠ NICHT still ueberspringen: ein Lauf mit weniger Pruefungen ist von
    # "bestanden" kaum zu unterscheiden - die Gegenprobe "Hook raus" meldete
    # 26 OK / 1 FAIL statt 33 / 7.
    for _n in ("er haengt am startup-Ereignis", "er fragt den Broker",
               "er warnt nur bei aktiver Kette", "er prueft auf True",
               "er nennt den Weg", "er veraendert nichts"):
        check(_n + " (Hook fehlt)", False)
else:
    deko = " ".join(ast.unparse(d) for d in hook.decorator_list)
    check("er haengt WIRKLICH am startup-Ereignis", "on_event('startup')" in deko)
    rumpf = ohne_doc(ast.unparse(hook))
    check("er fragt den Broker (das Backend darf kein nft list)",
          "egress_status" in rumpf)
    check("⚠ er warnt nur bei einer AKTIVEN Kette (kein Alarm auf Verdacht)",
          "nft_active" in rumpf)
    check("er prueft auf True, nicht auf Falsyness (None = nicht messbar)",
          "kernel_drop') is not True" in rumpf or 'kernel_drop") is not True' in rumpf)
    check("und er nennt den WEG zur Abhilfe", "Einrichten" in rumpf)
    check("er veraendert NICHTS (kein setup aus dem Backend)",
          "egress_setup" not in rumpf)

# ── 5. Nachgezogen wird im Broker-Start ───────────────────────────────────
print("\n\033[1m5. Selbstheilung: Schritt 6f\033[0m")
SH = (REPO / "start_jarvis_root.sh").read_text(encoding="utf-8")
sh_code = "\n".join(z.split("#")[0] for z in SH.splitlines())
check("Positivkontrolle: der Kommentar-Filter hat gearbeitet",
      "6f. Internet-Sperre" not in sh_code and "jarvis_egress" in sh_code)
i6f = sh_code.find("JARVIS_EGRESS_AUTOFIX")
check("Schritt 6f ist vorhanden", i6f > 0)
i7 = sh_code.find("Starte Root-Broker")
check("er steht VOR dem Broker-Start", 0 < i6f < i7)
block = sh_code[i6f:i7]
check("er laeuft im HINTERGRUND (der Socket wartet nicht)", ") &" in block)
check("⚠ er richtet NICHT ein, er zieht nur nach (nur bei vorhandener Kette)",
      'if [ -n "$KETTE" ]' in block)
check("er misst die WIRKSAMEN Regeln, nicht die Datei",
      "nft list table inet jarvis_egress" in block)
check("⚠ massgeblich ist der Zustand danach, nicht der Rueckgabewert",
      block.count("nft list table inet jarvis_egress") >= 2)
check("er ist abschaltbar", 'JARVIS_EGRESS_AUTOFIX:-1' in block)
check("ein Fehlschlag nennt den Handweg", "Einrichten / Reparieren" in block)
res = subprocess.run(["bash", "-n", str(REPO / "start_jarvis_root.sh")],
                     capture_output=True, text=True)
check("das Skript ist syntaktisch gueltig", res.returncode == 0)

# ── 6. Und die Oberflaeche sagt es auch ───────────────────────────────────
print("\n\033[1m6. Panel: der Zustand ist sichtbar\033[0m")
JS = (REPO / "frontend/js/security_incidents.js").read_text(encoding="utf-8")
js_code = re.sub(r"^\s*//.*$", "", JS, flags=re.M)
check("Positivkontrolle: der Kommentar-Filter hat gearbeitet",
      "EINE VERALTETE KETTE" not in js_code and "kernel_drop" in js_code)
check("das Panel liest kernel_drop", "kernel_drop" in js_code)
check("⚠ es prueft auf === true (None darf nicht als veraltet gelten)",
      "d.kernel_drop === true" in js_code)
# ⚠ GEZIELT SCHNEIDEN: "var head" steht fuenfmal in der Datei; das erste
# Vorkommen gehoert einem ganz anderen Panel. Ein Test, der irgendeines
# erwischt, prueft fremden Code.
i_eg = js_code.find("sec-egress-status")
i_eg = js_code.find("var head", i_eg) if i_eg > 0 else -1
check("Positivkontrolle: der Egress-Renderer wurde gefunden", i_eg > 0)
check("die Kopfzeile aendert sich (nicht nur eine Zeile weiter unten)",
      i_eg > 0 and "veraltet" in js_code[i_eg:i_eg + 400])
check("und der Text nennt die FOLGE, nicht nur den Zustand",
      "Netzwerk-Freigaben" in js_code)

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
