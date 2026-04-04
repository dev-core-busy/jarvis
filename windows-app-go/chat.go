package main

import (
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/widget"
)

type MessageRole string

const (
	RoleUser   MessageRole = "user"
	RoleJarvis MessageRole = "jarvis"
	RoleStatus MessageRole = "status"
)

type ChatMessage struct {
	Role MessageRole
	Text string
	Time time.Time
}

// ── Chat-Manager ──────────────────────────────────────────────────────────────

type ChatWidget struct {
	mu       sync.Mutex
	messages []ChatMessage

	Scroll    *container.Scroll
	MsgBox    *fyne.Container
	Input     *widget.Entry
	SendBtn   *widget.Button
	StatusLbl *canvas.Text

	OnSend func(string)
}

func NewChatWidget() *ChatWidget {
	c := &ChatWidget{}

	c.MsgBox = container.NewVBox()
	c.Scroll = container.NewScroll(c.MsgBox)
	c.Scroll.Direction = container.ScrollVerticalOnly

	c.Input = widget.NewMultiLineEntry()
	c.Input.SetPlaceHolder("Nachricht an Jarvis…")
	c.Input.OnChanged = func(_ string) {} // aktiviert OnSubmitted
	// Enter = Senden (Shift+Enter = Zeilenumbruch nicht direkt unterstützt im Entry)

	c.SendBtn = widget.NewButton("↑", func() { c.submit() })

	c.StatusLbl = canvas.NewText("", jc.muted)
	c.StatusLbl.TextSize = 11
	c.StatusLbl.Alignment = fyne.TextAlignCenter

	return c
}

// Layout gibt das fertige Container-Objekt zurück, das ins Fenster eingebettet wird.
func (c *ChatWidget) Layout() fyne.CanvasObject {
	inputRow := container.NewBorder(nil, nil, nil, c.SendBtn, c.Input)
	bottom := container.NewVBox(c.StatusLbl, inputRow)
	return container.NewBorder(nil, bottom, nil, nil, c.Scroll)
}

func (c *ChatWidget) submit() {
	text := c.Input.Text
	if text == "" {
		return
	}
	c.Input.SetText("")
	if c.OnSend != nil {
		c.OnSend(text)
	}
}

// ── Nachrichten hinzufügen ────────────────────────────────────────────────────

func (c *ChatWidget) AddMessage(role MessageRole, text string) {
	c.mu.Lock()
	msg := ChatMessage{Role: role, Text: text, Time: time.Now()}
	c.messages = append(c.messages, msg)
	c.mu.Unlock()

	row := c.buildRow(msg)
	c.MsgBox.Add(row)
	c.MsgBox.Refresh()
	c.scrollToBottom()
}

// AppendToLast hängt Text an die letzte Jarvis-Nachricht an (Streaming).
func (c *ChatWidget) AppendToLast(text string) {
	c.mu.Lock()
	if len(c.messages) == 0 || c.messages[len(c.messages)-1].Role != RoleJarvis {
		c.mu.Unlock()
		c.AddMessage(RoleJarvis, text)
		return
	}
	c.messages[len(c.messages)-1].Text += text
	last := c.messages[len(c.messages)-1]
	c.mu.Unlock()

	// Letztes Widget ersetzen
	idx := len(c.MsgBox.Objects) - 1
	if idx >= 0 {
		c.MsgBox.Objects[idx] = c.buildRow(last)
		c.MsgBox.Refresh()
	}
	c.scrollToBottom()
}

func (c *ChatWidget) SetStatus(text string) {
	c.StatusLbl.Text = text
	c.StatusLbl.Refresh()
}

func (c *ChatWidget) SetInputEnabled(enabled bool) {
	if enabled {
		c.Input.Enable()
		c.SendBtn.Enable()
	} else {
		c.Input.Disable()
		c.SendBtn.Disable()
	}
}

// ── Bubble-Rendering ──────────────────────────────────────────────────────────

func (c *ChatWidget) buildRow(msg ChatMessage) fyne.CanvasObject {
	const maxBubbleW float32 = 290

	switch msg.Role {
	case RoleStatus:
		lbl := canvas.NewText(msg.Text, jc.muted)
		lbl.TextSize = 11
		lbl.Alignment = fyne.TextAlignCenter
		return container.NewCenter(lbl)

	case RoleUser:
		bg := canvas.NewRectangle(jc.userBubble)
		bg.CornerRadius = 12
		ts := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		ts.TextSize = 10
		lbl := widget.NewLabel(msg.Text)
		lbl.Wrapping = fyne.TextWrapWord
		inner := container.NewVBox(lbl, container.NewHBox(layout.NewSpacer(), ts))
		content := container.NewStack(bg, container.NewPadded(inner))
		sized := container.NewGridWrap(fyne.NewSize(maxBubbleW, 0), content)
		return container.NewHBox(layout.NewSpacer(), sized)

	default: // RoleJarvis
		bg := canvas.NewRectangle(jc.jarvisBubble)
		bg.CornerRadius = 12
		ts := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		ts.TextSize = 10
		lbl := widget.NewLabel(msg.Text)
		lbl.Wrapping = fyne.TextWrapWord
		inner := container.NewVBox(lbl, ts)
		content := container.NewStack(bg, container.NewPadded(inner))
		sized := container.NewGridWrap(fyne.NewSize(maxBubbleW, 0), content)
		return container.NewHBox(sized, layout.NewSpacer())
	}
}

func (c *ChatWidget) scrollToBottom() {
	go func() {
		time.Sleep(60 * time.Millisecond)
		c.Scroll.ScrollToBottom()
	}()
}
