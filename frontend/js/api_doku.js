/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> in
   frontend/api.html. Eine CSP mit script-src 'self' blockiert Inline-Skripte -
   deshalb hier als Datei, an DERSELBEN Stelle synchron eingebunden
   (kein defer/async): Zeitpunkt und Reihenfolge bleiben gleich. */
    (function () {
        'use strict';
        var TOKEN = window.JarvisSitzung.token();
        var H = { 'Authorization': 'Bearer ' + TOKEN };
        if (!TOKEN) { window.location.replace('/'); return; }

        // Übersetzungs-Helfer (i18n.js ist eingebunden; Fallback = Key)
        function T(k) { return window.t ? window.t(k) : k; }
        // Symbol statt Schloss-Emoji (Code-Review 2026-10-07; Emojis rendern je
        // System farbig oder als grauer Kasten)
        function _schloss() { return window.JarvisIcons ? window.JarvisIcons.lock() : ''; }

        var METHOD_ORDER = ['get', 'post', 'put', 'patch', 'delete'];
        var spec = null, endpoints = [], activeMethods = {};
        METHOD_ORDER.forEach(function (m) { activeMethods[m] = true; });
        activeMethods['other'] = true;

        // "nur lokal"-Beschraenkung: Menge beschraenkter Endpunkte + Fremdzugriffs-Statistik
        var localOnly = {};   // "METHOD /pfad" -> true
        var loStats = {};     // "METHOD /pfad" -> {count,last,ips}
        function epKey(ep) { return ep.method.toUpperCase() + ' ' + ep.path; }
        function loadLocalOnly() {
            return fetch('/api/admin/api-local-only', { headers: H })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    localOnly = {}; loStats = (d && d.stats) || {};
                    ((d && d.restricted) || []).forEach(function (k) { localOnly[k] = true; });
                }).catch(function () {});
        }

        function esc(s) {
            return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
            });
        }
        function mCls(m) {
            return { get: 'm-get', post: 'm-post', put: 'm-put', delete: 'm-delete', patch: 'm-patch' }[m] || 'm-other';
        }
        function groupOf(path) {
            var parts = path.split('/').filter(Boolean);
            if (parts[0] === 'api') return parts[1] || 'api';
            if (!parts.length) return T('api.group_pages');
            return parts[0];
        }

        // ── JSON-Schema → $ref auflösen + Beispiel erzeugen ──
        function resolveRef(sch) {
            if (sch && sch.$ref) {
                var name = sch.$ref.split('/').pop();
                var comp = (spec.components && spec.components.schemas) || {};
                return comp[name] || {};
            }
            return sch || {};
        }
        function example(sch, depth) {
            depth = depth || 0;
            sch = resolveRef(sch);
            if (depth > 5 || !sch || typeof sch !== 'object') return null;
            if (sch.example !== undefined) return sch.example;
            if (sch.default !== undefined) return sch.default;
            if (sch.enum && sch.enum.length) return sch.enum[0];
            if (sch.anyOf || sch.oneOf) return example((sch.anyOf || sch.oneOf)[0], depth + 1);
            if (sch.allOf) { var o = {}; sch.allOf.forEach(function (s) { var e = example(s, depth + 1); if (e && typeof e === 'object') Object.assign(o, e); }); return o; }
            var t = sch.type;
            if (t === 'object' || sch.properties) {
                var out = {};
                var props = sch.properties || {};
                Object.keys(props).forEach(function (k) { out[k] = example(props[k], depth + 1); });
                return out;
            }
            if (t === 'array') return [example(sch.items, depth + 1)].filter(function (x) { return x !== null; });
            if (t === 'integer' || t === 'number') return 0;
            if (t === 'boolean') return false;
            if (t === 'string') return sch.format === 'date-time' ? '2026-01-01T00:00:00Z' : '';
            return null;
        }

        function bodySchema(op) {
            try {
                var c = op.requestBody.content['application/json'];
                return c ? c.schema : null;
            } catch (e) { return null; }
        }

        // Summe der nicht-lokalen (externen) Zugriffe auf alle Endpunkte einer Gruppe
        // seit dem letzten Dienststart (aus loStats, wird live vom Backend gezaehlt).
        function groupForeign(list) {
            var n = 0;
            list.forEach(function (ep) { var st = loStats[epKey(ep)]; if (st) n += (st.count || 0); });
            return n;
        }

        // ── Rendern ──
        function render() {
            var wrap = document.getElementById('ad-wrap');
            wrap.innerHTML = '';
            var groups = {};
            endpoints.forEach(function (ep) {
                (groups[ep.group] = groups[ep.group] || []).push(ep);
            });
            Object.keys(groups).sort().forEach(function (gname) {
                var list = groups[gname].sort(function (a, b) {
                    return a.path.localeCompare(b.path) || METHOD_ORDER.indexOf(a.method) - METHOD_ORDER.indexOf(b.method);
                });
                var det = document.createElement('details');
                det.className = 'ad-group';
                det.setAttribute('data-group', gname);
                var sum = document.createElement('summary');
                var foreign = groupForeign(list);
                var fHtml = foreign > 0
                    ? ' <span class="ad-gforeign" title="' + esc(T('api.foreign_hint')) + '">(' + foreign + ')</span>'
                    : '';
                sum.innerHTML = esc(gname) + ' <span class="ad-gcount">' + list.length + '</span>' + fHtml
                    + '<span class="ep-lock ad-glock" title="' + esc(T('api.lock_group')) + '">' + _schloss() + '</span>';
                det.appendChild(sum);
                list.forEach(function (ep) { det.appendChild(epNode(ep)); });
                wrap.appendChild(det);
            });
            applyFilter();
            updateGroupMarkers();
        }

        // Zaehler live aktualisieren, ohne die Gruppen neu aufzubauen (erhaelt den
        // Aufklapp-Zustand und laufende Testformulare). Holt nur die Statistik neu.
        function refreshForeignCounts() {
            fetch('/api/admin/api-local-only', { headers: H })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d) return;
                    loStats = d.stats || {};
                    // pro einzelnem Endpunkt
                    document.querySelectorAll('.ep[data-key]').forEach(function (ep) {
                        var st = loStats[ep.getAttribute('data-key')];
                        var n = st ? (st.count || 0) : 0;
                        var sum = ep.querySelector('summary');
                        if (!sum) return;
                        var badge = sum.querySelector('.ep-foreign');
                        if (n > 0) {
                            if (!badge) {
                                badge = document.createElement('span');
                                badge.className = 'ep-foreign';
                                badge.title = T('api.foreign_hint_ep');
                                var path = sum.querySelector('.ep-path');
                                if (path) path.insertAdjacentElement('afterend', badge);
                            }
                            badge.textContent = '(' + n + ')';
                        } else if (badge) {
                            badge.remove();
                        }
                    });
                    // pro Gruppe (Summe)
                    document.querySelectorAll('.ad-group').forEach(function (grp) {
                        var gname = grp.getAttribute('data-group');
                        var list = endpoints.filter(function (ep) { return ep.group === gname; });
                        var foreign = groupForeign(list);
                        var sum = grp.querySelector('summary');
                        var badge = sum ? sum.querySelector('.ad-gforeign') : null;
                        if (foreign > 0) {
                            if (!badge) {
                                badge = document.createElement('span');
                                badge.className = 'ad-gforeign';
                                badge.title = T('api.foreign_hint');
                                var cnt = sum.querySelector('.ad-gcount');
                                if (cnt) cnt.insertAdjacentElement('afterend', badge);
                            }
                            badge.textContent = '(' + foreign + ')';
                        } else if (badge) {
                            badge.remove();
                        }
                    });
                }).catch(function () {});
        }

        function epNode(ep) {
            var op = ep.op;
            var key = epKey(ep);
            var d = document.createElement('details');
            d.className = 'ep' + (localOnly[key] ? ' is-local-only' : '');
            d.setAttribute('data-search', (ep.method + ' ' + ep.path + ' ' + (op.summary || '') + ' ' + (op.description || '')).toLowerCase());
            d.setAttribute('data-method', ep.method);
            d.setAttribute('data-key', key);

            var s = document.createElement('summary');
            var st = loStats[key];
            var epForeign = st ? (st.count || 0) : 0;
            var epFHtml = epForeign > 0
                ? '<span class="ep-foreign" title="' + esc(T('api.foreign_hint_ep')) + '">(' + epForeign + ')</span>'
                : '';
            s.innerHTML = '<span class="ep-method ' + mCls(ep.method) + '">' + ep.method.toUpperCase() + '</span>'
                + '<span class="ep-path">' + esc(ep.path) + '</span>'
                + epFHtml
                + '<span class="ep-sum">' + esc(op.summary || '') + '</span>'
                + '<span class="ep-lock" title="' + esc(T('api.lock_ep')) + '">' + _schloss() + '</span>';
            d.appendChild(s);

            var body = document.createElement('div');
            body.className = 'ep-body';

            // "nur lokal"-Schalter (Admin): beschraenkt den Endpunkt auf Loopback
            var loRow = document.createElement('label'); loRow.className = 'ad-localonly';
            var loCb = document.createElement('input'); loCb.type = 'checkbox'; loCb.checked = !!localOnly[key];
            var loTxt = document.createElement('span');
            loTxt.innerHTML = ' ' + _schloss() + ' ' + esc(T('api.local_only_label'));
            loRow.appendChild(loCb); loRow.appendChild(loTxt);
            body.appendChild(loRow);
            loCb.addEventListener('change', function () { toggleLocalOnly(ep, loCb); });

            var descText = op.description || op.summary || '';
            if (descText) {
                var ds = document.createElement('div'); ds.className = 'ep-desc'; ds.textContent = descText;
                body.appendChild(ds);
            }

            var params = (op.parameters || []);
            if (params.length) {
                var ph = document.createElement('div'); ph.className = 'ep-h'; ph.textContent = T('api.params'); body.appendChild(ph);
                var tbl = document.createElement('table'); tbl.className = 'ad-params';
                tbl.innerHTML = '<tr><th>' + esc(T('api.th_name')) + '</th><th>' + esc(T('api.th_in')) + '</th><th>'
                    + esc(T('api.th_type')) + '</th><th>' + esc(T('api.th_required')) + '</th></tr>' + params.map(function (p) {
                    var t = (resolveRef(p.schema).type) || '';
                    return '<tr><td><code>' + esc(p.name) + '</code></td><td>' + esc(p.in) + '</td><td>' + esc(t)
                        + '</td><td>' + (p.required ? '<span class="ad-req">' + esc(T('api.yes')) + '</span>' : esc(T('api.no'))) + '</td></tr>';
                }).join('');
                body.appendChild(tbl);
            }

            var bs = bodySchema(op);
            var exampleBody = bs ? example(bs) : null;
            if (bs) {
                var bh = document.createElement('div'); bh.className = 'ep-h'; bh.textContent = T('api.body_example'); body.appendChild(bh);
                var pre = document.createElement('pre'); pre.className = 'ad-code';
                pre.textContent = JSON.stringify(exampleBody, null, 2);
                body.appendChild(pre);
            }

            // cURL-Beispiel
            var ch = document.createElement('div'); ch.className = 'ep-h'; ch.textContent = T('api.curl_example'); body.appendChild(ch);
            var curl = document.createElement('pre'); curl.className = 'ad-code';
            var cl = "curl -sk -X " + ep.method.toUpperCase() + " '" + location.origin + ep.path + "' \\\n"
                + "  -H 'Authorization: Bearer <" + T('api.token_ph') + ">'";
            if (bs) cl += " \\\n  -H 'Content-Type: application/json' \\\n  -d '" + JSON.stringify(exampleBody) + "'";
            curl.textContent = cl;
            body.appendChild(curl);

            body.appendChild(testForm(ep, params, bs, exampleBody));
            d.appendChild(body);
            return d;
        }

        // "nur lokal" umschalten. Beim Einschraenken prueft der Server auf reale
        // Fremdzugriffe und liefert ggf. eine Warnung mit Begruendung -> confirm.
        function toggleLocalOnly(ep, cb) {
            var key = epKey(ep);
            var want = cb.checked;
            function apply(confirm) {
                return fetch('/api/admin/api-local-only', {
                    method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, H),
                    body: JSON.stringify({ key: key, local_only: want, confirm: !!confirm })
                }).then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); });
            }
            apply(false).then(function (res) {
                var d = res.d || {};
                if (d.needs_confirm) {
                    if (window.confirm(d.warning || T('api.local_only_confirm'))) {
                        return apply(true).then(function (res2) { finish(res2); });
                    }
                    cb.checked = false;   // abgebrochen -> Zustand zuruecksetzen
                    return;
                }
                finish(res);
            }).catch(function () { cb.checked = !want; window.alert(T('api.save_failed')); });

            function finish(res) {
                var d = res.d || {};
                if (res.status >= 400 || d.error) {
                    cb.checked = !want; window.alert(d.error || ('Fehler (HTTP ' + res.status + ')'));
                    return;
                }
                localOnly = {}; (d.restricted || []).forEach(function (k) { localOnly[k] = true; });
                cb.checked = !!localOnly[key];
                // Marker an Endpunkt-Zeile UND Gruppe live aktualisieren
                var det = cb.closest('.ep');
                if (det) {
                    det.classList.toggle('is-local-only', !!localOnly[key]);
                    updateGroupMarkers();
                }
            }
        }

        // Markiert jede Gruppe, in der mindestens ein Endpunkt beschraenkt ist.
        function updateGroupMarkers() {
            document.querySelectorAll('.ad-group').forEach(function (grp) {
                var any = grp.querySelector('.ep.is-local-only') !== null;
                grp.classList.toggle('has-local-only', any);
            });
        }

        function testForm(ep, params, bs, exampleBody) {
            var box = document.createElement('div');
            box.className = 'ad-test';
            var th = document.createElement('div'); th.className = 'ep-h'; th.textContent = T('api.test_call'); box.appendChild(th);

            var inputs = {};
            params.forEach(function (p) {
                var f = document.createElement('div'); f.className = 'ad-field';
                var lab = document.createElement('label');
                lab.innerHTML = esc(p.name) + ' <span class="ad-in">(' + esc(p.in) + (p.required ? esc(T('api.required_suffix')) : '') + ')</span>';
                var inp = document.createElement('input'); inp.className = 'ad-input';
                inp.placeholder = (resolveRef(p.schema).type) || '';
                f.appendChild(lab); f.appendChild(inp); box.appendChild(f);
                inputs[p.name] = { el: inp, in: p.in };
            });

            var bodyEl = null;
            var allowBody = ep.method !== 'get';
            if (allowBody) {
                var bf = document.createElement('div'); bf.className = 'ad-field';
                var bl = document.createElement('label');
                bl.innerHTML = esc(T('api.body_label')) + (bs ? '' : '<span class="ad-in">' + esc(T('api.body_free')) + '</span>');
                bodyEl = document.createElement('textarea'); bodyEl.className = 'ad-textarea';
                bodyEl.value = bs ? JSON.stringify(exampleBody, null, 2) : '';
                if (!bs) bodyEl.placeholder = '{ }';
                bf.appendChild(bl); bf.appendChild(bodyEl); box.appendChild(bf);
            }

            var btn = document.createElement('button'); btn.className = 'ad-send'; btn.textContent = T('api.send');
            box.appendChild(btn);

            var resp = document.createElement('div'); resp.className = 'ad-resp';
            var rstat = document.createElement('div'); rstat.className = 'ad-resp-status';
            var rpre = document.createElement('pre'); rpre.className = 'ad-code'; rpre.style.marginTop = '6px';
            resp.appendChild(rstat); resp.appendChild(rpre); box.appendChild(resp);

            btn.addEventListener('click', function () {
                var url = ep.path;
                var qs = [];
                Object.keys(inputs).forEach(function (name) {
                    var o = inputs[name]; var v = o.el.value;
                    if (o.in === 'path') { url = url.replace('{' + name + '}', encodeURIComponent(v)); }
                    else if (o.in === 'query' && v !== '') { qs.push(encodeURIComponent(name) + '=' + encodeURIComponent(v)); }
                });
                if (qs.length) url += (url.indexOf('?') >= 0 ? '&' : '?') + qs.join('&');

                var opts = { method: ep.method.toUpperCase(), headers: { 'Authorization': 'Bearer ' + TOKEN } };
                if (bodyEl) {
                    opts.headers['Content-Type'] = 'application/json';
                    if (bodyEl.value.trim()) {
                        try { opts.body = JSON.stringify(JSON.parse(bodyEl.value)); }
                        catch (e) { resp.style.display = 'block'; rstat.className = 'ad-resp-status bad'; rstat.textContent = T('api.bad_json') + e.message; rpre.textContent = ''; return; }
                    }
                }
                btn.disabled = true; btn.textContent = T('api.sending_btn');
                resp.style.display = 'block'; rstat.className = 'ad-resp-status'; rstat.textContent = T('api.sending'); rpre.textContent = '';
                var t0 = performance.now();
                fetch(url, opts).then(function (r) {
                    var ct = r.headers.get('content-type') || '';
                    var pr = ct.indexOf('application/json') >= 0 ? r.json().then(function (j) { return JSON.stringify(j, null, 2); })
                        : r.text().then(function (t) { return t.length > 20000 ? t.slice(0, 20000) + '\n' + T('api.truncated') : t; });
                    return pr.then(function (txt) { return { status: r.status, ok: r.ok, txt: txt }; });
                }).then(function (res) {
                    var ms = Math.round(performance.now() - t0);
                    rstat.className = 'ad-resp-status ' + (res.ok ? 'ok' : (res.status >= 500 ? 'bad' : 'warn2'));
                    rstat.textContent = 'HTTP ' + res.status + ' · ' + ms + ' ms';
                    rpre.textContent = res.txt;
                }).catch(function (e) {
                    rstat.className = 'ad-resp-status bad'; rstat.textContent = T('api.network_error'); rpre.textContent = String(e);
                }).finally(function () { btn.disabled = false; btn.textContent = T('api.send'); });
            });

            return box;
        }

        // ── Filter (Suche + Methoden) ──
        function applyFilter() {
            var q = (document.getElementById('ad-search').value || '').trim().toLowerCase();
            document.querySelectorAll('.ad-group').forEach(function (g) {
                var any = false;
                g.querySelectorAll('.ep').forEach(function (ep) {
                    var mOk = activeMethods[ep.getAttribute('data-method')] !== false;
                    var sOk = !q || ep.getAttribute('data-search').indexOf(q) >= 0;
                    var show = mOk && sOk;
                    ep.style.display = show ? '' : 'none';
                    if (show) any = true;
                });
                g.style.display = any ? '' : 'none';
                if (q && any) g.open = true;
            });
        }

        function buildMethodFilter() {
            var box = document.getElementById('ad-mfilter');
            var present = {};
            endpoints.forEach(function (e) { present[e.method] = true; });
            METHOD_ORDER.concat(['other']).forEach(function (m) {
                if (!present[m]) return;
                var b = document.createElement('span');
                b.className = 'ad-mf on ' + mCls(m); b.textContent = m.toUpperCase();
                b.addEventListener('click', function () {
                    activeMethods[m] = !activeMethods[m];
                    b.classList.toggle('on', activeMethods[m]);
                    applyFilter();
                });
                box.appendChild(b);
            });
        }

        // Abmelden – gleiche Reihenfolge wie auf den uebrigen Seiten: das
        // Signal MUSS raus, BEVOR der Token verworfen wird (danach ist die
        // Abmeldung nicht mehr authentifizierbar), und die Seite navigiert
        // unmittelbar weg (keepalive steckt in JarvisSession.logout).
        var _lo = document.getElementById('ad-logout-btn');
        if (_lo) _lo.addEventListener('click', function () {
            var p = (window.JarvisSession ? window.JarvisSession.logout()
                                          : Promise.resolve());
            var keys = (window.JarvisSession && window.JarvisSession.tokenKeys)
                       || window.JarvisSitzung.tokenSchluessel();
            keys.forEach(function (k) { try { localStorage.removeItem(k); } catch (e) {} });
            p.catch(function () {}).then(function () { window.location.replace('/'); });
        });

        // ── Start: Admin-Gate + Schema laden ──
        fetch('/api/me', { headers: H }).then(function (r) { return r.ok ? r.json() : null; }).then(function (me) {
            if (!me) { window.location.replace('/'); return Promise.reject('noauth'); }
            if (!me.is_admin) { window.location.replace('/portal'); return Promise.reject('noadmin'); }
            return fetch('/openapi.json', { headers: H });
        }).then(function (r) { return r.json(); }).then(function (s) {
            spec = s;
            var paths = spec.paths || {};
            Object.keys(paths).forEach(function (path) {
                Object.keys(paths[path]).forEach(function (m) {
                    if (['get', 'post', 'put', 'patch', 'delete'].indexOf(m) < 0) return;
                    endpoints.push({ path: path, method: m, op: paths[path][m], group: groupOf(path) });
                });
            });
            return loadLocalOnly();
        }).then(function () {
            setCount();
            buildMethodFilter();
            render();
            document.getElementById('ad-search').addEventListener('input', applyFilter);
            // Zugriffszaehler pro Gruppe regelmaessig auffrischen (seit-Neustart-Werte)
            // – nur bei sichtbarem Tab (Code-Review 2026-10-07)
            setInterval(function () { if (!document.hidden) refreshForeignCounts(); }, 15000);
        }).catch(function (e) {
            if (e === 'noauth' || e === 'noadmin') return;
            var l = document.getElementById('ad-loading');
            if (l) { l.className = 'ad-error'; l.textContent = T('api.load_error'); }
        });

        function setCount() {
            document.getElementById('ad-count').textContent = endpoints.length + ' ' + T('api.endpoints') + ' ' + location.origin;
        }

        // Sprachwechsel: statische Texte macht applyLang (data-i18n), die dynamisch
        // gerenderten Endpunkt-Bloecke werden komplett neu aufgebaut. Die Endpunkt-
        // Beschreibungen selbst stammen aus den Backend-Docstrings (nur Deutsch).
        document.querySelectorAll('.lang-toggle-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                if (window.setLang) window.setLang(b.getAttribute('data-lang'));
                if (spec) { setCount(); render(); }
            });
        });
    })();
