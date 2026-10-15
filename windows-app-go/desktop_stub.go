//go:build !windows

package main

// DesktopExecute – Stub für Nicht-Windows-Builds.
func DesktopExecute(cmd DesktopCommand) DesktopResult {
	return DesktopResult{
		Action:    cmd.Action,
		RequestID: cmd.RequestID,
		Error:     "Desktop-Steuerung nur unter Windows verfügbar",
	}
}
