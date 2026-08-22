import sys

from PIL import Image, ImageDraw


def create_squircle_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), size], radius=radius, fill=255)
    return mask


img_path = sys.argv[1]
out_path = sys.argv[2]
img = Image.open(img_path).convert("RGBA")
# The image is 1024x1024 with a centered squircle.
# Crop tightly to the squircle.
bbox = (200, 200, 824, 824)
cropped = img.crop(bbox)
mask = create_squircle_mask(cropped.size, 120)
cropped.putalpha(mask)
cropped.save(out_path)
