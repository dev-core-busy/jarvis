/* Einstellungs-Zahnrad in der Titelleiste – EINE Stelle fuer ALLE Bereichsseiten.
 *
 * WARUM ZENTRAL (gemeldet dreimal, zuletzt 2026-08-23 "IMMER NOCH kein
 * Einstellungen Symbol"):
 * Jede Seite hatte ihre eigene Verdrahtung, und drei davon hingen am ABRUF DES
 * BEREICHS statt am Administrator-Status:
 *     /tracks  -> `ist_admin` aus GET /api/tracks/status
 *     /claude  -> `ist_admin` aus GET /api/claude/status
 *     /wissen  -> `is_admin`  aus GET /api/wissen/scope
 * Scheitert dieser Abruf, laeuft die Einblendung NIE. Und er scheitert genau
 * dann, wenn der Bereich noch nicht freigegeben ist (403 "nicht in der
 * Benutzerliste/-Gruppe freigeschaltet") oder ein Zeitlimit zuschlaegt – also in
 * dem Moment, in dem ein Administrator den Weg in die Einstellungen am
 * dringendsten braucht, denn DORT wird die Freigabe gepflegt. Auf DEV
 * nachgemessen: `/api/tracks/status` und `/api/claude/status` antworten fuer
 * einen Administrator ohne Bereichs-Freigabe mit 403 – der Knopf blieb weg,
 * obwohl `/api/me` fuer denselben Benutzer `is_admin: true` liefert.
 *
 * Der Knopf beantwortet EINE Frage: "Bist du Administrator?" Die beantwortet
 * `/api/me` – und nur die darf ihn steuern.
 *
 * KONVENTION STATT AUFZAEHLUNG: gesucht wird `[data-jarvis-settings]`. Eine neue
 * Bereichsseite setzt das Attribut und bindet dieses Modul ein, mehr nicht – sie
 * kann den Fehler nicht wiederholen (dieselbe Lehre wie bei den MCP-Gates und
 * bei `icons.js`: eine Regel erwischt neue Faelle von selbst, eine Liste nie).
 * Der Attributwert ist der Rueckweg fuer /settings; ohne Wert gilt der aktuelle
 * Pfad.
 *
 * BADGE (offene Root-Freigaben + gesperrte Konten): die Zahlen kommen aus
 * DERSELBEN /api/me-Antwort (`admin_badge`), die den Knopf ohnehin einblendet –
 * kein zusaetzlicher Roundtrip. Es gab sie schon einmal im alten
 * Einzelseiten-Hauptfenster (`gear-broker-badge` in app.js); sie fiel am
 * 2026-07-15 mit `bc41701` als toter Code, weil das Zahnrad in die
 * Bereichsseiten gewandert war und das Element nicht mitgenommen wurde. Sie
 * gehoert deshalb HIERHIN und nicht in eine Seite: sonst haette sie elf
 * Fassungen, und die zwoelfte Seite vergisst sie wieder.
 *
 * SSH-FEHLANMELDUNGEN (Serverueberwachung B13, Betreiberentscheid 2026-11-21):
 * stehen HIER als ein Posten und nicht an der CPU-Anzeige. In den
 * Einstellungen gibt es keinen Abschnitt, der sie erledigt – ein Klick auf
 * die Zeile klappt deshalb die einzelnen Versuche der letzten 24 Stunden auf
 * (Zeitpunkt, Anzahl, Quelladressen, Benutzer). Bis 2026-11-22 war die Zeile
 * ohne Wirkung, waehrend darunter "Eintrag anklicken, um den Abschnitt zu
 * oeffnen" stand – gemeldet als "ein Klick hat keine Wirkung". Der Hinweis
 * nennt jetzt, was der Klick bei welcher Zeile tut. Ein SSH-Alarm
 * (Durchprobieren) faerbt die Badge wie eine Sperre.
 *
 * SERVERUEBERWACHUNG (B13, Betreiberentscheid 2026-11-25): ALLE Warnungen und
 * Alarme stehen hier, nicht an der CPU-Anzeige – gemeldet als "'Serverüberwachung
 * Warnung' in der CPU Pill … das gehört in die Zahnrad Badge", nachdem am
 * 2026-11-21 nur die SSH-Fehlanmeldungen umgezogen waren. Je Befund eine
 * Zeile (der Text kommt aus derselben Vorlage `ue.art_*` wie die Mails). Zeilen
 * der Integritaetspruefung fuehren in den Container "Paket-Updates und
 * Integritaet" (dort liegt die Liste zur Durchsicht); die uebrigen haben keinen
 * Abschnitt, der sie erledigt – sie sind kein Knopf und versprechen keinen Sprung.
 * Ein Alarm faerbt die Badge wie eine Sperre.
 *
 * Ein Klick auf die Badge fuehrt in den Sicherheits-Reiter (sessionStorage
 * `jarvis_settings_tab`, ausgewertet in app.js) – eine Warnung ohne Weg zur
 * Abhilfe ist nur Laerm (dieselbe Regel wie beim Lizenz-Banner im Portal).
 *
 * MOUSEOVER AM BADGE (2026-08-30, nach dem Vorbild des Issues-Badges): die Zahl
 * sagt "3" und sonst nichts. Wer wissen wollte, WAS zu tun ist, musste erst
 * /settings oeffnen und den Sicherheits-Reiter durchsehen – bei zwei
 * gleichzeitigen Quellen (offene Freigaben UND Sperren) sogar zwei getrennte
 * Abschnitte. Das Panel zeigt die Eintraege dahinter, und jede Zeile fuehrt in
 * GENAU den Abschnitt, der sie erledigt (`jarvis_settings_focus`). Ein nativer
 * `title` konnte das nie: er kommt verzoegert, laesst sich nicht anklicken und
 * wird je nach Browser hart abgeschnitten.
 *
 * ADMIN-RECHTE AM ZAHNRAD (Betreiberentscheid 2026-11-20): bei der Anmeldung
 * wird ein Administrator nicht mehr nach der 2FA gefragt, jede Sitzung beginnt
 * OHNE Admin-Rechte. Sichtbar ist das Zahnrad deshalb fuer jedes Admin-KONTO
 * (`admin_konto` aus /api/me), nicht erst fuer eine Sitzung mit Rechten
 * (`is_admin`). Ein Klick fragt den Server (POST /api/admin/erhoehen), und der
 * entscheidet den Weg: es erscheint der Dialog fuer den Code bzw. – ohne
 * eingerichtete 2FA – fuer QR-Code, Code und Kennwort. Einen Weg ohne Code
 * gibt es nicht, auch nicht nach einer Firmenkonto-Anmeldung mit MFA. Mit Rechten traegt das
 * Zahnrad die Markierung `.jv-gear-erhoeht`, und ein Klick oeffnet ein Menue
 * mit "Einstellungen oeffnen" und "Administration beenden" (auf /settings nur
 * Letzteres). Beenden nimmt die Rechte der SITZUNG zurueck (alle Tabs), die
 * Anmeldung bleibt.
 *
 * Die Admin-Oberflaeche der Seite haengt an `is_admin` aus den Abrufen beim
 * Seitenaufbau. Nach dem Holen bzw. Abgeben wird deshalb die Seite gewechselt
 * bzw. neu geladen – ein halb umgeschalteter Zustand waere eine Anzeige, die
 * Rechte behauptet, die die Sitzung nicht (mehr) hat.
 */
(function () {
    'use strict';

    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();

    // Letzter Stand aus /api/me: {root_pending, gesperrt, gesamt}. null = noch
    // nichts gemessen (dann wird auch nichts behauptet, also keine Badge).
    var _badge = null;
    var _admin = false;      // Admin-Rechte DIESER Sitzung (nach dem Zahnrad)
    var _konto = false;      // Admin-KONTO: das Zahnrad wird angeboten
    var _pollTimer = null;
    var POLL_MS = 60000;   // wie die alte Fassung in app.js

    function T(key, fallback) {
        try { if (window.t) return window.t(key) || fallback; } catch (e) {}
        return fallback;
    }

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var t = localStorage.getItem(TOKEN_KEYS[i]);
                if (t) return t;
            } catch (e) { /* Speicher gesperrt (privates Fenster, iframe) */ }
        }
        return '';
    }

    function knoepfe() {
        return Array.prototype.slice.call(
            document.querySelectorAll('[data-jarvis-settings]'));
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* Wechselt nach /settings – mit Rueckweg, Reiter und (optional) dem
     * Abschnitt, der den Eintrag erledigt.
     *
     * Der Rueckweg kommt aus dem Zahnrad-Knopf: die Zeilen des Panels haengen
     * an `body` und koennen den Klick nicht an ihn weiterreichen, sonst waere
     * es dieselbe Bahn wie beim Klick auf die Badge. */
    function nachSettings(fokus, reiter) {
        var b = knoepfe()[0];
        var ziel = (b && b.getAttribute('data-jarvis-settings')) || location.pathname;
        try {
            sessionStorage.setItem('jarvis_settings_return', ziel);
            sessionStorage.setItem('jarvis_settings_tab', reiter || 'security');
            if (fokus) sessionStorage.setItem('jarvis_settings_focus', fokus);
            else sessionStorage.removeItem('jarvis_settings_focus');
        } catch (e) { /* egal - dann oeffnet der Vorgabe-Reiter */ }
        location.href = '/settings';
    }

    // ── Mouseover am Badge: was hinter der Zahl steckt ──────────────────────
    var _tip = null;
    var _tipTimer = null;
    // SSH-Zeile aufgeklappt? Lebt im Modul: das Panel wird im 60-s-Takt neu
    // gezeichnet und klappte sonst unter dem Zeiger wieder zu.
    var _sshOffen = false;

    function tipEl() {
        if (_tip) return _tip;
        _tip = document.createElement('div');
        _tip.className = 'jv-gear-tip';
        _tip.setAttribute('role', 'group');
        // Der Zeiger muss vom Badge INS Panel wandern koennen (die Zeilen sind
        // anklickbar). Deshalb haelt das Panel sich selbst offen.
        _tip.addEventListener('mouseenter', function () { clearTimeout(_tipTimer); });
        _tip.addEventListener('mouseleave', tipAusGleich);
        document.body.appendChild(_tip);
        return _tip;
    }

    /* Welcher Abschnitt des Sicherheits-Reiters erledigt diesen Eintrag?
     * Die Zuordnung steht HIER und nicht im Backend: sie beschreibt die
     * Oberflaeche, nicht die Daten. */
    function fokusFuer(art) {
        return art === 'blocked' ? 'incidents' : 'broker';
    }

    // Befunde der Serverueberwachung, die ein Abschnitt erledigt – und welcher:
    // {Befundart: [Reiter, Abschnitt]}. Alles andere ist ohne Sprung.
    var UE_ZIEL = {
        aide_offen: ['profiles', 'pakete'],
        aide_fehler: ['profiles', 'pakete'],
        aide_veraltet: ['profiles', 'pakete'],
    };

    function ueZiel(it) {
        return (it && it.art === 'ue' && UE_ZIEL.hasOwnProperty(it.ue_art)) ? UE_ZIEL[it.ue_art] : null;
    }

    /** Fuehrt diese Zeile irgendwohin? (SSH klappt auf, Ueberwachung nur mit Ziel) */
    function springt(it) {
        if (it.art === 'ssh') return false;
        if (it.art === 'ue') return !!ueZiel(it);
        return true;
    }

    function ueZeit(sek) {
        if (!sek) return '';
        try {
            return new Date(sek * 1000).toLocaleString(({ en: 'en-GB', fr: 'fr-FR' }[window._lang] || 'de-DE'),
                { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch (e) { return ''; }
    }

    function ueZahl(n, stellen) {
        var loc = ({ en: 'en-US', fr: 'fr-FR' }[window._lang] || 'de-DE');
        try {
            return Number(n).toLocaleString(loc, { minimumFractionDigits: stellen,
                                                   maximumFractionDigits: stellen });
        } catch (e) { return Number(n).toFixed(stellen); }
    }

    /** Text eines Befunds in der Oberflaechensprache (Vorlage `ue.art_*`, dieselbe
     *  wie in den Mails); ohne Vorlage der Text des Servers. Aus sysload.js
     *  hierher umgezogen (2026-11-25) – EINE Fassung. */
    function ueText(it) {
        var w = (it.werte && typeof it.werte === 'object') ? it.werte : {};
        var art = it.ue_art;
        if (art === 'zert_ablauf' && Number(w.tage) < 0) art = 'zert_abgelaufen';
        if (art === 'in_drop' && it.stufe === 'warnung') art = 'in_drop_voll';
        var schluessel = 'ue.art_' + art;
        var vorlage = T(schluessel, '');
        if (!vorlage || vorlage === schluessel) return String(it.titel || '');
        return vorlage.replace(/\{(\w+)\}/g, function (_, k) {
            var v = w[k];
            // {marke} kommt nicht vom Server: der Name der Oberflaeche (branding.js)
            if (k === 'marke') {
                var m = 'Jarvis';
                try { if (window.jarvisMarke) m = window.jarvisMarke() || m; } catch (e) { /* Rueckfall bleibt */ }
                return m;
            }
            if (k === 'zuletzt') return ueZeit(v);
            if (k === 'ablauf') return ueZeit(v).split(',')[0];
            if (Array.isArray(v)) return v.join(', ');
            if (typeof v === 'number' && k === 'prozent') return ueZahl(v, 1);
            return v == null ? '' : String(v);
        });
    }

    /* Zeile eines Befunds der Serverueberwachung. Mit Ziel ein Knopf, sonst ein
     * stiller Eintrag – ein Knopf ohne Wirkung waere die Meldung vom 2026-11-22
     * ("ein Klick hat keine Wirkung") noch einmal. Alles maskiert: Texte und
     * Werte stammen aus Journal, nft und Dateinamen. */
    function ueZeile(it) {
        var ziel = ueZiel(it);
        var alarm = it.stufe === 'alarm';
        var marke = alarm ? T('ue.alarm', 'Alarm') : T('ue.warnung', 'Warnung');
        var seit = it.ts ? T('ue.seit', 'seit {t}').replace('{t}', zeitpunkt(it.ts)) : '';
        var innen = '<div class="jv-gear-tip-top">'
            + '<span class="jv-gear-tip-k ' + (alarm ? 'blocked' : 'root') + '">' + esc(marke) + '</span>'
            + '<span class="jv-gear-tip-t">' + (esc(ueText(it)) || '–') + '</span>'
            + '</div>'
            + '<div class="jv-gear-tip-sub">' + esc([T('ue.titel', 'Serverüberwachung'), seit]
                .filter(Boolean).join(' · ')) + '</div>';
        if (ziel) {
            return '<button type="button" class="jv-gear-tip-row" data-ue="' + esc(it.ue_art)
                + '" data-fokus="' + esc(ziel[1]) + '" data-reiter="' + esc(ziel[0]) + '">' + innen + '</button>';
        }
        return '<div class="jv-gear-tip-row jv-gear-tip-still" data-ue="' + esc(it.ue_art) + '">' + innen + '</div>';
    }

    function tipZeichnen() {
        var el = tipEl();
        var posten = (_badge && _badge.items) || [];
        var gesamt = (_badge && _badge.gesamt) || 0;
        el.setAttribute('aria-label', T('security.gear_tip_title', 'Zu erledigen'));
        var zeilen = posten.map(function (it) {
            if (it.art === 'ssh') return sshZeile(it);
            if (it.art === 'ue') return ueZeile(it);
            var blockiert = it.art === 'blocked';
            var marke = blockiert
                ? T('security.gear_tip_blocked', 'Gesperrt')
                : T('security.gear_tip_root', 'Freigabe');
            // Fremdtext: Befehlsbeschreibung, Benutzername und Sperrgrund
            // stammen aus fremden Quellen und werden ausnahmslos maskiert.
            var sub = it.sub
                ? (blockiert ? esc(it.sub)
                             : esc(T('security.gear_tip_by', 'angefragt von')
                                   + ' ' + it.sub))
                : '';
            var zeit = it.ts ? zeitpunkt(it.ts) : '';
            var unten = [sub, zeit].filter(Boolean).join(' · ');
            return '<button type="button" class="jv-gear-tip-row" data-fokus="'
                + esc(fokusFuer(it.art)) + '">'
                + '<div class="jv-gear-tip-top">'
                + '<span class="jv-gear-tip-k ' + (blockiert ? 'blocked' : 'root') + '">'
                + esc(marke) + '</span>'
                + '<span class="jv-gear-tip-t">' + (esc(it.titel) || '–') + '</span>'
                + '</div>'
                + (unten ? '<div class="jv-gear-tip-sub">' + unten + '</div>' : '')
                + '</button>';
        }).join('');
        // ⚠ Die Restzahl MUSS dastehen: der Server deckelt die Uebertragung.
        // Ohne diese Zeile haelt der Administrator die gekuerzte Liste fuer
        // vollstaendig, waehrend die Badge eine groessere Zahl zeigt.
        var rest = gesamt - posten.length;
        var mehr = rest > 0
            ? '<div class="jv-gear-tip-more">'
              + esc(T('security.gear_tip_more', '… und {n} weitere')
                    .replace('{n}', String(rest))) + '</div>'
            : '';
        // Aeltere Fassungen liefern `items` nicht mit. Dann steht statt einer
        // Liste die Aufschluesselung nach Quellen da – eine leere Flaeche waere
        // die Behauptung, es gaebe nichts (Register).
        var ersatz = '<div class="jv-gear-tip-hint">' + esc(quellenText()) + '</div>';
        el.innerHTML = '<div class="jv-gear-tip-h">'
            + esc(T('security.gear_tip_title', 'Zu erledigen'))
            + ' (' + gesamt + ')</div>'
            + (zeilen || ersatz)
            + mehr
            + tipHinweis(posten);
        // Die SSH-Zeile klappt auf, statt zu springen: kein Abschnitt erledigt sie.
        Array.prototype.forEach.call(el.querySelectorAll('.jv-gear-tip-row[data-ssh]'),
            function (b) {
                b.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    _sshOffen = !_sshOffen;
                    tipZeichnen();
                    var neu = el.querySelector('.jv-gear-tip-row[data-ssh]');
                    if (neu) neu.focus();
                });
            });
        // Nur Zeilen MIT Abschnitt fuehren nach /settings.
        Array.prototype.forEach.call(el.querySelectorAll('.jv-gear-tip-row[data-fokus]'),
            function (b) {
                b.addEventListener('click', function () {
                    nachSettings(b.getAttribute('data-fokus'), b.getAttribute('data-reiter') || '');
                });
            });
    }

    /* SSH-Zeile: kein Knopf (kein Abschnitt, der sie erledigt). Titel und
     * Unterzeile aus der Uebersetzung; Adresse und Benutzer sind Fremdtext und
     * werden maskiert. */
    function sshZeile(it) {
        var titel = T('security.gear_ssh_titel', '{n} fehlgeschlagene SSH-Anmeldungen in 24 Stunden')
            .replace('{n}', String(Number(it.anzahl) || 0));
        if (titel.indexOf('security.') === 0) titel = String(it.titel || '');
        var sub = it.ip ? T('security.gear_ssh_sub', 'zuletzt von {ip}').replace('{ip}', String(it.ip)) : '';
        if (sub.indexOf('security.') === 0) sub = String(it.ip || '');
        if (it.user) sub += ' (' + it.user + ')';
        var unten = [esc(sub), it.ts ? zeitpunkt(it.ts) : ''].filter(Boolean).join(' · ');
        var verlauf = Array.isArray(it.verlauf) ? it.verlauf : [];
        return '<button type="button" class="jv-gear-tip-row" data-ssh="1" aria-expanded="'
            + (_sshOffen ? 'true' : 'false') + '">'
            + '<div class="jv-gear-tip-top">'
            + '<span class="jv-gear-tip-k ' + (it.alarm ? 'blocked' : 'root') + '">'
            + esc(T('security.gear_tip_ssh', 'SSH')) + '</span>'
            + '<span class="jv-gear-tip-t">' + esc(titel) + '</span>'
            + '<span class="jv-gear-tip-auf" aria-hidden="true">' + (_sshOffen ? '▾' : '▸') + '</span>'
            + '</div>'
            + (unten ? '<div class="jv-gear-tip-sub">' + unten + '</div>' : '')
            + (_sshOffen ? sshVerlauf(verlauf, Number(it.verlauf_gesamt) || verlauf.length) : '')
            + '</button>';
    }

    /* Die einzelnen Laeufe mit Fehlversuchen, juengster zuerst. Adressen und
     * Benutzer stammen aus dem sshd-Journal (Fremdtext) und werden maskiert. */
    function sshVerlauf(verlauf, gesamt) {
        if (!verlauf.length) {
            return '<div class="jv-gear-tip-detail">'
                + esc(T('security.gear_ssh_kein_verlauf', 'Keine Einzelheiten gespeichert.')) + '</div>';
        }
        var zeilen = verlauf.map(function (v) {
            var ips = (Array.isArray(v.ips) ? v.ips : []).filter(Boolean).join(', ') || '–';
            var text = T('security.gear_ssh_versuch', '{n} × von {ips}')
                .replace('{n}', String(Number(v.anzahl) || 0)).replace('{ips}', ips);
            if (text.indexOf('security.') === 0) text = String(Number(v.anzahl) || 0) + ' × ' + ips;
            if (v.user) text += ' (' + v.user + ')';
            return '<div class="jv-gear-tip-dz">' + esc((v.zeit ? zeitpunkt(v.zeit) + ' · ' : '') + text) + '</div>';
        }).join('');
        var rest = gesamt - verlauf.length;
        var mehr = rest > 0
            ? '<div class="jv-gear-tip-dz">' + esc(T('security.gear_ssh_mehr', '… und {n} frühere')
                  .replace('{n}', String(rest))) + '</div>'
            : '';
        return '<div class="jv-gear-tip-detail">' + zeilen + mehr + '</div>';
    }

    /* Was ein Klick tut, je nach den Zeilen, die dastehen – ein Hinweis, der
     * fuer eine Zeile nicht stimmt, ist die gemeldete "keine Wirkung". */
    function tipHinweis(posten) {
        var mitSprung = posten.some(function (it) { return springt(it) && it.art !== 'ue'; });
        var ssh = posten.some(function (it) { return it.art === 'ssh'; });
        var ueSprung = posten.some(function (it) { return it.art === 'ue' && springt(it); });
        var ueStill = posten.some(function (it) { return it.art === 'ue' && !springt(it); });
        var teile = [];
        if (mitSprung || !posten.length) {
            teile.push(T('security.gear_tip_hint', 'Eintrag anklicken, um den Abschnitt zu öffnen'));
        }
        if (ssh) {
            teile.push(T('security.gear_tip_hint_ssh', 'SSH-Eintrag anklicken, um die einzelnen Versuche zu sehen'));
        }
        if (ueSprung) {
            teile.push(T('security.gear_ue_hint_aide', 'Eintrag zur Integritätsprüfung anklicken, um die Liste zur Durchsicht zu öffnen'));
        }
        if (ueStill) {
            teile.push(T('security.gear_ue_hint', 'Meldungen der Serverüberwachung verschwinden von selbst, sobald die Ursache behoben ist'));
        }
        return teile.map(function (s) { return '<div class="jv-gear-tip-hint">' + esc(s) + '</div>'; }).join('');
    }

    function tipAn(anker) {
        clearTimeout(_tipTimer);
        if (!(_admin && _badge && _badge.gesamt)) return;
        var el = tipEl();
        tipZeichnen();
        el.style.display = 'block';
        // Erst nach dem Einblenden messen – ein verstecktes Element hat die
        // Breite 0, die Klammerung liefe ins Leere (Register).
        var a = anker.getBoundingClientRect();
        var b = el.getBoundingClientRect();
        var rand = 8;
        var links = a.right - b.width;               // rechtsbuendig zum Badge
        links = Math.max(rand, Math.min(links, window.innerWidth - b.width - rand));
        var oben = a.bottom + 8;
        // Kein Platz nach unten? Dann darueber – sonst haengt das Panel im
        // Nichts und ist unlesbar.
        if (oben + b.height > window.innerHeight - rand) {
            oben = Math.max(rand, a.top - b.height - 8);
        }
        el.style.left = links + 'px';
        el.style.top = oben + 'px';
    }

    function tipAus() {
        clearTimeout(_tipTimer);
        if (_tip) _tip.style.display = 'none';
    }

    // Verzoegert schliessen: der Weg vom Badge ins Panel fuehrt ueber ein paar
    // Pixel Zwischenraum. Ohne die Frist waere keine Zeile je anklickbar.
    function tipAusGleich() {
        clearTimeout(_tipTimer);
        _tipTimer = setTimeout(tipAus, 220);
    }

    function tipOffen() {
        return !!(_tip && _tip.style.display === 'block');
    }

    /** Kurzer Datums-/Zeitstempel in der Sprache des Browsers. */
    function zeitpunkt(ts) {
        try {
            return new Date(ts * 1000).toLocaleString(undefined,
                { day: '2-digit', month: '2-digit', hour: '2-digit',
                  minute: '2-digit' });
        } catch (e) { return ''; }
    }

    /** „Offene Root-Freigaben: 2 · Gesperrte Konten: 1" – die Aufschluesselung
     *  nach Quellen. Sie ist die Beschriftung der Badge (aria-label) UND der
     *  Rueckfall im Panel, wenn `items` fehlt. */
    function quellenText() {
        var teile = [];
        if (_badge && _badge.root_pending) {
            teile.push(T('security.gear_badge_title', 'Offene Root-Freigaben')
                + ': ' + _badge.root_pending);
        }
        if (_badge && _badge.gesperrt) {
            teile.push(T('security.gear_badge_blocked', 'Gesperrte Konten')
                + ': ' + _badge.gesperrt);
        }
        if (_badge && _badge.ssh_fehl) {
            teile.push(T('security.gear_badge_ssh', 'Fehlgeschlagene SSH-Anmeldungen (24 h)')
                + ': ' + _badge.ssh_fehl);
        }
        if (_badge && _badge.ue_warnungen) {
            teile.push(T('security.gear_badge_ue', 'Warnungen der Serverüberwachung')
                + ': ' + _badge.ue_warnungen);
        }
        return teile.join(' · ');
    }

    /* Malt die Badge in JEDEN Zahnrad-Knopf (bzw. entfernt sie wieder).
     *
     * Wird aus `zeige()` gerufen, damit ein NACHTRAEGLICH erzeugter Knopf sie
     * ebenfalls bekommt (claude_portal.js baut bei 403 eine Absage-Seite samt
     * Knopf) – und aus dem Sprachwechsel, weil der Titel uebersetzt ist.
     *
     * `pointer-events: auto` (und nicht `none` wie bei der alten
     * `.issues-badge`) ist Absicht – nur so kommen Zeigerereignisse an, und
     * ohne die gibt es kein Mouseover-Panel; der Klick blubbert trotzdem an den
     * Knopf.
     *
     * ⚠ LEERER title IST ABSICHT und keine Vergesslichkeit (dieselbe Stelle wie
     * beim Issues-Badge): der Knopf darunter traegt `title` aus
     * `data-i18n-title="nav.settings"`. Ohne das leere Attribut sucht der
     * Browser beim Hovern der Badge beim Vorfahren weiter und zeigt SEINEN
     * nativen Tooltip ZUSAETZLICH zum Panel – zwei Kaesten uebereinander. Die
     * Aufschluesselung nach Quellen steht statt dessen im `aria-label`; ein
     * `title` an der Badge waere ausserdem beim naechsten `applyLang()` weg,
     * wenn er am Knopf haenge. */
    function badgeMalen() {
        // Tiefenverteidigung: ohne belegten Administrator-Status wird nichts
        // gemalt. Das Backend fuellt `admin_badge` ohnehin nur fuer Admins –
        // aber eine Badge in einen ausgeblendeten Knopf zu malen, weil ein
        // (aelteres oder manipuliertes) Antwort-Objekt das Feld mitbringt,
        // waere eine Aussage ueber die Rechteverwaltung an den Falschen.
        var n = (_admin && _badge && _badge.gesamt) || 0;
        if (!n) tipAus();
        knoepfe().forEach(function (btn) {
            var el = btn.querySelector('.jv-gear-badge');
            if (!n) {
                if (el) el.parentNode.removeChild(el);
                btn.classList.remove('jv-gear-host');
                return;
            }
            if (!el) {
                el = document.createElement('span');
                el.className = 'jv-gear-badge';
                el.setAttribute('title', '');
                // Der Klick auf die Badge soll IN den Sicherheits-Reiter fuehren.
                // Eigener Handler statt Ausnutzen des Knopf-Handlers, weil nur
                // hier bekannt ist, dass die Badge gemeint war.
                el.addEventListener('click', function (ev) {
                    // Nicht an den Knopf weiterreichen: der oeffnet mit Rechten
                    // das Menue – gemeint ist hier aber der Sicherheits-Reiter.
                    ev.stopPropagation();
                    nachSettings('');
                });
                el.addEventListener('mouseenter', function () { tipAn(el); });
                el.addEventListener('mouseleave', tipAusGleich);
                btn.appendChild(el);
            }
            btn.classList.add('jv-gear-host');
            el.textContent = n > 99 ? '99+' : String(n);
            // Eine Sperre ist dringlicher als eine offene Freigabe: ein Konto
            // kommt nicht mehr herein, bis jemand handelt.
            // Ein SSH-Alarm (Durchprobieren) wiegt wie eine Sperre, ebenso jeder
            // Alarm der Serverueberwachung (Dienst aus, Platz, Zertifikat, Ausgang).
            el.classList.toggle('is-danger', !!(_badge && (_badge.gesperrt || _badge.ssh_alarm || _badge.ue_alarm)));
            el.setAttribute('aria-label', quellenText());
        });
        // Steht das Panel gerade offen, muss es dem neuen Stand folgen \u2013 sonst
        // zeigt es nach dem 60-s-Takt eine Liste, die es nicht mehr gibt
        // (Register: eine Anzeige darf keinen Zustand behaupten, den sie nicht
        // kennt). Bei 0 ist es oben schon geschlossen.
        if (n && tipOffen()) tipZeichnen();
    }

    /* Einblenden + binden. Idempotent: mehrfaches Aufrufen (Sprachwechsel,
     * verzoegertes Nachladen) darf keinen zweiten Handler anhaengen.
     *
     * ZWEI VERSTECK-MECHANISMEN, beide muessen behandelt werden: die meisten
     * Seiten setzen `style="display:none"` am Knopf, /wissen dagegen die Klasse
     * `hidden` – und die ist dort `display: none !important`. Ein blosses
     * `style.display = ''` (oder auch `'block'`) verliert gegen `!important`:
     * der Knopf waere auf /wissen unsichtbar geblieben, ohne dass im DOM etwas
     * falsch aussieht. Deshalb IMMER beides. */
    function zeige(an) {
        knoepfe().forEach(function (b) {
            b.style.display = an ? '' : 'none';
            if (an) b.classList.remove('hidden');
            else b.classList.add('hidden');
            if (!an || b.dataset.jvsGebunden) return;
            b.dataset.jvsGebunden = '1';
            b.addEventListener('click', function () { klick(b); });
        });
        zustandMalen();
        badgeMalen();
    }

    // ── Admin-Rechte am Zahnrad ─────────────────────────────────────────────

    function aufEinstellungen() { return location.pathname === '/settings'; }

    /* Markierung und Beschriftung je Zustand. Der `title` aus
     * `data-i18n-title="nav.settings"` wird hier ueberschrieben, weil er sonst
     * "Einstellungen" behauptet, wo ein Klick erst nach dem Code fragt; nach
     * einem Sprachwechsel malt der Listener unten neu. */
    function zustandMalen() {
        var text = _admin ? T('gear.title_aktiv', 'Administration aktiv – Klick für Optionen')
                          : T('gear.title_start', 'Administration starten');
        knoepfe().forEach(function (b) {
            b.classList.toggle('jv-gear-erhoeht', !!_admin);
            b.setAttribute('title', text);
            b.setAttribute('aria-label', text);
        });
    }

    function rueckwegMerken(b) {
        var ziel = (b && b.getAttribute('data-jarvis-settings')) || location.pathname;
        if (ziel === '/settings') return;
        try { sessionStorage.setItem('jarvis_settings_return', ziel); }
        catch (e) { /* egal – /settings faellt dann aufs Portal zurueck */ }
    }

    /* Die Titelleiste (kopfzeile.js) zeichnet ihre Nur-Admin-Symbole beim
     * naechsten Seitenaufbau SOFORT aus dem gemerkten Stand – ohne diese Zeile
     * stuenden sie nach "Administration beenden" bis zur Antwort von /api/me
     * noch einmal da (bzw. fehlten nach dem Holen kurz). */
    function kopfMerken(an) {
        try { if (window.JarvisKopf && window.JarvisKopf.merke) window.JarvisKopf.merke('admin', !!an); }
        catch (e) { /* egal – /api/me belegt den Stand ohnehin */ }
    }

    function senden(pfad, daten) {
        return fetch(pfad, {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token(),
                       'Content-Type': 'application/json' },
            body: JSON.stringify(daten || {})
        }).then(function (r) {
            return r.json().catch(function () { return {}; })
                .then(function (d) { return { status: r.status, d: d || {} }; });
        });
    }

    function klick(b) {
        if (_admin) { menueAn(b); return; }
        erhoehen(b, {});
    }

    /* Erster Schritt ohne Code: der Server sagt, was er braucht. */
    function erhoehen(b, daten) {
        return senden('/api/admin/erhoehen', daten).then(function (res) {
            var d = res.d;
            if (d.ok && d.erhoeht) {
                dialogZu();
                _admin = true;
                kopfMerken(true);
                rueckwegMerken(b);
                // Auf /settings selbst genuegt Neuladen; sonst dorthin wechseln.
                if (aufEinstellungen()) location.reload();
                else location.href = '/settings';
                return true;
            }
            if (d.requires_totp_setup || d.requires_totp) {
                dialogAuf(b, d);
            } else if (_dlg) {
                // Offener Dialog (z. B. 429 nach zu vielen Versuchen): die Meldung
                // gehoert an die Eingabe, die Felder bleiben stehen.
                meldung(d.error || d.detail
                    || T('gear.fehler', 'Die Administrator-Rechte konnten nicht freigeschaltet werden.'));
            } else {
                dialogAuf(b, { error: d.error || d.detail
                    || T('gear.fehler', 'Die Administrator-Rechte konnten nicht freigeschaltet werden.') });
            }
            return false;
        }).catch(function () {
            var t = T('gear.fehler_netz', 'Der Server ist gerade nicht erreichbar.');
            if (_dlg) meldung(t); else dialogAuf(b, { error: t });
            return false;
        });
    }

    function beenden() {
        menueAus();
        return senden('/api/admin/erhoehung/beenden', {}).then(function (res) {
            if (!(res.d && res.d.ok)) return false;
            _admin = false;
            kopfMerken(false);
            if (aufEinstellungen()) {
                var ziel = '';
                try { ziel = sessionStorage.getItem('jarvis_settings_return') || ''; }
                catch (e) { ziel = ''; }
                location.href = ziel && ziel !== '/settings' ? ziel : '/portal';
            } else {
                location.reload();
            }
            return true;
        }).catch(function () { return false; });
    }

    // ── Dialog: Code bzw. Einrichtung ───────────────────────────────────────
    var _dlg = null;
    var _dlgKnopf = null;

    function dialogZu() {
        if (_dlg && _dlg.parentNode) _dlg.parentNode.removeChild(_dlg);
        _dlg = null;
        document.removeEventListener('keydown', dialogTaste, true);
        if (_dlgKnopf) { try { _dlgKnopf.focus(); } catch (e) { /* egal */ } }
    }

    function dialogTaste(ev) {
        if (ev.key === 'Escape') { ev.preventDefault(); dialogZu(); }
    }

    function feld(id, typ, beschriftung, extra) {
        var wrap = document.createElement('label');
        wrap.className = 'jv-erh-zeile';
        var sp = document.createElement('span');
        sp.className = 'jv-erh-label';
        sp.textContent = beschriftung;
        var inp = document.createElement('input');
        inp.className = 'jv-erh-feld';
        inp.id = id;
        inp.type = typ;
        Object.keys(extra || {}).forEach(function (k) { inp.setAttribute(k, extra[k]); });
        wrap.appendChild(sp);
        wrap.appendChild(inp);
        return wrap;
    }

    /* `d`: Antwort des Servers – requires_totp (Code), requires_totp_setup
     * (QR + Code + Kennwort) oder nur `error`. Ein Fehler bleibt stehen, bis
     * der naechste Versuch laeuft (Register: Fehler verschwinden nicht von selbst). */
    function dialogAuf(b, d) {
        _dlgKnopf = b || _dlgKnopf;
        var einrichten = !!d.requires_totp_setup;
        // Ein offener Dialog bleibt stehen (der QR darf bei einem falschen Code
        // nicht verschwinden) – nur die Meldung wechselt.
        if (_dlg && _dlg.getAttribute('data-modus') === (einrichten ? 'einrichten' : 'code')
                && !d.qr_code) {
            meldung(d.error || '');
            var c = _dlg.querySelector('#jv-erh-code');
            if (c) { c.value = ''; c.focus(); }
            return;
        }
        dialogZu();
        var ov = document.createElement('div');
        ov.className = 'jv-erh-overlay';
        ov.setAttribute('data-modus', einrichten ? 'einrichten' : (d.requires_totp ? 'code' : 'fehler'));
        var box = document.createElement('div');
        box.className = 'jv-erh-dlg';
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');
        box.setAttribute('aria-labelledby', 'jv-erh-h');
        var kopf = document.createElement('div');
        kopf.className = 'jv-erh-kopf';
        var h = document.createElement('h3');
        h.id = 'jv-erh-h';
        h.textContent = T('gear.dlg_titel', 'Administration starten');
        var x = document.createElement('button');
        x.type = 'button';
        x.className = 'jv-erh-x';
        var xt = T('gear.schliessen', 'Schließen');
        x.setAttribute('title', xt);
        x.setAttribute('aria-label', xt);
        x.innerHTML = (window.JarvisIcons && window.JarvisIcons.close) ? window.JarvisIcons.close() : '';
        x.addEventListener('click', dialogZu);
        kopf.appendChild(h);
        kopf.appendChild(x);
        box.appendChild(kopf);

        var text = document.createElement('p');
        text.className = 'jv-erh-text';
        box.appendChild(text);
        if (einrichten) {
            text.textContent = T('gear.setup_text', 'Für Administratoren ist die Zwei-Faktor-Anmeldung Pflicht. Scanne den Code mit deiner Authenticator-App und gib den angezeigten 6-stelligen Code sowie zur Bestätigung dein Kennwort ein.');
            if (d.qr_code) {
                var qrw = document.createElement('div');
                qrw.className = 'jv-erh-qr';
                var img = document.createElement('img');
                img.src = d.qr_code;
                img.alt = T('gear.qr_alt', 'QR-Code für die Authenticator-App');
                qrw.appendChild(img);
                box.appendChild(qrw);
                var man = document.createElement('p');
                man.className = 'jv-erh-text';
                man.textContent = T('gear.manual', 'Oder den Schlüssel von Hand eintragen:') + ' ';
                var code = document.createElement('code');
                code.className = 'jv-erh-schluessel';
                code.textContent = d.secret || '';
                man.appendChild(code);
                box.appendChild(man);
            }
        } else if (d.requires_totp) {
            text.textContent = T('gear.code_text', 'Gib den 6-stelligen Code aus deiner Authenticator-App ein, um die Administrator-Rechte für diese Sitzung freizuschalten.');
        }
        var codeFeld = null, pwFeld = null;
        if (einrichten || d.requires_totp) {
            var zc = feld('jv-erh-code', 'text', T('gear.code_label', 'Zwei-Faktor-Code'),
                { autocomplete: 'one-time-code', inputmode: 'numeric', maxlength: '6',
                  pattern: '[0-9]*' });
            box.appendChild(zc);
            codeFeld = zc.querySelector('input');
            if (einrichten) {
                var zp = feld('jv-erh-pw', 'password', T('gear.pw_label', 'Kennwort'),
                    { autocomplete: 'current-password' });
                box.appendChild(zp);
                pwFeld = zp.querySelector('input');
            }
        }
        var fehler = document.createElement('p');
        fehler.className = 'jv-erh-fehler';
        fehler.setAttribute('role', 'alert');
        box.appendChild(fehler);

        var fuss = document.createElement('div');
        fuss.className = 'jv-erh-fuss';
        var ab = document.createElement('button');
        ab.type = 'button';
        ab.className = 'jv-erh-btn';
        ab.textContent = T('gear.abbrechen', 'Abbrechen');
        ab.addEventListener('click', dialogZu);
        fuss.appendChild(ab);
        if (codeFeld) {
            var ok = document.createElement('button');
            ok.type = 'button';
            ok.className = 'jv-erh-btn jv-erh-btn-haupt';
            ok.textContent = T('gear.bestaetigen', 'Freischalten');
            var abschicken = function () {
                var c = (codeFeld.value || '').replace(/\D/g, '');
                if (c.length !== 6) {
                    meldung(T('gear.code_fehlt', 'Bitte den 6-stelligen Code eingeben.'));
                    codeFeld.focus();
                    return;
                }
                var daten = { code: c };
                if (pwFeld) {
                    if (!pwFeld.value) {
                        meldung(T('gear.pw_fehlt', 'Bitte zur Bestätigung dein Kennwort eingeben.'));
                        pwFeld.focus();
                        return;
                    }
                    daten.password = pwFeld.value;
                }
                ok.disabled = true;
                meldung('');
                erhoehen(_dlgKnopf, daten).then(function () { ok.disabled = false; });
            };
            ok.addEventListener('click', abschicken);
            [codeFeld, pwFeld].forEach(function (f) {
                if (f) f.addEventListener('keydown', function (ev) {
                    if (ev.key === 'Enter') { ev.preventDefault(); abschicken(); }
                });
            });
            // Wie an der Anmeldemaske: sechs Ziffern schicken ab – aber nur,
            // wenn kein Kennwort mehr fehlt.
            codeFeld.addEventListener('input', function () {
                var c = codeFeld.value.replace(/\D/g, '');
                if (c.length === 6 && !pwFeld && !ok.disabled) { codeFeld.value = c; abschicken(); }
            });
            fuss.appendChild(ok);
        }
        box.appendChild(fuss);
        ov.appendChild(box);
        // Kein Schliessen per Klick auf den grauen Rand (Vorgabe 2026-10-29,
        // tests/test_popup_kein_aussenklick.js) – nur ×, Abbrechen oder Escape.
        document.body.appendChild(ov);
        _dlg = ov;
        document.addEventListener('keydown', dialogTaste, true);
        // Beim ersten Oeffnen ist der Server-Text nur die Aufforderung, die der
        // Dialog schon selbst ausspricht – gezeigt wird er nur ohne Eingabefeld.
        if (!codeFeld) meldung(d.error || '');
        if (codeFeld) codeFeld.focus(); else ab.focus();
    }

    function meldung(text) {
        if (!_dlg) return;
        var f = _dlg.querySelector('.jv-erh-fehler');
        if (f) f.textContent = text || '';
    }

    // ── Menue mit Rechten: Einstellungen / Administration beenden ───────────
    var _menue = null;

    function menueAus() {
        if (_menue && _menue.parentNode) _menue.parentNode.removeChild(_menue);
        _menue = null;
        document.removeEventListener('mousedown', menueAussen, true);
        document.removeEventListener('keydown', menueTaste, true);
    }

    function menueAussen(ev) {
        if (_menue && !_menue.contains(ev.target)) menueAus();
    }

    function menueTaste(ev) {
        if (ev.key === 'Escape') { ev.preventDefault(); menueAus(); }
    }

    function menueAn(b) {
        if (_menue) { menueAus(); return; }
        tipAus();
        var m = document.createElement('div');
        m.className = 'jv-erh-menue';
        m.setAttribute('role', 'menu');
        function eintrag(text, fn, art) {
            var e = document.createElement('button');
            e.type = 'button';
            e.className = 'jv-erh-menue-zeile' + (art ? ' ' + art : '');
            e.setAttribute('role', 'menuitem');
            e.textContent = text;
            e.addEventListener('click', fn);
            m.appendChild(e);
            return e;
        }
        if (!aufEinstellungen()) {
            eintrag(T('gear.menue_einstellungen', 'Einstellungen öffnen'), function () {
                menueAus();
                rueckwegMerken(b);
                location.href = '/settings';
            });
        }
        eintrag(T('gear.menue_beenden', 'Administration beenden'), beenden, 'is-ende');
        document.body.appendChild(m);
        var a = b.getBoundingClientRect();
        var r = m.getBoundingClientRect();
        var rand = 8;
        var links = Math.max(rand, Math.min(a.right - r.width, window.innerWidth - r.width - rand));
        var oben = a.bottom + 6;
        if (oben + r.height > window.innerHeight - rand) oben = Math.max(rand, a.top - r.height - 6);
        m.style.left = links + 'px';
        m.style.top = oben + 'px';
        _menue = m;
        document.addEventListener('mousedown', menueAussen, true);
        document.addEventListener('keydown', menueTaste, true);
        var erst = m.querySelector('button');
        if (erst) erst.focus();
    }

    var _lauf = null;

    /* Holt den Administrator-Status und blendet ein. Das Ergebnis wird je
     * Seitenaufruf gemerkt: mehrere Aufrufer (Seiten-Init, Sprachwechsel) sollen
     * nicht mehrere Roundtrips ausloesen – der Grund, aus dem /settings einmal
     * neun Sekunden brauchte. */
    function pruefe() {
        // Ein ERNEUTER Aufruf blendet nochmals ein, statt nur das gemerkte
        // Ergebnis zurueckzugeben: eine Seite kann den Knopf NACH dem Laden
        // erzeugen (claude_portal.js baut bei 403 eine Absage-Seite samt Knopf).
        // Gaebe `pruefe()` dann nur das Promise zurueck, blieben solche Knoepfe
        // verborgen – und der Roundtrip wird trotzdem nur einmal gemacht.
        if (_lauf) return _lauf.then(function (an) { zeige(an); return an; });
        var t = token();
        if (!t) { zeige(false); return Promise.resolve(false); }
        _lauf = fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _admin = !!(d && d.is_admin);
                _konto = !!(d && d.admin_konto) || _admin;
                _badge = (d && d.admin_badge) || null;
                var an = _konto;
                zeige(an);
                if (an) starteTakt();
                return an;
            })
            .catch(function () {
                // Kein Zustandswechsel bei Netzfehler: der Knopf startet
                // verborgen (display:none im Markup) und bleibt es. Ein
                // eingeblendeter Knopf ohne belegten Admin-Status waere eine
                // Behauptung.
                return false;
            });
        return _lauf;
    }

    /* Haelt die Badge aktuell, solange die Seite offen ist.
     *
     * NUR fuer Administratoren und erst NACH dem belegten Admin-Status – ein
     * Takt, der bei jedem Benutzer laeuft, waere Last ohne Aussage. Der Server
     * merkt sich die Zahlen 20 s, der Takt kostet also hoechstens eine
     * Datei- und eine Socket-Abfrage je Minute.
     *
     * WARUM UEBERHAUPT EIN TAKT: eine offene Freigabe entsteht, WAEHREND der
     * Administrator auf der Seite steht (er drueckt ⤓ an einem Skill, der
     * apt braucht). Ein Stand vom Seitenaufbau zeigte sie nie – genau deshalb
     * hatte die alte Fassung in app.js denselben 60-Sekunden-Takt. */
    function aktualisiere() {
        var t = token();
        if (!t) return Promise.resolve(null);
        return fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                // 401/403/Netzfehler: den alten Stand BEHALTEN. "Keine offene
                // Freigabe" waere eine Behauptung, die der Abruf nicht deckt.
                if (!d) return null;
                _badge = d.admin_badge || null;
                // Rechte in einem ANDEREN Tab geholt oder abgegeben: die
                // Markierung folgt (die Oberflaeche der Seite erst beim Neuladen).
                _admin = !!d.is_admin;
                zustandMalen();
                badgeMalen();
                return _badge;
            })
            .catch(function () { return null; });
    }

    function starteTakt() {
        if (_pollTimer) return;
        _pollTimer = setInterval(aktualisiere, POLL_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', pruefe);
    } else {
        pruefe();
    }

    // Der Badge-Tooltip ist uebersetzt, steht aber nicht im Markup –
    // `applyLang()` erreicht ihn nicht. Neu malen, NICHT neu abrufen.
    window.addEventListener('jarvis-lang-changed', function () {
        if (_konto) zustandMalen();
        badgeMalen();
    });

    window.JarvisSettingsBtn = { pruefe: pruefe, zeige: zeige,
                                 aktualisiere: aktualisiere, beenden: beenden };
})();
