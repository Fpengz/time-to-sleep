from PIL import Image, ImageDraw

def create_template():
    # 32x32 image with transparent background
    img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # The SVG path: 
    # M8 9h16v3H8zm0 6h10v3H8zm0 6h16v3H8z
    # That means:
    # Rect 1: x=8, y=9, w=16, h=3
    # Rect 2: x=8, y=15, w=10, h=3
    # Rect 3: x=8, y=21, w=16, h=3
    
    # We'll draw them in black. The alpha channel is what macOS uses for Template Images.
    draw.rectangle([8, 9, 8+16-1, 9+3-1], fill=(0, 0, 0, 255))
    draw.rectangle([8, 15, 8+10-1, 15+3-1], fill=(0, 0, 0, 255))
    draw.rectangle([8, 21, 8+16-1, 21+3-1], fill=(0, 0, 0, 255))
    
    img.save("MenuIcon.png")

create_template()
