/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> in
   frontend/supportagent.html direkt nach branding.js. An DERSELBEN Stelle
   synchron eingebunden - Zeitpunkt des Aufrufs bleibt gleich. */
if (window.refreshBranding) { try { window.refreshBranding(); } catch (e) {} }
