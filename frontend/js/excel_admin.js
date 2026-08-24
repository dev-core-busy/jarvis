/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → Excel: Add-in verteilen und Grenzen pflegen.

   Der Reiter hat zwei Aufgaben, und die erste ist die wichtigere:

   1. **Das Manifest zum Verteilen bereitstellen.** Anders als beim
      Outlook-Add-in gibt es keinen Exchange-Katalog, der die Datei ausrollt –
      Add-ins fuer Arbeitsmappen verteilt ein Exchange nicht. Der Administrator
      legt sie in einen Netzwerkordner, den die Arbeitsplaetze als
      vertrauenswuerdigen Katalog eintragen. Ohne diesen Knopf muesste er die
      URL kennen; das ist genau die Art verstecktes Wissen, die eine Funktion
      unbenutzbar macht.

   2. Die beiden Grenzwerte des Skills pflegen.

   WARUM DER DOWNLOAD EIN <a> IST UND KEIN fetch: der Endpunkt liefert
   `Content-Disposition: attachment` samt Branding-Dateinamen. Ein Umweg ueber
   fetch + Blob muesste den Dateinamen selbst bilden – und liefe damit dem
   Branding hinterher. Im Hochlade-Modus (unten) wird deshalb der Dateiname AUS
   DEM ANTWORTKOPF gelesen, nicht nachgebaut.

   DER KNOPF LAEDT HERUNTER – EINEN ZWEITEN ZUSTAND GIBT ES NICHT
   (Umbau 2026-08-24, nach mehreren Meldungen). Er ist ein <a href> und wird
   NICHT abgefangen: so entscheidet der Browser ueber das Ziel, und der
   Administrator kann die Datei auch auf den Desktop legen. Jeder abgefangene
   Klick nahm ihm diese Wahl.

   ⚠ WARUM DER EINGETRAGENE PFAD NICHT BENUTZT WERDEN KANN. Das ist keine
   Bequemlichkeit dieses Moduls, sondern eine Grenze JEDES Browsers: es gibt
   keine API, die in einen als TEXT genannten Ordner schreibt.
   `showDirectoryPicker`/`showSaveFilePicker` liefern ein Handle aus einem
   Dialog, `startIn` nimmt nur ein Handle oder einen festen Namen
   (documents/downloads/…), `suggestedName` keine Pfadtrenner. Eine Seite, die
   in `\\server\freigabe\…` schreiben duerfte, weil dort jemand den Pfad
   hingetippt hat, waere genau die Luecke, die diese Grenze verhindert.

   FRUEHERE ANLAEUFE, damit sie niemand wieder einbaut:
   * Zwei-Zustands-Knopf ("Manifest hochladen") mit Ordner-Dialog und
     gemerktem Handle in IndexedDB. Der Dialog kam nach jedem Browser-Neustart
     wieder (Chrome setzt das Schreibrecht auf "fragen" zurueck) – und er hat
     den eingetragenen Pfad nie benutzt, sondern nur den gewaehlten Ordner.
   * Eine fertige `curl.exe`-Zeile daneben. Sie hat den Pfad woertlich
     benutzt, war aber ausdruecklich nicht gewuenscht.
   Beides ist entfernt. Der eingetragene Pfad ist eine ANGABE fuer Menschen:
   der Hinweis unter dem Knopf nennt ihn, damit man weiss, wohin die
   heruntergeladene Datei gehoert, und `/excel` zeigt ihn den Benutzern
   anstelle des Download-Knopfes.

   MASSGEBLICH IST DER FELDINHALT, nicht der gespeicherte Wert: wer den Pfad
   eintippt, sieht ihn sofort im Hinweis – ohne erst speichern zu muessen.

   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var SKILL = 'excel-addin';
    var _gebunden = false;
    var _laeuft = false;
    // Der GESPEICHERTE Katalogpfad (nicht der Feldinhalt) – er entscheidet ueber
    // die Betriebsart des Knopfes.
    var _katalog = '';
    // Der Server hat den Abruf abgelehnt (localhost-Basis). Dann darf auch der
    // Ordner-Weg nichts tun: er legte eine Datei in die Freigabe, die auf jedem
    // Arbeitsplatz ins Leere zeigt.
    var _adresseKaputt = false;
    // Der Dateiname aus dem Antwortkopf (folgt dem Branding). Wird beim
    // Adress-Test mitgelesen – er kostet dort nichts. Er steht im Hinweis,
    // damit der Administrator die Datei im Download-Ordner wiederfindet;
    // nachgebaut liefe er dem Branding hinterher (genau der Fehler, den
    // `dateinameAus` vermeidet).
    var _dateiname = '';

    function $(id) { return document.getElementById(id); }
    /* Der Ordnername kommt aus dem Dateisystem und geht per innerHTML in den
       Hinweis – ein Ordner "a<img src=x onerror=…>" ist anlegbar. */
    function esc(t) {
        return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function token() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }

    /* Die Manifest-Version kommt vom Server. Sie steht auch im Manifest selbst,
       aber ein Administrator soll sie sehen, OHNE die Datei zu oeffnen – sonst
       ist "habe ich die aktuelle verteilt?" nicht beantwortbar. */
    function ladeVersion() {
        fetch('/api/excel-addin/version', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.version) {
                    melde('xa-version', 'Manifest-Fassung ' + d.version);
                }
            }).catch(function () { });
    }

    /* Ein Manifest, das ueber "localhost" abgerufen wurde, zeigt auf jedem
       Arbeitsplatz ins Leere – Excel installiert es klaglos, das Fenster bleibt
       danach leer. Der Server weist den Abruf deshalb ab (HTTP 400); hier wird
       der Grund SICHTBAR gemacht, statt den Administrator eine kaputte Datei
       verteilen zu lassen. */
    function pruefeAdresse() {
        var warn = $('xa-warn');
        var dl = $('xa-download');
        if (!warn) return;
        fetch('/excel-addin/manifest.xml', { method: 'GET', cache: 'no-store' })
            .then(function (r) {
                if (r.ok) {
                    _adresseKaputt = false;
                    _dateiname = dateinameAus(r);
                    knopfAktualisieren();     // Hinweis mit echtem Dateinamen
                    // ZERTIFIKAT: das Manifest ist gueltig, aber die Adresse
                    // darin passt vielleicht nicht zum Serverzertifikat. Dann
                    // meldet Office nur "vertraut dem Add-in nicht" – ein
                    // Fehler, der erst am Arbeitsplatz auffaellt. Der Server
                    // legt den Grund in den Antwortkopf; hier wird er als
                    // WARNUNG gezeigt, nicht als Sperre: bei TLS-Terminierung
                    // im Rueckwaertsproxy ist das lokale Zertifikat nicht
                    // massgeblich, und ein gesperrter Download waere dort falsch.
                    var zw = r.headers.get('X-Jarvis-Cert-Warn');
                    if (zw) {
                        warn.textContent = '⚠ ' + zw;
                        warn.style.color = 'var(--warning, #d98a00)';
                        warn.style.display = '';
                    } else {
                        warn.style.display = 'none';
                    }
                    return;
                }
                return r.json().catch(function () { return {}; }).then(function (d) {
                    _adresseKaputt = true;
                    warn.textContent = '⚠ ' + (d.error ||
                        'Das Manifest kann über diese Adresse nicht erzeugt werden.');
                    warn.style.color = 'var(--danger)';
                    warn.style.display = '';
                    if (dl) { dl.style.opacity = '.5'; dl.style.pointerEvents = 'none'; }
                    var ub = $('xa-upload');
                    if (ub) ub.disabled = true;
                });
            }).catch(function () { });
    }

    /* ── Der gemerkte Katalog-Ordner ────────────────────────────────────────
       Ein FileSystemDirectoryHandle ist strukturiert klonbar und laesst sich
       deshalb in IndexedDB ablegen – localStorage kann es NICHT (dort landet nur
       "[object FileSystemDirectoryHandle]"). Genau diese Persistenz ist der
       Unterschied zwischen "jedes Mal den Ordner suchen" und "einmal waehlen".
       Ein eigener kleiner Store, damit nichts mit anderen Modulen kollidiert. */
    var _DB = 'jarvis-fs', _STORE = 'handles', _KEY = 'excel-katalog';
    var _ordner = null;          // FileSystemDirectoryHandle oder null

    function db() {
        return new Promise(function (res, rej) {
            if (!window.indexedDB) { rej(new Error('IndexedDB fehlt')); return; }
            var a = indexedDB.open(_DB, 1);
            a.onupgradeneeded = function () {
                if (!a.result.objectStoreNames.contains(_STORE)) a.result.createObjectStore(_STORE);
            };
            a.onsuccess = function () { res(a.result); };
            a.onerror = function () { rej(a.error || new Error('IndexedDB')); };
        });
    }

    function handleLesen() {
        return db().then(function (d) {
            return new Promise(function (res) {
                var r = d.transaction(_STORE, 'readonly').objectStore(_STORE).get(_KEY);
                r.onsuccess = function () { res(r.result || null); };
                r.onerror = function () { res(null); };
            });
        }).catch(function () { return null; });
    }

    function handleSchreiben(h) {
        return db().then(function (d) {
            return new Promise(function (res, rej) {
                var t = d.transaction(_STORE, 'readwrite');
                t.objectStore(_STORE).put(h, _KEY);
                t.oncomplete = function () { res(true); };
                t.onerror = function () { rej(t.error); };
            });
        });
    }

    /* Berechtigung fuer das gemerkte Handle. Sie faellt nach einem
       Browser-Neustart regelmaessig auf "prompt" zurueck – das ist KEIN Fehler
       und darf nicht als solcher gemeldet werden. `fragen=false` prueft nur
       (fuer die Anzeige), `true` fragt nach (braucht eine Nutzergeste, liegt
       beim Klick vor). */
    function darfSchreiben(h, fragen) {
        if (!h || !h.queryPermission) return Promise.resolve(false);
        return h.queryPermission({ mode: 'readwrite' }).then(function (z) {
            if (z === 'granted') return true;
            if (!fragen || !h.requestPermission) return false;
            return h.requestPermission({ mode: 'readwrite' })
                    .then(function (z2) { return z2 === 'granted'; });
        }).catch(function () { return false; });
    }

    /* Den Zielordner besorgen – gemerkter zuerst, sonst EINMAL fragen.
       MUSS synchron in der Klick-Geste aufgerufen werden: `showDirectoryPicker`
       verlangt eine frische Benutzergeste, und die laeuft in Chrome nach
       wenigen Sekunden ab. Deshalb steht dieser Aufruf VOR dem Netz-Abruf des
       Manifests – anders als beim Speichern-Dialog droht hier keine 0-Byte-
       Datei, weil das Auswaehlen eines VERZEICHNISSES nichts anlegt. */
    function ordnerBesorgen() {
        if (_ordner) return Promise.resolve(_ordner);
        if (typeof window.showDirectoryPicker !== 'function') return Promise.resolve(null);
        return window.showDirectoryPicker({ id: 'jarvis-excel-katalog', mode: 'readwrite',
                                            startIn: 'documents' })
            .then(function (h) {
                return darfSchreiben(h, true).then(function (ok) {
                    if (!ok) throw new Error('Schreibrecht für den Ordner wurde nicht erteilt.');
                    _ordner = h;
                    // Das Merken darf den Vorgang nicht aufhalten und auch nicht
                    // kippen: schlaegt IndexedDB fehl (privates Fenster), wird
                    // beim naechsten Mal eben noch einmal gefragt.
                    handleSchreiben(h).catch(function () { });
                    knopfAktualisieren();
                    return h;
                });
            });
    }

    /* Kann dieser Browser in einen frei gewaehlten Ordner schreiben?
       Die File System Access API gibt es in Chrome und Edge, NICHT in Firefox
       und Safari – und nur im sicheren Kontext. Ohne sie bleibt es beim
       Download; das ist kein Fehler, sondern der Normalfall dieser Browser, und
       der Hinweistext sagt es. */
    function kannSpeichern() {
        return typeof window.showSaveFilePicker === 'function';
    }

    /* Der Pfad, der GERADE gilt: was im Feld steht, sonst der gespeicherte.
       Der Feldinhalt hat Vorrang – wer den Pfad eintippt und sofort auf den
       Knopf drueckt, meint diesen Pfad. Dass der Knopf frueher am GESPEICHERTEN
       Wert hing, war der gemeldete Fehler. */
    function feldPfad() {
        var f = $('xa-katalog');
        var v = (f ? f.value : '').trim();
        return v || _katalog;
    }

    /* Der Ordner-Weg als ZWEITER Knopf – er erscheint nur, wo er wirklich geht
       (Chrome/Edge) UND nur mit eingetragenem Pfad. Ein Knopf, der in Firefox
       nichts tut, ist schlimmer als keiner; und einer, der ohne Zielpfad
       dasteht, hat kein Ziel. */
    function ordnerKnopf(pfad) {
        var ub = $('xa-upload');
        if (!ub) return;
        var geht = !!pfad && kannSpeichern();
        ub.style.display = geht ? '' : 'none';
        if (geht) {
            ub.textContent = _ordner
                ? 'In Ordner „' + (_ordner.name || '?') + '" schreiben'
                : 'Ordner wählen und hineinschreiben';
        }
    }

    /* Der Hinweis unter dem Knopf. Der Knopf selbst hat nur EINEN Zustand:
       er laedt herunter. Er kann NICHT in den eingetragenen Netzwerkpfad
       schreiben – kein Browser darf in einen Ordner schreiben, der ihm als
       Text genannt wurde, und die einzige API dafuer nimmt ausschliesslich ein
       Handle aus einem Ordner-Dialog. Deshalb steht hier der Weg im Klartext:
       herunterladen, dann von Hand in die Freigabe legen. */
    function knopfAktualisieren() {
        var hint = $('xa-dl-hint');
        if (!hint) return;
        var pfad = feldPfad();
        // Der Ordner-Knopf wird VOR dem fruehen Ausstieg gesetzt. Stand er
        // dahinter, blieb er beim LEEREN des Feldes sichtbar – der Zweig war
        // dann unerreichbar, und der Kommentar unten versprach das Gegenteil
        // ("nur mit eingetragenem Pfad"). Ein Test hat genau das gemeldet.
        ordnerKnopf(pfad);
        if (!pfad) { hint.style.display = 'none'; return; }
        // Der Pfad wird ANGEZEIGT, damit man ihn beim Verschieben vor Augen
        // hat – er ist Fremdeingabe, also per textContent in ein eigenes
        // Element und nicht in die Zeichenkette hinein.
        hint.innerHTML = 'Der Browser darf das Manifest <b>nicht</b> selbst in die ' +
            'Netzwerkfreigabe schreiben – in einen Ordner, der ihm nur als Text genannt ' +
            'wurde, darf keine Webseite schreiben. Laden Sie die Datei also herunter ' +
            '(wohin, entscheidet Ihr Browser – Download-Ordner, Desktop, „Speichern ' +
            'unter") und <b>verschieben Sie sie anschließend selbst</b> nach ' +
            '<code class="xa-pfad"></code>. Sie heißt <code class="xa-datei"></code>.';
        var c = hint.querySelector('.xa-pfad');
        if (c) c.textContent = pfad;
        var f = hint.querySelector('.xa-datei');
        // Der Name kommt aus dem Antwortkopf. Ist der Adress-Test noch nicht
        // durch, wird er NICHT geraten – dann steht dort die neutrale Endung.
        if (f) f.textContent = _dateiname || 'manifest.xml';

        hint.style.color = '';
        hint.style.display = '';
    }

    /* Dateiname aus dem Antwortkopf statt nachgebaut – so folgt er dem Branding
       ohne zweite Fassung derselben Regel im Frontend. Der Rueckfall greift nur,
       wenn der Kopf fehlt. */
    function dateinameAus(antwort) {
        var cd = '';
        try { cd = antwort.headers.get('content-disposition') || ''; } catch (e) { }
        var m = /filename\*=utf-8''([^;]+)/i.exec(cd);
        if (m) { try { return decodeURIComponent(m[1].trim()); } catch (e) { } }
        m = /filename="([^"]+)"/i.exec(cd) || /filename=([^;]+)/i.exec(cd);
        if (m) return m[1].trim();
        return 'jarvis-excel-addin.xml';
    }

    /* ERST holen, DANN den Dialog oeffnen – nicht umgekehrt.
       Der Picker legt die Zieldatei bereits beim Auswaehlen an; scheiterte
       danach der Abruf, laege eine 0-Byte-Datei im Katalog und Excel meldete den
       Arbeitsplaetzen ein ungueltiges Manifest. Der Preis: die Benutzergeste
       kann theoretisch ablaufen (Chrome: ~5 s). Das Manifest wird lokal erzeugt
       und ist in Millisekunden da; tritt es doch ein, sagt die Meldung
       ausdruecklich, dass ein erneuter Klick genuegt. */
    function hochladen() {
        if (_adresseKaputt) return;

        // 1. Den eingetragenen Pfad MITSPEICHERN – ohne zweiten Knopf.
        //    Bewusst OHNE `await`: der naechste Schritt braucht die frische
        //    Benutzergeste, und ein Netz-Roundtrip davor kann sie aufbrauchen.
        var pfad = feldPfad();
        if (pfad && pfad !== _katalog) speicherePfad(pfad, true);

        // 2. Zielordner besorgen – SYNCHRON in der Geste (siehe ordnerBesorgen).
        var ordnerP = ordnerBesorgen();

        melde('xa-dl-status', 'Manifest wird geholt …');
        var name = 'jarvis-excel-addin.xml';
        ordnerP.then(function () {
            return fetch('/excel-addin/manifest.xml', { cache: 'no-store' });
        })
            .then(function (r) {
                if (!r.ok) {
                    return r.json().catch(function () { return {}; }).then(function (d) {
                        throw new Error(d.error || 'HTTP ' + r.status);
                    });
                }
                name = dateinameAus(r);
                return r.blob();
            })
            .then(function (blob) {
                melde('xa-dl-status', '');
                // STUFE 1+2: gemerkter Ordner. `fragen=true` ist wichtig – nach
                // einem Browser-Neustart steht die Berechtigung auf "prompt",
                // und das ist der Normalfall, kein Fehler.
                if (_ordner) {
                    return darfSchreiben(_ordner, true).then(function (ok) {
                        if (!ok) return schreibDialog(blob, name);
                        return _ordner.getFileHandle(name, { create: true })
                            .then(function (fh) {
                                return fh.createWritable().then(function (w) {
                                    return w.write(blob).then(function () { return w.close(); });
                                });
                            })
                            .then(function () { return (_ordner.name || '?') + '/' + name; });
                    });
                }
                return schreibDialog(blob, name);
            })
            .then(function (geschrieben) {
                // Die FOLGE benennen, nicht nur "gespeichert": ob die Datei im
                // richtigen Ordner gelandet ist, sieht man von hier aus nicht –
                // der Browser gibt den Pfad nicht heraus.
                melde('xa-dl-status', '✓ ' + geschrieben + ' geschrieben – im Katalog-Ordner ' +
                      'sehen die Arbeitsplätze sie beim nächsten Excel-Start.', 'ok');
                setTimeout(function () { melde('xa-dl-status', ''); }, 12000);
            })
            .catch(function (e) {
                // Abbrechen im Dialog ist KEIN Fehler – eine rote Meldung darauf
                // wuerde eine bewusste Entscheidung als Stoerung ausgeben.
                if (e && (e.name === 'AbortError' || e.code === 20)) {
                    melde('xa-dl-status', '');
                    return;
                }
                var txt = (e && e.message) || String(e);
                if (e && e.name === 'SecurityError') {
                    txt = 'Der Speichern-Dialog ließ sich nicht öffnen. Bitte den Knopf ' +
                          'noch einmal drücken.';
                }
                melde('xa-dl-status', 'Fehler: ' + txt, 'fehler');
            });
    }

    /* STUFE 3: Speichern-unter-Fenster. `id` laesst Chrome sich das Verzeichnis
       ueber Sitzungen hinweg merken, `startIn` setzt es auf das gemerkte Handle,
       falls eines da ist (aber die Berechtigung fehlt). Beides kostet nichts und
       erspart im Wiederholungsfall die Sucherei. */
    function schreibDialog(blob, name) {
        var opt = {
            id: 'jarvis-excel-katalog',
            suggestedName: name,
            types: [{ description: 'Office-Add-in-Manifest',
                      accept: { 'application/xml': ['.xml'] } }]
        };
        if (_ordner) opt.startIn = _ordner;
        return window.showSaveFilePicker(opt).then(function (handle) {
            return handle.createWritable().then(function (w) {
                return w.write(blob).then(function () { return w.close(); });
            }).then(function () { return handle.name || name; });
        });
    }

    function ladeGrenzen() {
        return fetch('/api/skills/' + SKILL + '/config', { headers: kopf() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // Der Endpunkt antwortet VERSCHACHTELT ({config: {...}}). Genau
                // das wurde am 2026-08-12 beim E-Mail-Reiter uebersehen: eine
                // Ebene zu hoch gegriffen, alle Felder undefined – und das
                // naechste Speichern schrieb die Leere fest.
                var c = (d && d.config) || {};
                var r1 = $('xa-l-runden'); if (r1) r1.value = c.max_runden || 3;
                var r2 = $('xa-l-aenderungen'); if (r2) r2.value = c.max_aenderungen || 200;
                var k = $('xa-katalog');
                // `|| ''` waere hier richtig, `|| vorgabe` nicht: ein leerer
                // Pfad ist die AUSSAGE "wir verteilen nicht zentral".
                _katalog = String(c.katalog_pfad || '').trim();
                if (k) k.value = _katalog;
                knopfAktualisieren();
            }).catch(function () { });
    }

    /* Eigener Knopf, eigene Teilmenge. `update_skill_config` merged – ein Knopf,
       der den ganzen Formularstand schickt, ueberschriebe den jeweils anderen
       Teil (Lehre von den SAP-Sichtbarkeiten und den beiden E-Mail-Knoepfen). */
    function speichereKatalog() {
        var feld = $('xa-katalog');
        speicherePfad((feld ? feld.value : '').trim(), false);
    }

    /* `still = true`: aufgerufen aus dem Hochlade-Knopf, der den Pfad nebenbei
       mitspeichert. Dann KEINE eigene Statusmeldung – der Knopf meldet ohnehin,
       und zwei Meldungen nebeneinander widersprechen sich beim Timing. Ein
       Fehlschlag wird trotzdem gezeigt: ein still verlorener Pfad waere genau
       die Art Fehler, die man erst Wochen spaeter bemerkt. */
    function speicherePfad(pfad, still) {
        if (_laeuft) return;
        _laeuft = true;
        if (!still) melde('xa-katalog-status', 'Speichert …');
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ katalog_pfad: pfad })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            // Erst JETZT gilt der Pfad – und mit ihm die Betriebsart des Knopfes
            // darueber. Ohne diesen Aufruf bewuerbe er weiter einen Download,
            // waehrend /excel den Benutzern schon die Freigabe nennt.
            _katalog = pfad;
            knopfAktualisieren();
            // Die Folge benennen, nicht nur "gespeichert": der Knopf schaltet
            // die Benutzerseite zwischen Download und Pfad um, und das sieht
            // man von hier aus nicht.
            if (!still) {
                melde('xa-katalog-status', pfad
                    ? 'Gespeichert – /excel zeigt jetzt diesen Pfad statt des Downloads.'
                    : 'Gespeichert – /excel bietet wieder den Download an.', 'ok');
                setTimeout(function () { melde('xa-katalog-status', ''); }, 5000);
            }
        }).catch(function (e) {
            melde('xa-katalog-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function speichere() {
        if (_laeuft) return;
        _laeuft = true;
        melde('xa-save-status', 'Speichert …');
        var runden = parseInt(($('xa-l-runden') || {}).value, 10);
        var aend = parseInt(($('xa-l-aenderungen') || {}).value, 10);
        if (!(runden >= 1 && runden <= 5)) runden = 3;
        if (!(aend >= 10 && aend <= 500)) aend = 200;
        // NUR die eigenen Felder senden. `update_skill_config` merged – ein
        // Knopf, der den ganzen Formularstand schickt, ueberschriebe fremde
        // Teile der Konfiguration (Lehre von den SAP-Sichtbarkeiten).
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ max_runden: runden, max_aenderungen: aend })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            melde('xa-save-status', 'Gespeichert.', 'ok');
            setTimeout(function () { melde('xa-save-status', ''); }, 3000);
        }).catch(function (e) {
            melde('xa-save-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function binde() {
        if (_gebunden) return;
        _gebunden = true;
        // Klapp-Container verdrahten. MUSS hier passieren: das Markup traegt nur
        // die Klassen, gebunden wird ueber _collapseInit in app.js – das merkt
        // sich zusaetzlich den Auf-/Zu-Zustand je Container.
        if (window.initExcelCollapse) window.initExcelCollapse();
        var b = $('xa-save');
        if (b) b.addEventListener('click', speichere);
        var kb = $('xa-katalog-save');
        if (kb) kb.addEventListener('click', speichereKatalog);
        // KEIN Handler am Download-Knopf. Er ist ein <a href> und bleibt es:
        // so entscheidet der BROWSER ueber das Ziel (Downloads-Ordner oder
        // "Speichern unter", je nach dessen Einstellung) – der Administrator
        // kann die Datei also auch auf den Desktop legen. Der frueher hier
        // haengende Handler hat ihm genau diese Wahl genommen.
        //
        // Der Ordner-Weg hat seinen EIGENEN Knopf. Zwei Aufgaben an einem Knopf
        // waren der Fehler: welche davon er gerade erfuellt, hing an einem Feld
        // weiter unten, und niemand konnte es dem Knopf ansehen.
        var ub = $('xa-upload');
        if (ub) ub.addEventListener('click', hochladen);
        // Der Hinweis unter dem Knopf nennt den eingetragenen Pfad und wandert
        // beim Tippen mit – ohne das muesste man erst speichern, um zu sehen,
        // wohin die Datei gehoert.
        var kf = $('xa-katalog');
        if (kf) kf.addEventListener('input', knopfAktualisieren);
        var g = $('xa-guide-btn');
        if (g) {
            g.addEventListener('click', function () {
                var box = $('xa-guide');
                if (!box) return;
                var auf = box.style.display !== 'none';
                box.style.display = auf ? 'none' : '';
                g.setAttribute('aria-expanded', auf ? 'false' : 'true');
                // Ein Umschalter mit unveraenderlicher Beschriftung sieht beim
                // Zuklappen wie ein wirkungsloser Klick aus (Lehre vom
                // Broker-Audit-Knopf).
                g.textContent = auf ? 'Anleitung für den Arbeitsplatz anzeigen'
                                    : 'Anleitung ausblenden';
            });
        }
    }

    window.ExcelAdmin = {
        onShow: function () {
            binde();
            ladeVersion();
            // Das gemerkte Handle VOR knopfAktualisieren laden, sonst behauptet
            // der Hinweis, es werde noch nach dem Ordner gefragt, obwohl schon
            // einer gemerkt ist. ladeGrenzen() ruft knopfAktualisieren am Ende –
            // hier wird es nach dem Laden noch einmal angestossen, weil beide
            // Abrufe nebenlaeufig sind und die Reihenfolge nicht feststeht.
            // Das gemerkte Handle VOR knopfAktualisieren laden, sonst
            // beschriftet sich der Ordner-Knopf mit "Ordner waehlen", obwohl
            // schon einer gemerkt ist. ladeGrenzen() ruft es am Ende noch
            // einmal – beide Abrufe sind nebenlaeufig.
            knopfAktualisieren();
            handleLesen().then(function (h) {
                _ordner = h || null;
                knopfAktualisieren();
            });
            ladeGrenzen();
            pruefeAdresse();
        }
    };
})();
