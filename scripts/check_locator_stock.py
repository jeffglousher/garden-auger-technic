import sys,json
from pathlib import Path
sys.path.insert(0,'scripts')
from cad_client import CadClient
from build_servo_rear_fit_test import read_model
p=Path('locator-fit-geometry-review.json');r=json.loads(p.read_text());records=[]
with CadClient() as c:
 c.call('cad_load_project_model',{'model_json':json.dumps(read_model(Path(r['cad'])))})
 for x,y in r['locators']['pin_centers_xy_mm']:
  s=c.call('solid_section_review',{'body_id':26,'plane':'xy','offset_mm':1.,'probe_mm':y,'deflection_mm':.01})
  spans=[[q['start_mm'],q['end_mm']] for q in s['probe_spans']]
  left=next((b-a for a,b in spans if abs(b-(x-2.6))<.02),None);right=next((b-a for a,b in spans if abs(a-(x+2.6))<.02),None)
  assert left and right and min(left,right)>2.4,(x,y,spans)
  records.append({'center':[x,y],'section_z_mm':1,'left_stock_mm':left,'right_stock_mm':right})
r['socket_side_stock']=records;p.write_text(json.dumps(r,indent=2)+'\n');print(records)
