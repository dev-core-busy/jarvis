#!/usr/bin/env python3
"""Optische Abnahme SQL-Assistent im ECHTEN Chrome: Seite /sql, Reiter, Chat-Auswahl.

jsdom rechnet kein Layout – Ueberlappung, Ueberlauf und Kontrast sieht nur ein
echter Browser. Geprueft in HELL und DUNKEL, dazu schmal (520 px).

Echte ``sql.html`` / echtes Panel aus ``settings.html`` mit echtem CSS, echtem
``i18n.js`` und echtem ``sql.js``/``sql_admin.js``; die Serverantworten kommen
aus einer Attrappe (die Probe legt nichts im Bestand an).

KONTRAST wird gegen die WIRKLICHE Flaeche gerechnet: halbtransparente
Hintergruende der Vorfahren werden bis zur ersten deckenden Flaeche
zusammengesetzt (ein durchscheinendes rgba ist kein Hintergrund, Register).
Chrome meldet color-mix als ``color(srgb 0..1)`` – beide Formen werden gelesen.

Aufruf auf DEV (Chrome vorhanden):  venv/bin/python tests/live_sql_ui_dev.py
Bilder landen in ~/sql_ui_*.png (HOME, nicht ein fester /tmp-Pfad – Register).
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "frontend"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:240]) if detail else ""))


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


BOESE = '<img src=x onerror="window.__xss=1">'
STUB = """
<script>
localStorage.setItem('jarvis_token','T');
(function(){
  var B = %s;
  var ANT = {
    '/api/me': {username:'m.mustermann', is_admin:true, permissions:{schema:true}},
    '/api/sql/status': {ok:true, vorhanden:true, stand:'2026-11-07 10:00:00', dialekt:'postgresql', frage_max:2000,
      schemata:[{id:'erp', name:'ERP-Datenbank mit einem recht langen Namen', tabellen:1234, sichten:12, spalten:45678},
               {id:'lager', name:'Lager', tabellen:88, sichten:0, spalten:900}]},
    '/api/sql/frage': {ok:true, dialekt:'postgresql',
      sql:'SELECT l.lndbez AS land, SUM(p.netwr) AS nettoumsatz\\nFROM vk.vbpos p\\nJOIN vk.vbkopf k ON k.vbeln = p.vbeln\\nJOIN stm.kdst c ON c.kdnr = k.kdnr\\nJOIN stm.lnd l ON l.lnd = c.lnd\\nWHERE k.audat >= DATE \\'2025-01-01\\' AND k.audat < DATE \\'2026-01-01\\'\\nGROUP BY l.lndbez\\nORDER BY nettoumsatz DESC;',
      erklaerung:'Summiert den Nettowert aller Auftragspositionen des Jahres 2025 je Land des Kunden.',
      annahmen:'- Der Umsatz ist der Nettowert der Positionen (vbpos.netwr).',
      pruefung:{ok:true, fehler:[], tabellen:['vk.vbpos','vk.vbkopf','stm.kdst','stm.lnd'], spalten_geprueft:9},
      tabellen_kontext:['vk.vbpos','vk.vbkopf','stm.kdst','stm.lnd','vs.lfkopf_mit_einem_sehr_langen_tabellennamen_ohne_umbruch'],
      verbinder:['vk.vbkopf'], unverbunden:[], runden:1, begriffe_quelle:'modell'},
    '/api/sql/suche': {ok:true, treffer:[{name:'stm.kdst', art:'tabelle', spalten_n:4, bereich:'kunde, auftrag', kommentar:'Kundenstamm (Debitoren) '+B},
                                         {name:'vk.vbkopf', art:'tabelle', spalten_n:5, bereich:null, kommentar:'Verkaufsbeleg Kopf'}]},
    '/api/sql/tabelle': {ok:true, tabelle:{name:'stm.kdst', art:'tabelle', kommentar:'Kundenstamm (Debitoren)', bereich:'kunde',
      spalten_gesamt:240, spalten:[{name:'kdnr', typ:'integer', pk:true, nullable:false, kommentar:''},
        {name:'kdname', typ:'varchar(120)', pk:false, nullable:false, kommentar:'Name des Kunden, so wie er auf Rechnungen erscheint'},
        {name:'lnd', typ:'char(2)', pk:false, nullable:true, kommentar:'Laenderschluessel ISO'}],
      raus_gesamt:1, raus:[{ziel:'stm.lnd', art:'fk', paare:[['lnd','lnd']]}], rein_gesamt:1, rein:[{quelle:'vk.vbkopf', art:'fk', paare:[['kdnr','kdnr']]}]}},
    '/api/sql/admin': {ok:true, skill_aktiv:true,
      cfg:{schemata:[{id:'erp', name:'ERP-Datenbank mit einem recht langen Namen fuer die Kopfzeile'}, {id:'hr', name:'Personal'}],
           dialekt:'postgresql', dateimuster:'*.sql,*.ddl', prozesse:0, fk_ableiten:true, max_tabellen:12, max_spalten:40, index_aus_chat:false},
      graph:{vorhanden:true, stand:'2026-11-07 10:00:00', schemata:[{id:'erp', name:'ERP', tabellen:1234, sichten:12, spalten:45678}]},
      dateien:{erp:{dateien:8000, ordner:120, bytes:90e9}, hr:{dateien:0, ordner:0, bytes:0}},
      erfassung:{laeuft:true, phase:'Dateien zerlegen', dateien_fertig:3100, dateien_neu:8000, bytes_fertig:40e9, bytes_neu:90e9, mb_pro_s:212.4, rest_s:1500,
                 fehler:['Datei unlesbar: erp/archiv/kaputt.sql']}},
    '/api/sql/admin/schema/erp/dateien': {ok:true, gekappt:true, gesamt:8120, dateien:8000, ordner:120, bytes:90e9, eintraege:[
      {pfad:'archiv', art:'ordner', groesse:0},
      {pfad:'archiv/2019_bis_2024_ein_sehr_langer_dateiname_ohne_jede_moeglichkeit_zum_umbrechen_der_zeile_schema_dump.sql', art:'datei', groesse:4.2e9},
      {pfad:'stamm', art:'ordner', groesse:0}, {pfad:'stamm/kunde.sql', art:'datei', groesse:12000}]},
    '/api/sql/admin/index': {ok:true, hier:true, erfassung:{laeuft:true, phase:'Dateien zerlegen', dateien_fertig:3100, dateien_neu:8000, bytes_fertig:40e9, bytes_neu:90e9}}
  };
  window.fetch = function(u, o){
    var p = String(u).split('?')[0], d = ANT[p] || {ok:true};
    return Promise.resolve({ok:true, status:200, json:function(){return Promise.resolve(JSON.parse(JSON.stringify(d)));},
                            text:function(){return Promise.resolve(JSON.stringify(d));}});
  };
  window.JarvisSitzung = window.JarvisSitzung || null;
})();
</script>
""" % json.dumps(BOESE)

TMP = tempfile.mkdtemp(prefix="sqlui_", dir=str(Path.home()))
shutil.copytree(ROOT, os.path.join(TMP, "static"), dirs_exist_ok=True)
seite = (ROOT / "sql.html").read_text(encoding="utf-8")
seite = seite.replace("</head>", STUB + "</head>")
seite = seite.replace('src="/static/', 'src="static/').replace('href="/static/', 'href="static/')
open(os.path.join(TMP, "sql.html"), "w", encoding="utf-8").write(seite)

settings = (ROOT / "settings.html").read_text(encoding="utf-8")
I18N_V = re.search(r"i18n\.js\?v=(\d+)", settings).group(1)
a, b = settings.find('<div id="settings-tab-sql"'), settings.find('<div id="settings-tab-tracks"')
# ⚠ `.settings-tab-content` ist nur mit `.active` sichtbar (setzt app.js) –
# ohne die Klasse mass die erste Fassung unsichtbaren Inhalt (Bild: leerer Kasten).
panel = settings[a:b].replace('class="settings-tab-content" style="display:none;">',
                              'class="settings-tab-content active" style="">', 1)
kopf = settings[:settings.find("</head>")]
links = "\n".join(z for z in kopf.splitlines() if 'rel="stylesheet"' in z)
reiter = ("<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"UTF-8\">" + links + STUB
          + "</head><body><script src=\"/static/js/theme_frueh.js?v=1\"></script>"
          + "<div class=\"modal-card\" style=\"max-width:980px;margin:20px auto;padding:20px;\">" + panel + "</div>"
          + "<script src=\"/static/js/sitzung.js?v=3\"></script><script src=\"/static/js/icons.js?v=11\"></script>"
          + "<script src=\"/static/js/i18n.js?v=" + I18N_V + "\"></script><script src=\"/static/js/sql_admin.js?v=1\"></script>"
          + "<script>setTimeout(function(){ window.SqlAdmin.onShow(); }, 300);</script></body></html>")
reiter = reiter.replace('src="/static/', 'src="static/').replace('href="/static/', 'href="static/')
open(os.path.join(TMP, "reiter.html"), "w", encoding="utf-8").write(reiter)

chathtml = (ROOT / "chat.html").read_text(encoding="utf-8")
theme_v = re.search(r"theme\.css\?v=(\d+)", chathtml).group(1)
chatfilter = ("<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"UTF-8\">"
              "<link rel=\"stylesheet\" href=\"static/css/theme.css?v=" + theme_v + "\">" + STUB
              + "</head><body style=\"margin:0\"><div style=\"position:fixed;left:0;right:0;bottom:0;padding:10px;"
              "background:var(--bg-secondary)\"><div style=\"margin-bottom:6px\">Verlauf darueber …</div>"
              "<div id=\"kb-filter-slot\" style=\"padding:0 10px 4px;display:flex;gap:8px\"></div>"
              "<textarea style=\"width:100%\">Eingabe</textarea></div>"
              "<script src=\"static/js/sitzung.js?v=3\"></script><script src=\"static/js/i18n.js?v=" + I18N_V + "\"></script>"
              "<script src=\"static/js/sqlschemafilter.js?v=1\"></script>"
              "<script>window.F = SqlSchemaFilter.mount({anchor: document.getElementById('kb-filter-slot'), direction: 'up'});</script>"
              "</body></html>")
open(os.path.join(TMP, "chatfilter.html"), "w", encoding="utf-8").write(chatfilter)

PORT = freier_port()
srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "-d", TMP],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)
PROFIL = tempfile.mkdtemp(prefix="chromeprof_", dir=str(Path.home()))
CDP = freier_port()
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-allow-origins=*",
     "--remote-debugging-port=%d" % CDP, "--user-data-dir=" + PROFIL, "--window-size=1280,900",
     "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(3.0)


def aufraeumen():
    try:
        chrome.kill()
        srv.kill()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        shutil.rmtree(PROFIL, ignore_errors=True)


try:
    import websocket
except ImportError:
    print("ABBRUCH (Exit 2): websocket-client fehlt.")
    aufraeumen()
    sys.exit(2)

ziel = None
for _ in range(25):
    try:
        liste = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % CDP, timeout=5).read().decode())
        seiten = [x for x in liste if x.get("type") == "page"]
        if seiten:
            ziel = seiten[0]
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.6)
if not ziel:
    print("ABBRUCH (Exit 2): keine CDP-Seite.")
    aufraeumen()
    sys.exit(2)
ws = websocket.create_connection(ziel["webSocketDebuggerUrl"], timeout=25)
_id = [0]


def cdp(methode, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": methode, "params": params or {}}))
    while True:
        a = json.loads(ws.recv())
        if a.get("id") == _id[0]:
            return a.get("result", {})


def js(ausdruck):
    r = cdp("Runtime.evaluate", {"expression": ausdruck, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"):
        return {"_wurf": str(r["exceptionDetails"])[:200]}
    return r.get("result", {}).get("value")


def bild(name):
    roh = cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}).get("data")
    if roh:
        p = Path.home() / ("sql_ui_%s.png" % name)
        p.write_bytes(base64.b64decode(roh))
        print("  … Screenshot: %s" % p)


def breite(w, h=900):
    cdp("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})


KONTRAST_JS = r"""
function _farbe(s){
  s = String(s||'').trim();
  var m = s.match(/^rgba?\(([^)]+)\)$/);
  if (m) { var t = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [t[0]/255,t[1]/255,t[2]/255, t.length>3?t[3]:1]; }
  m = s.match(/^color\(srgb ([^)]+)\)$/);
  if (m) { var u = m[1].replace('/',' ').split(/\s+/).filter(Boolean).map(Number); return [u[0],u[1],u[2], u.length>3?u[3]:1]; }
  return null;
}
function _flaeche(el){
  var schicht = [];
  for (var e = el; e; e = e.parentElement) {
    var f = _farbe(getComputedStyle(e).backgroundColor);
    if (f && f[3] > 0) { schicht.push(f); if (f[3] >= 0.999) break; }
  }
  var c = [1,1,1];
  for (var i = schicht.length - 1; i >= 0; i--) { var f = schicht[i];
    c = [c[0]*(1-f[3])+f[0]*f[3], c[1]*(1-f[3])+f[1]*f[3], c[2]*(1-f[3])+f[2]*f[3]]; }
  return c;
}
function _L(c){ return c.map(function(v){ return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); })
  .reduce(function(a,v,i){ return a + v*[0.2126,0.7152,0.0722][i]; }, 0); }
function kontrast(sel){
  var el = document.querySelector(sel); if (!el) return null;
  var t = _farbe(getComputedStyle(el).color); if (!t) return {roh:getComputedStyle(el).color};
  var b = _flaeche(el), l1 = _L(t.slice(0,3)), l2 = _L(b);
  return Math.round(100*(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05))/100;
}
"""


def lade(datei, warte_js, sek=6.0):
    cdp("Page.navigate", {"url": "http://127.0.0.1:%d/%s" % (PORT, datei)})
    ende = time.time() + sek
    while time.time() < ende:
        time.sleep(0.3)
        if js(warte_js):
            break
    js(KONTRAST_JS + "window.kontrast = kontrast;")


try:
    # ── Seite /sql ───────────────────────────────────────────────────────
    breite(1280)
    lade("sql.html", "document.getElementById('sq-app') && !document.getElementById('sq-app').classList.contains('hidden') && document.querySelectorAll('#sq-schemata input').length === 2")
    check(js("location.pathname") == "/sql.html" and js("!document.getElementById('sq-app').classList.contains('hidden')"),
          "Positivkontrolle: Seite geladen und sichtbar", js("location.href"))
    check(js("document.querySelectorAll('#sq-schemata input:checked').length") == 2,
          "Positivkontrolle: Schema-Auswahl gezeichnet, beide gewaehlt")
    for thema in ("dunkel", "hell"):
        print("\n── /sql, Thema: %s ──" % thema)
        js("document.body.classList.%s('light')" % ("add" if thema == "hell" else "remove"))
        js("var f=document.getElementById('sq-frage'); f.value='Wie hoch war der Nettoumsatz je Land im Jahr 2025?';"
           "f.dispatchEvent(new Event('input',{bubbles:true})); document.getElementById('sq-los').click();")
        time.sleep(0.8)
        js("var s=document.getElementById('sq-suchfeld'); s.value='kunde'; document.getElementById('sq-suchen').click();")
        time.sleep(0.6)
        js("var t=document.querySelector('#sq-treffer .sq-treffer'); t && t.click();")
        time.sleep(0.6)
        m = js("""(function(){ var p=document.getElementById('sq-pill').getBoundingClientRect(),
                  e=document.getElementById('sq-ergebnis').getBoundingClientRect();
                  return {pill:p.height>0 && p.top>=e.top-1, ueber:document.documentElement.scrollWidth>innerWidth,
                          xss:!!window.__xss, img:!!document.querySelector('.sq-wrap img'),
                          tab:document.querySelectorAll('#sq-detail tbody tr').length}; })()""")
        check(m.get("pill"), "[%s] Pruefstatus steht oben am Ergebnis" % thema, m)
        check(not m.get("ueber"), "[%s] kein waagerechter Ueberlauf (1280 px)" % thema)
        check(not m.get("xss") and not m.get("img"), "[%s] Fremdtext maskiert" % thema)
        check(m.get("tab") == 3, "[%s] Tabellendetail gezeichnet" % thema, m.get("tab"))
        for sel, name in (("#sq-pill", "Pille 'geprüft'"), (".sq-hint", "Hinweistext"),
                          (".sq-schema", "Schema-Etikett"), (".sq-schema-n", "Schema-Zahl"),
                          (".sq-schemabar .sq-lbl", "Schema-Beschriftung"), (".sq-treffer-meta", "Treffer-Zusatz"),
                          ("#sq-sql", "SQL-Block"), (".sq-chip", "Tabellen-Chip")):
            k = js("kontrast(%s)" % json.dumps(sel))
            check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast %s %s:1" % (thema, name, k), k)
        bild("seite_%s" % thema)
        # Nicht bestanden: rote Pille + Befunde
        js("""(function(){ var e = document.getElementById('sq-pill'); e.className='sq-pill is-bad';
              e.textContent='✗ Prüfung nicht bestanden – diese Abfrage bitte nicht verwenden';
              var b=document.getElementById('sq-befunde'); b.innerHTML='<li>Spalte k.nam gibt es in stm.kdst nicht (ähnlich: kdname).</li>';
              b.classList.remove('hidden'); })()""")
        k = js("kontrast('#sq-pill')")
        check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast Pille 'nicht bestanden' %s:1" % (thema, k), k)
        js("var st=document.getElementById('sq-frage-status'); st.textContent='Es läuft bereits eine Frage.'; st.className='sq-status is-fehler';")
        k = js("kontrast('#sq-frage-status')")
        check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast Fehlermeldung %s:1" % (thema, k), k)
        js("var st=document.getElementById('sq-kopier-status'); st.textContent='Kopiert.'; st.className='sq-status is-ok';")
        k = js("kontrast('#sq-kopier-status')")
        check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast Erfolgsmeldung %s:1" % (thema, k), k)
        js("document.getElementById('sq-quellen').innerHTML='<span class=\"sq-warn\">Bitte oben mindestens ein Schema auswählen.</span>'")
        k = js("kontrast('#sq-quellen .sq-warn')")
        check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast Warnzeile %s:1" % (thema, k), k)
        bild("seite_%s_fehler" % thema)
    breite(520)
    time.sleep(0.6)
    print("\n── /sql, 520 px ──")
    m = js("({ueber: document.documentElement.scrollWidth > innerWidth, sw: document.documentElement.scrollWidth,"
           " los: document.getElementById('sq-los').getBoundingClientRect().right <= innerWidth,"
           " bar: Array.prototype.every.call(document.querySelectorAll('.sq-schema'), function(e){ return e.getBoundingClientRect().right <= innerWidth; })})")
    check(not m.get("ueber"), "kein waagerechter Ueberlauf bei 520 px", m)
    check(m.get("los"), "Knopf 'SQL erzeugen' im Fenster", m)
    check(m.get("bar"), "Schema-Etiketten brechen um, keines ragt hinaus", m)
    bild("seite_schmal")

    # ── Reiter ───────────────────────────────────────────────────────────
    breite(1280)
    lade("reiter.html", "document.querySelectorAll('#sqadm-schemata .sqadm-schema').length === 2", 8.0)
    check(js("document.querySelectorAll('#sqadm-schemata .sqadm-schema').length") == 2,
          "Positivkontrolle: Reiter aufgebaut (2 Schemata)")
    hoehe = js("document.getElementById('settings-tab-sql').getBoundingClientRect().height")
    if not (isinstance(hoehe, (int, float)) and hoehe > 300):
        print("ABBRUCH (Exit 2): der Reiter ist nicht SICHTBAR (Hoehe %s) – jede Messung waere wertlos" % hoehe)
        aufraeumen()
        sys.exit(2)
    # Dateiliste ueber den echten Knopf aufklappen
    js("document.querySelector('.sqadm-schema[data-id=\"erp\"] .sqadm-listbtn').click()")
    time.sleep(0.8)
    check(js("document.querySelectorAll('.sqadm-baum[data-sid=\"erp\"] .sqadm-datei').length") == 4,
          "Positivkontrolle: Dateiliste ueber den Knopf aufgeklappt (4 Eintraege)")
    for thema in ("dunkel", "hell"):
        print("\n── Reiter, Thema: %s ──" % thema)
        js("document.body.classList.%s('light')" % ("add" if thema == "hell" else "remove"))
        time.sleep(0.4)
        m = js("""(function(){
            var out=[], dz=[];
            document.querySelectorAll('.sqadm-schema').forEach(function(r){ var b=r.querySelector('[data-akt="del-schema"]').getBoundingClientRect(),
                k=r.getBoundingClientRect(); out.push(b.right <= k.right+1 && b.width > 10); });
            document.querySelectorAll('.sqadm-datei').forEach(function(z){ var b=z.querySelector('[data-akt="del-datei"]').getBoundingClientRect(),
                k=z.getBoundingClientRect(); dz.push(b.right <= k.right+1 && b.width > 10 && b.top >= k.top-1 && b.bottom <= k.bottom+1); });
            var d=document.querySelector('.sqadm-drop'), db=d.getBoundingClientRect(), ob=d.querySelector('.sqadm-dirbtn').getBoundingClientRect();
            return {del:out, zeilen:dz, ueber:document.documentElement.scrollWidth>innerWidth,
                    drop: db.height > 60 && ob.width < db.width * 0.8,
                    fort:!document.getElementById('sqadm-fortschritt').hidden,
                    stop:getComputedStyle(document.getElementById('sqadm-stop')).display!=='none'}; })()""")
        check(all(m.get("del") or [False]), "[%s] Muelleimer je Schema im Kasten" % thema, m.get("del"))
        check(len(m.get("zeilen") or []) == 4 and all(m.get("zeilen")), "[%s] Muelleimer je Datei in ihrer Zeile (auch beim langen Namen)" % thema, m.get("zeilen"))
        check(m.get("drop"), "[%s] Ablagefeld sichtbar, 'Ordner wählen' nicht zeilenbreit" % thema, m)
        check(not m.get("ueber"), "[%s] kein waagerechter Ueberlauf" % thema)
        check(m.get("fort") and m.get("stop"), "[%s] Fortschritt und Abbrechen sichtbar" % thema, m)
        js("var st=document.getElementById('sqadm-status'); st.textContent='Nicht gespeichert.'; st.className='sqadm-st is-fehler';"
           "var s2=document.getElementById('sqadm-status2'); s2.textContent='Gespeichert.'; s2.className='sqadm-st is-ok';"
           "var u=document.querySelector('.sqadm-up-status'); u.textContent='3 Dateien übernommen, 1 abgelehnt.'; u.className='sqadm-up-status sqadm-st is-fehler';"
           # Der Erfassungs-Takt (alle 2 s) zeichnet die Fehlerliste neu – den
           # Eintrag deshalb unmittelbar vor der Messung setzen (sonst misst der
           # zweite Durchgang eine leere Liste).
           "document.getElementById('sqadm-fehler').innerHTML='<li>Datei unlesbar: erp/archiv/kaputt.sql</li>';")
        for sel, name in (("#sqadm-status", "Fehlermeldung"), ("#sqadm-status2", "Erfolgsmeldung"),
                          (".sqadm-up-status", "Upload-Ergebnis"), (".sqadm-drop", "Ablagefeld"),
                          (".sqadm-drop-sub", "Ablage-Zusatz"), (".sqadm-dname", "Dateiname"), (".sqadm-dgr", "Dateigroesse"),
                          (".vis-progress-text", "Fortschrittstext"), ("#sqadm-fehler li", "Fehlerliste"),
                          (".sqadm-zahlen", "Zahlen je Schema"), (".sqadm-baum .kb-hint", "Kuerzungshinweis")):
            k = js("kontrast(%s)" % json.dumps(sel))
            check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast %s %s:1" % (thema, name, k), k)
        bild("reiter_%s" % thema)
    breite(520)
    time.sleep(0.6)
    m = js("({ueber: document.documentElement.scrollWidth > innerWidth, sw: document.documentElement.scrollWidth})")
    check(not m.get("ueber"), "Reiter: kein waagerechter Ueberlauf bei 520 px", m)
    bild("reiter_schmal")

    # ── Chat-Auswahl ─────────────────────────────────────────────────────
    breite(1280)
    lade("chatfilter.html", "window.F && !window.F.el.hidden", 6.0)
    check(js("window.F && !window.F.el.hidden"), "Positivkontrolle: Chat-Auswahl sichtbar")
    js("document.querySelector('.sqsf-btn').click()")
    time.sleep(0.3)
    for thema in ("dunkel", "hell"):
        print("\n── Chat-Auswahl, Thema: %s ──" % thema)
        js("document.body.classList.%s('light')" % ("add" if thema == "hell" else "remove"))
        time.sleep(0.3)
        m = js(r"""(function(){ var p=document.querySelector('.sqsf-panel'), r=p.getBoundingClientRect(),
                  bg=getComputedStyle(p).backgroundColor;
                  return {offen:!p.hidden && r.height>40, oben:r.bottom <= document.querySelector('.sqsf-btn').getBoundingClientRect().top,
                          imFenster:r.top >= 0 && r.left >= 0 && r.right <= innerWidth, bg:bg,
                          deckend: !/rgba\(.*,\s*0?\.\d+\)$/.test(bg) && !/ \/ 0?\.\d+\)$/.test(bg)}; })()""")
        check(m.get("offen") and m.get("oben") and m.get("imFenster"), "[%s] Liste klappt nach OBEN auf, im Fenster" % thema, m)
        check(m.get("deckend"), "[%s] Aufklappfeld deckend (liegt ueber dem Verlauf)" % thema, m.get("bg"))
        for sel, name in ((".sqsf-btn", "Knopf"), (".sqsf-badge", "Abzeichen 'aus'"), (".sqsf-head", "Kopfzeile"),
                          (".sqsf-name", "Schemaname"), (".sqsf-zahl", "Tabellenzahl"), (".sqsf-a", "'Kein Schema'")):
            k = js("kontrast(%s)" % json.dumps(sel))
            check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast %s %s:1" % (thema, name, k), k)
        js("var c=document.querySelector('.sqsf-panel input'); if(!c.checked){c.click();}")
        time.sleep(0.2)
        k = js("kontrast('.sqsf-btn.sqsf-aktiv .sqsf-badge')")
        check(isinstance(k, (int, float)) and k >= 4.5, "[%s] Kontrast Abzeichen gewaehlt %s:1" % (thema, k), k)
        bild("chatfilter_%s" % thema)
finally:
    try:
        ws.close()
    finally:
        aufraeumen()

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 60, _ok, _fail, "=" * 60))
sys.exit(1 if _fail else 0)
