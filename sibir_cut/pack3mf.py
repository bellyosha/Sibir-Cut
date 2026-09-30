from __future__ import annotations
import hashlib, json, zipfile, base64
from pathlib import Path

PNG_1X1 = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2c4sAAAAASUVORK5CYII=')

def build_gcode_3mf(output, gcode: str, stats, profile_name='Bambu Lab A1 + UMTS'):
    output=Path(output); gbytes=gcode.encode('utf-8'); md5=hashlib.md5(gbytes).hexdigest().upper()
    content_types='''<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="gcode" ContentType="text/plain"/><Default Extension="json" ContentType="application/json"/><Default Extension="config" ContentType="application/xml"/></Types>'''
    rels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'''
    model='''<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><metadata name="Application">Sibir Cut</metadata><resources/><build/></model>'''
    model_settings='''<?xml version="1.0" encoding="UTF-8"?><config><plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value="Sibir Cut"/><metadata key="locked" value="false"/><metadata key="filament_map_mode" value="Auto For Flush"/><metadata key="filament_maps" value="1 1 1 1 1"/><metadata key="filament_volume_maps" value="0 0 0 0 0"/><metadata key="gcode_file" value="Metadata/plate_1.gcode"/><metadata key="thumbnail_file" value="Metadata/plate_1.png"/><metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/><metadata key="top_file" value="Metadata/top_1.png"/><metadata key="pick_file" value="Metadata/pick_1.png"/><metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/></plate></config>'''
    msrels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/Metadata/plate_1.gcode" Id="rel0" Type="http://schemas.bambulab.com/package/2021/relationships/gcode"/></Relationships>'''
    slice_info=f'''<?xml version="1.0" encoding="UTF-8"?><config><header><header_item key="X-BBL-Client-Type" value="slicer"/><header_item key="X-BBL-Client-Version" value="SibirCut-0.3.3"/></header><plate><metadata key="index" value="1"/><metadata key="prediction" value="{int(stats.estimated_seconds)}"/><metadata key="weight" value="0"/><metadata key="printer_model_id" value="SIBIR_A1_UMTS"/><metadata key="extruder_type" value="0"/><metadata key="nozzle_volume_type" value="0"/><metadata key="limit_filament_maps" value="0 0 0 0 0"/></plate></config>'''
    settings=json.dumps({'generator':'Sibir Cut 0.2.10','printer':profile_name,'non_extrusion_job':True,'warning':'UMTS cutting job; verify calibration before use'},ensure_ascii=False,separators=(',',':'))
    b=stats.bounds
    plate=json.dumps({'bed_type':'textured_plate','bbox':[b[0],b[1],b[2],b[3]],'generator':'Sibir Cut'},separators=(',',':'))
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


def build_orca_preview_3mf(output, paths, line_width=0.35, height=0.20, max_segments=20000):
    """Build a geometry-only 3MF for visual inspection in OrcaSlicer.

    This file is NOT the printer job. Each XY toolpath segment is represented
    as a thin rectangular prism so Orca has real geometric data to display.
    """
    import math
    from xml.etree import ElementTree as ET

    output=Path(output)
    vertices=[]
    triangles=[]
    seg_count=0
    half=max(0.03,float(line_width)/2.0)
    h=max(0.02,float(height))

    def add_prism(a,b):
        nonlocal seg_count
        x1,y1=a;x2,y2=b
        dx=x2-x1;dy=y2-y1
        length=math.hypot(dx,dy)
        if length<1e-6:
            return
        nx=-dy/length*half;ny=dx/length*half
        base=len(vertices)
        pts=[
            (x1+nx,y1+ny,0.0),(x1-nx,y1-ny,0.0),(x2-nx,y2-ny,0.0),(x2+nx,y2+ny,0.0),
            (x1+nx,y1+ny,h),(x1-nx,y1-ny,h),(x2-nx,y2-ny,h),(x2+nx,y2+ny,h),
        ]
        vertices.extend(pts)
        faces=[
            (0,1,2),(0,2,3), (4,6,5),(4,7,6),
            (0,4,5),(0,5,1), (1,5,6),(1,6,2),
            (2,6,7),(2,7,3), (3,7,4),(3,4,0),
        ]
        triangles.extend((base+a0,base+b0,base+c0) for a0,b0,c0 in faces)
        seg_count+=1

    for path in paths:
        for a,b in zip(path,path[1:]):
            add_prism(a,b)
            if seg_count>=max_segments:
                break
        if seg_count>=max_segments:
            break
    if not triangles:
        raise ValueError('Не удалось построить геометрию предпросмотра для Orca')

    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    ET.register_namespace('',ns)
    model=ET.Element('{%s}model'%ns,{'unit':'millimeter','xml:lang':'en-US'})
    md=ET.SubElement(model,'{%s}metadata'%ns,{'name':'Application'});md.text='Sibir Cut Orca Preview'
    resources=ET.SubElement(model,'{%s}resources'%ns)
    obj=ET.SubElement(resources,'{%s}object'%ns,{'id':'1','type':'model'})
    mesh=ET.SubElement(obj,'{%s}mesh'%ns)
    verts=ET.SubElement(mesh,'{%s}vertices'%ns)
    for x,y,z in vertices:
        ET.SubElement(verts,'{%s}vertex'%ns,{'x':f'{x:.5f}','y':f'{y:.5f}','z':f'{z:.5f}'})
    tris=ET.SubElement(mesh,'{%s}triangles'%ns)
    for a,b,c in triangles:
        ET.SubElement(tris,'{%s}triangle'%ns,{'v1':str(a),'v2':str(b),'v3':str(c)})
    build=ET.SubElement(model,'{%s}build'%ns)
    ET.SubElement(build,'{%s}item'%ns,{'objectid':'1'})
    model_bytes=ET.tostring(model,encoding='utf-8',xml_declaration=True)

    content_types='''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'''
    rels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'''
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',content_types)
        z.writestr('_rels/.rels',rels)
        z.writestr('3D/3dmodel.model',model_bytes)
    return output

def inspect_orca_preview_3mf(path):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(path) as z:
        names=set(z.namelist())
        for required in ('[Content_Types].xml','_rels/.rels','3D/3dmodel.model'):
            if required not in names:
                raise ValueError(f'Orca preview 3MF: отсутствует {required}')
        root=ET.fromstring(z.read('3D/3dmodel.model'))
        ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
        verts=root.findall('.//m:vertex',ns)
        tris=root.findall('.//m:triangle',ns)
        items=root.findall('.//m:build/m:item',ns)
        if not verts or not tris or not items:
            raise ValueError('Orca preview 3MF: нет геометрических данных')
    return True
