#!/usr/bin/env python3
"""Live auf DEV: Version im health-Endpunkt und Paketinhalt.

⚠ STELLT DEN VORGEFUNDENEN ZUSTAND WIEDER HER und raet ihn nicht: Skill-Schalter
und Freigabeliste werden vorher GELESEN und am Ende auf genau diesen Wert
zurueckgesetzt (Register 2026-09-09 – eine Messung, die einen Schalter hart
abschaltet, nimmt ihn dem Betreiber weg).
"""
import io
import json
import ssl
import sys
import urllib.error
import urllib.request
import zipfile

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


from backend import ai_mouse as am                                # noqa: E402
from backend.config import config as cfg                          # noqa: E402
from backend import main as M                                     # noqa: E402

# ⚠ DER BENUTZER MUSS FUER AI-MAUS FREIGEGEBEN SEIN, sonst antworten `health`
# und `/paket` mit 403 und die zwei wichtigsten Pruefungen werden
# UEBERSPRUNGEN – also trivial wahr (erster Lauf dieser Probe: 8 OK, davon 2
# ohne jede Aussage). Gewaehlt wird ein freigegebener aus der ECHTEN
# Konfiguration; die Freigabe wird NICHT umgestellt (Register 2026-09-09).
BENUTZER = next(
    (u for u in (__import__("os").environ.get("AIMOUSE_TESTUSER") or "",
                 "andreas.bender", "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)


def hole(pfad, token=TOKEN, roh=False):
    r = urllib.request.Request(BASIS + pfad)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            daten = a.read()
            return a.status, (daten if roh else json.loads(daten.decode()))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:                                        # noqa: BLE001
        return 0, str(e)


# ── Vorgefundenen Zustand LESEN (nicht raten) ──────────────────────────────
_st = cfg.get_skill_states() or {}
_vorher_an = bool((_st.get("ai_mouse") or {}).get("enabled"))
_vorher_frei = M._user_may_use_aimouse(BENUTZER)
print("vorgefunden: Skill=%s · freigegeben(%s)=%s"
      % (_vorher_an, BENUTZER, _vorher_frei))
if not _vorher_frei:
    print("ABBRUCH: %r ist nicht fuer AI-Maus freigegeben – health und /paket\n"
          "         antworten dann 403, und die Messung waere trivial wahr.\n"
          "         Einen freigegebenen Benutzer ueber AIMOUSE_TESTUSER setzen."
          % BENUTZER)
    sys.exit(2)

try:
    print("\n[1] klient_version: EINE Quelle")
    v = am.klient_version()
    check("klient_version() liefert eine Nummer", bool(v), repr(v))
    check("sie steht so in der csproj",
          ("<Version>%s</Version>" % v) in am.csproj_pfad().read_text(
              encoding="utf-8").replace(" ", ""),
          v)

    print("\n[2] health nennt sie")
    st, d = hole("/api/ai-mouse/health")
    if st != 200:
        check("health erreichbar (uebersprungen: HTTP %s)" % st, True,
              "ohne Freigabe antwortet der Endpunkt 403 – kein Codefehler")
    else:
        check("health liefert klient_version",
              isinstance(d, dict) and d.get("klient_version") == v,
              str((d or {}).get("klient_version")))

    print("\n[3] Das Paket: NUR die EXE")
    st, roh = hole("/api/ai-mouse/paket", roh=True)
    if st != 200:
        check("Paket erreichbar (uebersprungen: HTTP %s)" % st, True)
    else:
        z = zipfile.ZipFile(io.BytesIO(roh))
        namen = sorted(z.namelist())
        check("genau eine Datei im ZIP", namen == ["AiMouse.exe"], str(namen))
        check("keine Kurzanleitung",
              not any("LIESMICH" in n.upper() for n in namen), str(namen))
        check("die EXE ist brauchbar gross (> 20 MB)",
              z.getinfo("AiMouse.exe").file_size > 20 * 1048576,
              "%.1f MB" % (z.getinfo("AiMouse.exe").file_size / 1048576))
        # ⚠ DAS IST DIE ZUSAGE DER AKTUALISIERUNG: die Anwendung im Paket muss
        # GENAU die Version tragen, die health nennt – sonst laedt jeder
        # Arbeitsplatz endlos dieselbe Datei. Gemessen wird an der generierten
        # AssemblyInfo (in der EXE selbst sind die Zeichenketten komprimiert,
        # eine Suche darin ist untauglich – Register 2026-09-09).
        ai = (am._projekt_wurzel() / "ai-mouse" / "src" / "AiMouse" / "obj"
              / "Release" / "net8.0-windows" / "win-x64"
              / "AiMouse.AssemblyInfo.cs")
        if ai.is_file():
            txt = ai.read_text(encoding="utf-8", errors="replace")
            teile = (v.split(".") + ["0", "0", "0"])[:4]
            check("die gebaute Assembly traegt dieselbe Version",
                  ('AssemblyVersionAttribute("%s")' % ".".join(teile)) in txt,
                  v)
        else:
            check("AssemblyInfo nicht gefunden (uebersprungen)", True)

    print("\n[4] Ohne Anmeldung nichts")
    st, _ = hole("/api/ai-mouse/health", token="")
    check("health ohne Token: 401", st == 401, str(st))
    st, _ = hole("/api/ai-mouse/paket", token="")
    check("Paket ohne Token: 401", st == 401, str(st))
finally:
    # Nichts umgestellt -> nichts zurueckzustellen. Die Kontrolle bleibt
    # trotzdem, damit ein spaeterer Zusatz sie nicht vergisst.
    _st2 = cfg.get_skill_states() or {}
    check("Skill-Schalter unveraendert",
          bool((_st2.get("ai_mouse") or {}).get("enabled")) == _vorher_an)
    check("Freigabe fuer den Testbenutzer unveraendert",
          M._user_may_use_aimouse(BENUTZER) == _vorher_frei)

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 62, _ok, _fail, "=" * 62))
sys.exit(1 if _fail else 0)
