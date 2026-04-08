package main

import (
	"log"
	"strings"
	"sync"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
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

	connected bool
	debugMode bool // Zeigt alle Backend-Status-Nachrichten (nicht nur highlight)

	ttsBuf strings.Builder // Sammelt LLM-Text für TTS-Ausgabe

	textDictating bool             // Diktat läuft im Text-Modus
	textDictCtrl  *DialogController // Diktat-Controller (One-Shot)
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
	if !EnsureSingleInstance() {
		return // Bereits eine Instanz aktiv – still beenden
	}

	a := app.NewWithID("com.jarvis.app")
	a.Settings().SetTheme(JarvisTheme{})

	cfg := LoadConfig()

	// Gespeicherte TTS-Stimme aktivieren
	SetTTSVoice(cfg.TTSVoice)
	SetTTSServer(cfg.ServerURL, cfg.APIKey)

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
	ja.chat.LoadHistory()

	// Natives Win32 System-Tray starten (kein externes Paket)
	StartNativeSysTray(
		func() { // Modus umschalten
			if ja.cfg.DialogMode {
				ja.switchToTextMode()
			} else {
				ja.switchToDialogMode()
			}
		},
		func() { // Einstellungen
			showSettingsWindow(ja.fyneApp, ja, func() { ja.reconnect(); ja.refreshChatWindow() })
		},
		func() { // Debug umschalten
			ja.toggleDebug()
			// Chat-Fenster öffnen damit Debug-Meldungen sichtbar sind
			if !ja.cfg.DialogMode {
				ja.openChatWindow()
			}
		},
		func() { // Beenden
			ja.shutdown()
		},
		func() bool { return ja.cfg.DialogMode },
		func() bool { return ja.debugMode },
	)

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

// refreshTray – kein Update nötig: Menü liest cfg.DialogMode beim Öffnen live.
func (ja *JarvisApp) refreshTray() {}

// toggleDebug schaltet den Debug-Modus um.
func (ja *JarvisApp) toggleDebug() {
	ja.debugMode = !ja.debugMode
	if ja.debugMode {
		ja.chat.AddMessage(RoleStatus, "🔍 Debug-Modus AN – alle Agent-Nachrichten sichtbar")
		ja.chat.AddMessage(RoleStatus,
			"Avatar-Farben: 🟡 Gold = Bereit  🟢 Grün = Hört  🔵 Cyan = Spricht")
	} else {
		ja.chat.AddMessage(RoleStatus, "🔍 Debug-Modus AUS")
	}
}

// ── Modus-Wechsel ─────────────────────────────────────────────────────────────

func (ja *JarvisApp) switchToDialogMode() {
	ja.cfg.DialogMode = true
	_ = ja.cfg.Save()
	// ERST Avatar zeigen, DANN Chat verstecken – verhindert Fyne-Exit bei 0 Fenstern
	ja.showAvatarWindow()
	ja.chatMu.Lock()
	if ja.chatWin != nil {
		ja.chatWin.Hide()
	}
	ja.chatMu.Unlock()
	ja.startDialogIfNeeded()
	ja.refreshTray()
}

func (ja *JarvisApp) switchToTextMode() {
	ja.cfg.DialogMode = false
	_ = ja.cfg.Save()
	if ja.dialog != nil {
		ja.dialog.Stop()
	}
	ja.avatar.SetMode(ModeIdle)
	ja.refreshTray()
	// ERST Chat öffnen, DANN Avatar verstecken – verhindert Fyne-Exit bei 0 Fenstern
	ja.openChatWindow()
	if ja.avatarWin != nil {
		ja.avatarWin.Hide()
	}
}

func (ja *JarvisApp) startDialogIfNeeded() {
	if !ja.cfg.DialogMode {
		return
	}
	if ja.audio == nil {
		ja.chat.AddMessage(RoleStatus, "❌ Audio nicht verfügbar – Mikrofon konnte nicht initialisiert werden")
		return
	}
	if ja.dialog == nil {
		ja.dialog = NewDialogController(ja.audio, ja.ws, ja)
		ja.dialog.OnRMSLevel = func(rms float64, frameMs int) {
			bars := int(rms / 100)
			if bars > 20 {
				bars = 20
			}
			bar := ""
			for i := 0; i < bars; i++ {
				bar += "█"
			}
			ja.chat.SetStatus("🎤 " + bar)
		}
	}
	if err := ja.dialog.Start(); err != nil {
		ja.chat.AddMessage(RoleStatus,
			"❌ Mikrofon-Fehler: "+err.Error()+
				"\n→ Bitte Mikrofonzugriff in den Windows-Datenschutzeinstellungen prüfen")
		return
	}
	// Im Wake-Word-Modus: Avatar zeigt Gold/Idle (wartet), nicht Grün
	if ja.cfg.WakeWordEnabled {
		ja.avatar.SetMode(ModeIdle)
	} else {
		ja.avatar.SetMode(ModeListening)
	}
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
	ja.ws.OnWakeWordResult = func(transcript string, detected bool) {
		log.Printf("[wakeword] transcript=%q detected=%v", transcript, detected)
		ja.chat.SetStatus("")
		if detected && ja.dialog != nil {
			ja.dialog.OnWakeWordDetected() // → setzt Avatar auf Grün
		} else {
			ja.avatar.SetMode(ModeIdle) // zurück auf Gold
			if transcript != "" {
				ja.chat.SetInput(transcript)
			}
		}
	}
	ja.ws.OnVoiceTranscript = func(transcript string) {
		log.Printf("[voice] Transkript: %q", transcript)
		ja.chat.SetStatus("")
		if transcript == "" {
			ja.chat.AddMessage(RoleStatus, "🎤 Spracheingabe nicht erkannt")
			return
		}
		if ja.cfg.AutoSendVoice {
			// AutoSend: User-Nachricht mit dem echten Transkript hinzufügen
			ja.chat.AddMessage(RoleUser, transcript)
		} else {
			// Manuell: Transkript ins Eingabefeld setzen, Nutzer bestätigt mit Senden
			ja.chat.SetInput(transcript)
		}
	}
	ja.chat.OnSend = func(text string) {
		ja.chat.AddMessage(RoleUser, text)
		ja.ws.SendTask(text)
	}
	ja.chat.OnMicButton = func() {
		if ja.textDictating {
			ja.stopTextDictation()
		} else {
			ja.startTextDictation()
		}
	}
	ja.chat.OnSettings = func() {
		showSettingsWindow(ja.fyneApp, ja, func() { ja.reconnect(); ja.refreshChatWindow() })
	}
	// Desktop-Steuerung: Backend kann Windows-Desktop steuern
	ja.ws.OnDesktopCommand = func(cmd DesktopCommand) {
		res := DesktopExecute(cmd)
		ja.ws.SendDesktopResult(res)
	}
	if ja.dialog != nil {
		ja.dialog.ws = ja.ws
	}
	ja.ws.Start()
}

// ── WebSocket-Callbacks ───────────────────────────────────────────────────────

func (ja *JarvisApp) onConnected(connected bool) {
	ja.connected = connected
	if connected {
		ja.chat.SetConnectionState("connected")
		ja.chat.SetInputEnabled(true)
		ja.chat.AddMessage(RoleStatus, "✓ Verbunden mit Jarvis")
		ja.startDialogIfNeeded()
	} else {
		ja.chat.SetConnectionState("disconnected")
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
	case "status":
		if msg.Message == "" {
			return
		}
		if msg.Highlight {
			// "⏳ Warte auf LLM-Antwort…" als transiente Statuszeile – nicht in die Bubble
			if strings.HasPrefix(msg.Message, "⏳") {
				ja.chat.SetStatus(msg.Message)
				return
			}
			// Echten LLM-Streamingtext: Status leeren, in Bubble anzeigen + TTS sammeln
			ja.chat.SetStatus("")
			ja.chat.AppendToLast(msg.Message)
			ja.ttsBuf.WriteString(msg.Message)
			ja.ttsBuf.WriteString(" ")
			ja.avatar.SetMode(ModeSpeaking)
			if ja.dialog != nil {
				ja.dialog.MuteWhileSpeaking(true)
			}
		} else if ja.debugMode {
			// Debug-Modus: Agent-Denk-Nachrichten klein/gedimmt zeigen
			ja.chat.AddDebugMessage(msg.Message)
		}

	case "error":
		ja.ttsBuf.Reset()
		ja.chat.AddMessage(RoleStatus, "⚠ "+msg.Message)
		ja.avatar.SetMode(ModeIdle)
		if ja.dialog != nil {
			ja.dialog.MuteWhileSpeaking(false)
		}

	case "agent_event":
		if msg.Event == "started" {
			// Neuer Durchlauf: TTS-Puffer zurücksetzen
			ja.ttsBuf.Reset()
		} else if msg.Event == "finished" {
			ja.avatar.SetMode(ModeIdle)
			ttsText := ja.ttsBuf.String()
			ja.ttsBuf.Reset()
			go func() {
				// TTS nur im Dialogmodus sprechen
				if ttsText != "" && ja.cfg.DialogMode {
					SpeakText(ttsText)
				}
				if ja.dialog != nil {
					ja.dialog.MuteWhileSpeaking(false)
					if ja.cfg.DialogMode {
						ja.avatar.SetMode(ModeListening)
					}
				}
			}()
		}

	case "wakeword_result":
		if msg.Highlight && ja.dialog != nil {
			ja.dialog.OnWakeWordDetected()
		}
	}
}

func (ja *JarvisApp) onTTSAudio(data []byte) {
	if ja.audio != nil {
		ja.audio.PlayWAV(data)
	}
}

// ── Fenster-Management ────────────────────────────────────────────────────────

func (ja *JarvisApp) showStartUI() {
	if ja.cfg.DialogMode {
		ja.showAvatarWindow()
	} else {
		ja.openChatWindow()
	}
}

// showAvatarWindow zeigt den rahmenlosen Iron Man Kopf (nur im Dialogmodus).
func (ja *JarvisApp) showAvatarWindow() {
	if ja.avatarWin != nil {
		ja.avatarWin.Show()
		return
	}
	win := ja.fyneApp.NewWindow("Jarvis")
	win.SetFixedSize(true)
	win.Resize(fyne.NewSize(260, 260))
	ja.avatarWin = win

	win.SetPadded(false) // kein Fyne-Innenrahmen um den Avatar
	win.SetContent(ja.avatar)

	// Fenster verstecken statt schließen → App bleibt im Tray am Leben
	win.SetCloseIntercept(func() {
		win.Hide()
	})
	win.SetOnClosed(func() {
		ja.avatarWin = nil
	})
	win.Show()

	// Nach dem Anzeigen: Rahmen entfernen + transparent + gespeicherte Position
	savedX, savedY := ja.cfg.AvatarX, ja.cfg.AvatarY
	go func() {
		MakeAvatarWindowFrameless()
		if savedX != 0 || savedY != 0 {
			SetAvatarPosition(savedX, savedY)
		}
	}()
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

// refreshChatWindow baut den Inhalt des Chat-Fensters neu auf (z.B. nach Hintergrundänderung).
func (ja *JarvisApp) refreshChatWindow() {
	ja.chatMu.Lock()
	defer ja.chatMu.Unlock()
	if ja.chatWin == nil {
		return
	}
	ja.chatWin.SetContent(ja.chat.Layout(ja.cfg))
}

func (ja *JarvisApp) openChatWindowLocked() {
	win := ja.fyneApp.NewWindow("Jarvis – Chat")
	win.Resize(fyne.NewSize(float32(ja.cfg.WindowW), float32(ja.cfg.WindowH)))
	win.SetIcon(fyne.NewStaticResource("jarvis_icon", jarvisIconPNG))
	win.SetContent(ja.chat.Layout(ja.cfg))

	// Fenster verstecken statt schließen → App bleibt im Tray am Leben
	win.SetCloseIntercept(func() {
		win.Hide()
	})
	win.SetOnClosed(func() {
		ja.chatMu.Lock()
		ja.chatWin = nil
		ja.chatMu.Unlock()
	})
	ja.chatWin = win
	win.Show()
}

// startTextDictation startet die Spracheingabe im Text-Modus (einmalig).
func (ja *JarvisApp) startTextDictation() {
	if ja.audio == nil {
		ja.chat.AddMessage(RoleStatus, "❌ Audio nicht verfügbar")
		return
	}
	if ja.cfg.DialogMode {
		return // Im Dialogmodus läuft die Spracherkennung bereits dauerhaft
	}
	ja.textDictating = true
	ja.chat.SetMicActive(true)
	ja.chat.AddMessage(RoleStatus, "🎤 Sprechen Sie jetzt…")

	dc := NewDialogController(ja.audio, ja.ws, ja)
	dc.StopAfterFirstUtterance = true
	dc.OnStop = func() {
		ja.textDictating = false
		ja.chat.SetMicActive(false)
		ja.chat.SetStatus("")
	}
	dc.OnRMSLevel = func(rms float64, frameMs int) {
		bars := int(rms / 100)
		if bars > 20 {
			bars = 20
		}
		bar := ""
		for i := 0; i < bars; i++ {
			bar += "█"
		}
		ja.chat.SetStatus("🎤 " + bar)
	}
	ja.textDictCtrl = dc
	if err := dc.Start(); err != nil {
		ja.chat.AddMessage(RoleStatus, "❌ Mikrofon-Fehler: "+err.Error())
		ja.textDictating = false
		ja.chat.SetMicActive(false)
		ja.textDictCtrl = nil
	}
}

// stopTextDictation beendet die laufende Spracheingabe im Text-Modus.
// Gepufferte Sprache wird noch verarbeitet (FlushAndStop).
func (ja *JarvisApp) stopTextDictation() {
	if ja.textDictCtrl != nil {
		ja.textDictCtrl.FlushAndStop()
		ja.textDictCtrl = nil
	}
	ja.textDictating = false
	ja.chat.SetMicActive(false)
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
	// Avatar-Position vor dem Beenden speichern
	if ja.cfg.DialogMode && ja.avatarWin != nil {
		x, y := GetAvatarPosition()
		if x != 0 || y != 0 {
			ja.cfg.AvatarX = x
			ja.cfg.AvatarY = y
		}
	}
	_ = ja.cfg.Save()
	ja.fyneApp.Quit()
}
