//go:build windows

package main

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"image/png"
	"os/exec"
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

	// Kernel32 – Clipboard-Speicher
	procGlobalAlloc     = deskKernel32.NewProc("GlobalAlloc")
	procGlobalLock      = deskKernel32.NewProc("GlobalLock")
	procGlobalUnlock    = deskKernel32.NewProc("GlobalUnlock")
	procRtlMoveMemory   = deskKernel32.NewProc("RtlMoveMemory")
)

// ─── Konstanten ───────────────────────────────────────────────────────────────

const (
	smCxScreen    = 0
	smCyScreen    = 1
	srccopy       = 0x00CC0020
	dibRgbColors  = 0
	biRgb         = 0
	gmemMoveable  = 0x0002
	cfUnicodeText = 13

	inputMouse    uint32 = 0
	inputKeyboard uint32 = 1

	// Maus-Event-Flags
	mouseeventfMove      = 0x0001
	mouseeventfLeftDown  = 0x0002
	mouseeventfLeftUp    = 0x0004
	mouseeventfRightDown = 0x0008
	mouseeventfRightUp   = 0x0010
	mouseeventfMiddleDown = 0x0020
	mouseeventfMiddleUp  = 0x0040
	mouseeventfWheel     = 0x0800
	mouseeventfAbsolute  = 0x8000

	// Tastatur-Event-Flags
	keyeventfKeyDown = uint32(0x0000)
	keyeventfKeyUp   = uint32(0x0002)
	keyeventfUnicode = uint32(0x0004)
)

// ─── INPUT-Struktur (40 Byte auf 64-bit Windows) ─────────────────────────────
// type(4) + padding(4) + union(32) = 40

type winInput struct {
	inputType uint32
	_         uint32
	union     [32]byte
}

// setKeyboard befüllt die KEYBDINPUT-Union:
// offset 0: wVk(2), offset 2: wScan(2), offset 4: dwFlags(4), offset 8: time(4)
// offset 12: padding(4), offset 16: dwExtraInfo(8)
func (i *winInput) setKeyboard(vk, scan uint16, flags uint32) {
	i.inputType = inputKeyboard
	*(*uint16)(unsafe.Pointer(&i.union[0])) = vk
	*(*uint16)(unsafe.Pointer(&i.union[2])) = scan
	*(*uint32)(unsafe.Pointer(&i.union[4])) = flags
}

// setMouse befüllt die MOUSEINPUT-Union:
// offset 0: dx(4), offset 4: dy(4), offset 8: mouseData(4), offset 12: dwFlags(4)
// offset 16: time(4), offset 20: padding(4), offset 24: dwExtraInfo(8)
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

// ─── BITMAPINFOHEADER ─────────────────────────────────────────────────────────

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
	bmi.BmiHeader.BiHeight = -int32(h) // negativ = top-down
	bmi.BmiHeader.BiPlanes = 1
	bmi.BmiHeader.BiBitCount = 32
	bmi.BmiHeader.BiCompression = biRgb

	stride := w * 4
	pixels := make([]byte, stride*h)
	r, _, _ = procGetDIBits.Call(
		mdc, bmp,
		0, uintptr(h),
		uintptr(unsafe.Pointer(&pixels[0])),
		uintptr(unsafe.Pointer(&bmi)),
		dibRgbColors,
	)
	if r == 0 {
		return "", fmt.Errorf("GetDIBits fehlgeschlagen")
	}

	// BGRA → RGBA
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := 0; i < len(pixels); i += 4 {
		img.Pix[i+0] = pixels[i+2] // R
		img.Pix[i+1] = pixels[i+1] // G
		img.Pix[i+2] = pixels[i+0] // B
		img.Pix[i+3] = 255          // A
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

func desktopMouseClick(x, y int, button string, double bool) error {
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

	click := func() {
		var down, up winInput
		down.setMouse(0, 0, 0, downFlag)
		up.setMouse(0, 0, 0, upFlag)
		sendInputs([]winInput{down, up})
		time.Sleep(50 * time.Millisecond)
	}
	click()
	if double {
		click()
	}
	return nil
}

func desktopScroll(x, y, amount int) error {
	if err := desktopMouseMove(x, y); err != nil {
		return err
	}
	var inp winInput
	inp.setMouse(0, 0, uint32(amount*120), mouseeventfWheel)
	sendInputs([]winInput{inp})
	return nil
}

// ─── Tastatur ─────────────────────────────────────────────────────────────────

// VK-Code-Tabelle für benannte Tasten
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
	// Einzelnes Zeichen: A-Z → 0x41-0x5A, 0-9 → 0x30-0x39
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
	// Ausgabe auf 8000 Zeichen begrenzen (Token-Schutz)
	if len(output) > 8000 {
		output = output[:8000] + "\n[... abgeschnitten]"
	}
	return output, exitCode, nil
}

// ─── Dispatcher ───────────────────────────────────────────────────────────────

// DesktopExecute verarbeitet einen DesktopCommand und gibt das Ergebnis zurück.
func DesktopExecute(cmd DesktopCommand) DesktopResult {
	res := DesktopResult{Action: cmd.Action, RequestID: cmd.RequestID}

	switch cmd.Action {

	case "screenshot":
		data, err := desktopScreenshot()
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Data = data
		}

	case "mouse_move":
		if err := desktopMouseMove(int(cmd.X), int(cmd.Y)); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Maus bewegt zu (%d, %d)", int(cmd.X), int(cmd.Y))
		}

	case "mouse_click":
		btn := cmd.Button
		if btn == "" {
			btn = "left"
		}
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), btn, false); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("%s-Klick bei (%d, %d)", btn, int(cmd.X), int(cmd.Y))
		}

	case "mouse_double_click":
		btn := cmd.Button
		if btn == "" {
			btn = "left"
		}
		if err := desktopMouseClick(int(cmd.X), int(cmd.Y), btn, true); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Doppelklick bei (%d, %d)", int(cmd.X), int(cmd.Y))
		}

	case "scroll":
		amount := int(cmd.X) // X-Feld zweckentfremdet für Betrag (positiv=up, negativ=down)
		if err := desktopScroll(int(cmd.X), int(cmd.Y), amount); err != nil {
			res.Error = err.Error()
		} else {
			res.Output = fmt.Sprintf("Scroll %d bei (%d,%d)", amount, int(cmd.X), int(cmd.Y))
		}

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
			res.Output = fmt.Sprintf("Taste gedrückt: %s", cmd.Key)
		}

	case "open_url":
		url := cmd.URL
		if url == "" {
			url = cmd.Text // Fallback falls Backend url in text schickt
		}
		if url == "" {
			res.Error = "keine URL angegeben"
			break
		}
		// http/https Präfix sicherstellen
		if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
			url = "https://" + url
		}
		out, code, err := desktopShellExec(`start "" "` + url + `"`)
		res.ExitCode = code
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = "Browser geöffnet: " + url
			_ = out
		}

	case "open_app":
		app := cmd.Text
		if app == "" {
			app = cmd.Cmd
		}
		if app == "" {
			res.Error = "kein Programmname angegeben"
			break
		}
		out, code, err := desktopShellExec(`start "" ` + app)
		res.ExitCode = code
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = "Gestartet: " + app
			_ = out
		}

	case "shell_exec":
		out, code, err := desktopShellExec(cmd.Cmd)
		res.ExitCode = code
		if err != nil {
			res.Error = err.Error()
		} else {
			res.Output = out
		}

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

	default:
		res.Error = "unbekannte Aktion: " + cmd.Action
	}

	return res
}
