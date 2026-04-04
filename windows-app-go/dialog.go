package main

import (
	"encoding/binary"
	"log"
	"math"
	"sync"
	"time"
)

// ── VAD-Konstanten (Voice Activity Detection) ─────────────────────────────────

const (
	vadSampleRate      = 16000 // Hz
	vadFrameSize       = 160   // Samples pro Frame (~10ms)
	vadSilenceRMS      = 400   // Schwellwert für Stille (0-32767)
	vadSilenceDuration = 900   // ms Stille → Äußerung abgeschlossen
	vadMinSpeechMs     = 200   // Mindest-Sprechzeit damit gesendet wird
)

// ── Dialog-Controller ─────────────────────────────────────────────────────────

type DialogController struct {
	mu       sync.Mutex
	active   bool // Dialogmodus läuft
	muted    bool // Mic stumm (während Jarvis spricht)

	speechBuf   []byte // Gesammeltes PCM der aktuellen Äußerung
	silenceMs   int    // Aufgesammelte Stille-Millisekunden
	speechMs    int    // Aufgesammelte Sprech-Millisekunden
	inSpeech    bool   // Gerade Sprache erkannt

	audio   *AudioManager
	ws      *WSClient
	app     *JarvisApp
}

func NewDialogController(audio *AudioManager, ws *WSClient, app *JarvisApp) *DialogController {
	return &DialogController{audio: audio, ws: ws, app: app}
}

// Start aktiviert den Dialogmodus (Mikrofon + VAD).
func (d *DialogController) Start() {
	d.mu.Lock()
	if d.active {
		d.mu.Unlock()
		return
	}
	d.active = true
	d.mu.Unlock()

	d.audio.OnMicData = d.processMicFrame
	if err := d.audio.StartRecording(); err != nil {
		log.Printf("[dialog] Mic-Start Fehler: %v", err)
	}
	log.Println("[dialog] Dialogmodus gestartet")
}

// Stop beendet den Dialogmodus.
func (d *DialogController) Stop() {
	d.mu.Lock()
	d.active = false
	d.mu.Unlock()
	d.audio.StopRecording()
	log.Println("[dialog] Dialogmodus beendet")
}

// MuteWhileSpeaking stummt das Mikrofon während Jarvis spricht (verhindert Feedback).
func (d *DialogController) MuteWhileSpeaking(muted bool) {
	d.mu.Lock()
	d.muted = muted
	d.mu.Unlock()
}

// processMicFrame verarbeitet einen eingehenden PCM-Frame (VAD).
func (d *DialogController) processMicFrame(pcm []byte) {
	d.mu.Lock()
	if !d.active || d.muted {
		d.mu.Unlock()
		return
	}
	d.mu.Unlock()

	rms := calcRMS(pcm)
	frameDurationMs := (vadFrameSize * 1000) / vadSampleRate

	d.mu.Lock()
	defer d.mu.Unlock()

	if rms > vadSilenceRMS {
		// Sprache erkannt
		d.inSpeech = true
		d.silenceMs = 0
		d.speechMs += frameDurationMs
		d.speechBuf = append(d.speechBuf, pcm...)
	} else {
		// Stille
		if d.inSpeech {
			d.silenceMs += frameDurationMs
			d.speechBuf = append(d.speechBuf, pcm...) // Stille mit aufnehmen

			if d.silenceMs >= vadSilenceDuration {
				// Äußerung abgeschlossen → senden
				if d.speechMs >= vadMinSpeechMs {
					buf := make([]byte, len(d.speechBuf))
					copy(buf, d.speechBuf)
					speechMs := d.speechMs
					go d.sendVoice(buf, speechMs)
				}
				d.speechBuf = nil
				d.silenceMs = 0
				d.speechMs = 0
				d.inSpeech = false
			}
		}
	}
}

// sendVoice sendet die aufgenommene Äußerung an den Server.
func (d *DialogController) sendVoice(pcm []byte, durationMs int) {
	log.Printf("[dialog] Sende Sprache: %dms, %d bytes PCM", durationMs, len(pcm))

	// Avatar: Hören → Denken (Idle) während Upload
	d.app.avatar.SetMode(ModeIdle)

	// WAV-Header voranstellen
	header := BuildWAVHeader(len(pcm))
	wav := append(header, pcm...)

	// Als Base64 senden
	b64 := encodeBase64(wav)
	d.ws.SendTask("[Voice]\n<audio>" + b64 + "</audio>")

	// Chat-Anzeige
	d.app.chat.AddMessage(RoleUser, "🎤 Spracheingabe ("+formatDuration(durationMs)+")")
}

// ── Hilfsfunktionen ───────────────────────────────────────────────────────────

// calcRMS berechnet den RMS-Pegel eines PCM-int16-Frames.
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
