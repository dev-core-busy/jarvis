namespace AiMouse.Configuration;
// Attrappe fuer die Registry – haelt dasselbe Paar im Speicher.
internal static class ConfigStore
{
    private static string _ziel = string.Empty, _von = string.Empty;
    public static int Schreibzaehler;
    public static void MerkeUpdateVersuch(string ziel, string eigene)
    { _ziel = ziel ?? ""; _von = eigene ?? ""; Schreibzaehler++; }
    public static (string Ziel, string Von) LadeUpdateVersuch() => (_ziel, _von);
    public static void Vergessen() { _ziel = ""; _von = ""; }
}
