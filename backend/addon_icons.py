"""Symbole der Browser-Erweiterung – gebrandet erzeugt statt fest mitgeliefert.

**Warum das ueberhaupt sein muss:** das Symbol steht in der Symbolleiste JEDES
Arbeitsplatzes. Ein White-Label-Produkt darf dort nicht das Zeichen eines
fremden Herstellers zeigen – dieselbe Begruendung wie beim Namen im Manifest
(``jira_assist._manifest_gebrandet``), bei der Marke im Fenster
(``_popup_gebrandet``) und bei der Mail-Kategorie.

Gemeldet 2026-08-28: "das Symbol des Jira plugin im Browser ist leider immer
noch ungebranded". Zutreffend – die vier PNG im Repo waren **fest verdrahtet**
und trugen sogar die Kundenfarbe. Genau der Fehler, der aus ``popup.css`` schon
einmal entfernt wurde (dort ``#b80f2e``): die Farbe gehoert zum Server, nicht
ins ausgelieferte Paket.

WAS GEZEICHNET WIRD – und warum genau das
------------------------------------------
Das Symbol bildet den **Avatar oben links** in der Anwendung nach
(``.topbar-avatar``): runder Kreis, Verlauf 135° von der Akzentfarbe zu ihrer
dunklen Variante, darauf der Buchstabe in Weiss. Ohne Branding ist das das
``J``; mit Branding gilt dieselbe Regel wie in ``branding.js::brandOne``:

* ``logo_mode == "image"`` und eine Logodatei vorhanden → **das Logo**, auf
  weissem Grund (ein Markenlogo ist auf Weiss ausgelegt – auf dem Akzent-Verlauf
  verschwindet ein Logo in Markenfarbe).
* sonst → **``core_letter``** (hoechstens zwei Zeichen, wie im Frontend).

Dieses Modul RECHNET NUR. Es liest keine Konfiguration und kennt keine Pfade –
was gezeichnet werden soll, gibt der Aufrufer mit. So bleibt es ohne Server
testbar, und es entsteht keine zweite Wahrheit neben ``main.py``.
"""

from __future__ import annotations

import io

# Die Groessen aus dem Manifest. Aendert sich dort etwas, faellt es im Test auf:
# ein Manifest, das auf ein fehlendes Symbol zeigt, laesst die Installation mit
# einer generischen Meldung scheitern.
GROESSEN = (16, 32, 48, 128)

# Vierfach zeichnen, dann verkleinern. OHNE DAS IST DER KREIS TREPPIG und der
# Buchstabe ausgefranst – PIL kennt kein Antialiasing beim Zeichnen.
UEBERABTASTUNG = 4

# Jarvis-Standard, identisch zu `--accent`/`--accent-dark` in theme.css. Steht
# hier als Rueckfall, NICHT als Vorgabe fuer gebrandete Installationen.
STANDARD_AKZENT = "#9B59B6"
STANDARD_BUCHSTABE = "J"

# Fette Schrift, in dieser Reihenfolge gesucht. DejaVu ist auf Debian gesetzt;
# die anderen sind fuer den Fall, dass jemand das System abgespeckt hat.
_SCHRIFTEN = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)


def _hex_zu_rgb(wert: str) -> tuple:
    """``#RGB``/``#RRGGBB`` → ``(r, g, b)``; unbrauchbar → Standardton.

    Der Wert kommt aus einem Formular. Ein Tippfehler darf kein Symbol
    verhindern – er faellt auf den Standardton zurueck, und das Paket bleibt
    baubar.
    """
    t = (wert or "").strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        t = STANDARD_AKZENT.lstrip("#")
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return _hex_zu_rgb(STANDARD_AKZENT)


def dunkler(rgb: tuple) -> tuple:
    """Die dunkle Variante des Akzents – Faktor 0,78 je Kanal.

    GENAU DIESELBE RECHNUNG wie in ``branding.js`` (``--accent-dark``). Eine
    eigene Formel hier haette ein Symbol erzeugt, dessen Verlauf sich von dem
    im Fenster daneben unterscheidet.
    """
    return tuple(round(k * 0.78) for k in rgb)


def _schrift(groesse: int):
    """Fette Schrift in der gewuenschten Groesse – oder ``None``."""
    from PIL import ImageFont  # noqa: PLC0415

    for pfad in _SCHRIFTEN:
        try:
            return ImageFont.truetype(pfad, groesse)
        except Exception:  # noqa: BLE001
            continue
    return None


def _verlauf(kante: int, von: tuple, bis: tuple):
    """Quadrat mit linearem Verlauf 135° (links oben → rechts unten).

    Klein gerechnet und dann hochskaliert: ein Verlauf ist linear, das Ergebnis
    ist identisch – aber es sind 4096 statt 262144 Pixel in einer
    Python-Schleife.
    """
    from PIL import Image  # noqa: PLC0415

    n = 64
    punkte = []
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * n - 2)
            punkte.append(tuple(round(von[i] + (bis[i] - von[i]) * t) for i in range(3)))
    klein = Image.new("RGB", (n, n))
    klein.putdata(punkte)
    return klein.resize((kante, kante), Image.BILINEAR)


def _kreis_maske(kante: int):
    from PIL import Image, ImageDraw  # noqa: PLC0415

    maske = Image.new("L", (kante, kante), 0)
    ImageDraw.Draw(maske).ellipse((0, 0, kante - 1, kante - 1), fill=255)
    return maske


def _buchstabe_zeichnen(kante: int, text: str, akzent: tuple):
    """Kreis mit Verlauf und weissem Buchstaben – der Avatar der Anwendung."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    bild = Image.new("RGBA", (kante, kante), (0, 0, 0, 0))
    flaeche = _verlauf(kante, akzent, dunkler(akzent)).convert("RGBA")
    bild.paste(flaeche, (0, 0), _kreis_maske(kante))

    # DIE SCHRIFTGROESSE WIRD GEMESSEN, NICHT GESCHAETZT: "J" und "nx" sind
    # verschieden breit, und ein fester Faktor laesst zwei Zeichen ueber den
    # Kreisrand laufen. Gesucht ist die groesste Schrift, die in 62 % des
    # Durchmessers passt (der Rest ist Luft, wie im Frontend).
    ziel = kante * 0.62
    groesse = int(kante * 0.6)
    schrift = None
    while groesse > 4:
        s = _schrift(groesse)
        if s is None:
            return None
        kasten = ImageDraw.Draw(bild).textbbox((0, 0), text, font=s)
        if (kasten[2] - kasten[0]) <= ziel and (kasten[3] - kasten[1]) <= ziel:
            schrift = s
            break
        groesse = int(groesse * 0.92)
    if schrift is None:
        return None

    zeichner = ImageDraw.Draw(bild)
    k = zeichner.textbbox((0, 0), text, font=schrift)
    # Ueber den KASTEN zentrieren, nicht ueber den Zeilenursprung: sonst sitzt
    # der Buchstabe zu tief (Unterlaenge) und wirkt aus der Mitte gerutscht.
    x = (kante - (k[2] - k[0])) / 2 - k[0]
    y = (kante - (k[3] - k[1])) / 2 - k[1]
    zeichner.text((x, y), text, font=schrift, fill=(255, 255, 255, 255))
    return bild


def _logo_zeichnen(kante: int, rohdaten: bytes):
    """Das Markenlogo auf weissem Kreis – oder ``None``, wenn es nicht lesbar ist.

    Weisser Grund statt Akzent-Verlauf: genau das macht ``branding.js`` fuer die
    flachen Avatar-Kreise auch, und aus demselben Grund – ein Logo in
    Markenfarbe verschwindet sonst auf der Markenfarbe.
    """
    from PIL import Image  # noqa: PLC0415

    try:
        logo = Image.open(io.BytesIO(rohdaten))
        logo.load()
        logo = logo.convert("RGBA")
    except Exception:  # noqa: BLE001
        # SVG kann PIL nicht, und eine beschaedigte Datei soll das Paket nicht
        # verhindern: der Aufrufer faellt dann auf den Buchstaben zurueck.
        return None

    bild = Image.new("RGBA", (kante, kante), (0, 0, 0, 0))
    grund = Image.new("RGBA", (kante, kante), (255, 255, 255, 255))
    bild.paste(grund, (0, 0), _kreis_maske(kante))

    # `contain`, nicht `cover`: ein Logo darf nicht beschnitten werden.
    innen = int(kante * 0.74)          # Rand, damit es im Kreis nicht anstoesst
    logo.thumbnail((innen, innen), Image.LANCZOS)
    bild.alpha_composite(logo, ((kante - logo.width) // 2,
                                (kante - logo.height) // 2))
    return bild


def bauen(akzent: str = "", buchstabe: str = "", logo: bytes = b"",
          groessen=GROESSEN) -> dict | None:
    """``{groesse: png_bytes}`` – oder ``None``, wenn nichts gezeichnet werden kann.

    ``None`` heisst fuer den Aufrufer: nimm die mitgelieferten Dateien. Ein
    Paket OHNE Symbole waere der schlechtere Ausgang – Chrome verweigert dann
    die Installation, und die Meldung nennt den Grund nicht.

    Reihenfolge: ein brauchbares ``logo`` gewinnt, sonst der Buchstabe. Genau
    die Reihenfolge aus ``branding.js::brandOne``.
    """
    try:
        from PIL import Image  # noqa: PLC0415, F401
    except Exception:  # noqa: BLE001
        return None

    farbe = _hex_zu_rgb(akzent)
    # Wie im Frontend: hoechstens zwei Zeichen. Ein langer Firmenname im
    # Buchstabenfeld wuerde sonst zu einer unlesbaren Miniatur.
    text = (buchstabe or "").strip()[:2] or STANDARD_BUCHSTABE

    raus = {}
    for groesse in groessen:
        kante = groesse * UEBERABTASTUNG
        bild = _logo_zeichnen(kante, logo) if logo else None
        if bild is None:
            bild = _buchstabe_zeichnen(kante, text, farbe)
        if bild is None:
            return None            # keine Schrift → gar nichts versprechen
        from PIL import Image  # noqa: PLC0415

        klein = bild.resize((groesse, groesse), Image.LANCZOS)
        puffer = io.BytesIO()
        klein.save(puffer, format="PNG", optimize=True)
        raus[groesse] = puffer.getvalue()
    return raus
