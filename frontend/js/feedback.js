/**
 * Feedback-Bereich (/feedback): Formular ausfuellen und absenden.
 *
 * Die Seite ist eine LEERE HUELLE – eine Navigation traegt keinen
 * Authorization-Header, die Berechtigung kann also nicht in der Route geprueft
 * werden. Hier wird /api/me geholt und wer nicht darf, landet auf dem Portal;
 * die DATEN liegen ausschliesslich hinter require_feedback_access.
 *
 * ⚠ DIE SPALTEN KOMMEN VOM SERVER, die Zeilen legt der Benutzer an. Ein
 * Zellwert wird NIE ins Markup interpoliert (`.value =`), sondern gesetzt:
 * ein Anfuehrungszeichen im Text sprengt sonst das Attribut (Register).
 */
(function () {
    'use strict';

    var _formulare = [];
    var _aktiv = null;      // das gewaehlte Formular
    var _zeilen = [];       // [{spalten_id: wert}] – der Arbeitsstand
    var _sendet = false;

    // ⚠ DRIFT-SCHRANKE: beide Werte stehen ebenso in `backend/feedback.py`
    // (`TYP_FEST`, `ZEILEN_ID`). Laufen sie auseinander, rendert die Seite die
    // feste Spalte als Eingabefeld bzw. der Server ordnet keine Zeile mehr zu –
    // beides ohne Fehlermeldung. Ein Waechter vergleicht sie.
    var TYP_FEST = 'fest';
    var ZEILEN_ID = '_zid';

    /** Die vom Administrator vorgegebenen Zeilen des gewaehlten Formulars.
     *  Leer = der Benutzer legt seine Zeilen selbst an (Bestandsverhalten). */
    function festeZeilen() {
        var z = _aktiv && _aktiv.zeilen;
        return Array.isArray(z) ? z : [];
    }

    function tok() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
    }

    function $(id) { return document.getElementById(id); }

    function hole(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + tok();
        return fetch(pfad, o);
    }

    /** Fehlertext aus einer Serverantwort. Jarvis benutzt `error`, FastAPI
     *  `detail` – nur eines zu lesen laesst eine vorhandene Begruendung
     *  verschwinden (Register). */
    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    function t(key, fallback) {
        return (window.t ? window.t(key, fallback) : fallback) || fallback;
    }

    function melde(text, art) {
        var el = $('fb-status');
        if (!el) { return; }
        el.textContent = text || '';
        // Farbe UND Text: die Farbe allein ist keine Information (Projektregel).
        el.className = 'fb-status' + (art === 'ok' ? ' is-ok' : art === 'err' ? ' is-err' : '');
    }

    // ── Aufklappbare Container (Bauform aus /ai-mouse und /email) ───────────
    // Gespeichert werden die ZUGEKLAPPTEN: so ist die Vorgabe fuer einen neuen
    // Benutzer „alles offen", und ein spaeter ergaenzter Container ist
    // automatisch offen statt still versteckt.
    var KLAPP_SPEICHER = 'jarvis_feedback_zu';

    function klappZustand() {
        try {
            var roh = JSON.parse(localStorage.getItem(KLAPP_SPEICHER) || '[]');
            return Array.isArray(roh) ? roh.filter(function (x) { return typeof x === 'string'; }) : [];
        } catch (e) {
            // Ein kaputter Speicherstand darf nicht dazu fuehren, dass gar
            // nichts mehr aufklappt.
            return [];
        }
    }

    function klappInit() {
        var zu = klappZustand();
        document.querySelectorAll('.ja-card[data-klapp]').forEach(function (karte) {
            var kopf = karte.querySelector('.ja-card-head');
            if (!kopf) { return; }
            var id = karte.getAttribute('data-klapp');
            var istZu = zu.indexOf(id) >= 0;
            karte.classList.toggle('is-zu', istZu);
            kopf.setAttribute('aria-expanded', istZu ? 'false' : 'true');
            function um() {
                var neuZu = !karte.classList.contains('is-zu');
                karte.classList.toggle('is-zu', neuZu);
                kopf.setAttribute('aria-expanded', neuZu ? 'false' : 'true');
                var liste = klappZustand().filter(function (x) { return x !== id; });
                if (neuZu) { liste.push(id); }
                try { localStorage.setItem(KLAPP_SPEICHER, JSON.stringify(liste)); }
                catch (e) { /* privater Modus: der Zustand gilt nur fuer diese Seite */ }
            }
            kopf.addEventListener('click', function (ev) {
                // ⚠ OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile den
                // Container zu (Projektregel).
                if (ev.target.closest('button, input, label, a, select, textarea')) { return; }
                um();
            });
            kopf.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                    ev.preventDefault();
                    um();
                }
            });
        });
    }

    // ── Sterne ─────────────────────────────────────────────────────────────
    //
    // ⚠ EINE RADIOGRUPPE, KEINE FUENF KNOEPFE OHNE ZUSAMMENHANG. Fuer eine
    // Hilfstechnik ist „3 von 5" die Aussage – fuenf einzelne Knoepfe waeren
    // fuenf unverbundene Bedienelemente. Der Wert steht zusaetzlich als ZAHL
    // daneben: ohne sie muesste man zaehlen.
    function sterneBauen(wert, beschriftung, beiAenderung) {
        var box = document.createElement('div');
        box.className = 'fb-sterne';
        box.setAttribute('role', 'radiogroup');
        box.setAttribute('aria-label', beschriftung);

        var anzeige = document.createElement('span');
        anzeige.className = 'fb-sterne-wert';

        function zeichnen(n) {
            for (var i = 1; i <= 5; i++) {
                var b = box.children[i - 1];
                if (!b) { continue; }
                var an = i <= n;
                b.classList.toggle('is-an', an);
                b.setAttribute('aria-checked', an ? 'true' : 'false');
                // ⚠ Der Knopf bleibt fokussierbar, auch wenn er nicht gewaehlt
                // ist: eine Radiogruppe wird mit den Pfeiltasten bedient.
                b.innerHTML = window.JarvisIcons.star(an);
            }
            anzeige.textContent = n ? (n + '/5') : '–';
            box.setAttribute('data-wert', String(n));
        }

        for (var i = 1; i <= 5; i++) {
            (function (stufe) {
                var b = document.createElement('button');
                b.type = 'button';
                b.className = 'fb-stern';
                b.setAttribute('role', 'radio');
                b.setAttribute('data-stufe', String(stufe));
                b.title = t('feedback.star_set', '{n} von 5').replace('{n}', stufe);
                b.setAttribute('aria-label', b.title);
                b.addEventListener('click', function () {
                    // Ein Klick auf den bereits gesetzten Stern nimmt die
                    // Bewertung ZURUECK. Ohne diesen Weg gaebe es keinen: ein
                    // versehentlicher Klick waere nicht mehr korrigierbar, und
                    // ein eigener „keine"-Knopf waere ein Bedienelement mehr.
                    var alt = parseInt(box.getAttribute('data-wert') || '0', 10);
                    var neu = (alt === stufe) ? 0 : stufe;
                    zeichnen(neu);
                    if (beiAenderung) { beiAenderung(neu); }
                });
                b.addEventListener('keydown', function (ev) {
                    var alt = parseInt(box.getAttribute('data-wert') || '0', 10);
                    var neu = null;
                    if (ev.key === 'ArrowRight' || ev.key === 'ArrowUp') { neu = Math.min(5, alt + 1); }
                    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowDown') { neu = Math.max(0, alt - 1); }
                    if (neu === null) { return; }
                    ev.preventDefault();
                    zeichnen(neu);
                    if (beiAenderung) { beiAenderung(neu); }
                    // Der Fokus wandert MIT – sonst geht der naechste
                    // Tastendruck ins Leere, weil der Knopf unter dem Fokus
                    // nicht mehr der gewaehlte ist (Register: Ziehgriff).
                    var ziel = box.children[Math.max(1, neu) - 1];
                    if (ziel) { ziel.focus(); }
                });
                box.appendChild(b);
            })(i);
        }
        zeichnen(wert || 0);

        var huelle = document.createElement('span');
        huelle.style.display = 'inline-flex';
        huelle.style.alignItems = 'center';
        huelle.appendChild(box);
        huelle.appendChild(anzeige);
        return huelle;
    }

    // ── Tabelle ────────────────────────────────────────────────────────────

    function leereZeile() {
        var z = {};
        ((_aktiv && _aktiv.spalten) || []).forEach(function (s) {
            z[s.id] = (s.typ === 'sterne') ? 0 : '';
        });
        return z;
    }

    /** Den Arbeitsstand fuer das gewaehlte Formular aufbauen.
     *
     *  Bei FESTEN Zeilen entsteht je Vorgabe genau eine Zeile, in der
     *  Reihenfolge der Definition. Der feste Text wird mitgenommen – aber nur
     *  ZUR ANZEIGE: `senden()` schickt ihn nicht mit, er kommt serverseitig
     *  wieder aus der Definition (siehe dort).
     */
    function zeilenAufbauen() {
        var fest = festeZeilen();
        if (!fest.length) { return [leereZeile()]; }
        var spalten = (_aktiv && _aktiv.spalten) || [];
        return fest.map(function (fz) {
            var z = leereZeile();
            z[ZEILEN_ID] = fz.id;
            spalten.forEach(function (s) {
                if (s.typ === TYP_FEST) {
                    z[s.id] = (fz.werte || {})[s.id] || '';
                }
            });
            return z;
        });
    }

    function tabelleZeichnen() {
        var box = $('fb-tabelle');
        if (!box) { return; }
        box.innerHTML = '';
        if (!_aktiv) {
            var p = document.createElement('p');
            p.className = 'fb-leer';
            p.textContent = t('feedback.none',
                'Zurzeit ist kein Formular freigeschaltet. Ein Administrator legt sie unter Einstellungen → Feedback an.');
            box.appendChild(p);
            return;
        }
        var spalten = _aktiv.spalten || [];
        // Bei festen Zeilen gibt es nichts zu entfernen und nichts anzulegen –
        // die Struktur gehoert dem Administrator (Vorgabe des Betreibers).
        var fest = festeZeilen().length > 0;

        var wrap = document.createElement('div');
        wrap.className = 'fb-tab-wrap';
        var tab = document.createElement('table');
        tab.className = 'fb-tab' + (fest ? ' is-fest' : '');

        var thead = document.createElement('thead');
        var kopf = document.createElement('tr');
        var thNr = document.createElement('th');
        thNr.className = 'fb-c-nr';
        thNr.textContent = '#';
        kopf.appendChild(thNr);
        spalten.forEach(function (s) {
            var th = document.createElement('th');
            th.textContent = s.name;          // textContent: Fremdtext
            kopf.appendChild(th);
        });
        if (!fest) {
            var thAkt = document.createElement('th');
            thAkt.className = 'fb-c-akt';
            // Leere Ueberschrift ueber der Knopfspalte: ein Wort waere Rauschen,
            // die Bedeutung traegt der Knopf selbst ueber title/aria-label.
            thAkt.setAttribute('aria-label', t('feedback.row_del', 'Zeile entfernen'));
            kopf.appendChild(thAkt);
        }
        thead.appendChild(kopf);
        tab.appendChild(thead);

        var tbody = document.createElement('tbody');
        _zeilen.forEach(function (zeile, idx) {
            var tr = document.createElement('tr');
            var tdNr = document.createElement('td');
            tdNr.className = 'fb-c-nr';
            tdNr.textContent = String(idx + 1);
            tr.appendChild(tdNr);

            spalten.forEach(function (s) {
                var td = document.createElement('td');
                if (s.typ === TYP_FEST) {
                    // Nur zu lesen. textContent, weil der Text vom Server kommt;
                    // und KEIN `disabled`-Eingabefeld: das sieht aus wie ein
                    // Feld, das man fuellen koennte und das gerade klemmt.
                    td.className = 'fb-c-fest';
                    td.textContent = zeile[s.id] == null ? '' : String(zeile[s.id]);
                } else if (s.typ === 'sterne') {
                    td.appendChild(sterneBauen(
                        parseInt(zeile[s.id] || 0, 10),
                        s.name + ' – ' + t('feedback.stars', 'Bewertung'),
                        function (n) { zeile[s.id] = n; }));
                } else {
                    var inp = document.createElement('input');
                    inp.type = 'text';
                    inp.maxLength = 2000;
                    inp.setAttribute('aria-label', s.name);
                    // ⚠ .value setzen, NICHT ins Markup interpolieren.
                    inp.value = zeile[s.id] == null ? '' : String(zeile[s.id]);
                    inp.addEventListener('input', function () { zeile[s.id] = inp.value; });
                    td.appendChild(inp);
                }
                tr.appendChild(td);
            });

            if (fest) {
                tbody.appendChild(tr);
                return;
            }
            var tdAkt = document.createElement('td');
            tdAkt.className = 'fb-c-akt';
            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'fb-row-del';
            del.title = t('feedback.row_del', 'Zeile entfernen');
            del.setAttribute('aria-label', del.title);
            // Muelleimer: hier wird wirklich etwas entfernt (Symbol-Semantik).
            del.innerHTML = window.JarvisIcons.trash();
            del.addEventListener('click', function () {
                _zeilen.splice(idx, 1);
                // Die letzte Zeile wird nicht entfernt, sondern GELEERT: eine
                // Tabelle ohne jede Zeile ist ein Zustand, aus dem der Benutzer
                // nur ueber „+ Zeile" herauskommt – der Knopf steht daneben,
                // aber eine leere Tabelle sieht nach einem Fehler aus.
                if (!_zeilen.length) { _zeilen.push(leereZeile()); }
                tabelleZeichnen();
            });
            tdAkt.appendChild(del);
            tr.appendChild(tdAkt);
            tbody.appendChild(tr);
        });
        tab.appendChild(tbody);
        wrap.appendChild(tab);
        box.appendChild(wrap);
    }

    function formularWaehlen(fid) {
        _aktiv = _formulare.find(function (f) { return f.id === fid; }) || _formulare[0] || null;
        _zeilen = _aktiv ? zeilenAufbauen() : [];
        var desc = $('fb-form-desc');
        if (desc) {
            desc.textContent = (_aktiv && _aktiv.beschreibung) || '';
            desc.style.display = desc.textContent ? '' : 'none';
        }
        // Die Knoepfe haengen am Formular: ohne eines gibt es nichts zu tun.
        ['fb-zeile-neu', 'fb-senden'].forEach(function (id) {
            var b = $(id);
            if (b) { b.disabled = !_aktiv; }
        });
        // ⚠ „+ Zeile" wird bei festen Zeilen VERSTECKT, nicht nur gesperrt. Die
        // Projektregel „gesperrt mit Begruendung schlaegt verborgen" gilt fuer
        // Bedienelemente mit ZUSTAND – hier gibt es keinen Zustand, in dem der
        // Knopf je etwas tut: die Struktur gehoert dem Administrator. Ein grauer
        // Knopf wuerde eine Moeglichkeit andeuten, die es nicht gibt.
        var neu = $('fb-zeile-neu');
        if (neu) { neu.classList.toggle('hidden', !!(_aktiv && festeZeilen().length)); }
        melde('');
        tabelleZeichnen();
        meineLaden();
    }

    function formulareZeichnen() {
        var pick = $('fb-pick');
        var sel = $('fb-form-sel');
        if (!sel || !pick) { return; }
        sel.innerHTML = '';
        _formulare.forEach(function (f) {
            var o = document.createElement('option');
            o.value = f.id;
            o.textContent = f.titel;        // textContent: Fremdtext
            sel.appendChild(o);
        });
        // ⚠ Die Auswahl erscheint nur bei MEHREREN Formularen: ein Pulldown mit
        // genau einem Eintrag ist ein Bedienelement ohne Wahl.
        pick.classList.toggle('hidden', _formulare.length < 2);
    }

    // ── Absenden ───────────────────────────────────────────────────────────

    function senden() {
        if (!_aktiv || _sendet) { return; }
        var fest = festeZeilen().length > 0;

        /** Hat der BENUTZER in dieser Zeile etwas eingetragen? Eine
         *  `fest`-Spalte zaehlt ausdruecklich NICHT mit – sonst waere jede
         *  feste Zeile „gefuellt", nur weil ihr Kriterium dasteht, und ein
         *  leeres Formular liesse sich absenden. */
        function gefuellt(z) {
            return (_aktiv.spalten || []).some(function (s) {
                if (s.typ === TYP_FEST) { return false; }
                var w = z[s.id];
                return (s.typ === 'sterne') ? (parseInt(w || 0, 10) > 0)
                                            : String(w || '').trim() !== '';
            });
        }

        // Vor dem Senden aufraeumen: leere Zeilen weist der Server ohnehin ab,
        // aber die Meldung „keine Zeile ausgefuellt" ist am Formular ehrlicher
        // als eine Fehlermeldung vom Server.
        if (!_zeilen.some(gefuellt)) {
            melde(t('feedback.err_empty', 'Es ist keine einzige Zeile ausgefüllt.'), 'err');
            return;
        }
        // ⚠ BEI FESTEN ZEILEN GEHEN ALLE RAUS, auch die leeren – der Server
        // braucht sie nicht (er iteriert ueber die Definition), aber die
        // Zuordnung ueber ZEILEN_ID ist damit vollstaendig und der Rumpf sagt,
        // was der Benutzer gesehen hat. Ohne feste Zeilen bleibt es beim
        // Bestand: nur gefuellte Zeilen.
        // Die `fest`-Zellen werden AUSDRUECKLICH NICHT mitgeschickt: ihr Text
        // kommt serverseitig aus der Definition, und was nicht gesendet wird,
        // kann auch nicht gefaelscht aussehen.
        var voll = (fest ? _zeilen : _zeilen.filter(gefuellt)).map(function (z) {
            var raus = {};
            if (z[ZEILEN_ID]) { raus[ZEILEN_ID] = z[ZEILEN_ID]; }
            (_aktiv.spalten || []).forEach(function (s) {
                if (s.typ !== TYP_FEST) { raus[s.id] = z[s.id]; }
            });
            return raus;
        });
        _sendet = true;
        var knopf = $('fb-senden');
        if (knopf) { knopf.disabled = true; }
        melde(t('feedback.sending', 'Wird gesendet…'));
        hole('/api/feedback/abgabe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ formular_id: _aktiv.id, zeilen: voll })
        }).then(function (r) {
            return r.json().catch(function () { return null; }).then(function (d) {
                if (!r.ok || !d || d.ok === false) {
                    throw new Error(fehlertext(d, 'HTTP ' + r.status));
                }
                return d;
            });
        }).then(function (d) {
            melde(t('feedback.sent', '✓ Gesendet – vielen Dank.') + ' '
                + t('feedback.sent_n', '{n} Zeile(n).').replace('{n}', (d.abgabe.zeilen || []).length),
                'ok');
            // Frisches, leeres Formular: die Abgabe ist raus, der alte Stand
            // stuende sonst da, als waere nichts passiert. Bei festen Zeilen
            // entsteht dabei wieder der vollstaendige Bogen.
            _zeilen = zeilenAufbauen();
            tabelleZeichnen();
            meineLaden();
        }).catch(function (e) {
            melde(e.message, 'err');
        }).then(function () {
            _sendet = false;
            if (knopf) { knopf.disabled = false; }
        });
    }

    // ── Eigene Abgaben ─────────────────────────────────────────────────────

    function meineLaden() {
        var box = $('fb-meine');
        if (!box) { return; }
        hole('/api/feedback/meine' + (_aktiv ? '?fid=' + encodeURIComponent(_aktiv.id) : ''))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok) { throw new Error('laden'); }
                meineZeichnen(d.abgaben || []);
            })
            .catch(function () {
                // ⚠ Ein Ladefehler LEERT die Liste nicht: eine leere Liste waere
                // von „du hast noch nichts abgegeben" nicht zu unterscheiden.
                box.innerHTML = '<p class="fb-leer">'
                    + t('feedback.mine_err', 'Die bisherigen Abgaben konnten nicht geladen werden.')
                    + '</p>';
            });
    }

    function meineZeichnen(liste) {
        var box = $('fb-meine');
        if (!box) { return; }
        box.innerHTML = '';
        if (!liste.length) {
            var p = document.createElement('p');
            p.className = 'fb-leer';
            p.textContent = t('feedback.mine_none', 'Du hast noch nichts abgegeben.');
            box.appendChild(p);
            return;
        }
        liste.forEach(function (a) {
            box.appendChild(abgabeZeichnen(a));
        });
    }

    /** Eine abgegebene Tabelle nur zum Lesen.
     *
     *  ⚠ DIE SPALTEN KOMMEN AUS DER ABGABE, nicht aus dem heutigen Formular.
     *  Sonst stuenden nach einer Aenderung echte Daten unter einer Ueberschrift,
     *  die zum Zeitpunkt der Abgabe gar nicht galt (deshalb speichert der
     *  Server den Spalten-Snapshot mit).
     */
    function abgabeZeichnen(a) {
        var karte = document.createElement('div');
        karte.className = 'fb-abgabe';

        var kopf = document.createElement('div');
        kopf.className = 'fb-abgabe-kopf';
        var titel = document.createElement('span');
        titel.className = 'fb-abgabe-titel';
        titel.textContent = a.formular_titel || '';
        var zeit = document.createElement('span');
        zeit.className = 'fb-abgabe-zeit';
        zeit.textContent = (a.zeit || '').replace('T', ' ');
        kopf.appendChild(titel);
        kopf.appendChild(zeit);
        karte.appendChild(kopf);

        var body = document.createElement('div');
        body.className = 'fb-abgabe-body';
        var tab = document.createElement('table');
        tab.className = 'fb-tab';
        var spalten = a.spalten || [];

        var thead = document.createElement('thead');
        var kz = document.createElement('tr');
        spalten.forEach(function (s) {
            var th = document.createElement('th');
            th.textContent = s.name;
            kz.appendChild(th);
        });
        thead.appendChild(kz);
        tab.appendChild(thead);

        var tbody = document.createElement('tbody');
        (a.zeilen || []).forEach(function (z) {
            var tr = document.createElement('tr');
            spalten.forEach(function (s) {
                var td = document.createElement('td');
                if (s.typ === 'sterne') {
                    var n = parseInt(z[s.id] || 0, 10);
                    // Nur lesen: gefuellte Sterne plus Zahl, keine Knoepfe.
                    var sp = document.createElement('span');
                    sp.className = 'fb-sterne';
                    sp.setAttribute('aria-label', n + '/5');
                    for (var i = 1; i <= 5; i++) {
                        var s1 = document.createElement('span');
                        s1.className = 'fb-stern' + (i <= n ? ' is-an' : '');
                        s1.innerHTML = window.JarvisIcons.star(i <= n);
                        sp.appendChild(s1);
                    }
                    td.appendChild(sp);
                } else {
                    // Der feste Text steht in der Abgabe selbst (Snapshot) und
                    // bekommt dieselbe Auszeichnung wie im Formular – sonst
                    // saehe die Rueckschau anders aus als das Ausgefuellte.
                    if (s.typ === TYP_FEST) { td.className = 'fb-c-fest'; }
                    td.textContent = z[s.id] == null ? '' : String(z[s.id]);
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        tab.appendChild(tbody);
        body.appendChild(tab);
        karte.appendChild(body);
        return karte;
    }

    // ── Start ──────────────────────────────────────────────────────────────

    function binden() {
        var sel = $('fb-form-sel');
        if (sel) { sel.addEventListener('change', function () { formularWaehlen(sel.value); }); }
        var neu = $('fb-zeile-neu');
        if (neu) {
            neu.addEventListener('click', function () {
                // Der Knopf ist bei festen Zeilen versteckt – die Pruefung ist
                // die zweite Schranke: `hidden` laesst sich aus den
                // Entwicklerwerkzeugen entfernen, und eine so entstandene Zeile
                // haette keine Kennung und fiele serverseitig lautlos heraus.
                if (!_aktiv || festeZeilen().length) { return; }
                _zeilen.push(leereZeile());
                tabelleZeichnen();
                // Der Fokus springt in die neue Zeile – sonst muss der Benutzer
                // nach jedem Klick erst wieder hinklicken.
                var felder = document.querySelectorAll('#fb-tabelle tbody tr:last-child input[type="text"]');
                if (felder.length) { felder[0].focus(); }
            });
        }
        var senden_ = $('fb-senden');
        if (senden_) { senden_.addEventListener('click', senden); }

        var portal = $('fb-portal-btn');
        if (portal) { portal.addEventListener('click', function () { location.href = '/portal'; }); }

        var logout = $('fb-logout-btn');
        if (logout) {
            logout.addEventListener('click', function () {
                // Das Abmelde-Signal MUSS raus, bevor das Token verworfen wird,
                // und braucht keepalive: die Seite navigiert unmittelbar danach
                // weg (Anwesenheits-Buchhaltung, Register).
                try {
                    fetch('/api/logout', {
                        method: 'POST', keepalive: true,
                        headers: { 'Authorization': 'Bearer ' + tok() }
                    });
                } catch (e) { /* Abmelden darf am Signal nicht scheitern. */ }
                try { localStorage.removeItem('jarvis_token'); } catch (e) { }
                location.replace('/');
            });
        }
    }

    function start() {
        var app = $('fb-app');
        if (!tok()) { location.replace('/'); return; }

        // ⚠ VOR dem /api/me-Abruf: die Container stehen im Markup und sollen
        // ihren gemerkten Zustand sofort haben – sonst klappen sie sichtbar zu,
        // nachdem die Seite schon dastand.
        klappInit();
        binden();

        hole('/api/me').then(function (r) {
            if (!r.ok) { throw new Error('auth'); }
            return r.json();
        }).then(function (me) {
            // Freigabe UND aktiver Skill – der Server hat beides verrechnet.
            if (!me.permissions || !me.permissions.feedback) {
                location.replace('/portal');
                return null;
            }
            if (app) { app.classList.remove('hidden'); }
            var sb = $('fb-settings-btn');
            if (sb && me.is_admin) { sb.style.display = ''; }
            return hole('/api/feedback/formulare')
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    _formulare = (d && d.formulare) || [];
                    formulareZeichnen();
                    formularWaehlen(_formulare.length ? _formulare[0].id : '');
                });
        }).catch(function () {
            location.replace('/');
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
