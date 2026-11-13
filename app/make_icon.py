"""Gera o ícone do Miau 3D Studio (gato laranja) em .ico e .png."""
from PIL import Image, ImageDraw

S = 512
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=110, fill=(15, 17, 21, 255))
orange = (255, 138, 61, 255)
bg = (15, 17, 21, 255)
k = S / 64
pts = [(10, 54), (10, 14), (24, 26), (40, 26), (54, 14), (54, 54)]
d.polygon([(x * k, y * k) for x, y in pts], fill=orange)
for cx in (24, 40):
    d.ellipse([(cx - 4) * k, 34 * k, (cx + 4) * k, 42 * k], fill=bg)
d.polygon([(29 * k, 46 * k), (35 * k, 46 * k), (32 * k, 49 * k)], fill=bg)
img.save(r'D:\Miau3DStudio\app\ui\icon.png')
img.save(r'D:\Miau3DStudio\app\miau.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('ok')
