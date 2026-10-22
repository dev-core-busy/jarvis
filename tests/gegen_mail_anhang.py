#!/usr/bin/env python3
"""Gegenprobe zu tests/test_mail_anhang.py: beisst der Waechter?

Jede Probe dreht EINE tragende Zeile zurueck und erwartet mindestens ein FAIL
(Exit 1 MIT Bilanzzeile – ein Absturz zaehlt nicht als Biss). Vorher ein
gruener Basislauf; ohne ihn ist keine Probe deutbar (Exit 2). Gesichert wird
jede angefasste Datei, wiederhergestellt mit md5-Vergleich; ein liegen
gebliebener Rueckstand eines abgebrochenen Laufs wird beim Start zurueckgenommen.

NIE in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.

    python3 tests/gegen_mail_anhang.py
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "tests" / "test_mail_anhang.py"
SICHERUNG = Path.home() / ".gegen_mail_anhang"
DATEIEN = ["backend/mail_anhang.py", "backend/mail_client.py", "skills/email/main.py"]

PROBEN = [
    ("Eigentuemer der Ablage nicht geprueft", "backend/mail_anhang.py",
     "        if not documents.may_access(rp.name, benutzer, is_admin=False):\n"
     "            raise MailFehler(\"Die Datei '%s' gehoert",
     "        if False:\n            raise MailFehler(\"Die Datei '%s' gehoert"),
    ("fremde Anhang-Arbeitskopie erlaubt", "backend/mail_anhang.py",
     "if lauf_tmp.gehoert_anhang(rp, benutzer) is not True:",
     "if lauf_tmp.gehoert_anhang(rp, benutzer) is False and False:"),
    ("fremdes Arbeitsverzeichnis erlaubt", "backend/mail_anhang.py",
     "if lauf_tmp.gehoert_arbeitsbereich(rp, benutzer) is not True:",
     "if False:"),
    ("ohne Menschen auch Klarnamen", "backend/mail_anhang.py",
     "        if not mensch and not documents.is_capability(rp.name):",
     "        if False:"),
    ("Namensabgleich ohne Eigentuemer", "backend/mail_anhang.py",
     "if p.is_file() and documents.may_access(p.name, benutzer, is_admin=False):",
     "if p.is_file():"),
    ("Namensabgleich auch ohne Menschen", "backend/mail_anhang.py",
     "        if mensch:\n            ersatz = _ausgeliefert(",
     "        if True:\n            ersatz = _ausgeliefert("),
    ("Wissensordner als Anhangquelle", "backend/mail_anhang.py",
     "    raise MailFehler(\n        \"'%s' kann nicht angehaengt werden: als Anhang gehen nur deine eigenen \"",
     "    return rp, rp.name\n    raise MailFehler(\n        \"'%s' kann nicht angehaengt werden: als Anhang gehen nur deine eigenen \""),
    ("SMTP haengt nichts an", "backend/mail_client.py",
     "            m.add_attachment(inhalt, maintype=haupt, subtype=unter or \"octet-stream\",\n"
     "                             filename=name)",
     "            pass"),
    ("EWS haengt nichts an", "backend/mail_client.py",
     "                m.attach(xl.FileAttachment(name=name, content=inhalt))",
     "                pass"),
    ("Werkzeug reicht die Anhaenge nicht durch", "skills/email/main.py",
     "            return (\"✅ \" + c.senden(an, betreff, text, cc=cc, entwurf=False,\n"
     "                                    anhaenge=anh)",
     "            return (\"✅ \" + c.senden(an, betreff, text, cc=cc, entwurf=False,\n"
     "                                    anhaenge=[])"),
    ("Anhaenge erst NACH dem Verbindungsaufbau geprueft", "skills/email/main.py",
     "            anh = await asyncio.to_thread(_anhaenge, kwargs)\n        except MailFehler as f:\n"
     "            return \"❌ \" + klartext(f)\n\n        def _tun(c: MailClient):\n"
     "            from backend import mail_anhang\n"
     "            return (\"✅ \" + c.senden(an, betreff, text, cc=cc,",
     "            anh = None\n        except MailFehler as f:\n"
     "            return \"❌ \" + klartext(f)\n\n        def _tun(c: MailClient):\n"
     "            from backend import mail_anhang\n"
     "            anh = _anhaenge(kwargs)\n"
     "            return (\"✅ \" + c.senden(an, betreff, text, cc=cc,"),
]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(TEST)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def zurueck() -> None:
    if not SICHERUNG.is_dir():
        return
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            (ROOT / rel).write_bytes(s.read_bytes())
    for f in SICHERUNG.iterdir():
        f.unlink()
    SICHERUNG.rmdir()


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: eine Probe fasst eine Datei an, die nicht gesichert wird")
        return 2
    zurueck()  # Rueckstand eines abgeschossenen Laufs
    rc, out = lauf()
    if rc != 0 or not bilanz(out) or bilanz(out)[1]:
        print("ABBRUCH: Basislauf nicht gruen\n" + out[-2000:])
        return 2
    print(f"Basislauf gruen: {bilanz(out)[0]} OK")
    SICHERUNG.mkdir(mode=0o700)
    vorher = {}
    for rel in DATEIEN:
        (SICHERUNG / rel.replace("/", "__")).write_bytes((ROOT / rel).read_bytes())
        vorher[rel] = md5(ROOT / rel)
    stumm = 0
    try:
        for titel, rel, alt, neu in PROBEN:
            p = ROOT / rel
            orig = p.read_text()
            if orig.count(alt) != 1:
                print(f"  ANKER  {titel}: Anker {orig.count(alt)}x gefunden")
                stumm += 1
                continue
            p.write_text(orig.replace(alt, neu))
            try:
                rc, out = lauf()
            finally:
                p.write_text(orig)
            b = bilanz(out)
            if rc == 1 and b and b[1] > 0:
                print(f"  BEISST {titel}: {b[1]} FAIL")
            else:
                stumm += 1
                print(f"  STUMM  {titel}: rc={rc} bilanz={b}")
    finally:
        zurueck()
    for rel, h in vorher.items():
        if md5(ROOT / rel) != h:
            print(f"ABBRUCH: {rel} nicht byte-gleich wiederhergestellt")
            return 2
    print(f"\n{len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
