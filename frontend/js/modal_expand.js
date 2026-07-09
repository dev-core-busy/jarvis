/* Generischer Vollbild-/Expand-Button für alle Popups – analog zum
   Einstellungen-Modal. Fügt jedem <div class="modal"> mit einer .modal-header
   einen ⛶-Button hinzu, der .modal-expanded auf dem Modal umschaltet
   (CSS vergrößert dann die .modal-content auf nahezu Vollbild).
   Das Einstellungen-Modal hat bereits einen eigenen Maximieren-Button. */
(function () {
    'use strict';
    var SKIP = { 'settings-modal': 1 };

    function addTo(modal) {
        if (!modal || (modal.id && SKIP[modal.id])) return;
        var header = modal.querySelector('.modal-header');
        if (!header || header.querySelector('.modal-expand-btn')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-icon modal-expand-btn';
        btn.title = 'Vollbild ein/aus';
        btn.setAttribute('aria-label', 'Vollbild');
        btn.textContent = '⛶';
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            var on = modal.classList.toggle('modal-expanded');
            btn.textContent = on ? '🗗' : '⛶';
            btn.classList.toggle('active', on);
        });

        // Direkt vor dem Schließen-Button einfügen (sonst ans Header-Ende).
        var closeBtn = header.querySelector(
            '.btn-close-modal, [id$="-close"], .btn-icon[aria-label="Schließen"], .btn-icon:last-child');
        if (closeBtn && closeBtn.parentNode) closeBtn.parentNode.insertBefore(btn, closeBtn);
        else header.appendChild(btn);
    }

    function sweep() {
        try { document.querySelectorAll('.modal').forEach(addTo); } catch (e) {}
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sweep);
    else sweep();

    // Dynamisch (später) erzeugte Standard-Popups automatisch nachrüsten.
    try {
        var obs = new MutationObserver(function (muts) {
            for (var i = 0; i < muts.length; i++) {
                var added = muts[i].addedNodes;
                for (var j = 0; j < added.length; j++) {
                    var n = added[j];
                    if (n.nodeType !== 1) continue;
                    if (n.classList && n.classList.contains('modal')) addTo(n);
                    else if (n.querySelectorAll) n.querySelectorAll('.modal').forEach(addTo);
                }
            }
        });
        obs.observe(document.body, { childList: true, subtree: true });
    } catch (e) {}

    // Für dynamisch erzeugte Popups nachrüstbar
    window.addModalExpand = addTo;
    window.sweepModalExpand = sweep;
})();
