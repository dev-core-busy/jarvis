from PIL import Image
import os

def make_transparent():
    input_path = "favicon.png"
    output_path = "favicon.png"
    
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        return

    img = Image.open(input_path)
    img = img.convert("RGBA")
    datas = img.getdata()

    # Die verwendete Hintergrundfarbe war #0a0e17 -> (10, 14, 23)
    # Kleine Toleranz fuer eventuelle Kantenglaettungs-Artefakte
    bg_color = (10, 14, 23)
    tolerance = 20

    newData = []
    for item in datas:
        # Liegt der Bildpunkt nahe an der Hintergrundfarbe?
        if abs(item[0] - bg_color[0]) < tolerance and \
           abs(item[1] - bg_color[1]) < tolerance and \
           abs(item[2] - bg_color[2]) < tolerance:
            # Alpha auf 0 setzen (transparent)
            newData.append((0, 0, 0, 0))
        else:
            newData.append(item)

    img.putdata(newData)
    img.save(output_path, "PNG")
    print("✅ Background removed and transparency applied")

if __name__ == "__main__":
    make_transparent()
