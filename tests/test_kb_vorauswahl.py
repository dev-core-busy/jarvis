"""Waechter: Wissensquellen-Vorauswahl fuer NEUE Chats (Backend).

Geprueft werden EIGENSCHAFTEN, nicht Schreibweisen:

  1. Rundlauf speichern/lesen ueber die ECHTEN Funktionen.
  2. ⚠ GESPEICHERT WERDEN DIE ABGEWAEHLTEN IDS. Das ist die tragende
     Entscheidung: eine spaeter angelegte Wissensgruppe ist damit von selbst
     dabei, statt still aus allen neuen Chats zu fallen. Der Test haelt fest,
     dass die Datei die abgewaehlten fuehrt.
  3. Fremdeingabe wird geprueft und VERWORFEN, nicht geraten (Nicht-Strings,
     leere Werte, ueberlange Ids, Duplikate) – samt Deckel gegen Aufblaehen.
  4. Leere Liste = keine Vorauswahl -> Datei weg (beides bedeutet "alle aktiv",
     ein Eintrag dafuer waere eine Karteileiche).
  5. Der Benutzer kommt AUSSCHLIESSLICH aus der Anmeldung, nie aus dem Rumpf –
     sonst waere der Endpunkt ein Weg in fremde Einstellungen. Gemessen an
     einem ausgefuehrten Schnitt des Endpunkt-Rumpfs.
  6. Beide Endpunkte haengen an require_auth (nicht offen).

SANDKASTEN-SCHRANKE: der Test biegt _ROOT auf ein Wegwerf-Verzeichnis. Zeigt
er danach noch in den echten Datenbestand, bricht er mit Exit 2 ab – "konnte
nicht laufen" darf nie wie "bestanden" aussehen.
"""
import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def section(t):
    print(f"\n\033[1m{t}\033[0m")


def sicher(fn, *a, **k):
    """Ruft fn und gibt bei einem Wurf die Meldung zurueck – eine Pruefung darf
    nicht ABBRECHEN, sonst fehlt die Bilanzzeile und der Lauf ist von "nicht
    gelaufen" nicht zu unterscheiden."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"WURF: {type(e).__name__}: {e}"


# ── Namens-Guard GANZ OBEN: gegen einen aelteren Stand stirbt der Lauf sonst
#    an einem nackten AttributeError, ohne FAIL und ohne Bilanz.
from backend import chat_sessions as cs  # noqa: E402

fehlt = [n for n in ("get_kb_default", "save_kb_default", "_kb_ids_saeubern") if not hasattr(cs, n)]
if fehlt:
    print(f"\033[31mABBRUCH\033[0m: chat_sessions kennt nicht: {', '.join(fehlt)}")
    print("Ergebnis: 0 OK, 1 FAIL (alter Stand)")
    sys.exit(1)

# ── Sandkasten ───────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="kbvor-"))
cs._ROOT = TMP / "chats"
if str(ROOT) in str(cs._ROOT.resolve()) and "chats" in str(cs._ROOT) and not str(cs._ROOT).startswith(str(TMP)):
    print("\033[31mABBRUCH\033[0m: Sandkasten greift nicht – _ROOT zeigt in den echten Bestand")
    sys.exit(2)
if not str(cs._ROOT).startswith(str(TMP)):
    print("\033[31mABBRUCH\033[0m: Sandkasten greift nicht")
    sys.exit(2)

U = "nexus\\pruef.person"

try:
    # ── 1. Rundlauf ─────────────────────────────────────────────────────────
    section("1. Rundlauf")
    check("ohne Datei: None (= keine Vorauswahl, alle Gruppen aktiv)",
          sicher(cs.get_kb_default, U) is None)
    check("speichern liefert den gespeicherten Stand",
          sicher(cs.save_kb_default, U, ["g1", "g2"]) == ["g1", "g2"])
    check("lesen liefert denselben Stand",
          sicher(cs.get_kb_default, U) == ["g1", "g2"])
    check("ueberschreiben ersetzt (kein Anhaengen)",
          sicher(cs.save_kb_default, U, ["g3"]) == ["g3"] and cs.get_kb_default(U) == ["g3"])

    # ── 2. Die abgewaehlten, nicht die ausgewaehlten ────────────────────────
    section("2. Gespeichert werden die ABGEWAEHLTEN Ids")
    cs.save_kb_default(U, ["g_aus_1", "g_aus_2"])
    p = cs._user_dir(U) / "kb_default.json"
    inhalt = sicher(lambda: json.loads(p.read_text(encoding="utf-8")))
    check("Datei fuehrt die Liste unter 'off'",
          isinstance(inhalt, dict) and inhalt.get("off") == ["g_aus_1", "g_aus_2"], repr(inhalt))
    check("kein Feld, das die AUSGEWAEHLTEN fuehrt (das waere die Umkehrung)",
          isinstance(inhalt, dict) and set(inhalt.keys()) == {"off"}, repr(inhalt))
    quelle = (ROOT / "backend" / "chat_sessions.py").read_text(encoding="utf-8")
    doc = ast.get_docstring(next(
        n for n in ast.parse(quelle).body
        if isinstance(n, ast.FunctionDef) and n.name == "get_kb_default")) or ""
    check("die Begruendung steht bei der Funktion (abgewaehlt/neue Gruppe)",
          "abgewaehlt" in doc.lower() or "Vorauswahl" in doc)

    # ── 3. Fremdeingabe ─────────────────────────────────────────────────────
    section("3. Fremdeingabe wird verworfen, nicht geraten")
    check("Nicht-Strings fallen heraus",
          sicher(cs.save_kb_default, U, ["ok", 5, None, True, {"a": 1}, ["x"]]) == ["ok"])
    check("leere/nur-Leerraum-Ids fallen heraus",
          sicher(cs.save_kb_default, U, ["", "   ", "gut"]) == ["gut"])
    check("Ids werden getrimmt",
          sicher(cs.save_kb_default, U, ["  g9  "]) == ["g9"])
    check("ueberlange Id faellt heraus",
          sicher(cs.save_kb_default, U, ["a" * (cs._KB_DEFAULT_ID_MAX + 1), "kurz"]) == ["kurz"])
    check("Id genau an der Grenze bleibt (Positivkontrolle)",
          sicher(cs.save_kb_default, U, ["b" * cs._KB_DEFAULT_ID_MAX]) == ["b" * cs._KB_DEFAULT_ID_MAX])
    check("Duplikate werden zusammengefasst, Reihenfolge bleibt",
          sicher(cs.save_kb_default, U, ["b", "a", "b", "a", "c"]) == ["b", "a", "c"])
    viel = [f"id{i}" for i in range(cs._KB_DEFAULT_MAX_IDS + 50)]
    check(f"Deckel greift ({cs._KB_DEFAULT_MAX_IDS} Ids)",
          len(sicher(cs.save_kb_default, U, viel) or []) == cs._KB_DEFAULT_MAX_IDS)
    check("kein Wurf bei voelligem Unsinn statt Liste",
          sicher(cs.save_kb_default, U, "keine-liste") is None
          and sicher(cs.save_kb_default, U, None) is None)

    # ── 4. Leere Liste = keine Vorauswahl ───────────────────────────────────
    section("4. Leere Liste entfernt die Vorauswahl")
    cs.save_kb_default(U, ["g1"])
    check("Datei ist vorher da", p.exists())
    check("leere Liste liefert None", sicher(cs.save_kb_default, U, []) is None)
    check("Datei ist danach weg (keine Karteileiche)", not p.exists())
    check("lesen liefert danach None", sicher(cs.get_kb_default, U) is None)
    # Beschaedigte Datei: fail-open auf "keine Vorauswahl", kein Wurf
    cs._user_dir(U).mkdir(parents=True, exist_ok=True)
    p.write_text("{kein json", encoding="utf-8")
    check("beschaedigte Datei -> None (fail-open), kein Wurf",
          sicher(cs.get_kb_default, U) is None)
    p.write_text(json.dumps({"off": "keine-liste"}), encoding="utf-8")
    check("falscher Typ in der Datei -> None", sicher(cs.get_kb_default, U) is None)
    p.write_text(json.dumps({"off": []}), encoding="utf-8")
    check("leeres 'off' in der Datei -> None (= alle aktiv)", sicher(cs.get_kb_default, U) is None)

    # ── 5. Benutzertrennung + Endpunkt-Rumpf ────────────────────────────────
    section("5. Der Benutzer kommt aus der Anmeldung")
    cs.save_kb_default("alice", ["ga"])
    cs.save_kb_default("bob", ["gb"])
    check("zwei Benutzer, zwei Staende",
          cs.get_kb_default("alice") == ["ga"] and cs.get_kb_default("bob") == ["gb"])

    haupt = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    baum = ast.parse(haupt)
    fns = {n.name: n for n in ast.walk(baum)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    fn = fns.get("chat_kb_default_save")
    check("PUT-Endpunkt vorhanden", fn is not None)
    if fn is not None:
        # Dekoratoren und die Depends()-Vorgaben aus der Signatur entfernen:
        # `@app.put(...)` und `Depends(require_auth)` sind hier nicht aufloesbar,
        # gemessen werden soll der RUMPF.
        import copy
        schnitt = copy.deepcopy(fn)
        schnitt.decorator_list = []
        schnitt.name = "_f"
        schnitt.args.defaults = []
        schnitt.args.args = [ast.arg(arg="request"), ast.arg(arg="user")]
        schnitt.args.kwonlyargs = []
        schnitt.args.kw_defaults = []
        schnitt.returns = None
        rumpf = ast.unparse(ast.fix_missing_locations(schnitt))
        # Der Rumpf wird WIRKLICH ausgefuehrt: nur so faellt auf, wenn jemand
        # spaeter einen Namen aus dem Body zieht.
        gesehen = {}

        class _CS:
            _KB_DEFAULT_MAX_IDS = cs._KB_DEFAULT_MAX_IDS

            @staticmethod
            def save_kb_default(user, ids):
                gesehen["user"] = user
                gesehen["ids"] = ids
                return cs._kb_ids_saeubern(ids) or None

        class _Req:
            async def json(self):
                return {"off": ["x"], "user": "fremd", "username": "fremd",
                        "benutzer": "fremd", "owner": "fremd"}

        ns = {"JSONResponse": lambda d, **k: d, "Request": object}
        # Import im Rumpf auf die Attrappe umbiegen
        rumpf_att = rumpf.replace("from backend import chat_sessions as cs", "cs = _CS")
        # (Signatur steht schon auf (request, user) – siehe Schnitt oben.)
        ns["_CS"] = _CS
        erg = sicher(exec, compile(rumpf_att, "<schnitt>", "exec"), ns)
        if isinstance(erg, str):
            check("Endpunkt-Rumpf ausfuehrbar geschnitten", False, erg)
        else:
            import asyncio
            out = sicher(asyncio.run, ns["_f"](_Req(), "angemeldet"))
            check("Endpunkt WIRKLICH ausgefuehrt", isinstance(out, dict), repr(out))
            check("der gespeicherte Benutzer ist der ANGEMELDETE, nicht der aus dem Rumpf",
                  gesehen.get("user") == "angemeldet", repr(gesehen.get("user")))
            check("die Liste kommt aus dem Rumpf-Feld 'off'",
                  gesehen.get("ids") == ["x"], repr(gesehen.get("ids")))

    section("6. Rechte")
    for m, route in (("get", "/api/chat/kb-default"), ("put", "/api/chat/kb-default")):
        pat = re.compile(r'@app\.' + m + r'\("' + re.escape(route) + r'"\)\s*\nasync def \w+\(([^)]*)\)', re.S)
        mm = pat.search(haupt)
        check(f"{m.upper()} {route} haengt an require_auth",
              bool(mm) and "require_auth" in (mm.group(1) if mm else ""),
              (mm.group(1) if mm else "Route nicht gefunden"))

finally:
    shutil.rmtree(TMP, ignore_errors=True)

ok = sum(1 for r in res if r)
print(f"\n\033[1mErgebnis: {ok} OK, {len(res) - ok} FAIL\033[0m")
sys.exit(0 if all(res) else 1)
