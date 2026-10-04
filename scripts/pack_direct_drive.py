"""Package the direct-drive prototype without changing release B artifacts."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from print_packer import pack, mesh_from_object, component_count, CORE, M
from direct_drive_parameters import PILOT_TRIAL_DIAMETERS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build/direct-drive'
NOTES='''Round pilot press-fit FIT PROTOTYPE for INJORA INJS035-360.
Four PETG parts: yellow chassis halves, orange auger, gray direct press-fit adapter.
One PLA part: teal full loose wear sleeve. No ring lock or clip.
No separate servo horn and no four M4 mounting screws.
Use only a factory-compatible M3 center screw at the adapter; inspect actual shaft and thread depth.
No spline teeth are printed. The metal servo teeth form engagement in an undersized round PETG pilot.
Print A/B/C/D press-fit coupons first: bores 5.60/5.70/5.80/5.90 mm. Start with D, the largest bore.
Full adapter uses the provisional 5.70 mm bore B. Change its native pilot sketch to the physically selected fit.
Pilot depth 1.70 mm includes 0.15 mm lead-in. Shaft tip bears on the annular bore floor.
Reference stationary nose gap 0.30 mm; physical exposed spline length and nose geometry must be measured.
Center M3x6 trial: measured length 5.90-6.10, seat-to-shaft-tip 2.40-2.80, usable thread depth at least 4.00 mm.
This gives 3.10-3.70 mm thread entry and at least 0.30 mm tip room, conditional on all measurements.
M3 head 5.5 x3.0 clears 6.40 mm access; 3.40 passage and 4.00 x0.30 underhead relief clear screw neck.
Do not force seating with the screw or clamp the adapter against the stationary servo nose.
Printed torque capacity, creep, wear and service life have not been qualified.
Keep the 14 mm square and 28 mm auger hub; integral collar retained only by clamshell.
Native CAD and portable 3MF material/color metadata are explicit; select actual slicer profiles.
Chassis uses 4 ruthex RX-M3x5.7 inserts, 2 M3x12 front and 2 M3x18 rear screws.
Separate PLA and PETG printing avoids filament changes and purge.
'''


def small_plate(source,target,coupons=False):
    with zipfile.ZipFile(source) as z:entries={n:z.read(n) for n in z.namelist()}
    xml=ET.fromstring(entries['3D/3dmodel.model'])
    objects=xml.findall('m:resources/m:object',M)
    build=xml.find('m:build',M);build.clear()
    rotation=np.array([[1,0,0],[0,0,1],[0,-1,0]])
    out=ROOT/'print-parts/direct-drive';out.mkdir(parents=True,exist_ok=True)
    report=[]
    for i,obj in enumerate(objects):
        mesh=mesh_from_object(obj)
        assert component_count(mesh)==1
        vertices=mesh.vertices@rotation.T
        translation=np.array([8+i*23,8,0])-vertices.min(axis=0)
        bounds=np.array([vertices.min(axis=0),vertices.max(axis=0)])+translation
        assert np.all(bounds[0]>=0) and np.all(bounds[1,:2]<256)
        diameter=PILOT_TRIAL_DIAMETERS[i] if coupons else None
        label=f'PETG - Round press fit {chr(65+i)} - bore {diameter:.2f}' if coupons else 'PETG - Round press-fit square adapter'
        obj.set('name',label)
        ET.SubElement(build,f'{{{CORE}}}item',{'objectid':obj.get('id'),
            'transform':' '.join(f'{n:.9g}' for n in [*rotation.T.reshape(-1),*translation])})
        standalone=mesh.copy();standalone.vertices=vertices-vertices.min(axis=0)
        filename=f'press-fit-{chr(65+i).lower()}-{diameter:.2f}.stl' if coupons else 'petg-square-adapter.stl'
        standalone.export(out/filename)
        report.append({'name':label,'closed':True,'connected_components':1,
            'volume_mm3':float(mesh.volume),'bounds_mm':bounds.tolist()})
    entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
    entries['Metadata/print-notes.txt']=NOTES.encode()
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)
    return report


def main():
    report={'assembly':pack(OUT/'assembly-raw.3mf',ROOT/'garden-auger-direct-drive.3mf',
        individual_dir='print-parts/direct-drive',material_plates=False,print_notes=NOTES),
        'adapter':small_plate(OUT/'adapter-raw.3mf',ROOT/'garden-auger-direct-adapter.3mf'),
        'coupons':small_plate(OUT/'coupons-raw.3mf',ROOT/'garden-auger-press-fit.3mf',coupons=True)}
    proof=json.loads((ROOT/'direct-drive-verification.json').read_text())
    proof['desktop_compatibility']=json.loads((OUT/'desktop-compatibility.json').read_text())
    proof['print_checks']=report
    proof['artifact_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'garden-auger-direct-drive.nbcad',ROOT/'garden-auger-direct-drive.3mf',
         ROOT/'garden-auger-direct-adapter.3mf',ROOT/'garden-auger-press-fit.nbcad',ROOT/'garden-auger-press-fit.3mf']}
    (ROOT/'direct-drive-verification.json').write_text(json.dumps(proof,indent=2))
    print('Five-part direct assembly, single adapter and four round-pilot fit coupons packaged',flush=True)

if __name__=='__main__':main()
