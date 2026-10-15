/* Theme VOR dem ersten Zeichnen setzen (gegen das helle/dunkle Aufblitzen).
 *
 * Stand bis 2026-10-04 als Inline-<script> direkt hinter <body> in jeder Seite.
 * BSI H4: die Content-Security-Policy laesst kein Inline-Skript mehr zu – die
 * Datei wird deshalb SYNCHRON (ohne defer/async) an derselben Stelle geladen,
 * damit sie weiterhin vor dem ersten Zeichnen laeuft. document.body existiert
 * dort bereits. */
try { if (localStorage.getItem('jarvis_theme') !== 'dark') document.body.classList.add('light'); } catch (e) {}
