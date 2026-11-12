/**
 * Einstellungs-Reiter „AI-Maus": Werkzeug-Bereiche freischalten.
 *
 * Zwilling des Containers „Werkzeug-Bereiche freischalten" im Jira-Reiter
 * (jira.js::renderAreas/saveAreas) – bewusst dieselbe Bauart, damit ein
 * Administrator beide Stellen ohne Umdenken bedient.
 *
 * ⚠ DER KATALOG KOMMT VOM SERVER, nicht aus i18n.js. Name, Hinweis und
 * Werkzeugliste stehen dort NEBEN der Werkzeug-Definition (backend/ai_mouse.py:
 * BEREICHE), damit Text und Wirkung nicht auseinanderlaufen – dieselbe
 * Begründung wie beim SAP-Analysekatalog. `applyLang()` erreicht sie deshalb
 * nicht: bei `jarvis-lang-changed` wird neu geholt.
 *
 * ⚠ ADMIN-ENDPUNKT, nicht /api/ai-mouse/health: dessen Freigabe kennt keinen
 * Admin-Bypass, und ein Administrator ohne eigene AI-Mouse-Freigabe könnte den
 * Reiter sonst nicht befüllen (Register: dieselbe Stelle wie beim SAP-Katalog).
 */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    // window.t kennt nur EIN Argument und liefert bei fehlendem Schluessel den
    // Schluessel selbst – der Rueckfall griff so nie, die Oberflaeche zeigte
    // den rohen Schluessel (Code-Review 2026-10-07). Hausweg wie agent_roles.js.
    function t(key, fallback) {
        return (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;
    }

    function authHeaders(extra) {
        var h = extra || {};
        try { h['Authorization'] = 'Bearer ' + (window.JarvisSitzung.token()); }
        catch (e) { /* ohne Token laeuft der Abruf in 401 – das meldet der Zweig unten. */ }
        return h;
    }

    function setStatus(id, text, art) {
        var el = $(id);
        if (!el) { return; }
        el.textContent = text || '';
        // Farbe UND Text: die Farbe allein ist keine Information (Projektregel).
        el.style.color = art === 'ok' ? 'var(--success)'
            : art === 'error' ? 'var(--danger)' : 'var(--text-secondary)';
    }

    /* ── Ordner-Weg der Bereitstellung im Netz ─────────────────────────────
       Vorbild: Einstellungen → E-Mail → Outlook-Add-in Bereitstellung
       (email.js::schreibeInOrdner); die Begruendung der Grenze steht im Kopf
       von excel_admin.js.

       ⚠ DER EINGETRAGENE PFAD IST KEIN ZIEL. Es gibt keine Browser-API, die in
       einen als TEXT genannten Ordner schreibt; showDirectoryPicker liefert ein
       Handle aus einem Dialog. Der Zielordner wird deshalb EINMAL im Dialog
       gewaehlt und das Handle in IndexedDB gemerkt (localStorage kann es
       nicht – dort landet nur "[object FileSystemDirectoryHandle]").

       EIGENER Schluessel neben Outlook- und Excel-Add-in: die drei Dateien
       gehoeren in verschiedene Ordner, ein geteiltes Handle schriebe die
       Anwendung in den Add-in-Katalog. DB-Name, Version und Store muessen
       dagegen GLEICH sein wie dort – sonst scheitert `open` an einer
       Versionskollision derselben Datenbank. */
    var _FS_DB = 'jarvis-fs', _FS_STORE = 'handles', _FS_KEY = 'ai-mouse-ordner';
    var _ordner = null;            // FileSystemDirectoryHandle oder null

    function fsDb() {
        return new Promise(function (res, rej) {
            if (!window.indexedDB) { rej(new Error('IndexedDB fehlt')); return; }
            var a = indexedDB.open(_FS_DB, 1);
            a.onupgradeneeded = function () {
                if (!a.result.objectStoreNames.contains(_FS_STORE)) { a.result.createObjectStore(_FS_STORE); }
            };
            a.onsuccess = function () { res(a.result); };
            a.onerror = function () { rej(a.error || new Error('IndexedDB')); };
        });
    }

    function handleLesen() {
        return fsDb().then(function (d) {
            return new Promise(function (res) {
                var r = d.transaction(_FS_STORE, 'readonly').objectStore(_FS_STORE).get(_FS_KEY);
                r.onsuccess = function () { res(r.result || null); };
                r.onerror = function () { res(null); };
            });
        }).catch(function () { return null; });
    }

    function handleSchreiben(h) {
        return fsDb().then(function (d) {
            return new Promise(function (res, rej) {
                var tr = d.transaction(_FS_STORE, 'readwrite');
                tr.objectStore(_FS_STORE).put(h, _FS_KEY);
                tr.oncomplete = function () { res(true); };
                tr.onerror = function () { rej(tr.error); };
            });
        });
    }

    /* Schreibrecht fuer das Handle. Nach einem Browser-Neustart faellt es
       regelmaessig auf "prompt" zurueck – das ist KEIN Fehler. `fragen=true`
       braucht eine Nutzergeste. */
    function darfSchreiben(h, fragen) {
        if (!h || !h.queryPermission) { return Promise.resolve(false); }
        return h.queryPermission({ mode: 'readwrite' }).then(function (z) {
            if (z === 'granted') { return true; }
            if (!fragen || !h.requestPermission) { return false; }
            return h.requestPermission({ mode: 'readwrite' })
                .then(function (z2) { return z2 === 'granted'; });
        }).catch(function () { return false; });
    }

    /* Chrome/Edge im sicheren Kontext – Firefox und Safari haben die API nicht. */
    function kannSchreiben() {
        return typeof window.showDirectoryPicker === 'function';
    }

    /* Der Dateiname auf der Freigabe: der letzte Teil des EINGETRAGENEN Pfads,
       wenn er auf .exe endet – die Kachel zeigt den Benutzern genau diesen
       Pfad, eine Datei unter anderem Namen waere fuer sie nicht da. Sonst
       (Pfad nennt nur den Ordner) der Name, den der Server liefert.
       Es ist ein NAME, kein Ziel: getFileHandle lehnt Pfadtrenner ohnehin ab,
       und geschrieben wird nur in den im Dialog gewaehlten Ordner. */
    function zielName(pfad, vorgabe) {
        var teile = String(pfad || '').trim().split(/[\\/]/);
        var letzter = (teile[teile.length - 1] || '').trim();
        if (/\.exe$/i.test(letzter) && !/[<>:"|?*\x00-\x1f]/.test(letzter)) { return letzter; }
        return vorgabe || 'AiMouse.exe';
    }

    var Admin = {
        _bereiche: null,
        _gebunden: false,

        /** Wird aus app.js gerufen – beim Reiter-Klick UND beim Öffnen des
         *  Modals. Beide Wege sind idempotent (Register: „KI & System" ist der
         *  vorbelegte Reiter, ein Modul, das nur am Klick hängt, bleibt leer). */
        onShow: function () {
            this.bind();
            this.load();
            this.vorgabenLaden();
            this.signaturLaden();
        },

        bind: function () {
            if (this._gebunden) { return; }
            this._gebunden = true;
            var save = $('amtool-save');
            if (save) { save.addEventListener('click', this.saveAreas.bind(this)); }
            var neu = $('amvorg-neu');
            if (neu) { neu.addEventListener('click', function () { Admin.vorgabeFormular(null); }); }
            var shSave = $('amshare-save');
            if (shSave) { shSave.addEventListener('click', this.saveShare.bind(this)); }
            var shDl = $('amshare-dl');
            if (shDl) { shDl.addEventListener('click', this.holePaket.bind(this)); }
            var shUp = $('amshare-up');
            if (shUp) { shUp.addEventListener('click', this.schreibeInOrdner.bind(this)); }
            // MASSGEBLICH IST DER FELDINHALT, nicht der gespeicherte Wert: wer
            // den Pfad eintippt, sieht den Knopf sofort, wer ihn leert, verliert
            // ihn sofort (im Excel-Reiter war genau das der gemeldete Fehler).
            var shPfad = $('amshare-pfad');
            if (shPfad) { shPfad.addEventListener('input', this.ordnerKnopf.bind(this)); }
            // Ein frueher gewaehlter Ordner wird gemerkt – der Knopf nennt ihn.
            if (kannSchreiben()) {
                handleLesen().then(function (h) {
                    if (h) { _ordner = h; }
                    Admin.ordnerKnopf();
                });
            }
            var sgSave = $('amsign-save');
            if (sgSave) { sgSave.addEventListener('click', this.saveSignatur.bind(this)); }
            var sgDel = $('amsign-del');
            if (sgDel) { sgDel.addEventListener('click', this.delSignatur.bind(this)); }
            var kvDel = $('amsign-kv-del');
            if (kvDel) { kvDel.addEventListener('click', this.delKeyvault.bind(this)); }
            var wege = document.querySelectorAll('input[name="amsign-weg"]');
            for (var i = 0; i < wege.length; i++) {
                wege[i].addEventListener('change', function () { Admin.wegZeigen(Admin._wegGewaehlt()); });
            }
            window.addEventListener('jarvis-lang-changed', function () {
                // Nur nachladen, wenn der Reiter überhaupt schon einmal
                // gefüllt wurde – sonst holt ein Sprachwechsel auf einer
                // anderen Seite den Katalog ohne Anlass.
                if (Admin._bereiche) { Admin.load(); }
            });
        },

        load: function () {
            var sprache = (window.getLang && window.getLang()) || 'de';
            var self = this;
            fetch('/api/ai-mouse/admin/areas?lang=' + encodeURIComponent(sprache),
                  { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        });
                    }
                    return r.json();
                })
                .then(function (d) {
                    self._bereiche = d.bereiche || [];
                    self.renderAreas();
                    self.renderState(d);
                    self.renderVersion(d);
                    // ⚠ NUR FUELLEN, WENN DER BENUTZER NICHT GERADE TIPPT –
                    //   ein Sprachwechsel ruft `load()` erneut, und eine halb
                    //   eingegebene Adresse waere sonst weg.
                    var sp = $('amshare-pfad');
                    if (sp && document.activeElement !== sp) {
                        sp.value = d.freigabe_pfad || '';
                    }
                    // VOR jedem fruehen Ausstieg: der Knopf haengt am Feld.
                    self.ordnerKnopf();
                })
                .catch(function (e) {
                    // Ein Fehlschlag bleibt STEHEN. Ein leerer Container wäre
                    // von „es gibt keine Bereiche" nicht zu unterscheiden.
                    setStatus('amtool-status', e.message, 'error');
                });
        },

        renderAreas: function () {
            var box = $('amtool-areas');
            if (!box) { return; }
            var bs = this._bereiche || [];
            if (!bs.length) {
                box.innerHTML = '<span class="kb-hint">'
                    + esc(t('amtool.none', 'Keine Bereiche verfügbar.')) + '</span>';
                return;
            }
            // Die Werkzeugliste steht MIT da: ohne sie ist „Interne Fachsysteme"
            // eine Zusage, deren Umfang niemand prüfen kann.
            box.innerHTML = bs.map(function (b) {
                return '<label class="checkbox-group" style="align-items:flex-start;">'
                    + '<input type="checkbox" data-area="' + esc(b.id) + '"'
                    + (b.freigegeben ? ' checked' : '') + '>'
                    + '<span><b>' + esc(b.name) + '</b>'
                    + '<span class="kb-hint" style="display:block;">' + esc(b.hinweis || '') + '</span>'
                    + '<span class="kb-hint" style="display:block;opacity:.75;">'
                    + esc((b.werkzeuge || []).join(', ')) + '</span>'
                    + '</span></label>';
            }).join('');
        },

        // ── Bereitstellung im Netz (A) ──────────────────────────────────────
        /** Das Paket holen, um es auf die Freigabe zu legen.
         *
         * ⚠ ALS BLOB, NICHT ALS <a href> MIT ?token=. Ein Link braeuchte den
         * Token in der Adresse, und der stuende dann in der Adresszeile, im
         * Verlauf und in jedem Proxy-Log – dieselbe Wahl wie in der Kachel und
         * beim Paket der Jira-Erweiterung. Das Outlook-Add-in macht es anders,
         * dort ist das Manifest aber winzig und ohnehin offen.
         *
         * ⚠ DER ENDPUNKT BRAUCHT EINEN ADMIN-ZWEIG, und den hat er seit dem
         * 2026-09-22: `_user_may_use_aimouse` kennt keinen Admin-Bypass, ein
         * Administrator OHNE AI-Maus-Freigabe bekaeme hier sonst ein 403 –
         * und die Bereitstellung waere eine Einbahnstrasse.
         */
        holePaket: function () {
            var knopf = $('amshare-dl');
            var hinweis = $('amshare-dl-hint');
            if (!knopf || knopf.disabled) { return; }
            var alt = knopf.textContent;
            knopf.disabled = true;
            knopf.textContent = t('amshare.dl_running', 'Wird zusammengestellt…');
            if (hinweis) { hinweis.textContent = ''; hinweis.style.color = ''; }

            fetch('/api/ai-mouse/paket', { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; })
                            .then(function (d) {
                                throw new Error((d && (d.detail || d.error))
                                                || ('HTTP ' + r.status));
                            });
                    }
                    // Den Dateinamen aus dem Kopf nehmen – er traegt die Marke.
                    var name = 'ai-mouse.zip';
                    var m = (r.headers.get('Content-Disposition') || '')
                        .match(/filename="([^"]+)"/);
                    if (m) { name = m[1]; }
                    return r.blob().then(function (b) { return [name, b]; });
                })
                .then(function (paar) {
                    var url = URL.createObjectURL(paar[1]);
                    var a = document.createElement('a');
                    a.href = url;
                    a.download = paar[0];
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    // Erst nach dem Klick freigeben – vorher ist sie tot.
                    setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
                    if (hinweis) {
                        hinweis.textContent =
                            t('amshare.dl_ok', 'Heruntergeladen: ') + paar[0];
                    }
                })
                .catch(function (e) {
                    // ⚠ EIN FEHLSCHLAG BLEIBT STEHEN – einen Erfolg kann man
                    //   verpassen, eine Fehlerursache muss man lesen koennen.
                    if (hinweis) { hinweis.textContent = String(e.message || e); }
                })
                .finally(function () {
                    knopf.disabled = false;
                    knopf.textContent = alt;
                });
        },

        /** Ordner-Knopf zeigen/verbergen und beschriften. Nur in Chrome/Edge
         *  UND mit eingetragenem Pfad – einer ohne Zielpfad hat kein Ziel. */
        ordnerKnopf: function () {
            var ub = $('amshare-up');
            if (!ub || ub.disabled) { return; }
            var feld = $('amshare-pfad');
            var geht = !!(feld && feld.value.trim()) && kannSchreiben();
            ub.style.display = geht ? '' : 'none';
            if (geht) {
                ub.textContent = _ordner
                    ? t('amshare.up_named', 'In Ordner „{n}“ schreiben').replace('{n}', _ordner.name || '?')
                    : t('amshare.up', 'Ordner wählen und hineinschreiben');
            }
        },

        /** Zielordner besorgen – gemerkter zuerst, sonst EINMAL fragen.
         *  MUSS synchron in der Klick-Geste laufen: showDirectoryPicker
         *  verlangt eine frische Benutzergeste, und die ist nach dem
         *  66-MB-Abruf laengst verbraucht. Deshalb steht dieser Schritt VOR
         *  dem Netz-Abruf. */
        ordnerBesorgen: function () {
            var self = this;
            if (_ordner) {
                // Ein gemerkter Ordner kann nach einem Browser-Neustart wieder
                // nachfragen – auch das braucht die Geste, also hier.
                return darfSchreiben(_ordner, true).then(function (ok) {
                    if (!ok) {
                        throw new Error(t('amshare.up_noperm',
                            'Schreibrecht für den Ordner wurde nicht erteilt.'));
                    }
                    return _ordner;
                });
            }
            if (!kannSchreiben()) { return Promise.resolve(null); }
            return window.showDirectoryPicker({ id: 'jarvis-ai-mouse', mode: 'readwrite',
                                                startIn: 'documents' })
                .then(function (h) {
                    return darfSchreiben(h, true).then(function (ok) {
                        if (!ok) {
                            throw new Error(t('amshare.up_noperm',
                                'Schreibrecht für den Ordner wurde nicht erteilt.'));
                        }
                        _ordner = h;
                        // Das Merken darf den Vorgang nicht kippen: scheitert
                        // IndexedDB (privates Fenster), wird naechstes Mal
                        // eben noch einmal gefragt.
                        handleSchreiben(h).catch(function () { });
                        self.ordnerKnopf();
                        return h;
                    });
                });
        },

        /** Die Anwendung (EXE, nicht ZIP) in den gewaehlten Ordner schreiben. */
        schreibeInOrdner: function () {
            var self = this;
            var knopf = $('amshare-up');
            var hinweis = $('amshare-dl-hint');
            if (!knopf || knopf.disabled) { return; }
            var feld = $('amshare-pfad');
            var pfad = feld ? feld.value : '';
            var alt = knopf.textContent;
            knopf.disabled = true;
            if (hinweis) { hinweis.textContent = ''; hinweis.style.color = ''; }
            // ZUERST der Ordner (Benutzergeste!), dann die Anwendung holen.
            this.ordnerBesorgen().then(function (h) {
                if (!h) {
                    throw new Error(t('amshare.up_nofs',
                        'Dieser Browser kann nicht in einen Ordner schreiben – bitte herunterladen.'));
                }
                knopf.textContent = t('amshare.up_writing', 'schreibt …');
                return fetch('/api/ai-mouse/paket?form=exe', { headers: authHeaders() })
                    .then(function (r) {
                        if (!r.ok) {
                            return r.json().catch(function () { return null; })
                                .then(function (d) {
                                    throw new Error((d && (d.error || d.detail))
                                                    || ('HTTP ' + r.status));
                                });
                        }
                        var vorgabe = '';
                        var m = (r.headers.get('Content-Disposition') || '')
                            .match(/filename="([^"]+)"/);
                        if (m) { vorgabe = m[1]; }
                        return r.blob().then(function (b) { return [zielName(pfad, vorgabe), b]; });
                    })
                    .then(function (paar) {
                        return h.getFileHandle(paar[0], { create: true })
                            .then(function (fh) { return fh.createWritable(); })
                            .then(function (w) {
                                // createWritable schreibt in eine Schattendatei
                                // und tauscht erst bei close() – eine halb
                                // geschriebene EXE liegt also nie auf der
                                // Freigabe. Scheitert der Tausch (Datei gerade
                                // gestartet und gesperrt), kommt der Fehler hier.
                                return w.write(paar[1]).then(function () { return w.close(); });
                            })
                            .then(function () { return paar[0]; });
                    });
            }).then(function (name) {
                if (hinweis) {
                    hinweis.textContent = t('amshare.up_ok', '✓ „{n}“ in Ordner „{o}“ geschrieben.')
                        .replace('{n}', name).replace('{o}', (_ordner && _ordner.name) || '?');
                    hinweis.style.color = 'var(--success)';
                }
            }).catch(function (e) {
                // Ein abgebrochener Dialog ist KEIN Fehler – der Benutzer hat
                // sich entschieden. Alles andere BLEIBT stehen.
                if (e && (e.name === 'AbortError' || e.name === 'NotAllowedError')) {
                    if (hinweis) { hinweis.textContent = ''; }
                    return;
                }
                if (hinweis) {
                    hinweis.textContent = t('amshare.up_err', 'Fehler: ') + ((e && e.message) || e);
                    hinweis.style.color = 'var(--danger)';
                }
            }).then(function () {
                knopf.disabled = false;
                knopf.textContent = alt;
                self.ordnerKnopf();
            });
        },

        saveShare: function () {
            var el = $('amshare-pfad');
            if (!el) { return; }
            setStatus('amshare-status', t('amshare.saving', 'Wird gespeichert…'));
            fetch('/api/ai-mouse/admin/bereitstellung', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ pfad: el.value })
            }).then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    if (!r.ok || !d || !d.ok) {
                        throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
            }).then(function (d) {
                // Der GESPEICHERTE Stand gewinnt gegen das Formular – nur so
                // sieht der Administrator, wenn der Wert gekuerzt wurde.
                el.value = d.pfad || '';
                setStatus('amshare-status', d.pfad
                    ? t('amshare.ok', 'Gespeichert – die Kachel zeigt jetzt den Pfad.')
                    : t('amshare.ok_off', 'Gespeichert – die Kachel bietet wieder den Download an.'),
                    'ok');
            }).catch(function (e) {
                setStatus('amshare-status', e.message, 'error');
            });
        },

        // ── Code-Signatur (B) ───────────────────────────────────────────────
        signaturLaden: function () {
            var self = this;
            fetch('/api/ai-mouse/admin/signatur', { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        });
                    }
                    return r.json();
                })
                .then(function (d) { self.renderSignatur(d); })
                .catch(function (e) {
                    // ⚠ DER ZUSTAND WIRD NICHT GELEERT. Eine leere Anzeige
                    //   waere von „kein Zertifikat hinterlegt" nicht zu
                    //   unterscheiden – und wer darauf eines hochlaedt, ersetzt
                    //   womoeglich ein funktionierendes.
                    setStatus('amsign-status', e.message, 'error');
                });
        },

        /** Gewaehlter Signierweg im Formular ('pfx' | 'keyvault'). */
        _wegGewaehlt: function () {
            var kv = $('amsign-weg-kv');
            return kv && kv.checked ? 'keyvault' : 'pfx';
        },

        /** Felder und Entfernen-Knopf des gewaehlten Weges zeigen. Wirksam
         *  wird der Weg erst beim Speichern. */
        wegZeigen: function (weg) {
            var kv = weg === 'keyvault';
            var r = $(kv ? 'amsign-weg-kv' : 'amsign-weg-pfx');
            if (r) { r.checked = true; }
            var pfxBox = $('amsign-pfx-box'), kvBox = $('amsign-kv-box');
            if (pfxBox) { pfxBox.hidden = kv; }
            if (kvBox) { kvBox.hidden = !kv; }
            var del = $('amsign-del'), kvDel = $('amsign-kv-del');
            if (del) { del.hidden = kv; }
            if (kvDel) { kvDel.hidden = !kv; }
        },

        /** Der Zustand in Worten. Farbe ist hier die zweite Ebene, nicht die
         *  Aussage – dieselbe Regel wie bei den Anwesenheits-Pillen. */
        renderSignatur: function (d) {
            var box = $('amsign-state');
            var tsa = $('amsign-tsa');
            if (tsa && document.activeElement !== tsa) {
                tsa.value = d.tsa || '';
                tsa.placeholder = d.tsa_standard || 'http://timestamp.digicert.com';
            }
            // Key-Vault-Felder: alles ausser dem Secret kommt zurueck. Ein
            // gespeichertes Secret wird NIE angezeigt – der Platzhalter sagt,
            // dass ein leeres Feld es behaelt.
            var kv = d.keyvault || {};
            var felder = { 'amsign-kv-vault': kv.vault, 'amsign-kv-tenant': kv.tenant,
                           'amsign-kv-client': kv.client, 'amsign-kv-cert': kv.zertifikat,
                           'amsign-kv-auth': kv.anmeldung, 'amsign-kv-jsign': kv.jsign_quelle };
            Object.keys(felder).forEach(function (id) {
                var el = $(id);
                if (el && document.activeElement !== el) { el.value = felder[id] || ''; }
            });
            // Die Vorgaben kommen vom Server (eine Quelle) und stehen als
            // Platzhalter da – ein leeres Feld heisst „Vorgabe".
            var auth = $('amsign-kv-auth');
            if (auth && kv.anmeldung_standard) { auth.placeholder = kv.anmeldung_standard; }
            var jq = $('amsign-kv-jsign');
            if (jq && kv.jsign_quelle_standard) { jq.placeholder = kv.jsign_quelle_standard; }
            var sec = $('amsign-kv-secret');
            if (sec) {
                sec.placeholder = kv.secret_gesetzt
                    ? t('amsign.kv_secret_keep', 'gespeichert – leer lassen = unverändert')
                    : t('amsign.pw_ph', 'wird verschlüsselt gespeichert');
            }
            this._stand = d;
            this.wegZeigen(d.verfahren === 'keyvault' ? 'keyvault' : 'pfx');
            if (!box) { return; }
            var zeilen = [];
            zeilen.push(esc(d.verfahren === 'keyvault'
                ? t('amsign.st_weg_kv', 'Signiert wird über den Azure Key Vault.')
                : t('amsign.st_weg_pfx', 'Signiert wird mit der hinterlegten Zertifikatsdatei.')));

            if (!d.werkzeug_da) {
                // Ohne das Programm passiert gar nichts – das gehoert zuerst
                // gesagt, samt Weg (keine Aufforderung zur Handarbeit ohne ihn).
                zeilen.push('⚠ ' + esc(d.werkzeug_hinweis || ''));
            }
            if (!d.eingerichtet) {
                zeilen.push(esc(t('amsign.st_none',
                    'Kein Zertifikat hinterlegt – die Anwendung wird unsigniert ausgeliefert.')));
            } else {
                zeilen.push(esc(t('amsign.st_cert', 'Zertifikat: {b} (ausgestellt von {a}, gültig bis {d})')
                    .replace('{b}', d.betreff || '?')
                    .replace('{a}', d.aussteller || '?')
                    .replace('{d}', d.gueltig_bis || '?')));
                if (d.abgelaufen) {
                    zeilen.push('⚠ ' + esc(t('amsign.st_exp',
                        'Das Zertifikat ist abgelaufen – es wird nicht mehr signiert.')));
                }
            }
            // ⚠ DIE AUSSAGE UEBER DIE AUSGELIEFERTE DATEI IST DIE WICHTIGSTE:
            //   sie wird am PE-Header GEMESSEN, nicht aus der Einstellung
            //   abgeleitet. „Zertifikat hinterlegt" heisst nicht „die Datei,
            //   die der Knopf ausliefert, ist signiert".
            zeilen.push(d.exe_signiert
                ? '✓ ' + esc(t('amsign.st_signed', 'Die bereitliegende Anwendung ist signiert.'))
                : esc(t('amsign.st_unsigned', 'Die bereitliegende Anwendung ist nicht signiert.')));
            if (d.exe_signiert && d.ohne_zeitstempel) {
                zeilen.push('⚠ ' + esc(t('amsign.st_nots',
                    'Signiert OHNE Zeitstempel – die Signatur wird ungültig, sobald das Zertifikat abläuft.')));
            }
            if (d.letzter_fehler) {
                zeilen.push('⚠ ' + esc(t('amsign.st_err', 'Letzter Fehlschlag: ')) + esc(d.letzter_fehler));
            }
            box.innerHTML = zeilen.map(function (z) {
                return '<div style="margin:2px 0;">' + z + '</div>';
            }).join('');
        },

        saveSignatur: function () {
            if (this._wegGewaehlt() === 'keyvault') { return this.saveKeyvault(); }
            var datei = $('amsign-datei');
            var pw = $('amsign-pw');
            var tsa = $('amsign-tsa');
            var self = this;
            var f = datei && datei.files && datei.files[0] ? datei.files[0] : null;

            // Ohne Datei wird NUR der Zeitstempel geaendert – sonst muesste
            // ein Administrator, der die Adresse korrigiert, das ganze
            // Zertifikat erneut hochladen (und haette es womoeglich nicht zur
            // Hand).
            var fd = new FormData();
            if (f) {
                fd.append('datei', f);
                fd.append('kennwort', pw ? pw.value : '');
            }
            if (tsa) { fd.append('tsa', tsa.value); }
            // Liegt eine Zertifikatsdatei schon bereit und ist gerade der Key
            // Vault wirksam, stellt Speichern auf die Datei zurueck – ohne
            // erneuten Upload.
            if (!f && this._stand && this._stand.zertifikat && this._stand.verfahren === 'keyvault') {
                fd.append('verfahren', 'pfx');
            }

            setStatus('amsign-status', f
                ? t('amsign.saving', 'Zertifikat wird geprüft und die Anwendung signiert…')
                : t('amsign.saving_tsa', 'Wird gespeichert…'));

            // ⚠ KEIN Content-Type setzen: den multipart-Trenner bestimmt der
            //   Browser, ein selbst gesetzter Kopf macht den Rumpf unlesbar.
            fetch('/api/ai-mouse/admin/signatur', {
                method: 'POST', headers: authHeaders(), body: fd
            }).then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    if (!r.ok || !d || !d.ok) {
                        throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
            }).then(function (d) {
                self.renderSignatur(d);
                // Das Kennwort NIE stehen lassen – es gibt keinen Weg, es
                // wieder auszulesen, also hat es im Formular nichts verloren.
                if (pw) { pw.value = ''; }
                if (datei) { datei.value = ''; }
                setStatus('amsign-status',
                    d.hinweis || t('amsign.ok', 'Gespeichert.'),
                    d.hinweis ? 'error' : 'ok');
            }).catch(function (e) {
                setStatus('amsign-status', e.message, 'error');
            });
        },

        saveKeyvault: function () {
            var self = this;
            var wert = function (id) { var el = $(id); return el ? el.value.trim() : ''; };
            var tsa = $('amsign-tsa');
            var body = {
                vault: wert('amsign-kv-vault'), tenant: wert('amsign-kv-tenant'),
                client: wert('amsign-kv-client'), secret: wert('amsign-kv-secret'),
                zertifikat: wert('amsign-kv-cert'),
                anmeldung: wert('amsign-kv-auth'), jsign_quelle: wert('amsign-kv-jsign')
            };
            if (tsa) { body.tsa = tsa.value; }
            setStatus('amsign-status', t('amsign.kv_saving',
                'Anmeldung, Zertifikat und Probesignatur werden geprüft…'));
            fetch('/api/ai-mouse/admin/signatur/keyvault', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    if (!r.ok || !d || !d.ok) {
                        throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
            }).then(function (d) {
                self.renderSignatur(d);
                // Das Secret nie stehen lassen – auslesbar ist es ohnehin nicht.
                var sec = $('amsign-kv-secret');
                if (sec) { sec.value = ''; }
                setStatus('amsign-status',
                    d.hinweis || t('amsign.ok', 'Gespeichert.'),
                    d.hinweis ? 'error' : 'ok');
            }).catch(function (e) {
                setStatus('amsign-status', e.message, 'error');
            });
        },

        delKeyvault: function () {
            if (!window.confirm(t('amsign.kv_del_ask',
                'Key-Vault-Zugang wirklich entfernen? Liegt eine Zertifikatsdatei bereit, wird ab jetzt damit signiert, sonst gar nicht.'))) {
                return;
            }
            var self = this;
            setStatus('amsign-status', t('amsign.deleting', 'Wird entfernt…'));
            fetch('/api/ai-mouse/admin/signatur/keyvault', {
                method: 'DELETE', headers: authHeaders()
            }).then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    if (!r.ok || !d || !d.ok) {
                        throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
            }).then(function (d) {
                self.renderSignatur(d);
                setStatus('amsign-status', t('amsign.kv_del_ok',
                    'Entfernt. Die bereits gebaute Anwendung bleibt unverändert.'), 'ok');
            }).catch(function (e) {
                setStatus('amsign-status', e.message, 'error');
            });
        },

        delSignatur: function () {
            if (!window.confirm(t('amsign.del_ask',
                'Zertifikat und Kennwort wirklich entfernen? Künftige Auslieferungen sind dann unsigniert.'))) {
                return;
            }
            var self = this;
            setStatus('amsign-status', t('amsign.deleting', 'Wird entfernt…'));
            fetch('/api/ai-mouse/admin/signatur', {
                method: 'DELETE', headers: authHeaders()
            }).then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    if (!r.ok || !d || !d.ok) {
                        throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
            }).then(function (d) {
                self.renderSignatur(d);
                setStatus('amsign-status', t('amsign.del_ok',
                    'Entfernt. Die bereits gebaute Anwendung bleibt unverändert.'), 'ok');
            }).catch(function (e) {
                setStatus('amsign-status', e.message, 'error');
            });
        },

        /** Zustand: beantwortet „warum passiert nichts?" ohne einen Blick in
         *  die Skill-Liste oder aufs Portal. */
        /** Version des AUSGELIEFERTEN Pakets neben dem Download-Knopf – damit
         *  sichtbar ist, ob die Freigabe nach einem Versionswechsel nachgezogen
         *  werden muss. "" vom Server heisst unbekannt, nicht "keine". */
        renderVersion: function (d) {
            var el = $('amshare-ver');
            if (!el) { return; }
            if (!d.paket_bereit) {
                el.textContent = t('amshare.ver_none', 'Noch keine Anwendung gebaut.');
                return;
            }
            var text = t('amshare.ver', 'Aktuelle Version:') + ' '
                + (d.paket_version || t('amshare.ver_unknown', 'unbekannt'));
            if (d.paket_gebaut) {
                var datum = new Date(d.paket_gebaut);
                if (!isNaN(datum.getTime())) {
                    var sprache = (window.getLang && window.getLang()) || 'de';
                    text += ' (' + t('amshare.ver_built', 'gebaut am') + ' '
                        + datum.toLocaleString(sprache === 'en' ? 'en-GB' : 'de-DE',
                            { dateStyle: 'medium', timeStyle: 'short' }) + ')';
                }
            }
            el.textContent = text;
        },

        renderState: function (d) {
            var box = $('amtool-state');
            if (!box) { return; }
            var zeilen = [];
            if (!d.skill_aktiv) {
                zeilen.push(t('amtool.st_off',
                    '⚠ Der Skill ist nicht aktiv – die Freigabe hier bleibt bis dahin wirkungslos.'));
            } else {
                zeilen.push(t('amtool.st_on', '✓ Der Skill ist aktiv.'));
            }
            if (!d.paket_bereit) {
                // ⚠ KEINE AUFFORDERUNG ZUR HANDARBEIT. Der Bau laeuft von
                // selbst (Startup-Haken, Bootstrap-Schritt 6g, auf Bedarf) –
                // ein Satz, der einen Befehl zum Abtippen nennt, schickt den
                // Administrator zu einer Arbeit, die es nicht gibt.
                zeilen.push(t('amtool.st_nopkg',
                    '⏳ Die Anwendung wird gerade gebaut – der Download im Portal erscheint danach von selbst.'));
            } else {
                zeilen.push(t('amtool.st_pkg', '✓ Die Anwendung liegt zum Download bereit.'));
            }
            box.innerHTML = zeilen.map(function (z) {
                return '<p class="kb-hint">' + esc(z) + '</p>';
            }).join('');
        },

        /** Eigener Knopf, eigene TEILMENGE – wie im Jira-Reiter. Der Endpunkt
         *  schreibt nur das Freigabe-Feld; ein Knopf mit dem ganzen
         *  Formularstand überschriebe andere Skill-Einstellungen (Register). */
        saveAreas: function () {
            var gewaehlt = [];
            document.querySelectorAll('#amtool-areas input[data-area]').forEach(function (c) {
                if (c.checked) { gewaehlt.push(c.getAttribute('data-area')); }
            });
            setStatus('amtool-status', t('common.saving', 'Speichere…'));
            var self = this;
            fetch('/api/ai-mouse/admin/areas', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ bereiche: gewaehlt })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    // Der GESPEICHERTE Stand, nicht der gesendete: nur so fällt
                    // auf, wenn ein Bereich verworfen wurde.
                    setStatus('amtool-status', t('amtool.saved', '✓ Freigegeben:') + ' '
                        + ((d.bereiche || []).join(', ') || t('amtool.nothing', 'nichts')), 'ok');
                    // Neu laden: die Kästchen müssen den wirklich gültigen Stand
                    // zeigen, nicht den geklickten.
                    return self.load();
              })
              .catch(function (e) { setStatus('amtool-status', e.message, 'error'); });
        },

        // ── Vorgabe-Fragen ───────────────────────────────────────────────────
        // Die VORLAGE fuer neue Benutzer. Bauform bewusst wie die Vorlagenliste
        // im Jira-Reiter: eine Zeile je Eintrag, das Formular klappt DIREKT
        // darunter auf – EIN Container, der wandert (zwei waeren zwei Wege zum
        // Speichern, Register).
        _vorgaben: null,
        _vorgOffen: null,   // Kennung der gerade bearbeiteten Vorgabe ('' = neu)

        vorgabenLaden: function () {
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben', { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        });
                    }
                    return r.json();
                })
                .then(function (d) {
                    self._vorgaben = d.vorgaben || [];
                    self.vorgabenZeichnen();
                })
                .catch(function (e) {
                    // ⚠ Ein Ladefehler bleibt STEHEN und die Liste wird NICHT
                    // geleert: eine leere Liste waere von "es gibt keine
                    // Vorgaben" nicht zu unterscheiden – und wer darauf eine
                    // anlegt, haelt den Bestand fuer weg.
                    setStatus('amvorg-status', e.message, 'error');
                });
        },

        vorgabenZeichnen: function () {
            var box = $('amvorg-liste');
            if (!box) { return; }
            var vs = this._vorgaben || [];
            if (!vs.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('amvorg.empty',
                            'Keine Vorgaben – neue Benutzer starten dann mit einem leeren Menü.'))
                    + '</p>';
                return;
            }
            box.innerHTML = vs.map(function (v) {
                return '<div class="am-vorg-card" data-vid="' + esc(v.id) + '">'
                    + '<div class="am-vorg-row">'
                    + '<div class="am-vorg-main"><b>' + esc(v.titel) + '</b>'
                    + (v.aktion === 'anonymisieren'
                        ? ' <span class="am-vorg-art">'
                          + esc(t('amvorg.badge_anon', 'Anonymisieren')) + '</span>'
                        : '')
                    + '<span class="kb-hint" style="display:block;">' + esc(v.prompt) + '</span>'
                    + '</div>'
                    + '<button type="button" class="am-vorg-act" data-akt="edit" title="'
                    + esc(t('common.edit', 'Bearbeiten')) + '">' + JarvisIcons.pencil() + '</button>'
                    + '<button type="button" class="am-vorg-act" data-akt="del" title="'
                    + esc(t('common.delete', 'Löschen')) + '">'
                    + window.JarvisIcons.trash() + '</button>'
                    + '</div></div>';
            }).join('');
            box.querySelectorAll('.am-vorg-act').forEach(function (b) {
                b.addEventListener('click', function () {
                    var karte = b.closest('.am-vorg-card');
                    var vid = karte ? karte.getAttribute('data-vid') : '';
                    if (b.getAttribute('data-akt') === 'del') { Admin.vorgabeLoeschen(vid); }
                    else { Admin.vorgabeFormular(vid); }
                });
            });
            // Ein offenes Formular ueberlebt das Neuzeichnen – sonst schliesst
            // sich der Kasten bei jedem Speichern eines Nachbarn.
            if (this._vorgOffen !== null) { this.vorgabeFormular(this._vorgOffen, true); }
        },

        /** Formular unter der Zeile aufklappen. Zweiter Klick schliesst –
         *  sonst tut der Knopf sichtbar nichts. */
        vorgabeFormular: function (vid, wieder) {
            var alt = $('amvorg-form');
            if (alt && !wieder && this._vorgOffen === (vid || '')) {
                this._vorgOffen = null;
                alt.remove();
                return;
            }
            if (alt) { alt.remove(); }
            this._vorgOffen = vid || '';
            var v = (this._vorgaben || []).find(function (x) { return x.id === vid; }) || {};
            var form = document.createElement('div');
            form.id = 'amvorg-form';
            form.className = 'am-vorg-form';
            form.innerHTML =
                '<div class="form-group"><label>' + esc(t('amvorg.f_titel', 'Titel (Menüzeile)'))
                + '</label><input type="text" id="amvorg-f-titel" maxlength="80"></div>'
                + '<div class="form-group"><label>' + esc(t('amvorg.f_art', 'Art'))
                + '</label><select id="amvorg-f-art">'
                + '<option value="">' + esc(t('amvorg.art_frage', 'Frage an das Modell')) + '</option>'
                + '<option value="anonymisieren">'
                + esc(t('amvorg.art_anon', 'Anonymisieren – Namen und Gesichter unkenntlich machen'))
                + '</option></select>'
                + '<span class="kb-hint am-vorg-hint" id="amvorg-f-art-hint" style="display:none;">'
                + esc(t('amvorg.anon_hint',
                        'Statt einer Antwort kommt ein Bild zurück, in dem Namen, E-Mail-Adressen, '
                        + 'Telefonnummern und IBANs geschwärzt und Gesichter verpixelt sind. Das Bild '
                        + 'geht an kein Sprachmodell, nur der erkannte Text. Das Ergebnis wird nach '
                        + '30 Minuten gelöscht.'))
                + '</span></div>'
                + '<div class="form-group"><label id="amvorg-f-prompt-label">'
                + esc(t('amvorg.f_prompt', 'Anweisung an das Modell'))
                + '</label><textarea id="amvorg-f-prompt" rows="4" maxlength="2000"></textarea></div>'
                + '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
                + '<button type="button" class="btn-primary" id="amvorg-f-save">'
                + esc(t('common.save', 'Speichern')) + '</button>'
                + '<button type="button" class="btn-secondary" id="amvorg-f-abort">'
                + esc(t('common.cancel', 'Abbrechen')) + '</button></div>';
            // ⚠ Werte per .value setzen, NICHT ins Markup interpolieren: ein
            // Anführungszeichen im Titel sprengt sonst das Attribut.
            var karte = vid
                ? document.querySelector('.am-vorg-card[data-vid="' + vid + '"]')
                : null;
            if (karte) { karte.appendChild(form); }
            else { ($('amvorg-liste') || document.body).appendChild(form); }
            var ti = $('amvorg-f-titel'), pr = $('amvorg-f-prompt'), art = $('amvorg-f-art');
            if (ti) { ti.value = v.titel || ''; }
            if (pr) { pr.value = v.prompt || ''; }
            // ⚠ Erst NACH dem Einhaengen setzen – vorher gibt es die Option nicht
            // sicher, und `sel.value` auf eine fehlende Option verpufft still
            // (Register).
            if (art) {
                art.value = v.aktion === 'anonymisieren' ? 'anonymisieren' : '';
                art.addEventListener('change', function () { Admin._artAnzeigen(true); });
            }
            this._artAnzeigen(false);
            var sv = $('amvorg-f-save'), ab = $('amvorg-f-abort');
            if (sv) { sv.addEventListener('click', function () { Admin.vorgabeSpeichern(vid || ''); }); }
            if (ab) {
                ab.addEventListener('click', function () {
                    Admin._vorgOffen = null;
                    var f = $('amvorg-form');
                    if (f) { f.remove(); }
                });
            }
            if (ti && !wieder) { ti.focus(); }
        },

        /** Beschriftung und Hinweis an die gewaehlte Art anpassen.
         *  Bei „Anonymisieren" ist der Text keine Anweisung an ein Modell,
         *  sondern nur eine Beschreibung – eine Beschriftung, die weiter
         *  „Anweisung an das Modell" sagt, behauptet eine Wirkung, die es
         *  nicht gibt. ``vorbelegen``: ein LEERES Feld bekommt einen Text,
         *  weil der Server einen verlangt. */
        _artAnzeigen: function (vorbelegen) {
            var art = $('amvorg-f-art'), lbl = $('amvorg-f-prompt-label');
            var hint = $('amvorg-f-art-hint'), pr = $('amvorg-f-prompt');
            var anon = !!art && art.value === 'anonymisieren';
            if (lbl) {
                lbl.textContent = anon
                    ? t('amvorg.f_beschreibung', 'Beschreibung (wird nicht an ein Modell geschickt)')
                    : t('amvorg.f_prompt', 'Anweisung an das Modell');
            }
            if (hint) { hint.style.display = anon ? 'block' : 'none'; }
            if (anon && vorbelegen && pr && !pr.value.trim()) {
                pr.value = t('amvorg.anon_default',
                             'Namen und Gesichter im Ausschnitt unkenntlich machen.');
            }
        },

        vorgabeSpeichern: function (vid) {
            var ti = $('amvorg-f-titel'), pr = $('amvorg-f-prompt'), art = $('amvorg-f-art');
            if (!ti || !pr) { return; }
            setStatus('amvorg-status', t('common.saving', 'Speichere…'));
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ id: vid || '', titel: ti.value, prompt: pr.value,
                                       aktion: art ? art.value : '' })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    self._vorgOffen = null;
                    var f = $('amvorg-form');
                    if (f) { f.remove(); }
                    setStatus('amvorg-status', t('amvorg.saved', '✓ Gespeichert.'), 'ok');
                    return self.vorgabenLaden();
              })
              .catch(function (e) { setStatus('amvorg-status', e.message, 'error'); });
        },

        vorgabeLoeschen: function (vid) {
            var v = (this._vorgaben || []).find(function (x) { return x.id === vid; }) || {};
            if (!window.confirm(t('amvorg.del_ask', 'Vorgabe „{t}" wirklich löschen?')
                    .replace('{t}', v.titel || ''))) { return; }
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben/' + encodeURIComponent(vid),
                  { method: 'DELETE', headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    if (self._vorgOffen === vid) { self._vorgOffen = null; }
                    setStatus('amvorg-status', t('amvorg.deleted', '✓ Entfernt.'), 'ok');
                    return self.vorgabenLaden();
                })
                .catch(function (e) { setStatus('amvorg-status', e.message, 'error'); });
        }
    };

    window.AiMouseAdmin = Admin;
})();
