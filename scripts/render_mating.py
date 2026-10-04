"""Make the mating overview from the checked exact-CAD drawing pages."""
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def main():
    pages=[Image.open(ROOT/f'.build/drawing-page-{i}.png').convert('RGB') for i in [1,2]]
    result=Image.new('RGB',(max(p.width for p in pages),sum(p.height for p in pages)),(255,255,255))
    offset=0
    for p in pages:result.paste(p,(0,offset));offset+=p.height
    result.save(ROOT/'renders/square-mating-dimensions.png')
if __name__=='__main__':main()
