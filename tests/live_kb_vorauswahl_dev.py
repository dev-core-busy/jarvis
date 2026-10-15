"""LIVE auf DEV (Lauf AUF DEM SERVER: runuser -u jarvis -- venv/bin/python <datei>)

Live auf DEV: /api/chat/kb-default gegen den ECHTEN Dienst.

Rein ueber HTTPS. Der VORGEFUNDENE Stand wird gesichert und am Ende
wiederhergestellt – nicht ein geratener Leerwert.
"""
import json, os, ssl, sys, urllib.request, urllib.error
sys.path.insert(0, "/opt/jarvis")
os.chdir("/opt/jarvis")

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BASE = "https://127.0.0.1"

res = []
def check(n, c, d=""):
    res.append(bool(c)); print(("  \033[32m✓\033[0m " if c else "  \033[31m✗\033[0m ") + n + ("" if c else f" – {d}"))

# Token wie der Endpunkt es nach erfolgreicher Anmeldung tut (PAM-Kennwort des
# Dienstbenutzers ist ein anderes als der .env-Eintrag – Register).
from backend.main import generate_token          # noqa: E402
from backend import chat_sessions as cs          # noqa: E402

USER = "jarvis"
TOK = generate_token(USER)

def ruf(method, pfad, body=None, tok=TOK):
    req = urllib.request.Request(BASE + pfad, method=method)
    if tok: req.add_header("Authorization", "Bearer " + tok)
    daten = None
    if body is not None:
        daten = json.dumps(body).encode(); req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, daten, context=CTX, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, str(e)

VORHER = cs.get_kb_default(USER)
print(f"\033[1mVorgefundener Stand: {VORHER!r}\033[0m")

try:
    print("\n\033[1m1. Abruf und Speichern\033[0m")
    st, d = ruf("GET", "/api/chat/kb-default")
    check("GET 200 mit ok/off/set", st == 200 and isinstance(d, dict) and "off" in d and "set" in d, f"{st} {d}")

    st, d = ruf("PUT", "/api/chat/kb-default", {"off": ["livepruef-a", "livepruef-b"]})
    check("PUT 200, gespeicherter Stand zurueck",
          st == 200 and d.get("off") == ["livepruef-a", "livepruef-b"] and d.get("set") is True, f"{st} {d}")
    st, d = ruf("GET", "/api/chat/kb-default")
    check("GET liefert denselben Stand", d.get("off") == ["livepruef-a", "livepruef-b"], repr(d))
    check("liegt auf PLATTE im Ordner DIESES Benutzers",
          cs.get_kb_default(USER) == ["livepruef-a", "livepruef-b"], repr(cs.get_kb_default(USER)))
    p = cs._user_dir(USER) / "kb_default.json"
    check("die Datei fuehrt die ABGEWAEHLTEN unter 'off'",
          json.loads(p.read_text(encoding="utf-8")) == {"off": ["livepruef-a", "livepruef-b"]}, p.read_text(encoding="utf-8"))

    print("\n\033[1m2. Fremdeingabe und Rechte\033[0m")
    st, d = ruf("PUT", "/api/chat/kb-default", {"off": ["gut", 7, "", None, "gut"]})
    check("ungueltige Werte werden verworfen", st == 200 and d.get("off") == ["gut"], f"{st} {d}")
    st, d = ruf("PUT", "/api/chat/kb-default",
                {"off": ["nurmeins"], "user": "fremd", "username": "fremd", "benutzer": "fremd"})
    check("Benutzerfelder im Rumpf bleiben ohne Wirkung",
          st == 200 and cs.get_kb_default(USER) == ["nurmeins"] and cs.get_kb_default("fremd") is None,
          f"{st} eigen={cs.get_kb_default(USER)} fremd={cs.get_kb_default('fremd')}")
    st, _ = ruf("GET", "/api/chat/kb-default", tok=None)
    check("ohne Token 401", st == 401, str(st))
    st, _ = ruf("PUT", "/api/chat/kb-default", {"off": ["x"]}, tok="muell")
    check("mit Muell-Token 401", st == 401, str(st))
    check("und der Muell-Aufruf hat nichts geschrieben", cs.get_kb_default(USER) == ["nurmeins"])
    st, d = ruf("PUT", "/api/chat/kb-default", {})
    check("Rumpf ohne Feld -> Vorauswahl entfernt (leer = alle aktiv)",
          st == 200 and d.get("set") is False and cs.get_kb_default(USER) is None, f"{st} {d}")
    st, d = ruf("PUT", "/api/chat/kb-default", {"off": "keine-liste"})
    check("kein Wurf bei falschem Typ (500 waere ein Fehler)", st == 200, f"{st} {d}")

    print("\n\033[1m3. Wirkt es im Chat? (Sitzung ohne gespeicherte Auswahl)\033[0m")
    # Eine frische Sitzung hat kb_groups NICHT gesetzt -> der Client wendet dort
    # die Vorauswahl an. Der Endpunkt muss das Feld genau so ausweisen.
    s = cs.create_session(USER, "Live-Pruef kb-default")
    sid = s["id"]
    st, d = ruf("GET", f"/api/chat/sessions/{sid}")
    check("frische Sitzung: kb_groups_set ist false (dort greift die Vorauswahl)",
          st == 200 and d.get("kb_groups_set") is False and (d.get("transcript") or []) == [], f"{st} {d}")
    cs.delete_session(USER, sid)
    check("Pruef-Sitzung abgeraeumt", cs.get_meta(USER, sid) is None)
finally:
    cs.save_kb_default(USER, VORHER or [])
    ist = cs.get_kb_default(USER)
    ok = (ist == VORHER)
    print(("  \033[32m✓\033[0m " if ok else "  \033[31m✗\033[0m ") + f"Ausgangszustand wiederhergestellt ({ist!r})")
    res.append(ok)
    cs.save_kb_default("fremd", [])

n = sum(1 for r in res if r)
print(f"\n\033[1mErgebnis: {n} OK, {len(res)-n} FAIL\033[0m")
sys.exit(0 if all(res) else 1)
