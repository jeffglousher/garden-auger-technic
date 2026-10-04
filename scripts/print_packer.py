"""Union the auger, pack five parts, and export separate PLA/PETG plates.

Run with: uv run --no-project --python 3.12 --with trimesh --with manifold3d
          python scripts/pack_captured.py
"""

import json
import hashlib
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
M = {'m':CORE}
ET.register_namespace('',CORE)


def mesh_from_object(obj):
    vertices = [[float(v.get(k)) for k in ('x','y','z')]
                for v in obj.findall('m:mesh/m:vertices/m:vertex',M)]
    faces = [[int(t.get(k)) for k in ('v1','v2','v3')]
             for t in obj.findall('m:mesh/m:triangles/m:triangle',M)]
    mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=True)
    mesh.merge_vertices(digits_vertex=5)
    assert mesh.is_watertight and mesh.is_volume, obj.attrib
    return mesh


def component_count(mesh):
    parent=list(range(len(mesh.vertices)))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    for a,b,c in mesh.faces:
        for x in [b,c]:
            parent[find(int(x))]=find(int(a))
    return len({find(i) for i in range(len(parent))})


def replace_mesh(obj,mesh):
    obj.remove(obj.find('m:mesh',M))
    node=ET.SubElement(obj,f'{{{CORE}}}mesh')
    verts=ET.SubElement(node,f'{{{CORE}}}vertices')
    for vertex in mesh.vertices:
        ET.SubElement(verts,f'{{{CORE}}}vertex',dict(zip(('x','y','z'),(f'{x:.9g}' for x in vertex))))
    faces=ET.SubElement(node,f'{{{CORE}}}triangles')
    for face in mesh.faces:
        ET.SubElement(faces,f'{{{CORE}}}triangle',dict(zip(('v1','v2','v3'),(str(x) for x in face))))


def pack(source,target,fit=False,individual_dir='print-parts',material_plates=True,print_notes=None):
    with zipfile.ZipFile(source) as z:
        entries={name:z.read(name) for name in z.namelist()}
    xml=ET.fromstring(entries['3D/3dmodel.model'])
    assert xml.get('unit')=='millimeter'
    resources=xml.find('m:resources',M)
    objects={o.get('name'):o for o in resources.findall('m:object',M)}
    if 'Body90' in objects and 'Body15' in objects:
        core=mesh_from_object(objects['Body15']);flight=mesh_from_object(objects['Body90'])
        auger=trimesh.boolean.union([core,flight],engine='manifold')
        assert auger.is_watertight and auger.is_volume and component_count(auger)==1
        assert auger.bounds[1,1]>139.49 and auger.bounds[1,0]>15.49
        assert np.any((auger.vertices[:,1]>30)&(auger.vertices[:,1]<80)&
                      (np.hypot(auger.vertices[:,0],auger.vertices[:,2])>14)), 'Flight geometry lost'
        replace_mesh(objects['Body90'],auger)
        resources.remove(objects.pop('Body15'))
    ids={int(name.removeprefix('Body')):obj for name,obj in objects.items()}
    bush_ids=sorted(set(ids)-{15,26,46,90,216})
    assert len(bush_ids) in {0,1},bush_ids
    sleeve=bush_ids[0] if bush_ids else None
    auger_id=15 if fit else 90
    order=[26,46,auger_id,216]+([sleeve] if sleeve else [])
    names=['PETG - Housing upper','PETG - Housing lower','PETG - Journal fit coupon' if fit else 'PETG - One-piece auger',
           'PETG - Square adapter']+(['PLA - Full wear sleeve'] if sleeve else [])
    upright=np.array([[1,0,0],[0,0,1],[0,-1,0]])
    rotations=[np.diag([-1,1,-1]),np.eye(3),np.eye(3),
               upright,upright]
    anchors=([(8,8),(8,56),(8,106),(65,106),(104,106)] if fit else
             [(8,8),(8,116),(214,8),(214,169),(214,207)])
    material_id=max(int(r.get('id','0')) for r in resources)+1
    material=ET.SubElement(resources,f'{{{CORE}}}basematerials',{'id':str(material_id)})
    palette=[('PETG - Chassis yellow','#E5AE3CFF'),('PETG - Auger orange','#D57E37FF'),
             ('PETG - Adapter gray','#BEC3CAFF'),('PLA - Wear sleeve teal','#37AAA1FF')]
    for name,color in palette:
        ET.SubElement(material,f'{{{CORE}}}base',{'name':name,'displaycolor':color})
    build=xml.find('m:build',M)
    build.clear()
    report=[];boxes=[]
    for body,name,rotation,anchor in zip(order,names,rotations,anchors):
        obj=ids[body];obj.set('name',name)
        color_index=3 if body==sleeve else 2 if body==216 else 1 if body==auger_id else 0
        obj.set('pid',str(material_id));obj.set('pindex',str(color_index))
        for triangle in obj.findall('m:mesh/m:triangles/m:triangle',M):
            for attribute in ['pid','p1','p2','p3']:triangle.attrib.pop(attribute,None)
        mesh=mesh_from_object(obj)
        assert component_count(mesh)==1,(name,'disconnected mesh')
        vertices=mesh.vertices@rotation.T
        minimum=vertices.min(axis=0)
        translation=np.array([*anchor,0.])-minimum
        bounds=np.array([vertices.min(axis=0),vertices.max(axis=0)])+translation
        assert abs(bounds[0,2])<1e-6
        assert np.all(bounds[0,:2]>=0) and np.all(bounds[1,:2]<=256)
        for previous in boxes:
            assert np.any(bounds[1,:2]<=previous[0,:2]) or np.any(previous[1,:2]<=bounds[0,:2]),'Plate overlap'
        boxes.append(bounds)
        transform=list(rotation.T.reshape(-1))+list(translation)
        ET.SubElement(build,f'{{{CORE}}}item',{'objectid':obj.get('id'),
            'transform':' '.join(f'{n:.9g}' for n in transform)})
        report.append({'name':name,'closed':True,'connected_components':1,
                       'material':'PLA' if body==sleeve else 'PETG',
                       'color_name':palette[color_index][0].split(' - ')[1],
                       'color_hex':palette[color_index][1][:7],
                       'volume_mm3':float(mesh.volume),'plate_bounds_mm':bounds.tolist(),
                       'triangle_count':len(mesh.faces)})
        if not fit and individual_dir:
            # Each standalone STL uses its selected orientation, sitting on
            # Z=0 near the origin. The 3MF plates preserve named materials.
            individual=mesh.copy()
            individual.vertices=vertices-minimum
            out=ROOT/individual_dir;out.mkdir(parents=True,exist_ok=True)
            individual.export(out/(name.lower().replace(' - ','-').replace(' ','-')+'.stl'))
    entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
    entries['Metadata/print-notes.txt']=(
        ('Print the plain loose sleeve in PLA and the four other printed parts in PETG.\n' if sleeve else
         'Direct chassis bearing variant: print all four parts in PETG; no sleeve is used.\n')+
        'Retention is by the chassis clamshell only. No retaining clip or ring lock is used.\n'
        'The servo, screws and inserts are purchased hardware and are not in this print package.\n'
        'Geometry, material names and bed placement only: choose the actual printer and filament profiles in the slicer.\n'
        'Servo: INJORA INJS035-360. Use goBILDA 1906-0025-0032 metal 25T horn, 4 x M4 x 6 socket screws, M3 x 6 center screw.\n'
        'Critical printed dimensions require +/-0.10 mm acceptance. Print the fit check first; clean/finish bores as required.\n'
        'Verify spline engagement >=2 mm, center screw seat to shaft tip 2.6 +/-0.2 mm, and usable M3 thread depth >=4.0 mm.\n'
        'Use a factory-compatible center screw if these inspections fail; never bottom the screw.\n'
        'Material assignments are prototype specifications; loaded strength and wear require a bench trial.\n'
        'Use the separate material files for single-filament printing.\n').encode()
    if print_notes is not None:
        entries['Metadata/print-notes.txt']=print_notes.encode()
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)
    print(target.name,len(order),'closed, connected parts; plate fits 256 mm',flush=True)
    if not fit and material_plates:
        for selected,filename in [('PETG','garden-auger-petg.3mf'),('PLA','garden-auger-pla-bushing.3mf')]:
            if selected=='PLA' and not sleeve:continue
            subset=ET.fromstring(entries['3D/3dmodel.model'])
            selected_objects=[o for o in subset.findall('m:resources/m:object',M) if o.get('name').startswith(selected)]
            selected_ids={o.get('id') for o in selected_objects}
            sub_resources=subset.find('m:resources',M)
            for o in sub_resources.findall('m:object',M):
                if o.get('id') not in selected_ids:sub_resources.remove(o)
            sub_build=subset.find('m:build',M)
            for item in list(sub_build):
                if item.get('objectid') not in selected_ids:sub_build.remove(item)
            if selected=='PLA':
                item=sub_build.find('m:item',M)
                transform=[float(n) for n in item.get('transform').split()]
                # Move the single upright sleeve from the common plate to
                # the center of its own bed without changing orientation.
                transform[9]+=113.75-anchors[-1][0]
                transform[10]+=114-anchors[-1][1]
                item.set('transform',' '.join(f'{n:.9g}' for n in transform))
            data={**entries,'3D/3dmodel.model':ET.tostring(subset,encoding='utf-8',xml_declaration=True)}
            with zipfile.ZipFile(ROOT/filename,'w',zipfile.ZIP_DEFLATED) as z:
                for entry,payload in data.items():z.writestr(entry,payload)
            assert len(selected_objects)==(4 if selected=='PETG' else 1)
            print(filename,len(selected_objects),'parts,',selected,flush=True)
    return report
