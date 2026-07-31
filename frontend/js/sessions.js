/* Jarvis – Anwesenheit: Abmelde-Signal + Admin-Übersicht „Angemeldete Benutzer".
 *
 * Zwei Dinge in einer Datei, weil sie dieselbe Datenquelle betreffen:
 *
 *   window.JarvisSession.logout(token)  – meldet die Abmeldung am Server, BEVOR
 *       die Seite das Token verwirft. Ohne dieses Signal kann der Server
 *       „abgemeldet" nicht von „still geworden" unterscheiden (Tokens sind
 *       zustandslos, es gibt keine Sitzungstabelle).
 *
 *   window.UserSessions.init()          – das Panel hinter dem Personen-Symbol
 *       im Portal (nur Administratoren). Grüne Pille = online, graue = offline.
 */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function anyToken() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var v = localStorage.getItem(TOKEN_KEYS[i]);
                if (v) return v;
            } catch (e) { /* localStorage gesperrt */ }
        }
        return '';
    }

    function t(k, d) { return (window.t && window.t(k)) || d; }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // ── Abmelde-Signal ──────────────────────────────────────────────────────
    // `keepalive` ist hier der Kern: die Seite navigiert unmittelbar danach weg
    // bzw. verwirft das Token. Ohne keepalive bricht der Browser die Anfrage ab
    // und die Abmeldung käme nie an. sendBeacon scheidet aus – es kann keinen
    // Authorization-Header setzen.
    function logout(token) {
        var tok = token || anyToken();
        if (!tok) return Promise.resolve(false);
        try {
            return fetch('/api/logout', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + tok },
                keepalive: true,
            }).then(function () { return true; }).catch(function () { return false; });
        } catch (e) {
            return Promise.resolve(false);
        }
    }

    window.JarvisSession = { logout: logout, tokenKeys: TOKEN_KEYS };

    // ── Admin-Übersicht ─────────────────────────────────────────────────────
    var POLL_MS = 30000;
    var HOVER_ZU_MS = 350;      // Nachlauf beim Verlassen (Zittern vermeiden)
    var els = {};
    var _timer = null;
    var _bound = false;
    // Wodurch ist das Panel offen? Ein per KLICK geoeffnetes Panel darf beim
    // Wegbewegen der Maus NICHT zufallen - sonst waere die Liste nicht
    // benutzbar (Rechtsklick, Scrollen). Nur was der Hover geoeffnet hat,
    // schliesst der Hover auch wieder.
    var _viaHover = false;
    var _zuTimer = null;

    function fmt(ts) {
        if (!ts) return '–';
        var d = new Date(ts * 1000);
        var heute = new Date();
        var gleich = d.toDateString() === heute.toDateString();
        var uhr = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        if (gleich) return t('sessions.today', 'heute') + ' ' + uhr;
        return d.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' }) + ' ' + uhr;
    }

    // Ab wann "untätig" ausdruecklich gemeldet wird. Unter fuenf Minuten ist es
    // keine Aussage, sondern Rauschen (kurz nachgedacht, Kaffee geholt).
    var IDLE_AB = 300;
    // Ab wann die Angabe zusaetzlich FARBLICH auffaellt. Bewusst deutlich hoeher:
    // in einer Liste mit zwanzig Anmeldungen ist die Mehrheit fast immer laenger
    // als fuenf Minuten untaetig. Faerbte man ab IDLE_AB, waere die halbe Liste
    // orange – und eine Warnfarbe, die fast ueberall steht, ist keine Warnung
    // mehr, sondern Tapete. Die AUSSAGE kommt weiter ab fuenf Minuten, nur die
    // Hervorhebung wartet.
    var IDLE_WARN = 1800;

    function dauer(sek) {
        var s = Math.max(0, Math.floor(sek || 0));
        if (s < 60) return s + ' ' + t('sessions.sec', 'Sek.');
        if (s < 3600) return Math.floor(s / 60) + ' ' + t('sessions.min', 'Min.');
        if (s < 86400) {
            var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
            return h + ' ' + t('sessions.h', 'Std.') + (m ? ' ' + m + ' ' + t('sessions.min', 'Min.') : '');
        }
        return Math.floor(s / 86400) + ' ' + t('sessions.d', 'Tg.');
    }

    function relativ(ts) {
        if (!ts) return '';
        var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
        if (s < 60) return t('sessions.just_now', 'gerade eben');
        if (s < 3600) return Math.floor(s / 60) + ' ' + t('sessions.min_ago', 'Min.');
        if (s < 86400) return Math.floor(s / 3600) + ' ' + t('sessions.h_ago', 'Std.');
        return Math.floor(s / 86400) + ' ' + t('sessions.d_ago', 'Tg.');
    }

    // Alles, was NICHT in die sichtbare Zeile passt, steht im Titel. Bei vielen
    // Benutzern ist Ueberblick wichtiger als Vollstaendigkeit – die Zeitstempel
    // braucht man erst, wenn man einen bestimmten Benutzer schon gefunden hat.
    function titel(u) {
        var z = [u.username];
        if (u.display && u.display !== u.username) z[0] += ' (' + u.display + ')';
        if (u.last_action) {
            z.push(t('sessions.last_action', 'zuletzt') + ': ' + relativ(u.last_action)
                + (u.last_action_label ? ' – ' + u.last_action_label : ''));
        }
        z.push(t('sessions.seen', 'Anfrage') + ': '
            + (u.last_seen ? relativ(u.last_seen) : '–'));
        z.push(t('sessions.last_login', 'Anmeldung') + ': ' + fmt(u.last_login));
        z.push(t('sessions.last_logout', 'Abmeldung') + ': '
            + (u.last_logout ? fmt(u.last_logout) : t('sessions.never', 'nie')));
        return z.join('\n');
    }

    function zeile(u) {
        // Die Pille trägt die Aussage doppelt: Farbe UND Text. Farbe allein wäre
        // für Farbfehlsichtige keine Information.
        var pill = '<span class="pt-usr-pill ' + (u.online ? 'is-on' : 'is-off') + '">'
            + (u.online ? t('sessions.online', 'online') : t('sessions.offline', 'offline'))
            + '</span>';
        var api = u.kind === 'api'
            ? ' <span class="pt-usr-tag">API</span>' : '';
        // GENAU EINE Meta-Zeile, und zwar die Aussage, die man beim Blick in die
        // Liste sucht: Was hat der Benutzer zuletzt getan, und wie lange ist das
        // her? Bewusst getrennt von "anwesend": last_seen setzt jeder
        // Hintergrund-Poll, ein offener Tab saehe sonst dauerhaft aktiv aus.
        // "untätig seit X" und "zuletzt vor X" sind DERSELBE Wert
        // (idle_seconds = jetzt - last_action) – deshalb nie beides zeigen.
        var kurz;
        var label = u.last_action_label ? ' <i>' + esc(u.last_action_label) + '</i>' : '';
        if (!u.online && u.last_seen) {
            kurz = esc(t('sessions.offline_for', 'offline seit {d}')
                .replace('{d}', dauer(Math.floor(Date.now() / 1000 - u.last_seen)))) + label;
        } else if (!u.last_action) {
            kurz = esc(t('sessions.no_action', 'noch keine Aktion'));
        } else if (u.online && u.idle_seconds != null && u.idle_seconds >= IDLE_AB) {
            // Anwesend, aber seit einer Weile untaetig -> ausdruecklich sagen.
            // Hervorgehoben wird erst ab IDLE_WARN (siehe dort).
            kurz = '<span class="pt-usr-idle'
                + (u.idle_seconds >= IDLE_WARN ? ' is-warn' : '') + '">'
                + esc(t('sessions.idle_for', 'untätig seit {d}').replace('{d}', dauer(u.idle_seconds)))
                + '</span>' + label;
        } else {
            kurz = esc(t('sessions.last_action', 'zuletzt')) + ': <b>'
                + esc(relativ(u.last_action)) + '</b>' + label;
        }
        var gesperrt = u.blocked
            ? ' <span class="pt-usr-tag pt-usr-blocked">'
              + esc(t('sessions.blocked', 'gesperrt')) + '</span>' : '';
        // Sichtbarer Auslöser NEBEN dem Rechtsklick: ein Menü, das man nur per
        // Rechtsklick findet, findet niemand.
        var menue = '<button class="pt-usr-menubtn" type="button" tabindex="0"'
            + ' aria-haspopup="menu" title="' + esc(t('sessions.menu_open', 'Aktionen')) + '">⋯</button>';
        return '<div class="pt-usr-item" data-user="' + esc(u.username) + '"'
            + ' data-blocked="' + (u.blocked ? '1' : '0') + '"'
            + ' title="' + esc(titel(u)).replace(/\n/g, '&#10;') + '">'
            + '<div class="pt-usr-top">' + pill
            + '<span class="pt-usr-name">' + esc(u.display) + '</span>'
            + api + gesperrt + menue + '</div>'
            + '<div class="pt-usr-meta">' + kurz + '</div>'
            + '</div>';
    }

    var _mayBlock = false;
    var _users = [];        // letzter Stand vom Server (ungefiltert)
    var _filter = '';       // aktueller Suchbegriff, klein geschrieben
    var _stand = null;      // online/total/online_window der letzten Antwort

    function passt(u) {
        if (!_filter) return true;
        return String(u.username || '').toLowerCase().indexOf(_filter) !== -1
            || String(u.display || '').toLowerCase().indexOf(_filter) !== -1;
    }

    // Zeichnet aus _users + _filter. Getrennt von render(), damit die Eingabe
    // sofort wirkt, ohne auf den naechsten Abruf zu warten.
    function zeichne() {
        if (!els.list) return;
        var sicht = _users.filter(passt);
        if (!_users.length) {
            els.list.innerHTML = '<div class="pt-usr-empty">'
                + esc(t('sessions.empty', 'Noch keine Anmeldungen aufgezeichnet.')) + '</div>';
        } else if (!sicht.length) {
            els.list.innerHTML = '<div class="pt-usr-empty">'
                + esc(t('sessions.no_match', 'Kein Treffer für „{q}“.').replace('{q}', _filter))
                + '</div>';
        } else {
            els.list.innerHTML = sicht.map(zeile).join('');
        }
        // Ein Filterfeld ueber einer leeren Liste ist ein Filter fuer nichts.
        if (els.filter) els.filter.style.display = _users.length ? '' : 'none';
        if (els.count) {
            // Beim Filtern zaehlt die TREFFERZAHL – sonst stuende dort eine Zahl,
            // die zu der sichtbaren Liste nicht passt.
            els.count.textContent = _filter
                ? sicht.length + '/' + _users.length
                : (_stand && _stand.online != null ? _stand.online + '/' + _stand.total : '');
        }
    }

    function render(d) {
        if (!els.list) return;
        _mayBlock = !!(d && d.may_block);
        _users = (d && d.users) || [];
        _stand = d || null;
        zeichne();
        if (els.hint && d && d.online_window) {
            els.hint.textContent = t('sessions.hint', 'Online = Aktivität in den letzten {n} Sekunden. Wer den Browser schließt, ohne sich abzumelden, erscheint bis dahin weiter als online.')
                .replace('{n}', d.online_window);
        }
    }

    function load() {
        // Kein Abruf für ein geschlossenes Panel – der Poll läuft nur, solange
        // es offen ist (siehe toggle()).
        var tok = anyToken();
        if (!tok || !els.list) return;
        fetch('/api/sessions', { headers: { 'Authorization': 'Bearer ' + tok } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d && d.ok) render(d); })
            .catch(function () { });
    }

    // ── Aktionen ────────────────────────────────────────────────────────
    // ABMELDEN: Tokens sind zustandslos; der Server widerruft alle aelteren
    // Tokens des Benutzers. Wirkung beim naechsten Request des Betroffenen –
    // kein Sperren, eine Neuanmeldung geht sofort wieder.
    // SPERREN: dauerhaft, bis jemand entsperrt (security_guard).
    function ruf(pfad, koerper, fehlerText) {
        var tok = anyToken();
        if (!tok) return;
        fetch(pfad, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' },
            body: JSON.stringify(koerper || {}),
        }).then(function (r) { return r.json().catch(function () { return {}; }); })
          .then(function (d) {
              if (!d || !d.ok) { window.alert((d && d.detail) || fehlerText); return; }
              load();
          })
          .catch(function () { window.alert(fehlerText); });
    }

    function kick(name) {
        if (!window.confirm(t('sessions.kick_confirm', '{u} abmelden?').replace('{u}', name))) return;
        ruf('/api/sessions/' + encodeURIComponent(name) + '/logout', null,
            t('sessions.kick_failed', 'Abmelden fehlgeschlagen.'));
    }

    function sperren(name) {
        if (!window.confirm(t('sessions.block_confirm', '{u} sperren?').replace('{u}', name))) return;
        ruf('/api/security/incidents/block', { user: name },
            t('sessions.block_failed', 'Sperren fehlgeschlagen.'));
    }

    function entsperren(name) {
        if (!window.confirm(t('sessions.unblock_confirm', 'Sperre für {u} aufheben?').replace('{u}', name))) return;
        ruf('/api/security/incidents/unblock', { user: name },
            t('sessions.unblock_failed', 'Entsperren fehlgeschlagen.'));
    }

    // ── Kontextmenue ────────────────────────────────────────────────────
    var _menu = null;

    function menuZu() {
        if (_menu) { _menu.remove(); _menu = null; }
    }

    function menuAuf(zeile, x, y) {
        menuZu();
        var name = zeile.getAttribute('data-user') || '';
        var gesperrt = zeile.getAttribute('data-blocked') === '1';
        if (!name) return;
        var m = document.createElement('div');
        m.className = 'pt-usr-menu';
        m.setAttribute('role', 'menu');
        var eintraege = [
            { key: 'kick', text: t('sessions.menu_kick', 'Benutzer abmelden'), icon: '⎋' },
        ];
        // Sperren/Entsperren ist lokalen Benutzern vorbehalten – der Server
        // wuerde sonst mit 403 antworten. Lieber gar nicht anbieten.
        if (_mayBlock) {
            eintraege.push(gesperrt
                ? { key: 'unblock', text: t('sessions.menu_unblock', 'Benutzer entsperren'), icon: '🔓' }
                : { key: 'block', text: t('sessions.menu_block', 'Benutzer sperren'), icon: '🔒', gefahr: true });
        }
        m.innerHTML = '<div class="pt-usr-menu-head">' + esc(name) + '</div>'
            + eintraege.map(function (e) {
                return '<button type="button" class="pt-usr-menu-item'
                    + (e.gefahr ? ' is-danger' : '') + '" data-do="' + e.key + '" role="menuitem">'
                    + '<span class="pt-usr-menu-ico">' + e.icon + '</span>' + esc(e.text) + '</button>';
            }).join('');
        document.body.appendChild(m);
        // Im Fenster halten (das Panel sitzt am rechten Rand).
        var br = m.getBoundingClientRect();
        m.style.left = Math.max(6, Math.min(x, window.innerWidth - br.width - 6)) + 'px';
        m.style.top = Math.max(6, Math.min(y, window.innerHeight - br.height - 6)) + 'px';
        _menu = m;
        m.addEventListener('click', function (e) {
            var b = e.target.closest ? e.target.closest('.pt-usr-menu-item') : null;
            if (!b) return;
            var was = b.getAttribute('data-do');
            menuZu();
            if (was === 'kick') kick(name);
            else if (was === 'block') sperren(name);
            else if (was === 'unblock') entsperren(name);
        });
        // Erster Eintrag bekommt den Fokus (Tastaturbedienung).
        var erster = m.querySelector('.pt-usr-menu-item');
        if (erster) erster.focus();
    }

    function offen() { return els.panel && !els.panel.hasAttribute('hidden'); }

    function schliessen() {
        menuZu();
        // Filter zuruecksetzen: ein beim naechsten Oeffnen noch gesetzter
        // Begriff liesse die Liste unvollstaendig aussehen.
        if (els.search && els.search.value) els.search.value = '';
        if (_filter) { _filter = ''; zeichne(); }
        if (_zuTimer) { clearTimeout(_zuTimer); _zuTimer = null; }
        _viaHover = false;
        if (els.panel) els.panel.setAttribute('hidden', '');
        if (els.btn) els.btn.setAttribute('aria-expanded', 'false');
        if (_timer) { clearInterval(_timer); _timer = null; }
    }

    function oeffnen(viaHover) {
        if (_zuTimer) { clearTimeout(_zuTimer); _zuTimer = null; }
        if (offen()) {
            // Bereits offen: ein Klick auf ein per Hover geoeffnetes Panel
            // macht es dauerhaft (sonst faellt es beim Wegziehen wieder zu).
            if (!viaHover) _viaHover = false;
            return;
        }
        _viaHover = !!viaHover;
        if (els.panel) els.panel.removeAttribute('hidden');
        if (els.btn) els.btn.setAttribute('aria-expanded', 'true');
        load();
        if (!_timer) _timer = setInterval(load, POLL_MS);
    }

    // Klick am Knopf. FALLSTRICK: Wer den Knopf anklickt, hat ihn vorher
    // ueberfahren – mouseenter oeffnet das Panel also SCHON, bevor der Klick
    // ankommt. Ein reiner Umschalter wuerde es damit sofort wieder schliessen,
    // der Klick saehe wirkungslos aus. Deshalb: ist das Panel per HOVER offen,
    // macht der erste Klick es dauerhaft (festhalten), der zweite schliesst.
    // Fuer den Benutzer bleibt es damit das gewohnte Auf/Zu.
    function toggle() {
        if (!offen()) { oeffnen(false); return; }
        if (_viaHover) { oeffnen(false); return; }   // festhalten statt schliessen
        schliessen();
    }

    function init() {
        els.wrap = document.getElementById('pt-usr-wrap');
        els.btn = document.getElementById('pt-usr-btn');
        els.panel = document.getElementById('pt-usr-panel');
        els.list = document.getElementById('pt-usr-list');
        els.count = document.getElementById('pt-usr-count');
        els.hint = document.getElementById('pt-usr-hint');
        els.filter = document.getElementById('pt-usr-filter');
        els.search = document.getElementById('pt-usr-search');
        if (!els.wrap || !els.btn) return;
        els.wrap.style.display = '';        // erst jetzt sichtbar (Admin bestätigt)
        if (_bound) return;
        _bound = true;
        els.btn.addEventListener('click', function (e) { e.stopPropagation(); toggle(); });

        // Hover oeffnet, Verlassen schliesst - aber nur, wenn der Hover es auch
        // geoeffnet hat. Gebunden am WRAP (Knopf + Panel liegen darin), sonst
        // faellt das Panel beim Weg vom Knopf zur Liste zu.
        els.wrap.addEventListener('mouseenter', function () { oeffnen(true); });
        els.wrap.addEventListener('mouseleave', function () {
            if (!_viaHover) return;                    // per Klick geoeffnet: bleibt
            if (_zuTimer) clearTimeout(_zuTimer);
            _zuTimer = setTimeout(function () {
                if (_viaHover) schliessen();
            }, HOVER_ZU_MS);
        });

        if (els.search) {
            els.search.addEventListener('input', function () {
                _filter = String(els.search.value || '').trim().toLowerCase();
                zeichne();
            });
            // FALLSTRICK: Wer tippt, bewegt die Maus dabei leicht – bei einem
            // per Hover geoeffneten Panel faellt es sonst mitten in der Eingabe
            // zu. Fokus im Feld heftet es fest, wie ein Klick.
            els.search.addEventListener('focus', function () {
                _viaHover = false;
                if (_zuTimer) { clearTimeout(_zuTimer); _zuTimer = null; }
            });
            // Escape leert ZUERST den Filter und schliesst erst beim zweiten
            // Druck das Panel – sonst verliert man mit dem Filter die ganze
            // Liste, obwohl man nur die Eingabe loswerden wollte.
            els.search.addEventListener('keydown', function (e) {
                if (e.key !== 'Escape' || !els.search.value) return;
                els.search.value = '';
                _filter = '';
                zeichne();
                e.stopPropagation();
                e.preventDefault();
            });
        }

        // Menue: per Rechtsklick auf die Zeile ODER ueber den ⋯-Knopf.
        function oeffneMenue(e, row) {
            // Ein per Hover geoeffnetes Panel darf waehrend des Menues nicht
            // zufallen – der Mauszeiger verlaesst es dabei.
            _viaHover = false;
            if (_zuTimer) { clearTimeout(_zuTimer); _zuTimer = null; }
            menuAuf(row, e.clientX, e.clientY);
        }
        els.list.addEventListener('contextmenu', function (e) {
            var row = e.target && e.target.closest ? e.target.closest('.pt-usr-item') : null;
            if (!row) return;
            e.preventDefault();
            oeffneMenue(e, row);
        });
        els.list.addEventListener('click', function (e) {
            var btn = e.target && e.target.closest ? e.target.closest('.pt-usr-menubtn') : null;
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            var row = btn.closest('.pt-usr-item');
            if (row) oeffneMenue(e, row);
        });
        // Klick daneben / Escape schliesst das Menue – vor dem Panel.
        document.addEventListener('click', function (e) {
            if (_menu && !_menu.contains(e.target)) menuZu();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && _menu) { menuZu(); e.stopPropagation(); }
        }, true);
        // Klick daneben schließt – wie beim Dokumente-Panel.
        document.addEventListener('click', function (e) {
            if (offen() && els.wrap && !els.wrap.contains(e.target)) schliessen();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && offen()) schliessen();
        });
    }

    window.UserSessions = { init: init, load: load, close: schliessen };
})();
