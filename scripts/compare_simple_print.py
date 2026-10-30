"""Compare native slice estimates with the same saved process and materials."""
import hashlib,json
from pathlib import Path
import prepare_bambu_latest as b

ROOT=Path(__file__).resolve().parents[1]
BEFORE=ROOT/'ingress-flange-print-verification.json'
AFTER=ROOT/'simple-print-verification.json'
REPORT=ROOT/'simple-print-comparison.json'
ROLES=['Support','Support interface','Support transition']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    old,new=(json.loads(p.read_text()) for p in [BEFORE,AFTER])
    assert old['native_slicer_version']==new['native_slicer_version']
    assert old['native_engine_sha256']==new['native_engine_sha256']
    archives=[]
    for p in [old,new]:
        assert sha(ROOT/p['project'])==p['project_sha256']
        archives.append(b.read_zip(ROOT/p['project']))
    assert archives[0]['Metadata/project_settings.config']==archives[1]['Metadata/project_settings.config']
    configs=[b.project_parts(a)[1] for a in archives]
    metadata=[{b.metadata(o)['name']:b.metadata(o) for o in c.findall('object')} for c in configs]
    assert metadata[0]==metadata[1]
    result={'before_report':BEFORE.name,'before_report_sha256':sha(BEFORE),
        'after_report':AFTER.name,'after_report_sha256':sha(AFTER),
        'same_saved_global_settings_bytes':True,'same_saved_object_metadata':True,
        'same_native_engine_and_slicer':True,'plates':[]}
    for a,d in zip(old['native_slice']['sliced_plates'],new['native_slice']['sliced_plates']):
        assert a['id']==d['id']
        result['plates'].append({'plate':a['id'],
            'before_seconds':a['total_predication'],'after_seconds':d['total_predication'],
            'before_support_role_seconds':{r:a['feature_type_times'].get(r,0) for r in ROLES},
            'after_support_role_seconds':{r:d['feature_type_times'].get(r,0) for r in ROLES},
            'before_support_seconds':sum(a['feature_type_times'].get(r,0) for r in ROLES),
            'after_support_seconds':sum(d['feature_type_times'].get(r,0) for r in ROLES)})
    support_old=sum(p['before_support_seconds'] for p in result['plates'])
    support_new=sum(p['after_support_seconds'] for p in result['plates'])
    height=lambda p:next(o for o in p['placements'][1]['parts'] if o['name']=='PETG - One-piece auger')['bounds_mm'][1][2]
    result['total']={'before_seconds':old['time_seconds'],'after_seconds':new['time_seconds'],
        'saved_seconds':old['time_seconds']-new['time_seconds'],
        'before_filament_g':old['filament_g'],'after_filament_g':new['filament_g'],
        'saved_filament_g':old['filament_g']-new['filament_g'],
        'before_support_seconds':support_old,'after_support_seconds':support_new,
        'support_time_reduction_percent':100*(support_old-support_new)/support_old,
        'before_auger_mesh_height_mm':height(old),'after_auger_mesh_height_mm':height(new)}
    result['improves_all_measured_print_costs']=(new['time_seconds']<old['time_seconds'] and
        new['filament_g']<old['filament_g'] and support_new<support_old and height(new)<height(old))
    result['scope']='Native estimates with identical saved settings. Support seconds sum the three named feature roles, not support mass, removal effort or measured print reliability.'
    REPORT.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['total'],indent=2),flush=True)
    assert result['improves_all_measured_print_costs'],'Simplification did not reduce every measured print cost; review before preferring it.'


if __name__=='__main__':main()
