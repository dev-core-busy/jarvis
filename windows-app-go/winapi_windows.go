//go:build windows

package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

// ─────────────────────────────────────────────────────────────────────────────
// Win32 DLLs + Procs
// ─────────────────────────────────────────────────────────────────────────────

var (
	user32   = syscall.MustLoadDLL("user32.dll")
	shell32  = syscall.MustLoadDLL("shell32.dll")
	kernel32 = syscall.MustLoadDLL("kernel32.dll")
	winmm    = syscall.MustLoadDLL("winmm.dll")

	pMciSendStringW = winmm.MustFindProc("mciSendStringW")
	pCreateMutexW   = kernel32.MustFindProc("CreateMutexW")
	pGetLastError   = kernel32.MustFindProc("GetLastError")

	// Fenster-Hilfsfunktionen (Frameless-Avatar)
	pFindWindowW                = user32.MustFindProc("FindWindowW")
	pGetWindowLongPtrW          = user32.MustFindProc("GetWindowLongPtrW")
	pSetWindowLongPtrW          = user32.MustFindProc("SetWindowLongPtrW")
	pSetLayeredWindowAttributes = user32.MustFindProc("SetLayeredWindowAttributes")
	pSetWindowPos               = user32.MustFindProc("SetWindowPos")
	pSendMessageW               = user32.MustFindProc("SendMessageW")
	pReleaseCapture             = user32.MustFindProc("ReleaseCapture")
	pCallWindowProcW            = user32.MustFindProc("CallWindowProcW")

	// Systray
	pGetModuleHandleW    = kernel32.MustFindProc("GetModuleHandleW")
	pRegisterClassExW    = user32.MustFindProc("RegisterClassExW")
	pCreateWindowExW     = user32.MustFindProc("CreateWindowExW")
	pDefWindowProcW      = user32.MustFindProc("DefWindowProcW")
	pGetMessageW         = user32.MustFindProc("GetMessageW")
	pTranslateMessage    = user32.MustFindProc("TranslateMessage")
	pDispatchMessageW    = user32.MustFindProc("DispatchMessageW")
	pShellNotifyIconW    = shell32.MustFindProc("Shell_NotifyIconW")
	pLoadImageW          = user32.MustFindProc("LoadImageW")
	pShowWindow          = user32.MustFindProc("ShowWindow")
	pGetCursorPos        = user32.MustFindProc("GetCursorPos")
	pSetForegroundWindow = user32.MustFindProc("SetForegroundWindow")
	pGetSystemMetrics    = user32.MustFindProc("GetSystemMetrics")
	pGetWindowRect       = user32.MustFindProc("GetWindowRect")
	pCreatePopupMenu     = user32.MustFindProc("CreatePopupMenu")
	pAppendMenuW         = user32.MustFindProc("AppendMenuW")
	pTrackPopupMenu      = user32.MustFindProc("TrackPopupMenu")
	pDestroyMenu         = user32.MustFindProc("DestroyMenu")
	pPostQuitMessage     = user32.MustFindProc("PostQuitMessage")
)

// ─────────────────────────────────────────────────────────────────────────────
// Win32 Konstanten
// ─────────────────────────────────────────────────────────────────────────────

const (
	// Window-Styles (Avatar-Fenster)
	gwlStyle    = ^uintptr(15) // -16
	gwlExStyle  = ^uintptr(19) // -20
	gwlWndProc  = ^uintptr(3)  // -4  GWLP_WNDPROC

	wmNcHitTest = uintptr(0x0084)
	htClient    = uintptr(1)

	wsCaption     = uintptr(0x00C00000)
	wsSysMenu     = uintptr(0x00080000)
	wsThickFrame  = uintptr(0x00040000)
	wsMinimizeBox = uintptr(0x00020000)
	wsMaximizeBox = uintptr(0x00010000)
	wsPopup       = uintptr(0x80000000)

	wsExLayered    = uintptr(0x00080000)
	wsExTopMost    = uintptr(0x00000008)
	wsExToolWindow = uintptr(0x00000080)
	wsExNoActivate = uintptr(0x08000000)

	lwaColorkey = uintptr(0x01)
	colorkey    = uintptr(2 | (2 << 8) | (2 << 16)) // RGB(2,2,2)

	swpNomove       = uintptr(0x0002)
	swpNosize       = uintptr(0x0001)
	swpNozorder     = uintptr(0x0004)
	swpFrameChanged = uintptr(0x0020)
	swpShowWindow   = uintptr(0x0040)
	swpNoActivate   = uintptr(0x0010)
	hwndTopmost     = ^uintptr(0) // -1

	smCxSmIcon = uintptr(49) // GetSystemMetrics: Breite des kleinen Icons (Tray)
	smCySmIcon = uintptr(50) // GetSystemMetrics: Höhe des kleinen Icons (Tray)

	wmNcLButtonDown = uintptr(0x00A1)
	htCaption       = uintptr(2)

	// Systray
	wmUser         = uint32(0x0400)
	wmTray         = wmUser + 1 // Callback-Message von Shell_NotifyIcon
	wmRButtonUp    = uintptr(0x0205)
	wmLButtonDblClk = uintptr(0x0203)

	nimAdd    = uintptr(0)
	nimModify = uintptr(1)
	nimDelete = uintptr(2)

	nifMessage = uint32(0x01)
	nifIcon    = uint32(0x02)
	nifTip     = uint32(0x04)
	nifInfo    = uint32(0x10)  // Balloon-Benachrichtigung
	niifInfo   = uint32(0x01)  // Info-Icon in Balloon

	imageIcon      = uintptr(1)
	lrLoadFromFile = uintptr(0x10)
	lrDefaultSize  = uintptr(0x40)

	mfString    = uintptr(0x00)
	mfSeparator = uintptr(0x800)

	tpmLeftAlign   = uintptr(0x0000)
	tpmBottomAlign = uintptr(0x0020)
	tpmRightButton = uintptr(0x0002)
	tpmReturnCmd   = uintptr(0x0100)

	// Menü-Item IDs
	menuIDMode     = uintptr(1001)
	menuIDSettings = uintptr(1002)
	menuIDDebug    = uintptr(1003)
	menuIDQuit     = uintptr(1004)

)

// ─────────────────────────────────────────────────────────────────────────────
// Win32 Strukturen
// ─────────────────────────────────────────────────────────────────────────────

// NOTIFYICONDATA vollständig (64-bit layout, Windows Vista+)
type notifyIconData struct {
	Size            uint32
	_               [4]byte   // Padding für HWND
	Wnd             uintptr
	ID              uint32
	Flags           uint32
	CallbackMessage uint32
	_               [4]byte   // Padding für HICON
	Icon            uintptr
	Tip             [128]uint16
	State           uint32
	StateMask       uint32
	Info            [256]uint16
	Version         uint32
	InfoTitle       [64]uint16
	InfoFlags       uint32
	_               [4]byte   // Padding für GUID
	GuidItem        [16]byte
	BalloonIcon     uintptr
}

type wndClassExW struct {
	Size       uint32
	Style      uint32
	WndProc    uintptr
	ClsExtra   int32
	WndExtra   int32
	Instance   uintptr
	Icon       uintptr
	Cursor     uintptr
	Background uintptr
	MenuName   *uint16
	ClassName  *uint16
	IconSm     uintptr
}

type point struct{ X, Y int32 }

type msg struct {
	Hwnd    uintptr
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Pt      point
}

// ─────────────────────────────────────────────────────────────────────────────
// Systray – Callbacks
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Avatar-Fenster: Nativer Drag via WM_NCHITTEST → HTCAPTION
// ─────────────────────────────────────────────────────────────────────────────

var (
	avatarOrigWndProc  uintptr
	avatarSubclassProc = syscall.NewCallback(avatarSubclassFn) // Callback MUSS global bleiben (kein GC!)
)

func avatarSubclassFn(hwnd, msg, wp, lp uintptr) uintptr {
	if msg == wmNcHitTest {
		return htCaption
	}
	ret, _, _ := pCallWindowProcW.Call(avatarOrigWndProc, hwnd, msg, wp, lp)
	return ret
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat-Fenster: Rahmenlos mit nativem Drag (WM_NCHITTEST → HTCAPTION)
// ─────────────────────────────────────────────────────────────────────────────

var (
	chatOrigWndProc  uintptr
	chatSubclassProc = syscall.NewCallback(chatSubclassFn) // Callback MUSS global bleiben (kein GC!)
)

// chatSubclassFn: Nur ein schmaler Drag-Streifen ganz oben (20px) gibt HTCAPTION zurück.
// Der Rest bleibt HTCLIENT → Fyne-Buttons/-Eingaben funktionieren normal.
func chatSubclassFn(hwnd, msg, wp, lp uintptr) uintptr {
	if msg == wmNcHitTest {
		ret, _, _ := pCallWindowProcW.Call(chatOrigWndProc, hwnd, msg, wp, lp)
		if ret == htClient {
			var r winRECT
			pGetWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&r)))
			screenY := int32(int16((lp >> 16) & 0xFFFF))
			relY := screenY - r.Top
			// Nur die obersten 20px sind Drag-Bereich (schmaler Streifen über dem Header)
			if relY >= 0 && relY <= 20 {
				return htCaption
			}
		}
		return ret
	}
	ret, _, _ := pCallWindowProcW.Call(chatOrigWndProc, hwnd, msg, wp, lp)
	return ret
}

// MakeChatWindowFrameless entfernt den Titelrahmen des Chat-Fensters.
// Das Fenster bleibt normal bedienbar (kein TopMost, kein ToolWindow).
func MakeChatWindowFrameless() {
	var hwnd uintptr
	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		hwnd = findHWND("Jarvis – Chat")
		if hwnd != 0 {
			break
		}
	}
	if hwnd == 0 {
		return
	}

	// Titelleiste + Rahmen entfernen, aber Größenänderung beibehalten
	style, _, _ := pGetWindowLongPtrW.Call(hwnd, gwlStyle)
	style &^= wsCaption | wsSysMenu | wsMinimizeBox | wsMaximizeBox
	// wsThickFrame beibehalten → Größenänderung an den Kanten weiterhin möglich
	pSetWindowLongPtrW.Call(hwnd, gwlStyle, style)

	// Rahmen neu berechnen lassen
	pSetWindowPos.Call(hwnd, 0, 0, 0, 0, 0,
		swpNomove|swpNosize|swpNozorder|swpFrameChanged|swpShowWindow)

	// WndProc subclassen für Drag + Eingabefeld-Schutz
	chatOrigWndProc, _, _ = pSetWindowLongPtrW.Call(hwnd, gwlWndProc, chatSubclassProc)
}

var (
	trayCallbacks struct {
		onMode     func()
		onSettings func()
		onDebug    func()
		onQuit     func()
		dialogMode func() bool
		debugMode  func() bool
	}
	trayHWnd uintptr
	// Callback MUSS in Global-Variable gespeichert werden (kein GC!)
	trayWndProcCallback = syscall.NewCallback(trayWndProc)
)

// StartNativeSysTray startet das System-Tray in einem eigenen OS-Thread.
func StartNativeSysTray(onMode, onSettings, onDebug, onQuit func(), dialogMode, debugMode func() bool) {
	trayCallbacks.onMode = onMode
	trayCallbacks.onSettings = onSettings
	trayCallbacks.onDebug = onDebug
	trayCallbacks.onQuit = onQuit
	trayCallbacks.dialogMode = dialogMode
	trayCallbacks.debugMode = debugMode

	go func() {
		runtime.LockOSThread() // KRITISCH: Win32 Message-Queue ist thread-spezifisch
		runNativeSysTray()
	}()
}

func runNativeSysTray() {

	// ICO in Temp-Datei schreiben
	icoPath := filepath.Join(os.TempDir(), "jarvis_tray.ico")
	_ = os.WriteFile(icoPath, jarvisTrayICO, 0644)

	// Instanz-Handle
	hInst, _, _ := pGetModuleHandleW.Call(0)

	// Fensterklasse registrieren
	className, _ := syscall.UTF16PtrFromString("JarvisTrayWnd")
	wc := wndClassExW{
		Style:     0,
		WndProc:   trayWndProcCallback,
		Instance:  hInst,
		ClassName: className,
	}
	wc.Size = uint32(unsafe.Sizeof(wc))
	_, _, _ = pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))

	// Normales verstecktes Fenster (wie getlantern/systray)
	const (
		wsOverlappedWindow = uintptr(0x00CF0000)
		cwUseDefault       = uintptr(0x80000000)
		swHide             = uintptr(0)
	)
	hwnd, _, _ := pCreateWindowExW.Call(
		0,
		uintptr(unsafe.Pointer(className)),
		0,
		wsOverlappedWindow,
		cwUseDefault, cwUseDefault, cwUseDefault, cwUseDefault,
		0, 0, hInst, 0,
	)
	if hwnd == 0 {
		return
	}
	trayHWnd = hwnd
	pShowWindow.Call(hwnd, swHide)

	// Icon aus der EXE-Resource laden (rsrc.syso, ID 1) – zuverlässiger als Temp-Datei.
	// Fallback: Temp-Datei wenn Resource nicht gefunden.
	hIcon, _, _ := pLoadImageW.Call(
		hInst,
		1, // MAKEINTRESOURCE(1) – Resource-ID aus jarvis.rc
		imageIcon,
		0, 0,         // 0 = Windows wählt beste Größe (SM_CXICON)
		lrDefaultSize, // lädt bei SM_CXICON-Größe (32–40px je nach DPI)
	)
	if hIcon == 0 {
		// Fallback: aus Temp-Datei laden
		icoPathPtr, _ := syscall.UTF16PtrFromString(icoPath)
		hIcon, _, _ = pLoadImageW.Call(
			0,
			uintptr(unsafe.Pointer(icoPathPtr)),
			imageIcon,
			32, 32,
			lrLoadFromFile,
		)
	}

	// Shell_NotifyIcon NIM_ADD
	tip, _ := syscall.UTF16FromString("Jarvis AI")
	nid := notifyIconData{
		Wnd:             hwnd,
		ID:              1,
		Flags:           nifMessage | nifIcon | nifTip,
		CallbackMessage: wmTray,
		Icon:            hIcon,
	}
	copy(nid.Tip[:], tip)
	nid.Size = uint32(unsafe.Sizeof(nid))
	_, _, _ = pShellNotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(&nid)))

	// NOTIFYICON_VERSION_4 → modernes Verhalten (Windows Vista+)
	const nimSetVersion = uintptr(4)
	nid.Version = 4
	pShellNotifyIconW.Call(nimSetVersion, uintptr(unsafe.Pointer(&nid)))

	// Message-Loop
	var m msg
	for {
		r, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}

	// Aufräumen
	pShellNotifyIconW.Call(nimDelete, uintptr(unsafe.Pointer(&nid)))
}

// trayWndProc ist die Win32-Fensterprozedur für das Tray-Fenster.
func trayWndProc(hwnd, msg, wp, lp uintptr) uintptr {
	if msg == uintptr(wmTray) {
		switch lp & 0xFFFF {
		case wmRButtonUp:
			showTrayContextMenu(hwnd)
		case wmLButtonDblClk:
			// Doppelklick: Modus-Toggle
			if cb := trayCallbacks.onMode; cb != nil {
				go cb()
			}
		}
		return 0
	}
	ret, _, _ := pDefWindowProcW.Call(hwnd, msg, wp, lp)
	return ret
}

func showTrayContextMenu(hwnd uintptr) {
	var pt point
	pGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))

	hMenu, _, _ := pCreatePopupMenu.Call()
	if hMenu == 0 {
		return
	}
	defer pDestroyMenu.Call(hMenu)

	// Modus-Label je nach aktuellem Modus
	modeLabel := "Dialog  ->  zu Textmodus wechseln"
	if trayCallbacks.dialogMode != nil && !trayCallbacks.dialogMode() {
		modeLabel = "Text  ->  zu Dialogmodus wechseln"
	}
	debugLabel := "🔍 Debug Modus aktivieren"
	if trayCallbacks.debugMode != nil && trayCallbacks.debugMode() {
		debugLabel = "🔍 Debug Modus deaktivieren"
	}
	modeLabelPtr, _ := syscall.UTF16PtrFromString(modeLabel)
	settingsPtr, _ := syscall.UTF16PtrFromString("⚙  Einstellungen")
	debugPtr, _ := syscall.UTF16PtrFromString(debugLabel)
	quitPtr, _ := syscall.UTF16PtrFromString("✕  Beenden")

	pAppendMenuW.Call(hMenu, mfString, menuIDMode, uintptr(unsafe.Pointer(modeLabelPtr)))
	pAppendMenuW.Call(hMenu, mfString, menuIDSettings, uintptr(unsafe.Pointer(settingsPtr)))
	pAppendMenuW.Call(hMenu, mfString, menuIDDebug, uintptr(unsafe.Pointer(debugPtr)))
	pAppendMenuW.Call(hMenu, mfSeparator, 0, 0)
	pAppendMenuW.Call(hMenu, mfString, menuIDQuit, uintptr(unsafe.Pointer(quitPtr)))

	// WICHTIG: Foreground-Window setzen, sonst klappt Menü bei zweitem Klick nicht zu
	pSetForegroundWindow.Call(hwnd)

	// Menü anzeigen + auf Auswahl warten (TPM_RETURNCMD liefert gewählte ID)
	selected, _, _ := pTrackPopupMenu.Call(
		hMenu,
		tpmLeftAlign|tpmBottomAlign|tpmRightButton|tpmReturnCmd,
		uintptr(pt.X), uintptr(pt.Y),
		0, hwnd, 0,
	)

	switch selected {
	case menuIDMode:
		if cb := trayCallbacks.onMode; cb != nil {
			go cb()
		}
	case menuIDSettings:
		if cb := trayCallbacks.onSettings; cb != nil {
			go cb()
		}
	case menuIDDebug:
		if cb := trayCallbacks.onDebug; cb != nil {
			go cb()
		}
	case menuIDQuit:
		if cb := trayCallbacks.onQuit; cb != nil {
			go cb()
		}
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Avatar-Fenster: Rahmenlos + Transparent + Drag
// ─────────────────────────────────────────────────────────────────────────────

func findHWND(title string) uintptr {
	ptr, _ := syscall.UTF16PtrFromString(title)
	hwnd, _, _ := pFindWindowW.Call(0, uintptr(unsafe.Pointer(ptr)))
	return hwnd
}

// MakeAvatarWindowFrameless entfernt Titelleiste, macht Hintergrund transparent.
func MakeAvatarWindowFrameless() {
	var hwnd uintptr
	for i := 0; i < 20; i++ {
		time.Sleep(100 * time.Millisecond)
		hwnd = findHWND("Jarvis")
		if hwnd != 0 {
			break
		}
	}
	if hwnd == 0 {
		return
	}

	// Titelleiste + Rahmen entfernen
	style, _, _ := pGetWindowLongPtrW.Call(hwnd, gwlStyle)
	style &^= wsCaption | wsSysMenu | wsThickFrame | wsMinimizeBox | wsMaximizeBox
	style |= wsPopup
	pSetWindowLongPtrW.Call(hwnd, gwlStyle, style)

	// Layered + TopMost + kein Taskbar-Eintrag
	exStyle, _, _ := pGetWindowLongPtrW.Call(hwnd, gwlExStyle)
	exStyle |= wsExLayered | wsExTopMost | wsExToolWindow | wsExNoActivate
	pSetWindowLongPtrW.Call(hwnd, gwlExStyle, exStyle)

	// Colorkey RGB(2,2,2) = transparent
	pSetLayeredWindowAttributes.Call(hwnd, colorkey, 0, lwaColorkey)

	// Fensterrahmen neu zeichnen + TopMost bestätigen
	pSetWindowPos.Call(hwnd, hwndTopmost, 0, 0, 0, 0,
		swpNomove|swpNosize|swpFrameChanged|swpShowWindow)

	// WndProc subclassen: WM_NCHITTEST → HTCAPTION
	// Windows übernimmt damit den Drag vollständig – ruckelfrei, DPI-korrekt.
	avatarOrigWndProc, _, _ = pSetWindowLongPtrW.Call(hwnd, gwlWndProc, avatarSubclassProc)
}

// RECT Struktur für GetWindowRect
type winRECT struct{ Left, Top, Right, Bottom int32 }

// avatarHWND cached – verhindert FindWindow auf jedem Drag-Event
var (
	avatarHWNDCached uintptr
	avatarCachedX    int32
	avatarCachedY    int32
	avatarPosInit    bool
)

func ClearAvatarHWND() {
	avatarHWNDCached = 0
	avatarPosInit = false
}

// GetAvatarPosition gibt die aktuelle Fensterposition zurück (für Speichern beim Beenden).
func GetAvatarPosition() (x, y int) {
	hwnd := findHWND("Jarvis")
	if hwnd == 0 {
		return 0, 0
	}
	var r winRECT
	pGetWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&r)))
	return int(r.Left), int(r.Top)
}

// SetAvatarPosition setzt die Fensterposition (Wiederherstellen beim Start).
func SetAvatarPosition(x, y int) {
	if x == 0 && y == 0 {
		return // Keine gespeicherte Position
	}
	// Kurz warten bis Fyne das Fenster erstellt hat
	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		hwnd := findHWND("Jarvis")
		if hwnd != 0 {
			pSetWindowPos.Call(hwnd, 0,
				uintptr(x), uintptr(y), 0, 0,
				swpNosize|swpNozorder|swpNoActivate)
			// Auch Cache aktualisieren
			avatarHWNDCached = hwnd
			avatarCachedX = int32(x)
			avatarCachedY = int32(y)
			avatarPosInit = true
			return
		}
	}
}

// ShowTrayBalloon zeigt eine Windows-Tray-Balloon-Benachrichtigung.
func ShowTrayBalloon(title, text string) {
	if trayHWnd == 0 {
		return
	}
	var nid notifyIconData
	nid.Size = uint32(unsafe.Sizeof(nid))
	nid.Wnd = trayHWnd
	nid.ID = 1
	nid.Flags = nifInfo
	t, _ := syscall.UTF16FromString(title)
	copy(nid.InfoTitle[:], t)
	m, _ := syscall.UTF16FromString(text)
	copy(nid.Info[:], m)
	nid.InfoFlags = niifInfo
	pShellNotifyIconW.Call(nimModify, uintptr(unsafe.Pointer(&nid)))
}

// ─────────────────────────────────────────────────────────────────────────────
// TTS-Stimmen – Windows SAPI + Backend (edge-tts)
// ─────────────────────────────────────────────────────────────────────────────

var (
	currentTTSVoice  string
	currentServerURL string
	currentAPIKey    string

	// TTS-Stop: laufender Prozess/MCI-Zustand
	ttsStopMu      sync.Mutex
	ttsStopCmd     *exec.Cmd // aktueller PowerShell-Prozess (SAPI)
	ttsStopIsMCI   bool      // true = MCI/MP3 läuft gerade
)

// StopTTS unterbricht die laufende TTS-Wiedergabe sofort.
func StopTTS() {
	ttsStopMu.Lock()
	defer ttsStopMu.Unlock()
	if ttsStopCmd != nil && ttsStopCmd.Process != nil {
		_ = ttsStopCmd.Process.Kill()
		ttsStopCmd = nil
	}
	if ttsStopIsMCI {
		mciSend("stop jarvis_tts")
		mciSend("close jarvis_tts")
		ttsStopIsMCI = false
	}
}

// SetTTSVoice setzt die aktive Stimme (SAPI-Name oder Backend-ID wie "de-DE-KatjaNeural").
func SetTTSVoice(voice string) { currentTTSVoice = voice }

// SetTTSServer speichert Server-URL + API-Key für Backend-TTS.
func SetTTSServer(serverURL, apiKey string) {
	currentServerURL = serverURL
	currentAPIKey = apiKey
}

// isBackendVoice erkennt Backend-Stimmen am Format "xx-XX-...Neural".
func isBackendVoice(voice string) bool {
	if voice == "" || strings.HasPrefix(voice, "sapi:") {
		return false
	}
	p := strings.Split(voice, "-")
	return len(p) >= 3 && len(p[0]) == 2 && len(p[1]) == 2
}

// ── Backend-Stimmen ───────────────────────────────────────────────────────────

type ttsVoiceEntry struct {
	Name    string `json:"name"`    // Voice-ID (z.B. "de-DE-KatjaNeural")
	Display string `json:"display"` // Anzeigename
	Gender  string `json:"gender"`
	Locale  string `json:"locale"`
}

// jarvisHTTP führt einen einfachen HTTP-Request gegen den Jarvis-Backend durch.
func jarvisHTTP(method, url, token string, body interface{}) ([]byte, error) {
	var bodyReader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		bodyReader = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, url, bodyReader)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("X-API-Key", token)
	client := &http.Client{
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
		Timeout: 30 * time.Second,
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

// wsURLToHTTPS konvertiert wss:// → https://, ws:// → http://.
func wsURLToHTTPS(wsURL string) string {
	u := strings.TrimSuffix(wsURL, "/ws")
	u = strings.TrimSuffix(u, "/")
	u = strings.ReplaceAll(u, "wss://", "https://")
	u = strings.ReplaceAll(u, "ws://", "http://")
	return u
}

// FetchBackendVoices holt verfügbare TTS-Stimmen vom Backend (edge-tts).
// Gibt (Namen, IDs) zurück – beide Slices gleich lang.
func FetchBackendVoices(serverURL, apiKey string) (names []string, ids []string) {
	url := wsURLToHTTPS(serverURL) + "/api/tts/voices"
	data, err := jarvisHTTP("GET", url, apiKey, nil)
	if err != nil {
		return nil, nil
	}
	var voices []ttsVoiceEntry
	if err := json.Unmarshal(data, &voices); err != nil {
		return nil, nil
	}
	for _, v := range voices {
		display := v.Display
		if display == "" {
			display = v.Name
		}
		names = append(names, display)
		ids = append(ids, v.Name) // Name = Voice-ID (z.B. "de-DE-KatjaNeural")
	}
	return names, ids
}

// mciSend sendet einen MCI-Befehl via winmm.dll.
func mciSend(cmd string) {
	ptr, _ := syscall.UTF16PtrFromString(cmd)
	pMciSendStringW.Call(uintptr(unsafe.Pointer(ptr)), 0, 0, 0)
}

// playMP3Bytes schreibt MP3-Daten in eine Temp-Datei und spielt sie via mciSendString ab.
func playMP3Bytes(data []byte) {
	f, err := os.CreateTemp("", "jarvis_tts_*.mp3")
	if err != nil {
		return
	}
	path := f.Name()
	_, _ = f.Write(data)
	f.Close()
	defer os.Remove(path)
	path = strings.ReplaceAll(path, "/", "\\")
	mciSend(fmt.Sprintf(`open "%s" type mpegvideo alias jarvis_tts`, path))

	ttsStopMu.Lock()
	ttsStopIsMCI = true
	ttsStopMu.Unlock()

	mciSend(`play jarvis_tts wait`)

	ttsStopMu.Lock()
	ttsStopIsMCI = false
	ttsStopMu.Unlock()

	mciSend(`close jarvis_tts`)
}

// PlayWAVBytes schreibt WAV-Daten in eine Temp-Datei und spielt sie via PowerShell ab.
func PlayWAVBytes(data []byte) {
	f, err := os.CreateTemp("", "jarvis_tts_*.wav")
	if err != nil {
		return
	}
	path := f.Name()
	_, _ = f.Write(data)
	f.Close()
	defer os.Remove(path)
	path = strings.ReplaceAll(path, "/", "\\")
	script := `(New-Object System.Media.SoundPlayer '` + path + `').PlaySync()`
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Run()
}

// PlayBackendTTS generiert TTS-Audio über das Backend und spielt es ab (blockierend).
func PlayBackendTTS(serverURL, apiKey, text, voiceID string) error {
	url := wsURLToHTTPS(serverURL) + "/api/tts"
	data, err := jarvisHTTP("POST", url, apiKey, map[string]string{
		"text":  text,
		"voice": voiceID,
	})
	if err != nil {
		return err
	}
	playMP3Bytes(data)
	return nil
}

// ── Windows SAPI TTS ──────────────────────────────────────────────────────────

// ListTTSVoices gibt alle installierten Windows SAPI-Stimmen zurück.
func ListTTSVoices() []string {
	script := `Add-Type -AssemblyName System.Speech -EA SilentlyContinue; ` +
		`$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; ` +
		`$v.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }`
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.Output()
	if err != nil || len(out) == 0 {
		return nil
	}
	var voices []string
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimRight(line, "\r\n ")
		if line != "" {
			voices = append(voices, line)
		}
	}
	return voices
}

// PlayTestVoice spricht einen kurzen Testtext mit der angegebenen Stimme.
// voiceID="" → Standard. Blockierend, in Goroutine aufrufen!
func PlayTestVoice(voiceID string) {
	if isBackendVoice(voiceID) && currentServerURL != "" {
		_ = PlayBackendTTS(currentServerURL, currentAPIKey,
			"Hallo, ich bin Jarvis, dein persönlicher Assistent.", voiceID)
		return
	}
	text := "Hallo, ich bin Jarvis."
	voicePart := ""
	if strings.HasPrefix(voiceID, "sapi:") {
		safe := strings.ReplaceAll(voiceID[5:], "'", "")
		if safe != "" {
			voicePart = `try { $v.SelectVoice('` + safe + `') } catch {}; `
		}
	}
	script := `Add-Type -AssemblyName System.Speech -EA SilentlyContinue; ` +
		`$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; $v.Rate=1; ` +
		voicePart + `$v.Speak('` + text + `')`
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Run()
}

// PlayTestTone spielt einen kurzen Testton (440 Hz) über das Windows-Audiogerät.
func PlayTestTone() {
	script := `[System.Console]::Beep(440, 350); Start-Sleep -Milliseconds 80; [System.Console]::Beep(550, 200)`
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Run()
}

// SpeakText spricht den Text aus (blockierend, in Goroutine aufrufen).
// Priorität: Backend-Stimme → Windows SAPI.
func SpeakText(text string) {
	clean := stripMarkdownForTTS(text)
	if clean == "" {
		return
	}
	if len(clean) > 800 {
		cutAt := 800
		for i := 800; i > 600; i-- {
			if clean[i] == '.' || clean[i] == '!' || clean[i] == '?' {
				cutAt = i + 1
				break
			}
		}
		clean = clean[:cutAt]
	}

	// Backend-TTS bevorzugen: bei konfigurierter Backend-Stimme ODER als primärer Weg
	// wenn Server erreichbar ist (leere Stimme → Server nutzt seinen Default).
	if currentServerURL != "" {
		if err := PlayBackendTTS(currentServerURL, currentAPIKey, clean, currentTTSVoice); err == nil {
			return
		}
		// Fallback: Windows SAPI
	}

	// SAPI PowerShell (Fallback wenn kein Server oder Backend-TTS fehlschlägt)
	escaped := strings.ReplaceAll(clean, "'", " ")
	escaped = strings.ReplaceAll(escaped, "\n", " ")
	escaped = strings.Join(strings.Fields(escaped), " ")

	// Nur SAPI-Stimmen (sapi: Präfix) für SelectVoice verwenden.
	voicePart := ""
	if strings.HasPrefix(currentTTSVoice, "sapi:") {
		safe := strings.ReplaceAll(currentTTSVoice[5:], "'", "")
		if safe != "" {
			voicePart = `try { $v.SelectVoice('` + safe + `') } catch {}; `
		}
	}
	script := `Add-Type -AssemblyName System.Speech -ErrorAction SilentlyContinue; ` +
		`$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; ` +
		`$v.Rate = 1; ` + voicePart +
		`$v.Speak('` + escaped + `')`
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}

	// Prozess starten BEVOR er in ttsStopCmd eingetragen wird → Process ist dann nie nil
	if err := cmd.Start(); err != nil {
		return
	}
	ttsStopMu.Lock()
	ttsStopCmd = cmd
	ttsStopMu.Unlock()

	_ = cmd.Wait()

	ttsStopMu.Lock()
	if ttsStopCmd == cmd {
		ttsStopCmd = nil
	}
	ttsStopMu.Unlock()
}

// stripMarkdownForTTS entfernt Markdown-Formatierung für TTS-Ausgabe.
func stripMarkdownForTTS(text string) string {
	result := text
	for {
		start := strings.Index(result, "```")
		if start < 0 {
			break
		}
		end := strings.Index(result[start+3:], "```")
		if end < 0 {
			result = result[:start]
			break
		}
		result = result[:start] + " " + result[start+3+end+3:]
	}
	for strings.Contains(result, "`") {
		s := strings.Index(result, "`")
		e := strings.Index(result[s+1:], "`")
		if e < 0 {
			result = result[:s] + result[s+1:]
			break
		}
		result = result[:s] + " " + result[s+1+e+1:]
	}
	result = strings.ReplaceAll(result, "**", "")
	result = strings.ReplaceAll(result, "__", "")
	result = strings.ReplaceAll(result, "*", "")
	result = strings.ReplaceAll(result, "_", " ")
	result = strings.ReplaceAll(result, "### ", "")
	result = strings.ReplaceAll(result, "## ", "")
	result = strings.ReplaceAll(result, "# ", "")
	result = strings.ReplaceAll(result, "\n- ", " ")
	result = strings.ReplaceAll(result, "\n* ", " ")
	result = strings.ReplaceAll(result, "\n• ", " ")
	words := strings.Fields(result)
	filtered := make([]string, 0, len(words))
	for _, w := range words {
		if !strings.HasPrefix(w, "http://") && !strings.HasPrefix(w, "https://") {
			filtered = append(filtered, w)
		}
	}
	return strings.TrimSpace(strings.Join(filtered, " "))
}

// MoveAvatarWindow verschiebt das Avatar-Fenster um (dx, dy) Pixel.
// Cached HWND + Position → kein GetWindowRect auf jedem Drag-Event (ruckelfreier Drag).
func MoveAvatarWindow(dx, dy float64) {
	if avatarHWNDCached == 0 {
		avatarHWNDCached = findHWND("Jarvis")
		if avatarHWNDCached == 0 {
			return
		}
	}
	if !avatarPosInit {
		var r winRECT
		pGetWindowRect.Call(avatarHWNDCached, uintptr(unsafe.Pointer(&r)))
		avatarCachedX, avatarCachedY = r.Left, r.Top
		avatarPosInit = true
	}
	avatarCachedX += int32(dx)
	avatarCachedY += int32(dy)
	pSetWindowPos.Call(avatarHWNDCached, 0,
		uintptr(avatarCachedX), uintptr(avatarCachedY), 0, 0,
		swpNosize|swpNozorder|swpNoActivate,
	)
}

// ─────────────────────────────────────────────────────────────────────────────
// Single-Instance (Mutex + Named Pipe IPC)
// ─────────────────────────────────────────────────────────────────────────────

const (
	_mutexName    = "Local\\JarvisDesktopApp_v1"
	_pipeName     = `\\.\pipe\JarvisDesktopApp_v1`
	_errAlreadyExists = uintptr(183) // ERROR_ALREADY_EXISTS
)

var (
	pCreateNamedPipeW   = kernel32.MustFindProc("CreateNamedPipeW")
	pConnectNamedPipe   = kernel32.MustFindProc("ConnectNamedPipe")
	pReadFile           = kernel32.MustFindProc("ReadFile")
	pWriteFile          = kernel32.MustFindProc("WriteFile")
	pCreateFileW        = kernel32.MustFindProc("CreateFileW")
	pCloseHandle        = kernel32.MustFindProc("CloseHandle")
	pAllowSetForeground = user32.MustFindProc("AllowSetForegroundWindow")
	pBringWindowToTop   = user32.MustFindProc("BringWindowToTop")
	pEnumWindows        = user32.MustFindProc("EnumWindows")
	pGetWindowTextW     = user32.MustFindProc("GetWindowTextW")
	pIsWindowVisible    = user32.MustFindProc("IsWindowVisible")
)

// EnsureSingleInstance prüft via benanntem Mutex ob eine Instanz bereits läuft.
// Falls ja: sendet "show" durch Named Pipe an laufende Instanz und gibt false zurück.
func EnsureSingleInstance() bool {
	namePtr, _ := syscall.UTF16PtrFromString(_mutexName)
	// bInitialOwner=0: kein exklusiver Besitz – nur Existenzprüfung.
	// Der DRITTE Rückgabewert von Call() ist der Win32-Fehlercode (syscall.Errno).
	// GetLastError() danach wäre zu spät – Go-Runtime kann den Error überschreiben.
	_, _, err := pCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(namePtr)))
	if err.(syscall.Errno) != syscall.Errno(183) { // 183 = ERROR_ALREADY_EXISTS
		return true // Erste Instanz – normal starten
	}
	// Zweite Instanz: "show" an laufende Instanz schicken
	pipePtr, _ := syscall.UTF16PtrFromString(_pipeName)
	for i := 0; i < 8; i++ {
		h, _, _ := pCreateFileW.Call(
			uintptr(unsafe.Pointer(pipePtr)),
			0x40000000, // GENERIC_WRITE
			0, 0,
			3,          // OPEN_EXISTING
			0x00000080, // FILE_ATTRIBUTE_NORMAL
			0,
		)
		if h != 0 && h != ^uintptr(0) {
			msg := []byte("show\n")
			var written uint32
			pWriteFile.Call(h, uintptr(unsafe.Pointer(&msg[0])), uintptr(len(msg)), uintptr(unsafe.Pointer(&written)), 0)
			pCloseHandle.Call(h)
			return false
		}
		time.Sleep(150 * time.Millisecond)
	}
	return false
}

// StartPipeServer lauscht auf Named-Pipe-Verbindungen.
// Bei Empfang von "show" wird onShow() aufgerufen (im eigenen Goroutine).
func StartPipeServer(onShow func()) {
	go func() {
		for {
			pipePtr, _ := syscall.UTF16PtrFromString(_pipeName)
			h, _, _ := pCreateNamedPipeW.Call(
				uintptr(unsafe.Pointer(pipePtr)),
				0x00000001, // PIPE_ACCESS_INBOUND
				0x00000000, // PIPE_TYPE_BYTE | PIPE_WAIT
				10,         // nMaxInstances
				512, 512,   // out/in buffer
				0, 0,
			)
			if h == ^uintptr(0) { // INVALID_HANDLE_VALUE – kurz warten, Retry
				time.Sleep(500 * time.Millisecond)
				continue
			}
			// Blockiert bis Client verbindet
			pConnectNamedPipe.Call(h, 0)
			go func(handle uintptr) {
				defer pCloseHandle.Call(handle)
				buf := make([]byte, 16)
				var read uint32
				r, _, _ := pReadFile.Call(handle, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)), uintptr(unsafe.Pointer(&read)), 0)
				if r != 0 && read > 0 {
					onShow()
				}
			}(h)
		}
	}()
}

// BringToForeground sucht das Jarvis-Hauptfenster per Titel und bringt es in den Vordergrund.
// Muss aus der laufenden Instanz aufgerufen werden (Input-Rechte → SetForegroundWindow erlaubt).
func BringToForeground() {
	// Via EnumWindows nach Fenstername suchen
	var found uintptr
	cb := syscall.NewCallback(func(hwnd, _ uintptr) uintptr {
		if found != 0 {
			return 0
		}
		vis, _, _ := pIsWindowVisible.Call(hwnd)
		if vis == 0 {
			return 1
		}
		buf := make([]uint16, 256)
		pGetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
		title := syscall.UTF16ToString(buf)
		if title == "Jarvis – Chat" || title == "Jarvis" {
			found = hwnd
			return 0
		}
		return 1
	})
	pEnumWindows.Call(cb, 0)
	if found == 0 {
		return
	}
	// AllowSetForegroundWindow → SetForegroundWindow → BringWindowToTop
	pAllowSetForeground.Call(^uintptr(0)) // ASFW_ANY
	pShowWindow.Call(found, 9)            // SW_RESTORE (aus Minimize holen falls nötig)
	pSetForegroundWindow.Call(found)
	pBringWindowToTop.Call(found)
}
