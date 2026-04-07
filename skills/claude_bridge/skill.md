🛠 Claude Bridge Skill (v2.0)
========================================

Dieser Skill definiert, wie Jarvis die "Claude Bridge" nutzt, um Anweisungen über das Terminal an ein offenes Claude-Fenster (unter Linux) weiterzureichen.

1. Setup & Installation (Einmalig)
----------------------------------
Um den Skill lokal zu aktivieren, führen Sie das folgende Setup-Skript aus. Es installiert notwendige System-Abhängigkeiten und erstellt die Datei `claude_bridge.py` mit der verbesserten Fenster-Erkennung.

### # setup_bridge.py
```python
import os
import subprocess

def setup():
    print("--- Starte Installation der Claude Bridge v2.0 (Linux) ---")
    
    # dependencies: xdotool (Steuerung), xclip (Zwischenablage)
    try:
        subprocess.run(["sudo", "apt-get", "install", "-y", "xdotool", "xclip"], check=True)
        # pip: pyperclip (Zwischenablage), --break-system-packages für moderne Distros
        subprocess.run(["pip", "install", "--user", "pyperclip", "--break-system-packages"], check=True)
    except Exception as e:
        print(f"Hinweis: Systempakete konnten ggf. nicht automatisch installiert werden: {e}")

    # Skript erstellen
    script_content = r"""import pyperclip
import time
import sys
import subprocess

def get_window_name(window_id):
    try:
        res = subprocess.run(['xdotool', 'getwindowname', window_id], capture_output=True, text=True)
        return res.stdout.strip()
    except:
        return ""

def send_to_claude_linux(instruction):
    try:
        print(f"Suche nach Claude-Fenstern...")
        window_search = subprocess.run(
            ['xdotool', 'search', '--onlyvisible', '--name', 'Claude'], 
            capture_output=True, text=True
        )
        window_ids = window_search.stdout.strip().split('\n')
        
        if not window_ids or window_ids[0] == '':
            print("Fehler: Claude-Fenster nicht gefunden.")
            return

        target_id = None
        target_name = ""

        # Priorisierung: Exakter Name "Claude" > Name enthält "Claude" (nicht Chrome) > Chrome Tab
        for wid in window_ids:
            name = get_window_name(wid)
            print(f"Analysiere: ID {wid} | Name: '{name}'")
            if name == "Claude":
                target_id = wid
                target_name = name
                break
            elif "Claude" in name and "Google Chrome" not in name:
                target_id = wid
                target_name = name
        
        if not target_id:
            target_id = window_ids[0]
            target_name = get_window_name(target_id)

        print(f"Ziel gesetzt: {target_name} (ID: {target_id})")

        # Fenster in den Vordergrund und Fokus setzen
        subprocess.run(['xdotool', 'windowactivate', target_id])
        subprocess.run(['xdotool', 'windowfocus', target_id])
        
        time.sleep(1.0) # Erforderliche Gedenksekunde für Fokus-Wechsel
        
        pyperclip.copy(instruction)
        
        # Eingabefeld fokussieren und Text einfügen
        subprocess.run(['xdotool', 'key', '--window', target_id, 'ctrl+a'])
        time.sleep(0.1)
        subprocess.run(['xdotool', 'key', '--window', target_id, 'ctrl+v'])
        time.sleep(0.2)
        subprocess.run(['xdotool', 'key', '--window', target_id, 'Return'])
        
        print(f"✅ Anweisung wurde an '{target_name}' gesendet.")
        
    except Exception as e:
        print(f"Fehler: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        send_to_claude_linux(" ".join(sys.argv[1:]))
"""
    with open("claude_bridge.py", "w") as f:
        f.write(script_content)
    
    print("\n✅ Installation abgeschlossen. Skript 'claude_bridge.py' ist bereit.")
    print("Nutzung: python3 claude_bridge.py 'Deine Anweisung an Claude'")

if __name__ == "__main__":
    setup()
```

2. Skill-Definition (Anleitung für die KI)
------------------------------------------
Kopiere diesen Text in deine Jarvis-Instanz (z.B. als Custom Instruction), damit die KI weiß, wie sie die Brücke bedienen soll.

**Skill Name:** `Linux-Bridge-Controller`

**Zweck:** Ermöglicht es Jarvis, Instruktionen an geöffnete Claude-Fenster unter Linux zu delegieren.

**Verhaltensregeln:**
1.  **Erkennung:** Reagiere auf "Instruiere Claude mit: [X]" oder "Frage Claude: [X]".
2.  **Präzision:** Formuliere den Ziel-Text klar und konsekutiv.
3.  **Generierung:** Erzeuge ausschließlich den Terminal-Befehl:
    `python3 claude_bridge.py "[Ziel-Text]"`
4.  **Hinweis:** Erinnere den Nutzer ggf., dass die Ziel-Anwendung (Claude) sichtbar und nicht minimiert sein sollte.

3. Troubleshooting & Best Practices
-----------------------------------
- **Mehrere Fenster:** Wenn sowohl der Browser als auch die Desktop-App offen sind, priorisiert die Brücke das Fenster mit dem exakten Namen "Claude". Falls der falsche Tab fokussiert wird, benennen Sie andere Tabs kurzzeitig um.
- **X11 vs. Wayland:** Dieses Skript benötigt eine X11-Umgebung (oder XWayland). In reinen Wayland-Sitzungen kann `xdotool` eingeschränkt sein.
- **Fokus-Fehler:** Wenn nichts getippt wird, erhöhen Sie den `time.sleep(1.0)` im Skript auf `1.5` oder `2.0`.
- **Sichtbarkeit:** Das Fenster muss vorhanden und "visible" sein (nicht auf einem anderen virtuellen Desktop ohne Fokus).

---
*Dieser Skill wurde für maximale Verlässlichkeit unter Linux mit Google Chrome und der Claude Desktop App optimiert.*
