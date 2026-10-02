from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

from .geometry import path_length, load_raster, _morphological_skeleton, hatch_fill_paths, object_world_center, set_object_transform_about_center
from .gcode import generate_gcode, validate_gcode, analyze_path_bounds, GCodeError
from .lan import lan_self_test
from .discovery import discovery_self_test
from .transfer import transfer_self_test
from .models import Project, SceneObject, PrinterProfile
from .pack3mf import build_gcode_3mf, inspect_gcode_3mf, build_orca_preview_3mf, inspect_orca_preview_3mf
from .pipeline import prepare_paths, import_paths, detect_import_kind

def _raster_regression_test(td: str) -> None:
    import cv2
    import numpy as np

    # Reproduces the class of images that froze v0.1.0: large raster with
    # hundreds of independent shapes. The loader must downsample and bound
    # vector complexity before the CAM pipeline sees it.
    img=np.full((2400,3200),255,dtype=np.uint8)
    for row in range(15):
        for col in range(28):
            x=45+col*110
            y=50+row*145
            cv2.rectangle(img,(x,y),(x+58,y+72),0,-1)
            cv2.circle(img,(x+75,y+35),18,0,3)
    cv2.putText(img,'SIBIR CUT',(180,2250),cv2.FONT_HERSHEY_SIMPLEX,5,0,12,cv2.LINE_AA)
    png=Path(td)/'large-raster-regression.png'
    if not cv2.imwrite(str(png),img):
        raise RuntimeError('Could not write raster regression image')

    paths=load_raster(str(png),threshold=128,invert=False,min_area=10,external_only=True,smoothing=1.0,centerline=False)
    total=sum(len(p) for p in paths)
    if not paths:
        raise RuntimeError('Raster regression produced no contours')
    if len(paths)>2500 or total>65000:
        raise RuntimeError(f'Raster complexity guard failed: {len(paths)} paths, {total} points')

    project=Project()
    obj=SceneObject('large-raster-regression',paths)
    prepared=prepare_paths([obj],project.material)
    if not prepared:
        raise RuntimeError('Raster CAM preparation produced no paths')
    if sum(len(p) for p in prepared)>120000:
        raise RuntimeError('Prepared raster path count exploded unexpectedly')

def _file_detection_regression_test(td: str) -> None:
    import cv2
    import numpy as np
    unicode_dir=Path(td)/'Тестовая папка'
    unicode_dir.mkdir(parents=True,exist_ok=True)
    img=np.full((180,240),255,dtype=np.uint8)
    cv2.rectangle(img,(25,30),(190,140),0,-1)
    ok,encoded=cv2.imencode('.png',img)
    if not ok: raise RuntimeError('Could not encode PNG regression image')
    png=unicode_dir/'картинка для резки.png'
    encoded.tofile(str(png))
    if detect_import_kind(str(png))!='raster': raise RuntimeError('PNG detection failed')
    if not import_paths(str(png),threshold=128,external_only=True,smoothing=1.0): raise RuntimeError('Unicode raster import failed')
    fake_svg=unicode_dir/'рисунок.svg'
    fake_svg.write_bytes(png.read_bytes())
    if detect_import_kind(str(fake_svg))!='raster': raise RuntimeError('Mislabeled PNG-as-SVG detection failed')
    if not import_paths(str(fake_svg),threshold=128,external_only=True,smoothing=1.0): raise RuntimeError('Mislabeled PNG-as-SVG import failed')
    # Regression for AI-generated PNG/JUMBF files that contain an embedded
    # SVG snippet in metadata. The PNG signature must win.
    png_with_svg_meta=unicode_dir/'chatgpt-image.svg'
    png_with_svg_meta.write_bytes(png.read_bytes()+b'image/svg+xml<svg width="64" height="64"></svg>')
    if detect_import_kind(str(png_with_svg_meta))!='raster':
        raise RuntimeError('PNG with embedded SVG metadata was misdetected as SVG')
    if not import_paths(str(png_with_svg_meta),threshold=128,external_only=True,smoothing=1.0):
        raise RuntimeError('PNG with embedded SVG metadata import failed')
    real_svg=unicode_dir/'вектор.png'
    real_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30"><rect x="2" y="2" width="30" height="20"/></svg>',encoding='utf-8')
    if detect_import_kind(str(real_svg))!='svg': raise RuntimeError('SVG content detection failed')
    if not import_paths(str(real_svg)): raise RuntimeError('SVG content import failed')

def _transparent_png_thread_regression_test(td: str) -> None:
    import cv2
    import numpy as np
    import queue
    import threading
    import time

    # Mimic transparent AI-generated PNGs: transparent pixels have black RGB,
    # while only the drawn shape is opaque. This used to become a full black
    # page when alpha was discarded.
    rgba=np.zeros((1254,1254,4),dtype=np.uint8)
    cv2.line(rgba,(120,1100),(1130,180),(0,0,0,255),48,cv2.LINE_AA)
    cv2.circle(rgba,(650,620),260,(0,0,0,255),35,cv2.LINE_AA)
    ok,encoded=cv2.imencode('.png',rgba)
    if not ok: raise RuntimeError('Could not encode transparent PNG regression image')
    p=Path(td)/'прозрачная картинка.png'
    encoded.tofile(str(p))

    result=queue.Queue(maxsize=1)
    def worker():
        try:
            t0=time.monotonic()
            paths=import_paths(str(p),threshold=128,invert=False,external_only=False,smoothing=1.0,centerline=True)
            result.put((paths,time.monotonic()-t0,None))
        except Exception as exc:
            result.put((None,None,exc))
    th=threading.Thread(target=worker,daemon=True)
    th.start();th.join(10.0)
    if th.is_alive():
        raise RuntimeError('Transparent PNG centerline import did not finish within 10 seconds')
    paths,elapsed,error=result.get_nowait()
    if error is not None: raise error
    if not paths: raise RuntimeError('Transparent PNG centerline import produced no paths')
    if elapsed>10.0: raise RuntimeError(f'Transparent PNG centerline import too slow: {elapsed:.2f}s')

def _centerline_completeness_regression_test() -> None:
    import cv2
    import numpy as np
    img=np.zeros((420,900),dtype=np.uint8)
    cv2.putText(img,'AH',(35,330),cv2.FONT_HERSHEY_SIMPLEX,9,255,55,cv2.LINE_AA)
    skel=_morphological_skeleton(img)
    if cv2.countNonZero(skel)<300:
        raise RuntimeError('Centerline skeleton is unexpectedly sparse')
    n,labels,stats,_=cv2.connectedComponentsWithStats(skel,8)
    components=sum(1 for i in range(1,n) if stats[i,cv2.CC_STAT_AREA]>=5)
    if components>4:
        raise RuntimeError(f'Centerline skeleton fragmented into {components} components')
    ys,xs=np.where(skel>0)
    if xs.size==0 or (xs.max()-xs.min())<250 or (ys.max()-ys.min())<150:
        raise RuntimeError('Centerline skeleton does not cover the source glyphs')

def _drawing_fill_regression_test() -> None:
    outer=[(0.0,0.0),(40.0,0.0),(40.0,40.0),(0.0,40.0),(0.0,0.0)]
    hole=[(12.0,12.0),(28.0,12.0),(28.0,28.0),(12.0,28.0),(12.0,12.0)]
    fill=hatch_fill_paths([outer,hole],spacing=2.0,angle_deg=0.0,inset=0.0,crosshatch=False)
    if len(fill)<10:
        raise RuntimeError('Drawing hatch fill produced too few lines')
    for seg in fill:
        if len(seg)<2: continue
        mx=(seg[0][0]+seg[-1][0])/2;my=(seg[0][1]+seg[-1][1])/2
        if 12.01<mx<27.99 and 12.01<my<27.99:
            raise RuntimeError('Drawing hatch crossed an inner hole')
    project=Project();project.material.mode='Рисование';project.material.drawing_style='Контур + заливка';project.material.fill_spacing=2.0;project.objects=[SceneObject('donut',[outer,hole])]
    prepared=prepare_paths(project.objects,project.material)
    if len(prepared)<=2:
        raise RuntimeError('Drawing pipeline did not add fill paths')

def _mirror_job_regression_test() -> None:
    project=Project()
    project.material.blade_offset=0.0
    project.material.overcut=0.0
    project.objects=[SceneObject('asymmetric',[[(0.0,0.0),(10.0,0.0),(2.0,5.0)]])]
    project.material.mirror_x=False
    normal=prepare_paths(project.objects,project.material)
    project.material.mirror_x=True
    mirrored=prepare_paths(project.objects,project.material)
    if not normal or not mirrored:
        raise RuntimeError('Mirror regression produced no paths')
    if len(normal[0])!=len(mirrored[0]):
        raise RuntimeError('Mirror regression changed path length')
    x0=min(x for p in normal for x,_ in p);x1=max(x for p in normal for x,_ in p)
    expected=[(x0+x1-x,y) for x,y in normal[0]]
    for got,want in zip(mirrored[0],expected):
        if abs(got[0]-want[0])>1e-6 or abs(got[1]-want[1])>1e-6:
            raise RuntimeError('Whole-job horizontal mirror is incorrect')

def _live_transform_regression_test() -> None:
    obj=SceneObject('live-transform',[[(0.0,0.0),(40.0,0.0),(40.0,20.0),(0.0,20.0),(0.0,0.0)]],x=73.0,y=61.0,scale=1.25,rotation_deg=17.0)
    center0=object_world_center(obj)
    set_object_transform_about_center(obj,center0,rotation_deg=123.4,scale=2.15)
    center1=object_world_center(obj)
    if abs(center1[0]-center0[0])>1e-8 or abs(center1[1]-center0[1])>1e-8:
        raise RuntimeError('Live rotate/scale moved the object center')
    if abs(obj.rotation_deg-123.4)>1e-9 or abs(obj.scale-2.15)>1e-9:
        raise RuntimeError('Live transform did not apply requested rotation/scale')
    obj.mirror_x=True
    center2=object_world_center(obj)
    set_object_transform_about_center(obj,center2,rotation_deg=-41.25,scale=0.75)
    center3=object_world_center(obj)
    if abs(center3[0]-center2[0])>1e-8 or abs(center3[1]-center2[1])>1e-8:
        raise RuntimeError('Live transform moved mirrored object center')

def _bounds_regression_test() -> None:
    project=Project();project.printer.calibrated=True
    good=[[(10.0,10.0),(40.0,10.0),(40.0,40.0)]]
    info=analyze_path_bounds(good,project.printer)
    if info['outside_safe'] or info['outside_physical']:
        raise RuntimeError('Valid toolpath was incorrectly marked outside the bed')

    # Physical convention: tool_tip = nozzle + offset. A negative X offset
    # shifts the nozzle to the right and may push it beyond the bed.
    project.printer.tool_offset_x=-20.0
    near_edge=[[(240.0,20.0),(250.0,20.0)]]
    info=analyze_path_bounds(near_edge,project.printer)
    if not info['outside_physical']:
        raise RuntimeError('Tool offset overrun was not detected')
    try:
        generate_gcode(near_edge,project.printer,project.material,air_test=True)
    except GCodeError:
        pass
    else:
        raise RuntimeError('Export did not block a toolpath outside the physical bed')

    project.printer.tool_offset_x=20.0
    probe=[[(100.0,100.0),(110.0,100.0)]]
    g,_=generate_gcode(probe,project.printer,project.material,air_test=True)
    if 'G1 X80 Y100' not in g:
        raise RuntimeError('Tool offset sign is wrong: nozzle must move to tool_x - offset_x')

def _tool_calibration_regression_test() -> None:
    p=PrinterProfile()
    p.set_tool_calibration('knife',offset_x=12.5,offset_y=-3.0,z=4.2,safe_z=8.0,xy_calibrated=True,z_calibrated=True)
    p.set_tool_calibration('pen',offset_x=-8.0,offset_y=6.0,z=5.1,safe_z=9.0,xy_calibrated=True,z_calibrated=True)
    p.apply_tool_calibration('Резка')
    if not p.calibrated or abs(p.tool_offset_x-12.5)>1e-9 or abs(p.work_z-4.2)>1e-9:
        raise RuntimeError('Knife calibration was not auto-applied')
    p.apply_tool_calibration('Рисование')
    if not p.calibrated or abs(p.tool_offset_x+8.0)>1e-9 or abs(p.work_z-5.1)>1e-9:
        raise RuntimeError('Pen calibration was not auto-applied')
    p2=PrinterProfile()
    p2.set_tool_calibration('knife',offset_x=1.0,offset_y=2.0,xy_calibrated=True)
    p2.apply_tool_calibration('Резка')
    if p2.calibrated:
        raise RuntimeError('XY-only calibration must not unlock export before Z is calibrated')

def _drawing_z_safety_regression_test() -> None:
    project=Project();project.printer.calibrated=True
    project.printer.work_z=5.0   # first contact, no pressure
    project.printer.safe_z=8.0
    project.material.mode='Рисование'
    project.material.name='Рисование ручкой'
    project.material.drawing_press_depth=0.10
    project.material.drawing_lift_height=5.0
    paths=[[(20.0,20.0),(40.0,20.0)],[(20.0,30.0),(40.0,30.0)]]
    gcode,_=generate_gcode(paths,project.printer,project.material,air_test=False)
    upper=gcode.upper()
    if 'G1 Z4.9' not in upper:
        raise RuntimeError('Drawing Z is not derived from first-contact Z minus pen pressure')
    if 'G1 Z10' not in upper:
        raise RuntimeError('Pen safe Z is not derived from contact Z plus lift height')
    lines=[line.split(';',1)[0].strip().upper() for line in gcode.splitlines()]
    # Every drawing travel must have a completed Z lift before XY motion.
    for i,line in enumerate(lines):
        if 'TRAVEL PATH' in gcode.splitlines()[i].upper() if i < len(gcode.splitlines()) else False:
            pass
    raw=gcode.splitlines()
    for i,line in enumerate(raw):
        if '; travel path ' in line.lower():
            prev=[x.split(';',1)[0].strip().upper() for x in raw[max(0,i-3):i]]
            if not any(x=='M400' for x in prev):
                raise RuntimeError('Drawing XY travel is not preceded by M400 after pen lift')
    # Unsafe pressure must be blocked.
    project.material.drawing_press_depth=0.8
    try:
        generate_gcode(paths,project.printer,project.material,air_test=False)
    except GCodeError:
        pass
    else:
        raise RuntimeError('Excessive drawing pressure was not blocked')

def _direct_gcode_regression_test() -> None:
    project=Project();project.printer.calibrated=True
    project.printer.work_z=5.0;project.printer.safe_z=8.0
    project.material.mode='Рисование';project.material.drawing_press_depth=0.05;project.material.drawing_lift_height=5.0
    paths=[[(20.0,20.0),(40.0,20.0)]]
    gcode,_=generate_gcode(paths,project.printer,project.material,air_test=True)
    u=gcode.upper()
    if 'M109 ' in u or 'G1 E' in u or 'G28' in u:
        raise RuntimeError('Direct A1 G-code contains a standard print startup command')
    code_only='\n'.join(line.split(';',1)[0].strip().upper() for line in gcode.splitlines())
    if 'M400 U1' in code_only:
        raise RuntimeError('Direct A1 G-code contains firmware pause that relocates the toolhead')
    if u.count('M400 S')<2:
        raise RuntimeError('Direct A1 G-code must hold in place for install and removal')
    if u.count('M400 S10')<2:
        raise RuntimeError('Default UMTS install/remove holds must be 10 seconds')
    park_ok=False
    for line in gcode.splitlines():
        code=line.split(';',1)[0].strip().upper()
        if not code.startswith(('G0 ','G1 ')): continue
        vals={}
        for token in code.split()[1:]:
            if token[:1] in ('X','Y'):
                try: vals[token[0]]=float(token[1:])
                except ValueError: pass
        if abs(vals.get('X',-999)-230.0)<1e-3 and abs(vals.get('Y',-999)-10.0)<1e-3:
            park_ok=True
    if not park_ok:
        raise RuntimeError('Direct A1 G-code does not park away from the nozzle-wiper area')

def _service_wait_migration_test() -> None:
    old=PrinterProfile().to_dict()
    old['service_wait_version']=2
    old['install_wait_seconds']=300.0
    old['remove_wait_seconds']=180.0
    migrated=PrinterProfile.from_dict(old)
    if migrated.install_wait_seconds != 10.0 or migrated.remove_wait_seconds != 10.0:
        raise RuntimeError('0.2.9 default UMTS waits were not migrated to 10 seconds')
    custom=PrinterProfile().to_dict()
    custom['service_wait_version']=2
    custom['install_wait_seconds']=45.0
    custom['remove_wait_seconds']=20.0
    migrated_custom=PrinterProfile.from_dict(custom)
    if migrated_custom.install_wait_seconds != 45.0 or migrated_custom.remove_wait_seconds != 20.0:
        raise RuntimeError('User-custom service waits must be preserved during migration')

def run_self_test() -> None:
    from .lan_checks import run_lan_checks
    run_lan_checks()
    discovery_self_test()
    lan_self_test()
    transfer_self_test()
    _service_wait_migration_test()
    project = Project()
    project.printer.calibrated = True
    square = [(20.0, 20.0), (40.0, 20.0), (40.0, 40.0), (20.0, 40.0), (20.0, 20.0)]
    paths = [square]
    gcode, stats = generate_gcode(paths, project.printer, project.material, air_test=True)
    validate_gcode(gcode, project.printer, require_pause=True)
    upper = gcode.upper()
    for banned in ("M109", "M190", "G29", "M82", "M83"):
        if banned in upper:
            raise RuntimeError(f"Self-test found forbidden command: {banned}")
    if "G28" in upper:
        raise RuntimeError("UMTS job must not contain automatic homing")
    if "M104 S0" not in upper or "M140 S0" not in upper:
        raise RuntimeError("UMTS job must explicitly disable nozzle and bed heaters")
    code_only='\n'.join(line.split(';',1)[0].strip().upper() for line in gcode.splitlines())
    if "M400 U1" in code_only:
        raise RuntimeError("Firmware pause M400 U1 must not be used because A1 moves to the wiper area")
    if any(line.strip().startswith("G1 E") or " E" in line.split(";",1)[0] for line in upper.splitlines()):
        raise RuntimeError("UMTS job must not extrude filament")
    timed_waits=[i for i,line in enumerate(gcode.splitlines()) if line.strip().upper().startswith("M400 S")]
    if len(timed_waits)<2:
        raise RuntimeError("UMTS install/remove timed holds are missing")
    first_wait_line=timed_waits[0]
    prefix='\n'.join(gcode.splitlines()[:first_wait_line])
    park_ok=False
    for line in prefix.splitlines():
        code=line.split(';',1)[0].strip()
        if not code.upper().startswith(('G0 ','G1 ')):
            continue
        vals={}
        for token in code.split()[1:]:
            if token[:1].upper() in ('X','Y'):
                try:vals[token[0].upper()]=float(token[1:])
                except ValueError:pass
        if 'X' in vals and 'Y' in vals:
            if abs(vals['X']-project.printer.park_x)<1e-3 and abs(vals['Y']-project.printer.park_y)<1e-3:
                park_ok=True
    if not park_ok:
        raise RuntimeError("Toolhead is not parked at the accessible edge before UMTS installation pause")
    if path_length(square) <= 0 or stats.cut_length_mm <= 0:
        raise RuntimeError("Self-test path statistics are invalid")
    with tempfile.TemporaryDirectory(prefix="sibir-cut-selftest-") as td:
        out = Path(td) / "selftest.gcode.3mf"
        build_gcode_3mf(out, gcode, stats, profile_name=project.printer.name)
        if inspect_gcode_3mf(out) is not True:
            raise RuntimeError("Self-test 3MF inspection failed")
        preview=Path(td)/"selftest_ORCA_PREVIEW.3mf"
        build_orca_preview_3mf(preview,paths)
        if inspect_orca_preview_3mf(preview) is not True:
            raise RuntimeError("Orca preview 3MF inspection failed")
        _raster_regression_test(td)
        _file_detection_regression_test(td)
        _transparent_png_thread_regression_test(td)
        _centerline_completeness_regression_test()
        _drawing_fill_regression_test()
        _mirror_job_regression_test()
        _live_transform_regression_test()
        _bounds_regression_test()
        _tool_calibration_regression_test()
        _drawing_z_safety_regression_test()
        _direct_gcode_regression_test()

def main() -> int:
    try:
        run_self_test()
    except Exception:
        tb=traceback.format_exc()
        try:
            (Path(tempfile.gettempdir())/'sibir-cut-selftest-error.txt').write_text(tb,encoding='utf-8')
        except Exception:
            pass
        traceback.print_exc()
        return 2
    return 0
