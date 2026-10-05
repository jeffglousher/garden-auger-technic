"""Compose the current project's native Bambu plate previews."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw
from render_common import font

ROOT=Path(__file__).resolve().parents[1]


def main():
    proof=json.loads((ROOT/'bambu-slice-verification.json').read_text())
    project=ROOT/proof['source_project']
    digest=hashlib.sha256(project.read_bytes()).hexdigest()
    assert digest==proof['source_project_sha256']
    sheet=Image.new('RGB',(1600,1300),'#11151B')
    draw=ImageDraw.Draw(sheet)
    draw.text((30,20),'Current Bambu project | Four verified plates',font=font(35,True),fill='#EFF5FA')
    draw.text((30,75),'Native slicer previews | Corrected housing | Saved PETG / PLA profiles and object overrides',font=font(23),fill='#B8C8D8')
    titles=['Housing halves — PETG','Auger — PETG','Square adapter — PETG','Loose sleeve — PLA']
    with zipfile.ZipFile(project) as archive:
        for i,plate in enumerate(proof['plates']):
            x=30+(i%2)*790;y=130+(i//2)*550
            draw.rounded_rectangle((x,y,x+750,y+525),radius=15,fill='#181C22',outline='#384552',width=2)
            draw.text((x+20,y+15),f"{plate['plate']}  {titles[i]}",font=font(27,True),fill='#EFF5FA')
            seconds=plate['time_seconds']
            draw.text((x+20,y+55),f"Estimate: {seconds//3600} h {(seconds%3600)//60} min | {plate['filament_weight_g']:.1f} g",font=font(21),fill='#83D2C3')
            image=Image.open(io.BytesIO(archive.read(f"Metadata/plate_{plate['plate']}.png"))).convert('RGBA')
            image.thumbnail((710,405))
            sheet.paste(image,(x+(750-image.width)//2,y+100+(405-image.height)//2),image)
    draw.text((30,1258),'Five closed print solids. No printer commands sent. Slicer estimates include the saved supports and interfaces.',font=font(22),fill='#B8C8D8')
    output=ROOT/'renders/bambu-print-layout.png'
    sheet.save(output)
    (ROOT/'renders/bambu-print-layout-provenance.json').write_text(json.dumps({
        'image':output.name,'method':'Four freshly generated native Bambu CLI plate previews composed with labels',
        'source_project':project.name,'source_project_sha256':digest,
        'native_slicer':proof['native_slicer'],'verification':'bambu-slice-verification.json'},indent=2)+'\n')
    print('Current native Bambu plate layout rendered',flush=True)


if __name__=='__main__':main()
