/* ═══════════════════════════════════════════════════════════════════
   Hinweise an das eigene Konto – heute: "Deine 2FA wurde zurueckgesetzt"

   Setzt ein Administrator die Zwei-Faktor-Anmeldung eines Kontos zurueck
   (Einstellungen -> Sicherheit), merkt der Betroffene sonst nur, dass kein
   Code mehr gefragt wird. Diese Karte sagt ihm, wer es wann getan hat, und
   fuehrt zum Neu-Einrichten (Portal, Schloss-Symbol).

   Laeuft auf jeder Webseite, die sitzung.js laedt (nicht in den Office-
   Aufgabenfenstern). Abgefragt wird EINMAL je Sitzung (sessionStorage), nicht
   bei jedem Seitenwechsel – solange ein Hinweis offen ist, aber auf jeder
   Seite, bis er quittiert oder die 2FA neu eingerichtet ist.

   Eigenes Styling (Klassen jkh-*): jede Bereichsseite laedt andere
   Stylesheets, eine Knopfklasse von dort waere anderswo ein nackter Knopf.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var MERKER = 'jarvis_konto_hinweise_geprueft';

    function token() { return (window.JarvisSitzung && window.JarvisSitzung.token()) || ''; }
    function T(key, def) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return def;
    }
    // Merker = Pruefsumme des Tokens, KEIN Teil davon (Code-Review 2026-10-07:
    // hier standen die letzten 16 Zeichen – ein Stueck der Signatur). FNV-1a
    // genuegt: es geht nur um "derselbe Token wie beim letzten Mal?".
    function merkerWert(tok) {
        var h = 0x811c9dc5;
        for (var i = 0; i < tok.length; i++) {
            h ^= tok.charCodeAt(i);
            h = Math.imul(h, 0x01000193) >>> 0;
        }
        return 'f' + h.toString(16) + '.' + tok.length;
    }
    function geprueft(tok) {
        try { return sessionStorage.getItem(MERKER) === merkerWert(tok); } catch (e) { return false; }
    }
    function merken(tok) {
        try { sessionStorage.setItem(MERKER, merkerWert(tok)); } catch (e) {}
    }

    // Farben NUR aus Theme-Variablen (Code-Review 2026-10-07: color:#fff und
    // ein fester Schatten standen hier nackt). Die Rueckfallwerte in var()
    // bleiben: support-api.html laedt theme.css nicht.
    function stil() {
        if (document.getElementById('jkh-stil')) return;
        var s = document.createElement('style');
        s.id = 'jkh-stil';
        s.textContent =
            '.jkh-karte{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:99000;' +
            'width:min(560px,calc(100vw - 32px));box-sizing:border-box;padding:14px 16px;border-radius:10px;' +
            'background:var(--bg-secondary,#111827);color:var(--text-primary,#f3f4f6);' +
            'border:1px solid var(--accent,#6366f1);box-shadow:var(--shadow-lg,0 8px 28px rgba(0,0,0,.35));' +
            'font-family:inherit;font-size:.9rem;line-height:1.5;}' +
            '.jkh-titel{font-weight:600;margin:0 0 4px;}' +
            '.jkh-text{margin:0 0 12px;color:var(--text-secondary,#cbd5e1);}' +
            '.jkh-knoepfe{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}' +
            '.jkh-btn{font:inherit;font-size:.85rem;padding:6px 14px;border-radius:7px;cursor:pointer;' +
            'border:1px solid var(--border,rgba(148,163,184,.35));background:transparent;color:var(--text-primary,#f3f4f6);}' +
            '.jkh-btn:hover{border-color:var(--accent,#6366f1);}' +
            '.jkh-btn.jkh-haupt{background:var(--accent,#6366f1);border-color:var(--accent,#6366f1);color:var(--text-on-accent,#fff);}' +
            '.jkh-btn.jkh-haupt:hover{filter:brightness(1.1);}';
        document.head.appendChild(s);
    }

    function datum(sek) {
        if (!sek) return '';
        try {
            return new Date(sek * 1000).toLocaleDateString(window._lang === 'en' ? 'en-GB' : 'de-DE',
                { day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (e) { return ''; }
    }

    function einrichten() {
        var knopf = document.getElementById('btn-totp-setup');
        if (knopf) { knopf.click(); return; }
        window.KontoHinweise._weiter('/portal?zwei_faktor=einrichten');
    }

    function zeigen(h, tok) {
        if (document.querySelector('.jkh-karte')) return;
        stil();
        var karte = document.createElement('div');
        karte.className = 'jkh-karte';
        karte.setAttribute('role', 'alertdialog');
        karte.setAttribute('data-art', h.art);
        var titel = document.createElement('p');
        titel.className = 'jkh-titel';
        titel.textContent = T('konto.totp_reset_titel', 'Zwei-Faktor-Anmeldung zurückgesetzt');
        var text = document.createElement('p');
        text.className = 'jkh-text';
        // Name und Datum als TEXT einsetzen – nie als Markup
        text.textContent = T('konto.totp_reset_text',
            'Ein Administrator ({von}) hat deine Zwei-Faktor-Anmeldung am {am} zurückgesetzt. '
            + 'Du meldest dich zurzeit nur mit Kennwort an. Richte sie neu ein, damit dein Konto wieder geschützt ist.')
            .replace('{von}', h.von || T('konto.unbekannt', 'unbekannt'))
            .replace('{am}', datum(h.am));
        var knoepfe = document.createElement('div');
        knoepfe.className = 'jkh-knoepfe';
        var spaeter = document.createElement('button');
        spaeter.type = 'button';
        spaeter.className = 'jkh-btn jkh-gelesen';
        spaeter.textContent = T('konto.verstanden', 'Verstanden');
        var los = document.createElement('button');
        los.type = 'button';
        los.className = 'jkh-btn jkh-haupt jkh-einrichten';
        los.textContent = T('konto.totp_einrichten', 'Jetzt neu einrichten');
        knoepfe.appendChild(spaeter);
        knoepfe.appendChild(los);
        karte.appendChild(titel); karte.appendChild(text); karte.appendChild(knoepfe);
        document.body.appendChild(karte);

        spaeter.addEventListener('click', function () {
            spaeter.disabled = true;
            fetch('/api/auth/hinweise/gelesen', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' },
                body: JSON.stringify({ art: h.art })
            }).then(function (r) {
                if (!r.ok) throw new Error(String(r.status));
                merken(tok);
                karte.remove();
            }).catch(function () {
                // Bleibt stehen: ein still verschwundener Hinweis kaeme beim
                // naechsten Besuch wieder, ohne dass klar waere warum.
                spaeter.disabled = false;
            });
        });
        // Einrichten quittiert NICHT: erledigt ist der Hinweis erst, wenn die 2FA
        // wirklich wieder an ist (der Server raeumt ihn dann selbst ab).
        los.addEventListener('click', function () { karte.remove(); einrichten(); });
    }

    function pruefen() {
        var tok = token();
        if (!tok || geprueft(tok)) return;
        fetch('/api/auth/hinweise', { headers: { 'Authorization': 'Bearer ' + tok } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !Array.isArray(d.hinweise)) return;   // spaeter erneut versuchen
                var h = d.hinweise.filter(function (x) { return x && x.art === 'totp_zurueckgesetzt'; })[0];
                if (!h) { merken(tok); return; }
                zeigen(h, tok);
            })
            .catch(function () {});
    }

    function start() {
        // Portal: Ziel von "Jetzt neu einrichten" auf anderen Seiten
        if (/[?&]zwei_faktor=einrichten\b/.test(location.search)) {
            try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) {}
            setTimeout(function () {
                var knopf = document.getElementById('btn-totp-setup');
                if (knopf) knopf.click();
            }, 300);
            return;   // die Karte wuerde den Dialog nur verdecken
        }
        if (token()) { pruefen(); return; }
        // Anmeldung auf DERSELBEN Seite (Login-Maske ohne Neuladen): auf das
        // Token warten – ein Lesezugriff auf den Speicher, kein Netzverkehr.
        var warten = setInterval(function () {
            if (token()) { clearInterval(warten); pruefen(); }
        }, 2000);
    }

    // _weiter ist austauschbar, damit ein Waechter die Weiterleitung messen kann
    // (jsdom navigiert nicht).
    window.KontoHinweise = { pruefen: pruefen, _weiter: function (url) { location.href = url; } };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
