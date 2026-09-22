/**
 * Die Bereitstellung über eine Netzfreigabe (A) in der Kachel /ai-mouse.
 *
 * ⚠ DER ECHTE RENDERER LÄUFT gegen die ECHTE ai_mouse.html. Ob am Ende eine
 * Pfad-Zeile DASTEHT und ob der Download-Knopf VERSCHWINDET, kann eine
 * Quelltext-Suche nicht beantworten – und genau daran ist der erste Anlauf
 * gescheitert: die Prüfung `"_istAdmin" in JS && "am-dl-box" in JS` blieb
 * grün, als der Knopf unbedingt versteckt wurde (beide Namen stehen ja
 * weiterhin da). Register: die Eigenschaft messen, nicht ein Vorkommen.
 *
 *   node tests/test_ai_mouse_freigabe_ui.js     (JSDOM_PATH setzt den jsdom-Ort)
 */
const fs = require('fs');
let JSDOM = null;
for (const o of [process.env.JSDOM_PATH, 'jsdom',
                 '/tmp/node_modules/jsdom', './node_modules/jsdom',
                 process.env.HOME + '/node_modules/jsdom',
                 '/opt/jarvis/data/node_modules/jsdom', '/usr/share/nodejs/jsdom']) {
  if (!o) { continue; }
  try { JSDOM = require(o).JSDOM; break; } catch (e) { /* naechster Ort */ }
}
if (!JSDOM) {
  // Exit 2: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
  console.error('jsdom nicht gefunden - Exit 2 (nicht gelaufen, nicht bestanden)');
  process.exit(2);
}

let ok = 0, fail = 0;
const c = (t, b) => { b ? (ok++, console.log('  OK   ' + t))
                        : (fail++, console.log('  FAIL ' + t)); };
let bilanz = false;
// Der Wachhund MUSS frueh registriert sein – ein Absturz danach waere sonst
// von einem bestandenen Lauf nicht zu unterscheiden (Register).
process.on('exit', () => {
  if (!bilanz) { console.log('\nABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});
const wd = setTimeout(() => {
  console.log('\nWACHHUND: haengt\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
  bilanz = true; process.exit(1);
}, 25000);

/** Auf einen ZUSTAND warten, nicht auf die Uhr.
 *
 * ⚠ EINE FESTE WARTEZEIT IST EINE MESSUNG DER MASCHINE, NICHT DES CODES. Der
 * erste Anlauf wartete 300 ms und meldete 10 FAIL für einen Renderer, der
 * nachweislich einwandfrei läuft – er war nur noch nicht fertig. `start()`
 * hängt an drei verketteten Abrufen (/api/me → fragen → health).
 */
function warte(w, pruef, ms) {
  return new Promise((loese, brich) => {
    const ende = Date.now() + (ms || 5000);
    (function tick() {
      let da = false;
      try { da = pruef(); } catch (e) { da = false; }
      if (da) { return loese(true); }
      if (Date.now() > ende) {
        return brich(new Error('Zustand kam nicht zustande'));
      }
      setTimeout(tick, 15);
    })();
  });
}

/** Eine Seite mit gestelltem health-Zustand aufbauen und den Renderer fahren. */
function seite(healthExtra, istAdmin) {
  const d = new JSDOM(fs.readFileSync('frontend/ai_mouse.html', 'utf8'),
                      { url: 'https://x/ai-mouse', runScripts: 'outside-only' });
  const w = d.window;
  w.localStorage.setItem('jarvis_token', 't');
  const J = x => Promise.resolve({ ok: true, status: 200,
                                   json: () => Promise.resolve(x) });
  w.fetch = (u, o) => {
    const p = String(u).split('?')[0];
    if (p === '/api/ai-mouse/fragen') { return J({ fragen: [], ist_admin: istAdmin }); }
    if (p === '/api/ai-mouse/health') {
      return J(Object.assign({ paket_bereit: true, bereiche: [],
                               klient_version: '1.0.9' }, healthExtra));
    }
    if (p === '/api/me') {
      return J({ username: 'u', is_admin: istAdmin,
                 permissions: { ai_mouse: true } });
    }
    return J({});
  };
  for (const f of ['frontend/js/i18n.js', 'frontend/js/icons.js',
                   'frontend/js/ai_mouse.js']) {
    try { w.eval(fs.readFileSync(f, 'utf8')); }
    catch (e) { console.log('LADEFEHLER ' + f + ': ' + e.message); }
  }
  return w;
}

const sichtbar = (w, id) => {
  const e = w.document.getElementById(id);
  if (!e) { return false; }
  // `.hidden` ist im Projekt die Klasse, die ausblendet.
  for (let n = e; n && n.classList; n = n.parentElement) {
    if (n.classList.contains('hidden')) { return false; }
  }
  return true;
};

/** Seite bauen UND warten, bis der Renderer durch ist. */
async function fertig(healthExtra, istAdmin) {
  const w = seite(healthExtra, istAdmin);
  // Positivkontrolle des Messaufbaus: `start()` blendet die Anwendung erst
  // frei, wenn /api/me durch ist – vorher ist JEDES Element in einem
  // versteckten Vorfahren und jede Sichtbarkeitsmessung trivial falsch.
  await warte(w, () => {
    const app = w.document.getElementById('am-app');
    return app && !app.classList.contains('hidden');
  });
  // Und bis der Freigabe-Zweig wirklich gelaufen ist (health ist der letzte
  // Abruf der Kette).
  await warte(w, () => w.document.getElementById('am-version') !== null
                    && w.__amRendered !== false);
  await new Promise(r => setTimeout(r, 30));
  return w;
}

(async () => {
  // ── 1. Kein Pfad hinterlegt: alles wie bisher ────────────────────────────
  console.log('\n=== 1. Ohne Freigabe-Pfad ===');
  let w = await fertig({ freigabe_pfad: '' }, false);
  let box = w.document.getElementById('am-freigabe');
  c('der Freigabe-Container existiert', !!box);
  c('er ist leer', !!box && box.textContent.trim() === '');
  c('der Download-Knopf ist sichtbar', sichtbar(w, 'am-dl-box'));
  w.close();

  // ── 2. Pfad hinterlegt, gewöhnlicher Benutzer ────────────────────────────
  console.log('\n=== 2. Mit Freigabe-Pfad, Nicht-Admin ===');
  const PFAD = '\\\\srv\\freigabe\\tools\\AiMouse.exe';
  w = await fertig({ freigabe_pfad: PFAD }, false);
  box = w.document.getElementById('am-freigabe');
  c('die Pfad-Zeile ist da', !!box && !!box.querySelector('.ja-pfad'));
  const wert = w.document.getElementById('am-freigabe-pfad');
  c('der Pfad steht im Text', !!wert && wert.textContent === PFAD);
  c('es gibt einen Kopier-Knopf', !!w.document.getElementById('am-freigabe-copy'));
  c('⚠ der Download-Knopf ist für den Benutzer WEG', !sichtbar(w, 'am-dl-box'));
  c('ein Hinweis erklärt, was zu tun ist',
    !!box && box.textContent.length > 80);
  w.close();

  // ── 3. Pfad hinterlegt, Administrator ────────────────────────────────────
  console.log('\n=== 3. Mit Freigabe-Pfad, Administrator ===');
  w = await fertig({ freigabe_pfad: PFAD }, true);
  box = w.document.getElementById('am-freigabe');
  c('die Pfad-Zeile ist auch für ihn da', !!box && !!box.querySelector('.ja-pfad'));
  // ⚠ HIER STAND BIS 2026-09-22 DAS GEGENTEIL („der Administrator BEHÄLT den
  //   Download-Knopf"), und dieser Wächter hätte die Änderung abgelehnt.
  //   Der Einwand von damals war richtig – ohne Knopf gäbe es keinen Weg an
  //   die Datei –, die STELLE war falsch: er gehört in den Admin-Reiter
  //   (*Einstellungen → AI-Maus → Bereitstellung im Netz*), nicht in die
  //   Benutzer-Kachel. Ein Knopf, den nur eine Rolle sieht, macht dieselbe
  //   Seite für zwei Leute verschieden, und der Admin sieht nicht, was seine
  //   Benutzer sehen. Vorgabe des Betreibers, Vorbild Outlook-/Excel-Add-in.
  c('⚠ der Download ist für JEDEN weg, auch für den Administrator',
    !sichtbar(w, 'am-dl-box'));
  c('und die Kachel sieht für beide gleich aus',
    !!box && box.textContent.indexOf('Administrator') < 0);
  w.close();

  // ── 3b. Der Weg an die Datei steht im ADMIN-REITER ───────────────────────
  //   Sonst wäre die Bereitstellung eine Einbahnstraße – das ist die Hälfte
  //   der Zusage, die der Test oben nicht mehr misst.
  console.log('\n=== 3b. Der Download liegt im Admin-Reiter ===');
  const SH = fs.readFileSync('frontend/settings.html', 'utf8');
  const iShare = SH.indexOf('id="am-sect-share"');
  const iSign = SH.indexOf('id="am-sect-sign"');
  c('der Container am-sect-share existiert', iShare > 0);
  c('⚠ der Download-Knopf liegt DARIN',
    iShare > 0 && iSign > iShare
      && SH.slice(iShare, iSign).indexOf('id="amshare-dl"') > 0);
  // ⚠ EIN <button>, KEIN <a href>: ein Link bräuchte den Token IN DER ADRESSE.
  //   Das Outlook-Muster trägt hier nicht – dort ist das Manifest winzig und
  //   ohnehin offen, hier sind es 66 MB hinter einer Freigabe.
  const dlAusschnitt = iShare > 0
    ? SH.slice(SH.indexOf('id="amshare-dl"') - 200, SH.indexOf('id="amshare-dl"') + 200)
    : '';
  c('⚠ er ist ein <button>, kein <a href> mit Token in der Adresse',
    /<button[^>]*id="amshare-dl"/.test(dlAusschnitt));
  const AJS = fs.readFileSync('frontend/js/ai_mouse_admin.js', 'utf8');
  // ⚠ NICHT ueber ein FENSTER hinter `amshare-dl` messen: unmittelbar danach
  //   wird der naechste Knopf verdrahtet, und dessen `addEventListener` haelt
  //   jedes Umfeld-Muster wahr, auch wenn `shDl` gar nichts tut (am 2026-09-22
  //   so gemessen – die Gegenprobe war STUMM). Gemessen wird die EIGENSCHAFT:
  //   derselbe if-Block nennt `holePaket`.
  c('er ist verdrahtet',
    /amshare-dl'\)[^;]*;\s*if\s*\([^)]*\)\s*\{[^}]*holePaket[^}]*\}/.test(AJS));

  // ⚠ UND DER RUMPF WIRD GESCHNITTEN, nicht umfenstert: `holePaket` steht auch
  //   in der VERDRAHTUNG, und dahinter folgt `load:` mit eigenem
  //   `authHeaders()` – das Fenster traf also eine fremde Funktion.
  function rumpf(quelle, kopf) {
    const i = quelle.indexOf(kopf);
    if (i < 0) { return ''; }
    let tiefe = 0, j = quelle.indexOf('{', i);
    if (j < 0) { return ''; }
    for (let k = j; k < quelle.length; k++) {
      if (quelle[k] === '{') { tiefe++; }
      else if (quelle[k] === '}') { tiefe--; if (tiefe === 0) { return quelle.slice(i, k + 1); } }
    }
    return '';
  }
  const HOLE = rumpf(AJS, 'holePaket: function');
  c('Positivkontrolle: holePaket ist geschnitten', HOLE.length > 200);
  c('und lädt als Blob mit Authorization-Kopf',
    /fetch\('\/api\/ai-mouse\/paket',\s*\{\s*headers:\s*authHeaders\(\)/.test(HOLE)
    && HOLE.indexOf('createObjectURL') > 0);
  // Der tote i18n-Schlüssel darf nicht zurückkommen.
  const I18 = fs.readFileSync('frontend/js/i18n.js', 'utf8');
  c('der alte Kachel-Satz aimouse.share_admin ist weg',
    I18.indexOf('aimouse.share_admin') < 0);
  for (const k of ['amshare.dl', 'amshare.dl_running', 'amshare.dl_ok']) {
    c(k + ' gibt es in DE UND EN',
      (I18.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length === 2);
  }

  // ── 4. Der Pfad ist Fremdeingabe ─────────────────────────────────────────
  console.log('\n=== 4. Einschleusversuch über den Pfad ===');
  w = await fertig({ freigabe_pfad: '<img src=x onerror="window.__ARGH=1">' }, false);
  box = w.document.getElementById('am-freigabe');
  c('kein fremdes Element entsteht', !box || box.querySelectorAll('img').length === 0);
  c('der Text steht als TEXT da',
    !!box && box.textContent.indexOf('<img') >= 0);
  c('und nichts wurde ausgeführt', w.__ARGH === undefined);
  w.close();

  // ── 5. Trimmen/Leerwert ──────────────────────────────────────────────────
  console.log('\n=== 5. Nur Leerraum = nicht hinterlegt ===');
  w = await fertig({ freigabe_pfad: '   ' }, false);
  c('ein Pfad aus Leerraum zählt als NICHT hinterlegt',
    sichtbar(w, 'am-dl-box'));
  w.close();

  clearTimeout(wd);
  bilanz = true;
  console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
  process.exit(fail ? 1 : 0);
})().catch(e => {
  // Ein Wurf im Ablauf darf nicht als bestanden durchgehen.
  clearTimeout(wd);
  bilanz = true;
  console.log('\nABBRUCH: ' + (e && e.message));
  console.log(ok + ' OK, ' + (fail + 1) + ' FAIL');
  process.exit(1);
});
