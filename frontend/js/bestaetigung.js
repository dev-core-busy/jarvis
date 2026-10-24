/* Bestaetigung vor Aktionen mit Aussen- oder Loeschwirkung (BSI H9).
 *
 * Das Backend (backend/wirkung.py) haelt einen Werkzeugaufruf an und schickt
 * `bestaetigung_anfrage`; hier entsteht daraus eine Karte im Chat mit den
 * Angaben des Aufrufs und zwei Knoepfen. Der Klick geht als eigene
 * WebSocket-Nachricht `bestaetigung_antwort` zurueck – das Modell kann ihn
 * nicht erzeugen. `bestaetigung_erledigt` schliesst die Karte (Klick
 * quittiert, Frist abgelaufen, Lauf gestoppt).
 *
 * ⚠ Die Argumente stammen vom MODELL und koennen aus Fremdtext abgeleitet
 * sein (eine praeparierte Mail). Sie gehen deshalb ausschliesslich ueber
 * textContent ins DOM, nie ueber innerHTML.
 */
(function () {
    'use strict';

    function T(key, ersatz) {
        var v = (typeof window.t === 'function') ? window.t(key) : key;
        if (!v || v === key) v = ersatz || key;
        var marke = 'Jarvis';
        try { if (window.jarvisMarke) marke = window.jarvisMarke() || marke; }
        catch (e) { /* Rueckfall bleibt */ }
        return String(v).split('{marke}').join(marke);
    }

    var KLASSEN = ['aussen', 'loeschen', 'shell', 'zeitplan'];

    // Entprellung des Tippvorschlags. Jede Abfrage ist eine Anmeldung am
    // Exchange bzw. eine Verzeichnis-Abfrage, trifft also fremde Infrastruktur
    // – ohne Entprellung waere das eine Abfrage je Tastendruck. Das Backend
    // bremst zusaetzlich (backend/adressbuch.drossel_ok), aber eine Bremse
    // dort ist der Notnagel, nicht der Regelweg.
    var TIPP_MS = 320;
    // Dieselbe Untergrenze wie im Backend (adressbuch.MIN_FRAGE): unter zwei
    // Zeichen wird gar nicht gefragt.
    var MIN_FRAGE = 2;

    // Kennung -> Karte. Eine Karte, deren Anfrage erledigt ist, bleibt im
    // Verlauf stehen (man soll nachlesen koennen, was freigegeben wurde),
    // reagiert aber nicht mehr.
    var _karten = new Map();

    function _el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function _werkzeugText(name) {
        // Wirkung statt Technik: bekannte Werkzeuge mit Klartext, sonst der Name.
        var key = 'bestaetigung.wz.' + name;
        var v = (typeof window.t === 'function') ? window.t(key) : key;
        return (v && v !== key) ? v : String(name || '');
    }

    /**
     * Ein Feld, das der Mensch korrigieren darf: Eingabe + Adressbuch-Knopf +
     * Vorschlag beim Tippen.
     *
     * ⚠ Der VORSCHLAG DES MODELLS bleibt sichtbar (Zeile "Vorschlag: …") – die
     * Zusage von BSI H9 ist "was du siehst, laeuft", und nach einer Korrektur
     * muss nachlesbar bleiben, was das Modell wollte und was der Mensch daraus
     * gemacht hat.
     *
     * Alle Werte aus dem Verzeichnis gehen ueber textContent ins DOM – sie sind
     * Daten, keine Auszeichnung (gleiche Regel wie fuer die Argumente oben).
     *
     * ``beiAenderung(weg)`` bekommt den WEG: 'adressbuch' (ein Treffer wurde
     * angeklickt) oder 'getippt'. Das braucht die Karte, um die
     * Herkunfts-Zeile nachzuziehen – ohne den Weg koennte sie nur "irgendetwas
     * hat sich geaendert" sagen und muesste die Warnung stehenlassen.
     */
    function _feld(name, vorgabe, beiAenderung) {
        var box = _el('div', 'jv-best-feldbox');
        var zeile = _el('div', 'jv-best-feldzeile');
        var inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'jv-best-feld';
        inp.value = String(vorgabe == null ? '' : vorgabe);
        inp.setAttribute('aria-label',
                         T('bestaetigung.feld.' + name, name));
        zeile.appendChild(inp);

        var knopf = _el('button', 'jv-best-ab');
        knopf.type = 'button';
        // Lupe: "untersuchen, veraendert nichts" – genau das tut die Suche.
        // Bewusst ein BESTEHENDES Symbol aus icons.js: ein neues haette fuenf
        // Pruefstaende gebrochen, die JarvisIcons von Hand nachstellen.
        try {
            if (window.JarvisIcons && window.JarvisIcons.lupe) {
                knopf.innerHTML = window.JarvisIcons.lupe();
            } else {
                knopf.textContent = '…';
            }
        } catch (e) {
            knopf.textContent = '…';
        }
        knopf.title = T('bestaetigung.adressbuch', 'Im Adressbuch suchen');
        knopf.setAttribute('aria-label', knopf.title);
        zeile.appendChild(knopf);
        box.appendChild(zeile);

        var liste = _el('div', 'jv-best-vorschlaege');
        liste.setAttribute('role', 'listbox');
        box.appendChild(liste);
        var meldung = _el('div', 'jv-best-feldmeldung');
        meldung.setAttribute('role', 'status');
        box.appendChild(meldung);

        var timer = null;
        var laufend = 0;

        function leeren() {
            while (liste.firstChild) liste.removeChild(liste.firstChild);
        }

        function zeigen(treffer, hinweis) {
            leeren();
            (treffer || []).forEach(function (t) {
                var b = _el('button', 'jv-best-vorschlag');
                b.type = 'button';
                b.setAttribute('role', 'option');
                // Name und Adresse in eigenen Elementen, damit die Adresse
                // auch bei einem langen Namen lesbar bleibt.
                b.appendChild(_el('span', 'jv-best-v-name', String(t.name || '')));
                b.appendChild(_el('span', 'jv-best-v-adr', String(t.adresse || '')));
                if (t.art && t.art !== 'person') {
                    b.appendChild(_el('span', 'jv-best-v-art',
                                      T('bestaetigung.art.' + t.art, String(t.art))));
                }
                b.addEventListener('click', function () {
                    inp.value = String(t.adresse || '');
                    leeren();
                    meldung.textContent = '';
                    inp.focus();
                    if (typeof beiAenderung === 'function') beiAenderung('adressbuch');
                });
                liste.appendChild(b);
            });
            meldung.textContent = hinweis || '';
        }

        function suchen(frage) {
            var q = String(frage || '').trim();
            if (q.length < MIN_FRAGE) { leeren(); meldung.textContent = ''; return; }
            // Steht schon eine vollstaendige Adresse da, ist nichts zu loesen.
            if (q.indexOf('@') >= 0) { leeren(); meldung.textContent = ''; return; }
            var meine = ++laufend;
            meldung.textContent = T('bestaetigung.ab_suche', 'Suche …');
            var kopf = { 'Content-Type': 'application/json' };
            try {
                var tok = window.JarvisSitzung && window.JarvisSitzung.token();
                if (tok) kopf['Authorization'] = 'Bearer ' + tok;
            } catch (e) { /* ohne Token antwortet der Server mit 401 */ }
            fetch('/api/email/adressbuch', {
                method: 'POST', headers: kopf, body: JSON.stringify({ q: q })
            }).then(function (r) {
                return r.json().then(function (d) { return { ok: r.ok, d: d }; });
            }).then(function (res) {
                // Eine ueberholte Antwort darf eine neuere nicht ueberschreiben
                // (der Benutzer tippt weiter, waehrend die Anfrage laeuft).
                if (meine !== laufend) return;
                if (!res.ok || !res.d || res.d.ok === false) {
                    leeren();
                    // ⚠ Ein Fehler verschwindet NICHT von selbst – man muss ihn
                    // lesen und notfalls kopieren koennen (Register).
                    meldung.textContent = String((res.d && res.d.error)
                        || T('bestaetigung.ab_fehler',
                             'Adressbuch nicht erreichbar'));
                    return;
                }
                var tr = res.d.treffer || [];
                if (!tr.length) {
                    leeren();
                    meldung.textContent = T('bestaetigung.ab_leer',
                        'Kein Eintrag gefunden – Adresse von Hand eintragen.');
                    return;
                }
                zeigen(tr, res.d.hinweis || '');
            }).catch(function (e) {
                if (meine !== laufend) return;
                leeren();
                meldung.textContent = String(
                    T('bestaetigung.ab_fehler', 'Adressbuch nicht erreichbar')
                    + ' (' + (e && e.message ? e.message : e) + ')');
            });
        }

        inp.addEventListener('input', function () {
            if (timer) clearTimeout(timer);
            var wert = inp.value;
            timer = setTimeout(function () { suchen(wert); }, TIPP_MS);
            if (typeof beiAenderung === 'function') beiAenderung('getippt');
        });
        knopf.addEventListener('click', function () {
            if (timer) clearTimeout(timer);
            // Am Knopf wird OHNE die @-Schranke gesucht: wer ihn drueckt, will
            // nachsehen, auch wenn schon etwas Adressartiges im Feld steht.
            var q = String(inp.value || '').trim();
            if (q.length < MIN_FRAGE) {
                meldung.textContent = T('bestaetigung.ab_kurz',
                    'Mindestens 2 Zeichen eingeben.');
                return;
            }
            suchen(q.indexOf('@') >= 0 ? q.split('@')[0] : q);
        });

        // Ein Tippvorschlag gleich beim Erscheinen der Karte, WENN der Wert
        // offensichtlich keine Adresse ist: genau der gemeldete Fall ("an
        // Andreas Bender"). Steht eine Adresse da, passiert nichts.
        if (String(vorgabe || '').indexOf('@') < 0
                && String(vorgabe || '').trim().length >= MIN_FRAGE) {
            suchen(vorgabe);
        }

        return {
            box: box, eingabe: inp,
            /** Den Kasten durch den endgueltigen Wert ersetzen (nach dem Klick). */
            festschreiben: function () {
                if (timer) clearTimeout(timer);
                laufend++;                      // laufende Antwort verwerfen
                var fest = _el('div', 'jv-best-feldfest', inp.value);
                if (box.parentNode) box.parentNode.replaceChild(fest, box);
            }
        };
    }

    function _abschliessen(karte, grund) {
        if (!karte || karte.dataset.zustand === 'erledigt') return;
        karte.dataset.zustand = 'erledigt';
        karte.classList.add('is-erledigt');
        karte.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
        var st = karte.querySelector('.jv-best-status');
        // Der Server hat das letzte Wort: nach einem Klick bestaetigt er ihn
        // nur, kam aber Frist oder Stop dazwischen, gilt das – sonst stuende
        // "Freigegeben" an einer Aktion, die nie lief.
        if (st) {
            st.textContent = T('bestaetigung.status.' + grund,
                               T('bestaetigung.status.abgebrochen', 'Abgebrochen'));
        }
        karte.dataset.grund = grund || '';
    }

    /**
     * Karte fuer eine Anfrage anlegen.
     * @param {object} msg        die Server-Nachricht `bestaetigung_anfrage`
     * @param {object} umgebung   { container: Element, senden: fn(obj), scroll: fn() }
     * @returns {Element|null}    die Zeile, die eingefuegt wurde
     */
    function anfrage(msg, umgebung) {
        if (!msg || !msg.id || !umgebung || !umgebung.container) return null;
        if (_karten.has(msg.id)) return null;   // doppelt zugestellt
        var klasse = KLASSEN.indexOf(msg.klasse) >= 0 ? msg.klasse : 'aussen';

        var row = _el('div', 'msg-row bot jv-best-row');
        // Bewusst KEIN data-agent-id: die Karte muss sichtbar sein, auch wenn
        // gerade ein anderer Agent-Reiter offen ist – sonst wartet der Lauf
        // bis zur Frist auf einen Knopf, den niemand sieht.
        var karte = _el('div', 'jv-best is-' + klasse);
        karte.dataset.bestId = msg.id;
        karte.dataset.zustand = 'offen';
        karte.setAttribute('role', 'group');

        var titel = _el('div', 'jv-best-titel',
                        T('bestaetigung.titel', 'Bestätigung erforderlich'));
        karte.appendChild(titel);
        karte.setAttribute('aria-label', titel.textContent);
        karte.appendChild(_el('div', 'jv-best-klasse',
                              T('bestaetigung.klasse.' + klasse, klasse)));
        karte.appendChild(_el('div', 'jv-best-aktion', _werkzeugText(msg.werkzeug)));

        // Welche Felder der Server zum Korrigieren freigibt (Weissliste
        // `wirkung.AENDERBAR`). ⚠ Die Liste ist eine ANZEIGE-Erlaubnis, keine
        // Schranke: der Server prueft jedes Feld beim Klick erneut. Ein hier
        // erfundener Feldname wird dort verworfen und benannt.
        var aenderbar = Array.isArray(msg.aenderbar) ? msg.aenderbar : [];
        // Woher der Wert kommt: 'aufgeloest' (ueber das Adressbuch gesucht),
        // 'uebernommen' (aus Gedaechtnis/Verlauf) oder 'unbekannt'. Eine
        // uebernommene Adresse ist der gemeldete Fehlerfall – sie wird
        // AUFFAELLIG gezeigt, nicht als Fussnote.
        var herkunft = (msg.herkunft && typeof msg.herkunft === 'object')
            ? msg.herkunft : {};
        // Felder, die die Maske gefuellt haben MUSS. Ohne sie waere
        // "Ausfuehren" eine Freigabe fuer einen Versand, den der Mail-Client
        // danach abweist – der Benutzer haette geklickt und nichts erreicht.
        var pflicht = Array.isArray(msg.pflicht) ? msg.pflicht : [];
        var felder = {};        // feldname -> { box, eingabe, festschreiben }
        var urwerte = {};       // feldname -> was das Modell vorschlug
        var hzeilen = {};       // feldname -> die Herkunfts-Zeile (falls es eine gibt)

        /* ⚠ DIE HERKUNFT GILT FUER DEN VORSCHLAG DES MODELLS, NICHT FUER DAS
         * FELD (Code-Review 2026-10-24). Die Zeile wurde einmal beim Bauen der
         * Karte gesetzt und danach nie wieder angefasst: waehlte der Benutzer
         * einen Adressbuch-Treffer, stand die rote Warnung "wurde NICHT im
         * Adressbuch geprueft" weiter ueber einer Adresse, die er gerade
         * nachgesehen hatte. Eine Warnung, die im Regelfall erscheint, wird
         * beim dritten Mal ueberlesen – dann traegt sie den Fall nicht mehr,
         * fuer den sie gebaut ist (Register: eine Anzeige darf keinen Zustand
         * behaupten, den sie nicht kennt).
         *
         * Tippt der Benutzer den Vorschlag wieder her, gilt auch die
         * urspruengliche Herkunft wieder – deshalb wird sie nicht
         * ueberschrieben, sondern je Zustand neu gesetzt. */
        function _herkunftNachziehen(feld, weg) {
            var hz = hzeilen[feld];
            if (!hz || !felder[feld]) return;
            var jetzt = String(felder[feld].eingabe.value || '').trim();
            var ur = String(urwerte[feld] == null ? '' : urwerte[feld]).trim();
            var stufe = (jetzt === ur) ? String(herkunft[feld] || '')
                : (weg === 'adressbuch' ? 'gewaehlt' : 'getippt');
            if (!stufe) return;
            // ⚠ VOLLSTAENDIGE Rueckfalltexte, keine Schluesselnamen: der
            // Cache-Buster von `i18n.js` wird hier bewusst NICHT hochgezaehlt
            // (er steht in 19 Seiten, die gerade fremde Aenderungen tragen).
            // Ein Browser mit altem i18n im Cache kennt die neuen Schluessel
            // also noch nicht – und bekommt dann denselben Satz aus dem
            // Rueckfall statt des nackten Wortes "gewaehlt".
            var TEXTE = {
                gewaehlt: 'Von dir aus dem Adressbuch gewählt.',
                getippt: 'Von dir von Hand eingetragen.',
                aufgeloest: 'Im Adressbuch aufgelöst.',
                uebernommen: 'Diese Adresse wurde NICHT im Adressbuch geprüft '
                    + '– sie stammt aus dem Gesprächsverlauf. Bitte nachsehen, '
                    + 'bevor du freigibst.'
            };
            hz.className = 'jv-best-herkunft is-' + stufe;
            hz.textContent = T('bestaetigung.herkunft.' + stufe,
                               TEXTE[stufe] || stufe);
        }

        var args = Array.isArray(msg.argumente) ? msg.argumente : [];
        if (args.length) {
            var dl = _el('dl', 'jv-best-args');
            args.forEach(function (paar) {
                if (!Array.isArray(paar) || paar.length < 2) return;
                var feld = String(paar[0]);
                var wert = String(paar[1]);
                dl.appendChild(_el('dt', null, feld));
                if (aenderbar.indexOf(feld) >= 0) {
                    var dd = _el('dd', 'jv-best-dd-feld');
                    // Der Vorschlag des Modells bleibt lesbar – ein Feld, das
                    // ihn nur noch als Vorbelegung traegt, verwischt, wer was
                    // entschieden hat.
                    dd.appendChild(_el('div', 'jv-best-vorschlag-war',
                        T('bestaetigung.vorschlag', 'Vorschlag: {wert}')
                            .split('{wert}').join(wert)));
                    var hk = String(herkunft[feld] || '');
                    if (hk === 'uebernommen' || hk === 'aufgeloest') {
                        var hz = _el('div', 'jv-best-herkunft is-' + hk,
                            T('bestaetigung.herkunft.' + hk, hk === 'uebernommen'
                                ? 'Diese Adresse wurde NICHT im Adressbuch '
                                  + 'geprüft – bitte nachsehen.'
                                : 'Im Adressbuch aufgelöst.'));
                        hz.setAttribute('role', 'note');
                        dd.appendChild(hz);
                        hzeilen[feld] = hz;   // zum Nachziehen nach einer Korrektur
                    }
                    // Reihenfolge: `felder`/`urwerte` stehen VOR dem ersten
                    // Rueckruf – `_feld` sucht beim Erscheinen der Karte schon
                    // (der gemeldete Fall "an Andreas Bender"), und
                    // `_herkunftNachziehen` liest beide.
                    var f = _feld(feld, wert, function (weg) {
                        _pflichtPruefen();
                        _herkunftNachziehen(feld, weg);
                    });
                    felder[feld] = f;
                    urwerte[feld] = wert;
                    dd.appendChild(f.box);
                    dl.appendChild(dd);
                } else {
                    dl.appendChild(_el('dd', null, wert));
                }
            });
            karte.appendChild(dl);
        }

        // ⚠ FEHLENDE PFLICHTFELDER NACHTRAGEN. Die Schleife oben laeuft ueber
        // `argumente` – ein Empfaenger, den das Modell GAR NICHT gesetzt hat,
        // erzeugt dort keine Zeile und damit kein Eingabefeld. Genau dieser
        // Fall ist aber der gemeinte: "versende das Bild als E-Mail" ohne
        // Empfaenger soll die Versendemaske mit Adressbuch oeffnen.
        var _offeneP = pflicht.filter(function (f) { return !felder[f]; });
        if (_offeneP.length) {
            var dl2 = karte.querySelector('.jv-best-args');
            if (!dl2) {
                dl2 = _el('dl', 'jv-best-args');
                karte.appendChild(dl2);
            }
            _offeneP.forEach(function (feld) {
                dl2.appendChild(_el('dt', null, feld));
                var dd3 = _el('dd', 'jv-best-dd-feld');
                dd3.appendChild(_el('div', 'jv-best-vorschlag-war',
                    T('bestaetigung.kein_vorschlag',
                      'Das Modell hat keinen Empfänger genannt – hier wählen.')));
                // Den Weg auch hier durchreichen, obwohl es (noch) keine
                // Herkunfts-Zeile gibt: `_herkunftNachziehen` kehrt dann
                // einfach zurueck. Ein Rueckruf mit anderer Stelligkeit als
                // der daneben ist die Stelle, an der der naechste Umbau
                // auseinanderlaeuft.
                var f3 = _feld(feld, '', function (weg) {
                    _pflichtPruefen();
                    _herkunftNachziehen(feld, weg);
                });
                felder[feld] = f3;
                urwerte[feld] = '';
                dd3.appendChild(f3.box);
                dl2.appendChild(dd3);
            });
        }

        var minuten = Math.max(1, Math.round((Number(msg.frist_s) || 300) / 60));
        karte.appendChild(_el('div', 'jv-best-hinweis',
            T('bestaetigung.hinweis', 'Nichts geschieht ohne deinen Klick.')
                .split('{min}').join(String(minuten))));

        // ⚠ Reihenfolge: `ja` entsteht erst unten, deshalb haelt die Pruefung
        // sich an `felder`/`pflicht` und wird nach dem Bau der Knoepfe EINMAL
        // gerufen. Ein `_pflichtPruefen` vor der Knopf-Erzeugung waere ein
        // Zugriff auf undefined.
        var _pflichtHinweis = null;

        function _pflichtFehlt() {
            for (var i = 0; i < pflicht.length; i++) {
                var f = felder[pflicht[i]];
                if (f && !String(f.eingabe.value || '').trim()) return pflicht[i];
            }
            return '';
        }

        function _pflichtPruefen() {
            var fehlt = _pflichtFehlt();
            if (!ja) return;
            if (karte.dataset.zustand !== 'offen') return;
            ja.disabled = !!fehlt;
            if (_pflichtHinweis) {
                _pflichtHinweis.textContent = fehlt
                    ? T('bestaetigung.pflicht_fehlt',
                        'Empfänger fehlt – aus dem Adressbuch wählen oder '
                        + 'eintragen, dann freigeben.')
                    : '';
            }
        }

        var knoepfe = _el('div', 'jv-best-knoepfe');
        var ja = _el('button', 'jv-best-btn jv-best-ja',
                     T('bestaetigung.ausfuehren', 'Ausführen'));
        ja.type = 'button';
        var nein = _el('button', 'jv-best-btn jv-best-nein',
                       T('bestaetigung.ablehnen', 'Ablehnen'));
        nein.type = 'button';
        knoepfe.appendChild(ja);
        knoepfe.appendChild(nein);
        karte.appendChild(knoepfe);

        _pflichtHinweis = _el('div', 'jv-best-pflicht');
        _pflichtHinweis.setAttribute('role', 'status');
        karte.appendChild(_pflichtHinweis);

        var status = _el('div', 'jv-best-status');
        status.setAttribute('role', 'status');
        karte.appendChild(status);

        // Jetzt stehen Knoepfe und Felder: Sperre setzen, falls etwas fehlt.
        _pflichtPruefen();

        function klick(erlaubt) {
            // Genau EINE Antwort: das Sperren beider Knoepfe traegt das – ein
            // gesperrter Knopf loest keinen Klick mehr aus. Eine zusaetzliche
            // Zustandsabfrage hier war wirkungslos (Gegenprobe 2026-10-04).
            karte.dataset.zustand = 'gesendet';
            ja.disabled = true;
            nein.disabled = true;
            // Nur WIRKLICH geaenderte Felder mitschicken. Ein unveraendertes
            // Feld als "Korrektur" zu senden waere eine Zeile im Journal, die
            // nichts bewirkt hat – und das Journal ist hier der Beleg, an
            // welche Adresse die Mail ging.
            var korrekturen = {};
            var anzahl = 0;
            Object.keys(felder).forEach(function (f) {
                var neu = String(felder[f].eingabe.value || '').trim();
                if (neu !== String(urwerte[f] == null ? '' : urwerte[f]).trim()) {
                    korrekturen[f] = neu;
                    anzahl++;
                }
            });
            status.textContent = erlaubt
                ? T('bestaetigung.status.erlaubt', 'Freigegeben – wird ausgeführt')
                : T('bestaetigung.status.abgelehnt', 'Abgelehnt – nicht ausgeführt');
            var gesendet;
            try {
                var paket = { type: 'bestaetigung_antwort', id: msg.id,
                              erlaubt: erlaubt === true };
                // Bei "Ablehnen" wird nichts ausgefuehrt – dann gehoert auch
                // keine Korrektur in die Nachricht (der Server verwirft sie
                // ohnehin, aber eine Nachricht, die etwas mitschickt, das nie
                // wirkt, ist eine Falschaussage).
                if (erlaubt === true && anzahl) paket.aenderungen = korrekturen;
                gesendet = umgebung.senden(paket);
            } catch (e) {
                gesendet = false;
            }
            // ⚠ `senden` meldet ein NICHT gesendetes Paket mit `false` (Code-
            // Review 2026-10-07): chat.js' wsSend kehrte bei geschlossenem
            // WebSocket still zurueck, die Karte stand dann dauerhaft auf
            // "Freigegeben – wird ausgefuehrt", obwohl der Server nie etwas
            // bekam. Jetzt: Hinweis UND die Knoepfe wieder frei, damit nach dem
            // Wiederverbinden erneut geantwortet werden kann.
            if (gesendet === false) {
                karte.dataset.zustand = 'offen';
                ja.disabled = false;
                nein.disabled = false;
                status.textContent = T('bestaetigung.status.nicht_gesendet',
                                       'Antwort konnte nicht gesendet werden');
                _pflichtPruefen();   // Sperre gilt weiter, falls etwas fehlt
                // ⚠ Die Eingabefelder bleiben hier BEWUSST stehen: nach dem
                // Wiederverbinden wird erneut geantwortet, und ein
                // festgeschriebenes Feld haette den getippten Wert verloren.
                return;
            }
            // Die Antwort ist raus: aus den Eingabefeldern wird Text. Die Karte
            // bleibt im Verlauf stehen und soll nachlesbar zeigen, was
            // freigegeben wurde – ein weiterhin tippbares Feld wuerde eine
            // Aenderung versprechen, die nichts mehr bewirkt.
            Object.keys(felder).forEach(function (f) {
                try { felder[f].festschreiben(); } catch (e) { /* nur Anzeige */ }
            });
        }
        ja.addEventListener('click', function () { klick(true); });
        nein.addEventListener('click', function () { klick(false); });

        row.appendChild(karte);
        umgebung.container.appendChild(row);
        _karten.set(msg.id, karte);
        if (typeof umgebung.scroll === 'function') {
            try { umgebung.scroll(); } catch (e) { /* nur Komfort */ }
        }
        return row;
    }

    /** Server meldet: die Anfrage wartet nicht mehr (Klick, Frist, Stop). */
    function erledigt(msg) {
        if (!msg || !msg.id) return;
        var karte = _karten.get(msg.id);
        if (!karte) return;
        _abschliessen(karte, String(msg.grund || 'abgebrochen'));
    }

    window.JarvisBestaetigung = { anfrage: anfrage, erledigt: erledigt };
})();
