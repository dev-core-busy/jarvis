package main

import (
	"encoding/binary"
	"log"
	"math"
	"strings"
	"sync"
	"time"
)

// ── VAD-Konstanten (Voice Activity Detection) ─────────────────────────────────

const (
	vadSampleRate = 16000 // Hz
	vadFrameSize  = 160   // Samples pro Frame (~10ms)
)

// ── Dialog-Zustands-Maschine ──────────────────────────────────────────────────

type DialogState int

const (
	StateWaitWakeWord DialogState = iota // Wartet auf Wake-Word
	StateListening                        // Aktiv: Aufnahme nach Wake-Word
	StateSending                          // Sendet gerade (Mic stumm)
)

// ── Dialog-Controller ─────────────────────────────────────────────────────────

type DialogController struct {
	mu    sync.Mutex
	state DialogState
	muted bool // Mic stumm (während Jarvis spricht)

	speechBuf []byte
	silenceMs int
	speechMs  int
	inSpeech  bool

	audio *AudioManager
	ws    *WSClient
	app   *JarvisApp

	StopAfterFirstUtterance bool
	OnStop                  func()                              // Callback nach erster Äußerung (Diktat-Modus)
	OnRMSLevel              func(rms float64, frameMs int)     // Callback für Live-Pegelanzeige
}

func NewDialogController(audio *AudioManager, ws *WSClient, app *JarvisApp) *DialogController {
	return &DialogController{audio: audio, ws: ws, app: app}
}

// Start aktiviert den Dialogmodus. Gibt nil zurück wenn OK, sonst den Mic-Fehler.
func (d *DialogController) Start() error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.state != StateSending || !d.audio.IsRecording() {
		if d.app.cfg.WakeWordEnabled {
			d.state = StateWaitWakeWord
		} else {
			d.state = StateListening
		}
	}
	d.audio.OnMicData = d.processMicFrame
	if !d.audio.IsRecording() {
		if err := d.audio.StartRecording(); err != nil {
			log.Printf("[dialog] Mic-Start Fehler: %v", err)
			return err
		}
	}
	log.Printf("[dialog] Dialogmodus gestartet (WakeWord=%v, State=%v)", d.app.cfg.WakeWordEnabled, d.state)
	return nil
}

// Stop beendet den Dialogmodus.
func (d *DialogController) Stop() {
	d.mu.Lock()
	d.state = StateSending // temporärer Stop-Marker
	d.mu.Unlock()
	d.audio.StopRecording()
	log.Println("[dialog] Dialogmodus beendet")
}

// FlushAndStop verarbeitet noch gepufferte Sprache und beendet dann den Dialogmodus.
// Wird beim manuellen Mic-Stop aufgerufen (zweiter Klick auf Mikrofon-Button).
func (d *DialogController) FlushAndStop() {
	d.mu.Lock()
	buf := d.speechBuf
	sm := d.speechMs
	state := d.state
	d.speechBuf = nil
	d.silenceMs = 0
	d.speechMs = 0
	d.inSpeech = false
	d.state = StateSending
	d.mu.Unlock()
	d.audio.StopRecording()
	if len(buf) > 0 && sm >= d.app.cfg.MinSpeechMs {
		log.Printf("[dialog] FlushAndStop: verarbeite %dms gepufferte Sprache", sm)
		go d.handleUtterance(buf, sm, state)
	}
	log.Println("[dialog] Dialogmodus beendet (flush)")
}

// MuteWhileSpeaking stummt das Mikrofon während Jarvis spricht.
func (d *DialogController) MuteWhileSpeaking(muted bool) {
	d.mu.Lock()
	d.muted = muted
	if !muted && d.app.cfg.WakeWordEnabled {
		// Nach TTS: zurück in Wake-Word-Modus
		d.state = StateWaitWakeWord
		d.speechBuf = nil
		d.silenceMs = 0
		d.speechMs = 0
		d.inSpeech = false
	}
	d.mu.Unlock()
}

// OnWakeWordDetected wird vom WS-Client aufgerufen wenn Backend Wake-Word bestätigt.
func (d *DialogController) OnWakeWordDetected() {
	d.mu.Lock()
	d.state = StateListening
	d.speechBuf = nil
	d.silenceMs = 0
	d.speechMs = 0
	d.inSpeech = false
	d.mu.Unlock()
	d.app.avatar.SetMode(ModeListening)
	d.app.chat.AddMessage(RoleStatus, "🎤 Jarvis hört…")
	log.Println("[dialog] Wake-Word erkannt – warte auf Befehl")
}

// processMicFrame verarbeitet einen eingehenden PCM-Frame (VAD).
func (d *DialogController) processMicFrame(pcm []byte) {
	d.mu.Lock()
	state := d.state
	muted := d.muted
	silenceMs := d.app.cfg.SilenceMs
	minSpeechMs := d.app.cfg.MinSpeechMs
	vadThresh := float64(d.app.cfg.VADThreshold)
	d.mu.Unlock()

	if muted || state == StateSending {
		return
	}

	rms := calcRMS(pcm)
	// Tatsächliche Frame-Dauer aus Byte-Länge berechnen (16-bit = 2 Bytes/Sample, mono)
	frameDurationMs := len(pcm) / 2 * 1000 / vadSampleRate

	if d.OnRMSLevel != nil {
		d.OnRMSLevel(rms, frameDurationMs)
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	if rms > vadThresh {
		d.inSpeech = true
		d.silenceMs = 0
		d.speechMs += frameDurationMs
		d.speechBuf = append(d.speechBuf, pcm...)
	} else {
		if d.inSpeech {
			d.silenceMs += frameDurationMs
			d.speechBuf = append(d.speechBuf, pcm...)

			if d.silenceMs >= silenceMs {
				if d.speechMs >= minSpeechMs {
					buf := make([]byte, len(d.speechBuf))
					copy(buf, d.speechBuf)
					sm := d.speechMs
					curState := d.state
					go d.handleUtterance(buf, sm, curState)
				}
				d.speechBuf = nil
				d.silenceMs = 0
				d.speechMs = 0
				d.inSpeech = false
			}
		}
	}
}

// handleUtterance verarbeitet eine abgeschlossene Äußerung.
func (d *DialogController) handleUtterance(pcm []byte, durationMs int, state DialogState) {
	log.Printf("[dialog] Äußerung: state=%v, %dms, %d bytes", state, durationMs, len(pcm))

	header := BuildWAVHeader(len(pcm))
	wav := append(header, pcm...)
	b64 := encodeBase64(wav)

	if state == StateWaitWakeWord {
		// Wake-Word-Prüfung: Avatar blau = "habe etwas gehört, prüfe…"
		d.app.avatar.SetMode(ModeChecking)
		d.ws.SendWakeWordCheck(b64, d.app.cfg.WakeWord)
		return
	}

	// Normale Spracheingabe
	d.app.avatar.SetMode(ModeIdle)
	if d.app.cfg.AutoSendVoice {
		// AutoSend: Backend transkribiert + startet Agent direkt.
		// User-Nachricht erscheint erst wenn voice_transcript zurückkommt (echter Text).
		d.app.chat.SetStatus("🎤 Transkribiere…")
		d.ws.SendTask("[Voice]\n<audio>" + b64 + "</audio>")
	} else {
		// Manuell bestätigen: nur transkribieren, Ergebnis landet im Eingabefeld.
		d.app.chat.SetStatus("🎤 Transkribiere…")
		d.ws.SendTranscribeOnly(b64)
	}

	d.mu.Lock()
	d.state = StateSending
	d.mu.Unlock()

	if d.StopAfterFirstUtterance {
		go func() {
			d.Stop()
			if d.OnStop != nil {
				d.OnStop()
			}
		}()
	}
}

// ── Hilfsfunktionen ───────────────────────────────────────────────────────────

func calcRMS(pcm []byte) float64 {
	if len(pcm) < 2 {
		return 0
	}
	var sum float64
	n := len(pcm) / 2
	for i := 0; i < n; i++ {
		sample := int16(binary.LittleEndian.Uint16(pcm[i*2 : i*2+2]))
		sum += float64(sample) * float64(sample)
	}
	return math.Sqrt(sum / float64(n))
}

func formatDuration(ms int) string {
	if ms < 1000 {
		return "< 1s"
	}
	return time.Duration(ms * int(time.Millisecond)).Round(time.Second).String()
}

func encodeBase64(data []byte) string {
	const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	result := make([]byte, 0, (len(data)+2)/3*4)
	for i := 0; i < len(data); i += 3 {
		b0 := data[i]
		result = append(result, chars[b0>>2])
		if i+1 < len(data) {
			b1 := data[i+1]
			result = append(result, chars[((b0&3)<<4)|(b1>>4)])
			if i+2 < len(data) {
				b2 := data[i+2]
				result = append(result, chars[((b1&0xf)<<2)|(b2>>6)])
				result = append(result, chars[b2&0x3f])
			} else {
				result = append(result, chars[(b1&0xf)<<2], '=')
			}
		} else {
			result = append(result, chars[(b0&3)<<4], '=', '=')
		}
	}
	return string(result)
}

// containsWakeWord prüft ob der Transkript das Wake-Word enthält.
func containsWakeWord(transcript, wakeWord string) bool {
	return strings.Contains(
		strings.ToLower(strings.TrimSpace(transcript)),
		strings.ToLower(strings.TrimSpace(wakeWord)),
	)
}
