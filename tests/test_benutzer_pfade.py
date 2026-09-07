#!/usr/bin/env python3
"""Waechter: EIN Benutzername, EINE Ablage (Vorfall 2026-09-07).

Geprueft werden vier Dinge, und das dritte ist das eigentliche Netz:
  1. die Eigenschaften von ``norm_user``/``pfad_teil`` (vier Tippformen desselben
     Menschen ergeben EINEN Pfadteil, Kanal-Kennungen bleiben unterscheidbar,
     Traversal ist ausgeschlossen);
  2. eine DRIFT-SCHRANKE gegen die neun vorhandenen ``norm_user``-Fassungen –
     sie werden AUSGEFUEHRT und gegen die kanonische verglichen. Laufen sie
     auseinander, bedeutet derselbe Name in zwei Modulen etwas Verschiedenes;
  3. die REGEL: jede Funktion, die aus einem Benutzernamen einen Pfad bildet,
     muss ``pfad_teil`` benutzen. Ueber den AST, nicht ueber eine gepflegte
     Liste – damit faellt auch eine kuenftige sechste Ablage auf. Mit
     Positivkontrolle: findet der Waechter die fuenf bekannten Stellen nicht,
     ist er blind und bricht mit Exit 2 ab;
  4. die Migration, WIRKLICH ausgefuehrt in einem Sandkasten, mit den echten
     Namen des DEV-Bestands.
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

OK = FAIL = 0
def check(bez, bed):
    global OK, FAIL
    if isinstance(bez, bool) or not isinstance(bez, str):
        print("WAECHTER-FEHLER: Argumente vertauscht:", bez, bed); sys.exit(2)
    if bed:
        OK += 1; print(f"  OK   {bez}")
    else:
        FAIL += 1; print(f"  FAIL {bez}")

def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren: eine Pruefung darf nicht WERFEN, sonst
    bricht der Lauf ohne Bilanz ab und ist von 'nicht gelaufen' nicht zu
    unterscheiden (Register)."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"<WURF: {type(e).__name__}: {e}>"

def ohne_kommentare(quelle: str) -> str:
    """Kommentare und Docstrings entfernen – ein Waechter, der seine eigene
    Begruendung liest, prueft nichts (Register, 13 belegte Faelle)."""
    import tokenize
    raus = list(quelle)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                (zs, zc), (ze, ec) = tok.start, tok.end
                if zs == ze:
                    zeilen = quelle.split("\n")
                    off = sum(len(z) + 1 for z in zeilen[:zs - 1])
                    for i in range(off + zc, min(off + ec, len(raus))):
                        raus[i] = " "
    except Exception:
        return quelle
    s = "".join(raus)
    # Docstrings ueber den AST leeren
    try:
        baum = ast.parse(s)
    except SyntaxError:
        return s
    zeilen = s.split("\n")
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (k.body and isinstance(k.body[0], ast.Expr)
                    and isinstance(k.body[0].value, ast.Constant)
                    and isinstance(k.body[0].value.value, str)):
                d = k.body[0]
                for i in range(d.lineno - 1, min(d.end_lineno, len(zeilen))):
                    zeilen[i] = ""
    return "\n".join(zeilen)


print("\n=== 1. norm_user / pfad_teil: die Eigenschaften ===")
from backend.benutzer import norm_user, pfad_teil  # noqa: E402

# Der gemeldete Fall und die drei weiteren Tippformen desselben Menschen.
formen = ["nexus\\karsten.moeller", "karsten.moeller",
          "karsten.moeller@nexus-ag.de", "NEXUS\\Karsten.Moeller"]
teile = {sicher(pfad_teil, f) for f in formen}
check(f"vier Tippformen -> EIN Pfadteil (erhalten: {sorted(teile)})", teile == {"karsten.moeller"})
check("Grossschreibung faellt zusammen", pfad_teil("ANDREAS.BENDER") == "andreas.bender")
check("jarvis bleibt jarvis", pfad_teil("jarvis") == "jarvis")

# Kanal-Kennungen: MUESSEN unterscheidbar bleiben. Ein Zerlegen am Doppelpunkt
# wuerde alle API-Quellen auf EINE Ablage werfen - auf DEV liegen dort vier.
# ⚠ "api:kunde@extern" und "api:dom\\quelle" gehoeren DAZU und sind der
# eigentliche Pruefstein: nur sie brechen, wenn die ":"-Ausnahme in norm_user
# faellt. Die erste Fassung dieser Liste enthielt weder @ noch Backslash – die
# Gegenprobe "zerlegt Kanal-Kennungen" traf damit ins Leere und blieb stumm.
kanaele = ["api:Externes System", "api:Audit-Test", "api:PPT-Untersuchung",
           "api:kunde@extern", "api:dom\\quelle",
           "wa:+491234567", "tg:998877"]
kteile = [sicher(pfad_teil, k) for k in kanaele]
check(f"Kanal-Kennungen bleiben unterscheidbar ({len(set(kteile))} von {len(kanaele)})",
      len(set(kteile)) == len(kanaele))
check("api-Kanal behaelt seinen Praefix", all(t.startswith("api_") for t in kteile[:5]))
check(f"Kanal-Kennung mit @ bleibt ganz ({norm_user('api:kunde@extern')!r})",
      norm_user("api:kunde@extern") == "api:kunde@extern")
check(f"Kanal-Kennung mit Backslash bleibt ganz ({norm_user('api:dom\\quelle')!r})",
      norm_user("api:dom\\quelle") == "api:dom\\quelle")
check("wa/tg unterscheiden sich", kteile[3] != kteile[4])

# Traversal: das Ergebnis darf NIE einen Pfadwechsel ausloesen.
for boes in ["../../etc/passwd", "..", ".", "/etc/passwd", "..\\..\\x", "a/../b", ""]:
    t = sicher(pfad_teil, boes)
    check(f"kein Pfadwechsel aus {boes!r} (-> {t!r})",
          isinstance(t, str) and "/" not in t and "\\" not in t
          and t not in ("..", ".") and t != "")

print("\n=== 2. Drift-Schranke: die neun vorhandenen norm_user-Fassungen ===")
# Sie werden AUSGEFUEHRT, nicht im Quelltext verglichen: zwei Fassungen koennen
# zeichengleich aussehen und trotzdem verschieden wirken (Vorgabewerte, strip).
proben = ["nexus\\andreas.bender", "andreas.bender", "ANDREAS.BENDER@x.de",
          "jarvis", "api:Externes System", "wa:+49123", "", "  x  ",
          # Diese zwei trennen die Fassungen wirklich: eine ohne ":"-Ausnahme
          # zerlegt sie (short_tracks.norm_user hat sie nicht - deshalb steht
          # es bewusst NICHT in der Liste unten).
          "api:kunde@extern", "api:dom\\quelle"]
fassungen = {
    "audit_log": ("backend.audit_log", "norm_user"),
    "conv_log": ("backend.conv_log", "norm_user"),
    "security_guard": ("backend.security_guard", "norm_user"),
    "jira_accounts": ("backend.jira_accounts", "norm_user"),
    "mail_accounts": ("backend.mail_accounts", "norm_user"),
    "sap_accounts": ("backend.sap_accounts", "norm_user"),
    "vemas_accounts": ("backend.vemas_accounts", "norm_user"),
    "user_sessions": ("backend.user_sessions", "_key"),
    "short_tracks": ("backend.short_tracks", "norm_user"),
}
gefunden = 0
for label, (mod, fn) in fassungen.items():
    try:
        m = __import__(mod, fromlist=[fn])
        f = getattr(m, fn)
    except Exception as e:  # noqa: BLE001
        print(f"  --   {label}: nicht ladbar ({type(e).__name__}) - NICHT GEPRUEFT")
        continue
    gefunden += 1
    abw = [(p, sicher(f, p), sicher(norm_user, p)) for p in proben]
    abw = [x for x in abw if x[1] != x[2]]
    check(f"{label}.{fn} deckungsgleich mit benutzer.norm_user"
          + (f" (Abweichung: {abw[:2]})" if abw else ""), not abw)
check(f"mindestens 6 Fassungen wirklich geprueft (waren {gefunden})", gefunden >= 6)

print("\n=== 3. REGEL: Benutzerpfade nur ueber pfad_teil ===")
BENUTZER_PARAM = {"user", "username", "owner", "benutzer", "usr"}

def pfadbildner(pfad: Path):
    """Funktionen, die aus einem benutzerartigen Parameter einen Pfad bilden.

    Erkannt wird die EIGENSCHAFT: ein Parameter mit benutzerartigem Namen, und
    im Rumpf ein ``/``-Ausdruck oder ein f-String, in dem dieser Parameter
    (direkt oder ueber eine lokale Variable) vorkommt.
    """
    try:
        baum = ast.parse(ohne_kommentare(pfad.read_text(encoding="utf-8")))
    except Exception:
        return []
    raus = []
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        if not (params & BENUTZER_PARAM):
            continue
        # Bildet sie einen Pfad? -> BinOp mit "/" irgendwo im Rumpf
        hat_pfad = any(isinstance(k, ast.BinOp) and isinstance(k.op, ast.Div)
                       for k in ast.walk(fn))
        if not hat_pfad:
            continue
        # Gibt sie einen Path zurueck oder legt sie ein Verzeichnis an?
        rueck = any(isinstance(k, ast.Return) and k.value is not None
                    and any(isinstance(x, ast.BinOp) and isinstance(x.op, ast.Div)
                            for x in ast.walk(k))
                    for k in ast.walk(fn))
        if not rueck:
            continue
        namen = {k.id for k in ast.walk(fn) if isinstance(k, ast.Name)} \
            | {k.attr for k in ast.walk(fn) if isinstance(k, ast.Attribute)}
        raus.append((fn.name, namen))
    return raus

def alle_funktionen(pfad: Path) -> dict:
    """Jede Funktion des Moduls mit den Namen, die in ihrem Rumpf vorkommen."""
    try:
        baum = ast.parse(ohne_kommentare(pfad.read_text(encoding="utf-8")))
    except Exception:
        return {}
    raus = {}
    for fn in ast.walk(baum):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raus[fn.name] = {k.id for k in ast.walk(fn) if isinstance(k, ast.Name)} \
                | {k.attr for k in ast.walk(fn) if isinstance(k, ast.Attribute)}
    return raus

def nutzt_pfad_teil(start: str, welt: dict, tiefe: int = 0) -> bool:
    """TRANSITIV: eine Funktion ist in Ordnung, wenn sie ``pfad_teil`` selbst
    ruft ODER an eine Funktion delegiert, die es (mittelbar) tut.

    Ohne diese Aufloesung meldet der Waechter jede Delegation als Verstoss –
    ``_sess_dir`` und ``welcome_done`` rufen ``_user_dir``, und ``_path`` in
    chat_history ruft ``_safe_user``. Drei Fehlalarme beim ersten Lauf.
    """
    if tiefe > 6 or start not in welt:
        return False
    namen = welt[start]
    if "pfad_teil" in namen:
        return True
    return any(nutzt_pfad_teil(n, welt, tiefe + 1)
               for n in namen if n in welt and n != start)

kandidaten = {}
welten = {}
for rel in ["backend/tools/memory.py", "backend/chat_sessions.py",
            "backend/chat_history.py", "backend/main.py"]:
    welten[rel] = alle_funktionen(WURZEL / rel)
    for name, _ in pfadbildner(WURZEL / rel):
        kandidaten[f"{rel}::{name}"] = (rel, name)

# POSITIVKONTROLLE: findet der Waechter die bekannten Stellen nicht, misst er
# etwas anderes als er behauptet - dann ist jede gruene Zeile wertlos.
bekannt = ["memory.py::_get_memory_path", "chat_sessions.py::_user_dir",
           "chat_history.py::_path", "main.py::_sap_instr_path",
           "main.py::_support_instr_path", "main.py::_vemas_instr_path"]
fehlt = [b for b in bekannt if not any(k.endswith(b) for k in kandidaten)]
if fehlt:
    print(f"  ABBRUCH: der Erkenner findet diese bekannten Stellen NICHT: {fehlt}")
    print(f"  gefunden wurden: {sorted(kandidaten)}")
    sys.exit(2)
check(f"Erkenner findet alle {len(bekannt)} bekannten Pfadbildner", True)

for k, (rel, name) in sorted(kandidaten.items()):
    check(f"{k} nutzt pfad_teil (ggf. mittelbar)", nutzt_pfad_teil(name, welten[rel]))

print("\n=== 3b. REGEL: Benutzer-VERGLEICHE nur ueber norm_user ===")
# Nicht nur Pfade – auch dict-Schluessel und Eigentuemer-Vergleiche. Auf DEV
# lagen in issues_admin_seen.json BEIDE Formen desselben Menschen als
# Schluessel ('nexus\andreas.bender' und 'andreas.bender'), weil issues.py
# ueberall roh mit .strip().lower() verglich.
roh = ohne_kommentare((WURZEL / "backend" / "issues.py").read_text(encoding="utf-8"))
treffer = []
for i, z in enumerate(roh.split("\n"), 1):
    if "strip().lower()" not in z:
        continue
    # Nur Zeilen, in denen es um einen BENUTZER geht - type/priority/status
    # duerfen weiterhin roh kleingeschrieben werden.
    if any(w in z for w in ("user", "author", "owner", "benutzer")):
        treffer.append((i, z.strip()[:80]))
check(f"issues.py: keine rohen Benutzer-Vergleiche ({treffer or 'keine'})", not treffer)
# Positivkontrolle des Schnitts: die Datei MUSS norm_user wirklich benutzen,
# sonst waere die Abwesenheit trivial (z.B. bei einer leeren Datei).
check(f"issues.py ruft norm_user ({roh.count('norm_user(')}x)", roh.count("norm_user(") >= 8)
check("issues.py importiert norm_user aus backend.benutzer",
      "from backend.benutzer import norm_user" in roh)

print("\n=== 4. Migration: ausgefuehrt im Sandkasten ===")
sandkasten = Path(tempfile.mkdtemp(prefix="benutzer-mig-"))
try:
    import backend.benutzer_migration as mig
    # ⚠ SANDKASTEN-WAECHTER: ohne ihn schreibt der Test in den ECHTEN Bestand.
    mig.DATA = sandkasten / "data"
    mig.PROJECT_ROOT = sandkasten
    if not str(mig.DATA).startswith(str(sandkasten)):
        print("  ABBRUCH: Sandkasten nicht wirksam"); sys.exit(2)
    D = mig.DATA
    (D / "chats").mkdir(parents=True)
    (D / "chat_history").mkdir(parents=True)
    (D / "support_instructions").mkdir(parents=True)
    (D / "vemas_instructions").mkdir(parents=True)
    # Die sechste Ablage MUSS im Testbestand vorkommen, sonst ist die
    # Gegenprobe "vemas als Ablage vergessen" zahnlos (sie war es).
    (D / "vemas_instructions" / "nexus_karsten.moeller.md").write_text(
        "meine VEMAS-Anweisung", encoding="utf-8")

    # Namensquelle wie im echten Bestand
    (D / "user_sessions.json").write_text(json.dumps(
        {"users": {"andreas.bender": {}, "andrea.ladd": {}, "karsten.moeller": {}, "jarvis": {}}}),
        encoding="utf-8")
    (D / "settings.json").write_text(json.dumps({"ad_domain": "nexus.local"}), encoding="utf-8")

    # (a) memory: BEIDE Formen vorhanden -> zusammenfuehren, neuerer gewinnt
    (D / "memory_nexus_karsten_moeller.json").write_text(json.dumps({
        "alt_und_neu": {"value": "AUS DER DOMAENEN-DATEI", "updated": "2026-09-01T10:00:00"},
        "nur_domaene": {"value": "nur hier", "updated": "2026-05-01T10:00:00"}}), encoding="utf-8")
    (D / "memory_karsten.moeller.json").write_text(json.dumps({
        "alt_und_neu": {"value": "ALT", "updated": "2026-01-01T10:00:00"},
        "nur_kanonisch": {"value": "bleibt", "updated": "2026-06-01T10:00:00"}}), encoding="utf-8")

    # (b) chats: beide Formen, Sitzungen + Datei auf Benutzerebene
    (D / "chats" / "nexusandreas.bender" / "aaa111bbb222").mkdir(parents=True)
    (D / "chats" / "nexusandreas.bender" / "aaa111bbb222" / "meta.json").write_text("{}", encoding="utf-8")
    (D / "chats" / "nexusandreas.bender" / "preprompt.txt").write_text("mein preprompt", encoding="utf-8")
    (D / "chats" / "andreas.bender" / "ccc333ddd444").mkdir(parents=True)

    # (c) chats: NUR die Domaenenform -> umbenennen
    (D / "chats" / "nexusandrea.ladd" / "eee555fff666").mkdir(parents=True)

    # (d) chat_history: beide Formen -> nach ts sortiert zusammenfuehren
    # ⚠ ABSICHTLICH DIE FALSCHE Reihenfolge: das ZIEL traegt die NEUERE
    # Nachricht, die Quelle die aeltere. Ohne Sortierung ergibt "Ziel + Quelle"
    # dann [zweite, erste] – nur so ist die Sortierpruefung nicht zahnlos.
    # (Register: genau diese Falle stand dort schon, und ich bin erneut
    # hineingelaufen – die erste Fassung stand zufaellig richtig.)
    (D / "chat_history" / "nexusandreas.bender.json").write_text(
        json.dumps([{"role": "user", "text": "erste", "ts": 100}]), encoding="utf-8")
    (D / "chat_history" / "andreas.bender.json").write_text(
        json.dumps([{"role": "user", "text": "zweite", "ts": 200}]), encoding="utf-8")

    # (f) Kanal-Ablagen und der Sentinel: keine Menschen, aber echte Ablagen.
    # Ohne Rekonstruktion blieben sie als "nicht zuordenbar" liegen - und weil
    # der korrigierte Code sie unter dem NEUEN Namen sucht, waere ihr Inhalt
    # still verloren (auf DEV vier Dateien).
    (D / "memory_api_Audit-Test.json").write_text(
        json.dumps({"k": {"value": "Kanal-Gedaechtnis", "updated": "2026-01-01T00:00:00"}}),
        encoding="utf-8")
    (D / "memory___unprivilegiert__.json").write_text(
        json.dumps({"u": {"value": "anonym", "updated": "2026-01-01T00:00:00"}}),
        encoding="utf-8")

    # (e) Fremde Datei, die NICHT angefasst werden darf
    (D / "memory.json").write_text(json.dumps({"global": {"value": "x"}}), encoding="utf-8")
    fremd_md5 = (D / "memory.json").read_bytes()

    b = mig.finde()
    check(f"bekannte Benutzer erkannt ({sorted(b.benutzer)})",
          {"andreas.bender", "andrea.ladd", "karsten.moeller"} <= set(b.benutzer))
    check(f"Domaenen-Praefix 'nexus' erkannt ({b.praefixe})", "nexus" in b.praefixe)

    nach_ablage = {}
    for v in b.vorgaenge:
        nach_ablage.setdefault(v.ablage, []).append(v)
    # ⚠ Die EIGENSCHAFT, nicht die Anzahl: eine feste Zahl ist eine Zeitbombe
    # (Register) - sie schnappte prompt zu, als der Testbestand um die zwei
    # Kanal-Ablagen wuchs.
    def gibt(ablage, quelle, ziel):
        return any(v.quelle.name == quelle and v.ziel.name == ziel
                   for v in nach_ablage.get(ablage, []))
    check("memory: die Domaenen-Datei wird zusammengefuehrt",
          gibt("memory", "memory_nexus_karsten_moeller.json", "memory_karsten.moeller.json"))
    check(f"chats: beide Ordner erfasst ({[v.quelle.name for v in nach_ablage.get('chats', [])]})",
          gibt("chats", "nexusandreas.bender", "andreas.bender")
          and gibt("chats", "nexusandrea.ladd", "andrea.ladd"))
    check("chat_history: die Domaenen-Datei wird erfasst",
          gibt("chat_history", "nexusandreas.bender.json", "andreas.bender.json"))
    check("vemas_instructions: die Domaenen-Datei wird erfasst",
          gibt("vemas_instructions", "nexus_karsten.moeller.md", "karsten.moeller.md"))
    arten = {(v.ablage, v.quelle.name): v.art for v in b.vorgaenge}
    check("memory-Vorgang ist ein Zusammenfuehren",
          arten.get(("memory", "memory_nexus_karsten_moeller.json")) == "zusammenfuehren")
    check("chats/nexusandrea.ladd ist ein Umbenennen",
          arten.get(("chats", "nexusandrea.ladd")) == "umbenennen")

    # TROCKENLAUF darf NICHTS aendern
    vorher = sorted(str(p.relative_to(D)) for p in D.rglob("*"))
    tr = mig.anwenden(b, trocken=True)
    check("Trockenlauf ist die Vorgabe (anwenden() ohne Argument)",
          mig.anwenden.__defaults__[-1] is True)
    check("Trockenlauf aendert nichts",
          sorted(str(p.relative_to(D)) for p in D.rglob("*")) == vorher)
    check(f"Trockenlauf meldet {len(tr['vorgaenge'])} Vorgaenge", len(tr["vorgaenge"]) >= 4)

    # ANWENDEN
    erg = mig.anwenden(mig.finde(), trocken=False)
    check(f"keine Fehler beim Anwenden ({erg['fehler']})", not erg["fehler"])
    check("Sicherung wurde angelegt", bool(erg["sicherung"]) and Path(erg["sicherung"]).exists())

    # memory zusammengefuehrt, neuerer gewinnt
    m = sicher(lambda: json.loads((D / "memory_karsten.moeller.json").read_text(encoding="utf-8")))
    check("memory: Domaenen-Datei ist weg",
          not (D / "memory_nexus_karsten_moeller.json").exists())
    check(f"memory: alle drei Schluessel da ({sorted(m) if isinstance(m, dict) else m})",
          isinstance(m, dict) and set(m) == {"alt_und_neu", "nur_domaene", "nur_kanonisch"})
    check("memory: bei Konflikt gewinnt der NEUERE",
          isinstance(m, dict) and m.get("alt_und_neu", {}).get("value") == "AUS DER DOMAENEN-DATEI")

    # chats zusammengefuehrt
    zb = D / "chats" / "andreas.bender"
    check("chats: Domaenen-Ordner ist weg", not (D / "chats" / "nexusandreas.bender").exists())
    check("chats: beide Sitzungen im Zielordner",
          (zb / "aaa111bbb222").is_dir() and (zb / "ccc333ddd444").is_dir())
    check("chats: preprompt.txt der Benutzerebene ist mitgekommen",
          (zb / "preprompt.txt").exists()
          and (zb / "preprompt.txt").read_text(encoding="utf-8") == "mein preprompt")
    check("chats: umbenannter Ordner heisst jetzt andrea.ladd",
          (D / "chats" / "andrea.ladd" / "eee555fff666").is_dir()
          and not (D / "chats" / "nexusandrea.ladd").exists())

    # chat_history sortiert
    h = sicher(lambda: json.loads((D / "chat_history" / "andreas.bender.json").read_text(encoding="utf-8")))
    check(f"chat_history: beide Nachrichten, nach ts sortiert ({h})",
          isinstance(h, list) and [x.get("text") for x in h] == ["erste", "zweite"])

    check("vemas_instructions: umbenannt auf den kanonischen Namen",
          (D / "vemas_instructions" / "karsten.moeller.md").exists()
          and not (D / "vemas_instructions" / "nexus_karsten.moeller.md").exists())
    check("Kanal-Ablage rekonstruiert und umbenannt",
          (D / "memory_api_audit-test.json").exists()
          and not (D / "memory_api_Audit-Test.json").exists())
    check("Kanal-Inhalt ist erhalten",
          "Kanal-Gedaechtnis" in (D / "memory_api_audit-test.json").read_text(encoding="utf-8")
          if (D / "memory_api_audit-test.json").exists() else False)
    check("Sentinel __unprivilegiert__ umbenannt",
          (D / "memory_unprivilegiert.json").exists()
          and not (D / "memory___unprivilegiert__.json").exists())
    check("fremde memory.json unangetastet", (D / "memory.json").read_bytes() == fremd_md5)

    # ── Mangel 3: der Praefix-Filter in bekannte_benutzer war ungeprueft.
    # Sein Nutzen ist eine ANZEIGE-Aussage: das Skript nennt die "bekannten
    # Benutzer", und ein kaputter Name darf dort nicht als Benutzer erscheinen.
    kaputt = [u for u in b.benutzer
              if any(u.lower().startswith(p) and len(u) > len(p) for p in b.praefixe)]
    check(f"kein kaputter Name gilt als bekannter Benutzer ({kaputt or 'keiner'})", not kaputt)

    # IDEMPOTENZ
    b2 = mig.finde()
    check(f"zweiter Lauf findet nichts mehr ({len(b2.vorgaenge)} Vorgaenge)", not b2.vorgaenge)
    check(f"nichts unzuordenbar liegengeblieben ({b2.unzuordenbar})", not b2.unzuordenbar)

    print("\n=== 4c. Der ECHT-Fall: alte memory-Form OHNE Punkt-Fassung ===")
    # ⚠ DAS IST DER GEMELDETE FALL, und mein erster Testbestand hat ihn NICHT
    # getroffen: dort lag als Ziel schon `memory_karsten.moeller.json`. Auf
    # ECHT lagen `memory_karsten_moeller.json` (die ALTE Punkt->Unterstrich-
    # Form) UND `memory_nexus_karsten_moeller.json` - und KEINE Punkt-Fassung.
    # Ergebnis am 2026-09-07 live: `karsten_moeller` galt als eigener
    # kanonischer Benutzer, und die Domaenen-Datei landete unter dem
    # Unterstrich-Namen. Der Fehler war verschoben, nicht behoben.
    for f in list(D.glob("memory_*.json")):
        f.unlink()
    (D / "memory_karsten_moeller.json").write_text(json.dumps({
        "aus_unterstrich": {"value": "alte Form", "updated": "2026-05-01T10:00:00"}}),
        encoding="utf-8")
    (D / "memory_nexus_karsten_moeller.json").write_text(json.dumps({
        "aus_domaene": {"value": "Domaenen-Form", "updated": "2026-09-01T10:00:00"}}),
        encoding="utf-8")
    b4 = mig.finde()
    check(f"'karsten_moeller' gilt NICHT als eigener Benutzer ({b4.benutzer})",
          "karsten_moeller" not in b4.benutzer)
    ziele = {v.quelle.name: v.ziel.name for v in b4.vorgaenge if v.ablage == "memory"}
    check(f"beide Fassungen zeigen auf memory_karsten.moeller.json ({ziele})",
          ziele.get("memory_karsten_moeller.json") == "memory_karsten.moeller.json"
          and ziele.get("memory_nexus_karsten_moeller.json") == "memory_karsten.moeller.json")
    mig.anwenden(b4, trocken=False)
    check("keine Unterstrich-Fassung mehr uebrig",
          not (D / "memory_karsten_moeller.json").exists()
          and not (D / "memory_nexus_karsten_moeller.json").exists())
    km = sicher(lambda: json.loads((D / "memory_karsten.moeller.json").read_text(encoding="utf-8")))
    check(f"BEIDE Inhalte sind in der kanonischen Datei ({sorted(km) if isinstance(km, dict) else km})",
          isinstance(km, dict) and set(km) == {"aus_unterstrich", "aus_domaene"})
    check(f"zweiter Lauf findet nichts mehr ({len(mig.finde().vorgaenge)})",
          not mig.finde().vorgaenge)

    print("\n=== 4d. Mehrdeutigkeit ist fail-closed ===")
    # ⚠ AUSGEFUEHRT, nicht im Quelltext gelesen: eine Textsuche nach
    # "mehrdeutig" bleibt gruen, sobald jemand nur die Zuweisung entfernt -
    # genau so blieb die erste Fassung dieser Gegenprobe stumm.
    #
    # Der Fall: ZWEI EXTERN bekannte Namen bilden auf denselben alten
    # Pfadteil ab, haben aber verschiedene Ziele. `_alt_memory` macht aus
    # "max.mueller" UND aus "max_mueller" jeweils "max_mueller", die Ziele
    # sind aber "max.mueller" bzw. "max_mueller". Wer hier "der letzte
    # gewinnt" spielt, legt die Datei eines Menschen unter dem falschen
    # Namen ab - und ein Zusammenfuehren ist nicht rueckholbar.
    for f in list(D.glob("memory_*.json")):
        f.unlink()
    (D / "user_sessions.json").write_text(json.dumps(
        {"users": {"max.mueller": {}, "max_mueller": {}}}), encoding="utf-8")
    (D / "memory_max_mueller.json").write_text(json.dumps(
        {"k": {"value": "wem gehoert das?", "updated": "2026-01-01T00:00:00"}}),
        encoding="utf-8")
    roh_vorher = (D / "memory_max_mueller.json").read_bytes()
    b5 = mig.finde()
    mem5 = [v for v in b5.vorgaenge if v.ablage == "memory"]
    check(f"mehrdeutiger Eintrag steht NICHT in den Vorgaengen "
          f"({[(v.quelle.name, v.ziel.name) for v in mem5]})", not mem5)
    check(f"er wird als mehrdeutig GEMELDET ({b5.unzuordenbar})",
          any("max_mueller" in e and "mehrdeutig" in e for _, e in b5.unzuordenbar))
    mig.anwenden(b5, trocken=False)
    check("die Datei ist unangetastet",
          (D / "memory_max_mueller.json").exists()
          and (D / "memory_max_mueller.json").read_bytes() == roh_vorher)

    # Die ANDERE Mehrdeutigkeit: zwei Kandidaten, zwei VERSCHIEDENE Ziele,
    # und keiner von beiden beansprucht den Eintrag als seinen eigenen.
    # `a.b.c` und `a.b_c` bilden beide auf `a_b_c` ab, ihre Ziele sind aber
    # `a.b.c` bzw. `a.b_c`. Ohne diesen Fall im Bestand blieb die Gegenprobe
    # "der letzte gewinnt" stumm.
    for f in list(D.glob("memory_*.json")):
        f.unlink()
    (D / "user_sessions.json").write_text(json.dumps(
        {"users": {"a.b.c": {}, "a.b_c": {}}}), encoding="utf-8")
    (D / "memory_a_b_c.json").write_text(json.dumps(
        {"k": {"value": "wem?", "updated": "2026-01-01T00:00:00"}}), encoding="utf-8")
    roh2 = (D / "memory_a_b_c.json").read_bytes()
    b6 = mig.finde()
    mem6 = [v for v in b6.vorgaenge if v.ablage == "memory"]
    check(f"zwei verschiedene Ziele -> kein Vorgang "
          f"({[(v.quelle.name, v.ziel.name) for v in mem6]})", not mem6)
    check(f"als mehrdeutig gemeldet ({b6.unzuordenbar})",
          any("a_b_c" in e and "mehrdeutig" in e for _, e in b6.unzuordenbar))
    mig.anwenden(b6, trocken=False)
    check("Datei unangetastet", (D / "memory_a_b_c.json").exists()
          and (D / "memory_a_b_c.json").read_bytes() == roh2)

    print("\n=== 4b. Doppelte dict-Schluessel ===")
    (D / "issues_admin_seen.json").write_text(json.dumps({
        "nexus\\andreas.bender": "2026-09-05T00:00:00",
        "andreas.bender": "2026-01-01T00:00:00",
        "jonas.reichelt": "2026-03-01T00:00:00"}), encoding="utf-8")
    # Sperren duerfen NICHT angefasst werden (Entscheidung 2026-08-10).
    sperren = {"violations": {"nexus\\andreas.bender": [{"x": 1}]},
               "blocked": {"nexus\\andreas.bender": {"bis": 1}}}
    (D / "security_state.json").write_text(json.dumps(sperren), encoding="utf-8")
    sperren_vorher = (D / "security_state.json").read_bytes()

    seen_vorher = (D / "issues_admin_seen.json").read_bytes()
    m = mig.schluessel_aufraeumen(trocken=True)
    check(f"doppelter Schluessel erkannt ({m})", any("andreas.bender" in x for x in m))
    # Ueber die BYTES, nicht ueber eine Textsuche: ein Backslash im JSON-Text
    # ist doppelt escaped, und ein Suchausdruck darauf ist eine Fehlerquelle
    # ohne Gegenwert (erste Fassung schlug genau daran fehl).
    check("Trockenlauf laesst die Datei unangetastet",
          (D / "issues_admin_seen.json").read_bytes() == seen_vorher)
    # Nie ungeprueft: eine Pruefung darf nicht WERFEN, sonst bricht der Lauf
    # ohne Bilanz ab und ist von "nicht gelaufen" nicht zu unterscheiden.
    r = sicher(mig.schluessel_aufraeumen, trocken=False)
    check(f"schluessel_aufraeumen wirft nicht ({r if isinstance(r, str) else 'ok'})",
          not isinstance(r, str))
    d = sicher(lambda: json.loads((D / "issues_admin_seen.json").read_text(encoding="utf-8")))
    check(f"Domaenen-Schluessel ist weg ({sorted(d) if isinstance(d, dict) else d})",
          isinstance(d, dict) and "nexus\\andreas.bender" not in d)
    check("kanonischer Schluessel ist da", isinstance(d, dict) and "andreas.bender" in d)
    # Der AELTERE Marker gewinnt: mit dem neueren verpasst der Admin Meldungen.
    check(f"aelterer Marker bleibt ({d.get('andreas.bender') if isinstance(d, dict) else '?'})",
          isinstance(d, dict) and d.get("andreas.bender") == "2026-01-01T00:00:00")
    check("fremder Schluessel unangetastet",
          isinstance(d, dict) and d.get("jonas.reichelt") == "2026-03-01T00:00:00")
    check("⚠ security_state.json (Sperren) NICHT angefasst",
          (D / "security_state.json").read_bytes() == sperren_vorher)
    check("security_state steht nicht in SCHLUESSEL_DATEIEN",
          not any("security_state" in n for n, _ in mig.SCHLUESSEL_DATEIEN))

    print("\n=== 5. Unzuordenbares wird GEMELDET, nicht geraten ===")
    (D / "memory_voelligUnbekannt_X.json").write_text("{}", encoding="utf-8")
    b3 = mig.finde()
    check("unbekannter Eintrag wird als unzuordenbar gemeldet",
          any(e == "voelligUnbekannt_X" for _, e in b3.unzuordenbar))
    check("unbekannter Eintrag wird NICHT angefasst", not b3.vorgaenge)
finally:
    shutil.rmtree(sandkasten, ignore_errors=True)

print(f"\n{OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
