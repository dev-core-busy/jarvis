#!/usr/bin/env python3
"""Erhebt die Lizenzen aller Fremdkomponenten und erzeugt die Tabellen fuer
`used_licenses.md`.

Die Angaben stammen aus den PAKET-METADATEN, nicht aus einer Liste im Kopf:

  Python  – importlib.metadata im venv auf dem Zielserver
  Node    – package.json jedes Pakets in node_modules auf dem Zielserver
  Go      – LICENSE-Datei im lokalen Modul-Cache, Typ am Wortlaut erkannt

Warum ueber SSH: der venv und node_modules liegen auf dem Server, nicht im Repo.
Die Erhebung muss dort laufen, wo die Pakete tatsaechlich installiert sind –
requirements.txt allein zeigt nur die Spitze (198 Distributionen aus 42 direkten).

Lauf:   python3 tests/tools/lizenzen_erheben.py [--host root@191.100.144.1]
Ausgabe: /tmp/tabellen.md  (Abschnitte 9–11 von used_licenses.md)
"""
import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Python: Metadaten im venv auslesen ───────────────────────────────────────
PY_REMOTE = r'''
from importlib import metadata
import json
def klass(md):
    """Erst SPDX-Feld, dann Trove-Classifier, dann Freitext – in dieser Reihenfolge."""
    lic = (md.get("License-Expression") or "").strip()
    if lic:
        return lic
    cls = [c for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if cls:
        return " / ".join(c.split(" :: ")[-1].strip() for c in cls)
    raw = (md.get("License") or "").strip()
    if raw:
        # Manche Pakete legen den ganzen Lizenztext in das Feld.
        return raw.splitlines()[0][:70] if (len(raw) > 70 or "\n" in raw) else raw
    return ""
out = []
for d in metadata.distributions():
    try:
        md = d.metadata
        out.append({"name": md.get("Name") or "?", "version": d.version,
                    "license": klass(md)})
    except Exception:
        pass
out.sort(key=lambda x: x["name"].lower())
print(json.dumps(out, ensure_ascii=False))
'''

NODE_REMOTE = r'''
const fs=require('fs'),p=require('path');
const root=process.argv[2], out=[];
function scan(dir,pref){
  for(const e of fs.readdirSync(dir)){
    if(e==='.bin'||e==='.package-lock.json')continue;
    const f=p.join(dir,e);
    if(e.startsWith('@')){ scan(f,e+'/'); continue; }
    try{
      const j=JSON.parse(fs.readFileSync(p.join(f,'package.json'),'utf8'));
      let lic=j.license||j.licenses;
      if(Array.isArray(lic))lic=lic.map(x=>x.type||x).join(' / ');
      if(lic&&typeof lic==='object')lic=lic.type||'';
      out.push({name:j.name||pref+e,version:j.version||'',license:lic||''});
    }catch(err){}
  }
}
scan(root,'');
out.sort((a,b)=>a.name.localeCompare(b.name));
console.log(JSON.stringify(out));
'''

# Erkennung am charakteristischen Wortlaut. Reihenfolge ist wichtig: die
# BSD-3-Muster muessen VOR BSD-2 stehen, sonst gewinnt das kuerzere.
GO_MUSTER = [
    (r"Apache License\s*\n?\s*Version 2\.0", "Apache-2.0"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE\s*\n?\s*Version 3", "LGPL-3.0"),
    (r"GNU GENERAL PUBLIC LICENSE\s*\n?\s*Version 3", "GPL-3.0"),
    (r"GNU GENERAL PUBLIC LICENSE\s*\n?\s*Version 2", "GPL-2.0"),
    (r"Mozilla Public License.{0,40}2\.0", "MPL-2.0"),
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Redistributions of source code.*?Neither the name", "BSD-3-Clause"),
    (r"Redistributions of source code", "BSD-2-Clause"),
    (r"Permission to use, copy, modify, and/or distribute", "ISC"),
    (r"Boost Software License", "BSL-1.0"),
    (r"released into the public domain", "Unlicense"),
]

# Trove-Freitext -> SPDX. Bewusst konservativ: was sich nicht eindeutig zuordnen
# laesst, bleibt im Original stehen (lieber unscharf als falsch).
MAP = {
    'MIT License': 'MIT', 'MIT': 'MIT', 'CMU License (MIT-CMU)': 'MIT-CMU',
    'Apache Software License': 'Apache-2.0', 'Apache-2.0': 'Apache-2.0',
    'Apache License 2.0': 'Apache-2.0', 'Apache License, Version 2.0': 'Apache-2.0',
    'BSD License': 'BSD', 'BSD-3-Clause': 'BSD-3-Clause',
    '3-Clause BSD License': 'BSD-3-Clause', 'BSD-2-Clause': 'BSD-2-Clause',
    'Python Software Foundation License': 'PSF-2.0', 'PSF-2.0': 'PSF-2.0',
    'GNU Lesser General Public License v3 (LGPLv3)': 'LGPL-3.0',
    'LGPL-3.0-only': 'LGPL-3.0',
    'GNU General Public License v3 or later (GPLv3+)': 'GPL-3.0+',
    'GPLv2': 'GPL-2.0',
    'Mozilla Public License 2.0 (MPL 2.0)': 'MPL-2.0',
    'ISC License (ISCL)': 'ISC', 'Boost Software License': 'BSL-1.0',
    'Other/Proprietary License': 'proprietär',
    'NVIDIA Proprietary Software': 'proprietär (NVIDIA)',
    'LicenseRef-NVIDIA-SOFTWARE-LICENSE': 'proprietär (NVIDIA)',
    'LicenseRef-NVIDIA-Proprietary': 'proprietär (NVIDIA)',
    'BSD License / Apache Software License': 'BSD OR Apache-2.0',
    'MIT License / Apache Software License': 'MIT OR Apache-2.0',
    'Apache Software License / MIT License': 'MIT OR Apache-2.0',
    'BSD License / Other/Proprietary License': 'BSD (+ Zusatzbedingung)',
    'BSD 3-Clause OR Apache-2.0': 'Apache-2.0 OR BSD-3-Clause',
    'BSD-3-Clause, Apache-2.0, dependency licenses': 'BSD-3-Clause AND Apache-2.0',
}


def spdx(lic):
    lic = (lic or '').strip()
    return MAP.get(lic, lic or 'KEINE ANGABE')


def paketname(spec):
    """`faiss-cpu>=1.7.4` -> `faiss-cpu`; vereinheitlicht - und _."""
    return re.split(r'[<>=!\[;]', spec.strip())[0].strip().lower().replace('_', '-')


def direkte_abhaengigkeiten():
    """Wer steht in requirements.txt bzw. in einem skill.json? Der Rest ist transitiv."""
    d = collections.defaultdict(list)
    for zeile in open(os.path.join(ROOT, 'requirements.txt'), encoding='utf-8'):
        zeile = zeile.split('#')[0].strip()
        if zeile:
            d[paketname(zeile)].append('Kern')
    for pfad in sorted(glob.glob(os.path.join(ROOT, 'skills', '*', 'skill.json'))):
        man = json.load(open(pfad, encoding='utf-8'))
        skill = os.path.basename(os.path.dirname(pfad))
        for feld, zusatz in (('dependencies', ''), ('optional_dependencies', ' (optional)')):
            for spec in man.get(feld) or []:
                d[paketname(spec)].append('Skill `%s`%s' % (skill, zusatz))
    return d


def ssh(host, *cmd):
    return subprocess.run(['ssh', '-i', os.path.expanduser('~/.ssh/id_rsa'), host] + list(cmd),
                          capture_output=True, text=True, check=True).stdout


def hole_python(host, venv):
    ziel = '/tmp/_liz_py.py'
    subprocess.run(['ssh', '-i', os.path.expanduser('~/.ssh/id_rsa'), host,
                    'cat > %s' % ziel], input=PY_REMOTE, text=True, check=True)
    return json.loads(ssh(host, '%s/bin/python' % venv, ziel))


def hole_node(host, mods):
    ziel = '/tmp/_liz_node.js'
    subprocess.run(['ssh', '-i', os.path.expanduser('~/.ssh/id_rsa'), host,
                    'cat > %s' % ziel], input=NODE_REMOTE, text=True, check=True)
    return json.loads(ssh(host, 'node', ziel, mods))


def hole_go():
    """Nur die Module, die WIRKLICH gebunden werden.

    `go list -m all` liefert den ganzen Modulgraphen (193 Eintraege), von denen
    die meisten nie uebersetzt werden und gar nicht im Cache liegen. Gezaehlt
    gehoert, was `go list -deps` fuer das Zielsystem einbindet (25).
    """
    verz = os.path.join(ROOT, 'windows-app-go')
    if not os.path.isdir(verz):
        return []
    umg = dict(os.environ, GOOS='windows')
    roh = subprocess.run(
        ['go', 'list', '-deps', '-f',
         '{{if .Module}}{{.Module.Path}} {{.Module.Version}} {{.Module.Dir}}{{end}}', './...'],
        cwd=verz, env=umg, capture_output=True, text=True).stdout
    out, gesehen = [], set()
    for zeile in sorted(set(roh.splitlines())):
        teile = zeile.split()
        if len(teile) < 3 or teile[0] in gesehen:
            continue
        gesehen.add(teile[0])
        pfad, ver, verzeichnis = teile[0], teile[1], teile[2]
        lic = ''
        for name in ('LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENCE', 'COPYING', 'LICENSE-MIT'):
            datei = os.path.join(verzeichnis, name)
            if not os.path.exists(datei):
                continue
            txt = open(datei, errors='ignore').read()
            for rx, kennung in GO_MUSTER:
                if re.search(rx, txt, re.S | re.I):
                    lic = kennung
                    break
            lic = lic or 'unbekannt (LICENSE vorhanden)'
            break
        out.append({'name': pfad, 'version': ver, 'license': lic or 'keine LICENSE-Datei'})
    return out


def gruppiert(items, key):
    g = collections.defaultdict(list)
    for x in items:
        g[key(x)].append(x)
    # Grosse Bloecke zuerst – die Ausreisser stehen dann unten und fallen auf.
    return [(lic, sorted(g[lic], key=lambda x: x['name'].lower()))
            for lic in sorted(g, key=lambda k: (-len(g[k]), k.lower()))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='root@191.100.144.1')
    ap.add_argument('--venv', default='/opt/jarvis/venv')
    ap.add_argument('--node-modules', default='/opt/jarvis/services/whatsapp-bridge/node_modules')
    ap.add_argument('--out', default='/tmp/tabellen.md')
    a = ap.parse_args()

    direkt = direkte_abhaengigkeiten()
    py = hole_python(a.host, a.venv)
    node = hole_node(a.host, a.node_modules)
    go = hole_go()
    print('Python: %d · Node: %d · Go: %d' % (len(py), len(node), len(go)), file=sys.stderr)

    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('## 9. Python – Backend, Skills, Wissenssuche (%d Distributionen)\n' % len(py))
        for lic, xs in gruppiert(py, lambda x: spdx(x['license'])):
            f.write('\n### %s (%d)\n\n| Paket | Version | Rolle |\n|---|---|---|\n' % (lic, len(xs)))
            for x in xs:
                rolle = direkt.get(paketname(x['name']))
                f.write('| `%s` | %s | %s |\n' % (
                    x['name'], x['version'],
                    ', '.join(sorted(set(rolle))) if rolle else 'transitiv'))

        f.write('\n\n## 10. Node.js – WhatsApp-Bridge (%d Pakete)\n' % len(node))
        for lic, xs in gruppiert(node, lambda x: (x['license'] or 'KEINE ANGABE').replace('Apache 2.0', 'Apache-2.0')):
            f.write('\n### %s (%d)\n\n' % (lic, len(xs)))
            for x in xs:
                f.write('- `%s` %s\n' % (x['name'], x['version']))

        f.write('\n\n## 11. Go – Windows-Client (%d gebundene Module)\n' % len(go))
        for lic, xs in gruppiert(go, lambda x: x['license']):
            f.write('\n### %s (%d)\n\n' % (lic, len(xs)))
            for x in xs:
                f.write('- `%s` %s\n' % (x['name'], x['version']))
    print('geschrieben: %s' % a.out, file=sys.stderr)


if __name__ == '__main__':
    main()
