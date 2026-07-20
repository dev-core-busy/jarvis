/* ═══════════════════════════════════════════════════════════════════
   Branding / White-Label
   ───────────────────────────────────────────────────────────────────
   Wendet ein optionales Firmen-Branding (Name, Farben, Logo) zur
   Laufzeit an – ohne die HTML/CSS-Dateien zu verändern. Ist der
   Branding-Skill deaktiviert, liefert /api/branding {active:false} und
   das Standard-Jarvis-Design bleibt unangetastet.

   Eingebunden in index.html, chat.html und userchat.html.
   Der Admin-Teil (Einstellungs-Tab) initialisiert sich nur dort, wo
   das Tab-Markup vorhanden ist (index.html).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var CACHE_KEY = 'jarvis_branding_cache';

    // Zuletzt angewendetes Branding (fuer Theme-Wechsel + dynamische Avatare)
    var _current = null;

    // Aktueller Modus: Hell, wenn body.light gesetzt ist
    function currentIsLight() {
        return !!(document.body && document.body.classList.contains('light'));
    }

    // Theme-aufgeloeste Farben: Akzent markenweit (aus Dark), bg/text je Modus
    // mit Fallback auf die Dunkel-Werte.
    function effectiveColors(b, isLight) {
        var d = b.colors || {};
        if (!isLight) return d;
        var l = b.colors_light || {};
        return {
            accent: d.accent,
            accent_hover: d.accent_hover,
            bg_primary: l.bg_primary || d.bg_primary,
            bg_secondary: l.bg_secondary || d.bg_secondary,
            text_primary: l.text_primary || d.text_primary
        };
    }

    // Theme-aufgeloeste Logo-URL (Hell faellt auf Dunkel zurueck)
    function effectiveLogoUrl(b, isLight) {
        if (isLight) return b.logo_url_light || b.logo_url || '';
        return b.logo_url || '';
    }

    // Theme-aufgeloeste Namens-/Schriftzug-Logo-URL (ersetzt den Marken-Namen
    // durch ein Bild; Hell faellt auf Dunkel zurueck).
    function effectiveNameLogoUrl(b, isLight) {
        if (isLight) return b.name_logo_url_light || b.name_logo_url || '';
        return b.name_logo_url || '';
    }

    // ── Favicon (Browser-Tab-Icon) markensensitiv ──────────────────
    // Original-Favicon (Standard-Jarvis) wird gemerkt, damit resetBranding()
    // es exakt wiederherstellen kann.
    var _origFavicon = null;

    function faviconEl() {
        var el = document.querySelector('link[rel~="icon"]');
        if (!el) {
            el = document.createElement('link');
            el.rel = 'icon';
            document.head.appendChild(el);
        }
        return el;
    }

    // Erzeugt im Buchstaben-Modus ein Favicon (runder Akzent-Kreis + Initiale)
    function letterFavicon(letter, accent) {
        try {
            var size = 64;
            var cv = document.createElement('canvas');
            cv.width = size; cv.height = size;
            var ctx = cv.getContext('2d');
            ctx.fillStyle = accent || '#6366f1';
            ctx.beginPath();
            ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 38px system-ui, Arial, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText((letter || 'J').slice(0, 1).toUpperCase(), size / 2, size / 2 + 2);
            return cv.toDataURL('image/png');
        } catch (e) { return null; }
    }

    // Setzt das Favicon passend zum Branding (Bild-Logo bzw. Buchstaben-Icon).
    // Dedup ueber einen billigen Schluessel ZUERST – das teure Canvas/toDataURL
    // im Buchstaben-Modus wird nur bei tatsaechlicher Aenderung erzeugt
    // (applyBranding laeuft mehrfach: Cache, Fetch, setTimeout, load, themechange).
    function applyFavicon(b, logoUrl) {
        var key, type = 'image/png';
        if (b.logo_mode === 'image' && logoUrl) {
            key = 'img:' + logoUrl;
            if (/\.svg($|\?)/i.test(logoUrl)) type = 'image/svg+xml';
        } else if (b.core_letter) {
            key = 'ltr:' + b.core_letter + ':' + ((b.colors || {}).accent || '');
        } else {
            return;
        }
        var el = faviconEl();
        if (_origFavicon === null) _origFavicon = el.getAttribute('href') || '';
        if (el._brandKey === key) return; // unveraendert – kein Neu-Rendern
        var href = (b.logo_mode === 'image') ? logoUrl
            : letterFavicon(b.core_letter, (b.colors || {}).accent);
        if (!href) return;
        el._brandKey = key;
        el.setAttribute('type', type);
        el.setAttribute('href', href);
    }

    // Stellt das Standard-Jarvis-Favicon wieder her
    function resetFavicon() {
        if (_origFavicon === null) return;
        var el = faviconEl();
        el.setAttribute('type', 'image/png');
        if (_origFavicon) el.setAttribute('href', _origFavicon);
        else el.removeAttribute('href'); // es gab original kein Favicon
        el._brandKey = '';
        _origFavicon = null;
    }

    // ── Hilfsfunktionen ─────────────────────────────────────────────
    function hexToRgba(hex, alpha) {
        if (!hex) return null;
        var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
        if (!m) return null;
        var r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
        return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
    }

    // Liefert {r,g,b} aus einem Hex-Wert (oder null).
    function hexToRgb(hex) {
        if (!hex) return null;
        var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
        if (!m) return null;
        return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
    }

    // Konfig-Schlüssel → CSS-Variable(n)
    function applyColors(colors) {
        if (!colors) return;
        // Auf <body> setzen (nicht <html>), damit Branding-Farben auch das
        // body.light-Theme ueberschreiben (Inline gewinnt gegen Klassen-Regel).
        var root = (document.body || document.documentElement).style;
        if (colors.accent) {
            root.setProperty('--accent', colors.accent);
            var glow = hexToRgba(colors.accent, 0.4);
            var light = hexToRgba(colors.accent, 0.1);
            if (glow) root.setProperty('--accent-glow', glow);
            if (light) root.setProperty('--accent-light', light);
            // RGB-Tripel + abgeleitete Varianten, damit auch Toenungen
            // (Bubbles, Hover, Verlaeufe) der Markenfarbe folgen.
            var c = hexToRgb(colors.accent);
            if (c) {
                root.setProperty('--accent-rgb', c.r + ', ' + c.g + ', ' + c.b);
                var dark = function (v) { return Math.round(v * 0.78); };
                root.setProperty('--accent-dark', 'rgb(' + dark(c.r) + ', ' + dark(c.g) + ', ' + dark(c.b) + ')');
                if (!colors.accent_hover) {
                    var lite = function (v) { return Math.min(255, Math.round(v + (255 - v) * 0.25)); };
                    root.setProperty('--accent-hover', 'rgb(' + lite(c.r) + ', ' + lite(c.g) + ', ' + lite(c.b) + ')');
                }
            }
        }
        if (colors.accent_hover) root.setProperty('--accent-hover', colors.accent_hover);
        if (colors.bg_primary) root.setProperty('--bg-primary', colors.bg_primary);
        if (colors.bg_secondary) root.setProperty('--bg-secondary', colors.bg_secondary);
        if (colors.text_primary) root.setProperty('--text-primary', colors.text_primary);
    }

    // Setzt den Text reiner Marken-Labels (nicht über i18n gesteuert).
    // Originaltexte werden in data-brand-orig gemerkt, damit resetBranding()
    // beim Deaktivieren des Skills exakt den Ausgangszustand wiederherstellt.
    // skipVisualName: true, wenn ein Namens-Logo (Bild) die sichtbaren
    // Marken-Namen ersetzt – dann hier NICHT den Text setzen (das uebernimmt
    // applyNameLogo). Seitentitel/Placeholder/Begruessung nutzen weiter den Text.
    function setBrandLabels(name, skipVisualName) {
        if (!name) return;
        if (!skipVisualName) {
            // .topbar-title bewusst NICHT branden: dort steht der Seitenname
            // (Chat / Benutzerchat). Marke bleibt via Avatar-Logo, Farben und
            // Login-/Header-Titel erhalten.
            ['.login-title', '.header-title'].forEach(function (sel) {
                document.querySelectorAll(sel).forEach(function (el) {
                    if (el.dataset.brandOrig === undefined) el.dataset.brandOrig = el.textContent;
                    el.textContent = name;
                });
            });
        }
        // Seitentitel + Begrüßungs-/Hinweistexte: 'Jarvis' → Firmenname
        if (document.title) {
            if (window.__brandOrigTitle === undefined) window.__brandOrigTitle = document.title;
            document.title = document.title.replace(/jarvis/ig, name);
        }
        document.querySelectorAll('[placeholder]').forEach(function (el) {
            if (/jarvis/i.test(el.placeholder)) {
                if (el.dataset.brandOrigPh === undefined) el.dataset.brandOrigPh = el.placeholder;
                el.placeholder = el.placeholder.replace(/jarvis/ig, name);
            }
        });
        // Begrüßungszeilen werden NICHT hier (Firmenname) gebrandet, sondern in
        // applyAssistantName() mit dem separaten Assistenten-Namen.
        // Produkt-/Seitenname (z.B. /support, /portal): 'Jarvis' → Firmenname
        if (!skipVisualName) {
            document.querySelectorAll('.brand-app-name').forEach(function (el) {
                if (/jarvis/i.test(el.textContent)) {
                    if (el.dataset.brandOrig === undefined) el.dataset.brandOrig = el.textContent;
                    el.textContent = el.textContent.replace(/jarvis/ig, name);
                }
            });
        }
    }

    // Marken-Namen (Topbar/Header/Login/Seitenname) durch ein Schriftzug-Logo
    // (Bild) ersetzen. Ohne URL bleibt der Text-Name (via setBrandLabels).
    var NAME_LABEL_SELECTOR = '.login-title, .header-title, .brand-app-name';
    function applyNameLogo(b, url) {
        if (!url) return;
        document.querySelectorAll(NAME_LABEL_SELECTOR).forEach(function (el) {
            // Sub-Zeile auf /portal ('Wähle einen Bereich') nicht ersetzen
            if (el.classList.contains('brand-app-name-sub')) return;
            var existing = el.querySelector('img.brand-name-logo');
            if (existing && existing.getAttribute('src') === url) return;
            if (el.dataset.brandOrig === undefined) el.dataset.brandOrig = el.textContent;
            el.innerHTML = '';
            var img = document.createElement('img');
            img.src = url;
            img.alt = b.company_name || '';
            img.className = 'brand-name-logo';
            img.style.height = '1.4em';
            img.style.width = 'auto';
            img.style.maxWidth = '240px';
            img.style.objectFit = 'contain';
            img.style.verticalAlign = 'middle';
            img.style.display = 'inline-block';
            el.appendChild(img);
        });
    }

    // Macht jegliches angewandte Branding rueckgaengig → Standard-Jarvis-Design.
    // Wird bei /api/branding active:false und beim Deaktivieren des Skills gerufen.
    function resetBranding() {
        _current = null;
        window.brandAssistantName = '';   // TTS-Vorschau nutzt wieder 'Jarvis'
        // 1) Inline-CSS-Variablen entfernen (Themes/Defaults greifen wieder)
        var root = (document.body || document.documentElement).style;
        ['--accent', '--accent-glow', '--accent-light', '--accent-rgb',
         '--accent-dark', '--accent-hover', '--bg-primary', '--bg-secondary',
         '--text-primary'].forEach(function (p) { root.removeProperty(p); });
        // 2) Marken-Labels wiederherstellen
        document.querySelectorAll('[data-brand-orig]').forEach(function (el) {
            el.textContent = el.dataset.brandOrig;
            delete el.dataset.brandOrig;
        });
        document.querySelectorAll('[data-brand-orig-ph]').forEach(function (el) {
            el.placeholder = el.dataset.brandOrigPh;
            delete el.dataset.brandOrigPh;
        });
        if (window.__brandOrigTitle !== undefined) {
            document.title = window.__brandOrigTitle;
            window.__brandOrigTitle = undefined;
        }
        // 3) Logos/Avatare auf das Standard-'J' zuruecksetzen
        document.querySelectorAll(AVATAR_SELECTOR).forEach(function (core) {
            core.classList.remove('branding-logo-img');
            core._brandedUrl = '';
            core.style.background = '';
            core.textContent = 'J';
        });
        // 4) Favicon auf Standard-Jarvis zuruecksetzen
        resetFavicon();
        // 5) Portal-Animation ausblenden/entfernen
        var animWrap = document.getElementById('brand-portal-anim');
        if (animWrap) {
            var av = document.getElementById('brand-portal-video');
            if (av) { av.removeAttribute('src'); av._brandedSrc = ''; try { av.load(); } catch (e) {} }
            animWrap.style.display = 'none';
        }
        // 6) Kontakt-/Infozeile auf die eingebauten Defaults zuruecksetzen
        applyPortalContact(null);
    }

    // Alle runden „J"-Logo-/Avatar-Elemente, die gebrandet werden sollen
    // (Header-Ringe, Login-/Topbar-Avatare, User-Chat-Avatare und die
    // dynamischen Chat-Bubble-Avatare des Agent-Logs).
    // Nur „Jarvis/Marken"-Kreise branden – NICHT die per-Benutzer-Avatare
    // (.uc-avatar in /userchat zeigen User-Initialen, kein Firmenlogo).
    var AVATAR_SELECTOR = '.logo-core, .logo-mini-ring, .jv-bubble-avatar, ' +
                          '.msg-avatar, .topbar-avatar, .login-avatar';

    // Brandet ein einzelnes Kreis-Element (Bild oder Buchstabe)
    function brandOne(core, b, logoUrl) {
        if (b.logo_mode === 'image' && logoUrl) {
            if (core._brandedUrl === logoUrl) return; // schon gesetzt
            core._brandedUrl = logoUrl;
            // Neutraler (weisser) Hintergrund statt Akzent-Gradient – sonst
            // verschwindet ein Logo in Markenfarbe (z.B. rotes Logo auf rotem
            // Avatar). Markenlogos sind auf Weiss ausgelegt. NUR fuer die flachen
            // Avatar-Kreise – die Header-Ring-Kerne haben ihr eigenes Design.
            var isRingCore = core.classList.contains('logo-core') ||
                             core.classList.contains('logo-mini-core');
            var img = document.createElement('img');
            img.alt = b.company_name || 'Logo';
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '50%';
            // Bild erst NACH erfolgreichem Laden einwechseln – sonst ist der
            // Kreis fuer die Ladedauer leer (z.B. wenn der Server gerade eine
            // laengere Anfrage abarbeitet) bzw. bleibt bei veraltetem
            // localStorage-Cache/404 dauerhaft ohne Logo.
            img.onload = function () {
                if (core._brandedUrl !== logoUrl) return; // inzwischen gewechselt/zurueckgesetzt
                core.innerHTML = '';
                core.classList.add('branding-logo-img');
                if (!isRingCore) core.style.background = '#fff';
                core.appendChild(img);
            };
            img.onerror = function () {
                if (core._brandedUrl === logoUrl) core._brandedUrl = ''; // Retry beim naechsten apply
            };
            img.src = logoUrl;
        } else if (b.core_letter) {
            core.classList.remove('branding-logo-img');
            core._brandedUrl = '';
            core.style.background = '';   // Gradient/Standard wiederherstellen
            core.textContent = b.core_letter.slice(0, 2);
        }
    }

    // Ersetzt alle runden Logo-/Avatar-Elemente (Buchstabe oder Bild)
    function applyLogo(b, logoUrl) {
        document.querySelectorAll(AVATAR_SELECTOR).forEach(function (core) {
            brandOne(core, b, logoUrl);
        });
    }

    // Brandet ein einzelnes, dynamisch erzeugtes Avatar-Element.
    // Wird aus app.js beim Erstellen eines Chat-Bubble-Avatars aufgerufen.
    function brandAvatar(el) {
        if (!el || !_current || !_current.active) return;
        brandOne(el, _current, effectiveLogoUrl(_current, currentIsLight()));
    }

    // Portal-Animation (nur auf Seiten mit #brand-portal-anim, z.B. /portal):
    // Setzt die Videoquelle und blendet den Container ein, wenn ein Branding-
    // Video hinterlegt ist – sonst bleibt er ausgeblendet.
    function applyPortalVideo(b) {
        var wrap = document.getElementById('brand-portal-anim');
        if (!wrap) return;
        var vid = document.getElementById('brand-portal-video');
        var url = (b && b.active && b.portal_video_url) ? b.portal_video_url : '';
        if (url && vid) {
            if (vid._brandedSrc !== url) {
                vid._brandedSrc = url;
                vid.src = url;
                try { vid.play(); } catch (e) { /* Autoplay ggf. blockiert */ }
            }
            wrap.style.display = '';
        } else {
            if (vid) { vid.removeAttribute('src'); vid._brandedSrc = ''; try { vid.load(); } catch (e) {} }
            wrap.style.display = 'none';
        }
    }

    // ── Kontakt-/Infozeile der Portalseite (#pt-contact, nur /portal) ──
    // Ohne aktives Branding gelten die eingebauten Defaults (Info-Text via
    // i18n, Telefon leer, E-Mail dev-core@web.de). Bei aktivem Branding
    // zaehlen ausschliesslich die gepflegten Werte – leere Felder werden
    // ausgeblendet (White-Label ohne Kontaktangabe).
    var CONTACT_DEFAULT_EMAIL = 'dev-core@web.de';

    // Info-Text setzen: Ein eigener Branding-Text verliert sein data-i18n
    // (sonst wuerde der naechste Sprachwechsel ihn mit dem Default-Text
    // ueberschreiben); beim Zuruecksetzen wird das Attribut wiederhergestellt
    // und der uebersetzte Default erneut angewendet.
    function setContactInfo(el, text) {
        if (text) {
            if (el.dataset.i18n) { el.dataset.brandI18n = el.dataset.i18n; el.removeAttribute('data-i18n'); }
            el.textContent = text;
        } else {
            if (el.dataset.brandI18n) { el.setAttribute('data-i18n', el.dataset.brandI18n); delete el.dataset.brandI18n; }
            if (el.dataset.i18n && window.t) el.textContent = window.t(el.dataset.i18n);
        }
    }

    function applyPortalContact(b) {
        var wrap = document.getElementById('pt-contact');
        if (!wrap) return; // Seite ohne Kontaktzeile
        var active = !!(b && b.active);
        var info = active ? (b.contact_info || '') : '';   // '' = i18n-Default
        var phone = active ? (b.contact_phone || '') : '';
        var email = active ? (b.contact_email || '') : CONTACT_DEFAULT_EMAIL;

        var infoEl = document.getElementById('pt-contact-info');
        var infoShown = false;
        if (infoEl) {
            setContactInfo(infoEl, info);
            // Bei aktivem Branding ohne Info-Text die Zeile nicht mit dem
            // Jarvis-Default fuellen, sondern den Info-Teil ausblenden.
            infoShown = !active || !!info;
            infoEl.classList.toggle('hidden', !infoShown);
        }
        var pEl = document.getElementById('pt-contact-phone');
        var pLink = document.getElementById('pt-contact-phone-link');
        if (pEl && pLink) {
            if (phone) { pLink.textContent = phone; pLink.href = 'tel:' + phone.replace(/[^+\d]/g, ''); }
            pEl.classList.toggle('hidden', !phone);
        }
        var eEl = document.getElementById('pt-contact-email');
        var eLink = document.getElementById('pt-contact-email-link');
        if (eEl && eLink) {
            if (email) { eLink.textContent = email; eLink.href = 'mailto:' + email; }
            eEl.classList.toggle('hidden', !email);
        }
        // Benutzerhandbuch-Link hinter der E-Mail (nur bei aktivem Branding
        // mit gepflegter URL; Link-Text kommt aus i18n)
        var manual = active ? (b.manual_url || '') : '';
        var mEl = document.getElementById('pt-contact-manual');
        var mLink = document.getElementById('pt-contact-manual-link');
        if (mEl && mLink) {
            if (manual) mLink.href = manual;
            mEl.classList.toggle('hidden', !manual);
        }
        // Trennpunkte nur zwischen sichtbaren Teilen anzeigen
        var pSep = document.getElementById('pt-contact-phone-sep');
        if (pSep) pSep.classList.toggle('hidden', !(phone && infoShown));
        var eSep = document.getElementById('pt-contact-email-sep');
        if (eSep) eSep.classList.toggle('hidden', !(email && (infoShown || phone)));
        var mSep = document.getElementById('pt-contact-manual-sep');
        if (mSep) mSep.classList.toggle('hidden', !(manual && (infoShown || phone || email)));
    }

    // Assistenten-Name fuer die Begruessungen: eigenes Feld, sonst Firmenname.
    function assistantNameOf(b) {
        return ((b && b.assistant_name) || '').trim() || (b && b.company_name) || '';
    }

    // Ersetzt 'Jarvis' in den sichtbaren Begruessungszeilen durch den
    // Assistenten-Namen (nicht den Firmennamen). Best-effort: applyLang setzt
    // die data-i18n-Zeile bei Sprachwechsel ggf. neu -> applyBranding laeuft
    // erneut (setTimeout/load/themechange).
    function applyAssistantName(b) {
        var name = assistantNameOf(b);
        if (!name) return;
        ['.log-welcome p', '[data-i18n="chat.greeting"]'].forEach(function (sel) {
            document.querySelectorAll(sel).forEach(function (el) {
                if (/jarvis/i.test(el.textContent)) {
                    if (el.dataset.brandOrig === undefined) el.dataset.brandOrig = el.textContent;
                    el.textContent = el.textContent.replace(/jarvis/ig, name);
                }
            });
        });
    }

    function applyBranding(b) {
        if (!b || !b.active) return;
        _current = b;
        var isLight = currentIsLight();
        applyColors(effectiveColors(b, isLight));
        var nlu = effectiveNameLogoUrl(b, isLight);
        setBrandLabels(b.company_name, !!nlu);
        applyAssistantName(b);
        // Fuer nicht-DOM-Texte (z.B. TTS-Vorschau in chat.js/app.js) bereitstellen
        window.brandAssistantName = assistantNameOf(b);
        var lu = effectiveLogoUrl(b, isLight);
        applyLogo(b, lu);
        applyNameLogo(b, nlu);
        applyFavicon(b, lu);
        applyPortalVideo(b);
        applyPortalContact(b);
    }

    // ── Laufzeit: Branding laden & anwenden ─────────────────────────
    // 1) Cache sofort anwenden (vermeidet Aufblitzen des Standard-Designs)
    try {
        var cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
        if (cached && cached.active) {
            _current = cached;
            var _il = currentIsLight();
            applyColors(effectiveColors(cached, _il));
            var _lu = effectiveLogoUrl(cached, _il);
            applyLogo(cached, _lu);
            applyFavicon(cached, _lu);
        }
    } catch (e) { /* ignorieren */ }

    function refreshBranding() {
        fetch('/api/branding')
            .then(function (r) { return r.json(); })
            .then(function (b) {
                try { localStorage.setItem(CACHE_KEY, JSON.stringify(b)); } catch (e) {}
                if (!b || !b.active) {
                    // Skill deaktiviert → Cache leeren UND angewandtes Branding
                    // vollstaendig zuruecksetzen (Standard-Jarvis-Design).
                    try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
                    resetBranding();
                    return;
                }
                applyBranding(b);
                // Nach i18n-/Spät-Renderern erneut anwenden
                setTimeout(function () { applyBranding(b); }, 400);
                window.addEventListener('load', function () { applyBranding(b); });
            })
            .catch(function () { /* offline o.ä. – Standard belassen */ });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', refreshBranding);
    } else {
        refreshBranding();
    }

    window.refreshBranding = refreshBranding;
    window.resetBranding = resetBranding;
    window.brandAvatar = brandAvatar;

    // Bei Hell/Dunkel-Wechsel das passende Farb-/Logo-Set neu anwenden
    document.addEventListener('jarvis:themechange', function () {
        if (_current && _current.active) applyBranding(_current);
    });

    // ═══════════════════════════════════════════════════════════════
    //  Admin-Teil: Einstellungs-Tab (nur auf index.html vorhanden)
    // ═══════════════════════════════════════════════════════════════
    function token() { return localStorage.getItem('jarvis_token') || ''; }

    var DEFAULTS = {
        accent: '#6366f1', accent_hover: '#818cf8',
        bg_primary: '#0a0e17', bg_secondary: '#111827',
        text_primary: '#f8fafc',
        // Hell-Modus-Defaults (entsprechen body.light in style.css)
        bg_primary_light: '#f4f5f7', bg_secondary_light: '#ffffff',
        text_primary_light: '#1a2233'
    };

    var BrandingAdmin = {
        _logoUrl: '',
        _logoUrlLight: '',
        init: function () {
            var tab = document.getElementById('settings-tab-branding');
            if (!tab || tab._brInit) return;
            tab._brInit = true;
            var saveBtn = document.getElementById('br-save');
            if (saveBtn) saveBtn.addEventListener('click', this.save.bind(this));
            var logoInput = document.getElementById('br-logo-file');
            if (logoInput) logoInput.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'dark', 'compact'); });
            var logoDel = document.getElementById('br-logo-del');
            if (logoDel) logoDel.addEventListener('click', function () { BrandingAdmin.deleteLogo('dark', 'compact'); });
            var logoInputL = document.getElementById('br-logo-file-light');
            if (logoInputL) logoInputL.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'light', 'compact'); });
            var logoDelL = document.getElementById('br-logo-del-light');
            if (logoDelL) logoDelL.addEventListener('click', function () { BrandingAdmin.deleteLogo('light', 'compact'); });
            // Namens-/Schriftzug-Logo (ersetzt den Firmennamen-Text durch ein Bild)
            var nameInput = document.getElementById('br-name-logo-file');
            if (nameInput) nameInput.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'dark', 'name'); });
            var nameDel = document.getElementById('br-name-logo-del');
            if (nameDel) nameDel.addEventListener('click', function () { BrandingAdmin.deleteLogo('dark', 'name'); });
            var nameInputL = document.getElementById('br-name-logo-file-light');
            if (nameInputL) nameInputL.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'light', 'name'); });
            var nameDelL = document.getElementById('br-name-logo-del-light');
            if (nameDelL) nameDelL.addEventListener('click', function () { BrandingAdmin.deleteLogo('light', 'name'); });
            var vidInput = document.getElementById('br-portal-video-file');
            if (vidInput) vidInput.addEventListener('change', function (ev) { BrandingAdmin.uploadPortalVideo(ev); });
            var vidDel = document.getElementById('br-portal-video-del');
            if (vidDel) vidDel.addEventListener('click', function () { BrandingAdmin.deletePortalVideo(); });
            // Live-Vorschau bei Farb-/Text-/Logo-Änderung
            ['br-accent', 'br-accent-hover', 'br-bg-primary', 'br-bg-secondary', 'br-text-primary',
             'br-bg-primary-light', 'br-bg-secondary-light', 'br-text-primary-light',
             'br-name', 'br-assistant-name', 'br-letter',
             'br-contact-info', 'br-contact-phone', 'br-contact-email', 'br-manual-url']
                .forEach(function (id) {
                    var el = document.getElementById(id);
                    if (el) el.addEventListener('input', function () { BrandingAdmin.preview(); });
                });
            document.querySelectorAll('input[name="br-logo-mode"]').forEach(function (r) {
                r.addEventListener('change', function () { BrandingAdmin.preview(); });
            });
            this.load();
        },
        _val: function (id, def) {
            var el = document.getElementById(id);
            return (el && el.value) ? el.value : (def || '');
        },
        _set: function (id, v) { var el = document.getElementById(id); if (el) el.value = v; },
        load: function () {
            fetch('/api/skills/branding/config', { headers: { 'Authorization': 'Bearer ' + token() } })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    var col = c.colors || {};
                    var colL = c.colors_light || {};
                    BrandingAdmin._set('br-name', c.company_name || '');
                    BrandingAdmin._set('br-assistant-name', c.assistant_name || '');
                    BrandingAdmin._set('br-letter', c.core_letter || '');
                    BrandingAdmin._set('br-contact-info', c.contact_info || '');
                    BrandingAdmin._set('br-contact-phone', c.contact_phone || '');
                    BrandingAdmin._set('br-contact-email', c.contact_email || '');
                    BrandingAdmin._set('br-manual-url', c.manual_url || '');
                    BrandingAdmin._set('br-accent', col.accent || DEFAULTS.accent);
                    BrandingAdmin._set('br-accent-hover', col.accent_hover || DEFAULTS.accent_hover);
                    BrandingAdmin._set('br-bg-primary', col.bg_primary || DEFAULTS.bg_primary);
                    BrandingAdmin._set('br-bg-secondary', col.bg_secondary || DEFAULTS.bg_secondary);
                    BrandingAdmin._set('br-text-primary', col.text_primary || DEFAULTS.text_primary);
                    BrandingAdmin._set('br-bg-primary-light', colL.bg_primary || DEFAULTS.bg_primary_light);
                    BrandingAdmin._set('br-bg-secondary-light', colL.bg_secondary || DEFAULTS.bg_secondary_light);
                    BrandingAdmin._set('br-text-primary-light', colL.text_primary || DEFAULTS.text_primary_light);
                    var mode = c.logo_mode || 'letter';
                    var radio = document.querySelector('input[name="br-logo-mode"][value="' + mode + '"]');
                    if (radio) radio.checked = true;
                    BrandingAdmin.refreshLogoPreview();
                })
                .catch(function () {});
        },
        refreshLogoPreview: function () {
            fetch('/api/branding')
                .then(function (r) { return r.json(); })
                .then(function (b) {
                    b = b || {};
                    var img = document.getElementById('br-logo-preview');
                    if (img) {
                        if (b.logo_url) { img.src = b.logo_url; img.style.display = ''; BrandingAdmin._logoUrl = b.logo_url; }
                        else { img.style.display = 'none'; BrandingAdmin._logoUrl = ''; }
                    }
                    var imgL = document.getElementById('br-logo-preview-light');
                    if (imgL) {
                        if (b.logo_url_light) { imgL.src = b.logo_url_light; imgL.style.display = ''; BrandingAdmin._logoUrlLight = b.logo_url_light; }
                        else { imgL.style.display = 'none'; BrandingAdmin._logoUrlLight = ''; }
                    }
                    var nimg = document.getElementById('br-name-logo-preview');
                    if (nimg) {
                        if (b.name_logo_url) { nimg.src = b.name_logo_url; nimg.style.display = ''; }
                        else { nimg.removeAttribute('src'); nimg.style.display = 'none'; }
                    }
                    var nimgL = document.getElementById('br-name-logo-preview-light');
                    if (nimgL) {
                        if (b.name_logo_url_light) { nimgL.src = b.name_logo_url_light; nimgL.style.display = ''; }
                        else { nimgL.removeAttribute('src'); nimgL.style.display = 'none'; }
                    }
                    var vid = document.getElementById('br-portal-video-preview');
                    if (vid) {
                        if (b.portal_video_url) { vid.src = b.portal_video_url; vid.style.display = ''; try { vid.play(); } catch (e) {} }
                        else { vid.removeAttribute('src'); vid.style.display = 'none'; }
                    }
                }).catch(function () {});
        },
        _mode: function () {
            var r = document.querySelector('input[name="br-logo-mode"]:checked');
            return r ? r.value : 'letter';
        },
        // Baut das komplette Branding-Objekt aus den Formularfeldern
        _buildBranding: function () {
            return {
                active: true,
                company_name: this._val('br-name', ''),
                assistant_name: this._val('br-assistant-name', ''),
                core_letter: this._val('br-letter', ''),
                contact_info: this._val('br-contact-info', ''),
                contact_phone: this._val('br-contact-phone', ''),
                contact_email: this._val('br-contact-email', ''),
                manual_url: this._val('br-manual-url', ''),
                logo_mode: this._mode(),
                logo_url: this._logoUrl,
                logo_url_light: this._logoUrlLight,
                colors: {
                    accent: this._val('br-accent', DEFAULTS.accent),
                    accent_hover: this._val('br-accent-hover', DEFAULTS.accent_hover),
                    bg_primary: this._val('br-bg-primary', DEFAULTS.bg_primary),
                    bg_secondary: this._val('br-bg-secondary', DEFAULTS.bg_secondary),
                    text_primary: this._val('br-text-primary', DEFAULTS.text_primary)
                },
                colors_light: {
                    bg_primary: this._val('br-bg-primary-light', DEFAULTS.bg_primary_light),
                    bg_secondary: this._val('br-bg-secondary-light', DEFAULTS.bg_secondary_light),
                    text_primary: this._val('br-text-primary-light', DEFAULTS.text_primary_light)
                }
            };
        },
        preview: function () {
            // Vorschau wendet das fuer den aktuellen Modus passende Set an
            applyBranding(this._buildBranding());
        },
        save: function () {
            var b = this._buildBranding();
            var body = {
                company_name: b.company_name,
                assistant_name: b.assistant_name,
                core_letter: b.core_letter,
                contact_info: b.contact_info,
                contact_phone: b.contact_phone,
                contact_email: b.contact_email,
                manual_url: b.manual_url,
                logo_mode: b.logo_mode,
                colors: b.colors,
                colors_light: b.colors_light
            };
            fetch('/api/skills/branding/config', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () {
                  try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
                  refreshBranding();
                  var st = document.getElementById('br-status');
                  if (st) { st.textContent = '✓ Gespeichert'; setTimeout(function () { st.textContent = ''; }, 2500); }
              }).catch(function () {
                  var st = document.getElementById('br-status');
                  if (st) st.textContent = window.t('branding.save_error');
              });
        },
        uploadLogo: function (ev, variant, kind) {
            var f = ev.target.files && ev.target.files[0];
            if (!f) return;
            kind = kind === 'name' ? 'name' : 'compact';
            var fd = new FormData();
            fd.append('file', f);
            fd.append('variant', variant === 'light' ? 'light' : 'dark');
            fd.append('kind', kind);
            fetch('/api/branding/logo', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token() },
                body: fd
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success) {
                      BrandingAdmin.refreshLogoPreview();
                      // Nur fuer das runde Kompakt-Logo automatisch den Bild-Modus aktivieren
                      if (kind === 'compact') {
                          var modeImg = document.querySelector('input[name="br-logo-mode"][value="image"]');
                          if (modeImg) modeImg.checked = true;
                      }
                      var st = document.getElementById('br-status');
                      if (st) { st.textContent = '✓ Logo hochgeladen'; setTimeout(function () { st.textContent = ''; }, 2500); }
                  } else {
                      var st2 = document.getElementById('br-status');
                      if (st2) st2.textContent = '✗ ' + ((d && d.error) || 'Upload fehlgeschlagen');
                  }
              }).catch(function () {});
        },
        deleteLogo: function (variant, kind) {
            variant = variant === 'light' ? 'light' : 'dark';
            kind = kind === 'name' ? 'name' : 'compact';
            fetch('/api/branding/logo?variant=' + variant + '&kind=' + kind, {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + token() }
            }).then(function () {
                BrandingAdmin.refreshLogoPreview();
            }).catch(function () {});
        },
        uploadPortalVideo: function (ev) {
            var f = ev.target.files && ev.target.files[0];
            if (!f) return;
            var st = document.getElementById('br-status');
            if (st) st.textContent = window.t('branding.uploading_animation');
            var fd = new FormData();
            fd.append('file', f);
            fetch('/api/branding/portal-video', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token() },
                body: fd
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success) {
                      BrandingAdmin.refreshLogoPreview();
                      if (st) { st.textContent = '✓ Animation hochgeladen'; setTimeout(function () { st.textContent = ''; }, 2500); }
                  } else if (st) {
                      st.textContent = '✗ ' + ((d && d.error) || 'Upload fehlgeschlagen');
                  }
              }).catch(function () { if (st) st.textContent = '✗ Upload fehlgeschlagen'; });
        },
        deletePortalVideo: function () {
            fetch('/api/branding/portal-video', {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + token() }
            }).then(function () {
                BrandingAdmin.refreshLogoPreview();
            }).catch(function () {});
        }
    };

    window.brandingAdmin = BrandingAdmin;
})();
