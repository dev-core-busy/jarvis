#!/usr/bin/env node
/**
 * BSI H4 (2026-10-04) – Klicktest fuer knowledge.js / vision.js / google.js
 * ohne Inline-Handler.
 *
 * Die drei Module bauen ihr Markup per innerHTML; die Knoepfe tragen seit H4
 * nur noch data-Attribute, verteilt wird ueber einen delegierten Listener je
 * Modul. Dieser Test rendert ueber die ECHTEN Renderer, klickt WIRKLICH und
 * misst, welche Methode mit welchen Argumenten ankommt:
 *   - Argument-Treue (Pfad mit ' " \ &, Zahlen statt Strings, Boolean)
 *   - `this`-Faelle (Element als Argument)
 *   - stopPropagation (Eltern-Listener und Ordnerkopf bleiben stumm)
 *   - change-Ereignisse, onerror an <img>, und dass unbekannte Namen nichts tun
 *   - kein on*-Attribut im gerenderten Markup
 * jsdom mit runScripts:'outside-only' fuehrt Inline-Handler ohnehin NICHT aus –
 * ein gruener Lauf belegt also die Delegation, nicht ein Ueberbleibsel.
 *
 * Exit 0 = gruen, 1 = Fehler, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

let ok = 0, fail = 0;
function pruefe(cond, name, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail ? '\n         ' + detail : '')); }
}
function abbruch(grund) { console.log('ABBRUCH (Exit 2): ' + grund); process.exit(2); }

function lies(rel) {
    try { return fs.readFileSync(path.join(ROOT, rel), 'utf8'); }
    catch (e) { abbruch('Datei fehlt: ' + rel); }
}
const ICONS = lies('frontend/js/icons.js');
const KNOW = lies('frontend/js/knowledge.js');
const VIS = lies('frontend/js/vision.js');
const GOO = lies('frontend/js/google.js');

function seite() {
    const dom = new JSDOM(`<!doctype html><html><body>
        <div id="kb-stats-container"></div>
        <div id="kb-folder-list"></div>
        <div id="kb-mount-list"></div>
        <div id="kb-cleanup-body"></div>
        <div id="vis-profiles-list"></div>
        <div id="vis-detected-faces"></div>
        <div id="google-status-container"></div>
    </body></html>`, { url: 'https://host/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.t = (k) => k;
    w.JarvisSitzung = { token: () => 'tok' };
    w.JarvisDL = { schluessel: () => 'dlk' };
    w.fetch = () => new Promise(() => {});   // nie aufloesen: kein Netz, kein Nebenweg
    w.eval(ICONS);
    w.eval(KNOW);
    w.eval(VIS);
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));   // vision.js legt die Instanz dort an
    w.eval(GOO);
    return { dom, w, d: w.document };
}

function spione(obj, namen) {
    const aufrufe = [];
    for (const n of namen) obj[n] = (...a) => { aufrufe.push([n, a]); };
    return aufrufe;
}
function onAttribute(wurzel) {
    const funde = [];
    for (const el of wurzel.querySelectorAll('*')) {
        for (const a of el.attributes) if (/^on/i.test(a.name)) funde.push(el.tagName + ' ' + a.name);
    }
    return funde;
}

const { dom, w, d } = seite();
const km = w.knowledgeManager, vm = w.visionManager, gm = w.googleManager;
if (!km || !vm || !gm) abbruch('Manager-Instanzen fehlen (km=' + !!km + ' vm=' + !!vm + ' gm=' + !!gm + ')');
if (!w._kbAktionenGebunden || !w._visAktionenGebunden || !w._gmAktionenGebunden) {
    abbruch('delegierte Listener nicht registriert – Messaufbau prueft nichts');
}

// ── knowledge.js: Ordnerknoten (Argument + stopPropagation) ───────────────
console.log('== knowledge.js: Ordner ==');
{
    const pfad = `data/rag/O'Neil "x" & a\\b`;
    const liste = d.getElementById('kb-folder-list');
    liste.innerHTML = km._folderNodeHtml(pfad, true, false, false);
    pruefe(onAttribute(liste).length === 0, 'Ordnerknoten ohne on*-Attribut', onAttribute(liste).join(', '));
    const auf = spione(km, ['toggleDir', 'createSubfolder', 'renameSubfolder', 'moveSubfolder', 'deleteSubfolder', 'editFolder']);
    let eltern = 0;
    liste.addEventListener('click', () => { eltern++; });
    const share = [];
    w.KnowledgeSync = { openShare: (p) => share.push(p) };

    const kopf = liste.querySelector('.kb-folder-toggle');
    // Positivkontrolle: Klick auf ein INNERES Element des Kopfes erreicht toggleDir
    kopf && kopf.querySelector('.kb-folder-icon').click();
    pruefe(auf.length === 1 && auf[0][0] === 'toggleDir' && auf[0][1][0] === pfad
           && auf[0][1][1] === km._pathId(pfad),
        'Positivkontrolle: Ordnerkopf -> toggleDir(pfad, id) mit Sonderzeichen', JSON.stringify(auf));
    pruefe(eltern === 1, 'Ordnerkopf erreicht den Eltern-Listener (kein stopPropagation)', 'eltern=' + eltern);

    auf.length = 0; eltern = 0;
    const add = liste.querySelector('.kb-btn-addsub');
    add && add.click();
    pruefe(auf.length === 1 && auf[0][0] === 'createSubfolder' && auf[0][1][0] === pfad,
        'createSubfolder(pfad) mit unveraendertem Pfad', JSON.stringify(auf));
    pruefe(eltern === 0, 'createSubfolder: stopPropagation – Eltern-Listener bleibt stumm', 'eltern=' + eltern);

    auf.length = 0;
    liste.querySelector('.kb-btn-share').click();
    pruefe(share.length === 1 && share[0] === pfad && auf.length === 0 && eltern === 0,
        'openShare(pfad), kein toggleDir, kein Eltern-Listener', JSON.stringify({ share, auf, eltern }));

    auf.length = 0;
    liste.querySelector('.kb-btn-movesub').click();
    liste.querySelector('.kb-btn-rename').click();
    pruefe(auf.map(x => x[0]).join() === 'moveSubfolder,renameSubfolder'
           && auf.every(x => x[1][0] === pfad) && eltern === 0,
        'moveSubfolder/renameSubfolder mit Pfad, gestoppt', JSON.stringify(auf));

    // Unterordner als eigener Speicherordner (2026-10-21): das Etikett oeffnet
    // denselben Gruppen-Dialog wie beim Wurzelordner.
    auf.length = 0;
    const etikett = liste.querySelector('.kb-btn-groups');
    etikett && etikett.click();
    pruefe(!!etikett && auf.length === 1 && auf[0][0] === 'editFolder' && auf[0][1][0] === pfad
           && eltern === 0,
        'Unterordner: Etikett -> editFolder(pfad), gestoppt', JSON.stringify(auf));
}

// ── knowledge.js: Wurzelordner – Bleistift und Etikett getrennt (2026-10-21) ─
console.log('== knowledge.js: Wurzelordner ==');
{
    const wurzel = `data/rag/O'Neil "x" & b`;
    const liste = d.getElementById('kb-folder-list');
    liste.innerHTML = km._folderNodeHtml(wurzel, true, true, false);
    const auf = spione(km, ['renameFolder', 'editFolder', 'removeFolder', 'toggleDir', 'moveSubfolder']);
    let eltern = 0;
    liste.addEventListener('click', () => { eltern++; });
    const stift = liste.querySelector('.kb-btn-rename');
    const etikett = liste.querySelector('.kb-btn-groups');
    pruefe(!!stift && !!etikett && !!stift.querySelector('.jv-ico-pencil') && stift !== etikett,
        'Positivkontrolle: Wurzel traegt Bleistift UND Etikett als zwei Knoepfe');
    stift && stift.click();
    pruefe(auf.length === 1 && auf[0][0] === 'renameFolder' && auf[0][1][0] === wurzel && eltern === 0,
        'Bleistift -> renameFolder(pfad), gestoppt', JSON.stringify(auf));
    auf.length = 0;
    etikett && etikett.click();
    pruefe(auf.length === 1 && auf[0][0] === 'editFolder' && auf[0][1][0] === wurzel && eltern === 0,
        'Etikett -> editFolder(pfad), gestoppt', JSON.stringify(auf));
    // Verschieben (2026-10-21): die Wurzel wird Unterordner des Ziels.
    auf.length = 0;
    const schieben = liste.querySelector('.kb-btn-movesub');
    schieben && schieben.click();
    pruefe(!!schieben && auf.length === 1 && auf[0][0] === 'moveSubfolder' && auf[0][1][0] === wurzel
           && eltern === 0, 'Wurzel: Verschieben -> moveSubfolder(pfad), gestoppt', JSON.stringify(auf));
    // Eine Wurzel ausserhalb von data/rag kann der Server weder umbenennen noch
    // verschieben – dann gibt es keinen Knopf statt eines, der abgewiesen wird.
    liste.innerHTML = km._folderNodeHtml('/srv/anderswo', true, true, false);
    pruefe(!liste.querySelector('.kb-btn-rename') && !liste.querySelector('.kb-btn-movesub')
           && !!liste.querySelector('.kb-btn-groups'),
        'Wurzel ausserhalb data/rag: kein Bleistift, kein Verschieben, aber Etikett');
}

// ── knowledge.js: Datei-Zeile ──────────────────────────────────────────────
console.log('== knowledge.js: Dateizeile ==');
{
    const box = d.createElement('div');
    d.body.appendChild(box);
    const f = { path: `data/rag/a'b"c.pdf`, name: 'x', size: '1 KB' };
    box.innerHTML = km._fileRowHtml(f, `data/rag/d'ir`);
    const auf = spione(km, ['moveFiles', 'deleteFile']);
    box.querySelector('.kb-btn-move-file').click();
    box.querySelector('.kb-btn-delete-file').click();
    pruefe(auf.length === 2 && Array.isArray(auf[0][1][0]) && auf[0][1][0].length === 1
           && auf[0][1][0][0] === f.path && auf[0][1][1] === `data/rag/d'ir`
           && auf[1][1][0] === f.path && auf[1][1][1] === `data/rag/d'ir`,
        'moveFiles([pfad], dir) und deleteFile(pfad, dir)', JSON.stringify(auf));
}

// ── knowledge.js: Statistik-Panel (`this` + change) ───────────────────────
console.log('== knowledge.js: Statistik ==');
{
    km._renderStats({ total_size_bytes: 0, total_files: 0, indexed_files: 0, total_chunks: 0, folders: [] },
        { total_files: 2, total_size_kb: 3, months: [] }, { auto: false });
    const c = d.getElementById('kb-stats-container');
    pruefe(onAttribute(c).length === 0, 'Statistik ohne on*-Attribut', onAttribute(c).join(', '));
    const auf = spione(km, ['toggleLearnedList', 'downloadLearnedJson', 'compactLearned', 'showCompactInfo', 'setCompactAuto']);
    const ex = c.querySelector('[data-kb-aktion="downloadLearnedJson"]');
    const exs = c.querySelector('[data-kb-aktion="downloadLearnedJsonSplit"]');
    ex && ex.click(); exs && exs.click();
    pruefe(auf.length === 2 && auf[0][1][0] === ex && auf[0][1].length === 1
           && auf[1][1][0] === exs && auf[1][1][1] === true,
        'downloadLearnedJson(this) und (this, true)', JSON.stringify(auf.map(a => [a[0], a[1].length, a[1][1]])));
    auf.length = 0;
    const comp = d.getElementById('kb-compact-btn');
    comp && comp.click();
    pruefe(auf.length === 1 && auf[0][0] === 'compactLearned' && auf[0][1][0] === comp,
        'compactLearned(this)', JSON.stringify(auf.map(a => a[0])));
    auf.length = 0;
    c.querySelector('[data-kb-aktion="showCompactInfo"]').click();
    pruefe(auf.length === 1 && auf[0][1][0] === true, 'showCompactInfo(true)', JSON.stringify(auf));
    auf.length = 0;
    const cb = d.getElementById('kb-compact-auto');
    cb.click();   // echter Klick -> change
    pruefe(auf.length === 1 && auf[0][0] === 'setCompactAuto' && auf[0][1][0] === cb && cb.checked === true,
        'Kaestchen: change -> setCompactAuto(this), Haken gesetzt', JSON.stringify(auf.map(a => a[0])));
}

// ── knowledge.js: Aufraeum-Vergleich (idx als ZAHL + this) ────────────────
console.log('== knowledge.js: Aufraeumen ==');
{
    km._cleanupVorschlaege = [
        { ok: true, geaendert: true, schluessel: 'a', alt: 'x', neu: 'y', bytes_alt: 1, bytes_neu: 1 },
        { ok: true, geaendert: true, schluessel: 'b', alt: 'x', neu: 'z', bytes_alt: 1, bytes_neu: 1 },
    ];
    const auf = spione(km, ['cleanupBearbeiten', 'cleanupEinzelSpeichern', 'cleanupOeffnen']);
    try { km._cleanupVergleich('m'); } catch (e) { /* Nachlauf (Bilanz) darf fehlen */ }
    const box = d.getElementById('kb-cleanup-body');
    pruefe(onAttribute(box).length === 0, 'Aufraeum-Vergleich ohne on*-Attribut', onAttribute(box).join(', '));
    const save = box.querySelector('#kb-cl-karte-1 .kb-cl-save');
    const edit = box.querySelector('#kb-cl-karte-1 [data-kb-aktion="cleanupBearbeiten"]');
    edit && edit.click(); save && save.click();
    const z = box.querySelector('#kb-cl-zurueck'); z && z.click();
    pruefe(auf.length === 3 && auf[0][1][0] === 1 && typeof auf[0][1][0] === 'number'
           && auf[1][1][0] === 1 && typeof auf[1][1][0] === 'number' && auf[1][1][1] === save
           && auf[2][0] === 'cleanupOeffnen',
        'cleanupBearbeiten(1), cleanupEinzelSpeichern(1, this), cleanupOeffnen()',
        JSON.stringify(auf.map(a => [a[0], a[1].map(x => typeof x)])));
}

// ── knowledge.js: Netzwerk-Freigaben (Boolean, change, Abbrechen) ─────────
console.log('== knowledge.js: Freigaben ==');
{
    km._renderMounts([{ type: 'smb', source: '//s/a', active: true }, { type: 'nfs', source: 's:/b', active: false }]);
    const liste = d.getElementById('kb-mount-list');
    pruefe(onAttribute(liste).length === 0, 'Freigabenliste ohne on*-Attribut', onAttribute(liste).join(', '));
    const auf = spione(km, ['toggleMount', 'diagnoseMount', 'showEditMount', 'removeMount', 'saveEditMount', 'mountBeispielNachziehen']);
    const tg = liste.querySelectorAll('[data-kb-aktion="toggleMount"]');
    tg[0] && tg[0].click(); tg[1] && tg[1].click();
    pruefe(auf.length === 2 && auf[0][1][0] === 0 && auf[0][1][1] === false
           && auf[1][1][0] === 1 && auf[1][1][1] === true,
        'toggleMount(i, !active) mit Zahl und Boolean', JSON.stringify(auf));
    auf.length = 0;
    const sel = liste.querySelectorAll('.kb-mount-edit-type')[1];
    sel.value = 'webdav';
    sel.dispatchEvent(new w.Event('change', { bubbles: true }));
    pruefe(auf.length === 1 && auf[0][0] === 'mountBeispielNachziehen' && auf[0][1][0] === sel,
        'Typ-Auswahl: change -> mountBeispielNachziehen(this)', JSON.stringify(auf.map(a => a[0])));
    const form = d.getElementById('kb-mount-edit-1');
    form.style.display = 'block';
    form.querySelector('.kb-btn-secondary').click();
    pruefe(form.style.display === 'none', 'Abbrechen blendet das Bearbeiten-Formular aus');
    // Die Ausblende-Aktion nimmt nur Editoren dieses Moduls, keine beliebige ID
    const fremd = d.createElement('div'); fremd.id = 'kb-stats-container-x'; d.body.appendChild(fremd);
    const b = d.createElement('button');
    b.setAttribute('data-kb-aktion', 'ausblenden'); b.setAttribute('data-kb-ziel', 'kb-stats-container-x');
    d.body.appendChild(b); b.click();
    pruefe(fremd.style.display !== 'none', 'ausblenden greift nicht auf fremde IDs');
}

// ── knowledge.js: unbekannte Aktion tut nichts (kein Script-Gadget) ───────
{
    let getroffen = 0;
    // Ein Wurf im Listener erreicht b.click() nicht - jsdom meldet ihn als
    // 'error' am window. Mitzaehlen, sonst ist "tut nichts" nicht messbar.
    const wurf = () => { getroffen += 100; };
    w.addEventListener('error', wurf);
    km.constructor = () => { getroffen++; };
    w.__gadget = () => { getroffen++; };
    for (const name of ['constructor', '__proto__', 'toString', '__gadget', 'window.__gadget', 'hasOwnProperty']) {
        const b = d.createElement('button');
        b.setAttribute('data-kb-aktion', name);
        d.body.appendChild(b);
        try { b.click(); } catch (e) { getroffen += 100; }
    }
    w.removeEventListener('error', wurf);
    pruefe(getroffen === 0, 'unbekannte/geerbte Aktionsnamen tun nichts', 'getroffen=' + getroffen);
}

// ── vision.js ───────────────────────────────────────────────────────────────
console.log('== vision.js ==');
{
    // Mit Apostroph und &: genau das, was das alte '${p.id}'-Literal brach.
    // KEIN '"': id="vis-test-${p.id}" und data-profile stehen im Renderer
    // (Bestand, nicht Teil von H4) unmaskiert - ein " zerlegt dort den Tag.
    const pid = `p'1&2`;
    vm._renderProfilesList([{ id: pid, name: 'Anna', action: 'greet', num_images: 3 }],
        [{ id: 'greet', label: 'Gruessen' }, { id: 'webhook', label: 'Webhook' }]);
    const liste = d.getElementById('vis-profiles-list');
    pruefe(onAttribute(liste).length === 0, 'Profilliste ohne on*-Attribut', onAttribute(liste).join(', '));
    const auf = spione(vm, ['_testGreetAudio', '_deleteProfile', '_saveInlineAction', '_onInlineActionChange']);
    for (const a of ['testGreetAudio', 'deleteProfile', 'saveInlineAction']) {
        const k = liste.querySelector(`[data-vis-aktion="${a}"]`); k && k.click();
    }
    pruefe(auf.length === 3 && auf.every(x => x[1][0] === pid),
        'Test/Loeschen/Speichern mit unveraenderter Profil-ID', JSON.stringify(auf));
    auf.length = 0;
    const sel = liste.querySelector('.vis-action-select');
    sel.value = 'webhook';
    sel.dispatchEvent(new w.Event('change', { bubbles: true }));
    pruefe(auf.length === 1 && auf[0][1][0] === sel, 'Aktionswahl: change -> _onInlineActionChange(this)');
    // _editProfile ist ECHT (nicht bespitzelt): es findet den Namen ueber data-vis-id
    const modal = d.createElement('div'); modal.id = 'vis-profile-modal'; modal.style.display = 'none';
    modal.innerHTML = '<input id="vis-modal-name">'; d.body.appendChild(modal);
    liste.querySelector('[data-vis-aktion="editProfile"]').click();
    pruefe(d.getElementById('vis-modal-name').value === 'Anna' && modal.style.display === 'flex',
        'Bearbeiten oeffnet den Dialog mit dem Profilnamen', d.getElementById('vis-modal-name').value);

    // onerror: Fehler-Ereignis am Bild (wie vom Browser, ohne Bubbling)
    const thumb = liste.querySelector('.vis-profile-thumb');
    thumb.dispatchEvent(new w.Event('error'));
    pruefe(thumb.getAttribute('src').startsWith('data:image/svg+xml,<svg'),
        'Profilbild: Ladefehler setzt den Platzhalter', thumb.getAttribute('src').slice(0, 40));
    vm._renderDetectedFaces([{ name: 'Anna', confidence: 0.9 }]);
    const crop = d.querySelector('#vis-detected-faces .vis-face-crop');
    pruefe(onAttribute(d.getElementById('vis-detected-faces')).length === 0, 'Gesichter ohne on*-Attribut');
    crop.dispatchEvent(new w.Event('error'));
    pruefe(crop.style.display === 'none', 'Gesichtsausschnitt: Ladefehler blendet aus');
}

// ── google.js ──────────────────────────────────────────────────────────────
console.log('== google.js ==');
{
    const c = d.getElementById('google-status-container');
    c.innerHTML = gm._renderJarvisSection({ configured: true, authenticated: true, email: 'a@beispiel.de' })
                + gm._renderJarvisSection({ configured: true, authenticated: false });
    pruefe(onAttribute(c).length === 0, 'Google-Karten ohne on*-Attribut', onAttribute(c).join(', '));
    const auf = spione(gm, ['revokeJarvis', 'connectJarvis', '_renderAll', '_stopDevicePoll']);
    const r = c.querySelector('[data-gm-aktion="revokeJarvis"]'); r && r.click();
    const k = c.querySelector('[data-gm-aktion="connectJarvis"]'); k && k.click();
    const b = d.createElement('button'); b.setAttribute('data-gm-aktion', 'abbrechenPoll'); c.appendChild(b); b.click();
    pruefe(auf.map(x => x[0]).join() === 'revokeJarvis,connectJarvis,_stopDevicePoll,_renderAll',
        'Trennen, Verbinden, Abbrechen (Poll stoppen, dann neu zeichnen)', JSON.stringify(auf.map(x => x[0])));
}

console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
dom.window.close();
process.exit(fail ? 1 : 0);
