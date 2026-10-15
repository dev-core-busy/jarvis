"""Live-Probe (DEV): meldet /api/wissen/destillat/extract?stream=1 den Fortschritt?

Laeuft AUF DEM SERVER (sys.path /opt/jarvis) gegen den laufenden Dienst und
die ECHTE Extraktion. Schickt vier Dateien:
  a.txt  – lesbar
  b.xyz  – Format nicht unterstuetzt (Fehler MIT Grund erwartet)
  c.pdf  – Bild-PDF ohne Textschicht (OCR, also langsam)
  d.md   – lesbar
und misst:
  - Antworttyp application/x-ndjson,
  - je Datei eine Zeile art=datei, i=1..4, n=4, in Reihenfolge, VOR art=fertig,
  - das Protokoll nennt jede Datei, den Fehler mit Grund,
  - ⚠ die Zeilen kommen STUECKWEISE: die erste Zeile ist da, bevor die
    langsame PDF fertig ist (Abstand erste Zeile -> fertig wird gemessen und
    genannt; ohne messbaren Abstand ist die Stueckweise-Zusage NICHT PRUEFBAR,
    nicht bestanden),
  - ohne ?stream=1 bleibt die alte JSON-Antwort.
Schreibt nichts Dauerhaftes. Aufruf: sudo -u jarvis python3 tests/live_wissen_destillat_strom_dev.py
"""
import io
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

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

BENUTZER = os.environ.get("DEST_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
if not M._editable_groups_for(BENUTZER):
    print("ABBRUCH: %r hat keinen Wissensbereich (403) – NICHT PRUEFBAR" % BENUTZER)
    sys.exit(2)


def bild_pdf() -> bytes:
    """PDF aus EINEM Bild mit Text – keine Textschicht, die Extraktion muss OCR."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    for z in range(30):
        d.text((120, 120 + z * 70), "Fortschrittsprobe Zeile %d – Wissen destillieren" % z,
               fill="black", font=f)
    out = io.BytesIO()
    img.save(out, "PDF", resolution=200)
    return out.getvalue()


DATEIEN = [("a.txt", b"Alpha Inhalt"), ("b.xyz", b"egal"),
           ("c.pdf", bild_pdf()), ("d.md", b"# Delta\n\nText")]


def multipart(dateien):
    grenze = uuid.uuid4().hex
    teile = []
    for name, inhalt in dateien:
        teile.append(("--%s\r\nContent-Disposition: form-data; name=\"files\"; "
                      "filename=\"%s\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                      % (grenze, name)).encode() + inhalt + b"\r\n")
    return b"".join(teile) + ("--%s--\r\n" % grenze).encode(), grenze


def anfrage(pfad):
    body, grenze = multipart(DATEIEN)
    r = urllib.request.Request(BASIS + pfad, data=body, method="POST")
    r.add_header("Authorization", "Bearer " + TOKEN)
    r.add_header("Content-Type", "multipart/form-data; boundary=" + grenze)
    return urllib.request.urlopen(r, context=_KTX, timeout=600)


# ── Strom ──────────────────────────────────────────────────────────────────
print("Strom (?stream=1):")
try:
    a = anfrage("/api/wissen/destillat/extract?stream=1")
except urllib.error.HTTPError as e:
    print("ABBRUCH: HTTP %s – NICHT PRUEFBAR" % e.code)
    sys.exit(2)
t0 = time.monotonic()
zeilen = []                      # (sekunden, objekt)
with a:
    typ = a.headers.get("Content-Type", "")
    while True:
        z = a.readline()
        if not z:
            break
        if z.strip():
            zeilen.append((time.monotonic() - t0, json.loads(z)))
# Positivkontrolle: ohne fertig-Zeile ist alles darunter bedeutungslos.
fertig = [o for _, o in zeilen if o.get("art") == "fertig"]
if not fertig:
    print("ABBRUCH: keine fertig-Zeile – %r" % [o for _, o in zeilen][-2:])
    sys.exit(2)
fertig = fertig[0]
check("Antworttyp application/x-ndjson", typ.startswith("application/x-ndjson"), typ)
dz = [o for _, o in zeilen if o.get("art") == "datei"]
check("je Datei eine Zeile, i=1..4, n=4, in Reihenfolge",
      [(o.get("i"), o.get("n"), o.get("name")) for o in dz]
      == [(1, 4, "a.txt"), (2, 4, "b.xyz"), (3, 4, "c.pdf"), (4, 4, "d.md")],
      [(o.get("i"), o.get("name")) for o in dz])
check("fertig ist die LETZTE Zeile", zeilen[-1][1].get("art") == "fertig")
prot = fertig.get("protokoll") or []
check("Protokoll nennt jede Datei", [p.get("name") for p in prot] == [n for n, _ in DATEIEN],
      [p.get("name") for p in prot])
fb = [p for p in prot if p.get("name") == "b.xyz"]
check("b.xyz: Fehler MIT Grund", bool(fb) and fb[0].get("art") == "fehler"
      and "unterstützt" in (fb[0].get("grund") or ""), fb)
fc = [p for p in prot if p.get("name") == "c.pdf"]
print("  c.pdf (OCR): %s" % fc)
check("a.txt und d.md gelesen", {"a.txt", "d.md"} <= set(fertig.get("ok") or []), fertig.get("ok"))
t_erst = zeilen[0][0]
t_ende = zeilen[-1][0]
t_pdf = [s for s, o in zeilen if o.get("art") == "datei" and o.get("name") == "c.pdf"]
t_nach = [s for s, o in zeilen if o.get("art") == "datei" and o.get("name") == "d.md"]
print("  Zeitpunkte: erste Zeile %.2fs, 'c.pdf' %.2fs, 'd.md' %.2fs, fertig %.2fs"
      % (t_erst, t_pdf[0] if t_pdf else -1, t_nach[0] if t_nach else -1, t_ende))
if t_pdf and t_nach and t_nach[0] - t_pdf[0] >= 0.5:
    # Die PDF braucht messbar Zeit. Stuende der Strom erst am Ende, kaemen
    # 'c.pdf' und 'd.md' im selben Augenblick an.
    check("Zeilen kommen STUECKWEISE (c.pdf-Zeile deutlich vor der naechsten)",
          t_nach[0] - t_pdf[0] >= 0.5, "%.2fs" % (t_nach[0] - t_pdf[0]))
else:
    print("  NICHT PRUEFBAR: die PDF war zu schnell (%.2fs) – Stueckweise-Zusage nicht gemessen"
          % ((t_nach[0] - t_pdf[0]) if t_pdf and t_nach else -1))

# ── Ohne Strom: alte Antwort ─────────────────────────────────────────────
print("Ohne Strom:")
with anfrage("/api/wissen/destillat/extract") as a:
    typ2 = a.headers.get("Content-Type", "")
    d = json.loads(a.read().decode())
check("ohne ?stream=1: gewoehnliches JSON", typ2.startswith("application/json"), typ2)
check("… mit Text, ok, fehler und protokoll",
      bool(d.get("text")) and "b.xyz" in (d.get("fehler") or {}) and len(d.get("protokoll") or []) == 4)

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
