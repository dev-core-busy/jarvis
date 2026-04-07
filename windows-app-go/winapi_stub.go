//go:build !windows

package main

func EnsureSingleInstance() bool                                             { return true }
func MakeAvatarWindowFrameless()                                            {}
func MakeChatWindowFrameless()                                              {}
func MoveAvatarWindow(dx, dy float64)                                       {}
func ClearAvatarHWND()                                                      {}
func GetAvatarPosition() (x, y int)                                         { return 0, 0 }
func SetAvatarPosition(x, y int)                                            {}
func StartNativeSysTray(_, _, _, _ func(), _, _ func() bool)                {}
func SetTTSVoice(voice string)                                               {}
func SetTTSServer(serverURL, apiKey string)                                  {}
func ListTTSVoices() []string                                                { return nil }
func FetchBackendVoices(serverURL, apiKey string) ([]string, []string)       { return nil, nil }
func PlayTestTone()                                                          {}
func PlayTestVoice(voiceID string)                                           {}
func PlayWAVBytes(data []byte)                                               {}
func PlayBackendTTS(serverURL, apiKey, text, voiceID string) error           { return nil }
func SpeakText(text string)                                                  {}
func ShowTrayBalloon(title, text string)                                     {}
