/* ═══════════════════════════════════════════════════════════════════
   Avatar-Assistent – Frontend-Widget
   ───────────────────────────────────────────────────────────────────
   Zeigt eine sprechende Figur (Clippy-Sprite via clippy.js ODER einen
   SVG-Platzhalter) mit eigener Text-/Spracheingabe. Anfragen laufen ueber
   /api/avatar/ask (serverseitiger Override-Abgleich, sonst Agent). Bei
   Spracheingabe wird die Antwort zusaetzlich per /api/tts vorgelesen.

   Aktiv nur, wenn der Avatar-Skill eingeschaltet ist (/api/avatar/config
   liefert active:true). Eingebunden in chat.html (spaeter portal/support).
   Externe Abhaengigkeit: jQuery + clippy.min.js (nur fuer die Sprite-Figur),
   beide selbst gehostet unter /static/vendor/clippy/.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // ── Hilfen ──────────────────────────────────────────────────────
    function token() {
        // Gleiche Reihenfolge wie support.js::TOKEN_KEYS – je nach Seite liegt
        // das Sitzungstoken unter einem anderen Schluessel.
        return localStorage.getItem('jarvis_token')
            || localStorage.getItem('jarvis_chat_token')
            || localStorage.getItem('jarvis_uc_token') || '';
    }
    function T(key, fallback) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return fallback;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    // Escaped Text + klickbare URLs + Zeilenumbrueche
    function fmt(s) {
        var urls = [];
        var html = esc(s).replace(/(https?:\/\/[^\s<]+)/g, function (u) {
            var tail = ''; var m = u.match(/[)\].,;:!?]+$/);
            if (m) { tail = m[0]; u = u.slice(0, -tail.length); }
            urls.push('<a href="' + u + '" target="_blank" rel="noopener">' + u + '</a>' + tail);
            return '@@U' + (urls.length - 1) + '@@';
        });
        return html.replace(/@@U(\d+)@@/g, function (_, i) { return urls[+i]; });
    }
    // Markdown-Reste fuer die Sprachausgabe entfernen
    function stripForSpeech(s) {
        return String(s || '')
            .replace(/```[\s\S]*?```/g, ' ')
            .replace(/\[([^\]]+)\]\((?:https?:[^)]+)\)/g, '$1')
            .replace(/https?:\/\/\S+/g, '')
            .replace(/[*_`#>]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    var cfg = null;          // /api/avatar/config
    var brand = null;        // /api/branding (Logo + Marken-Name)
    var agent = null;        // clippy-Agent (falls graphic=clippy)
    var busy = false;
    var aborter = null;      // AbortController der laufenden Anfrage
    var stopped = false;     // true = Abbruch wurde vom Nutzer ausgeloest
    var recog = null;
    var listening = false;
    var els = {};

    // ── Start ───────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        if (!token()) return;   // nicht angemeldet
        fetch('/api/avatar/config', { headers: { 'Authorization': 'Bearer ' + token() } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.active) return;   // Skill aus
                cfg = d;
                // Der Schalter haengt NUR an dieser Antwort – nicht zusaetzlich
                // am Branding. Sonst erscheint er bei langsamem Netz spaet, und
                // wer den Avatar ausgeschaltet hat, sieht ihn erst gar nicht
                // (und kaeme nicht zurueck).
                injectToggle();
                if (istAus()) return;
                // Branding ist oeffentlich; ohne aktiven Branding-Skill kommt
                // {active:false} und alle Rueckfaelle greifen wie bisher.
                return fetch('/api/branding')
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .catch(function () { return null; })
                    .then(function (bd) { brand = bd; build(); });
            })
            .catch(function () {});
    });

    // ── Ein/Aus je Seite ────────────────────────────────────────────
    // Der Zustand haengt am Pfad, nicht global: der Avatar soll z.B. im Chat
    // stoeren duerfen und im Portal sichtbar bleiben (Vorgabe „pro Seite").
    var AUS_KEY = 'jarvis_avatar_off:';
    var toggleBtn = null;

    function seitenSchluessel() {
        return AUS_KEY + ((location.pathname || '/').replace(/\/+$/, '') || '/');
    }
    function istAus() {
        try { return localStorage.getItem(seitenSchluessel()) === '1'; } catch (e) { return false; }
    }
    function setzeAus(aus) {
        try {
            if (aus) localStorage.setItem(seitenSchluessel(), '1');
            else localStorage.removeItem(seitenSchluessel());
        } catch (e) {}
    }

    // Sichtbarer Zustand: durchgestrichenes Symbol = Avatar aus
    var SVG_AN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"'
        + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        + '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'
        + '<circle cx="9.5" cy="11" r="1"/><circle cx="14.5" cy="11" r="1"/>'
        + '<path d="M9 14.5c.8.7 1.9 1 3 1s2.2-.3 3-1"/></svg>';
    var SVG_AUS = SVG_AN.replace('</svg>', '<line x1="3" y1="21" x2="21" y2="3"/></svg>');

    // Der Knopf wird zur Laufzeit eingehaengt und uebernimmt die Klassen des
    // Theme-Knopfes – so passt er ohne Extrawurst zum Stil JEDER Seite und
    // sitzt ueberall an derselben Stelle (direkt links davon).
    function injectToggle() {
        if (toggleBtn) return;
        var anker = document.getElementById('btn-theme-toggle')
                 || document.getElementById('btn-theme');   // /chat; NICHT btn-theme-login
        toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.id = 'jav-toggle';
        if (anker && anker.parentNode) {
            toggleBtn.className = anker.className;
            anker.parentNode.insertBefore(toggleBtn, anker);
        } else {
            // Seiten ohne Symbolleiste (z.B. /settings): frei schwebend oben rechts
            toggleBtn.className = 'jav-toggle-float';
            document.body.appendChild(toggleBtn);
        }
        toggleBtn.addEventListener('click', function () {
            var ausJetzt = !istAus();
            setzeAus(ausJetzt);
            zeichneToggle();
            if (ausJetzt) { destroy(); return; }
            // Beim Einschalten kann das Branding noch fehlen: es wird beim
            // Laden uebersprungen, wenn der Avatar aus ist. Ohne dieses
            // Nachladen bekaeme man Standardname statt Marke und kein Logo.
            if (brand !== null) { build(); return; }
            fetch('/api/branding')
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; })
                .then(function (bd) { brand = bd; build(); });
        });
        zeichneToggle();
    }

    function zeichneToggle() {
        if (!toggleBtn) return;
        var aus = istAus();
        toggleBtn.innerHTML = aus ? SVG_AUS : SVG_AN;
        toggleBtn.classList.toggle('jav-toggle-off', aus);
        var t = aus ? T('avatar.toggle_show', 'Avatar einblenden')
                    : T('avatar.toggle_hide', 'Avatar ausblenden');
        toggleBtn.title = t;
        toggleBtn.setAttribute('aria-label', t);
        toggleBtn.setAttribute('aria-pressed', aus ? 'false' : 'true');
    }

    // Widget vollstaendig abraeumen. Wichtig: laufende Sprite-Rueckrufe ueber
    // figurGen entwerten und die von clippy an <body> gehaengten Knoten
    // mitnehmen – sonst bleibt beim Ausschalten eine Figur stehen.
    function destroy() {
        clearTimeout(figurTimer);
        figurGen++;
        if (els.root) els.root.remove();
        Array.prototype.forEach.call(
            document.querySelectorAll('body > .clippy, body > .clippy-balloon'),
            function (n) { n.remove(); });
        agent = null;
        busy = false;
        els = {};
    }

    // ── DOM aufbauen ────────────────────────────────────────────────
    function build() {
        if (els.root) return;          // schon aufgebaut (Doppelklick auf den Schalter)
        var root = document.createElement('div');
        root.id = 'jav-root';
        root.className = (cfg.position === 'bottom-left') ? 'jav-pos-bl' : 'jav-pos-br';
        // Auf Seiten mit eigener Eingabezeile am unteren Rand (/chat) sass die
        // Figur GENAU ueber dem Senden-Knopf und fing dessen Klicks ab.
        if (document.getElementById('chat-screen')) root.classList.add('jav-above-input');
        // Name: eigenes Feld > Branding (Assistenten- bzw. Firmenname) > Standard.
        // Ohne den Branding-Rueckfall hiesse die Figur in einer White-Label-
        // Installation "Assistent", waehrend der Rest der Seite die Marke traegt.
        var title = cfg.title
            || (brand && brand.active && (brand.assistant_name || brand.company_name))
            || T('avatar.title_default', 'Assistent');
        root.innerHTML =
            '<div id="jav-panel" class="jav-hidden">'
            + '  <div id="jav-grip" title="' + esc(T('avatar.resize', 'Größe ändern')) + '"></div>'
            + '  <div class="jav-header"><span class="jav-dot"></span>'
            + '    <span id="jav-title"></span>'
            + '    <button id="jav-close" title="' + esc(T('avatar.close', 'Schließen')) + '">×</button>'
            + '  </div>'
            + '  <div id="jav-log"></div>'
            + '  <div class="jav-input">'
            + '    <button id="jav-mic" class="jav-ibtn" title="' + esc(T('avatar.mic', 'Sprechen')) + '">🎤</button>'
            + '    <input id="jav-text" type="text" autocomplete="off" placeholder="' + esc(T('avatar.placeholder', 'Frag mich etwas…')) + '">'
            + '    <button id="jav-send" class="jav-ibtn" title="' + esc(T('avatar.send', 'Senden')) + '">➤</button>'
            + '    <button id="jav-stop" class="jav-ibtn jav-hidden" title="' + esc(T('avatar.stop', 'Abbrechen')) + '">■</button>'
            + '  </div>'
            + '</div>'
            + '<div id="jav-figure" title="' + esc(title) + '"></div>';
        document.body.appendChild(root);

        els.root = root;
        els.panel = root.querySelector('#jav-panel');
        els.log = root.querySelector('#jav-log');
        els.figure = root.querySelector('#jav-figure');
        els.text = root.querySelector('#jav-text');
        els.mic = root.querySelector('#jav-mic');
        els.send = root.querySelector('#jav-send');
        els.stop = root.querySelector('#jav-stop');
        els.grip = root.querySelector('#jav-grip');
        root.querySelector('#jav-title').textContent = title;

        // Ereignisse
        els.figure.addEventListener('click', toggle);
        root.querySelector('#jav-close').addEventListener('click', function () { setOpen(false); });
        els.send.addEventListener('click', sendFromInput);
        els.stop.addEventListener('click', stopRun);
        els.text.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); sendFromInput(); }
        });
        els.mic.addEventListener('click', toggleMic);
        initResize();

        renderFigure();

        if (cfg.auto_open) setTimeout(function () { setOpen(true); }, 400);
    }

    // ── Groesse aendern + merken ────────────────────────────────────
    // Gespeichert wird im localStorage, gilt also fuer den Browser dieses
    // Nutzers und ueberdauert die Sitzung.
    var SIZE_KEY = 'jarvis_avatar_size';
    var MIN_W = 260, MIN_H = 120;

    function maxW() { return Math.max(MIN_W, window.innerWidth - 36); }
    function maxH() { return Math.max(MIN_H, Math.round(window.innerHeight * 0.75)); }

    function loadSize() {
        try {
            var d = JSON.parse(localStorage.getItem(SIZE_KEY) || 'null');
            if (d && d.w && d.h) return d;
        } catch (e) {}
        return null;
    }

    // Breite ans Panel, Hoehe an den Nachrichtenbereich.
    // WICHTIG: die Hoehe darf NICHT als Inline-Stil am Panel haengen – beim
    // Schliessen klappt es ueber `.jav-hidden { height: 0 }` ein, und ein
    // Inline-Wert wuerde diese Regel ueberstimmen (das Panel bliebe offen).
    function applySize(w, h) {
        w = Math.max(MIN_W, Math.min(w, maxW()));
        h = Math.max(MIN_H, Math.min(h, maxH()));
        els.panel.style.width = w + 'px';
        els.log.style.height = h + 'px';
        els.log.style.maxHeight = 'none';   // sonst kappt die 46vh-Regel
        return { w: w, h: h };
    }

    function initResize() {
        var s = loadSize();
        if (s) applySize(s.w, s.h);

        var startX = 0, startY = 0, startW = 0, startH = 0, aktiv = false;
        var links = !els.root.classList.contains('jav-pos-bl');  // Griff links?

        els.grip.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            aktiv = true;
            startX = e.clientX; startY = e.clientY;
            startW = els.panel.getBoundingClientRect().width;
            startH = els.log.getBoundingClientRect().height;
            document.body.classList.add('jav-resizing');
            try { els.grip.setPointerCapture(e.pointerId); } catch (err) {}
        });

        els.grip.addEventListener('pointermove', function (e) {
            if (!aktiv) return;
            // Das Widget haengt unten rechts (bzw. links). Zieht man den Griff
            // nach oben/aussen, wird es GROESSER – daher die Vorzeichen.
            var dx = links ? (startX - e.clientX) : (e.clientX - startX);
            applySize(startW + dx, startH + (startY - e.clientY));
        });

        function ende(e) {
            if (!aktiv) return;
            aktiv = false;
            document.body.classList.remove('jav-resizing');
            try { els.grip.releasePointerCapture(e.pointerId); } catch (err) {}
            try {
                localStorage.setItem(SIZE_KEY, JSON.stringify({
                    w: Math.round(els.panel.getBoundingClientRect().width),
                    h: Math.round(els.log.getBoundingClientRect().height)
                }));
            } catch (err) {}
        }
        els.grip.addEventListener('pointerup', ende);
        els.grip.addEventListener('pointercancel', ende);

        // Kleineres Fenster in der naechsten Sitzung: gespeicherte Groesse
        // wieder einpassen, sonst ragt das Panel aus dem Bild.
        // Nur EINMAL registrieren – build() laeuft beim Ein-/Ausschalten erneut,
        // sonst sammeln sich Zuhoerer auf einem laengst entfernten Panel.
        if (!resizeGebunden) {
            resizeGebunden = true;
            window.addEventListener('resize', function () {
                if (!els.panel || !els.panel.style.width) return;
                applySize(parseInt(els.panel.style.width, 10) || MIN_W,
                          parseInt(els.log.style.height, 10) || MIN_H);
            });
        }
    }
    var resizeGebunden = false;

    // ── Figur rendern ───────────────────────────────────────────────
    // Reihenfolge: gewaehlte Figur → RUECKFALL 'Clippy' → SVG-Platzhalter.
    // Clippy ist der ausdrueckliche Rueckfall (Vorgabe 2026-07-30); der
    // SVG-Platzhalter greift nur noch, wenn auch Clippy nicht kommt – eine
    // leere Ecke darf es nie geben.
    var FALLBACK = 'Clippy';
    var figurGen = 0;          // zaehlt Renderversuche (verwaiste Rueckrufe verwerfen)
    var figurTimer = null;
    // Wartezeit, bevor der Platzhalter als LADEZUSTAND erscheint.
    // Er wurde frueher sofort gezeichnet – dadurch blitzte bei jedem
    // Seitenwechsel kurz eine ANDERE Figur auf, bevor die gewaehlte da war
    // (gemessen auf DEV: Sprite nach 73–147 ms, Aufblitzen 37–59 ms).
    // Deutlich darueber liegen heisst: im Normalfall sieht man ihn nie, bei
    // echter Verzoegerung aber schon – eine dauerhaft leere Ecke waere
    // schlimmer als ein spaeter Ladezustand.
    var PLACEHOLDER_DELAY = 1200;

    function renderFigure() {
        clearTimeout(figurTimer);

        if (cfg.graphic === 'placeholder') { placeholder(); return; }  // Wunschfigur

        if (cfg.graphic === 'branding' && brandLogo()) {
            // Bild per DOM setzen statt per innerHTML, damit ein kaputter
            // Logo-Link nicht als Bildruine stehenbleibt, sondern auf Clippy
            // zurueckfaellt (Rueckfallkette gilt auch hier).
            var img = document.createElement('img');
            img.className = 'jav-logo';
            img.id = 'jav-ph';
            img.alt = '';
            img.addEventListener('error', function () { loadSprite(FALLBACK, true); });
            img.src = brandLogo();
            els.figure.innerHTML = '';
            els.figure.appendChild(img);
            return;
        }

        figurTimer = setTimeout(function () {
            if (!els.figure.firstChild) placeholder();
        }, PLACEHOLDER_DELAY);

        if (cfg.graphic === 'branding') {
            loadSprite(FALLBACK, true);                 // kein Logo -> Clippy
            return;
        }
        loadSprite(cfg.is_sprite ? cfg.graphic : FALLBACK, !cfg.is_sprite);
    }

    // Laedt einen Sprite-Satz. Scheitert er ODER bleibt er haengen, wird EINMAL
    // auf Clippy zurueckgefallen. Das Haengen ist real: steht in `sounds-mp3.js`
    // ein anderer Agentenname als im Ordner, ruft clippy WEDER den Erfolgs- noch
    // den Fehler-Rueckruf – ohne Zeitgrenze bliebe es fuer immer beim Platzhalter.
    function loadSprite(name, istRueckfall) {
        if (!window.clippy) return;                     // Platzhalter bleibt
        var gen = ++figurGen;
        var erledigt = false;

        function gescheitert() {
            if (erledigt || gen !== figurGen) return;
            erledigt = true;
            if (!istRueckfall && name !== FALLBACK) loadSprite(FALLBACK, true);
        }

        try {
            window.clippy.BASE_PATH = (cfg.assets_base || '/static/vendor/clippy') + '/agents/';
            window.clippy.load(name, function (ag) {
                if (gen !== figurGen) return;           // ueberholter Versuch
                erledigt = true;
                clearTimeout(figurTimer);               // kein Ladezustand mehr noetig
                agent = ag;
                try { ag.show(true); } catch (e) {}
                // clippy haengt sein Element an <body>; bevorzugt das Element
                // DIESES Agenten nehmen – bei einem Rueckfall liegen sonst zwei
                // `.clippy`-Knoten herum und man erwischt den falschen.
                var cl = (ag && ag._el && ag._el[0]) || document.querySelector('body > .clippy');
                if (cl && els.figure) {
                    els.figure.innerHTML = '';          // Platzhalter ersetzen
                    els.figure.appendChild(cl);
                    // KEIN eigener Klick-Handler auf dem Sprite: der Klick
                    // blubbert zu #jav-figure, das schon `toggle` traegt. Ein
                    // zweiter Handler hier schaltete zweimal um – unterm Strich
                    // gar nicht, und ein Klick direkt auf Clippy tat nichts
                    // (nur der schmale Rand daneben wirkte).
                }
                // verwaiste Knoten des gescheiterten Versuchs entfernen
                Array.prototype.forEach.call(
                    document.querySelectorAll('body > .clippy'),
                    function (n) { if (n !== cl) n.remove(); });
            }, gescheitert);
        } catch (e) { gescheitert(); return; }

        setTimeout(gescheitert, 6000);
    }

    // Logo aus dem Branding-Skill (Hell-Variante faellt auf Dunkel zurueck).
    // Leer, wenn kein Branding aktiv ist -> dann greift der SVG-Platzhalter,
    // damit "branding" ohne hinterlegtes Logo keine leere Ecke hinterlaesst.
    function brandLogo() {
        if (!brand || !brand.active) return '';
        var hell = document.body && document.body.classList.contains('light');
        return (hell ? (brand.logo_url_light || brand.logo_url) : brand.logo_url) || '';
    }

    function placeholder() {
        els.figure.innerHTML =
            '<svg class="jav-ph" id="jav-ph" viewBox="0 0 96 96" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            + '<line class="jav-antenna" x1="48" y1="6" x2="48" y2="18" stroke="var(--accent,#6366f1)" stroke-width="3" stroke-linecap="round"/>'
            + '<circle class="jav-antenna" cx="48" cy="6" r="4" fill="var(--accent,#6366f1)"/>'
            + '<rect x="18" y="18" width="60" height="52" rx="14" fill="var(--bg-secondary,#232833)" stroke="var(--accent,#6366f1)" stroke-width="3"/>'
            + '<circle cx="36" cy="40" r="7" fill="#fff"/><circle cx="36" cy="41" r="3.4" fill="#1b1f27"/>'
            + '<circle cx="60" cy="40" r="7" fill="#fff"/><circle cx="60" cy="41" r="3.4" fill="#1b1f27"/>'
            + '<rect class="jav-mouth" x="38" y="54" width="20" height="7" rx="3.5" fill="var(--accent,#6366f1)"/>'
            + '<rect x="30" y="70" width="36" height="16" rx="6" fill="var(--bg-secondary,#232833)" stroke="var(--accent,#6366f1)" stroke-width="3"/>'
            + '</svg>';
    }

    // ── Oeffnen/Schliessen ──────────────────────────────────────────
    function setOpen(open) {
        els.panel.classList.toggle('jav-hidden', !open);
        if (open) {
            if (!els.log.dataset.greeted) {
                var g = cfg.greeting || T('avatar.greeting_default', 'Hallo! Wie kann ich helfen?');
                addBot(g);
                els.log.dataset.greeted = '1';
            }
            setTimeout(function () { els.text && els.text.focus(); }, 60);
        }
    }
    function toggle() { setOpen(els.panel.classList.contains('jav-hidden')); }

    // ── Nachrichten ─────────────────────────────────────────────────
    function addUser(text) {
        var d = document.createElement('div');
        d.className = 'jav-msg jav-msg-user';
        d.textContent = text;
        els.log.appendChild(d); scrollLog(); return d;
    }
    function addBot(text) {
        var d = document.createElement('div');
        d.className = 'jav-msg jav-msg-bot';
        d.innerHTML = fmt(text);
        els.log.appendChild(d); scrollLog(); return d;
    }
    function addThinking() {
        var d = document.createElement('div');
        d.className = 'jav-msg jav-msg-bot jav-thinking';
        d.innerHTML = esc(T('avatar.thinking', 'Denke nach')) + '<span class="jav-dots"></span>';
        els.log.appendChild(d); scrollLog(); return d;
    }
    function scrollLog() { els.log.scrollTop = els.log.scrollHeight; }

    // ── Senden ──────────────────────────────────────────────────────
    function sendFromInput() {
        var v = (els.text.value || '').trim();
        if (!v) return;
        els.text.value = '';
        ask(v, false);
    }

    function ask(text, viaVoice) {
        if (busy) return;
        busy = true;
        setBusyUi(true);
        setOpen(true);
        addUser(text);
        var think = addThinking();
        gesture('think');

        aborter = ('AbortController' in window) ? new AbortController() : null;
        stopped = false;

        fetch('/api/avatar/ask', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, voice: !!viaVoice }),
            signal: aborter ? aborter.signal : undefined
        }).then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
        }).then(function (res) {
            think.remove();
            if (!res.ok) {
                if (res.status === 423) { addBot(T('avatar.blocked', 'Konto gesperrt (Sicherheitsverstoß).')); }
                else if (res.status === 401) { addBot(T('avatar.reauth', 'Bitte neu anmelden.')); }
                else { addBot((res.d && res.d.detail) || T('avatar.error', 'Es ist ein Fehler aufgetreten.')); }
                gesture('idle');
                return;
            }
            var ans = (res.d && res.d.answer) || '';
            // Serverseitig abgebrochen: eine Teilantwort ist besser als nichts,
            // wird aber NICHT vorgelesen (der Nutzer wollte ja Ruhe).
            if (res.d && res.d.stopped) {
                addBot(ans ? ans : T('avatar.stopped', 'Abgebrochen.'));
                gesture('idle');
                return;
            }
            addBot(ans || T('avatar.empty', '(keine Antwort)'));
            gesture('answer');
            if (viaVoice && cfg.speak_on_voice && ans) speak(ans);
        }).catch(function (err) {
            think.remove();
            // Vom Abbrechen-Knopf ausgeloest -> kein Fehler, sondern Absicht.
            if (stopped || (err && err.name === 'AbortError')) {
                addBot(T('avatar.stopped', 'Abgebrochen.'));
            } else {
                addBot(T('avatar.error', 'Es ist ein Fehler aufgetreten.'));
            }
            gesture('idle');
        }).finally(function () {
            busy = false; aborter = null;
            setBusyUi(false);
        });
    }

    // Laufende Anfrage abbrechen: Server anweisen aufzuhoeren UND den fetch
    // abbrechen. Nur das Abbrechen im Browser wuerde den Agenten serverseitig
    // weiterlaufen lassen (verbrauchte Modell-Aufrufe ohne Empfaenger).
    function stopRun() {
        if (!busy) return;
        stopped = true;
        if (els.stop) els.stop.disabled = true;
        fetch('/api/avatar/stop', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token() }
        }).catch(function () {}).finally(function () {
            // Erst nach der Stop-Meldung abbrechen – sonst kann der Browser die
            // Verbindung schliessen, bevor der Server den Auftrag kennt.
            if (aborter) { try { aborter.abort(); } catch (e) {} }
        });
    }

    // Senden-/Abbrechen-Knopf tauschen (wie im Chat)
    function setBusyUi(on) {
        if (els.send) els.send.classList.toggle('jav-hidden', !!on);
        if (els.stop) {
            els.stop.classList.toggle('jav-hidden', !on);
            els.stop.disabled = false;
        }
        if (els.text) els.text.disabled = !!on;
        // Mikrofon waehrend eines Laufs sperren: ask() wuerde ohnehin abweisen,
        // ein klickbarer Knopf ohne Wirkung sieht aber nach einem Fehler aus.
        if (els.mic) els.mic.disabled = !!on;
    }

    // ── Figur-Gesten ────────────────────────────────────────────────
    function gesture(kind) {
        if (agent) {
            try {
                if (kind === 'think') play(['Thinking', 'Processing', 'GetAttention']);
                else if (kind === 'answer') play(['Explain', 'Congratulate', 'GestureRight', 'Wave']);
            } catch (e) {}
        }
    }
    function play(names) {
        if (!agent) return;
        var have = {};
        try { (agent.animations() || []).forEach(function (a) { have[a] = 1; }); } catch (e) { return; }
        for (var i = 0; i < names.length; i++) { if (have[names[i]]) { try { agent.play(names[i]); } catch (e) {} return; } }
    }

    // ── Sprachausgabe (TTS) ─────────────────────────────────────────
    function setTalking(on) {
        var ph = document.getElementById('jav-ph');
        if (ph) ph.classList.toggle('talking', !!on);
        if (on) play(['Explain', 'GestureRight']);
    }
    function speak(text) {
        var clean = stripForSpeech(text);
        if (!clean) return;
        var voice = localStorage.getItem('jarvis_chat_tts_voice') || '';
        fetch('/api/tts', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: clean, voice: voice })
        }).then(function (r) { return r.ok ? r.blob() : null; })
          .then(function (blob) {
              if (!blob) return;
              var url = URL.createObjectURL(blob);
              var a = new Audio(url);
              setTalking(true);
              a.onended = function () { setTalking(false); URL.revokeObjectURL(url); };
              a.onerror = function () { setTalking(false); URL.revokeObjectURL(url); };
              a.play().catch(function () { setTalking(false); });
          }).catch(function () {});
    }

    // ── Spracheingabe (Browser-STT) ─────────────────────────────────
    function toggleMic() {
        var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { addBot(T('avatar.no_mic', 'Spracheingabe wird von diesem Browser nicht unterstützt.')); setOpen(true); return; }
        if (listening) { try { recog && recog.stop(); } catch (e) {} return; }
        recog = new SR();
        recog.lang = 'de-DE';
        recog.continuous = false;
        recog.interimResults = false;
        recog.onstart = function () { listening = true; els.mic.classList.add('jav-listening'); setOpen(true); };
        recog.onerror = function () { stopMic(); };
        recog.onend = function () { stopMic(); };
        recog.onresult = function (e) {
            var t = '';
            for (var i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
            t = t.trim();
            stopMic();
            if (t) ask(t, true);   // via Mikrofon -> Antwort wird vorgelesen
        };
        try { recog.start(); } catch (e) { stopMic(); }
    }
    function stopMic() {
        listening = false;
        if (els.mic) els.mic.classList.remove('jav-listening');
    }
})();
