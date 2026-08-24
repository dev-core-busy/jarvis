/* Prompt-Pruefung: Knopf + Popup, gemeinsam fuer alle Formulare mit
 * gespeichertem Prompt (Short-Tracks-Ablage, E-Mail-Regel, Rollen-Agent).
 *
 * WARUM EIN BAUSTEIN UND NICHT DREI FASSUNGEN: der Knopf gehoert in jedes
 * Formular, dessen Text spaeter OHNE den Benutzer laeuft. Drei Kopien wuerden
 * beim naechsten Feinschliff auseinanderlaufen – dieselbe Lehre wie bei der
 * CPU-Anzeige, die in vier Fassungen vorlag und auf sechs Seiten fehlte.
 *
 * DELEGIERTER LISTENER AM DOKUMENT, kein Binden pro Knopf: die Formulare
 * werden bei jedem Oeffnen, bei jedem Sprachwechsel und nach jedem Speichern
 * neu aus einem HTML-String aufgebaut. Ein direkt gebundener Handler waere
 * danach weg – und der Knopf saehe funktionsfaehig aus, ohne zu wirken.
 */
(function () {
    'use strict';

    var POPUP_ID = 'jv-pc-pop';
    var _offen = false;
    var _feld = null;          // Textarea, in die "uebernehmen" schreibt
    var _beispiel = '';

    /* Dieselbe Form wie in tracks.js/email_portal.js: `window.t(key)` liefert
     * den Key zurueck, wenn er fehlt – dann gilt der Fallback. Platzhalter
     * ersetzt i18n hier NICHT, das macht der Aufrufer. */
    function T(key, fallback, vars) {
        var s = null;
        try { s = window.t ? window.t(key) : null; } catch (e) { s = null; }
        var out = (s && s !== key) ? s : (fallback || key);
        if (vars) {
            Object.keys(vars).forEach(function (k) {
                out = out.split('{' + k + '}').join(vars[k]);
            });
        }
        return out;
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                      '"': '&quot;', "'": '&#39;' })[c];
        });
    }

    /* Knopf-Markup fuer ein Formular. `klasse` uebernimmt den Stil der
     * Nachbarknoepfe (st-btn, em-btn, btn-secondary) – der Knopf soll sich
     * einreihen, nicht auffallen. */
    function knopfHtml(feldId, kontext, klasse) {
        return '<button type="button" class="jv-pc-btn ' + esc(klasse || '') + '"'
            + ' data-pc-feld="' + esc(feldId) + '"'
            + ' data-pc-kontext="' + esc(kontext) + '"'
            + ' data-i18n="promptcheck.btn"'
            + ' data-i18n-title="promptcheck.title"'
            + ' title="' + esc(T('promptcheck.title',
                'Den Text vom Modell prüfen lassen: wie er verstanden wird und was fehlt'))
            + '">' + esc(T('promptcheck.btn', 'Prompt prüfen')) + '</button>';
    }

    function popup() {
        var p = document.getElementById(POPUP_ID);
        if (p) { return p; }
        p = document.createElement('div');
        p.id = POPUP_ID;
        p.className = 'jv-pc-overlay';
        p.setAttribute('hidden', 'hidden');
        p.innerHTML =
            '<div class="jv-pc-box" role="dialog" aria-modal="true"'
          + ' aria-labelledby="jv-pc-head">'
          + '<div class="jv-pc-head">'
          + '<h3 id="jv-pc-head">' + esc(T('promptcheck.head', 'Prompt-Prüfung'))
          + '</h3>'
          + '<button type="button" class="btn-icon jv-pc-x"'
          + ' title="' + esc(T('promptcheck.close', 'Schließen')) + '"'
          + ' aria-label="' + esc(T('promptcheck.close', 'Schließen')) + '">'
          + (window.JarvisIcons && window.JarvisIcons.close
                ? window.JarvisIcons.close() : '&#10005;')
          + '</button></div>'
          + '<div class="jv-pc-body" id="jv-pc-body"></div>'
          + '<div class="jv-pc-foot">'
          + '<button type="button" class="btn-primary jv-pc-take" hidden>'
          + esc(T('promptcheck.take', 'Beispiel übernehmen')) + '</button>'
          + '<button type="button" class="btn-secondary jv-pc-close">'
          + esc(T('promptcheck.close', 'Schließen')) + '</button>'
          + '<span class="jv-pc-model" id="jv-pc-model"></span>'
          + '</div></div>';
        // DIREKTES KIND VON BODY: sonst erbt das Overlay Transformationen und
        // Stapelkontexte des Formulars und liegt womoeglich HINTER der Karte.
        document.body.appendChild(p);
        p.addEventListener('click', function (ev) {
            if (ev.target === p) { zu(); }            // Klick daneben
        });
        p.querySelector('.jv-pc-x').addEventListener('click', zu);
        p.querySelector('.jv-pc-close').addEventListener('click', zu);
        p.querySelector('.jv-pc-take').addEventListener('click', uebernehmen);
        return p;
    }

    function auf(inhaltHtml, modell) {
        var p = popup();
        p.querySelector('#jv-pc-body').innerHTML = inhaltHtml;
        var m = p.querySelector('#jv-pc-model');
        m.textContent = modell ? T('promptcheck.model', 'Modell: {m}', { m: modell }) : '';
        var take = p.querySelector('.jv-pc-take');
        if (_beispiel && _feld) { take.removeAttribute('hidden'); }
        else { take.setAttribute('hidden', 'hidden'); }
        p.removeAttribute('hidden');
        _offen = true;
        var f = p.querySelector('.jv-pc-close');
        if (f) { f.focus(); }
    }

    function zu() {
        var p = document.getElementById(POPUP_ID);
        if (p) { p.setAttribute('hidden', 'hidden'); }
        _offen = false;
    }

    function uebernehmen() {
        if (!_feld || !_beispiel) { zu(); return; }
        _feld.value = _beispiel;
        // `input` FEUERN: Zeichenzaehler, Formular-Spiegel und
        // Tab-Uebernahme haengen daran. Ohne das Ereignis steht der neue Text
        // da, und der Zaehler darunter zeigt die alte Laenge.
        try { _feld.dispatchEvent(new Event('input', { bubbles: true })); }
        catch (e) { /* aeltere Browser */ }
        _feld.focus();
        zu();
    }

    function liste(titel, punkte, klasse) {
        if (!punkte || !punkte.length) { return ''; }
        var li = punkte.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('');
        return '<div class="jv-pc-sect ' + klasse + '"><h4>' + esc(titel)
             + '</h4><ul>' + li + '</ul></div>';
    }

    function ergebnisHtml(d) {
        var h = '';
        if (d.gekuerzt) {
            h += '<p class="jv-pc-warn">' + esc(T('promptcheck.trunc',
                 'Der Entwurf war zu lang und wurde für die Prüfung gekürzt.')) + '</p>';
        }
        h += '<div class="jv-pc-sect"><h4>'
           + esc(T('promptcheck.interpretation', 'So wird der Prompt verstanden'))
           + '</h4><p>' + esc(d.interpretation || '') + '</p></div>';
        h += liste(T('promptcheck.assumptions', 'Offen – müsste geraten werden'),
                   d.annahmen, 'jv-pc-ass');
        h += liste(T('promptcheck.risks', 'Was dadurch schiefgehen kann'),
                   d.risiken, 'jv-pc-risk');
        if (d.beispiel) {
            h += '<div class="jv-pc-sect"><h4>'
               + esc(T('promptcheck.example', 'Vorschlag zur Bearbeitung'))
               + '</h4><pre class="jv-pc-pre">' + esc(d.beispiel) + '</pre></div>';
        }
        return h;
    }

    /* Dieselben Schluessel und dieselbe Reihenfolge wie in den Bereichsseiten –
     * der Baustein laeuft in /tracks, /email und /settings, und die legen ihr
     * Token unter verschiedenen Namen ab. */
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var v = localStorage.getItem(TOKEN_KEYS[i]);
                if (v) { return v; }
            } catch (e) { /* Speicher gesperrt */ }
        }
        return '';
    }

    async function pruefen(btn) {
        var feldId = btn.getAttribute('data-pc-feld') || '';
        var kontext = btn.getAttribute('data-pc-kontext') || '';
        _feld = document.getElementById(feldId);
        _beispiel = '';
        if (!_feld) {
            auf('<p class="jv-pc-warn">' + esc(T('promptcheck.nofield',
                'Das Prompt-Feld wurde nicht gefunden.')) + '</p>', '');
            return;
        }
        var text = (_feld.value || '').trim();
        if (!text) {
            auf('<p class="jv-pc-warn">' + esc(T('promptcheck.empty',
                'Es steht noch kein Text im Prompt-Feld.')) + '</p>', '');
            return;
        }
        var alt = btn.textContent;
        btn.disabled = true;
        btn.textContent = T('promptcheck.running', 'prüft …');
        try {
            var r = await fetch('/api/prompt/pruefen', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token()
                },
                body: JSON.stringify({
                    prompt: text, kontext: kontext,
                    lang: (window._lang === 'en') ? 'en' : 'de'
                })
            });
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok || !d.ok) {
                auf('<p class="jv-pc-warn">' + esc(d.error
                    || T('promptcheck.failed', 'Die Prüfung ist fehlgeschlagen.'))
                    + '</p>', '');
                return;
            }
            _beispiel = d.beispiel || '';
            auf(ergebnisHtml(d), d.modell || '');
        } catch (e) {
            auf('<p class="jv-pc-warn">' + esc(T('promptcheck.failed',
                'Die Prüfung ist fehlgeschlagen.')) + '</p>', '');
        } finally {
            btn.disabled = false;
            btn.textContent = alt;
        }
    }

    document.addEventListener('click', function (ev) {
        var b = ev.target && ev.target.closest
            ? ev.target.closest('.jv-pc-btn') : null;
        if (!b) { return; }
        ev.preventDefault();
        pruefen(b);
    });
    document.addEventListener('keydown', function (ev) {
        if (_offen && ev.key === 'Escape') { ev.stopPropagation(); zu(); }
    });

    window.JarvisPromptCheck = { knopfHtml: knopfHtml, schliessen: zu };
})();
