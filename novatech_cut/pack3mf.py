from __future__ import annotations
import hashlib, json, zipfile, base64
from pathlib import Path

PNG_1X1 = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2c4sAAAAASUVORK5CYII=')

def build_gcode_3mf(output, gcode: str, stats, profile_name='Bambu Lab A1 + UMTS'):
    output=Path(output); gbytes=gcode.encode('utf-8'); md5=hashlib.md5(gbytes).hexdigest().upper()
    content_types='''<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="gcode" ContentType="text/plain"/><Default Extension="json" ContentType="application/json"/><Default Extension="config" ContentType="application/xml"/></Types>'''
    rels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'''
    model='''<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="Application">Novatech Cut</metadata><resources/><build/></model>'''
    model_settings='''<?xml version="1.0" encoding="UTF-8"?><config><plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value="Novatech Cut"/><metadata key="locked" value="false"/><metadata key="filament_map_mode" value="Auto For Flush"/><metadata key="filament_maps" value="1 1 1 1 1"/><metadata key="filament_volume_maps" value="0 0 0 0 0"/><metadata key="gcode_file" value="Metadata/plate_1.gcode"/><metadata key="thumbnail_file" value="Metadata/plate_1.png"/><metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/><metadata key="top_file" value="Metadata/top_1.png"/><metadata key="pick_file" value="Metadata/pick_1.png"/><metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/></plate></config>'''
    msrels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/Metadata/plate_1.gcode" Id="rel0" Type="http://schemas.bambulab.com/package/2021/relationships/gcode"/></Relationships>'''
    slice_info=f'''<?xml version="1.0" encoding="UTF-8"?><config><header><header_item key="X-BBL-Client-Type" value="slicer"/><header_item key="X-BBL-Client-Version" value="NovatechCut-0.1.5"/></header><plate><metadata key="index" value="1"/><metadata key="prediction" value="{int(stats.estimated_seconds)}"/><metadata key="weight" value="0"/><metadata key="printer_model_id" value="NOVA_A1_UMTS"/><metadata key="extruder_type" value="0"/><metadata key="nozzle_volume_type" value="0"/><metadata key="limit_filament_maps" value="0 0 0 0 0"/></plate></config>'''
    settings=json.dumps({'generator':'Novatech Cut 0.1.5','printer':profile_name,'non_extrusion_job':True,'warning':'UMTS cutting job; verify calibration before use'},ensure_ascii=False,separators=(',',':'))
    b=stats.bounds
    plate=json.dumps({'bed_type':'textured_plate','bbox':[b[0],b[1],b[2],b[3]],'generator':'Novatech Cut'},separators=(',',':'))
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',content_types);z.writestr('_rels/.rels',rels);z.writestr('3D/3dmodel.model',model)
        z.writestr('Metadata/plate_1.gcode',gbytes);z.writestr('Metadata/plate_1.gcode.md5',md5)
        z.writestr('Metadata/model_settings.config',model_settings);z.writestr('Metadata/_rels/model_settings.config.rels',msrels)
        z.writestr('Metadata/slice_info.config',slice_info);z.writestr('Metadata/project_settings.config',settings);z.writestr('Metadata/plate_1.json',plate)
        for name in ('plate_1.png','plate_1_small.png','plate_no_light_1.png','top_1.png','pick_1.png'):z.writestr('Metadata/'+name,PNG_1X1)
    return output

def inspect_gcode_3mf(path):
    required={'[Content_Types].xml','_rels/.rels','3D/3dmodel.model','Metadata/plate_1.gcode','Metadata/plate_1.gcode.md5','Metadata/model_settings.config','Metadata/_rels/model_settings.config.rels','Metadata/slice_info.config','Metadata/project_settings.config','Metadata/plate_1.json'}
    with zipfile.ZipFile(path) as z:
        names=set(z.namelist());missing=required-names
        if missing:raise ValueError('3MF: отсутствуют '+', '.join(sorted(missing)))
        g=z.read('Metadata/plate_1.gcode');expected=z.read('Metadata/plate_1.gcode.md5').decode().strip().upper();actual=hashlib.md5(g).hexdigest().upper()
        if expected!=actual:raise ValueError('3MF: MD5 G-code не совпадает')
    return True
