/* Fernzugang (SSH) – Einstellungen → Sicherheit (BSI M7).
   Zustand und Aenderungen ueber /api/broker/ssh/* (Broker: backend/broker/fernzugang.py,
   Regeln in deploy/security/ssh_haertung.sh und firewall.sh).

   Jede Aenderung ist ZWEISTUFIG: "Test" wirkt sofort und wird nach der Frist vom
   Server selbst zurueckgenommen; erst "Bestaetigen" macht sie dauerhaft. Die
   Weboberflaeche kann nicht pruefen, ob ein NEUES SSH-Login noch geht – das muss
   der Mensch in einem zweiten Terminal tun, bevor er bestaetigt.

   Schluessel hinterlegen geht hier bewusst NICHT (neuer Weg zu root per SSH);
   gezeigt werden Konten, Fingerabdruecke und eine Anleitung. */
(function () {
    'use strict';

    function token() { return window.JarvisSitzung.token(); }
    function authHeaders(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {}); }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, def) {
        return (window.t && window.t(key) !== key ? window.t(key) : null) || def;
    }
    // ── Adressen rechnen (IPv4 und IPv6 als BigInt) ─────────────────────────
    // Nur fuer die ANZEIGE im Helfer (enthalten? doppelt?). Massgeblich prueft
    // und normiert der Server (firewall.sh, Python ipaddress).
    function ipZuZahl(ip) {
        ip = String(ip || '').trim();
        var m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(ip);
        if (m) {
            var t = m.slice(1).map(Number);
            if (t.some(function (x) { return x > 255; })) return null;
            return { v: 4, n: BigInt(((t[0] * 256 + t[1]) * 256 + t[2]) * 256 + t[3]) };
        }
        if (!/^[0-9a-fA-F:]+$/.test(ip) || ip.indexOf(':') < 0) return null;
        var teile = ip.split('::');
        if (teile.length > 2) return null;
        var vorn = teile[0] ? teile[0].split(':') : [];
        var hinten = teile.length === 2 && teile[1] ? teile[1].split(':') : [];
        var fehlt = 8 - vorn.length - hinten.length;
        if (teile.length === 1 ? fehlt !== 0 : fehlt < 1) return null;
        var gruppen = vorn.concat(new Array(teile.length === 2 ? fehlt : 0).fill('0'), hinten);
        if (gruppen.some(function (g) { return !/^[0-9a-fA-F]{1,4}$/.test(g); })) return null;
        var n = BigInt(0);
        gruppen.forEach(function (g) { n = (n << BigInt(16)) + BigInt(parseInt(g, 16)); });
        return { v: 6, n: n };
    }
    function zahlZuIp(v, n) {
        if (v === 4) {
            var o = [];
            for (var i = 0; i < 4; i++) { o.unshift(Number(n & BigInt(255))); n >>= BigInt(8); }
            return o.join('.');
        }
        var g = [];
        for (var j = 0; j < 8; j++) { g.unshift(Number(n & BigInt(65535)).toString(16)); n >>= BigInt(16); }
        // laengste Nullfolge (>= 2 Gruppen) zu "::" kuerzen
        var best = -1, len = 0;
        for (var a = 0; a < 8; a++) {
            var b = a; while (b < 8 && g[b] === '0') b++;
            if (b - a > len && b - a >= 2) { best = a; len = b - a; }
            a = b;
        }
        if (best < 0) return g.join(':');
        return g.slice(0, best).join(':') + '::' + g.slice(best + len).join(':');
    }
    /* "adresse[/praefix]" -> {v, netz, praefix, text} oder null. Ohne Praefix
       gilt `umfang`: einzeln (/32 bzw. /128), klein (/24 bzw. /64), gross
       (/16 bzw. /48). Host-Bits werden genullt wie bei ipaddress(strict=False). */
    function netzNormieren(eingabe, umfang) {
        var roh = String(eingabe || '').trim();
        var teile = roh.split('/');
        if (teile.length > 2) return null;
        var ip = ipZuZahl(teile[0]);
        if (!ip) return null;
        var max = ip.v === 4 ? 32 : 128;
        var p;
        if (teile.length === 2) {
            if (!/^\d{1,3}$/.test(teile[1])) return null;
            p = Number(teile[1]);
        } else {
            p = { einzeln: max, klein: ip.v === 4 ? 24 : 64, gross: ip.v === 4 ? 16 : 48 }[umfang || 'einzeln'];
        }
        if (!(p >= 0 && p <= max)) return null;
        var maske = ((BigInt(1) << BigInt(max)) - BigInt(1)) ^ ((BigInt(1) << BigInt(max - p)) - BigInt(1));
        var netz = ip.n & maske;
        return { v: ip.v, netz: netz, praefix: p, text: zahlZuIp(ip.v, netz) + '/' + p };
    }
    function enthaelt(netzText, ipText) {
        var n = netzNormieren(netzText), ip = ipZuZahl(ipText);
        if (!n || !ip || n.v !== ip.v) return false;
        var max = n.v === 4 ? 32 : 128;
        return (ip.n >> BigInt(max - n.praefix)) === (n.netz >> BigInt(max - n.praefix));
    }
    function mmss(s) {
        s = Math.max(0, Math.floor(s || 0));
        return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
    }

    var Fz = {
        _bound: false,
        _stand: null,
        _netze: [],          // Liste im Helfer (normierte Texte)
        _netzeGeaendert: false,
        _uhr: null,
        _fristBis: { haertung: 0, netze: 0 },

        onShow: function () { this._bind(); this.laden(); },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var self = this;
            function an(id, fn) { var el = $(id); if (el) el.addEventListener('click', fn); }
            an('sec-ssh-refresh', function () { self.laden(); });
            an('sec-ssh-h-test', function () { self.haertung('test'); });
            an('sec-ssh-h-ok', function () { self.haertung('bestaetigen'); });
            an('sec-ssh-h-weg', function () { self.haertung('verwerfen'); });
            an('sec-ssh-h-aus', function () { self.haertung('aus'); });
            an('sec-ssh-n-test', function () { self.netze('test'); });
            an('sec-ssh-n-ok', function () { self.netze('bestaetigen'); });
            an('sec-ssh-n-weg', function () { self.netze('verwerfen'); });
            // Maus-Helfer: Hinzufuegen per Knopf oder Enter, Entfernen und
            // Vorschlaege per Delegation (kein Inline-Handler, CSP H4)
            an('sec-ssh-netz-add', function () { self.netzEingabeHinzu(); });
            var neu = $('sec-ssh-netz-neu');
            if (neu) neu.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); self.netzEingabeHinzu(); }
            });
            var liste = $('sec-ssh-netze-liste');
            if (liste) liste.addEventListener('click', function (e) {
                var k = e.target.closest && e.target.closest('[data-netz-weg]');
                if (k) self.netzWeg(k.getAttribute('data-netz-weg'));
            });
            var vs = $('sec-ssh-netze-vorschlaege');
            if (vs) vs.addEventListener('click', function (e) {
                var k = e.target.closest && e.target.closest('[data-netz-dazu]');
                if (k && !k.disabled) self.netzHinzu(k.getAttribute('data-netz-dazu'));
            });
        },

        laden: function () {
            var self = this;
            return fetch('/api/broker/ssh/status', { headers: authHeaders() })
                .then(function (r) { return r.json().catch(function () { return null; }); })
                .then(function (d) { self.zeigen(d); })
                .catch(function () { self.zeigen(null); });
        },

        // ── Anzeige ────────────────────────────────────────────────────────
        zeigen: function (d) {
            this._stand = d;
            var box = $('sec-ssh-status');
            if (!box) return;
            if (!d || !d.ok) {
                // Ein Broker ohne diese Ops sagt "unbekannte Operation" – der Grund
                // ist dann fast immer ein fehlender Neustart nach dem Update.
                box.innerHTML = '<div class="sec-ssh-zeile sec-ssh-warn">'
                    + esc(T('security.ssh_nicht_erreichbar',
                        'Zustand nicht abrufbar. Ist der Root-Broker aktuell? Nach einem Update: jarvis-broker.service neu starten.'))
                    + (d && d.error ? ' (' + esc(d.error) + ')' : '') + '</div>';
                this._knoepfe(null);
                this._badge(null);
                return;
            }
            var s = d.sshd || {};
            var kennwort = s.passwordauthentication === 'yes' || s.kbdinteractiveauthentication === 'yes';
            var rootTxt = {
                'no': T('security.ssh_root_no', 'nicht erlaubt'),
                'prohibit-password': T('security.ssh_root_key', 'nur per Schlüssel'),
                'without-password': T('security.ssh_root_key', 'nur per Schlüssel'),
                'yes': T('security.ssh_root_yes', 'auch per Kennwort')
            }[s.permitrootlogin] || (s.permitrootlogin || '?');
            var netzTxt = d.netze ? d.netze : T('security.ssh_netze_alle', 'aus allen Netzen');
            var zeilen = [
                [T('security.ssh_st_kennwort', 'Anmeldung per Kennwort'),
                    s.passwordauthentication ? (kennwort ? T('security.ssh_erlaubt', 'erlaubt') : T('security.ssh_aus', 'abgeschaltet')) : '?',
                    kennwort ? 'warn' : 'ok'],
                [T('security.ssh_st_root', 'Anmeldung als root'), rootTxt,
                    s.permitrootlogin === 'yes' ? 'warn' : 'ok'],
                [T('security.ssh_st_netze', 'SSH erreichbar'), netzTxt, d.netze ? 'ok' : 'warn']
            ];
            box.innerHTML = zeilen.map(function (z) {
                return '<div class="sec-ssh-zeile sec-ssh-' + z[2] + '"><span class="sec-ssh-k">'
                    + esc(z[0]) + '</span><span class="sec-ssh-v">' + esc(z[1]) + '</span></div>';
            }).join('');

            this._konten(d);
            var root = d.root_modus === 'schluessel' ? 'schluessel' : 'nein';
            document.querySelectorAll('input[name="sec-ssh-root"]').forEach(function (r) {
                r.checked = (r.value === root);
            });
            // Eine angefangene, noch nicht uebernommene Liste nicht ueberschreiben
            if (!this._netzeGeaendert) {
                this._netze = String(d.netze || '').split(/\s+/).filter(Boolean);
            }
            this._netzeZeigen();
            this._knoepfe(d);
            this._badge(d, kennwort);
        },

        _konten: function (d) {
            var box = $('sec-ssh-konten');
            if (!box) return;
            var konten = d.konten || [];
            var html;
            if (!konten.length) {
                html = '<div class="sec-ssh-zeile sec-ssh-warn">'
                    + esc(T('security.ssh_keine_konten', 'Kein Konto gefunden, das Administrator werden kann.')) + '</div>';
            } else {
                html = konten.map(function (k) {
                    // root heisst schon so – die Art nur bei sudo-Konten dazuschreiben
                    var art = k.art === 'root' ? '' : ' · ' + esc(T('security.ssh_art_admin', 'Administrator (sudo)'));
                    var keys = (k.schluessel || []).map(function (s) {
                        return '<div class="sec-ssh-key"><code>' + esc(s.fingerabdruck) + '</code> '
                            + esc(s.typ) + (s.kommentar && s.kommentar !== 'no comment' ? ' · ' + esc(s.kommentar) : '') + '</div>';
                    }).join('');
                    if (!keys) keys = '<div class="sec-ssh-key sec-ssh-leer">'
                        + esc(T('security.ssh_kein_schluessel', 'kein Schlüssel hinterlegt')) + '</div>';
                    var zaehlt = k.zaehlt
                        ? '<span class="sec-ssh-marke ok">' + esc(T('security.ssh_zaehlt', 'kommt nach der Umstellung herein')) + '</span>'
                        : '<span class="sec-ssh-marke">' + esc(k.art === 'root' && k.anzahl > 0
                            ? T('security.ssh_zaehlt_root', 'nur wenn root per Schlüssel erlaubt ist')
                            : T('security.ssh_zaehlt_nicht', 'kommt nach der Umstellung nicht herein')) + '</span>';
                    return '<div class="sec-ssh-konto"><div><b>' + esc(k.name) + '</b>' + art
                        + ' ' + zaehlt + '</div>' + keys + '</div>';
                }).join('');
            }
            box.innerHTML = html;
            // Anleitung von selbst aufklappen, solange niemand mit Schluessel hereinkaeme
            var zm = d.zugang_moeglich || {};
            var anl = $('sec-ssh-anleitung');
            if (anl && !zm.nein && !zm.schluessel) anl.open = true;
        },

        // ── Maus-Helfer "Erlaubte Netze" ────────────────────────────────────
        netzHinzu: function (text) {
            var n = netzNormieren(text);
            if (!n) return false;
            if (this._netze.indexOf(n.text) < 0) this._netze.push(n.text);
            this._netzeGeaendert = true;
            this._netzeZeigen();
            return true;
        },

        netzWeg: function (text) {
            this._netze = this._netze.filter(function (x) { return x !== text; });
            this._netzeGeaendert = true;
            this._netzeZeigen();
        },

        netzEingabeHinzu: function () {
            var feld = $('sec-ssh-netz-neu'), umfang = ($('sec-ssh-netz-praefix') || {}).value;
            var fehler = $('sec-ssh-netz-fehler');
            var roh = (feld && feld.value || '').trim();
            var n = netzNormieren(roh, umfang);
            var meldung = '';
            if (!roh) meldung = '';
            else if (!n) meldung = T('security.ssh_netz_ungueltig', 'Keine gültige IPv4- oder IPv6-Adresse: %s').replace('%s', roh);
            else if (this._netze.indexOf(n.text) >= 0) meldung = T('security.ssh_netz_doppelt', 'Schon enthalten: %s').replace('%s', n.text);
            if (fehler) { fehler.textContent = meldung; fehler.style.display = meldung ? '' : 'none'; }
            if (!n || meldung) return;
            this.netzHinzu(n.text);
            if (feld) feld.value = '';
        },

        _abgedeckt: function (netzOderIp) {
            var self = this;
            var n = netzNormieren(netzOderIp);
            return this._netze.some(function (x) {
                if (n && x === n.text) return true;
                var ip = String(netzOderIp).split('/')[0];
                var xn = netzNormieren(x);
                return n && xn && n.praefix >= xn.praefix && enthaelt(x, ip);
            });
        },

        _netzeZeigen: function () {
            var self = this, d = this._stand || {};
            var versteckt = $('sec-ssh-netze');
            if (versteckt) versteckt.value = this._netze.join(' ');
            var box = $('sec-ssh-netze-liste');
            if (box) {
                box.innerHTML = this._netze.length
                    ? this._netze.map(function (x) {
                        return '<span class="sec-ssh-chip"><code>' + esc(x) + '</code>'
                            + '<button type="button" class="sec-ssh-chip-weg" data-netz-weg="' + esc(x) + '" title="'
                            + esc(T('security.ssh_entfernen', 'Entfernen')) + '" aria-label="'
                            + esc(T('security.ssh_entfernen', 'Entfernen')) + ' ' + esc(x) + '">'
                            + (window.JarvisIcons ? window.JarvisIcons.trash() : '') + '</button></span>';
                    }).join('')
                    : '<span class="sec-ssh-leer">' + esc(T('security.ssh_netze_leer', 'Keine Einschränkung – SSH ist aus allen Netzen erreichbar.')) + '</span>';
            }
            // Vorschlaege: eigene Adresse, bisherige SSH-Anmeldungen, Tailscale, Netze des Servers
            var vs = d.vorschlaege || {}, items = [], gesehen = {};
            function dazu(netz, label, hinweis) {
                var n = netzNormieren(netz);
                if (!n) return;
                if (gesehen[n.text] !== undefined) { items[gesehen[n.text]].hinweise.push(hinweis); return; }
                gesehen[n.text] = items.length;
                items.push({ netz: n.text, label: label, hinweise: [hinweis] });
            }
            if (d.deine_adresse && ipZuZahl(d.deine_adresse)) {
                dazu(d.deine_adresse, d.deine_adresse, T('security.ssh_vs_deine', 'deine aktuelle Adresse (Weboberfläche)'));
            }
            (vs.anmeldungen || []).forEach(function (a) {
                var tag = '';
                try { tag = new Date(a.zuletzt).toLocaleDateString(window._lang === 'en' ? 'en-GB' : 'de-DE'); } catch (e) { tag = ''; }
                dazu(a.ip, a.ip, T('security.ssh_vs_anm', '%n× per SSH angemeldet (%k), zuletzt %d')
                    .replace('%n', a.anzahl).replace('%k', (a.konten || []).join(', ')).replace('%d', tag));
            });
            if (vs.tailscale) dazu('100.64.0.0/10', '100.64.0.0/10', T('security.ssh_vs_tailscale', 'Tailscale-Netz'));
            (vs.lokal || []).forEach(function (l) {
                dazu(l.netz, l.netz, T('security.ssh_vs_lokal', 'Netz des Servers (%s)').replace('%s', l.schnittstelle || ''));
            });
            var vbox = $('sec-ssh-netze-vorschlaege');
            if (vbox) {
                vbox.innerHTML = items.length ? items.map(function (it) {
                    var drin = self._abgedeckt(it.netz);
                    return '<button type="button" class="sec-ssh-vorschlag" data-netz-dazu="' + esc(it.netz) + '"'
                        + (drin ? ' disabled' : '') + '><span class="sec-ssh-vs-netz">' + (drin ? '' : '+ ') + esc(it.label) + '</span>'
                        + '<span class="sec-ssh-vs-hinweis">' + esc(it.hinweise.join(' · '))
                        + (drin ? ' · ' + esc(T('security.ssh_enthalten', 'enthalten')) : '') + '</span></button>';
                }).join('') : '<span class="sec-ssh-leer">' + esc(T('security.ssh_keine_vorschlaege', 'Keine Vorschläge verfügbar.')) + '</span>';
            }
            // Warnungen: wer sich bisher angemeldet hat, waere ausgesperrt?
            var warn = [];
            if (this._netze.length) {
                if (d.deine_adresse && ipZuZahl(d.deine_adresse) && !this._abgedeckt(d.deine_adresse)) {
                    warn.push(T('security.ssh_warn_deine',
                        'Deine aktuelle Adresse %s ist nicht enthalten. Meldest du dich von hier aus per SSH an, wäre das nach dem Übernehmen gesperrt.')
                        .replace('%s', d.deine_adresse));
                }
                // Die eigene Adresse nennt schon die Zeile darueber
                var fehlen = (vs.anmeldungen || []).filter(function (a) {
                    return a.ip !== d.deine_adresse && !self._abgedeckt(a.ip); })
                    .map(function (a) { return a.ip; });
                if (fehlen.length) {
                    warn.push(T('security.ssh_warn_anm',
                        'Nicht enthalten sind Adressen, von denen sich in den letzten 30 Tagen jemand per SSH angemeldet hat: %s')
                        .replace('%s', fehlen.join(', ')));
                }
            }
            var geaendert = this._netze.join(' ') !== String(d.netze || '').split(/\s+/).filter(Boolean).join(' ');
            if (geaendert) warn.push(T('security.ssh_ungespeichert', 'Noch nicht übernommen – zum Ausprobieren „Übernehmen (Test, 5 Min.)“ klicken.'));
            var wbox = $('sec-ssh-netze-warnung');
            if (wbox) {
                wbox.innerHTML = warn.map(function (t) { return '<div>' + esc(t) + '</div>'; }).join('');
                wbox.style.display = warn.length ? '' : 'none';
            }
        },

        _sichtbar: function (id, an) { var el = $(id); if (el) el.style.display = an ? '' : 'none'; },

        _knoepfe: function (d) {
            var t = (d && d.test) || {};
            var th = t.haertung || {}, tn = t.netze || {};
            var aktiv = !!(d && d.haertung === 'an');
            this._sichtbar('sec-ssh-h-test', d && !th.laeuft && !aktiv);
            this._sichtbar('sec-ssh-h-ok', d && th.laeuft);
            this._sichtbar('sec-ssh-h-weg', d && th.laeuft);
            this._sichtbar('sec-ssh-h-aus', d && aktiv && !th.laeuft);
            var wahl = $('sec-ssh-haertung-wahl');
            if (wahl) wahl.querySelectorAll('input').forEach(function (i) { i.disabled = !!(aktiv || th.laeuft); });
            this._sichtbar('sec-ssh-n-test', d && !tn.laeuft);
            this._sichtbar('sec-ssh-n-ok', d && tn.laeuft);
            this._sichtbar('sec-ssh-n-weg', d && tn.laeuft);
            var nTest = $('sec-ssh-n-test');
            if (nTest) nTest.disabled = !!(d && !d.firewall_eingerichtet);
            var nRes = $('sec-ssh-n-result');
            if (d && !d.firewall_eingerichtet) {
                this._ergebnis('sec-ssh-n-result', false, T('security.ssh_fw_fehlt',
                    'Der Paketfilter ist auf diesem Server noch nicht eingerichtet. Die Ersteinrichtung geschieht an der Konsole (deploy/security/firewall.sh --test, danach --anwenden).'));
                if (nRes) nRes.setAttribute('data-fw', '1');
            } else if (nRes && nRes.getAttribute('data-fw') === '1') {
                nRes.removeAttribute('data-fw');
                nRes.style.display = 'none';
            }
            var jetzt = Date.now();
            this._fristBis.haertung = th.laeuft && th.rest_s != null ? jetzt + th.rest_s * 1000 : 0;
            this._fristBis.netze = tn.laeuft && tn.rest_s != null ? jetzt + tn.rest_s * 1000 : 0;
            this._uhrStellen();
        },

        _badge: function (d, kennwort) {
            var b = $('sec-ssh-badge');
            if (!b) return;
            if (!d) { b.style.display = 'none'; return; }
            var t = d.test || {};
            var txt, art;
            if ((t.haertung || {}).laeuft || (t.netze || {}).laeuft) {
                txt = T('security.ssh_badge_test', 'Test läuft – bestätigen'); art = 'warn';
            } else if (kennwort) {
                txt = T('security.ssh_badge_kennwort', 'Kennwort erlaubt'); art = 'warn';
            } else {
                txt = T('security.ssh_badge_ok', 'nur Schlüssel'); art = 'ok';
            }
            b.textContent = txt;
            b.className = 'sec-ssh-badge ' + art;
            b.style.display = '';
        },

        // Restfrist sichtbar herunterzaehlen; bei Ablauf den Zustand neu holen
        // (der Server hat dann zurueckgestellt).
        _uhrStellen: function () {
            var self = this;
            if (this._uhr) { clearInterval(this._uhr); this._uhr = null; }
            function tick() {
                var jetzt = Date.now(), neuLaden = false;
                [['haertung', 'sec-ssh-h-frist'], ['netze', 'sec-ssh-n-frist']].forEach(function (p) {
                    var el = $(p[1]);
                    var bis = self._fristBis[p[0]];
                    if (!el) return;
                    if (!bis) { el.textContent = ''; return; }
                    var rest = (bis - jetzt) / 1000;
                    if (rest <= 0) { el.textContent = ''; self._fristBis[p[0]] = 0; neuLaden = true; return; }
                    el.textContent = T('security.ssh_frist', 'Rücknahme in %s, wenn nicht bestätigt').replace('%s', mmss(rest));
                });
                if (neuLaden) setTimeout(function () { self.laden(); }, 3000);
                if (!self._fristBis.haertung && !self._fristBis.netze && self._uhr) {
                    clearInterval(self._uhr); self._uhr = null;
                }
            }
            tick();
            if (this._fristBis.haertung || this._fristBis.netze) this._uhr = setInterval(tick, 1000);
        },

        // Ergebnis AM Knopf. Fehler bleiben stehen (man muss sie lesen/kopieren
        // koennen), Erfolge auch – sie werden vom naechsten Ergebnis ersetzt.
        _ergebnis: function (id, ok, text) {
            var el = $(id);
            if (!el) return;
            el.removeAttribute('data-fw');
            el.className = 'sec-ssh-result ' + (ok ? 'ok' : 'fehler');
            el.textContent = text || '';
            el.style.display = text ? '' : 'none';
        },

        // ── Freigabe-Code (wie Root-Freigaben; der BROKER prueft ihn) ──────────
        _code: function () {
            var c = window.prompt(T('security.broker_code_prompt',
                'Freigabe-Code (6 Ziffern aus der Authenticator-App für Root-Freigaben dieses Servers):'), '');
            if (c === null) return null;
            return String(c).replace(/\D/g, '');
        },

        _codeText: function (grund) {
            return {
                'nicht_eingerichtet': T('security.broker_code_setup',
                    'Auf diesem Server ist noch kein Freigabe-Code eingerichtet. Als root: jarvis-broker-admin totp-einrichten – oder die Freigabe dort direkt erteilen: jarvis-broker-admin erlauben <Eintrag>'),
                'nachweis_fehlt': T('security.broker_code_missing', 'Bitte den 6-stelligen Freigabe-Code eingeben.'),
                'nachweis_falsch': T('security.broker_code_wrong', 'Der Freigabe-Code ist falsch oder abgelaufen.'),
                'nachweis_verbraucht': T('security.broker_code_used', 'Dieser Freigabe-Code wurde schon verwendet – bitte den nächsten abwarten.')
            }[grund] || '';
        },

        _senden: function (url, body, ergebnisId, knopfId, beiErfolg) {
            var self = this;
            var knopf = $(knopfId);
            if (knopf) knopf.disabled = true;
            self._ergebnis(ergebnisId, true, T('security.ssh_laeuft', 'Wird ausgeführt …'));
            return fetch(url, {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json().catch(function () { return {}; }); })
              .then(function (d) {
                  var text;
                  if (d && d.grund) text = self._codeText(d.grund) || d.error;
                  else if (d && d.ok) text = d.meldung || T('security.ssh_erledigt', 'Erledigt.');
                  else text = (d && (d.meldung || d.error)) || T('security.ssh_fehler', 'Fehlgeschlagen.');
                  if (d && d.ok && beiErfolg) beiErfolg();
                  self._ergebnis(ergebnisId, !!(d && d.ok), text);
              })
              .catch(function (e) { self._ergebnis(ergebnisId, false, String(e)); })
              .then(function () { if (knopf) knopf.disabled = false; return self.laden(); });
        },

        haertung: function (aktion) {
            var body = { aktion: aktion };
            if (aktion === 'test') {
                var w = document.querySelector('input[name="sec-ssh-root"]:checked');
                body.root_modus = w ? w.value : 'nein';
                if (!window.confirm(T('security.ssh_h_test_confirm',
                    'Die Anmeldung per Kennwort wird jetzt abgeschaltet.\n\nMelde dich danach in einem NEUEN Terminal per SSH mit Schlüssel an. Erst wenn das klappt, hier „Bestätigen“ klicken. Ohne Bestätigung wird die Änderung nach 5 Minuten von selbst zurückgenommen.\n\nFortfahren?'))) return;
            }
            if (aktion === 'aus' && !window.confirm(T('security.ssh_h_aus_confirm',
                'Die Anmeldung per Kennwort wird wieder erlaubt – Kennwörter lassen sich dann über SSH ohne Zwei-Faktor-Schutz durchprobieren. Wirklich?'))) return;
            if (aktion === 'bestaetigen' && !window.confirm(T('security.ssh_ok_confirm',
                'Hast du dich in einem NEUEN Terminal erfolgreich per SSH angemeldet? Nach der Bestätigung gibt es keine automatische Rücknahme mehr.'))) return;
            if (aktion !== 'verwerfen') {
                var c = this._code();
                if (c === null) return;
                body.nachweis = c;
            }
            var knopf = { test: 'sec-ssh-h-test', bestaetigen: 'sec-ssh-h-ok', verwerfen: 'sec-ssh-h-weg', aus: 'sec-ssh-h-aus' }[aktion];
            return this._senden('/api/broker/ssh/haertung', body, 'sec-ssh-h-result', knopf);
        },

        netze: function (aktion) {
            var body = { aktion: aktion };
            if (aktion === 'test') {
                body.netze = (($('sec-ssh-netze') || {}).value || '').trim();
                var frage = body.netze
                    ? T('security.ssh_n_test_confirm',
                        'SSH ist danach nur noch aus diesen Netzen erreichbar:\n%s\n\nPrüfe in einem NEUEN Terminal, ob du dich anmelden kannst, und bestätige dann. Ohne Bestätigung gilt nach 5 Minuten wieder der vorherige Stand.').replace('%s', body.netze)
                    : T('security.ssh_n_alle_confirm', 'SSH wird wieder aus allen Netzen erreichbar. Fortfahren?');
                if (!window.confirm(frage)) return;
            }
            if (aktion === 'bestaetigen' && !window.confirm(T('security.ssh_ok_confirm',
                'Hast du dich in einem NEUEN Terminal erfolgreich per SSH angemeldet? Nach der Bestätigung gibt es keine automatische Rücknahme mehr.'))) return;
            if (aktion !== 'verwerfen') {
                var c = this._code();
                if (c === null) return;
                body.nachweis = c;
            }
            var knopf = { test: 'sec-ssh-n-test', bestaetigen: 'sec-ssh-n-ok', verwerfen: 'sec-ssh-n-weg' }[aktion];
            var self = this;
            // Nach Erfolg zeigt die Liste wieder den Stand des Servers (normiert)
            return this._senden('/api/broker/ssh/netze', body, 'sec-ssh-n-result', knopf,
                                function () { self._netzeGeaendert = false; });
        }
    };

    // Rechenhelfer fuer den Waechter (tests/test_fernzugang_ui.js)
    Fz._rechnen = { ipZuZahl: ipZuZahl, netzNormieren: netzNormieren, enthaelt: enthaelt };
    window.Fernzugang = Fz;
})();
