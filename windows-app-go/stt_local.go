package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

// exeDir gibt das Verzeichnis von jarvis.exe zurück.
func exeDir() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(exe)
}

// sttDir gibt den Unterordner 'speech-to-text' neben jarvis.exe zurück.
func sttDir() string {
	return filepath.Join(exeDir(), "speech-to-text")
}

// findWhisper sucht whisper-cli.exe im Unterordner speech-to-text.
func findWhisper() (binPath, modelPath string, ok bool) {
	dir := sttDir()
	for _, name := range []string{"whisper-cli.exe", "whisper.exe", "main.exe"} {
		p := filepath.Join(dir, name)
		if _, err := os.Stat(p); err == nil {
			binPath = p
			break
		}
	}
	if binPath == "" {
		return "", "", false
	}
	for _, name := range []string{
		"ggml-small.bin", "ggml-small-q5_1.bin", "ggml-small-q8_0.bin",
		"ggml-base.bin", "ggml-base-q5_1.bin",
		"ggml-tiny.bin", "ggml-tiny-q5_1.bin",
	} {
		p := filepath.Join(dir, name)
		if _, err := os.Stat(p); err == nil {
			modelPath = p
			break
		}
	}
	if modelPath == "" {
		return "", "", false
	}
	return binPath, modelPath, true
}

// ── Whisper-Server (Modell bleibt im RAM → schnell ab 2. Aufruf) ─────────────

const sttServerPort = 15748

var (
	sttServerMu    sync.Mutex
	sttServerCmd   *exec.Cmd
	sttServerReady bool
)

// StartWhisperServer startet whisper-server.exe im Hintergrund (falls vorhanden).
// Blockiert bis der Server bereit ist (max. 20s für Modell-Laden).
// Soll beim App-Start in einer Goroutine aufgerufen werden.
func StartWhisperServer() {
	addr := fmt.Sprintf("127.0.0.1:%d", sttServerPort)

	// Läuft der Server bereits (z.B. vom vorherigen App-Start)?
	if conn, err := net.DialTimeout("tcp", addr, time.Second); err == nil {
		conn.Close()
		sttServerMu.Lock()
		sttServerReady = true
		sttServerMu.Unlock()
		return
	}

	sttServerMu.Lock()
	if sttServerReady {
		sttServerMu.Unlock()
		return
	}
	sttServerMu.Unlock()

	serverBin := filepath.Join(sttDir(), "whisper-server.exe")
	if _, err := os.Stat(serverBin); os.IsNotExist(err) {
		return
	}
	_, modelPath, ok := findWhisper()
	if !ok {
		return
	}

	cmd := exec.Command(serverBin,
		"-m", modelPath,
		"--language", "de",
		"--host", "127.0.0.1",
		"--port", fmt.Sprintf("%d", sttServerPort),
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := cmd.Start(); err != nil {
		return
	}
	sttServerMu.Lock()
	sttServerCmd = cmd
	sttServerMu.Unlock()

	// Warten bis Port offen ist – kein Timeout, Modell kann lange laden
	go func() {
		for {
			if conn, err := net.DialTimeout("tcp", addr, time.Second); err == nil {
				conn.Close()
				sttServerMu.Lock()
				sttServerReady = true
				sttServerMu.Unlock()
				return
			}
			time.Sleep(500 * time.Millisecond)
		}
	}()
}

// StopWhisperServer beendet den Hintergrund-Server beim App-Exit.
func StopWhisperServer() {
	sttServerMu.Lock()
	defer sttServerMu.Unlock()
	if sttServerCmd != nil && sttServerCmd.Process != nil {
		_ = sttServerCmd.Process.Kill()
	}
	sttServerReady = false
}

func transcribeViaServer(wavData []byte) (string, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	fw, err := w.CreateFormFile("file", "audio.wav")
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(fw, bytes.NewReader(wavData)); err != nil {
		return "", err
	}
	_ = w.WriteField("language", "de")
	_ = w.WriteField("response_format", "json")
	w.Close()

	url := fmt.Sprintf("http://127.0.0.1:%d/inference", sttServerPort)
	client := &http.Client{Timeout: 6 * time.Second}
	resp, err := client.Post(url, w.FormDataContentType(), &buf) //nolint:gosec
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var result struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}
	return strings.TrimSpace(result.Text), nil
}

// ── Transkription ─────────────────────────────────────────────────────────────

// TranscribeLocalSafe ist der sichere Einstiegspunkt mit hartem 25s-Timeout.
// Auf Windows blockiert cmd.Output() dauerhaft wenn ein Prozess gekillt wird
// (bekannter Go-Bug: Pipes werden beim Kill nicht geschlossen).
// Die innere Goroutine kann hängen – der Aufrufer wird nach 25s trotzdem fortgesetzt.
var (
	sttLastMode   string
	sttLastModeMu sync.Mutex
)

func getSttLastMode() string {
	sttLastModeMu.Lock()
	defer sttLastModeMu.Unlock()
	return sttLastMode
}

func setSttLastMode(s string) {
	sttLastModeMu.Lock()
	sttLastMode = s
	sttLastModeMu.Unlock()
}

func TranscribeLocalSafe(wavData []byte) (string, error) {
	type result struct {
		text string
		err  error
	}
	ch := make(chan result, 1)
	go func() {
		t, e := TranscribeLocal(wavData)
		select {
		case ch <- result{t, e}:
		default:
		}
	}()
	select {
	case r := <-ch:
		return r.text, r.err
	case <-time.After(25 * time.Second):
		setSttLastMode("hard-timeout (25s)")
		return "", fmt.Errorf("STT Timeout nach 25s – whisper hängt")
	}
}

func TranscribeLocal(wavData []byte) (string, error) {
	sttServerMu.Lock()
	ready := sttServerReady
	sttServerMu.Unlock()

	// Fallback-Check: Port direkt testen falls sttServerReady noch nicht gesetzt wurde
	if !ready {
		addr := fmt.Sprintf("127.0.0.1:%d", sttServerPort)
		if conn, err := net.DialTimeout("tcp", addr, 500*time.Millisecond); err == nil {
			conn.Close()
			sttServerMu.Lock()
			sttServerReady = true
			sttServerMu.Unlock()
			ready = true
			setSttLastMode("server (live-check)")
		}
	}

	if ready {
		t0 := time.Now()
		setSttLastMode("server")
		text, err := transcribeViaServer(wavData)
		elapsed := time.Since(t0).Round(time.Millisecond)
		if err == nil {
			setSttLastMode(fmt.Sprintf("server (%dms)", elapsed.Milliseconds()))
			return text, nil
		}
		setSttLastMode(fmt.Sprintf("server-fehler (%dms): %v", elapsed.Milliseconds(), err))
		// Server-Fehler → CLI-Fallback
	}

	if bin, model, ok := findWhisper(); ok {
		t0 := time.Now()
		text, err := transcribeWhisperCLI(wavData, bin, model)
		elapsed := time.Since(t0).Round(time.Millisecond)
		if err == nil {
			setSttLastMode(fmt.Sprintf("cli (%dms)", elapsed.Milliseconds()))
		} else {
			setSttLastMode(fmt.Sprintf("cli-fehler (%dms): %v", elapsed.Milliseconds(), err))
		}
		return text, err
	}

	t0 := time.Now()
	text, err := transcribeSAPI(wavData)
	elapsed := time.Since(t0).Round(time.Millisecond)
	if err == nil {
		setSttLastMode(fmt.Sprintf("sapi (%dms)", elapsed.Milliseconds()))
	} else {
		setSttLastMode(fmt.Sprintf("sapi-fehler (%dms): %v", elapsed.Milliseconds(), err))
	}
	return text, err
}

func transcribeWhisperCLI(wavData []byte, binPath, modelPath string) (string, error) {
	f, err := os.CreateTemp("", "jarvis-stt-*.wav")
	if err != nil {
		return "", err
	}
	tmpPath := f.Name()
	defer os.Remove(tmpPath)
	if _, err := f.Write(wavData); err != nil {
		f.Close()
		return "", err
	}
	f.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binPath,
		"-m", modelPath,
		"-l", "de",
		"--no-timestamps",
		"-f", tmpPath,
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	// StdoutPipe statt cmd.Output() – vermeidet Windows-Pipe-Hang nach Kill
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	if err := cmd.Start(); err != nil {
		return "", err
	}
	outBytes, _ := io.ReadAll(stdout)
	_ = cmd.Wait()
	if ctx.Err() != nil {
		return "", fmt.Errorf("whisper-cli Timeout (>20s)")
	}
	return strings.TrimSpace(string(outBytes)), nil
}

func transcribeSAPI(wavData []byte) (string, error) {
	f, err := os.CreateTemp("", "jarvis-stt-*.wav")
	if err != nil {
		return "", err
	}
	tmpPath := f.Name()
	defer os.Remove(tmpPath)
	if _, err := f.Write(wavData); err != nil {
		f.Close()
		return "", err
	}
	f.Close()

	winPath := strings.ReplaceAll(tmpPath, "/", "\\")
	script := `
Add-Type -AssemblyName System.Speech
$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$rec.SetInputToWaveFile('` + winPath + `')
$g = New-Object System.Speech.Recognition.DictationGrammar
$rec.LoadGrammar($g)
$rec.BabbleTimeout = [TimeSpan]::FromSeconds(0)
$rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(1)
$rec.EndSilenceTimeout = [TimeSpan]::FromSeconds(0)
try {
    $r = $rec.Recognize()
    if ($r -ne $null) { Write-Output $r.Text }
} catch {}
$rec.Dispose()
`
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	// StdoutPipe statt cmd.Output() – vermeidet Windows-Pipe-Hang nach Kill
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", err
	}
	if err := cmd.Start(); err != nil {
		return "", err
	}
	outBytes, _ := io.ReadAll(stdout)
	_ = cmd.Wait()
	if ctx.Err() != nil {
		return "", fmt.Errorf("SAPI Timeout (>10s)")
	}
	return strings.TrimSpace(string(outBytes)), nil
}
