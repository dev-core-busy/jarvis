/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> direkt
   nach <body> in frontend/support-api.html. Setzt data-lang VOR dem ersten
   Zeichnen (kein Aufblitzen der falschen Sprache) - deshalb synchron an
   derselben Stelle eingebunden, kein defer/async. */
try{document.documentElement.setAttribute('data-lang',localStorage.getItem('jarvis_lang')||'de');}catch(e){}
