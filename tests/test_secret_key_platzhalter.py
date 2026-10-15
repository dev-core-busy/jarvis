#!/usr/bin/env python3
"""Waechter: kein oeffentlich bekannter SECRET_KEY signiert je ein Token (2026-09-28).

DIE ZUSAGE: eine Installation laeuft NIE mit einem SECRET_KEY, der im Repo
steht – egal ob die Vorlage unveraendert kopiert wurde, ob eine alte ``.env``
den Beispielwert noch traegt oder ob jemand die README abgeschrieben hat.

Anlass: ``.env.example`` trug ``SECRET_KEY=change-me-…``, ``docs/install.sh``
kopierte die Vorlage nach ``.env`` und niemand musste den Wert tauschen. Mit dem
Schluessel aus GitHub liess sich fuer jeden Benutzernamen ein gueltiges
Sitzungstoken bauen (``main.generate_token`` ist ein nacktes HMAC darueber).

Gemessen wird:
1. ``secret_key.aufloesen`` – AUSGEFUEHRT im Sandkasten: Platzhalter werden
   verworfen, echte Werte bleiben, die Datei entsteht mit 0600.
2. JEDER SECRET_KEY-Wert, der je in ``.env.example`` stand (Git-Historie) oder
   heute in Vorlage/README steht, wird verworfen – als Regel, nicht als Liste.
3. ``config.SECRET_KEY`` kommt aus ``aufloesen`` (AST, kein Textvorkommen).
4. Der Block in ``docs/install.sh`` – AUSGEFUEHRT mit bash gegen eine ``.env``
   mit dem alten Beispielwert: danach ist die Zeile leer.
"""
import ast
import hashlib
import hmac
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

_ok = 0
_fail = 0


def check(beschreibung, bedingung, zusatz=""):
    """check(TEXT, BEDINGUNG) – vertauscht waere jede Zeichenkette wahr. Exit 2."""
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(beschreibung, bedingung) vertauscht")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  [{zusatz}]" if zusatz else ""))


def sicher(fn, *a, **kw):
    """Ausnahme als MESSWERT statt Abbruch."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", f"{type(e).__name__}: {e}")


try:
    from backend import secret_key as sk
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.secret_key nicht importierbar: {e}")
    sys.exit(2)

ALT = "change-me-to-a-secure-random-string-min-32-chars"
ECHT = "3f9c1e7a5b2d4c6e8f0a1b3c5d7e9f11" * 2   # 64 Hex-Zeichen, kein Platzhalter

sandkasten = Path(tempfile.mkdtemp(prefix="secretkey_"))


def datei(name):
    p = sandkasten / name / "data" / ".secret_key"
    if not str(p).startswith(tempfile.gettempdir()):
        print(f"ABBRUCH: Sandkasten-Pfad zeigt heraus: {p}")
        sys.exit(2)
    return p


def werte_je_in_vorlage():
    """Alle SECRET_KEY-Werte, die je in .env.example standen (Git) + heute Vorlage/README."""
    werte = set()
    r = subprocess.run(["git", "-C", str(WURZEL), "log", "--all", "-p", "--", ".env.example"],
                       capture_output=True, text=True)
    git_ok = r.returncode == 0 and "SECRET_KEY" in r.stdout
    for m in re.finditer(r"^\+SECRET_KEY=(.*)$", r.stdout, re.M):
        werte.add(m.group(1).split("#")[0].strip())
    for rel in (".env.example", "README.md"):
        txt = (WURZEL / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"^SECRET_KEY=(.*)$", txt, re.M):
            werte.add(m.group(1).split("#")[0].strip())
    return werte, git_ok


# ─── 1. aufloesen, ausgefuehrt ──────────────────────────────────────────────
print("1. aufloesen() im Sandkasten")
d = datei("a")
k = sicher(sk.aufloesen, ALT, d)
# Positivkontrolle: die Funktion lief ueberhaupt und lieferte eine Zeichenkette
if not isinstance(k, str):
    print(f"ABBRUCH: aufloesen lief nicht: {k}")
    sys.exit(2)
check("Beispielwert aus der alten Vorlage wird NICHT verwendet", k != ALT)
check("stattdessen ein Zufallsschluessel (64 Hex)", bool(re.fullmatch(r"[0-9a-f]{64}", k)), k[:8])
check("und in data/.secret_key abgelegt", d.exists() and d.read_text().strip() == k)
check("Datei nur fuer den Eigentuemer lesbar (0600)",
      d.exists() and stat.S_IMODE(d.stat().st_mode) == 0o600)
check("zweiter Start mit Beispielwert liefert DENSELBEN Schluessel (Sitzungen bleiben)",
      sicher(sk.aufloesen, ALT, d) == k)
k2 = sicher(sk.aufloesen, ALT, datei("b"))
check("zwei Installationen bekommen VERSCHIEDENE Schluessel", isinstance(k2, str) and k2 != k)
check("ein echter Wert aus .env wird unveraendert benutzt", sicher(sk.aufloesen, ECHT, datei("c")) == ECHT)
check("... und dabei entsteht keine Datei", not datei("c").exists())
check("leerer Wert -> Datei-Schluessel", sicher(sk.aufloesen, "", d) == k)
d_p = datei("d")
d_p.parent.mkdir(parents=True, exist_ok=True)
d_p.write_text(ALT)
kd = sicher(sk.aufloesen, "", d_p)
check("Platzhalter IN data/.secret_key wird ebenfalls ersetzt", isinstance(kd, str) and kd != ALT)
for variante in (f"  {ALT}  ", "Change-Me-bitte", "change-me"):
    kv = sicher(sk.aufloesen, variante, datei("v" + str(abs(hash(variante)))))
    check(f"Variante {variante.strip()[:20]!r} wird verworfen",
          isinstance(kv, str) and kv.strip() != variante.strip())

# Wirkung: ein mit dem oeffentlichen Wert gebautes Token passt nicht zum aufgeloesten Schluessel
msg = b"admin:1790000000"
gefaelscht = hmac.new(ALT.encode(), msg, hashlib.sha256).hexdigest()
echt_sig = hmac.new(k.encode(), msg, hashlib.sha256).hexdigest()
check("mit dem GitHub-Wert gebaute Signatur ist UNGUELTIG", not hmac.compare_digest(gefaelscht, echt_sig))

# ─── 2. jeder Wert, der je im Repo stand ────────────────────────────────────
print("2. Werte aus Vorlage, README und Git-Historie")
werte, git_ok = werte_je_in_vorlage()
if git_ok:
    check("Positivkontrolle: Git-Historie liefert den alten Beispielwert", ALT in werte, str(werte))
else:
    print("  (Git-Historie nicht lesbar – nur heutige Dateien geprueft)")
check("Positivkontrolle: mindestens zwei Fundstellen", len(werte) >= 2, str(werte))
for i, w in enumerate(sorted(werte)):
    r = sicher(sk.aufloesen, w, datei(f"h{i}"))
    check(f"Repo-Wert {w[:24]!r} wird verworfen", isinstance(r, str) and r != w and r.strip() != w)

# ─── 3. config benutzt aufloesen ────────────────────────────────────────────
print("3. config.SECRET_KEY kommt aus aufloesen()")
baum = ast.parse((WURZEL / "backend" / "config.py").read_text(encoding="utf-8"))
alias = {n.asname or n.name for x in ast.walk(baum) if isinstance(x, ast.ImportFrom)
         and x.module == "backend.secret_key" for n in x.names if n.name == "aufloesen"}
zuweisungen = [x for x in ast.walk(baum)
               if isinstance(x, (ast.Assign, ast.AnnAssign))
               and any(isinstance(t, ast.Name) and t.id == "SECRET_KEY"
                       for t in (x.targets if isinstance(x, ast.Assign) else [x.target]))]
check("genau EINE Zuweisung an SECRET_KEY", len(zuweisungen) == 1, str(len(zuweisungen)))
check("aufloesen wird aus backend.secret_key importiert", bool(alias))
check("die Zuweisung IST ein Aufruf von aufloesen",
      len(zuweisungen) == 1 and isinstance(zuweisungen[0].value, ast.Call)
      and isinstance(zuweisungen[0].value.func, ast.Name) and zuweisungen[0].value.func.id in alias)

# ─── 4. install.sh, ausgefuehrt ─────────────────────────────────────────────
print("4. docs/install.sh repariert eine .env mit Beispielwert")
sh = (WURZEL / "docs" / "install.sh").read_text(encoding="utf-8")
m = re.search(r"\n(if grep -qiE '\^SECRET_KEY=.*?\nfi\n)", sh, re.S)
check("Positivkontrolle: Reparatur-Block gefunden", m is not None)
if m:
    for name, inhalt, erwartet in (
        ("alter Beispielwert", f"JARVIS_PASSWORD=x\nSECRET_KEY={ALT}\nVNC_PORT=5900\n", "SECRET_KEY="),
        ("echter Wert bleibt", f"SECRET_KEY={ECHT}\n", f"SECRET_KEY={ECHT}"),
    ):
        inst = sandkasten / ("inst_" + str(abs(hash(name))))
        inst.mkdir()
        (inst / ".env").write_text(inhalt)
        skript = f'warn(){{ echo "WARN $*"; }}\nINSTALL_DIR="{inst}"\n' + m.group(1)
        r = subprocess.run(["bash", "-c", skript], capture_output=True, text=True, timeout=20)
        zeilen = (inst / ".env").read_text().splitlines()
        sk_zeilen = [z for z in zeilen if z.startswith("SECRET_KEY=")]
        check(f"{name}: bash lief (rc 0)", r.returncode == 0, r.stderr.strip()[:120])
        check(f"{name}: SECRET_KEY-Zeile ist danach {erwartet!r}", sk_zeilen == [erwartet], str(sk_zeilen))
        check(f"{name}: uebrige Zeilen unveraendert",
              [z for z in zeilen if not z.startswith("SECRET_KEY=")]
              == [z for z in inhalt.splitlines() if not z.startswith("SECRET_KEY=")])

shutil.rmtree(sandkasten, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
