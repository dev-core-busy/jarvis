/* Anleitungs- und Downloadseite fuer die Browser-Erweiterung (/jira-addon).
 *
 * Die Seite ist eine LEERE HUELLE: die Route prueft keine Berechtigung (eine
 * Navigation traegt keinen Authorization-Header). Geprueft wird hier ueber
 * /api/me, und Unberechtigte gehen aufs Portal – die DATEN liegen ohnehin
 * hinter require_jira_assist_access.
 */
(function () {
    'use strict';

    var $ = function (id) { return document.getElementById(id); };

    function token() { return localStorage.getItem('jarvis_token') || ''; }

    function T(key, rueckfall) {
        // i18n.js ist eingebunden; faellt es aus, steht der deutsche Text da.
        try {
            if (window.t) { var s = window.t(key); if (s && s !== key) return s; }
        } catch (e) {}
        return rueckfall;
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // ── Zustand: gemessen, nicht behauptet ──────────────────────────────────
    /* Drei Zeilen mit je eigener Aussage. WICHTIG ist die dritte: passt die
     * Adresse nicht zum Serverzertifikat, bricht der Hintergrund-Aufruf der
     * Erweiterung wortlos ab – dort gibt es kein "trotzdem fortfahren" wie in
     * einem Tab. Genau dieser Fehler hat beim Outlook-Add-in Tage gekostet,
     * deshalb steht er hier VOR der Anleitung. */
    function zeile(art, text) {
        return '<li class="ja-st ja-st-' + art + '">' + esc(text) + '</li>';
    }

    function zeigeStatus(d) {
        var box = $('ja-status');
        if (!box) return;
        var out = [];

        out.push(zeile('ok', T('jaddon.st_free',
            'Dein Konto ist für den Jira-Assistenten freigeschaltet.')));

        if (d && d.jira_konfiguriert) {
            out.push(zeile('ok', T('jaddon.st_jira_ok',
                'Die Jira-Anbindung ist eingerichtet.')));
        } else {
            out.push(zeile('warn', T('jaddon.st_jira_no',
                'Die Jira-Anbindung ist nicht eingerichtet – ohne sie kann kein '
                + 'Ticket gelesen werden. Bitte die Administration ansprechen.')));
        }

        // Die Adresse, die der Benutzer in die Erweiterung eintragen soll.
        var adresse = window.location.origin;
        if (d && d.zert_deckt_adresse === false) {
            // Nicht gedeckt: das ist die haeufigste unerklaerliche Fehlerursache.
            out.push(zeile('warn', T('jaddon.st_cert_bad',
                'Achtung: diese Adresse (' + adresse + ') steht nicht im '
                + 'Serverzertifikat. Die Erweiterung wird den Server darüber '
                + 'nicht erreichen. Benutze stattdessen: '
                + ((d.zert_namen || []).join(', ') || '–'))));
        } else if (d && d.zert_deckt_adresse === true) {
            out.push(zeile('ok', T('jaddon.st_cert_ok',
                'Trage in der Erweiterung diese Adresse ein: ') + adresse));
        } else {
            // null = nicht feststellbar. Das ist NICHT dasselbe wie "passt nicht"
            // (z.B. TLS-Terminierung in einem Rueckwaertsproxy) – hier wird
            // deshalb nichts behauptet.
            out.push(zeile('info', T('jaddon.st_cert_unknown',
                'Trage in der Erweiterung die Adresse ein, unter der du Jarvis '
                + 'aufrufst (aktuell: ') + adresse + ').'));
        }
        box.innerHTML = out.join('');
    }

    // ── Herunterladen ───────────────────────────────────────────────────────
    /* Bewusst per fetch + Blob statt <a href="…?token=">: ein Query-Token
     * landet im Browser-Verlauf und in Proxy-Logs. Hier gibt es keinen Grund
     * dafuer – der Klick kann den Authorization-Header setzen. */
    function meldung(text, warn) {
        var m = $('ja-dl-msg');
        if (!m) return;
        m.textContent = text || '';
        m.hidden = !text;
        m.classList.toggle('ja-warn', !!warn);
    }

    /* ── Woher das Paket kommt: Netzfreigabe ODER Download ────────────────
     *
     * Ist unter *Einstellungen → Jira* ein Netzwerkpfad hinterlegt, steht hier
     * dieser Pfad zum Kopieren – sonst wie bisher der Download-Knopf. Die
     * Entscheidung faellt JE VARIANTE: ein Haus kann das Chrome-Paket auf die
     * Freigabe legen und Firefox weiter herunterladen lassen.
     *
     * Der Pfad ist Fremdeingabe aus einem Formular und wird ausschliesslich per
     * textContent gesetzt.
     */
    function kopieren(pfad, knopf) {
        var alt = knopf.textContent;
        var fertig = function (text) {
            knopf.textContent = text;
            setTimeout(function () { knopf.textContent = alt; }, 2000);
        };
        try {
            navigator.clipboard.writeText(pfad).then(function () {
                // Rueckmeldung ist Pflicht: in der Zwischenablage sieht man
                // nichts, ein stiller Fehlschlag waere unsichtbar.
                fertig(T('jaddon.copy_ok', 'kopiert ✓'));
            }, function () {
                meldung(T('jaddon.copy_err',
                    'Kopieren nicht möglich – markiere den Pfad und kopiere ihn '
                    + 'von Hand.'), true);
            });
        } catch (e) {
            meldung(T('jaddon.copy_err',
                'Kopieren nicht möglich – markiere den Pfad und kopiere ihn '
                + 'von Hand.'), true);
        }
    }

    function pfadZeile(titel, pfad) {
        var zeileEl = document.createElement('div');
        zeileEl.className = 'ja-pfad';

        var lab = document.createElement('div');
        lab.className = 'ja-pfad-lab';
        lab.textContent = titel;

        var wert = document.createElement('code');
        wert.className = 'ja-pfad-wert';
        wert.textContent = pfad;          // NIE innerHTML – Fremdeingabe

        var knopf = document.createElement('button');
        knopf.type = 'button';
        knopf.className = 'ja-btn';
        knopf.textContent = T('jaddon.copy', 'Pfad kopieren');
        knopf.addEventListener('click', function () { kopieren(pfad, knopf); });

        zeileEl.appendChild(lab);
        zeileEl.appendChild(wert);
        zeileEl.appendChild(knopf);
        return zeileEl;
    }

    function dlKnopf(variante, titel) {
        var b = document.createElement('button');
        b.type = 'button';
        b.id = 'ja-dl-' + variante;
        b.className = 'ja-btn' + (variante === 'chrome' ? ' ja-btn-haupt' : '');
        b.textContent = titel;
        b.addEventListener('click', function () { laden(variante, b); });
        return b;
    }

    function paketBlock(d) {
        var box = $('ja-paket');
        if (!box) return;
        var pfade = (d && d.paket_pfade) || {};
        var varianten = [
            ['chrome', T('jaddon.dl_chrome', 'Für Chrome / Edge')],
            ['firefox', T('jaddon.dl_firefox', 'Für Firefox')]
        ];
        var mitPfad = varianten.some(function (v) {
            return !!(pfade[v[0]] || '').trim();
        });
        box.innerHTML = '';
        // Nebeneinander nur, solange es zwei Knoepfe sind – ein Pfad braucht
        // die ganze Breite, sonst bricht er mitten im Servernamen um.
        box.className = 'ja-dl' + (mitPfad ? ' ja-dl-spalte' : '');
        varianten.forEach(function (v) {
            var pfad = (pfade[v[0]] || '').trim();
            box.appendChild(pfad ? pfadZeile(v[1], pfad) : dlKnopf(v[0], v[1]));
        });
        if (mitPfad) {
            var hinweis = document.createElement('p');
            hinweis.className = 'ja-hint';
            hinweis.textContent = T('jaddon.share_hint',
                'Pfad kopieren und im Windows-Explorer in die Adresszeile '
                + 'einfügen. Kommst du nicht an die Freigabe, wende dich an die '
                + 'Administration.');
            box.appendChild(hinweis);
        }
    }

    async function laden(variante, knopf) {
        var alt = knopf.textContent;
        knopf.disabled = true;
        knopf.textContent = T('jaddon.dl_running', 'wird erstellt …');
        meldung('');
        try {
            var r = await fetch('/api/jira/assist/paket?variante=' + encodeURIComponent(variante), {
                headers: { 'Authorization': 'Bearer ' + token() }
            });
            if (!r.ok) {
                var d = null;
                try { d = await r.json(); } catch (e) {}
                throw new Error((d && d.error) || ('HTTP ' + r.status));
            }
            var blob = await r.blob();
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'jarvis-jira-' + variante + '.zip';
            document.body.appendChild(a);
            a.click();
            a.remove();
            // Erst nach dem Klick freigeben, sonst ist der Blob schon weg.
            setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
            meldung(T('jaddon.dl_ok', 'Paket heruntergeladen. Weiter bei Schritt 2.'));
        } catch (e) {
            meldung(T('jaddon.dl_err', 'Download fehlgeschlagen: ') + (e.message || e), true);
        } finally {
            knopf.disabled = false;
            knopf.textContent = alt;
        }
    }

    // ── Start ───────────────────────────────────────────────────────────────
    async function start() {
        if (!token()) { window.location.replace('/'); return; }

        var me = null;
        try {
            var r = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token() } });
            me = r.ok ? await r.json() : null;
        } catch (e) { me = null; }

        // Fail-closed: fehlt die Auskunft, gilt "nicht freigegeben".
        var darf = !!(me && me.permissions && me.permissions.jira_assist);
        if (!darf) { window.location.replace('/portal'); return; }

        var app = $('ja-app');
        if (app) app.classList.remove('hidden');

        // Das Zahnrad nur fuer Administratoren – wie auf den anderen Bereichsseiten.
        if (me && me.is_admin) {
            var s = $('ja-settings-btn');
            if (s) s.style.display = '';
        }

        try {
            var h = await fetch('/api/jira/assist/health',
                                { headers: { 'Authorization': 'Bearer ' + token() } });
            var hd = h.ok ? await h.json() : null;
            zeigeStatus(hd);
            paketBlock(hd);
        } catch (e) {
            zeigeStatus(null);
            // Ohne Auskunft bleibt der Download – der funktioniert immer.
            paketBlock(null);
        }

        var p = $('ja-portal-btn');
        if (p) p.addEventListener('click', function () { window.location.href = '/portal'; });

        var lo = $('ja-logout-btn');
        if (lo) lo.addEventListener('click', async function () {
            // Das Abmelde-Signal muss RAUS, BEVOR das Token verworfen wird –
            // und mit keepalive, weil die Seite unmittelbar danach wegnavigiert.
            try {
                await fetch('/api/logout', {
                    method: 'POST', keepalive: true,
                    headers: { 'Authorization': 'Bearer ' + token() }
                });
            } catch (e) {}
            localStorage.removeItem('jarvis_token');
            window.location.href = '/';
        });

        // Zustandsblock UND Paket-Block sind gerendert, nicht uebersetzt – nach
        // einem Sprachwechsel muessen sie neu gebaut werden, sonst bleiben sie
        // deutsch (der Paket-Block traegt die Knopf- und Kopiertexte).
        window.addEventListener('jarvis-lang-changed', function () {
            fetch('/api/jira/assist/health',
                  { headers: { 'Authorization': 'Bearer ' + token() } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { zeigeStatus(d); paketBlock(d); })
                .catch(function () {});
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
