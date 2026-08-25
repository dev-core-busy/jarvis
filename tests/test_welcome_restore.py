"""Prueft die Wiederherstellung des Willkommens-Chats "Beispiel Prompts".

Warum es das gibt: der Chat wird pro Benutzer EINMAL angelegt und traegt danach
einen Marker (`.welcome_v1`), damit er nach dem Loeschen nicht von selbst
wiederkommt. Das war Absicht – aber es gab keinen Weg zurueck: ein Benutzer, der
ihn geloescht hatte, brauchte einen Administrator auf dem Server. Der Test misst
die drei Zusagen des neuen Weges:

  1. geloescht -> kommt zurueck (Marker wird entfernt, Sitzung neu angelegt),
  2. noch vorhanden -> es entsteht KEIN zweiter Eintrag gleichen Namens,
  3. der Benutzer kommt aus der Anmeldung, nie aus dem Request-Rumpf.

Laeuft ohne fastapi: `backend/chat_sessions.py` wird direkt geladen und sein
Ablageort auf ein Wegwerf-Verzeichnis umgebogen; der Endpunkt in `main.py` wird
per `ast` aus dem Quelltext geprueft.
"""
import ast
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
res = []


def check(name, cond, detail=""):
    res.append((name, bool(cond)))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


# ── Modul laden und den Ablageort umbiegen ───────────────────────────────────
spec = importlib.util.spec_from_file_location("cs_test", ROOT / "backend" / "chat_sessions.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_welcome_"))
cs._ROOT = SANDKASTEN / "chats"

# SANDKASTEN-WAECHTER: zeigt der Ablageort noch irgendwo ins echte Projekt, wuerde
# der Test die Chatverlaeufe des laufenden Servers anfassen. Exit 2, damit
# "konnte nicht laufen" nicht wie "bestanden" aussieht.
if not str(cs._ROOT).startswith(str(SANDKASTEN)) or str(ROOT) in str(cs._ROOT):
    print("\033[31mABBRUCH: Ablageort zeigt nicht in den Sandkasten\033[0m")
    sys.exit(2)

U = "nexustestuser"


def sid(s):
    """Id einer Sitzung – oder "" statt eines Absturzes, wenn keine kam.

    Register: nie `x["id"]` direkt in einer Pruefung. Bricht die Wiederherstellung
    (z.B. weil der Marker stehen bleibt), liefert restore None – ein direkter
    Zugriff wuerde WERFEN, und ein abgebrochener Lauf sieht wie ein bestandener aus.
    """
    return (s or {}).get("id", "")


def zaehle_welcome(user):
    """Wie viele Sitzungen des Benutzers sind der Willkommens-Chat?"""
    return sum(1 for s in cs.list_sessions(user) if cs._ist_welcome(user, s["id"], cs.get_meta(user, s["id"])))


print("\n\033[1m1. Erstanlage (unveraendertes Verhalten)\033[0m")
erst = cs.ensure_welcome_session(U)
check("erster Aufruf legt an", erst and erst.get("title") == cs.WELCOME_TITLE, str(erst))
check("Marker gesetzt", cs.welcome_done(U))
check("zweiter Aufruf legt NICHTS an (Marker greift)", cs.ensure_welcome_session(U) is None)
check("genau EIN Willkommens-Chat", zaehle_welcome(U) == 1, str(zaehle_welcome(U)))
check("meta traegt kind=welcome", (cs.get_meta(U, erst["id"]) or {}).get("kind") == "welcome",
      json.dumps(cs.get_meta(U, erst["id"])))

print("\n\033[1m2. Wiederherstellen NACH dem Loeschen\033[0m")
check("Loeschen klappt", cs.delete_session(U, erst["id"]))
check("danach kein Willkommens-Chat mehr", cs.find_welcome_session(U) is None)
check("Marker steht noch (deshalb kommt er NICHT von selbst wieder)", cs.welcome_done(U))
check("ensure allein holt ihn NICHT zurueck", cs.ensure_welcome_session(U) is None)

sess, neu = cs.restore_welcome_session(U)
check("restore liefert eine Sitzung", bool(sess), str(sess))
check("restore meldet 'neu angelegt'", neu is True, str(neu))
check("Titel stimmt", sess and sess.get("title") == cs.WELCOME_TITLE, str(sess))
check("wieder genau EIN Willkommens-Chat", zaehle_welcome(U) == 1, str(zaehle_welcome(U)))
tr = cs.load_transcript(U, sid(sess)) if sess else []
check("Transkript enthaelt genau den welcome-Eintrag",
      len(tr) == 1 and tr[0].get("kind") == "welcome", json.dumps(tr)[:200])
check("neue Id (es ist wirklich eine neue Sitzung)", sid(sess) and sid(sess) != sid(erst))

print("\n\033[1m3. Zweiter Aufruf legt KEINEN zweiten Chat an\033[0m")
sess2, neu2 = cs.restore_welcome_session(U)
check("liefert dieselbe Sitzung", sid(sess2) and sid(sess2) == sid(sess), f"{sess2} != {sess}")
check("meldet 'war schon da' (restored=False)", neu2 is False, str(neu2))
check("weiterhin genau EIN Willkommens-Chat", zaehle_welcome(U) == 1, str(zaehle_welcome(U)))
# Auch dreimal hintereinander darf nichts wuchern.
for _ in range(3):
    cs.restore_welcome_session(U)
check("auch nach fuenf Aufrufen nur EINER", zaehle_welcome(U) == 1, str(zaehle_welcome(U)))

print("\n\033[1m4. Ein FREMDER Chat namens 'Beispiel Prompts' zaehlt nicht\033[0m")
# Der Titel allein darf nicht genuegen: ein Benutzer darf einen echten Chat so
# nennen. Wuerde der als Willkommens-Chat gelten, verweigerte die
# Wiederherstellung still ihren Dienst UND der Benutzer landete in seinem
# eigenen Verlauf statt in den Beispielen.
V = "nexusfremduser"
cs.ensure_welcome_session(V)
echt = cs.find_welcome_session(V)
cs.delete_session(V, sid(echt))
getarnt = cs.create_session(V, cs.WELCOME_TITLE)
cs.save_transcript(V, sid(getarnt), [{"role": "user", "text": "meine echten Notizen"}])
check("getarnter Chat gilt NICHT als Willkommens-Chat", cs.find_welcome_session(V) is None)
s3, neu3 = cs.restore_welcome_session(V)
check("Wiederherstellung laeuft trotzdem", bool(s3) and neu3 is True, str((s3, neu3)))
gt = cs.load_transcript(V, sid(getarnt))
check("der getarnte Chat bleibt unangetastet",
      len(gt) == 1 and gt[0].get("text") == "meine echten Notizen", str(gt))
check("und er wurde nicht ueberschrieben", sid(s3) and sid(s3) != sid(getarnt))

print("\n\033[1m5. Altbestand OHNE kind im meta wird ueber Titel+Transkript erkannt\033[0m")
# Vor 2026-08-25 angelegte Willkommens-Chats tragen die Kennzeichnung nicht.
A = "nexusaltuser"
cs.ensure_welcome_session(A)
alt = cs.find_welcome_session(A)
sd = cs._sess_dir(A, sid(alt))
m = cs._read_meta(sd)
m.pop("kind", None)
cs._write_meta(sd, m)
check("kind wirklich entfernt", "kind" not in (cs._read_meta(sd) or {}))
check("Altbestand wird trotzdem gefunden",
      sid(cs.find_welcome_session(A)) and sid(cs.find_welcome_session(A)) == sid(alt))
sa, neua = cs.restore_welcome_session(A)
check("und NICHT verdoppelt", neua is False and sid(sa) == sid(alt), str((sa, neua)))

print("\n\033[1m6. Benutzertrennung\033[0m")
# Zwei Benutzer duerfen sich nicht in die Quere kommen – der Ordner ist der
# einzige Trenner, und _safe() macht aus 'nexus\\name' denselben Ordner wie aus
# 'nexusname'. Geprueft wird deshalb an ECHT verschiedenen Namen.
B = "nexusanderer"
check("anderer Benutzer hat (noch) keinen", cs.find_welcome_session(B) is None)
cs.restore_welcome_session(B)
check("jeder hat jetzt genau einen",
      zaehle_welcome(U) == 1 and zaehle_welcome(B) == 1,
      f"{zaehle_welcome(U)} / {zaehle_welcome(B)}")

print("\n\033[1m7. Der Endpunkt nimmt den Benutzer aus der ANMELDUNG\033[0m")
src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(src)
fn = None
for node in ast.walk(baum):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            d = ast.dump(dec)
            if "'/api/chat/welcome/restore'" in d.replace('"', "'"):
                fn = node
check("Endpunkt POST /api/chat/welcome/restore existiert", fn is not None)
if fn:
    rumpf = ast.get_source_segment(src, fn) or ""
    args = [a.arg for a in fn.args.args]
    check("Parameter 'user' haengt an require_auth",
          "user" in args and "require_auth" in ast.dump(fn.args))
    # Der Benutzer darf NICHT aus dem Rumpf kommen: sonst waere der Endpunkt ein
    # Weg, in fremde Chatordner zu schreiben.
    check("liest KEINEN Benutzer aus dem Request-Rumpf",
          "request.json" not in rumpf and "body.get" not in rumpf, rumpf[:200])
    check("ruft restore_welcome_session(user)",
          "restore_welcome_session(user)" in rumpf, rumpf[:200])
    check("meldet Fehlschlag als Fehler, nicht als stillen Erfolg",
          "status_code=500" in rumpf)
    check("NICHT require_local_auth (der Chat gehoert dem Benutzer selbst)",
          "require_local_auth" not in ast.dump(fn.args))

print("\n\033[1m8. Oberflaeche: Knopf, Verdrahtung, Texte\033[0m")
html = (ROOT / "frontend" / "chat.html").read_text(encoding="utf-8")
js = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")
i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
css = (ROOT / "frontend" / "css" / "chat.css").read_text(encoding="utf-8")
check("Knopf im Markup", 'id="cs-welcome"' in html)
check("Knopf liegt in der Verlaufsleiste (nach der Liste)",
      html.find('id="cs-list"') < html.find('id="cs-welcome"') < html.find("</aside>"))
check("Knopf ist uebersetzt", 'data-i18n="chat.welcome_restore"' in html)
check("Knopf ist verdrahtet", "_csWelBtn" in js and "_restoreWelcome" in js)
check("ruft den richtigen Endpunkt", "'/api/chat/welcome/restore'" in js)
for key in ("chat.welcome_restore", "chat.welcome_restore_title",
            "chat.welcome_restored", "chat.welcome_present",
            "chat.welcome_restore_failed"):
    check(f"{key} in DE UND EN", i18n.count(f"'{key}'") >= 2, str(i18n.count(f"'{key}'")))
# Der Fuss liegt beim Scrollen UEBER den Eintraegen – halbtransparent schiene der
# Text darunter durch (Register: "Was ueber Inhalt liegt, braucht eine DECKENDE
# Flaeche"). jsdom/Regex kann kein Layout rechnen, also wird die REGEL geprueft.
fuss = css[css.find(".cs-foot {"):css.find("}", css.find(".cs-foot {"))]
check(".cs-foot vorhanden", bool(fuss))
check(".cs-foot hat eine DECKENDE Flaeche", "var(--bg-secondary)" in fuss, fuss)
check(".cs-foot bleibt beim Scrollen stehen", "position: sticky" in fuss, fuss)
knopf = css[css.find(".cs-welcome {"):css.find("}", css.find(".cs-welcome {"))]
check(".cs-welcome vorhanden", bool(knopf))
# Im echten Chrome gemessen: chat.css setzt in `body.light` bewusst
# `--fg-rgb: 255,255,255`. Auf /chat sind --border/--border-hover aus theme.css
# damit in BEIDEN Themes weiss – ein Rand darauf ist auf der weissen Flaeche des
# Fusses unsichtbar (der erste Anlauf las sich als blosse Beschriftung).
for name, block in ((".cs-foot", fuss), (".cs-welcome", knopf)):
    code = block.split("*/")[-1]          # eigene Begruendung nicht mitlesen
    check(f"{name}: Rand nicht ueber --fg-rgb/--border (auf /chat weiss)",
          "--fg-rgb" not in code and "var(--border" not in code, code)
    check(f"{name}: keine harte Farbe", "#" not in code, code)
# Der Hinweis in der Karte versprach bisher nur das Loeschen. Ein Weg zurueck, den
# niemand kennt, ist kein Weg.
check("Kartenhinweis nennt den Weg zurueck (DE)",
      "Beispiel-Prompts“ unten in der Verlaufsleiste" in i18n
      or "unten in der Verlaufsleiste" in i18n)
check("Kartenhinweis nennt den Weg zurueck (EN)", "brings it back" in i18n)

shutil.rmtree(SANDKASTEN, ignore_errors=True)
schlecht = [n for n, ok in res if not ok]
print(f"\n\033[1mErgebnis: {len(res) - len(schlecht)}/{len(res)}\033[0m")
sys.exit(1 if schlecht else 0)
