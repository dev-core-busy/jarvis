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

    // Setzt den Text reiner Marken-Labels (nicht über i18n gesteuert)
    function setBrandLabels(name) {
        if (!name) return;
        ['.login-title', '.header-title', '.topbar-title'].forEach(function (sel) {
            document.querySelectorAll(sel).forEach(function (el) {
                el.textContent = name;
            });
        });
        // Seitentitel + Begrüßungs-/Hinweistexte: 'Jarvis' → Firmenname
        if (document.title) {
            document.title = document.title.replace(/jarvis/ig, name);
        }
        document.querySelectorAll('[placeholder]').forEach(function (el) {
            if (/jarvis/i.test(el.placeholder)) {
                el.placeholder = el.placeholder.replace(/jarvis/ig, name);
            }
        });
        // Begrüßungszeilen (best-effort; werden bei Sprachwechsel ggf. neu gesetzt)
        ['.log-welcome p', '[data-i18n="chat.greeting"]'].forEach(function (sel) {
            document.querySelectorAll(sel).forEach(function (el) {
                if (/jarvis/i.test(el.textContent)) {
                    el.textContent = el.textContent.replace(/jarvis/ig, name);
                }
            });
        });
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
            core.innerHTML = '';
            core.classList.add('branding-logo-img');
            // Neutraler (weisser) Hintergrund statt Akzent-Gradient – sonst
            // verschwindet ein Logo in Markenfarbe (z.B. rotes Logo auf rotem
            // Avatar). Markenlogos sind auf Weiss ausgelegt. NUR fuer die flachen
            // Avatar-Kreise – die Header-Ring-Kerne haben ihr eigenes Design.
            var isRingCore = core.classList.contains('logo-core') ||
                             core.classList.contains('logo-mini-core');
            if (!isRingCore) core.style.background = '#fff';
            var img = document.createElement('img');
            img.src = logoUrl;
            img.alt = b.company_name || 'Logo';
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '50%';
            core.appendChild(img);
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

    function applyBranding(b) {
        if (!b || !b.active) return;
        _current = b;
        var isLight = currentIsLight();
        applyColors(effectiveColors(b, isLight));
        setBrandLabels(b.company_name);
        applyLogo(b, effectiveLogoUrl(b, isLight));
    }

    // ── Laufzeit: Branding laden & anwenden ─────────────────────────
    // 1) Cache sofort anwenden (vermeidet Aufblitzen des Standard-Designs)
    try {
        var cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
        if (cached && cached.active) {
            _current = cached;
            var _il = currentIsLight();
            applyColors(effectiveColors(cached, _il));
            applyLogo(cached, effectiveLogoUrl(cached, _il));
        }
    } catch (e) { /* ignorieren */ }

    function refreshBranding() {
        fetch('/api/branding')
            .then(function (r) { return r.json(); })
            .then(function (b) {
                try { localStorage.setItem(CACHE_KEY, JSON.stringify(b)); } catch (e) {}
                if (!b || !b.active) {
                    // Skill deaktiviert → Cache leeren, Standard bleibt
                    try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
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
            if (logoInput) logoInput.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'dark'); });
            var logoDel = document.getElementById('br-logo-del');
            if (logoDel) logoDel.addEventListener('click', function () { BrandingAdmin.deleteLogo('dark'); });
            var logoInputL = document.getElementById('br-logo-file-light');
            if (logoInputL) logoInputL.addEventListener('change', function (ev) { BrandingAdmin.uploadLogo(ev, 'light'); });
            var logoDelL = document.getElementById('br-logo-del-light');
            if (logoDelL) logoDelL.addEventListener('click', function () { BrandingAdmin.deleteLogo('light'); });
            // Live-Vorschau bei Farb-/Text-/Logo-Änderung
            ['br-accent', 'br-accent-hover', 'br-bg-primary', 'br-bg-secondary', 'br-text-primary',
             'br-bg-primary-light', 'br-bg-secondary-light', 'br-text-primary-light',
             'br-name', 'br-letter']
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
                    BrandingAdmin._set('br-letter', c.core_letter || '');
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
                core_letter: this._val('br-letter', ''),
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
                core_letter: b.core_letter,
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
                  if (st) st.textContent = '✗ Fehler beim Speichern';
              });
        },
        uploadLogo: function (ev, variant) {
            var f = ev.target.files && ev.target.files[0];
            if (!f) return;
            var fd = new FormData();
            fd.append('file', f);
            fd.append('variant', variant === 'light' ? 'light' : 'dark');
            fetch('/api/branding/logo', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token() },
                body: fd
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success) {
                      BrandingAdmin.refreshLogoPreview();
                      var modeImg = document.querySelector('input[name="br-logo-mode"][value="image"]');
                      if (modeImg) modeImg.checked = true;
                      var st = document.getElementById('br-status');
                      if (st) { st.textContent = '✓ Logo hochgeladen'; setTimeout(function () { st.textContent = ''; }, 2500); }
                  } else {
                      var st2 = document.getElementById('br-status');
                      if (st2) st2.textContent = '✗ ' + ((d && d.error) || 'Upload fehlgeschlagen');
                  }
              }).catch(function () {});
        },
        deleteLogo: function (variant) {
            variant = variant === 'light' ? 'light' : 'dark';
            fetch('/api/branding/logo?variant=' + variant, {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + token() }
            }).then(function () {
                BrandingAdmin.refreshLogoPreview();
            }).catch(function () {});
        }
    };

    window.brandingAdmin = BrandingAdmin;
})();
