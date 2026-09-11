#!/usr/bin/env python3
"""NUR LESEN: kam der Chat-Preprompt in den LAEUFEN an?

⚠ VERAENDERT NICHTS. Der LLM-Verlauf speichert den vollstaendigen
System-Prompt jedes Laufs (seit 2026-08-04 ungekuerzt). Damit laesst sich die
Frage direkt beantworten, ohne einen Lauf auszuloesen:

  Steht in den Laeufen SEIT dem Setzen die Marke "PERSÖNLICHE ANWEISUNG"?
    ja   -> der Prompt kam an; dann haelt sich das MODELL nicht daran.
    nein -> er kam nicht an; dann klemmt die Uebergabe (session_id/Benutzer).

⚠ ES WERDEN KEINE INHALTE AUSGEGEBEN – keine Aufgaben, keine Antworten, keine
Prompt-Texte. Nur: Zeitpunkt, Kanal, Laenge und ob die Marke vorkommt.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

BENUTZER = "andreas.bender"
SID = "c51a5589c408"
MARKE = "PERSÖNLICHE ANWEISUNG"
CONV = Path("/opt/jarvis/data/logs/conv")
CHATS = Path("/opt/jarvis/data/chats") / BENUTZER / SID

print("=" * 70)
print("  LESEND: kam der Chat-Preprompt in den Laeufen an?")
print("=" * 70)

# ── Wann wurde er gesetzt, und wurde die Sitzung danach benutzt? ───────────
meta = CHATS / "meta.json"
gesetzt = meta.stat().st_mtime if meta.exists() else 0
print("\nSitzung %s (%s)" % (SID, BENUTZER))
print("  Prompt gesetzt:      %s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                                  time.localtime(gesetzt)))
for name in ("transcript.json", "context.json"):
    p = CHATS / name
    if p.exists():
        st = p.stat()
        n = "?"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            n = len(d) if isinstance(d, list) else len(d.get("history", []) or [])
        except Exception:                                        # noqa: BLE001
            pass
        print("  %-18s %s, %s Eintraege, %.1f KB"
              % (name + ":", time.strftime("%H:%M:%S", time.localtime(st.st_mtime)),
                 n, st.st_size / 1024.0))
        if st.st_mtime > gesetzt:
            print("      -> NACH dem Setzen benutzt (%.1f min spaeter)"
                  % ((st.st_mtime - gesetzt) / 60.0))
        else:
            print("      -> seit dem Setzen NICHT mehr benutzt")
    else:
        print("  %-18s fehlt" % (name + ":"))

# ── Die Laeufe dieses Benutzers seit dem Setzen ────────────────────────────
idx = CONV / "index.jsonl"
if not idx.exists():
    print("\nKein LLM-Verlauf unter %s" % CONV)
    sys.exit(2)

from backend.benutzer import norm_user                           # noqa: E402

treffer = []
for zeile in idx.read_text(encoding="utf-8", errors="replace").splitlines():
    try:
        e = json.loads(zeile)
    except Exception:                                            # noqa: BLE001
        continue
    # ⚠ Das Feld heisst `username`, NICHT `user` (am echten Index gemessen –
    # geraten war es falsch und lieferte "0 Laeufe gesamt").
    if norm_user(e.get("username") or "") != norm_user(BENUTZER):
        continue
    ts = e.get("ts") or 0
    if isinstance(ts, str):
        try:
            ts = float(ts)
        except ValueError:
            ts = 0
    treffer.append((ts, e))

treffer.sort(key=lambda x: x[0])
seit = [t for t in treffer if t[0] >= gesetzt - 60]
print("\nLaeufe von %s: %d gesamt, %d seit dem Setzen"
      % (BENUTZER, len(treffer), len(seit)))

if not seit:
    print("""
⇒ SEIT DEM SETZEN GAB ES KEINEN LAUF DIESES BENUTZERS. Dann kann der Prompt
  nirgends gegriffen haben – die Frage wurde in einer ANDEREN Sitzung oder vor
  dem Setzen gestellt.""")

if treffer:
    print("  letzter Lauf ueberhaupt: %s"
          % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(treffer[-1][0])))
print("\n%-20s %-22s %-7s %-9s %s"
      % ("Zeit", "Kanal", "Prompt", "Marke?", "Kennung"))
print("-" * 70)
for ts, e in seit[-25:]:
    cid = e.get("id") or e.get("conv_id") or ""
    rumpf = CONV / ("%s.json" % cid)
    sp = ""
    if rumpf.exists():
        try:
            d = json.loads(rumpf.read_text(encoding="utf-8"))
            sp = d.get("system_prompt") or ""
        except Exception:                                        # noqa: BLE001
            sp = ""
    print("%-20s %-22s %-7d %-9s %s"
          % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
             str(e.get("client_type") or "")[:22], len(sp),
             "JA" if MARKE in sp else "nein", cid))

mit = sum(1 for ts, e in seit
          if MARKE in ((json.loads((CONV / ("%s.json" % (e.get("id") or ""))).read_text(
              encoding="utf-8")).get("system_prompt") or "")
              if (CONV / ("%s.json" % (e.get("id") or ""))).exists() else ""))
print("-" * 70)
print("Von %d Laeufen seit dem Setzen tragen %d die Marke." % (len(seit), mit))
if seit and not mit:
    print("""
⇒ DER PROMPT KAM IN KEINEM LAUF AN. Das Speichern geht, das Anwenden nicht –
  die Uebergabe (session_id bzw. Benutzer im WS-Lauf) ist die Stelle.""")
elif mit:
    print("""
⇒ ER KAM AN. Dann ist die Kette intakt und es ist eine Frage der Formulierung
  bzw. des Modells – kein Uebergabefehler.""")
print("=" * 70)
