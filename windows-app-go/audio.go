package main

import (
	"bytes"
	"encoding/binary"
	"log"
	"sync"

	"github.com/gen2brain/malgo"
)

// ── Audio-Manager ─────────────────────────────────────────────────────────────

type AudioManager struct {
	mu      sync.Mutex
	ctx     *malgo.AllocatedContext
	playDev *malgo.Device
	recDev  *malgo.Device

	// Konfigurierte Geräte-IDs (leer = Standard)
	SpeakerID string
	MicID     string

	// Callback wenn Mikrofon-Daten verfügbar sind
	OnMicData func(pcm []byte)

	// Interne Playback-Queue
	playQueue chan []byte
	stopCh    chan struct{}
}

func NewAudioManager() (*AudioManager, error) {
	ctx, err := malgo.InitContext(nil, malgo.ContextConfig{}, func(msg string) {
		log.Printf("[audio] %s", msg)
	})
	if err != nil {
		return nil, err
	}
	am := &AudioManager{
		ctx:       ctx,
		playQueue: make(chan []byte, 32),
		stopCh:    make(chan struct{}),
	}
	return am, nil
}

func (am *AudioManager) Close() {
	close(am.stopCh)
	am.mu.Lock()
	defer am.mu.Unlock()
	if am.playDev != nil {
		am.playDev.Uninit()
	}
	if am.recDev != nil {
		am.recDev.Uninit()
	}
	_ = am.ctx.Uninit()
	am.ctx.Free()
}

// ── Geräte-Auflistung ─────────────────────────────────────────────────────────

type AudioDevice struct {
	ID   string
	Name string
}

func (am *AudioManager) ListSpeakers() []AudioDevice {
	return am.listDevices(malgo.Playback)
}

func (am *AudioManager) ListMics() []AudioDevice {
	return am.listDevices(malgo.Capture)
}

func (am *AudioManager) listDevices(dtype malgo.DeviceType) []AudioDevice {
	infos, err := am.ctx.Devices(dtype)
	if err != nil {
		return nil
	}
	devs := make([]AudioDevice, 0, len(infos)+1)
	devs = append(devs, AudioDevice{ID: "", Name: "Standard"})
	for _, info := range infos {
		devs = append(devs, AudioDevice{
			ID:   info.ID.String(),
			Name: info.Name(),
		})
	}
	return devs
}

// ── Playback: TTS-Audio abspielen ─────────────────────────────────────────────

// PlayPCM spielt rohe PCM-Daten (16-bit signed, 44100Hz, Stereo) ab.
func (am *AudioManager) PlayPCM(data []byte) {
	select {
	case am.playQueue <- data:
	default:
		// Queue voll – verwerfen
	}
}

// PlayWAV parst einen WAV-Header und spielt den PCM-Teil ab.
func (am *AudioManager) PlayWAV(data []byte) {
	pcm := extractWAVData(data)
	if len(pcm) > 0 {
		am.PlayPCM(pcm)
	}
}

// StartPlayback startet den Playback-Thread.
func (am *AudioManager) StartPlayback() error {
	cfg := malgo.DefaultDeviceConfig(malgo.Playback)
	cfg.Playback.Format = malgo.FormatS16
	cfg.Playback.Channels = 2
	cfg.SampleRate = 44100

	var buf []byte
	var bufMu sync.Mutex

	// Playback-Callback: liefert PCM-Frames
	callbacks := malgo.DeviceCallbacks{
		Data: func(_, pOutput []byte, _ uint32) {
			bufMu.Lock()
			defer bufMu.Unlock()

			needed := len(pOutput)
			if len(buf) >= needed {
				copy(pOutput, buf[:needed])
				buf = buf[needed:]
			} else {
				copy(pOutput, buf)
				for i := len(buf); i < needed; i++ {
					pOutput[i] = 0
				}
				buf = buf[:0]
			}
		},
	}

	dev, err := malgo.InitDevice(am.ctx.Context, cfg, callbacks)
	if err != nil {
		return err
	}
	am.mu.Lock()
	am.playDev = dev
	am.mu.Unlock()

	if err := dev.Start(); err != nil {
		return err
	}

	// Feeder-Goroutine: schiebt Daten aus der Queue in den Buffer
	go func() {
		for {
			select {
			case <-am.stopCh:
				return
			case data := <-am.playQueue:
				bufMu.Lock()
				buf = append(buf, data...)
				bufMu.Unlock()
			}
		}
	}()
	return nil
}

// ── Mikrofon-Aufnahme ─────────────────────────────────────────────────────────

func (am *AudioManager) StartRecording() error {
	cfg := malgo.DefaultDeviceConfig(malgo.Capture)
	cfg.Capture.Format = malgo.FormatS16
	cfg.Capture.Channels = 1
	cfg.SampleRate = 16000 // Whisper bevorzugt 16kHz

	callbacks := malgo.DeviceCallbacks{
		Data: func(pInput, _ []byte, _ uint32) {
			if am.OnMicData != nil && len(pInput) > 0 {
				cp := make([]byte, len(pInput))
				copy(cp, pInput)
				am.OnMicData(cp)
			}
		},
	}

	dev, err := malgo.InitDevice(am.ctx.Context, cfg, callbacks)
	if err != nil {
		return err
	}
	am.mu.Lock()
	am.recDev = dev
	am.mu.Unlock()
	return dev.Start()
}

func (am *AudioManager) StopRecording() {
	am.mu.Lock()
	dev := am.recDev
	am.recDev = nil
	am.mu.Unlock()
	if dev != nil {
		dev.Uninit()
	}
}

// ── WAV-Hilfsfunktionen ───────────────────────────────────────────────────────

// extractWAVData extrahiert den PCM-Datenteil aus einem WAV-Byte-Slice.
func extractWAVData(data []byte) []byte {
	if len(data) < 44 {
		return data // Kein Header – direkt als PCM behandeln
	}
	// WAV-Signatur prüfen
	if string(data[0:4]) != "RIFF" || string(data[8:12]) != "WAVE" {
		return data
	}
	// "data"-Chunk suchen
	for i := 12; i < len(data)-8; i++ {
		if string(data[i:i+4]) == "data" {
			chunkSize := int(binary.LittleEndian.Uint32(data[i+4 : i+8]))
			start := i + 8
			end := start + chunkSize
			if end > len(data) {
				end = len(data)
			}
			return data[start:end]
		}
	}
	return data
}

// BuildWAVHeader erzeugt einen WAV-Header für PCM-Daten (16-bit, mono, 16kHz).
func BuildWAVHeader(pcmLen int) []byte {
	buf := new(bytes.Buffer)
	sampleRate := uint32(16000)
	numChannels := uint16(1)
	bitsPerSample := uint16(16)
	byteRate := sampleRate * uint32(numChannels) * uint32(bitsPerSample/8)
	blockAlign := numChannels * bitsPerSample / 8
	dataLen := uint32(pcmLen)
	chunkSize := 36 + dataLen

	buf.WriteString("RIFF")
	_ = binary.Write(buf, binary.LittleEndian, chunkSize)
	buf.WriteString("WAVE")
	buf.WriteString("fmt ")
	_ = binary.Write(buf, binary.LittleEndian, uint32(16))     // Subchunk1Size
	_ = binary.Write(buf, binary.LittleEndian, uint16(1))      // PCM
	_ = binary.Write(buf, binary.LittleEndian, numChannels)
	_ = binary.Write(buf, binary.LittleEndian, sampleRate)
	_ = binary.Write(buf, binary.LittleEndian, byteRate)
	_ = binary.Write(buf, binary.LittleEndian, blockAlign)
	_ = binary.Write(buf, binary.LittleEndian, bitsPerSample)
	buf.WriteString("data")
	_ = binary.Write(buf, binary.LittleEndian, dataLen)
	return buf.Bytes()
}
