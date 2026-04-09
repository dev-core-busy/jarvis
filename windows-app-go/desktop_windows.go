//go:build windows

package main

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"image/png"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// ─── Win32 APIs ───────────────────────────────────────────────────────────────

var (
	deskUser32   = syscall.NewLazyDLL("user32.dll")
	deskGdi32    = syscall.NewLazyDLL("gdi32.dll")
	deskKernel32 = syscall.NewLazyDLL("kernel32.dll")

	// GDI – Screenshot
	procCreateCompatibleDC     = deskGdi32.NewProc("CreateCompatibleDC")
	procCreateCompatibleBitmap = deskGdi32.NewProc("CreateCompatibleBitmap")
	procSelectObject           = deskGdi32.NewProc("SelectObject")
	procBitBlt                 = deskGdi32.NewProc("BitBlt")
	procGetDIBits              = deskGdi32.NewProc("GetDIBits")
	procDeleteObject           = deskGdi32.NewProc("DeleteObject")
	procDeleteDC               = deskGdi32.NewProc("DeleteDC")

	// User32 – Bildschirm, Maus, Tastatur, Zwischenablage
	procGetDC            = deskUser32.NewProc("GetDC")
	procReleaseDC        = deskUser32.NewProc("ReleaseDC")
	procGetSystemMetrics = deskUser32.NewProc("GetSystemMetrics")
	procSetCursorPos     = deskUser32.NewProc("SetCursorPos")
	procSendInput        = deskUser32.NewProc("SendInput")
	procOpenClipboard    = deskUser32.NewProc("OpenClipboard")
	procCloseClipboard   = deskUser32.NewProc("CloseClipboard")
	procEmptyClipboard   = deskUser32.NewProc("EmptyClipboard")
	procGetClipboardData = deskUser32.NewProc("GetClipboardData")
	procSetClipboardData = deskUser32.NewProc("SetClipboardData")

	// User32 – Fensterverwaltung
	procGetForegroundWindow = deskUser32.NewProc("GetForegroundWindow")
	procSetForegroundWindow = deskUser32.NewProc("SetForegroundWindow")
	procGetWindowTextW      = deskUser32.NewProc("GetWindowTextW")
	procGetClassNameW       = deskUser32.NewProc("GetClassNameW")
	procEnumWindows         = deskUser32.NewProc("EnumWindows")
	procIsWindowVisible     = deskUser32.NewProc("IsWindowVisible")
	procShowWindow          = deskUser32.NewProc("ShowWindow")
	procSetWindowPos        = deskUser32.NewProc("SetWindowPos")
	procPostMessageW        = deskUser32.NewProc("PostMessageW")
	procGetWindowRect       = deskUser32.NewProc("GetWindowRect")

	// Kernel32 – Clipboard-Speicher
	procGlobalAlloc   = deskKernel32.NewProc("GlobalAlloc")
	procGlobalLock    = deskKernel32.NewProc("GlobalLock")
	procGlobalUnlock  = deskKernel32.NewProc("GlobalUnlock")
	procRtlMoveMemory = deskKernel32.NewProc("RtlMoveMemory")
)

// ─── Konstanten ───────────────────────────────────────────────────────────────

const (
	smCxScreen   = 0
	smCyScreen   = 1
	srccopy      = 0x00CC0020
	dibRgbColors = 0
	biRgb        = 0
	gmemMoveable = 0x0002
	cfUnicodeText = 13

	inputMouse    uint32 = 0
	inputKeyboard uint32 = 1

	// Maus-Event-Flags
	mouseeventfMove        = 0x0001
	mouseeventfLeftDown    = 0x0002
	mouseeventfLeftUp      = 0x0004
	mouseeventfRightDown   = 0x0008
	mouseeventfRightUp     = 0x0010
	mouseeventfMiddleDown  = 0x0020
	mouseeventfMiddleUp    = 0x0040
	mouseeventfWheel       = 0x0800
	mouseeventfHWheel      = 0x1000
	mouseeventfAbsolute    = 0x8000

	// Tastatur-Event-Flags
	keyeventfKeyDown = uint32(0x0000)
	keyeventfKeyUp   = uint32(0x0002)
	keyeventfUnicode = uint32(0x0004)

	// ShowWindow-Kommandos
	swHide     = 0
	swNormal   = 1
	swMinimize = 6
	swMaximize = 3
	swRestore  = 9

	// SetWindowPos-Flags (desktop-lokal, unterschiedliche Typen zu winapi_windows.go)
	deskSwpNoZOrder   = uintptr(0x0004)
	deskSwpNoActivate = uintptr(0x0010)
	deskSwpNoSize     = uintptr(0x0001)
	deskSwpNoMove     = uintptr(0x0002)

	// Nachrichten
	wmClose = 0x0010
)

// ─── INPUT-Struktur (40 Byte auf 64-bit Windows) ─────────────────────────────

type winInput struct {
	inputType uint32
	_         uint32
	union     [32]byte
}

func (i *winInput) setKeyboard(vk, scan uint16, flags uint32) {
	i.inputType = inputKeyboard
	*(*uint16)(unsafe.Pointer(&i.union[0])) = vk
	*(*uint16)(unsafe.Pointer(&i.union[2])) = scan
	*(*uint32)(unsafe.Pointer(&i.union[4])) = flags
}

func (i *winInput) setMouse(dx, dy int32, mouseData, flags uint32) {
	i.inputType = inputMouse
	*(*int32)(unsafe.Pointer(&i.union[0])) = dx
	*(*int32)(unsafe.Pointer(&i.union[4])) = dy
	*(*uint32)(unsafe.Pointer(&i.union[8])) = mouseData
	*(*uint32)(unsafe.Pointer(&i.union[12])) = flags
}

func sendInputs(inputs []winInput) {
	if len(inputs) == 0 {
		return
	}
	procSendInput.Call(
		uintptr(len(inputs)),
		uintptr(unsafe.Pointer(&inputs[0])),
		unsafe.Sizeof(winInput{}),
	)
}

// ─── RECT und Bitmap ─────────────────────────────────────────────────────────

type RECT struct {
	Left, Top, Right, Bottom int32
}

type bitmapInfoHeader struct {
	BiSize          uint32
	BiWidth         int32
	BiHeight        int32
	BiPlanes        uint16
	BiBitCount      uint16
	BiCompression   uint32
	BiSizeImage     uint32
	BiXPelsPerMeter int32
	BiYPelsPerMeter int32
	BiClrUsed       uint32
	BiClrImportant  uint32
}

type bitmapInfo struct {
	BmiHeader bitmapInfoHeader
	BmiColors [1]uint32
}

// ─── Screenshot ───────────────────────────────────────────────────────────────

func desktopScreenshot() (string, error) {
	sw, _, _ := procGetSystemMetrics.Call(smCxScreen)
	sh, _, _ := procGetSystemMetrics.Call(smCyScreen)
	w, h := int(sw), int(sh)
	if w == 0 || h == 0 {
		return "", fmt.Errorf("GetSystemMetrics: w=%d h=%d", w, h)
	}

	hdc, _, _ := procGetDC.Call(0)
	if hdc == 0 {
		return "", fmt.Errorf("GetDC fehlgeschlagen")
	}
	defer procReleaseDC.Call(0, hdc)

	mdc, _, _ := procCreateCompatibleDC.Call(hdc)
	if mdc == 0 {
		return "", fmt.Errorf("CreateCompatibleDC fehlgeschlagen")
	}
	defer procDeleteDC.Call(mdc)

	bmp, _, _ := procCreateCompatibleBitmap.Call(hdc, uintptr(w), uintptr(h))
	if bmp == 0 {
		return "", fmt.Errorf("CreateCompatibleBitmap fehlgeschlagen")
	}
	defer procDeleteObject.Call(bmp)

	procSelectObject.Call(mdc, bmp)

	r, _, _ := procBitBlt.Call(mdc, 0, 0, uintptr(w), uintptr(h), hdc, 0, 0, srccopy)
	if r == 0 {
		return "", fmt.Errorf("BitBlt fehlgeschlagen")
	}

	bmi := bitmapInfo{}
	bmi.BmiHeader.BiSize = uint32(unsafe.Sizeof(bmi.BmiHeader))
	bmi.BmiHeader.BiWidth = int32(w)
	bmi.BmiHeader.BiHeight = -int32(h)
	bmi.BmiHeader.BiPlanes = 1
	bmi.BmiHeader.BiBitCount = 32
	bmi.BmiHeader.BiCompression = biRgb

	stride := w * 4
	pixels := make([]byte, stride*h)
	r, _, _ = procGetDIBits.Call(
		mdc, bmp, 0, uintptr(h),
		uintptr(unsafe.Pointer(&pixels[0])),
		uintptr(unsafe.Pointer(&bmi)),
		dibRgbColors,
	)
	if r == 0 {
		return "", fmt.Errorf("GetDIBits fehlgeschlagen")
	}

	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := 0; i < len(pixels); i += 4 {
		img.Pix[i+0] = pixels[i+2]
		img.Pix[i+1] = pixels[i+1]
		img.Pix[i+2] = pixels[i+0]
		img.Pix[i+3] = 255
	}

	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes()), nil
}

// ─── Maus ─────────────────────────────────────────────────────────────────────

func desktopMouseMove(x, y int) error {
	r, _, _ := procSetCursorPos.Call(uintptr(x), uintptr(y))
	if r == 0 {
		return fmt.Errorf("SetCursorPos(%d,%d) fehlgeschlagen", x, y)
	}
	return nil
}

func desktopMouseClick(x, y int, button string, count int) error {
	if err := desktopMouseMove(x, y); err != nil {
		return err
	}
	time.Sleep(30 * time.Millisecond)

	var downFlag, upFlag uint32
	switch strings.ToLower(button) {
	case "right":
		downFlag, upFlag = mouseeventfRightDown, mouseeventfRightUp
	case "middle":
		downFlag, upFlag = mouseeventfMiddleDown, mouseeventfMiddleUp
	default:
		downFlag, upFlag = mouseeventfLeftDown, mouseeventfLeftUp
	}

	for i := 0; i < count; i++ {
		var down, up winInput
		down.setMouse(0, 0, 0, downFlag)
		up.setMouse(0, 0, 0, upFlag)
		sendInputs([]winInput{down, up})
		if count > 1 {
			time.Sleep(50 * time.Millisecond)
		}
	}
	return nil
}

func desktopScroll(x, y, amount int, direction string) error {
	if err := desktopMouseMove(x, y); err != nil {
		return err
	}
	if amount <= 0 {
		amount = 3
	}
	var inp winInput
	switch strings.ToLower(direction) {
	case "left":
		inp.setMouse(0, 0, uint32(int32(-amount*120)), mouseeventfHWheel)
	case "right":
		inp.setMouse(0, 0, uint32(int32(amount*120)), mouseeventfHWheel)
	case "up":
		inp.setMouse(0, 0, uint32(int32(amount*120)), mouseeventfWheel)
	default: // "down"
		inp.setMouse(0, 0, uint32(int32(-amount*120)), mouseeventfWheel)
	}
	sendInputs([]winInput{inp})
	return nil
}

func desktopDragAndDrop(x1, y1, x2, y2 int) error {
	if err := desktopMouseMove(x1, y1); err != nil {
		return err
	}
	time.Sleep(50 * time.Millisecond)
	var down winInput
	down.setMouse(0, 0, 0, mouseeventfLeftDown)
	sendInputs([]winInput{down})
	time.Sleep(100 * time.Millisecond)
	// Stufenweise Bewegung für zuverlässiges Drag
	steps := 15
	for i := 1; i <= steps; i++ {
		ix := x1 + (x2-x1)*i/steps
		iy := y1 + (y2-y1)*i/steps
		_ = desktopMouseMove(ix, iy)
		time.Sleep(15 * time.Millisecond)
	}
	time.Sleep(50 * time.Millisecond)
	var up winInput
	up.setMouse(0, 0, 0, mouseeventfLeftUp)
	sendInputs([]winInput{up})
	return nil
}

// ─── Tastatur ─────────────────────────────────────────────────────────────────

var vkNames = map[string]uint16{
	"ctrl": 0x11, "control": 0x11, "strg": 0x11,
	"alt": 0x12,
	"shift": 0x10,
	"win": 0x5B, "meta": 0x5B,
	"return": 0x0D, "enter": 0x0D,
	"space": 0x20,
	"tab": 0x09,
	"escape": 0x1B, "esc": 0x1B,
	"backspace": 0x08,
	"delete": 0x2E, "del": 0x2E,
	"insert": 0x2D, "ins": 0x2D,
	"home": 0x24, "end": 0x23,
	"pageup": 0x21, "pgup": 0x21,
	"pagedown": 0x22, "pgdown": 0x22,
	"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
	"printscreen": 0x2C,
	"f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
	"f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
	"f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

func nameToVK(name string) uint16 {
	if vk, ok := vkNames[name]; ok {
		return vk
	}
	if len(name) == 1 {
		c := rune(name[0])
		if c >= 'a' && c <= 'z' {
			return uint16(c - 'a' + 0x41)
		}
		if c >= '0' && c <= '9' {
			return uint16(c - '0' + 0x30)
		}
	}
	return 0
}

func desktopKeyPress(combo string) error {
	parts := strings.Split(strings.ToLower(combo), "+")
	var vks []uint16
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		vk := nameToVK(p)
		if vk == 0 {
			return fmt.Errorf("unbekannte Taste: %q", p)
		}
		vks = append(vks, vk)
	}
	if len(vks) == 0 {
		return fmt.Errorf("leere Tastenkombination")
	}

	inputs := make([]winInput, 0, len(vks)*2)
	for _, vk := range vks {
		var i winInput
		i.setKeyboard(vk, 0, keyeventfKeyDown)
		inputs = append(inputs, i)
	}
	for j := len(vks) - 1; j >= 0; j-- {
		var i winInput
		i.setKeyboard(vks[j], 0, keyeventfKeyUp)
		inputs = append(inputs, i)
	}
	sendInputs(inputs)
	return nil
}

func desktopTypeText(text string) error {
	for _, r := range text {
		var down, up winInput
		down.setKeyboard(0, uint16(r), keyeventfUnicode)
		up.setKeyboard(0, uint16(r), keyeventfUnicode|keyeventfKeyUp)
		sendInputs([]winInput{down, up})
		time.Sleep(10 * time.Millisecond)
	}
	return nil
}

// ─── Zwischenablage ───────────────────────────────────────────────────────────

func desktopClipboardSet(text string) error {
	wide, err := syscall.UTF16FromString(text)
	if err != nil {
		return err
	}
	size := uintptr(len(wide) * 2)

	h, _, _ := procGlobalAlloc.Call(gmemMoveable, size)
	if h == 0 {
		return fmt.Errorf("GlobalAlloc fehlgeschlagen")
	}
	ptr, _, _ := procGlobalLock.Call(h)
	if ptr == 0 {
		return fmt.Errorf("GlobalLock fehlgeschlagen")
	}
	procRtlMoveMemory.Call(ptr, uintptr(unsafe.Pointer(&wide[0])), size)
	procGlobalUnlock.Call(h)

	procOpenClipboard.Call(0)
	procEmptyClipboard.Call()
	procSetClipboardData.Call(cfUnicodeText, h)
	procCloseClipboard.Call()
	return nil
}

func desktopClipboardGet() (string, error) {
	procOpenClipboard.Call(0)
	defer procCloseClipboard.Call()

	h, _, _ := procGetClipboardData.Call(cfUnicodeText)
	if h == 0 {
		return "", nil
	}
	ptr, _, _ := procGlobalLock.Call(h)
	if ptr == 0 {
		return "", fmt.Errorf("GlobalLock fehlgeschlagen")
	}
	defer procGlobalUnlock.Call(h)

	var buf []uint16
	for i := uintptr(0); ; i++ {
		w := *(*uint16)(unsafe.Pointer(ptr + i*2))
		if w == 0 {
			break
		}
		buf = append(buf, w)
	}
	return syscall.UTF16ToString(buf), nil
}

// ─── Shell ────────────────────────────────────────────────────────────────────

func desktopShellExec(cmd string) (string, int, error) {
	c := exec.Command("cmd.exe", "/C", cmd)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	var out bytes.Buffer
	c.Stdout = &out
	c.Stderr = &out
	err := c.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		}
	}
	output := strings.TrimRight(out.String(), "\r\n")
	if len(output) > 8000 {
		output = output[:8000] + "\n[... abgeschnitten]"
	}
	return output, exitCode, nil
}

// ─── Fensterverwaltung ────────────────────────────────────────────────────────

func getWindowTitle(hwnd uintptr) string {
	buf := make([]uint16, 512)
	procGetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	return syscall.UTF16ToString(buf)
}

func getWindowClass(hwnd uintptr) string {
	buf := make([]uint16, 256)
	procGetClassNameW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	return syscall.UTF16ToString(buf)
}

// enumWindowsList: temporäre Liste für den EnumWindows-Callback
var enumWindowsList []string

func enumWindowsCallback(hwnd, _ uintptr) uintptr {
	vis, _, _ := procIsWindowVisible.Call(hwnd)
	if vis == 0 {
		return 1
	}
	title := getWindowTitle(hwnd)
	if title == "" {
		return 1
	}
	enumWindowsList = append(enumWindowsList, fmt.Sprintf("%d\t%s", hwnd, title))
	return 1 // weitermachen
}

func enumVisibleWindows() []string {
	enumWindowsList = nil
	cb := syscall.NewCallback(enumWindowsCallback)
	procEnumWindows.Call(cb, 0)
	return enumWindowsList
}

// findWindow sucht ein sichtbares Fenster dessen Titel den Suchtext enthält.
// Gibt als erstes Ergebnis das aktive Fenster zurück, falls es passt.
func findWindow(title string) uintptr {
	needle := strings.ToLower(strings.TrimSpace(title))
	for _, entry := range enumVisibleWindows() {
		parts := strings.SplitN(entry, "\t", 2)
		if len(parts) == 2 && strings.Contains(strings.ToLower(parts[1]), needle) {
			n, err := strconv.ParseUint(parts[0], 10, 64)
			if err == nil {
				return uintptr(n)
			}
		}
	}
	return 0
}

func getWindowInfo(hwnd uintptr) string {
	title := getWindowTitle(hwnd)
	class := getWindowClass(hwnd)
	var rect RECT
	procGetWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&rect)))
	w := rect.Right - rect.Left
	h := rect.Bottom - rect.Top
	return fmt.Sprintf("Handle: %d\nTitel: %s\nKlasse: %s\nPosition: %d,%d  Größe: %dx%d",
		hwnd, title, class, rect.Left, rect.Top, w, h)
}

// ─── Bekannte App-Namen ───────────────────────────────────────────────────────

// knownApps mappt gängige Kurzbezeichnungen auf ausführbare Dateien.
// Auch deutsche Umschreibungen (z.B. "excel arbeitsblatt") werden abgefangen.
var knownApps = map[string]string{
	// Microsoft Office
	"excel":                    "excel.exe",
	"excel arbeitsblatt":       "excel.exe",
	"neues excel":              "excel.exe",
	"neues excel arbeitsblatt": "excel.exe",
	"word":                     "winword.exe",
	"microsoft word":           "winword.exe",
	"microsoft excel":          "excel.exe",
	"powerpoint":               "powerpnt.exe",
	"microsoft powerpoint":     "powerpnt.exe",
	"outlook":                  "outlook.exe",
	"onenote":                  "onenote.exe",
	"access":                   "msaccess.exe",
	// Windows-Bordmittel
	"notepad":            "notepad.exe",
	"editor":             "notepad.exe",
	"texteditor":         "notepad.exe",
	"wordpad":            "wordpad.exe",
	"paint":              "mspaint.exe",
	"calculator":         "calc.exe",
	"taschenrechner":     "calc.exe",
	"explorer":           "explorer.exe",
	"dateiexplorer":      "explorer.exe",
	"cmd":                "cmd.exe",
	"eingabeaufforderung": "cmd.exe",
	"powershell":         "powershell.exe",
	"task manager":       "taskmgr.exe",
	"taskmanager":        "taskmgr.exe",
	"regedit":            "regedit.exe",
	"snipping tool":      "SnippingTool.exe",
	"snip":               "SnippingTool.exe",
	// Browser
	"chrome":             "chrome.exe",
	"google chrome":      "chrome.exe",
	"firefox":            "firefox.exe",
	"edge":               "msedge.exe",
	"microsoft edge":     "msedge.exe",
}

// ─── Dispatcher ───────────────────────────────────────────────────────────────

func DesktopExecute(cmd DesktopCommand) DesktopResult {
	res := DesktopResult{Action: cmd.Action, RequestID: cmd.RequestID}

	switch cmd.Action {

	// ── Screenshot ──────────────────────────────────────────────────────────────
	case "screenshot":
		data, err := desktopScreenshot()
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Data = data
		}

	// ── Maus: Bewegen ───────────────────────────────────────────────────────────
	case "mouse_move", "move_mouse":
		if err := desktopMouseMove(int(cmd.X), int(cmd.Y)); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Maus → (%d,%d)", int(cmd.X), int(cmd.Y))
		}

	// ── Maus: Klicks ────────────────────────────────────────────────────────────
	case "mouse_click", "click":
		btn := cmd.Button
		if btn == "" {
			btn = "left"
		}
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), btn, 1); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("%s-Klick @ (%d,%d)", btn, int(cmd.X), int(cmd.Y))
		}

	case "mouse_double_click", "double_click":
		btn := cmd.Button
		if btn == "" {
			btn = "left"
		}
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), btn, 2); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Doppelklick @ (%d,%d)", int(cmd.X), int(cmd.Y))
		}

	case "triple_click":
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), "left", 3); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Dreifachklick @ (%d,%d)", int(cmd.X), int(cmd.Y))
		}

	case "right_click":
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), "right", 1); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Rechtsklick @ (%d,%d)", int(cmd.X), int(cmd.Y))
		}

	case "middle_click":
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), "middle", 1); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Mittelklick @ (%d,%d)", int(cmd.X), int(cmd.Y))
		}

	// ── Maus: Scrollen ──────────────────────────────────────────────────────────
	case "scroll":
		dir := cmd.Direction
		if dir == "" {
			dir = "down"
		}
		amount := cmd.Amount
		if amount <= 0 {
			amount = 3
		}
		if err := desktopScroll(int(cmd.X), int(cmd.Y), amount, dir); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Scroll %s ×%d @ (%d,%d)", dir, amount, int(cmd.X), int(cmd.Y))
		}

	// ── Maus: Drag & Drop ───────────────────────────────────────────────────────
	case "drag_and_drop":
		if err := desktopDragAndDrop(int(cmd.X), int(cmd.Y), int(cmd.X2), int(cmd.Y2)); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Drag (%d,%d) → (%d,%d)", int(cmd.X), int(cmd.Y), int(cmd.X2), int(cmd.Y2))
		}

	// ── Tastatur ────────────────────────────────────────────────────────────────
	case "type_text":
		if err := desktopTypeText(cmd.Text); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Text getippt: %q", cmd.Text)
		}

	case "key_press":
		if err := desktopKeyPress(cmd.Key); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Taste: %s", cmd.Key)
		}

	// ── Shell ───────────────────────────────────────────────────────────────────
	case "shell_exec":
		out, code, err := desktopShellExec(cmd.Cmd)
		res.ExitCode = code
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = out
		}

	// ── URL / App öffnen ────────────────────────────────────────────────────────
	case "open_url":
		url := cmd.URL
		if url == "" {
			url = cmd.Text
		}
		if url == "" {
			res.Error = "keine URL angegeben"
			break
		}
		if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
			url = "https://" + url
		}
		_, _, err := desktopShellExec(`start "" "` + url + `"`)
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = "Browser geöffnet: " + url
		}

	case "open_app":
		app := strings.TrimSpace(cmd.Text)
		if app == "" {
			app = strings.TrimSpace(cmd.Cmd)
		}
		if app == "" {
			res.Error = "kein Programmname angegeben"
			break
		}
		// Bekannte App-Namen auf ausführbare Dateien mappen (DE + EN)
		if mapped, ok := knownApps[strings.ToLower(app)]; ok {
			app = mapped
		}
		// PowerShell Start-Process ist robuster als 'start ""' (kein UNC-Pfad-Bug)
		safe := strings.ReplaceAll(app, "'", "''")
		psCmd := fmt.Sprintf(`powershell -NoProfile -WindowStyle Hidden -Command "Start-Process '%s'"`, safe)
		_, _, err := desktopShellExec(psCmd)
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = "Gestartet: " + app
		}

	// ── Zwischenablage ──────────────────────────────────────────────────────────
	case "clipboard_get":
		text, err := desktopClipboardGet()
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = text
		}

	case "clipboard_set":
		if err := desktopClipboardSet(cmd.Text); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = "Zwischenablage gesetzt"
		}

	// ── Fensterverwaltung ───────────────────────────────────────────────────────
	case "get_active_window":
		hwnd, _, _ := procGetForegroundWindow.Call()
		if hwnd == 0 {
			res.Error = "kein aktives Fenster"
			break
		}
		res.Output = getWindowInfo(hwnd)

	case "list_windows":
		windows := enumVisibleWindows()
		if len(windows) == 0 {
			res.Output = "(keine sichtbaren Fenster)"
		} else {
			res.Output = strings.Join(windows, "\n")
		}

	case "focus_window":
		needle := cmd.Text
		if needle == "" {
			needle = cmd.WindowID
		}
		if needle == "" {
			res.Error = "kein Fenstername (text) angegeben"
			break
		}
		hwnd := findWindow(needle)
		if hwnd == 0 {
			res.Error = "Fenster nicht gefunden: " + needle
			break
		}
		procShowWindow.Call(hwnd, swRestore)
		procSetForegroundWindow.Call(hwnd)
		res.Output = fmt.Sprintf("Fenster fokussiert: %s", getWindowTitle(hwnd))

	case "close_window":
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		procPostMessageW.Call(hwnd, wmClose, 0, 0)
		res.Output = fmt.Sprintf("Fenster geschlossen: %s", getWindowTitle(hwnd))

	case "minimize_window":
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		procShowWindow.Call(hwnd, swMinimize)
		res.Output = "Fenster minimiert"

	case "maximize_window":
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		procShowWindow.Call(hwnd, swMaximize)
		res.Output = "Fenster maximiert"

	case "restore_window":
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		procShowWindow.Call(hwnd, swNormal)
		res.Output = "Fenster wiederhergestellt"

	case "resize_window":
		if cmd.Width == 0 || cmd.Height == 0 {
			res.Error = "width und height müssen angegeben werden"
			break
		}
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		// SWP_NOMOVE: Position beibehalten, nur Größe ändern
		procSetWindowPos.Call(hwnd, 0, 0, 0, uintptr(cmd.Width), uintptr(cmd.Height), deskSwpNoZOrder|deskSwpNoMove|deskSwpNoActivate)
		res.Output = fmt.Sprintf("Fenstergröße: %dx%d", cmd.Width, cmd.Height)

	case "move_window":
		var hwnd uintptr
		if cmd.Text != "" {
			hwnd = findWindow(cmd.Text)
			if hwnd == 0 {
				res.Error = "Fenster nicht gefunden: " + cmd.Text
				break
			}
		} else {
			hwnd, _, _ = procGetForegroundWindow.Call()
		}
		// SWP_NOSIZE: Größe beibehalten, nur Position ändern
		procSetWindowPos.Call(hwnd, 0, uintptr(int(cmd.X)), uintptr(int(cmd.Y)), 0, 0, deskSwpNoZOrder|deskSwpNoSize|deskSwpNoActivate)
		res.Output = fmt.Sprintf("Fenster verschoben → (%d,%d)", int(cmd.X), int(cmd.Y))

	default:
		res.Error = "unbekannte Aktion: " + cmd.Action
	}

	return res
}
