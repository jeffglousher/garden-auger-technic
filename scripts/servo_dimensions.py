"""Mechanical datums from the user's dimensioned INJORA 35KG drawing.

World Y runs rearward from the output shaft tip. Local reference Z is the
opposite direction. The 24.7 dimension starts at the ear UNDERSIDE.
"""
from direct_drive_parameters import SHAFT_TIP_SEAT_Y

CASE_DRAWING_LENGTH=40.0
CASE_DESIGN_ENVELOPE_LENGTH=40.5  # larger length in the same image's catalog row
CASE_WIDTH=20.0
TIP_TO_REAR=41.5
CASE_AXIAL_HEIGHT=37.5
EAR_UNDERSIDE_TO_REAR=24.7
EAR_THICKNESS=2.7
EAR_SPAN=56.0
MOUNT_HOLE_SPACING=49.0
SHAFT_FROM_RIGHT_EDGE=10.0
CASE_CLEARANCE=.4
EAR_FACE_CLEARANCE=.2
CASE_FRONT_ALLOWANCE=1.0
CASE_REAR_ALLOWANCE=1.5

CASE_FRONT_Y=SHAFT_TIP_SEAT_Y+TIP_TO_REAR-CASE_AXIAL_HEIGHT
CASE_REAR_Y=SHAFT_TIP_SEAT_Y+TIP_TO_REAR
EAR_REAR_Y=CASE_REAR_Y-EAR_UNDERSIDE_TO_REAR
EAR_FRONT_Y=EAR_REAR_Y-EAR_THICKNESS
CASE_LEFT_X=SHAFT_FROM_RIGHT_EDGE-CASE_DESIGN_ENVELOPE_LENGTH
CASE_RIGHT_X=SHAFT_FROM_RIGHT_EDGE
EAR_LEFT_X=SHAFT_FROM_RIGHT_EDGE-(CASE_DRAWING_LENGTH+EAR_SPAN)/2
EAR_RIGHT_X=EAR_LEFT_X+EAR_SPAN
MOUNT_LEFT_X=(EAR_LEFT_X+EAR_RIGHT_X-MOUNT_HOLE_SPACING)/2
MOUNT_RIGHT_X=MOUNT_LEFT_X+MOUNT_HOLE_SPACING
CASE_POCKET_FRONT_Y=CASE_FRONT_Y-CASE_FRONT_ALLOWANCE
CASE_POCKET_REAR_Y=CASE_REAR_Y+CASE_REAR_ALLOWANCE
EAR_POCKET_FRONT_Y=EAR_FRONT_Y-EAR_FACE_CLEARANCE
EAR_POCKET_REAR_Y=EAR_REAR_Y+EAR_FACE_CLEARANCE


def set_plane_origin(model,sketch_names,axis,value):
    sketches={s['name']:s for s in model['sketches']}
    for name in sketch_names:
        sketch=sketches[name]
        sketch['basis']['origin'][axis]=value
        datum=next(p for p in model['datum_planes'] if p['datum_id']==sketch['plane']['datum_id'])
        datum['basis']['origin'][axis]=value
        datum['source']['distance']=value if axis==2 else -value


def configure_reference(model):
    """Correct the purchased-servo reference independently of housing pockets."""
    from cad_build import profile
    sketches={s['name']:s for s in model['sketches']}
    profile(sketches['Sketch1'],[(CASE_LEFT_X,-CASE_WIDTH/2),(CASE_RIGHT_X,-CASE_WIDTH/2),
                               (CASE_RIGHT_X,CASE_WIDTH/2),(CASE_LEFT_X,CASE_WIDTH/2)])
    set_plane_origin(model,['Sketch1'],2,-TIP_TO_REAR)
    set_plane_origin(model,['Sketch2','Sketch3'],2,-(TIP_TO_REAR-EAR_UNDERSIDE_TO_REAR))
    # The open mounting slots have no published diameter. Retain their
    # conservative rectangular envelopes, but locate their centers at 49 mm.
    entities=dict(sketches['Sketch3']['snapshot']['entities'])
    for start,center,low,high in [(1,MOUNT_LEFT_X,3,7),(9,MOUNT_LEFT_X,-7,-3),
                                (17,MOUNT_RIGHT_X,3,7),(25,MOUNT_RIGHT_X,-7,-3)]:
        for offset,(x,y) in enumerate([(center-3,low),(center+3,low),(center+3,high),(center-3,high)]):
            entities[start+offset]['position']={'x':x,'y':y}
    sketches['Sketch3']['profile_identities']={'next':0,'records':[]}
    extrudes={e['feature_id']:e for e in model['extrudes']}
    extrudes[3]['extent']['distance']=CASE_AXIAL_HEIGHT
    extrudes[5]['extent']['distance']=EAR_THICKNESS
    extrudes[7]['extent']['distance']=EAR_THICKNESS
    for group in ('definitions','occurrences'):
        for item in model['assembly']['component_structure'][group]:
            if item.get('component_id',item['id'])==3:
                item['name']='INJORA 35KG mechanical envelope - drawing-correct ear datums'
    return model
