/* ============================================================================
 * model_caps.js – "Was kann dieses Modell?" im Profil-Formular
 *
 * Der ⓘ-Knopf in der PROFILZEILE (links vom Schloss-Knopf "Nutzung erlauben
 * fuer") fragt `POST /api/profiles/capabilities` ab und zeigt Text / Vision /
 * Werkzeuge / Denkmodus / Bilderzeugung / Einbettungen / Audio, dazu
 * Kontextfenster und Modellgroesse.
 *
 * ER SITZT IN DER LISTE, NICHT IM FORMULAR (auf Wunsch des Nutzers 2026-08-10):
 * die Frage "was kann dieses Modell" stellt man beim Vergleichen der Profile,
 * nicht beim Bearbeiten eines einzelnen. Die Werte kommen deshalb aus dem
 * Profil-Objekt und nicht aus Formularfeldern; den API-Key holt das Backend
 * ueber `profile_id` (er ist in `GET /api/profiles` maskiert).
 *
 * DAS PANEL WANDERT, es gibt aber nur EINEN Container – dasselbe Muster wie die
 * Rollen-Bearbeitung und die Extraktions-Vorschau in /wissen, mit denselben
 * Fallstricken: Heimatplatz nur beim ERSTEN Verschieben merken, und vor dem
 * Neuaufbau der Liste heimholen (sonst raeumt `innerHTML = ''` ihn mit ab).
 *
 * DREI ZUSTAENDE, NICHT ZWEI: ja · nein · unbekannt. Der letzte ist der
 * wichtigste – ein vLLM-Server nennt in `/v1/models` nur `max_model_len`, ueber
 * Vision sagt er NICHTS. Daraus "nein" zu machen waere eine Behauptung ueber
 * etwas, das nie abgefragt wurde (dieselbe Fehlerklasse wie der Trenner "Neue
 * Sitzung" oder der leere Profil-Umschalter).
 *
 * Fuer die unbekannten Faelle gibt es "Genauer pruefen": zwei echte
 * Mini-Anfragen (`max_tokens: 1`). Das ist der einzige Beweis, kostet aber
 * Tokens – deshalb ein eigener Knopf und keine Automatik. Auf DEV gemessen:
 * vLLM/Qwen 159 ms, Gemini 1,9 s.
 * ========================================================================== */

(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const tt = (k, f) => { try { return (window.t && window.t(k)) || f; } catch (e) { return f; } };
    const esc = (s) => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    let _letzte = null;      // letzte Antwort, damit die Probe sie ergaenzen kann
    let _aktuell = null;     // Profil, dessen Panel offen ist (fuer die Probe)
    let _probeLaeuft = false; // laeuft die Nachmessung? (Status in der Titelzeile)

    function headers() {
        return {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + (localStorage.getItem('jarvis_token') || ''),
        };
    }

    /* Anfrage-Rumpf aus dem PROFIL-Objekt der Liste.
     * `api_key` bleibt leer: `GET /api/profiles` maskiert ihn, und das Backend
     * nimmt bei leerem/maskiertem Wert den echten aus der Konfiguration
     * (main.py::_caps_key). Der Schluessel muss also nie durch den Browser. */
    function rumpf(p) {
        return {
            profile_id: p.id || '',
            provider: p.provider || '',
            api_url: p.api_url || '',
            model: p.model || '',
            auth_method: p.auth_method || 'api_key',
        };
    }

    const SYMBOL = { true: '✓', false: '✕', null: '?' };
    const KLASSE = { true: 'is-yes', false: 'is-no', null: 'is-unknown' };

    const BESCHRIFTUNG = {
        text: ['caps.text', 'Text / Chat'],
        vision: ['caps.vision', 'Bilder verstehen (Vision)'],
        tools: ['caps.tools', 'Werkzeug-Aufrufe (Function Calling)'],
        thinking: ['caps.thinking', 'Denkmodus (Reasoning)'],
        bild: ['caps.image', 'Bilder erzeugen'],
        embedding: ['caps.embedding', 'Einbettungen (Embeddings)'],
        audio: ['caps.audio', 'Audio-Ein-/Ausgabe'],
    };

    function zeile(schluessel, wert, geprobt) {
        const [k, f] = BESCHRIFTUNG[schluessel] || [null, schluessel];
        const s = String(wert);
        const marke = geprobt
            ? ` <span class="mc-probed" title="${esc(tt('caps.by_probe', 'durch echte Probe ermittelt'))}">●</span>`
            : '';
        return `<div class="mc-row ${KLASSE[s]}">`
             + `<span class="mc-mark">${SYMBOL[s]}</span>`
             + `<span class="mc-label">${esc(k ? tt(k, f) : f)}</span>${marke}</div>`;
    }

    function grenzenHtml(g) {
        if (!g) return '';
        const teile = [];
        const num = (n) => Number(n).toLocaleString(
            (window.currentLang === 'en' ? 'en-US' : 'de-DE'));
        if (g.kontext_tokens) teile.push(`${tt('caps.context', 'Kontext')}: ${num(g.kontext_tokens)} ${tt('caps.tokens', 'Token')}`);
        if (g.ausgabe_tokens) teile.push(`${tt('caps.output', 'Ausgabe')}: ${num(g.ausgabe_tokens)} ${tt('caps.tokens', 'Token')}`);
        if (g.parameter) teile.push(`${tt('caps.params', 'Größe')}: ${esc(g.parameter)}`);
        if (g.quantisierung) teile.push(`${tt('caps.quant', 'Quantisierung')}: ${esc(g.quantisierung)}`);
        if (g.familie) teile.push(`${tt('caps.family', 'Familie')}: ${esc(g.familie)}`);
        if (g.server) teile.push(`${tt('caps.server', 'Server')}: ${esc(g.server)}`);
        if (!teile.length) return '';
        return `<div class="mc-limits">${teile.map(esc).join(' · ')}</div>`;
    }

    const QUELLE_TEXT = {
        'google-models': 'Google-Modellliste',
        'ollama-show': 'Ollama /api/show (echte Capabilities)',
        'openai-models': 'OpenAI-kompatible Modellliste',
        'openrouter-models': 'OpenRouter-Modellliste',
        'anthropic-models': 'Anthropic-Modellliste',
    };

    function rendern(d, geprobt) {
        const box = $('model-caps-box');
        if (!box) return;
        const f = d.faehigkeiten || {};
        const unbekannt = Object.keys(f).filter(k => f[k] === null);

        // Die Probe laeuft AUTOMATISCH mit dem Klick auf ⓘ (Vorgabe des Nutzers
        // 2026-08-11) – kein eigener Knopf mehr. Waehrend sie laeuft, steht in der
        // Titelzeile ein Status, damit die springenden Werte erklaert sind.
        const status = _probeLaeuft
            ? `<span class="mc-probing">${esc(tt('caps.probing', 'prüfe Vision und Werkzeuge …'))}</span>`
            : '';

        let html = '';
        if (d.anzeige_name || d.modell || status) {
            html += `<div class="mc-title">`
                  + `<span>${esc(d.anzeige_name || d.modell)}</span>${status}</div>`;
        }
        if (d.beschreibung && d.beschreibung !== d.anzeige_name) {
            html += `<div class="mc-desc">${esc(d.beschreibung)}</div>`;
        }
        html += '<div class="mc-grid">';
        for (const k of Object.keys(BESCHRIFTUNG)) {
            if (!(k in f)) continue;
            html += zeile(k, f[k], geprobt && geprobt.indexOf(k) >= 0);
        }
        html += '</div>';
        html += grenzenHtml(d.grenzen);

        if (Array.isArray(d.roh) && d.roh.length) {
            html += `<div class="mc-raw">${esc(tt('caps.raw', 'Vom Anbieter gemeldet'))}: `
                  + `<code>${esc(d.roh.join(', '))}</code></div>`;
        }
        if (d.quelle) {
            html += `<div class="mc-src">${esc(tt('caps.source', 'Quelle'))}: `
                  + `${esc(QUELLE_TEXT[d.quelle] || d.quelle)}</div>`;
        }

        // "?" braucht eine Erklaerung, sonst liest es sich wie ein Fehler.
        if (unbekannt.length) {
            html += `<div class="mc-note">${esc(tt('caps.unknown_hint',
                'Ein „?" heißt: der Anbieter macht dazu keine Angabe – NICHT, '
                + 'dass das Modell es nicht kann.'))}</div>`;
        }
        for (const h of (d.hinweise || [])) {
            html += `<div class="mc-note">${esc(h)}</div>`;
        }
        for (const j of (d.jarvis || [])) {
            const cls = j.art === 'warn' ? 'mc-jarvis is-warn'
                      : (j.art === 'ok' ? 'mc-jarvis is-ok' : 'mc-jarvis');
            html += `<div class="${cls}">${esc(j.text)}</div>`;
        }

        // c) Der Punkt hinter einem Merkmal muss erklaert werden – ein Tooltip
        // allein ist unsichtbar, und ein unerklaertes Zeichen ist eine Zumutung.
        if (geprobt && geprobt.length) {
            html += `<div class="mc-legend"><span class="mc-probed">●</span> `
                  + esc(tt('caps.legend_probed',
                           'durch echte Testanfrage ermittelt (nicht aus der Anbieter-Auskunft)'))
                  + '</div>';
        }

        box.innerHTML = html;
        box.style.display = '';
        // ZWEITER Aufruf, nicht nur beim Oeffnen: das fertige Panel ist deutlich
        // hoeher als der Ladehinweis und ragt sonst wieder aus dem Sichtfenster.
        sichtbarMachen(box);
    }

    /* ── Das Panel wandert unter die angeklickte Karte ──────────────────────
     * Es gibt nur EINEN Container (`#model-caps-box`). Fallstricke wie bei der
     * Rollen-Bearbeitung (agent_roles.js) und der Extraktions-Vorschau:
     *  - Heimatplatz NUR beim ersten Verschieben merken; ein spaeteres Auslesen
     *    wuerde die verschobene Position als "Heimat" festschreiben.
     *  - Vor dem Neuaufbau der Liste heimholen (`heim()`), sonst raeumt
     *    `profilesContainer.innerHTML = ''` das Panel mit ab und
     *    `$('model-caps-box')` ist danach null.
     *  - KIND der Karte (`appendChild`), nicht Geschwister: nur so sieht es wie
     *    ein Teil der Zeile aus (Merkregel „wenn zwei Elemente wie eines
     *    aussehen sollen, gehoert eines INS andere").
     */
    /* ── Das geoeffnete Panel sichtbar machen ───────────────────────────────
     * GEMELDET (2026-08-11): "der geoeffnete Container wird nicht gescrollt, so
     * dass der Benutzer nicht direkt sieht, dass etwas geoeffnet wurde". Die
     * Karte waechst nach unten – steht sie am unteren Rand des Sichtfensters,
     * passiert scheinbar nichts.
     *
     * DER SCROLL-CONTAINER WIRD GESUCHT, NICHT ANGENOMMEN: normalerweise ist es
     * `.modal-body` (overflow-y: auto), im Vollbild-Modus des Einstellungs-
     * Dialogs aber setzt das CSS `overflow: visible !important` – dann scrollt
     * das FENSTER. Gleiches Muster wie `chatlib.js::__jarvisImgScroll`.
     *
     * FALLSTRICK, im Projekt schon bezahlt (Extraktions-Vorschau in /wissen,
     * 2026-07-28): `scrollTo(0, scrollHeight)` springt ans ENDE der Liste und
     * damit vom Panel WEG. Deshalb wird nur so weit gescrollt, wie noetig – und
     * NIE so weit, dass die OBERKANTE DER KARTE aus dem Blick gerät: sonst sieht
     * man Merkmale, ohne zu wissen, zu welchem Profil sie gehoeren. Ist alles
     * schon sichtbar, passiert nichts.
     */
    const _RAND = 12;

    function scrollElternteil(el) {
        let p = el && el.parentElement;
        while (p) {
            let oy = '';
            try { oy = getComputedStyle(p).overflowY; } catch (e) { /* detached */ }
            if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p;
            p = p.parentElement;
        }
        return null;                      // dann scrollt das Fenster
    }

    function sichtbarMachen(box) {
        if (!box) return;
        const karte = box.closest ? box.closest('.profile-card') : null;
        // Nach dem Setzen von innerHTML im naechsten Frame messen – vorher steht
        // die neue Hoehe noch nicht.
        const tun = () => {
            try {
                const c = scrollElternteil(box);
                const rb = box.getBoundingClientRect();
                const oben = c ? c.getBoundingClientRect().top : 0;
                const unten = c ? c.getBoundingClientRect().bottom : window.innerHeight;
                const noetig = rb.bottom - unten + _RAND;      // >0 = ragt hinaus
                if (noetig <= 0) return;                        // schon sichtbar
                // Deckel: die Oberkante der KARTE muss sichtbar bleiben – sonst
                // sieht man Merkmale, ohne zu wissen, zu welchem Profil sie
                // gehoeren (genau der Zustand, der gemeldet wurde). Faellt die
                // Karte weg, gilt die Oberkante des Panels.
                const bezug = karte ? karte.getBoundingClientRect() : rb;
                const spielraum = Math.max(0, bezug.top - oben - _RAND);
                const delta = Math.min(noetig, spielraum);
                if (delta <= 1) return;
                if (c) c.scrollBy({ top: delta, behavior: 'smooth' });
                else window.scrollBy({ top: delta, behavior: 'smooth' });
            } catch (e) { /* Scrollen ist Komfort, nie ein Grund zu scheitern */ }
        };
        if (window.requestAnimationFrame) window.requestAnimationFrame(tun);
        else setTimeout(tun, 16);
    }

    let _home = null;
    let _offenFuer = '';     // Profil-Id, fuer die das Panel gerade offen ist

    /* Das Panel wird KIND der angeklickten Profilkarte – dort, wo der Knopf ist.
     *
     * Die Liste hat keine Hoehenbegrenzung (siehe style.css) – die Karte waechst
     * also einfach mit, gescrollt wird im Dialog.
     *
     * Es gibt nur EINEN Container; Fallstricke wie beim Rollen-Formular:
     *  - Heimatplatz NUR beim ersten Verschieben merken.
     *  - Vor dem Neuaufbau der Liste heimholen (`heim()`), sonst raeumt
     *    `profilesContainer.innerHTML = ''` das Panel mit ab.
     */
    function platziere(karte) {
        const box = $('model-caps-box');
        if (!box) return null;
        if (!_home) _home = { parent: box.parentNode, next: box.nextSibling };
        document.querySelectorAll('.profile-card.is-caps').forEach(
            k => k.classList.remove('is-caps'));
        if (karte && karte.classList && karte.classList.contains('profile-card')) {
            karte.appendChild(box);              // KIND der Karte
            karte.classList.add('is-caps');
        } else if (_home.parent) {
            _home.parent.insertBefore(box, _home.next);
        }
        return box;
    }

    /* Von app.js VOR renderProfileList() gerufen. */
    function heim() {
        const box = $('model-caps-box');
        if (box) { box.style.display = 'none'; box.innerHTML = ''; }
        // Zurueck an den Heimatplatz AUSSERHALB der Liste – sonst nimmt
        // `profilesContainer.innerHTML = ''` das Panel mit ins Grab.
        if (box && _home && _home.parent) _home.parent.insertBefore(box, _home.next);
        // Die Markierung MUSS mit weg: eine abgesetzte Karte ohne Panel behauptet
        // einen Zustand, den es nicht gibt. (Beim Neuaufbau der Liste verschwinden
        // die Karten ohnehin – aber `heim()` darf auch allein aufgerufen werden.)
        document.querySelectorAll('.profile-card.is-caps').forEach(
            k => k.classList.remove('is-caps'));
        _offenFuer = ''; _letzte = null; _aktuell = null; _probeLaeuft = false;
    }

    function zu() {
        const box = $('model-caps-box');
        if (box) { box.style.display = 'none'; box.innerHTML = ''; }
        document.querySelectorAll('.profile-card.is-caps').forEach(
            k => k.classList.remove('is-caps'));
        platziere(null);
        _offenFuer = ''; _letzte = null; _aktuell = null; _probeLaeuft = false;
    }

    function meldung(text, fehler) {
        const box = $('model-caps-box');
        if (!box) return;
        box.innerHTML = `<div class="mc-note${fehler ? ' is-warn' : ''}">${esc(text)}</div>`;
        box.style.display = '';
        sichtbarMachen(box);
    }

    /* Der ⓘ-Knopf einer Profilzeile. `karte` = .profile-card, `p` = Profil. */
    async function fuerProfil(p, karte) {
        if (!p) return;
        // Zweiter Klick auf DASSELBE Profil schliesst (Umschalter). Ein Klick auf
        // ein anderes Profil laesst das Panel dorthin wandern und laedt neu.
        if (_offenFuer === p.id) { zu(); return; }
        const box = platziere(karte);
        if (!box) return;
        _offenFuer = p.id;
        _aktuell = p;
        if (!p.model) {
            meldung(tt('caps.no_model_profile',
                       'Dieses Profil hat kein Modell eingetragen.'), true);
            return;
        }
        meldung(tt('caps.loading', 'Frage den Anbieter …'));
        try {
            const r = await fetch('/api/profiles/capabilities',
                { method: 'POST', headers: headers(), body: JSON.stringify(rumpf(p)) });
            const j = await r.json();
            if (!r.ok) { meldung((j && j.detail) || ('HTTP ' + r.status), true); return; }
            _letzte = j;
            // Was die Metadaten offenlassen, wird SOFORT nachgemessen. Erst das
            // schnelle Ergebnis zeigen, dann nachtragen – sonst starrt man auf
            // einen Ladehinweis, obwohl die halbe Antwort schon da ist.
            const offen = Object.keys(j.faehigkeiten || {}).filter(
                k => j.faehigkeiten[k] === null && (k === 'vision' || k === 'tools'));
            _probeLaeuft = offen.length > 0;
            rendern(j, []);
            if (offen.length) probe(offen);
        } catch (e) {
            _probeLaeuft = false;
            meldung(tt('caps.failed', 'Abfrage fehlgeschlagen') + ': ' + e, true);
        }
    }

    /* Echte Mini-Anfragen fuer das, was die Metadaten offenlassen. Laeuft
     * automatisch im Anschluss an `fuerProfil` – der frueher noetige Knopf ist
     * entfallen. `max_tokens: 1` je Anfrage, gemessen 159 ms (vLLM) bis 1,9 s
     * (Gemini); der Kostenanteil ist damit vernachlaessigbar. */
    async function probe(welche) {
        if (!_aktuell || !welche || !welche.length) return;
        const fuer = _aktuell.id;
        try {
            const d = Object.assign(rumpf(_aktuell), { welche: welche });
            const r = await fetch('/api/profiles/capabilities/probe',
                { method: 'POST', headers: headers(), body: JSON.stringify(d) });
            const j = await r.json();
            // Der Benutzer kann waehrenddessen ein anderes Profil geoeffnet oder
            // die Box geschlossen haben – dann ist die Antwort veraltet.
            if (_offenFuer !== fuer) return;
            if (!r.ok) { meldung((j && j.detail) || ('HTTP ' + r.status), true); return; }
            const basis = _letzte || { faehigkeiten: {} };
            const geprobt = [];
            for (const k of Object.keys(j.faehigkeiten || {})) {
                // Ein `null` aus der Probe ("nicht pruefbar") darf einen
                // vorhandenen Metadaten-Wert NICHT ueberschreiben.
                if (j.faehigkeiten[k] === null) continue;
                basis.faehigkeiten[k] = j.faehigkeiten[k];
                geprobt.push(k);
            }
            basis.hinweise = (basis.hinweise || []).concat(j.hinweise || []);
            _letzte = basis;
            _probeLaeuft = false;
            rendern(basis, geprobt);
        } catch (e) {
            _probeLaeuft = false;
            meldung(tt('caps.failed', 'Abfrage fehlgeschlagen') + ': ' + e, true);
        }
    }

    // `bind` gibt es nicht mehr: den Knopf erzeugt app.js::renderProfileList
    // dynamisch und haengt den Handler direkt an – ein DOM-Bind beim Laden
    // fasste ins Leere, weil die Karten erst spaeter entstehen.
    window.ModelCaps = { fuerProfil: fuerProfil, heim: heim, zu: zu,
                         _rendern: rendern };
})();
