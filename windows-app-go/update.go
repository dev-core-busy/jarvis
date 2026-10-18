package main

import (
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"jarvis-windows/hilfen"
)

type WindowsVersionInfo struct {
	VersionCode int    `json:"versionCode"`
	VersionName string `json:"versionName"`
	DownloadURL string `json:"downloadUrl"`
	// SHA256 der EXE (Hex). Code-Review 2026-10-18: der Server liefert das Feld
	// noch nicht; fehlt es, wird nur Kopf und Groesse geprueft und ein Hinweis
	// protokolliert.
	SHA256 string `json:"sha256,omitempty"`
}

// currentBuildNum parst die Build-Nummer aus AppVersion ("0.836" → 836).
func currentBuildNum() int {
	parts := strings.Split(AppVersion, ".")
	if len(parts) < 2 {
		return 0
	}
	n, _ := strconv.Atoi(parts[len(parts)-1])
	return n
}

// httpClient gibt einen HTTP-Client mit 60s Timeout zurück.
func httpClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: false},
		},
	}
}

// CheckForUpdate prüft version_windows.json auf jarvis-ai.info.
// Gibt nil zurück wenn kein Update verfügbar oder bei Fehler.
func CheckForUpdate() *WindowsVersionInfo {
	url := fmt.Sprintf("https://jarvis-ai.info/downloads/version_windows.json?t=%d", time.Now().UnixMilli())
	resp, err := httpClient(10 * time.Second).Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	// Code-Review 2026-10-18: nur eine 200-Antwort zaehlt, und die kleine
	// JSON-Datei wird auf 64 KB gedeckelt gelesen.
	if resp.StatusCode != http.StatusOK {
		return nil
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if err != nil {
		return nil
	}
	var info WindowsVersionInfo
	if err := json.Unmarshal(body, &info); err != nil {
		return nil
	}
	if info.VersionCode > currentBuildNum() {
		return &info
	}
	return nil
}

// PerformUpdate lädt die neue EXE herunter, ersetzt die aktuelle per Batch-Script
// und startet die Anwendung neu. progressFn wird mit 0.0–1.0 aufgerufen.
// Bei Fehler wird die Fehlermeldung zurückgegeben.
func PerformUpdate(info *WindowsVersionInfo, progressFn func(float64)) error {
	// Download-URL bestimmen
	downloadURL := info.DownloadURL
	if downloadURL == "" {
		downloadURL = "https://jarvis-ai.info/downloads/jarvis.exe"
	}

	// Pfad der laufenden EXE
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("EXE-Pfad nicht ermittelbar: %w", err)
	}
	exePath, err = filepath.EvalSymlinks(exePath)
	if err != nil {
		return fmt.Errorf("EXE-Symlink nicht auflösbar: %w", err)
	}
	exeDir := filepath.Dir(exePath)

	// Neue EXE in dasselbe Verzeichnis herunterladen
	newExePath := filepath.Join(exeDir, "jarvis_update.exe")
	if err := downloadFile(downloadURL, newExePath, info.SHA256, progressFn); err != nil {
		_ = os.Remove(newExePath)
		return fmt.Errorf("Download fehlgeschlagen: %w", err)
	}

	// Batch-Script schreiben: wartet auf das Ende der App, tauscht die EXE und
	// startet sie neu. Code-Review 2026-10-18: Aufbau und Fehlerwege (errorlevel
	// nach jedem move, Zurueckbenennen statt Loeschen, "%" im Pfad) stehen in
	// hilfen.UpdaterBatch, dort auch getestet.
	batchPath := filepath.Join(exeDir, "jarvis_updater.bat")
	oldExePath := filepath.Join(exeDir, "jarvis_old.exe")
	batchContent := hilfen.UpdaterBatch(exePath, oldExePath, newExePath, filepath.Base(exePath))

	if err := os.WriteFile(batchPath, []byte(batchContent), 0755); err != nil {
		_ = os.Remove(newExePath)
		return fmt.Errorf("Updater-Script konnte nicht geschrieben werden: %w", err)
	}

	// Batch-Script starten (unsichtbar, unabhängig vom aktuellen Prozess)
	cmd := exec.Command("cmd", "/c", "start", "", "/b", batchPath)
	cmd.Dir = exeDir
	if err := cmd.Start(); err != nil {
		_ = os.Remove(newExePath)
		_ = os.Remove(batchPath)
		return fmt.Errorf("Updater-Script konnte nicht gestartet werden: %w", err)
	}

	// App beenden – Batch übernimmt
	go func() {
		time.Sleep(500 * time.Millisecond)
		FlushHistory() // os.Exit laeuft an jedem defer vorbei
		os.Exit(0)
	}()
	return nil
}

// downloadFile lädt die Update-EXE herunter und ruft progressFn mit 0.0–1.0 auf.
//
// Code-Review 2026-10-18: vorher wurde jede Antwort ungeprueft gespeichert und
// danach eingewechselt (auch eine 404-Seite). Jetzt: nur https://, nur Status
// 200, Download auf hilfen.MaxEXEGroesse gedeckelt, danach Mindestgroesse,
// PE-Kopf "MZ" und – falls geliefert – SHA-256 geprueft. Erst wenn alles
// stimmt, liegt die Datei fuer den Tausch bereit; sonst entfernt sie der Aufrufer.
func downloadFile(url, dest, sollHash string, progressFn func(float64)) error {
	if err := hilfen.PruefeDownloadURL(url); err != nil {
		return err
	}
	resp, err := httpClient(5 * time.Minute).Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("Server antwortet HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > hilfen.MaxEXEGroesse {
		return fmt.Errorf("Download zu gross (%d Bytes)", resp.ContentLength)
	}

	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()

	pruefer := hilfen.NeuerExePruefer()
	ziel := io.MultiWriter(f, pruefer)
	// Ein Byte mehr als erlaubt lesen: so faellt eine zu grosse Antwort in
	// pruefer.Pruefe auf, statt still abgeschnitten zu werden.
	body := io.LimitReader(resp.Body, hilfen.MaxEXEGroesse+1)
	total := resp.ContentLength
	var downloaded int64
	buf := make([]byte, 32*1024)
	for {
		n, err := body.Read(buf)
		if n > 0 {
			if _, werr := ziel.Write(buf[:n]); werr != nil {
				return werr
			}
			downloaded += int64(n)
			if total > 0 && progressFn != nil {
				progressFn(float64(downloaded) / float64(total))
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
	}
	if total > 0 && downloaded != total {
		return fmt.Errorf("Download unvollstaendig (%d von %d Bytes)", downloaded, total)
	}
	if err := f.Sync(); err != nil {
		return err
	}
	if err := pruefer.Pruefe(sollHash); err != nil {
		if !errors.Is(err, hilfen.ErrKeinHash) {
			return err
		}
		log.Printf("[update] Hinweis: %v", err)
	}
	if progressFn != nil {
		progressFn(1.0)
	}
	return nil
}
