"""Exact OCCT sections, native CAD sheets and the controlled prototype drawing."""
import json
import sys
import textwrap
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
import fitz
from cad_client import CadClient
from cad_build import save_project
from design_parameters import *

ROOT=Path(__file__).resolve().parents[1]
W,H=431.8,279.4
COLORS={26:(.72,.49,.08),46:(.72,.49,.08),15:(.77,.32,.08),216:(.25,.31,.38),221:(.04,.48,.43)}

def main():
    out=ROOT/'output/pdf';out.mkdir(parents=True,exist_ok=True)
    audit=json.loads((ROOT/'dimension-audit.json').read_text());stack=audit['tolerance_stack']
    model=json.loads((ROOT/'.build/model.json').read_text())
    horn=json.loads((ROOT/'.build/parts.json').read_text())['horn']
    if "--pdf-only" in sys.argv:
        projections=json.loads((ROOT/".build/drawing-projections.json").read_text())
    else:
        projections={}
        with CadClient() as cad:
            cad.call('cad_load_project_model',{'model_json':json.dumps(model)})
            for body in [26,46,15,216,221,horn]:
                projections[str(body)]=cad.call('drawing_projection',{'body_ids':[body],'scope':'definition',
                    'direction':[1,0,0],'up':[0,0,1],'include_hidden':False,'deflection':.01,
                    'section_plane':{'point':[0,0,0],'normal':[1,0,0]}})
            for key,body,direction,up in [('adapter_end',216,[0,-1,0],[0,0,1]),
                                          ('housing_top',46,[0,0,1],[0,1,0])]:
                projections[key]=cad.call('drawing_projection',{'body_ids':[body],'scope':'definition',
                    'direction':direction,'up':up,'include_hidden':False,'deflection':.01})
            for number,title,bodies in [(1,'Drive assembly and tolerance stack',[26,46,15,216,221,horn]),
                 (2,'Square drive adapter',[216]),(3,'Auger journal and PLA sleeve',[15,221]),
                 (4,'Lower housing and heat-set inserts',[46])]:
                sheet=cad.call('drawing_create_sheet',{'name':title,'format':'ansi_b','orientation':'landscape',
                    'standard':'ansi','projection_method':'third_angle','title_block':{
                        'title':title,'drawing_number':f'GA-B-{number:02}','revision':'B',
                        'material':'PETG structural / PLA sleeve / purchased metal horn'},
                    'tolerance_note':{'preset':'custom','custom':'mm. Critical printed sizes +/-0.10; see controlled PDF for datums, profile and stack.'}})
                sheets=cad.call('drawing_document')['sheets'];sid=sheets[-1]['id']
                cad.call('drawing_add_view',{'sheet_id':sid,'view':{'name':title,'kind':'custom',
                    'direction':[1,0,0],'up':[0,0,1],'position':[120,145],
                    'scale':1 if number in [1,4] else 3,'body_ids':bodies,'scope':'definition',
                    'show_hidden_lines':True,'show_tangent_edges':False}})
                notes={1:'Clamshell alone captures both faces of integral collar. No ring lock or clip. H-C = 34.40 +/-0.15 installed. Drive axis offset <=0.50 radial.',
                       2:'A: metal-horn seating face. B: pilot bore axis. C: +X M4 mounting hole for clocking. Square 14 BASIC / R1 BASIC; profile 0.10 to A|B|C. 4x diameter 4.60 +/-0.10 on 16 BASIC square, rotated 45 degrees; position diameter 0.20 RFS to A|B. Center diameter3.40 through.',
                       3:'Auger A: diameter28 journal axis. B: front collar face. Square 14.40 BASIC / R1.20 BASIC; profile0.10 to A|B (free clocking). Collar diameter34 x3.00 +/-0.10. Front collar to socket mouth25.50 +/-0.10. Socket12.00 +/-0.10 deep. Sleeve diameter34 / bore28.60 / length10.40.',
                       4:'A: clamshell split plane. B: common assembled journal axis. C: front thrust stop. Critical span3.60 +/-0.10 between thrust stops. Journal diameter29.60 +/-0.10. Sleeve cavity diameter35.60 +/-0.10. 4x ruthex RX-M3x5.7; pilot diameter4.00 x6.70 deep. Front M3x12; rear M3x18.'}
                if number==2:
                    notes[number]+=' Center M3x6: seat-to-shaft-tip2.60 +/-0.20; usable thread depth>=4.00.'
                cad.call('drawing_add_note',{'sheet_id':sid,'position':[230,65],
                    'text':textwrap.fill(notes[number],width=64)})
            save_project(cad,ROOT/'.build/drawing-project.nbcad')
        (ROOT/'.build/drawing-projections.json').write_text(json.dumps(projections))
    pdfmetrics.registerFont(TTFont('Segoe','C:/Windows/Fonts/segoeui.ttf'))
    pdfmetrics.registerFont(TTFont('SegoeBold','C:/Windows/Fonts/segoeuib.ttf'))
    pdf=canvas.Canvas(str(out/'garden-auger-release-B.pdf'),pagesize=(W*mm,H*mm))
    pdf.setTitle('Garden auger - Release B - functional dimensions and GD&T')
    def txt(x,y,s,size=9,bold=False):
        pdf.setFont('SegoeBold' if bold else 'Segoe',size);pdf.drawString(x*mm,y*mm,s)
    def line(a,b,width=.25):
        pdf.setLineWidth(width*mm);pdf.line(a[0]*mm,a[1]*mm,b[0]*mm,b[1]*mm)
    def base(n,title):
        pdf.setStrokeColorRGB(.15,.18,.22);pdf.setFillColorRGB(.1,.13,.18)
        pdf.rect(8*mm,8*mm,(W-16)*mm,(H-16)*mm)
        txt(16,H-20,'GARDEN AUGER  /  RELEASE B',15,True);txt(16,H-29,title,11)
        line((16,27),(W-16,27));txt(16,18,'GA-B-%02d   |   2026-10-03   |   mm   |   Third-angle views   |   Prototype inspection specification'%n,8)
        txt(W-97,18,f'Sheet {n} / 4   •   CAD geometry verified',8)
    def plot(key,box,bounds=None,section=False,color=(.16,.2,.24)):
        p=projections[str(key)];b=bounds or p['bounds'];x,y,w,h=box
        scale=min(w/(b[2]-b[0]),h/(b[3]-b[1]));ox=x+(w-(b[2]-b[0])*scale)/2;oy=y+(h-(b[3]-b[1])*scale)/2
        def tr(q):return(ox+(q[0]-b[0])*scale,oy+(q[1]-b[1])*scale)
        pdf.saveState();path=pdf.beginPath();path.rect(x*mm,y*mm,w*mm,h*mm);pdf.clipPath(path,stroke=0)
        pdf.setStrokeColorRGB(*color)
        for poly in p['section'] if section else p['visible']:
            pts=poly['points']
            for a,bp in zip(pts,pts[1:]):line(tr(a),tr(bp),.3 if section else .18)
        pdf.restoreState();return tr
    def dim(a,b,label,offset=8):
        y=max(a[1],b[1])+offset
        line(a,(a[0],y+1));line(b,(b[0],y+1));line((a[0],y),(b[0],y))
        for x,sign in [(a[0],1),(b[0],-1)]:
            line((x,y),(x+sign*2,y+1));line((x,y),(x+sign*2,y-1))
        width=pdfmetrics.stringWidth(label,'Segoe',8)/mm
        pdf.setFillColorRGB(1,1,1);pdf.rect((sum([a[0],b[0]])/2-width/2-1)*mm,(y+1)*mm,(width+2)*mm,4*mm,fill=1,stroke=0)
        pdf.setFillColorRGB(.1,.13,.18);txt((a[0]+b[0]-width)/2,y+2,label,8)
    def datum(point,letter,offset=(8,7)):
        x,y=point;bx=x+offset[0];by=y+offset[1]
        line((x,y),(bx,by));pdf.rect(bx*mm,by*mm,5*mm,5*mm);txt(bx+1.3,by+1,letter,8,True)
        path=pdf.beginPath();path.moveTo(x*mm,y*mm);path.lineTo((x+1)*mm,(y+2)*mm);path.lineTo((x-1)*mm,(y+2)*mm);path.close();pdf.drawPath(path,fill=1)
    def fcf(x,y,kind,value,datums):
        cells=[8,19]+[8]*len(datums);ox=x
        for w in cells:pdf.rect(ox*mm,y*mm,w*mm,7*mm);ox+=w
        if kind=='profile':
            pdf.arc((x+1.5)*mm,(y+1.3)*mm,(x+6.5)*mm,(y+6.3)*mm,0,180);line((x+1.5,y+3.8),(x+6.5,y+3.8))
        elif kind=='position':
            pdf.circle((x+4)*mm,(y+3.5)*mm,2*mm);line((x+1,y+3.5),(x+7,y+3.5));line((x+4,y+.5),(x+4,y+6.5))
        elif kind=='perp':line((x+2,y+2),(x+6,y+2));line((x+4,y+2),(x+4,y+6))
        else:
            for a,b in [((x+2,y+2),(x+5,y+2)),((x+5,y+2),(x+6,y+5)),((x+6,y+5),(x+3,y+5)),((x+3,y+5),(x+2,y+2))]:line(a,b)
        txt(x+10,y+2,value,8)
        for i,d in enumerate(datums):txt(x+29+8*i,y+2,d,8,True)
    def notes(x,y,rows,size=9,gap=6):
        for i,s in enumerate(rows):txt(x,y-gap*i,s,size)
    base(1,'Assembly section • retention surfaces and worst-case tolerance stack')
    section_bounds=[110.5,-24,154,24]
    for body in [26,46,15,221,216,horn]:
        tr=plot(body,(24,91,221,130),section_bounds,True,COLORS.get(body,(.28,.4,.55)))
    dim(tr((113.7,20)),tr((117.3,20)),'3.60 ±0.10',7)
    dim(tr((113.7,-21)),tr((148.1,-21)),'Installed H-C 34.40 ±0.15',-6)
    datum(tr((113.7,18)),'C',(-14,0));datum(tr((148.1,17)),'H',(8,5))
    txt(25,75,'Section through Y axis, X=0. Orange: auger. Teal: loose sleeve. Gray: adapter + metal horn.',8)
    txt(25,65,'Both chassis thrust stops act on the Ø34 integral collar. No sleeve lock, clip or separate retainer.',9,True)
    txt(262,229,'WORST-CASE ACCEPTANCE STACK',11,True)
    rows=[('Axial end float',f"{stack['end_float_min_mm']:.2f}–{stack['end_float_max_mm']:.2f} mm"),
          ('Square engagement',f"{stack['square_engagement_min_mm']:.2f}–{stack['square_engagement_max_mm']:.2f} mm"),
          ('Tip-to-socket-bottom gap',f"≥{stack['socket_bottom_clearance_min_mm']:.2f} mm"),
          ('Flange-to-auger gap',f"≥{stack['flange_to_hub_gap_min_mm']:.2f} mm"),
          ('Journal radial clearance',f"≥{stack['journal_radial_clearance_min_mm']:.2f} mm"),
          ('Allowed drive-axis offset','≤0.50 mm radial'),('Remaining radial margin','≥0.20 mm'),
          ('Square flat clearance','≥0.10 mm / side'),('Pilot bottom clearance','≥0.15 mm')]
    for i,(k,v) in enumerate(rows):
        y=217-10*i;txt(263,y,k,9);txt(370,y,v,9,True);line((262,y-3),(413,y-3),.1)
    notes(263,110,['Printed critical extrema: ±0.10 mm.', 'Installed horn face H: ±0.15 mm from C.',
        'Arithmetic worst case; no statistical averaging.', 'Limits include form within the functional envelope.',
        'The numbers are required acceptance limits,', 'not measured FDM or supplier capabilities.',
        'Qualify the fit coupon before printing the auger.'],8.5,6)
    notes(25,48,['Assembly inspection: assembled journal axis offset ≤0.50 radial from installed servo/horn axis.',
                'Shim/finish the printed seat if needed to achieve H-C and axis limits. Axial faces are checked at their functional extrema.'],8,5)
    pdf.showPage()
    base(2,'PETG square adapter • gray #BEC3CA • dimensioned metal-horn interface')
    tr=plot('adapter_end',(25,108,159,123));sr=plot(216,(227,108,142,123),section=True)
    txt(39,100,'Auger-facing end view',9,True);txt(238,100,'Longitudinal section, X=0',9,True)
    dim(sr((129.5,17)),sr((148.1,17)),'18.60 ±0.10',8)
    dim(sr((141.1,-17)),sr((148.1,-17)),'7.00 ±0.10',-8)
    datum(sr((148.1,17)),'A',(10,8));datum(sr((146,7.25)),'B',(12,6))
    datum(tr((MOUNT_RADIUS,0)),'C',(8,-8))
    notes(23,82,['Ø34.00 ±0.10 flange. 14.00 BASIC square, R1.00 BASIC corners.',
        '4× Ø4.60 ±0.10 through; Ø7.40 ±0.10 counterbore, 4.40 ±0.10 deep.',
        'Hole centers: 16 BASIC square rotated 45°; cardinal ±11.3137 BASIC.',
        'Horn-side pilot Ø14.50 ±0.10 ×2.30 ±0.10 deep; center Ø3.40 through.',
        'Center head relief Ø6.40, front at Y142.60; seats the horn M3 head clear.',
        'M3×6: seat-to-shaft-tip 2.60 ±0.20; require ≥4.00 usable thread depth.'],9,7)
    fcf(238,79,'profile','0.10',['A','B','C']);txt(291,81,'Square surfaces, all around',8)
    fcf(238,68,'position','Ø0.20',['A','B']);txt(283,70,'4× mount holes, RFS',8)
    fcf(238,57,'flat','0.10',[]);txt(269,59,'Face A',8)
    notes(238,47,['A: horn seating plane. B: pilot bore axis.',
        'C: +X mounting hole, used only to clock the square.',
        'Basic square sizes use profile; no extra size tolerance added.'],8,5)
    pdf.showPage()
    base(3,'PETG auger journal • orange #D57E37 • loose PLA sleeve • teal #37AAA1')
    tr=plot(15,(25,123,216,111),[110,-18,141,18],True,COLORS[15]);sr=plot(221,(286,133,94,100),section=True,color=COLORS[221])
    dim(tr((114,17)),tr((139.5,17)),'25.50 ±0.10',7)
    dim(tr((114,-17)),tr((117,-17)),'3.00 ±0.10',-7)
    datum(tr((122,14)),'A',(3,7));datum(tr((114,17)),'B',(-10,6))
    txt(35,112,'Tail section; continuous Ø28 journal axis is datum A',9,True)
    txt(291,123,'Full slip-on sleeve; no key or lock',9,True)
    notes(24,95,['Journal Ø28.00 ±0.10. Collar Ø34.00 ±0.10 ×3.00 ±0.10.',
        'Socket 14.40 BASIC across flats, R1.20 BASIC; depth12.00 ±0.10.',
        'Socket is concentric to datum A; clocking is free before assembly.',
        'Keep the modeled collar fillets and 0.50 outer mouth chamfer.',
        'Nominal minimum hub corner wall: 4.31 straight / 3.81 at mouth.',
        'Geometric backlash about 3.89° total; this is not a zero-play joint.'],9,7)
    fcf(24,43,'profile','0.10',['A','B']);txt(70,45,'Socket surfaces, all around',8)
    fcf(24,32,'perp','0.10',['A']);txt(62,34,'Collar thrust faces; within axial size envelope',8)
    notes(278,96,['Sleeve OD Ø34.00 ±0.10; bore Ø28.60 ±0.10.',
        'Length10.40 ±0.10; lead-ins match CAD.',
        'Housing sleeve cavity Ø35.60 ±0.10.',
        'Combined minimum radial float0.90 mm.',
        'Sleeve slides over the journal from the drive end.',
        'PLA/PETG wear benefit needs a physical trial.',
        'One-piece auger export includes the original flight.'],8.5,7)
    pdf.showPage()
    base(4,'PETG chassis • yellow #E5AE3C • datums, insert pockets and fasteners')
    tr=plot('housing_top',(23,69,182,166))
    txt(26,58,'Lower housing, split-face view. Upper uses matching screw pattern.',8)
    txt(229,229,'HOUSING DATUM REFERENCE FRAME',11,True)
    notes(229,216,['A: machined/finished clamshell split plane (Z=0).',
        'B: common assembled Ø29.60 journal axis.', 'C: front collar thrust-stop plane (Y113.70).',
        'Thrust-stop span3.60 ±0.10. Cavity Ø35.60 ±0.10.',
        'Journal Ø29.60 ±0.10; front/rear axes must be common.',
        'Inspect with both chassis halves clamped together.'],9,7)
    fcf(229,165,'flat','0.10',[]);txt(260,167,'Split plane A',8)
    fcf(229,154,'perp','0.10',['B']);txt(267,156,'Thrust stops, within axial span limits',8)
    txt(229,139,'FOUR HEAT-SET POCKETS',11,True)
    notes(229,128,['ruthex RX-M3x5.7 brass: Ø4.6 ×5.7, M3 thread.',
        'Pilot Ø4.00 +0.10/-0.00 ×6.70 +0.20/-0.00 deep.',
        'Install flush; pocket depth ≥actual insert length +1.00.',
        'Front centers: X±27.00, Y118.50.',f'Rear centers: X−36.00 / +16.00, Y{REAR_SCREW_Y:.2f}.',
        'Upper Ø3.40 clearance / Ø6.20 head recess.',
        '2× M3×12 front; 2× M3×18 rear, ISO4762.',
        'Thread engagement4.00 front /5.30 rear nominal.',
        'Rear fastener pads clear the relocated wire channel.'],9,7)
    wall=min(s['minimum_wall_with_print_and_insert_allowance_mm'] for s in audit['heat_set_inserts']['seats'])
    txt(24,46,f'Checked insert-wall margin: minimum {wall:.2f} mm after dimensional allowance (required ≥1.60 mm).',9,True)
    txt(24,35,'Material labels and colors are set in native CAD and 3MF. Choose actual printer, filament and support profiles in the slicer.',8)
    pdf.showPage();pdf.save()
    doc=fitz.open(out/'garden-auger-release-B.pdf')
    for i,page in enumerate(doc):page.get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(ROOT/f'.build/drawing-page-{i+1}.png')
    print('Four-page PDF refreshed' if '--pdf-only' in sys.argv else
          'Four native CAD sheets and four-page release drawing saved',flush=True)

if __name__=='__main__':main()
