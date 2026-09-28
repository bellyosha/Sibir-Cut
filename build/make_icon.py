from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets"
OUT.mkdir(parents=True,exist_ok=True)

S=512
im=Image.new("RGBA",(S,S),(0,0,0,0))
d=ImageDraw.Draw(im)

# Dark rounded tile.
pad=28
d.rounded_rectangle((pad,pad,S-pad,S-pad),radius=112,fill=(15,23,42,255))

# Stylized cutting path / letter S.
path=[(158,150),(220,112),(320,118),(365,164),(350,210),(302,236),(214,246),(168,278),(157,330),(198,382),(300,398),(362,366)]
d.line(path,fill=(255,255,255,255),width=34,joint="curve")

# Orange blade tip cutting into the lower stroke.
blade=[(330,321),(411,350),(352,407)]
d.polygon(blade,fill=(249,115,22,255))
d.line([(325,315),(365,355)],fill=(255,237,213,255),width=14)

# Teal calibration dot / tool point.
d.ellipse((105,235,149,279),fill=(20,184,166,255))
d.ellipse((117,247,137,267),fill=(236,253,245,255))

png=OUT/"SibirCut.png"
ico=OUT/"SibirCut.ico"
im.resize((256,256),Image.Resampling.LANCZOS).save(png)
im.save(ico,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(ico)
