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
)

// ── Dialog-Zustands-Maschine ──────────────────────────────────────────────────

type DialogState int

const (
	StateWaitWakeWord DialogState = iota // Wartet auf Wake-Word
	StateListening                        // Aktiv: Aufnahme nach Wake-Word
	StateSending                          // Sendet gerade (Mic stumm)
)

// utteranceData enthält eine abgeschlossene Äußerung aus der VAD.
type utteranceData struct {
	pcm       []byte
	durationMs int
	state     DialogState
}

// ── Dialog-Controller ─────────────────────────────────────────────────────────

type DialogController struct {
	mu       sync.Mutex
	doneOnce sync.Once
	state    DialogState
	muted    bool

	speechBuf []byte
	silenceMs int
	speechMs  int
	inSpeech  bool

	audio *AudioManager
	ws    *WSClient
	app   *JarvisApp

	// Äußerungen werden über diesen Channel kommuniziert (nie direkt verarbeitet)
	utteranceCh chan utteranceData
	// doneCh signalisiert Watcher-Goroutinen dass der Controller beendet wird
	doneCh chan struct{}

	OnRMSLevel func(rms float64, frameMs int)
}

func NewDialogController(audio *AudioManager, ws *WSClient, app *JarvisApp) *DialogController {
	return &DialogController{
		audio:       audio,
		ws:          ws,
		app:         app,
		utteranceCh: make(chan utteranceData, 4),
		doneCh:      make(chan struct{}),
	}
}

// Start aktiviert den Dialogmodus (mit Wake-Word falls konfiguriert).
func (d *DialogController) Start() error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.app.cfg.WakeWordEnabled {
		d.state = StateWaitWakeWord
	} else {
		d.state = StateListening
	}
	return d.startLocked()
}

// StartListening aktiviert direkt das Zuhören – kein Wake-Word-Check.
// Wird für manuell ausgelöstes Diktat (Mikrofon-Button) verwendet.
func (d *DialogController) StartListening() error {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.state = StateListening
	return d.startLocked()
}

func (d *DialogController) startLocked() error {
	d.audio.SetOnMicData(d.processMicFrame)
	if !d.audio.IsRecording() {
		if err := d.audio.StartRecording(); err != nil {
			log.Printf("[dialog] Mic-Start Fehler: %v", err)
			return err
		}
	}
	log.Printf("[dialog] Gestartet (WakeWord=%v)", d.app.cfg.WakeWordEnabled)
	return nil
}

// Stop beendet den Dialogmodus.
func (d *DialogController) Stop() {
	d.mu.Lock()
	d.state = StateSending
	d.mu.Unlock()
	d.doneOnce.Do(func() { close(d.doneCh) })
	d.audio.StopRecording()
	log.Println("[dialog] Beendet")
}

// FlushAndStop: gepufferte Sprache in Channel senden, dann stoppen.
func (d *DialogController) FlushAndStop() {
	d.doneOnce.Do(func() { close(d.doneCh) })
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
		select {
		case d.utteranceCh <- utteranceData{buf, sm, state}:
		default:
		}
	}
	log.Println("[dialog] Beendet (flush)")
}

// MuteWhileSpeaking stummt das Mikrofon während Jarvis spricht.
func (d *DialogController) MuteWhileSpeaking(muted bool) {
	d.mu.Lock()
	d.muted = muted
	if !muted && d.app.cfg.WakeWordEnabled {
		d.state = StateWaitWakeWord
		d.speechBuf = nil
		d.silenceMs = 0
		d.speechMs = 0
		d.inSpeech = false
	}
	d.mu.Unlock()
}

// OnWakeWordDetected wird aufgerufen wenn das Backend Wake-Word bestätigt.
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
	log.Println("[dialog] Wake-Word erkannt")
}

// processMicFrame verarbeitet einen PCM-Frame (VAD).
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
	// Tatsächliche Frame-Dauer aus Byte-Länge (16-bit mono = 2 Bytes/Sample)
	frameDurationMs := len(pcm) / 2 * 1000 / vadSampleRate
	if frameDurationMs == 0 {
		frameDurationMs = 10
	}

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
	} else if d.inSpeech {
		d.silenceMs += frameDurationMs
		d.speechBuf = append(d.speechBuf, pcm...)

		if d.silenceMs >= silenceMs {
			if d.speechMs >= minSpeechMs {
				buf := make([]byte, len(d.speechBuf))
				copy(buf, d.speechBuf)
				utt := utteranceData{buf, d.speechMs, d.state}
				// Nicht-blockierend senden – Audio-Callback darf nie blockieren
				select {
				case d.utteranceCh <- utt:
					log.Printf("[dialog] Äußerung erkannt: %dms, %d bytes", d.speechMs, len(buf))
				default:
					log.Println("[dialog] utteranceCh voll – Äußerung verworfen")
				}
			}
			d.speechBuf = nil
			d.silenceMs = 0
			d.speechMs = 0
			d.inSpeech = false
		}
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

func containsWakeWord(transcript, wakeWord string) bool {
	return strings.Contains(
		strings.ToLower(strings.TrimSpace(transcript)),
		strings.ToLower(strings.TrimSpace(wakeWord)),
	)
}
