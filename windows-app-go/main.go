package main

import (
	"log"
	"strings"
	"sync"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/driver/desktop"
)

// ── Zentrale App-Struktur ─────────────────────────────────────────────────────

type JarvisApp struct {
	fyneApp fyne.App
	cfg     *Config
	ws      *WSClient
	audio   *AudioManager
	avatar  *AvatarWidget
	chat    *ChatWidget
	dialog  *DialogController

	avatarWin fyne.Window
	chatWin   fyne.Window
	chatMu    sync.Mutex

	// Tray-Menü-Items (für dynamische Updates)
	modeItem    *fyne.MenuItem
	trayMenu    *fyne.Menu

	connected bool
}

// ── URL-Hilfsfunktionen ───────────────────────────────────────────────────────

func serverToURL(host string) string {
	host = strings.TrimSpace(host)
	hasSchema := strings.HasPrefix(host, "ws://") ||
		strings.HasPrefix(host, "wss://") ||
		strings.HasPrefix(host, "http://") ||
		strings.HasPrefix(host, "https://")
	if !hasSchema {
		host = "wss://" + host
	}
	schemaEnd := strings.Index(host, "://") + 3
	rest := host[schemaEnd:]
	if !strings.Contains(rest, "/") {
		host = host + "/ws"
	}
	return host
}

func urlToHost(url string) string {
	url = strings.TrimPrefix(url, "wss://")
	url = strings.TrimPrefix(url, "ws://")
	url = strings.TrimPrefix(url, "https://")
	url = strings.TrimPrefix(url, "http://")
	url = strings.TrimSuffix(url, "/ws")
	return url
}

// ── Einstiegspunkt ────────────────────────────────────────────────────────────

func main() {
	a := app.New()
	a.Settings().SetTheme(JarvisTheme{})

	cfg := LoadConfig()

	ja := &JarvisApp{
		fyneApp: a,
		cfg:     cfg,
	}

	// Audio initialisieren
	audio, err := NewAudioManager()
	if err != nil {
		log.Printf("[audio] Nicht verfügbar: %v", err)
	} else {
		ja.audio = audio
		if err := audio.StartPlayback(); err != nil {
			log.Printf("[audio] Playback-Start: %v", err)
		}
	}

	// Avatar + Chat aufbauen
	ja.avatar = NewAvatarWidget()
	ja.chat = NewChatWidget()
	ja.chat.SetInputEnabled(false)

	// System-Tray einrichten
	ja.setupTray()

	// Beim ersten Start sofort Einstellungen zeigen
	if cfg.IsFirstStart() {
		showSettingsWindow(a, ja, func() {
			ja.reconnect()
			ja.showStartUI()
		})
	} else {
		ja.reconnect()
		ja.showStartUI()
	}

	a.Run()
}

// ── System-Tray ───────────────────────────────────────────────────────────────

func (ja *JarvisApp) setupTray() {
	desk, ok := ja.fyneApp.(desktop.App)
	if !ok {
		log.Println("[tray] System-Tray nicht verfügbar auf dieser Plattform")
		return
	}

	// Tray-Icon
	icon := newTrayIcon(false, ja.cfg.DialogMode)
	desk.SetSystemTrayIcon(icon)

	// Modus-Item (Toggle)
	ja.modeItem = ja.buildModeItem()

	// Menü
	ja.trayMenu = fyne.NewMenu("Jarvis",
		ja.modeItem,
		fyne.NewMenuItem("Einstellungen", func() {
			showSettingsWindow(ja.fyneApp, ja, func() {
				ja.reconnect()
			})
		}),
		fyne.NewMenuItemSeparator(),
		fyne.NewMenuItem("Beenden", func() {
			ja.shutdown()
		}),
	)
	desk.SetSystemTrayMenu(ja.trayMenu)
}

func (ja *JarvisApp) buildModeItem() *fyne.MenuItem {
	if ja.cfg.DialogMode {
		return fyne.NewMenuItem("🎤 Dialogmodus  →  zu Textmodus wechseln", func() {
			ja.switchToTextMode()
		})
	}
	return fyne.NewMenuItem("⌨  Textmodus  →  zu Dialogmodus wechseln", func() {
		ja.switchToDialogMode()
	})
}

func (ja *JarvisApp) refreshTray() {
	if desk, ok := ja.fyneApp.(desktop.App); ok {
		icon := newTrayIcon(ja.connected, ja.cfg.DialogMode)
		desk.SetSystemTrayIcon(icon)
	}
	if ja.trayMenu == nil {
		return
	}
	newItem := ja.buildModeItem()
	ja.modeItem.Label = newItem.Label
	ja.modeItem.Action = newItem.Action
	ja.trayMenu.Refresh()
}

// ── Modus-Wechsel ─────────────────────────────────────────────────────────────

func (ja *JarvisApp) switchToDialogMode() {
	ja.cfg.DialogMode = true
	_ = ja.cfg.Save()
	// Chat-Fenster schließen – im Dialogmodus nicht sichtbar
	ja.chatMu.Lock()
	if ja.chatWin != nil {
		ja.chatWin.Close()
		ja.chatWin = nil
	}
	ja.chatMu.Unlock()
	// Avatar-Fenster öffnen
	ja.showAvatarWindow()
	ja.startDialogIfNeeded()
	ja.refreshTray()
}

func (ja *JarvisApp) switchToTextMode() {
	ja.cfg.DialogMode = false
	_ = ja.cfg.Save()
	// Mikrofon + Dialogmodus stoppen
	if ja.dialog != nil {
		ja.dialog.Stop()
	}
	// Avatar-Fenster schließen – im Textmodus nicht sichtbar
	if ja.avatarWin != nil {
		ja.avatarWin.Close()
		ja.avatarWin = nil
	}
	ja.avatar.SetMode(ModeIdle)
	ja.refreshTray()
	// Chat-Fenster öffnen (wie Android App)
	ja.openChatWindow()
}

func (ja *JarvisApp) startDialogIfNeeded() {
	if !ja.cfg.DialogMode || ja.audio == nil {
		return
	}
	if ja.dialog == nil {
		ja.dialog = NewDialogController(ja.audio, ja.ws, ja)
	}
	ja.dialog.Start()
	ja.avatar.SetMode(ModeListening)
}

// ── Verbindung ────────────────────────────────────────────────────────────────

func (ja *JarvisApp) reconnect() {
	if ja.ws != nil {
		ja.ws.Stop()
	}
	ja.ws = NewWSClient(ja.cfg)
	ja.ws.OnConnected = ja.onConnected
	ja.ws.OnMessage = ja.onMessage
	ja.ws.OnTTSAudio = ja.onTTSAudio
	ja.chat.OnSend = func(text string) {
		ja.chat.AddMessage(RoleUser, text)
		ja.ws.SendTask(text)
	}
	if ja.dialog != nil {
		ja.dialog.ws = ja.ws
	}
	ja.ws.Start()
}

// ── WebSocket-Callbacks ───────────────────────────────────────────────────────

func (ja *JarvisApp) onConnected(connected bool) {
	ja.connected = connected
	ja.refreshTray()
	if connected {
		ja.chat.SetInputEnabled(true)
		ja.chat.AddMessage(RoleStatus, "✓ Verbunden mit Jarvis")
		ja.startDialogIfNeeded()
	} else {
		ja.chat.SetInputEnabled(false)
		ja.chat.AddMessage(RoleStatus, "Verbindung getrennt – erneuter Versuch…")
		ja.avatar.SetMode(ModeIdle)
		if ja.dialog != nil {
			ja.dialog.MuteWhileSpeaking(true)
		}
	}
}

func (ja *JarvisApp) onMessage(msg WSMessage) {
	switch msg.Type {
	case "highlight":
		if msg.Message == "" {
			return
		}
		ja.chat.AppendToLast(msg.Message)
		ja.avatar.SetMode(ModeSpeaking)
		if ja.dialog != nil {
			ja.dialog.MuteWhileSpeaking(true) // Mic stumm während Jarvis spricht
		}

	case "error":
		ja.chat.AddMessage(RoleStatus, "⚠ "+msg.Message)
		ja.avatar.SetMode(ModeIdle)
		if ja.dialog != nil {
			ja.dialog.MuteWhileSpeaking(false)
		}

	case "agent_event":
		if msg.Event == "finished" {
			ja.avatar.SetMode(ModeIdle)
			if ja.dialog != nil {
				// Kurze Pause, dann Mic wieder aktiv
				go func() {
					ja.dialog.MuteWhileSpeaking(false)
					if ja.cfg.DialogMode {
						ja.avatar.SetMode(ModeListening)
					}
				}()
			}
		}
	}
}

func (ja *JarvisApp) onTTSAudio(data []byte) {
	if ja.audio != nil {
		ja.audio.PlayWAV(data)
	}
}

// ── Fenster-Management ────────────────────────────────────────────────────────

// showStartUI öffnet je nach Modus das passende Fenster beim Start.
func (ja *JarvisApp) showStartUI() {
	if ja.cfg.DialogMode {
		ja.showAvatarWindow()
	} else {
		ja.openChatWindow()
	}
}

// showAvatarWindow zeigt den Jarvis-Kopf (nur im Dialogmodus).
// Kein Chat-Fenster, kein Klick-Handler – nur der Kopf reagiert auf Audio.
func (ja *JarvisApp) showAvatarWindow() {
	if ja.avatarWin != nil {
		ja.avatarWin.Show()
		return
	}
	win := ja.fyneApp.NewWindow("Jarvis")
	win.SetFixedSize(true)
	win.Resize(fyne.NewSize(200, 210))
	ja.avatarWin = win

	// Nur der Avatar – kein Button, kein Toolbar
	win.SetContent(ja.avatar)
	win.SetOnClosed(func() {
		ja.avatarWin = nil
		// Schließen des Avatar-Fensters = App beenden (nur im Dialogmodus)
		if ja.cfg.DialogMode {
			ja.shutdown()
		}
	})
	win.Show()
}

func (ja *JarvisApp) openChatWindow() {
	ja.chatMu.Lock()
	defer ja.chatMu.Unlock()
	if ja.chatWin != nil {
		ja.chatWin.Show()
		return
	}
	ja.openChatWindowLocked()
}

func (ja *JarvisApp) openChatWindowLocked() {
	win := ja.fyneApp.NewWindow("Jarvis – Chat")
	win.Resize(fyne.NewSize(float32(ja.cfg.WindowW), float32(ja.cfg.WindowH)))
	win.SetContent(ja.chat.Layout())
	win.SetOnClosed(func() {
		ja.chatMu.Lock()
		ja.chatWin = nil
		ja.chatMu.Unlock()
	})
	ja.chatWin = win
	win.Show()
}

// ── App beenden ───────────────────────────────────────────────────────────────

func (ja *JarvisApp) shutdown() {
	if ja.dialog != nil {
		ja.dialog.Stop()
	}
	if ja.ws != nil {
		ja.ws.Stop()
	}
	if ja.audio != nil {
		ja.audio.Close()
	}
	if ja.avatar != nil {
		ja.avatar.Stop()
	}
	_ = ja.cfg.Save()
	ja.fyneApp.Quit()
}
