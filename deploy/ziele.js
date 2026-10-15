// Server-Ziele aus der Umgebung statt aus dem Repo - Gegenstueck zu deploy/ziele.py.
// Reihenfolge: Umgebungsvariable, sonst .env im Repo-Wurzelverzeichnis (gitignored).
// Fehlt der Wert: Exit 2 ("konnte nicht laufen") statt eines geratenen Servers.
'use strict';
const fs = require('fs');
const path = require('path');

const ENV_DATEI = path.join(__dirname, '..', '.env');

function finde(name) {
  if (process.env[name]) return process.env[name];
  let text;
  try { text = fs.readFileSync(ENV_DATEI, 'utf8'); } catch (_) { return null; }
  for (const roh of text.split('\n')) {
    const zeile = roh.trim();
    if (!zeile || zeile.startsWith('#') || !zeile.includes('=')) continue;
    const i = zeile.indexOf('=');
    if (zeile.slice(0, i).replace(/^export\s+/, '').trim() !== name) continue;
    let wert = zeile.slice(i + 1).trim();
    if (wert.length >= 2 && wert[0] === wert[wert.length - 1] && `"'`.includes(wert[0])) {
      wert = wert.slice(1, -1);
    }
    return wert || null;
  }
  return null;
}

function wert(name) {
  const w = finde(name);
  if (!w) {
    console.error(`ABBRUCH (Exit 2): ${name} ist nicht gesetzt.`);
    console.error(`  Interne Adressen stehen nicht im Repo. Eintragen in ${ENV_DATEI}`);
    console.error('  (Vorlage: .env.example) oder als Umgebungsvariable setzen.');
    process.exit(2);
  }
  return w;
}

module.exports = { finde, wert };
