package main

// Bild-Anzeige in Chat-Bubbles: erkennt von Jarvis generierte/gesuchte Bilder
// (/api/generated/<uuid>.<ext>) in der Antwort und laedt sie inline als Bild.

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/theme"

	"jarvis-windows/hilfen"
	"jarvis-windows/tlsvertrauen"
)

// imgServerBase ist die HTTPS-Basis (z.B. "https://jarvis.firma.local"), gesetzt aus der ServerURL.
//
// Code-Review 2026-10-18: nur unter imgMu lesen/schreiben – SetImageServer
// laeuft im UI-Thread (Einstellungen), buildJarvisBody beim Rendern.
var (
	imgMu         sync.RWMutex
	imgServerBase string
)

// imgToken liefert das AKTUELLE Token (Funktion statt Wert: der Einstellungs-
// dialog kann es zur Laufzeit aendern). Seit 2026-10-15 verlangt der Server fuer
// /api/generated/ eine Anmeldung; vorher war die Adresse ohne Anmeldung abrufbar.
var imgToken = func() string { return "" }

// SetImageAuth setzt die Quelle des Tokens fuer den Bildabruf.
func SetImageAuth(f func() string) {
	if f != nil {
		imgMu.Lock()
		imgToken = f
		imgMu.Unlock()
	}
}

// SetImageServer leitet die HTTP(S)-Basis aus der konfigurierten ServerURL ab.
// Code-Review 2026-10-18: gemeinsamer Helfer hilfen.HTTPBasis statt eigener
// Schema-Abstreifung (dieselbe Regel wie fuer Issues, TTS und Sperr-Info).
func SetImageServer(serverURL string) {
	if b := hilfen.HTTPBasis(serverURL); b != "" {
		imgMu.Lock()
		imgServerBase = b
		imgMu.Unlock()
	}
}

func imgBasis() string {
	imgMu.RLock()
	defer imgMu.RUnlock()
	return imgServerBase
}

func imgTokenJetzt() string {
	imgMu.RLock()
	f := imgToken
	imgMu.RUnlock()
	return f()
}

// Grenzen fuer den Bildabruf.
const (
	// imgMaxBytes deckelt ein einzelnes Bild (io.LimitReader).
	imgMaxBytes = 20 << 20
	// imgCacheMax: so viele Bytes behaelt der Cache insgesamt.
	imgCacheMax = 64 << 20
)

// imgClients haelt EINEN http.Client je Server-Host.
//
// Code-Review 2026-10-18: vorher entstand pro Bild ein neuer http.Transport –
// jede Anzeige baute eine frische TLS-Verbindung auf, und die alten Transporte
// hielten ihre Leerlauf-Verbindungen offen, bis der GC sie fand. Der Pin des
// Zertifikats wird in VerifyConnection bei jeder Verbindung neu gelesen, ein
// spaeter bestaetigtes Zertifikat wirkt also auch mit dem gemeinsamen Client.
var (
	imgClientMu sync.Mutex
	imgClients  = map[string]*http.Client{}
)

func imgClientFuer(adresse string) *http.Client {
	host := adresse
	if u, err := url.Parse(adresse); err == nil && u.Host != "" {
		host = strings.ToLower(u.Scheme + "://" + u.Host)
	}
	imgClientMu.Lock()
	defer imgClientMu.Unlock()
	if c, ok := imgClients[host]; ok {
		return c
	}
	c := &http.Client{
		Timeout:   20 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsvertrauen.ServerTLS(adresse)},
	}
	imgClients[host] = c
	return c
}

// imgCache: einfacher Bild-Cache (Adresse -> Bytes), begrenzt auf imgCacheMax.
// Code-Review 2026-10-18: der Chat baut Bubbles bei jedem Neuaufbau (Bearbeiten,
// Loeschen, Fensterwechsel) neu – vorher wurde jedes Bild dabei neu geladen.
// Verdraengt wird in Einfuegereihenfolge (die Bild-Adressen sind eindeutige
// UUIDs, ein Bild aendert sich nie).
var (
	imgCacheMu    sync.Mutex
	imgCache      = map[string][]byte{}
	imgCacheFolge []string
	imgCacheSumme int
)

func imgCacheHole(adresse string) ([]byte, bool) {
	imgCacheMu.Lock()
	defer imgCacheMu.Unlock()
	b, ok := imgCache[adresse]
	return b, ok
}

func imgCacheLege(adresse string, b []byte) {
	if len(b) > imgCacheMax {
		return
	}
	imgCacheMu.Lock()
	defer imgCacheMu.Unlock()
	if _, ok := imgCache[adresse]; ok {
		return
	}
	for imgCacheSumme+len(b) > imgCacheMax && len(imgCacheFolge) > 0 {
		alt := imgCacheFolge[0]
		imgCacheFolge = imgCacheFolge[1:]
		imgCacheSumme -= len(imgCache[alt])
		delete(imgCache, alt)
	}
	imgCache[adresse] = b
	imgCacheFolge = append(imgCacheFolge, adresse)
	imgCacheSumme += len(b)
}

var genImgURLRe = regexp.MustCompile(`/api/generated/[0-9a-f]{32}\.[a-z]+`)
var genImgMdRe = regexp.MustCompile(`!\[[^\]]*\]\([^)]*?/api/generated/[0-9a-f]{32}\.[a-z]+\)`)

// extractGenImages liefert die relativen Bild-URLs und den um die Bild-Referenzen
// bereinigten Text.
func extractGenImages(text string) ([]string, string) {
	urls := genImgURLRe.FindAllString(text, -1)
	clean := genImgMdRe.ReplaceAllString(text, "")
	clean = genImgURLRe.ReplaceAllString(clean, "")
	clean = strings.TrimSpace(clean)
	return urls, clean
}

func fetchImageBytes(url string) ([]byte, error) {
	if b, ok := imgCacheHole(url); ok {
		return b, nil
	}
	client := imgClientFuer(url)
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	if tok := imgTokenJetzt(); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("Bildabruf: HTTP %d", resp.StatusCode)
	}
	// Ein Byte mehr lesen, damit ein zu grosses Bild erkannt statt abgeschnitten wird
	data, err := io.ReadAll(io.LimitReader(resp.Body, imgMaxBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > imgMaxBytes {
		return nil, fmt.Errorf("Bild groesser als %d Bytes", imgMaxBytes)
	}
	imgCacheLege(url, data)
	return data, nil
}

// buildJarvisBody baut den Inhalt einer Jarvis-Bubble: Text und – falls vorhanden –
// inline geladene Bilder.
func buildJarvisBody(text string) fyne.CanvasObject {
	urls, clean := extractGenImages(text)
	if len(urls) == 0 {
		return newBoldWhiteText(text, true)
	}

	items := []fyne.CanvasObject{}
	if clean != "" {
		items = append(items, newBoldWhiteText(clean, true))
	}
	for _, u := range urls {
		img := canvas.NewImageFromResource(theme.FileImageIcon()) // Platzhalter bis geladen
		img.FillMode = canvas.ImageFillContain
		img.SetMinSize(fyne.NewSize(260, 200))
		full := imgBasis() + u
		go func(url string, target *canvas.Image) {
			data, err := fetchImageBytes(url)
			if err != nil || len(data) == 0 {
				return
			}
			target.Resource = fyne.NewStaticResource("genimg", data)
			canvas.Refresh(target)
		}(full, img)
		items = append(items, img)
	}
	return container.NewVBox(items...)
}
