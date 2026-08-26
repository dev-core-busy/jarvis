#!/usr/bin/env node
/**
 * Signaturen und Antwort-Format in der Oberflaeche (2026-08-26).
 *
 * GEMELDET: "in dem Outlook-Add-In werden aktuell Entwuerfe im Text Format
 * erstellt. 'HTML', 'Text' und 'Rich-Text' sollten waehlbar sein. Ausserdem
 * soll auswaehlbar eine Signatur sein."
 *
 * Geprueft wird gegen die ECHTEN Dateien und mit WIRKLICH ausgefuehrtem Code -
 * eine Quelltext-Suche wuerde nur bestaetigen, dass die Zeile dasteht. Die
 * beiden Pulldown-Funktionen werden aus der Datei geschnitten und aufgerufen,
 * die Signatur-Liste wirklich gerendert und angeklickt.
 *
 * DREI AUSSAGEN, die nur hier pruefbar sind:
 *   1. Rich-Text erscheint, ist aber NICHT waehlbar - und nennt den Grund.
 *   2. Die Signatur steht NICHT im bearbeitbaren Textfeld, sondern als Hinweis
 *      "angehaengt wird ...". Sie ist eine Pflichtangabe; was im Textfeld
 *      steht, kann geaendert werden.
 *   3. Ein Klick auf "Speichern" des Postfachs fasst die Signatur-LISTE nicht
 *      an (sonst ueberschreiben zwei offene Fenster einander).
 *
 *   node tests/test_mail_sig_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const TASKPANE = fs.readFileSync(path.join(ROOT, 'frontend/addin/taskpane.html'), 'utf8');
const ADDINJS = fs.readFileSync(path.join(ROOT, 'frontend/addin/addin.js'), 'utf8');
const EMHTML = fs.readFileSync(path.join(ROOT, 'frontend/email.html'), 'utf8');
const EMJS = fs.readFileSync(path.join(ROOT, 'frontend/js/email_portal.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

/* Eine Funktion aus einer Datei schneiden und in einem eigenen Fenster
   ausfuehren. Geschnitten wird an der STRUKTUR (`\n    }` = Ende auf
   Einrueckungsebene 1), nicht "bis zum ersten }": die Funktionen enthalten
   selbst Bloecke, und ein zu kurzer Schnitt ergibt Code, der gar nicht laeuft -
   der Test waere dann trivial gruen (Fallstrick aus test_update_pill_ui.js). */
function schneide(quelle, name) {
    const von = quelle.indexOf('function ' + name + '(');
    if (von < 0) return null;
    const rest = quelle.slice(von);
    const bis = rest.indexOf('\n    }');
    return bis < 0 ? null : rest.slice(0, bis + 6);
}

function fenster(vorspann) {
    const dom = new JSDOM('<div id="x"></div>', { runScripts: 'outside-only' });
    dom.window.eval('function esc(s){return String(s==null?"":s)' +
        '.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")' +
        '.replace(/"/g,"&quot;");}' +
        'function T(k,f){return f;}' + (vorspann || ''));
    return dom;
}

(function () {

// ══════════════════════════════════════════════════════════════════════════
abschnitt('1. Format-Pulldown: Rich-Text sichtbar, aber abgeschaltet');
// ══════════════════════════════════════════════════════════════════════════
['addin.js', 'email_portal.js'].forEach(function (datei) {
    const quelle = datei === 'addin.js' ? ADDINJS : EMJS;
    const src = schneide(quelle, 'formatOptionen');
    pruefe(!!src, datei + ': formatOptionen gefunden und geschnitten');
    if (!src) return;
    const dom = fenster('var _konto = {antwort_format: ""};' + src);
    const w = dom.window;
    const h = w.eval('formatOptionen("")');

    // Der Eintrag ist da UND unbrauchbar. Beides muss gelten: weglassen liesse
    // die Frage "warum fehlt Rich-Text?" unbeantwortet, waehlbar machen waere
    // eine Behauptung.
    pruefe(/value="richtext"/.test(h), datei + ': Rich-Text steht im Pulldown');
    const rt = h.split('value="richtext"')[1] || '';
    pruefe(/^[^>]*\bdisabled\b/.test(rt), datei + ': ... und ist disabled', rt.slice(0, 80));
    pruefe(/title="[^"]*EWS[^"]*"/.test(rt) || /title="[^"]*winmail/.test(rt),
        datei + ': ... und nennt den Grund im title', rt.slice(0, 160));

    // Ein DOM-Test statt einer Zeichenkettenpruefung: nur so ist belegt, dass
    // der Browser den Eintrag wirklich als nicht waehlbar behandelt.
    const sel = w.document.getElementById('x');
    sel.innerHTML = '<select id="s">' + h + '</select>';
    const opts = Array.from(w.document.querySelectorAll('#s option'));
    const rtOpt = opts.filter(o => o.value === 'richtext')[0];
    pruefe(!!rtOpt && rtOpt.disabled === true,
        datei + ': im DOM ist die Option wirklich disabled');
    pruefe(opts.filter(o => !o.disabled).map(o => o.value).sort().join(',') === ',html,text',
        datei + ': waehlbar sind genau "", html, text',
        opts.filter(o => !o.disabled).map(o => o.value).join(','));

    // Die Vorgabe-Beschriftung MUSS sagen, WELCHES Format die Vorgabe ist -
    // "Vorgabe" allein ist eine Anzeige, die ihren Zustand verschweigt.
    pruefe(/Nur Text/.test(h.split('</option>')[0]),
        datei + ': die Vorgabe nennt das tatsaechliche Format (Text)');
    const dom2 = fenster('var _konto = {antwort_format: "html"};' + src);
    const h2 = dom2.window.eval('formatOptionen("")');
    pruefe(/HTML/.test(h2.split('</option>')[0]),
        datei + ': ... und folgt der Postfach-Vorgabe (HTML)');
    // Eine getroffene Wahl bleibt beim Neuzeichnen ausgewaehlt.
    const h3 = w.eval('formatOptionen("html")');
    pruefe(/value="html"[^>]*selected/.test(h3), datei + ': die Wahl bleibt erhalten');
    pruefe(!/value=""[^>]*selected/.test(h3),
        datei + ': dann ist NICHT zusaetzlich die Vorgabe vorgewaehlt');
    dom.window.close(); dom2.window.close();
});

// ══════════════════════════════════════════════════════════════════════════
abschnitt('2. Signatur-Pulldown: leer, "-" und die Standard-Markierung');
// ══════════════════════════════════════════════════════════════════════════
['addin.js', 'email_portal.js'].forEach(function (datei) {
    const quelle = datei === 'addin.js' ? ADDINJS : EMJS;
    const src = schneide(quelle, 'sigOptionen');
    pruefe(!!src, datei + ': sigOptionen gefunden');
    if (!src) return;
    const zwei = [{ id: 'a', name: 'Standard', standard: true, text: 'x' },
                  { id: 'b', name: 'Englisch', standard: false, text: 'y' }];
    const dom = fenster('var _signaturen = ' + JSON.stringify(zwei) + ';' + src);
    const w = dom.window;
    const h = w.eval('sigOptionen("")');
    pruefe(/value=""[^>]*selected/.test(h), datei + ': leer ist vorgewaehlt');
    pruefe(/Standard \*/.test(h),
        datei + ': der Standard steht als erster Eintrag mit *');
    // DER STANDARD DARF NICHT ZWEIMAL IN DER LISTE STEHEN - genau das war beim
    // Stil-Pulldown 2026-08-18 der gemeldete Fehler ("Standard - Standard").
    pruefe((h.match(/Standard/g) || []).length === 1,
        datei + ': der Standard erscheint GENAU EINMAL', h);
    pruefe(/value="b"/.test(h), datei + ': die uebrigen Signaturen sind gelistet');
    pruefe(/value="-"/.test(h), datei + ': "ohne Signatur" ist waehlbar');
    // Ohne hinterlegte Signatur gibt es kein "-" - es waere die Wahl zwischen
    // nichts und nichts.
    const dom2 = fenster('var _signaturen = [];' + src);
    const h0 = dom2.window.eval('sigOptionen("")');
    pruefe(!/value="-"/.test(h0), datei + ': ohne Signaturen kein "-"-Eintrag');
    pruefe(/keine Signatur/.test(h0), datei + ': ... sondern "keine Signatur"');
    const h2 = w.eval('sigOptionen("b")');
    pruefe(/value="b"[^>]*selected/.test(h2), datei + ': eine Wahl bleibt erhalten');
    // KEIN "automatisch": was fest angehaengt wird, soll kein Modell aussuchen.
    pruefe(!/value="auto"/.test(h) && !/automatisch/i.test(h),
        datei + ': KEIN "automatisch waehlen" (anders als beim Stil)');
    // Fremdtext wird maskiert - ein Signaturname ist Freitext.
    const dom3 = fenster('var _signaturen = ' +
        JSON.stringify([{ id: 'c', name: '<img src=x onerror=b()>', standard: true }]) +
        ';' + src);
    const h4 = dom3.window.eval('sigOptionen("")');
    pruefe(!/<img/.test(h4) && /&lt;img/.test(h4),
        datei + ': ein Name mit Markup wird maskiert', h4);
    dom.window.close(); dom2.window.close(); dom3.window.close();
});

// ══════════════════════════════════════════════════════════════════════════
abschnitt('3. Add-in: Signatur-Liste wird gerendert und ist bedienbar');
// ══════════════════════════════════════════════════════════════════════════
{
    // Das echte Aufgabenfenster mit dem echten addin.js. Nur so ist belegt,
    // dass Markup-IDs und Code zusammenpassen - genau da lag der Fehler, der
    // auf DEV die halbe Skills-Seite leer liess (icons.js fehlte im HTML).
    const dom = new JSDOM(TASKPANE, {
        url: 'https://x/addin/taskpane.html', runScripts: 'outside-only'
    });
    const w = dom.window;
    const gesendet = [];
    w.localStorage.setItem('jarvis_token', 'T');
    // EINE Quelle fuer den Kontostand: `/api/email/status` UND die Antwort von
    // `POST /api/email/account` liefern dasselbe Objekt. Die erste Fassung des
    // Tests liess den POST `{ok:true}` antworten - `_konto = a.konto || null`
    // wurde damit null, `kontoBereit()` false, und der Nachricht-Reiter zeigte
    // "hinterlege zuerst dein Postfach". Der Test suchte den Fehler dann im
    // Umbau. Ein Mock muss die ECHTE Antwortform haben (Register).
    const KONTO = {
        vorhanden: true, adresse: 'a@b.de', aktiv: true, kanal: 'ews',
        passwort_gesetzt: true, antwort_format: 'html', stile: [],
        signaturen: [
            { id: 's1', name: 'Standard', text: 'Max\nNexus AG', html: '', standard: true },
            { id: 's2', name: 'Mit Logo', text: 'Max', html: '<p><b>Max</b></p>',
              standard: false }
        ]
    };
    w.fetch = (u, o) => {
        o = o || {};
        gesendet.push({ url: String(u).split('?')[0], methode: o.method || 'GET',
                        rumpf: o.body ? JSON.parse(o.body) : null });
        const pfad = String(u).split('?')[0];
        const gib = (d) => Promise.resolve({ ok: true, status: 200,
                                            json: () => Promise.resolve(d) });
        if (pfad === '/api/me') return gib({ username: 'a', is_admin: false,
                                            permissions: { email: true } });
        if (pfad === '/api/email/status') {
            return gib({ ok: true, regeln: 0, bereiche: [], server: {},
                grenzen: { sig_name_max: 60, sig_text_max: 4000, sig_html_max: 60000 },
                konto: KONTO });
        }
        if (pfad === '/api/email/account') return gib({ ok: true, konto: KONTO });
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [], bereiche: [] });
        if (pfad === '/api/email/log') return gib({ ok: true, eintraege: [] });
        if (pfad === '/api/email/signatures') return gib({ ok: true, signaturen: [] });
        if (pfad === '/api/email/reply/preview') {
            return gib({ ok: true, text: 'Vielen Dank fuer Ihre Nachricht.',
                         an: 'kunde@firma.de', betreff: 'Re: Anfrage' });
        }
        if (pfad === '/api/email/reply/send') {
            return gib({ ok: true, ergebnis: 'Antwort als Entwurf gespeichert.' });
        }
        return gib({ ok: true });
    };
    // OHNE Office-Kontext wartet das Fenster OFFICE_WARTE_MS (4 s) und zeigt
    // WEDER Anmeldung NOCH Anwendung - der Test saehe ein leeres Fenster und
    // haette den Fehler im Umbau gesucht. Genau dafuer gibt es die Attrappe.
    w.Office = { onReady: (cb) => cb({}), context: { mailbox: { item: {
        itemId: 'AAA', subject: 'S', from: { emailAddress: 'x@y.de' } } } } };
    w.eval(I18N);
    w.eval(ADDINJS);

    setTimeout(function () {
        const d = w.document;
        const box = d.getElementById('ad-sigs');
        pruefe(!!box, 'der Container ad-sigs liegt im Markup');
        const karten = d.querySelectorAll('#ad-sigs [data-sig]');
        pruefe(karten.length === 2, 'beide Signaturen sind gerendert',
            String(karten.length));
        const txt = box ? box.textContent : '';
        pruefe(/Standard/.test(txt) && /Mit Logo/.test(txt), 'die Namen stehen da');
        pruefe(/HTML/.test(txt),
            'die Signatur MIT HTML-Fassung ist als solche markiert');
        // Der Muelleimer/Bearbeiten-Knopf muss existieren, sonst ist die Liste
        // eine Anzeige ohne Bedienung.
        const acts = d.querySelectorAll('#ad-sigs [data-act]');
        pruefe(acts.length >= 5,
            'Bedienelemente je Eintrag (Standard setzen, Bearbeiten, Loeschen)',
            String(acts.length));
        // Bearbeiten oeffnet das Formular DIREKT UNTER der Zeile - ein Formular
        // am Ende der Sektion gehoert zu keinem sichtbaren Eintrag.
        const edit = Array.from(d.querySelectorAll('#ad-sigs [data-act="edit"]'))[0];
        if (edit) edit.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        const f = d.getElementById('ad-sig-edit');
        pruefe(!!f && f.querySelector('#ad-g-name'), 'das Formular ist offen');
        pruefe(!!f && !!f.closest('[data-sig]'),
            'das Formular haengt IM Container der angeklickten Signatur');
        pruefe(!!d.getElementById('ad-g-text') && !!d.getElementById('ad-g-html'),
            'es hat BEIDE Felder (Text und HTML)');
        const nameFeld = d.getElementById('ad-g-name');
        pruefe(nameFeld && nameFeld.value === 'Standard',
            'die Werte sind belegt', nameFeld && nameFeld.value);
        // Ein zweiter Klick schliesst wieder (Umschalter, wie beim Stil).
        if (edit) edit.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        pruefe(!d.getElementById('ad-g-name'), 'ein zweiter Klick schliesst wieder');

        // Das Postfach-Formular kennt die Vorgabe und sendet sie mit - aber NIE
        // die Liste.
        const fmt = d.getElementById('ad-format');
        pruefe(!!fmt && fmt.value === 'html',
            'die Postfach-Vorgabe ist im Formular belegt', fmt && fmt.value);
        const rtOpt = fmt && Array.from(fmt.options).filter(o => o.value === 'richtext')[0];
        pruefe(!!rtOpt && rtOpt.disabled,
            'Rich-Text ist auch hier abgeschaltet');
        gesendet.length = 0;
        const speichern = d.getElementById('ad-save-acct');
        if (speichern) speichern.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        setTimeout(function () {
            const post = gesendet.filter(g => g.url === '/api/email/account' &&
                                              g.methode === 'POST')[0];
            pruefe(!!post, 'Speichern schickt das Konto');
            if (post) {
                pruefe(post.rumpf.antwort_format === 'html',
                    'das Format geht mit', JSON.stringify(post.rumpf.antwort_format));
                pruefe(!('signaturen' in post.rumpf),
                    'die LISTE geht NICHT mit (sonst ueberschreiben zwei Fenster einander)');
                pruefe(!('stile' in post.rumpf), 'die Stilliste ebenfalls nicht');
            }
            vorschau(w, d, gesendet);
        }, 60);
        // 600 ms, nicht 250: `officeErmitteln` fragt im 100-ms-Takt, bis der
        // Outlook-Kontext da ist. Vorher rendert der Nachricht-Reiter den Zweig
        // "keine Kennung geliefert" - der Test saehe keinen Antwort-Block und
        // haette den Fehler im Umbau gesucht.
    }, 600);
}

// ══════════════════════════════════════════════════════════════════════════
/* DER GEMELDETE FALL, ende zu ende durch den ECHTEN Code: erst "Antwort
   vorschlagen", dann die Pulldowns pruefen, dann "Als Entwurf" - und im
   abgeschickten Rumpf muessen Format und Signatur stehen. Eine
   Quelltext-Suche koennte nicht zeigen, dass die Felder auch wirklich
   erscheinen, wenn ein Vorschlag da ist. */
function vorschau(w, d, gesendet) {
    abschnitt('3b. Antwort-Vorschau: Format und Signatur beim Senden');
    const machen = d.getElementById('ad-reply-make');
    pruefe(!!machen, 'der Knopf "Antwort vorschlagen" ist da');
    // VOR dem Vorschlag gibt es die Pulldowns NICHT: sie gehoeren zum Versand,
    // nicht zum Formulieren.
    pruefe(!d.getElementById('ad-reply-fmt'),
        'vor dem Vorschlag kein Format-Pulldown (es gehoert zum Versand)');
    if (machen) machen.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    setTimeout(function () {
        const ta = d.getElementById('ad-reply-text');
        pruefe(!!ta && /Vielen Dank/.test(ta.value), 'der Vorschlag steht im Textfeld');
        // DIE SICHERHEITSAUSSAGE: die Signatur ist NICHT im Textfeld.
        pruefe(!!ta && !/Nexus AG/.test(ta.value) && !/Max/.test(ta.value),
            'die Signatur steht NICHT im bearbeitbaren Textfeld');
        const fmt = d.getElementById('ad-reply-fmt');
        const sig = d.getElementById('ad-reply-sig');
        pruefe(!!fmt && !!sig, 'beide Pulldowns erscheinen mit dem Vorschlag');
        const hinweis = d.getElementById('ad-reply-sighint');
        pruefe(!!hinweis && /Standard/.test(hinweis.textContent),
            'ein Hinweis nennt die Signatur, die angehaengt wird',
            hinweis && hinweis.textContent);
        // Umschalten auf "ohne Signatur" muss den Hinweis mitziehen - sonst
        // behauptet die Anzeige einen Zustand, den sie nicht mehr hat.
        if (sig) {
            sig.value = '-';
            sig.dispatchEvent(new w.Event('change', { bubbles: true }));
        }
        pruefe(!!hinweis && !/Standard/.test(hinweis.textContent),
            'nach "ohne Signatur" sagt der Hinweis das auch',
            hinweis && hinweis.textContent);
        // Und zurueck auf eine echte Signatur.
        if (sig) {
            sig.value = 's2';
            sig.dispatchEvent(new w.Event('change', { bubbles: true }));
        }
        pruefe(!!hinweis && /Mit Logo/.test(hinweis.textContent),
            'eine andere Signatur wird ebenfalls benannt',
            hinweis && hinweis.textContent);
        if (fmt) { fmt.value = 'html'; fmt.dispatchEvent(new w.Event('change', { bubbles: true })); }

        gesendet.length = 0;
        const entwurf = d.getElementById('ad-reply-draft');
        pruefe(!!entwurf, 'der Knopf "Als Entwurf" ist da');
        if (entwurf) entwurf.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
        setTimeout(function () {
            const post = gesendet.filter(g => g.url === '/api/email/reply/send')[0];
            pruefe(!!post, 'Senden geht an /api/email/reply/send');
            if (post) {
                pruefe(post.rumpf.format === 'html',
                    'das gewaehlte FORMAT geht mit', JSON.stringify(post.rumpf.format));
                pruefe(post.rumpf.signatur === 's2',
                    'die gewaehlte SIGNATUR geht mit (als Kennung)',
                    JSON.stringify(post.rumpf.signatur));
                pruefe(post.rumpf.entwurf === true, 'entwurf: true');
                pruefe(!('html' in post.rumpf) && !('signatur_text' in post.rumpf),
                    'KEIN Signaturtext und KEIN HTML im Rumpf');
            }
            w.close();
            ende();
        }, 80);
    }, 120);
}

// ══════════════════════════════════════════════════════════════════════════
function ende() {
    abschnitt('4. /email: Markup und Verdrahtung');
    // /email hat KEINE Antwort-Vorschau (die gibt es nur im Add-in) - hier
    // werden Signaturen gepflegt und je Regel gewaehlt.
    pruefe(/id="em-sigs-list"/.test(EMHTML), 'Container fuer die Liste');
    pruefe(/id="em-sig-edit"/.test(EMHTML), 'Container fuer das Formular');
    pruefe(/id="em-sig-neu"/.test(EMHTML), 'Knopf "Neue Signatur"');
    pruefe(/id="em-format"/.test(EMHTML), 'Pulldown fuer die Postfach-Vorgabe');
    pruefe(/id="em-help-sigs"/.test(EMHTML), 'Erklaerung (ⓘ) vorhanden');
    pruefe(EMHTML.indexOf('id="em-sigs-list"') > EMHTML.indexOf('id="em-stile-list"'),
        'die Signaturen stehen UNTER den Stilen (beides gehoert zum Antworten)');
    pruefe(/em-f-sig/.test(EMJS) && /em-f-fmt/.test(EMJS),
        'das Regel-Formular hat beide Felder');
    // Der Formular-Spiegel muss die neuen Felder kennen, sonst ist eine halb
    // getippte Regel nach einem Sprachwechsel weg (Register).
    // Geschnitten wird das ARRAY-LITERAL des Spiegels, nicht "ab dem zweiten
    // Vorkommen von em-f-betreff": das traf das Formular und nicht den Spiegel,
    // die Pruefung war damit falsch-rot. Ein Waechter, der ungefaehr schneidet,
    // misst fremden Code (Register).
    function spiegelArray(quelle, praefix) {
        const von = quelle.indexOf("'" + praefix + "-max'");
        if (von < 0) return '';
        const bis = quelle.indexOf(']', von);
        return bis < 0 ? '' : quelle.slice(von, bis);
    }
    const spiegel = spiegelArray(EMJS, 'em-f');
    pruefe(!!spiegel, 'der Formular-Spiegel von /email ist auffindbar');
    pruefe(/em-f-fmt/.test(spiegel) && /em-f-sig/.test(spiegel),
        'beide stehen im Formular-Spiegel (sonst ist eine halb getippte Regel '
        + 'nach einem Sprachwechsel weg)', spiegel);
    const spiegelAd = spiegelArray(ADDINJS, 'ad-f');
    pruefe(!!spiegelAd, 'der Formular-Spiegel des Add-ins ist auffindbar');
    pruefe(/ad-f-fmt/.test(spiegelAd) && /ad-f-sig/.test(spiegelAd),
        'im Add-in ebenso', spiegelAd);

    abschnitt('5. Die Signatur steht NICHT im bearbeitbaren Textfeld');
    // Das ist die Sicherheitsaussage: eine Pflichtangabe darf nicht in einem
    // Feld stehen, das der Benutzer (oder ein Skript) noch aendern kann. Sie
    // wird serverseitig angehaengt - deshalb MUSS ein Hinweis sagen, was kommt.
    const senden = ADDINJS.split('/api/email/reply/send', 2)[1] || '';
    pruefe(/signatur:/.test(senden.slice(0, 900)),
        'gesendet wird die KENNUNG der Signatur');
    pruefe(!/signatur_text|sigText/.test(ADDINJS),
        'nirgends wird ein Signatur-TEXT gesendet');
    pruefe(/sig_will_append/.test(ADDINJS) && /sig_will_none/.test(ADDINJS),
        'der Hinweis nennt beide Faelle (mit und ohne Signatur)');
    // Der Hinweis muss in BEIDEN Sprachen existieren.
    ['mail.sig_will_append', 'mail.sig_will_none', 'mail.fmt_rtf_why'].forEach(k => {
        pruefe((I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length === 2,
            'i18n ' + k + ' in DE und EN');
    });

    console.log('\n' + '='.repeat(62));
    console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
    console.log('='.repeat(62));
    process.exit(fail ? 1 : 0);
}

})();
