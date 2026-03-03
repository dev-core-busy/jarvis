from PIL import Image, ImageDraw, ImageFont
import os

def create_favicon():
    size = 512
    # Colors from CSS
    bg_color = (10, 14, 23)      # #0a0e17
    accent_color = (99, 102, 241) # #6366f1
    
    # Create image
    img = Image.new('RGB', (size, size), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Draw ring
    margin = 40
    width = 15
    draw.ellipse([margin, margin, size - margin, size - margin], outline=accent_color, width=width)
    
    # Draw 'J'
    try:
        # Try to find a sans-serif font
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
        ]
        font = None
        for path in font_paths:
            if os.path.exists(path):
                font = ImageFont.truetype(path, 300)
                break
        if not font:
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
        
    text = "J"
    # Get text size
    w, h = draw.textbbox((0, 0), text, font=font)[2:]
    draw.text(((size-w)/2, (size-h)/2 - 20), text, fill=accent_color, font=font)
    
    # Save
    img.save('favicon.png')
    print("✅ favicon.png created successfully")

if __name__ == "__main__":
    create_favicon()
