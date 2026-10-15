#!/usr/bin/env python3
"""/chat: ein angehaengtes Bild muss nach F5 wieder erscheinen.

GEMELDET 2026-09-27: nach dem Neuladen stand in der Frage nur noch
"mach deutsch daraus [🖼️ image.png]" – das Bild war weg. Der Verlauf speichert
bewusst kein base64; er wusste aber auch nicht, WO das Bild liegt, obwohl
`_anhang_ablegen` es laengst dauerhaft in data/documents abgelegt hatte.

Die Kette, die hier AUSGEFUEHRT (nicht gelesen) wird:
  1. `_bild_als_datei(..., ablage=[])` meldet den Ablagenamen heraus.
  2. Der WS-Handler schickt ihn als `attachments_stored` an /chat zurueck
     (Syntaxbaum: Aufruf mit `ablage=`, Ereignis traegt die gesammelte Liste).
  3. `_onAttachmentsStored` (chat.js) haengt ihn an den Verlaufseintrag – aber
     nur, solange der Eintrag noch im offenen Verlauf steht.
  4. `_addHistoryBubble` zeigt das Bild statt des Hinweises.
  5. `GET /api/chat/attachment/{name}` liefert es aus – nur dem Eigentuemer,
     nur Rastergrafik.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
`CBV_ROOT` zeigt auf einen anderen Baum (Gegenprobe arbeitet auf einer Kopie).
"""
import ast
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CBV_ROOT") or Path(__file__).resolve().parent.parent)
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
CHATJS = ROOT / "frontend" / "js" / "chat.js"

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f" – {detail}"))


def abbruch(grund):
    print(f"ABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


BAUM = ast.parse(MAIN)
FUNK = {k.name: k for k in ast.walk(BAUM)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))}
for n in ("_anhang_ablegen", "_bild_als_datei", "get_chat_attachment",
          "_anhang_dateiname", "_bild_mime_aus_kopf", "_bild_mime_aus_bytes"):
    if n not in FUNK:
        abbruch(f"Funktion {n} fehlt in main.py")

PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# ─────────────────────────────────────────────────────────────────────────
print("1. _bild_als_datei meldet den Ablagenamen heraus")
sk = Path(tempfile.mkdtemp(prefix="cbv_"))
try:
    (sk / "backend").mkdir()
    (sk / "data").mkdir()

    class _Doc:
        @staticmethod
        def register_upload(name, benutzer):
            return True

    class _Lauf:
        @staticmethod
        def anhang_ziel(benutzer, sicher):
            (sk / "arb").mkdir(exist_ok=True)
            return sk / "arb" / ("anhang_0123456789ab_" + sicher)

    sys.modules["backend.lauf_tmp"] = _Lauf
    ns = {"Path": Path, "os": os, "print": lambda *a, **k: None, "_documents": _Doc,
          "_anhang_merken": lambda *a, **k: None, "__file__": str(sk / "backend" / "main.py")}
    quelle = "\n\n".join(ast.get_source_segment(MAIN, FUNK[n])
                         for n in ("_anhang_dateiname", "_anhang_ablegen", "_bild_als_datei"))
    exec(compile(quelle, "<kette>", "exec"), ns)
    abl = []
    h = ns["_bild_als_datei"](base64.b64encode(PNG_1x1).decode(), "image.png",
                              "m.mustermann", "sid-1", None, ablage=abl)
    docs = sorted(p.name for p in (sk / "data" / "documents").glob("*"))
    check("Positivkontrolle: Hinweis und Ablage entstanden", bool(h) and len(docs) == 1,
          f"hinweis={bool(h)} docs={docs}")
    check("Ablagename kommt heraus und IST die abgelegte Datei", abl == docs, f"{abl} vs {docs}")
    abl2 = []
    ns["_bild_als_datei"]("!!!kein base64!!!", "x.png", "a", "sid", None, ablage=abl2)
    check("gescheiterte Ablage meldet keinen Namen", abl2 == [], str(abl2))
    check("ohne ablage= weiter aufrufbar (alte Aufrufer)",
          isinstance(ns["_bild_als_datei"](base64.b64encode(PNG_1x1).decode(), "y.png",
                                           "a", "sid", None), str))
finally:
    shutil.rmtree(sk, ignore_errors=True)
    sys.modules.pop("backend.lauf_tmp", None)

# ─────────────────────────────────────────────────────────────────────────
print("2. WS-Handler schickt die Ablage an /chat zurueck (Syntaxbaum)")
aufrufe = [k for k in ast.walk(BAUM) if isinstance(k, ast.Call)
           and isinstance(k.func, ast.Name) and k.func.id == "_bild_als_datei"]
check("Positivkontrolle: Aufruf von _bild_als_datei gefunden", len(aufrufe) >= 1)
mit_abl = [k for k in aufrufe if any(kw.arg == "ablage" for kw in k.keywords)]
check("Aufruf reicht ablage= herein", len(mit_abl) >= 1)
abl_namen = {kw.value.id for k in mit_abl for kw in k.keywords
             if kw.arg == "ablage" and isinstance(kw.value, ast.Name)}


def _ereignis_listen():
    """Name der Liste, die das Ereignis attachments_stored als items traegt."""
    for k in ast.walk(BAUM):
        if isinstance(k, ast.Dict):
            d = {getattr(a, "value", None): b for a, b in zip(k.keys, k.values)}
            t = d.get("type")
            if isinstance(t, ast.Constant) and t.value == "attachments_stored":
                it = d.get("items")
                yield it.id if isinstance(it, ast.Name) else None


ereignis = list(_ereignis_listen())
check("Ereignis attachments_stored existiert", len(ereignis) == 1, str(ereignis))
# Die Liste im Ereignis muss aus der ablage= befuellt werden: .append auf sie
# in derselben Funktion, in der ein Name aus abl_namen gelesen wird.
befuellt = False
for f in FUNK.values():
    seg = [k for k in ast.walk(f)]
    appends = {k.func.value.id for k in seg if isinstance(k, ast.Call)
               and isinstance(k.func, ast.Attribute) and k.func.attr == "append"
               and isinstance(k.func.value, ast.Name)}
    gelesen = {k.id for k in seg if isinstance(k, ast.Name)}
    if ereignis and ereignis[0] in appends and abl_namen & gelesen and \
            any(isinstance(k, ast.Call) and getattr(k.func, "id", "") == "_bild_als_datei" for k in seg):
        befuellt = True
check("Ereignis-Liste wird aus der Ablage befuellt", befuellt)

# ─────────────────────────────────────────────────────────────────────────
print("3. GET /api/chat/attachment/{name}: nur Eigentuemer, nur Rastergrafik")
sk = Path(tempfile.mkdtemp(prefix="cbv_ep_"))
try:
    (sk / "backend").mkdir()
    docs = sk / "data" / "documents"
    docs.mkdir(parents=True)
    for n in ("image.png", "boese.svg", "seite.html"):
        (docs / n).write_bytes(PNG_1x1)
    # ⚠ Code-Review 2026-09-28: ein Umlaut-Name wurde abgelegt, aber nicht
    # ausgeliefert (400) - das Bild verschwand nach F5. Und der TYP kommt aus
    # dem INHALT: echtes SVG/HTML bleibt draussen, auch unter .png-Namen.
    JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
    (docs / "Übersicht.png").write_bytes(PNG_1x1)
    (docs / "foto.jfif").write_bytes(JPG)
    (docs / "FOTO.JPG").write_bytes(JPG)
    (docs / "echt.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>')
    (docs / "tarn.png").write_bytes(b"<html><script>alert(1)</script></html>")
    EIGNER = {n: "m.mustermann" for n in ("image.png", "boese.svg", "seite.html",
              "Übersicht.png", "foto.jfif", "FOTO.JPG", "echt.svg", "tarn.png")}

    class _D:
        @staticmethod
        def may_access(name, user, admin=False):
            return admin or EIGNER.get(name) == user

    class _JSON:
        def __init__(self, inhalt, status_code=200):
            self.status_code = status_code

    class _File:
        def __init__(self, pfad, media_type=None, **kw):
            self.status_code, self.pfad, self.media_type = 200, pfad, media_type
            self.headers = kw.get("headers") or {}

    fn = FUNK["get_chat_attachment"]
    fn.decorator_list = []
    _magic = next((ast.get_source_segment(MAIN, k) for k in BAUM.body if isinstance(k, ast.Assign)
                   and any(getattr(t, "id", "") == "_ANHANG_BILD_MAGIC" for t in k.targets)), None)
    if not _magic:
        abbruch("_ANHANG_BILD_MAGIC fehlt in main.py")
    # Die Helfer kommen MIT - sie sind die geteilte Regel, keine Attrappe.
    src = "\n\n".join([_magic] + [ast.get_source_segment(MAIN, FUNK[n]) for n in
                                   ("_bild_mime_aus_kopf", "_anhang_dateiname")] + [ast.unparse(fn)])
    ns = {"Path": Path, "JSONResponse": _JSON, "FileResponse": _File, "_documents": _D,
          "_is_admin_user": lambda u: u == "admin", "Depends": lambda f: None,
          "require_auth_or_query": None, "__file__": str(sk / "backend" / "main.py"),
          "os": os}
    exec(compile(src, "<endpunkt>", "exec"), ns)

    def ruf(name, user):
        return asyncio.run(ns["get_chat_attachment"](name, user))

    r = ruf("image.png", "m.mustermann")
    check("Positivkontrolle: Eigentuemer bekommt sein Bild",
          r.status_code == 200 and getattr(r, "media_type", "") == "image/png",
          f"{r.status_code}")
    check("nosniff gesetzt", getattr(r, "headers", {}).get("X-Content-Type-Options") == "nosniff")
    check("fremder Benutzer: 404", ruf("image.png", "fremd").status_code == 404)
    check("Admin darf", ruf("image.png", "admin").status_code == 200)
    check("fehlende Datei: 404", ruf("weg.png", "m.mustermann").status_code == 404)
    # Der Typ kommt aus dem INHALT: PNG-Bytes unter .svg gehen als image/png raus -
    # nie als SVG. Echtes SVG/HTML wird abgewiesen, auch unter .png-Namen.
    _r = ruf("boese.svg", "m.mustermann")
    check("PNG-Inhalt unter .svg: als image/png, nie als SVG",
          _r.status_code == 200 and getattr(_r, "media_type", "") == "image/png", str(_r.status_code))
    check("⚠ echtes SVG wird nicht ausgeliefert", ruf("echt.svg", "m.mustermann").status_code == 400)
    check("⚠ HTML unter .png-Namen wird nicht ausgeliefert",
          ruf("tarn.png", "m.mustermann").status_code == 400)
    check("HTML-Endung mit PNG-Inhalt: als image/png",
          getattr(ruf("seite.html", "m.mustermann"), "media_type", "") == "image/png")
    _r = ruf("Übersicht.png", "m.mustermann")
    check("⚠ Umlaut-Name wird ausgeliefert (vorher 400)", _r.status_code == 200, str(_r.status_code))
    _r = ruf("foto.jfif", "m.mustermann")
    check("⚠ .jfif wird als JPEG ausgeliefert (vorher 400)",
          _r.status_code == 200 and getattr(_r, "media_type", "") == "image/jpeg", str(_r.status_code))
    check("Endung in Grossbuchstaben", ruf("FOTO.JPG", "m.mustermann").status_code == 200)
    check("⚠ fremdes Umlaut-Bild bleibt 404", ruf("Übersicht.png", "fremd").status_code == 404)
    for _boes in ("a b.png", "a/b.png", "a\\b.png", "_x.png", "x.png\n", ".versteckt.png", "", "a" * 256 + ".png"):
        check(f"kein Fixpunkt der Ablageregel abgewiesen: {_boes[:20]!r}",
              ruf(_boes, "m.mustermann").status_code == 400)
    check("Pfadversuch abgewiesen", ruf("../documents/image.png", "m.mustermann").status_code == 400)
    check("Punkt-Anfang abgewiesen", ruf("..png", "m.mustermann").status_code == 400)
finally:
    shutil.rmtree(sk, ignore_errors=True)

def _ruft(fname, ziel):
    return any(isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == ziel
               for k in ast.walk(FUNK[fname]))
check("Ablage und Auslieferung teilen _anhang_dateiname (keine zweite Fassung)",
      _ruft("_anhang_ablegen", "_anhang_dateiname") and _ruft("get_chat_attachment", "_anhang_dateiname"))
check("Upload und Auslieferung teilen _bild_mime_aus_kopf",
      _ruft("_bild_mime_aus_bytes", "_bild_mime_aus_kopf") and _ruft("get_chat_attachment", "_bild_mime_aus_kopf"))

# ─────────────────────────────────────────────────────────────────────────
print("4. Frontend (jsdom): Rueckmeldung speichern, Verlauf zeigt das Bild")
NODE = r"""
const fs = require('fs');
let JSDOM = null;
for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom', '/usr/share/nodejs/jsdom']) {
    if (!k) continue; try { JSDOM = require(k).JSDOM; break; } catch (e) {}
}
// Das Skript liegt im Temp-Verzeichnis – aufgeloest wird relativ zum Repo.
if (!JSDOM) { try { JSDOM = require(require.resolve('jsdom', {paths: [process.argv[3]]})).JSDOM; } catch (e) {} }
if (!JSDOM) { console.log(JSON.stringify({abbruch: 'jsdom fehlt'})); process.exit(0); }
const SRC = fs.readFileSync(process.argv[2], 'utf8');
/* icons.js NEBEN chat.js aufloesen, nicht aus argv[3]: argv[3] ist die echte
   Repo-Wurzel (dort liegt node_modules fuer jsdom), waehrend chat.js ueber
   CBV_ROOT aus einer KOPIE kommen kann - die Gegenprobe arbeitet auf einer.
   Aus argv[3] gelesen wuerde eine Sabotage an icons.js in der Kopie nicht
   gesehen, und die Gegenprobe waere stumm aus dem falschen Grund. */
const ICONS = require('path').join(require('path').dirname(process.argv[2]), 'icons.js');
let ICONS_SRC = null;
try { ICONS_SRC = fs.readFileSync(ICONS, 'utf8'); } catch (e) {
    // Den PFAD nennen: ein falscher Abbruchgrund sieht wie ein geklaerter
    // Fall aus und wird nicht nachgeprueft.
    console.log(JSON.stringify({abbruch: 'icons.js nicht lesbar: ' + ICONS}));
    process.exit(0);
}
function schneide(name) {
    const m = SRC.match(new RegExp('function\\s+' + name + '\\s*\\('));
    if (!m) return '';
    const i = SRC.indexOf('{', m.index + m[0].length - 1);
    let t = 0;
    for (let j = i; j < SRC.length; j++) {
        if (SRC[j] === '{') t++;
        else if (SRC[j] === '}') { t--; if (t === 0) return SRC.slice(m.index, j + 1); }
    }
    return '';
}
const teile = ['_dataUrl', '_renderAttachments', '_addHistoryBubble', '_onAttachmentsStored'].map(schneide);
if (teile.some(x => !x)) { console.log(JSON.stringify({abbruch: 'Schnitt leer'})); process.exit(0); }
const dom = new JSDOM('<!doctype html><body><div id="m"></div></body>', {url: 'https://h/chat', runScripts: 'outside-only'});
const w = dom.window;
/* Das ECHTE icons.js laden, NIE eine Teil-Attrappe: ein von Hand gestelltes
   JarvisIcons = { trash: ... } stirbt beim naechsten Symbol, und zwar
   reihenweise - am 2026-10-06 brachen fuenf Pruefstaende auf einmal, als
   JarvisIcons.pencil/setPencil dazukam. Dieser hier war der SECHSTE Fall und
   fiel nur spaeter auf, weil er in einer .py-Datei steckt: der Sweep, der die
   30 JS-Waechter auf die gemeinsame Quelle gezogen hat, sah ihn nicht.
   icons.js ist eine IIFE und setzt window.JarvisIcons; die geschnittenen
   Renderer laufen unten per w.eval ebenfalls im FENSTER-Scope, der blosse
   Name JarvisIcons wird dort also aufgeloest (ein global.JarvisIcons waere
   nur noetig, wenn der Renderer im NODE-Scope liefe). */
w.eval(ICONS_SRC);
// Positivkontrolle VOR den Messungen: ohne JarvisIcons ist jede Pruefung
// unten trivial - der Renderer wuerde im ReferenceError enden.
if (!w.JarvisIcons || typeof w.JarvisIcons !== 'object') {
    console.log(JSON.stringify({abbruch: 'icons.js geladen, aber window.JarvisIcons fehlt: ' + ICONS}));
    process.exit(0);
}
w.eval(`
  var messagesEl = document.getElementById('m');
  var escapeHtml = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
  var renderMarkdown = s => s;
  var _makeRetryBtn = () => document.createElement('button');
  var _editUserBubble = () => {}; var _botActions = () => document.createElement('div');
  var _buildBubbleCtxItems = () => []; var openLightbox = () => {}; var showCtxMenu = () => {};
  var addLongPress = () => {}; var _renderFileChip = () => document.createElement('div');
  window.t = k => k;
  window.JarvisDL = { url: u => u + '?token=JDL1.x' };
  var _chatHistory = []; var saves = 0, persists = 0;
  var _saveHistory = () => { saves++; }; var _persistSession = () => { persists++; };
  var _attRefs = new Map();
` + teile.join('\n'));
/* Ab hier laeuft PRODUKTIVCODE aus chat.js. Wirft er, ist das KEIN Befund,
   sondern "konnte nicht laufen" - und der Grund muss in EINER Zeile lesbar
   sein. Vorher endete so ein Wurf als abgeschnittenes Stack-Ende
   ("node lieferte nichts Lesbares:  s/loader:1613:10)"); die Ursache
   (ReferenceError: JarvisIcons is not defined) war nur zu finden, indem man
   das eingebettete Skript aus dieser Datei herausloest und von Hand startet.
   Genau das soll beim naechsten neuen Symbol nicht noch einmal noetig sein. */
function messe(was, fn) {
    try { return fn(); } catch (e) {
        console.log(JSON.stringify({abbruch: 'Produktivcode wirft bei ' + was + ': ' +
                                              (e && e.message ? e.message : String(e))}));
        process.exit(0);
    }
}
const r = {};
messe('_onAttachmentsStored', () => w.eval(`
  var e1 = { role: 'user', text: 'mach deutsch daraus [🖼️ image.png]', att_note: ' [🖼️ image.png]', att_count: 1 };
  _chatHistory.push(e1); _attRefs.set('r1', e1);
  _onAttachmentsStored({ att_ref: 'r1', items: [{ name: 'image.png', mime_type: 'image/png', doc: 'image.png' }] });
  var e2 = { role: 'user', text: 'x [🖼️ b.png]', att_note: ' [🖼️ b.png]', att_count: 1 };
  _attRefs.set('r2', e2);   // steht NICHT (mehr) im Verlauf -> andere Sitzung
  _onAttachmentsStored({ att_ref: 'r2', items: [{ name: 'b.png', mime_type: 'image/png', doc: 'b.png' }] });
`));
r.gespeichert = w.eval('JSON.stringify(e1.attachments || null)');
r.persists = w.eval('persists');
r.fremd = w.eval('e2.attachments === undefined');
messe('_addHistoryBubble', () => w.eval(`_addHistoryBubble(e1);`));
const row1 = w.document.querySelectorAll('.msg-row')[0];
const img = row1 && row1.querySelector('img');
r.src = img ? img.getAttribute('src') : null;
r.text1 = row1 ? row1.querySelector('.msg-bubble').textContent : null;
r.raw1 = row1 ? row1.dataset.rawText : null;
// Altbestand ohne Verweis: unveraendert Text mit Hinweis, kein Bild
messe('_addHistoryBubble (Altbestand)', () => w.eval(`_addHistoryBubble({ role: 'user', text: 'alt [🖼️ a.png]' });`));
const row2 = w.document.querySelectorAll('.msg-row')[1];
r.alt_img = !!row2.querySelector('img');
r.alt_text = row2.querySelector('.msg-bubble').textContent;
// Nicht alle Anhaenge mit Verweis (Bild + PDF): Hinweis bleibt stehen
messe('_addHistoryBubble (teilweise)', () => w.eval(`_addHistoryBubble({ role: 'user', text: 'z [🖼️ a.png, 📄 b.pdf]', att_note: ' [🖼️ a.png, 📄 b.pdf]', att_count: 2,
                            attachments: [{ name: 'a.png', mime_type: 'image/png', doc: 'a.png' }] });`));
const row3 = w.document.querySelectorAll('.msg-row')[2];
r.teil_text = row3.querySelector('.msg-bubble').textContent;
// Ablage abgelaufen: Bild-Fehler -> Hinweis kommt zurueck
if (img) img.dispatchEvent(new w.Event('error'));
r.nach_fehler = row1.querySelector('.msg-bubble').textContent;
r.nach_fehler_img = !!row1.querySelector('img');
console.log(JSON.stringify(r));
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
    fh.write(NODE)
    js = fh.name
try:
    out = subprocess.run(["node", js, str(CHATJS), str(Path(__file__).resolve().parent.parent)], capture_output=True, text=True, timeout=60)
finally:
    os.unlink(js)
def _node_fehler(stderr):
    """Die AUSSAGEKRAEFTIGE Zeile aus einem Node-Stacktrace.

    Die LETZTE Zeile ist die schlechteste Wahl - dort steht
    "Node.js v20.19.2", und davor nur Rahmen ("at Module._load ..."). Der
    Grund steht in der Zeile "<Name>Error: <Text>". Ohne diese Auswahl las
    der Abbruchgrund am 2026-10-11 woertlich "node lieferte nichts Lesbares:
    s/loader:1613:10)" - richtig und vollkommen nutzlos.
    """
    zeilen = [z.strip() for z in (stderr or "").splitlines() if z.strip()]
    for z in zeilen:
        # "ReferenceError: x is not defined", "TypeError: ...", auch
        # "Uncaught SyntaxError: ..." - aber nicht die "at ..."-Rahmenzeilen.
        if not z.startswith("at ") and "Error: " in z:
            return z
    return " | ".join(zeilen[:3]) if zeilen else "(stderr leer)"


try:
    r = json.loads(out.stdout.strip().splitlines()[-1])
except Exception:  # noqa: BLE001
    abbruch(f"node lieferte nichts Lesbares: {_node_fehler(out.stderr)} "
            f"[rc={out.returncode}, stdout={out.stdout[-200:]!r}]")
if r.get("abbruch"):
    abbruch(r["abbruch"])
check("Verlaufs-Bubble zeigt das Bild", r.get("src") is not None, str(r))
check("Rueckmeldung landet am Verlaufseintrag",
      r.get("gespeichert") == json.dumps([{"name": "image.png", "mime_type": "image/png",
                                            "doc": "image.png"}], separators=(",", ":")),
      str(r.get("gespeichert")))
check("... und wird genau einmal gespeichert", r.get("persists") == 1, str(r.get("persists")))
check("Eintrag einer anderen Sitzung wird NICHT beschrieben", r.get("fremd") is True)
check("Bild-Adresse = Endpunkt + Abruf-Schluessel",
      r.get("src") == "/api/chat/attachment/image.png?token=JDL1.x", str(r.get("src")))
check("Hinweis '[🖼️ image.png]' verschwindet, Frage bleibt",
      r.get("text1") == "mach deutsch daraus", repr(r.get("text1")))
check("Wiederholen/Bearbeiten nimmt die Frage ohne Hinweis",
      r.get("raw1") == "mach deutsch daraus", repr(r.get("raw1")))
check("Altbestand ohne Verweis unveraendert",
      not r.get("alt_img") and r.get("alt_text") == "alt [🖼️ a.png]", str(r))
check("teilweise Verweise: Hinweis bleibt vollstaendig",
      (r.get("teil_text") or "").startswith("z [🖼️ a.png, 📄 b.pdf]"), repr(r.get("teil_text")))
check("totes Bild: Hinweis kommt zurueck",
      r.get("nach_fehler") == "mach deutsch daraus [🖼️ image.png]" and not r.get("nach_fehler_img"),
      repr(r.get("nach_fehler")))

ok = sum(res)
print(f"\nErgebnis: {ok}/{len(res)}")
sys.exit(0 if ok == len(res) else 1)
