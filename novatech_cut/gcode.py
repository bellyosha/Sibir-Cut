from __future__ import annotations
import math, re
from dataclasses import dataclass
from typing import List
from .models import Path, PrinterProfile, MaterialProfile
from .geometry import path_length, bbox

@dataclass
class JobStats:
    cut_length_mm: float
    travel_length_mm: float
    estimated_seconds: float
    bounds: tuple
    path_count: int
    passes: int

class GCodeError(ValueError): pass

def _fmt(v): return f"{v:.3f}".rstrip('0').rstrip('.')

def analyze_path_bounds(paths: List[Path], printer: PrinterProfile):
    """Return geometric/tool-tip bounds and whether they stay inside the bed."""
    if not paths:
        return {
            'geometry_bounds': (0.0,0.0,0.0,0.0),
            'tool_bounds': (0.0,0.0,0.0,0.0),
            'outside_safe': False,
            'outside_physical': False,
        }
    gb=bbox(paths)
    tb=(
        gb[0]+printer.tool_offset_x,
        gb[1]+printer.tool_offset_y,
        gb[2]+printer.tool_offset_x,
        gb[3]+printer.tool_offset_y,
    )
    l,b,r,t=printer.safe_bounds
    outside_safe=tb[0]<l-1e-6 or tb[1]<b-1e-6 or tb[2]>r+1e-6 or tb[3]>t+1e-6
    outside_physical=tb[0]<-1e-6 or tb[1]<-1e-6 or tb[2]>printer.bed_width+1e-6 or tb[3]>printer.bed_height+1e-6
    return {
        'geometry_bounds': gb,
        'tool_bounds': tb,
        'outside_safe': outside_safe,
        'outside_physical': outside_physical,
    }

def _bounds_error_message(info, printer):
    x0,y0,x1,y1=info['tool_bounds']
    l,b,r,t=printer.safe_bounds
    if info['outside_physical']:
        return (
            "Траектория инструмента выходит за физические границы стола. "
            f"С учётом Offset X/Y: X {x0:.2f}…{x1:.2f}, Y {y0:.2f}…{y1:.2f} мм; "
            f"стол: X 0…{printer.bed_width:.2f}, Y 0…{printer.bed_height:.2f} мм."
        )
    if info['outside_safe']:
        return (
            "Траектория инструмента выходит за настроенную безопасную область. "
            f"С учётом Offset X/Y: X {x0:.2f}…{x1:.2f}, Y {y0:.2f}…{y1:.2f} мм; "
            f"безопасная зона: X {l:.2f}…{r:.2f}, Y {b:.2f}…{t:.2f} мм."
        )
    return ""

def generate_gcode(paths: List[Path], printer: PrinterProfile, material: MaterialProfile, air_test=False):
    if not printer.calibrated:
        raise GCodeError("Профиль принтера не откалиброван. Экспорт заблокирован.")
    bound_info=analyze_path_bounds(paths,printer)
    if bound_info['outside_physical'] or bound_info['outside_safe']:
        raise GCodeError(_bounds_error_message(bound_info,printer))
    if material.mode=='Рисование':
        contact_z=float(printer.work_z)
        press=float(getattr(material,'drawing_press_depth',0.10))
        lift=float(getattr(material,'drawing_lift_height',5.0))
        if not (0.0 <= press <= 0.5):
            raise GCodeError(f"Прижим ручки {press:.3f} мм вне безопасного диапазона 0…0.5 мм.")
        if lift < 3.0:
            raise GCodeError(f"Подъём ручки {lift:.3f} мм слишком мал. Для рисования требуется минимум 3 мм.")
        work_z=contact_z-press
        safe_z=max(float(printer.safe_z),float(material.safe_z),contact_z+lift)
    else:
        work_z = material.work_z if material.work_z != 0 else printer.work_z
        safe_z = max(material.safe_z, printer.safe_z)
    if work_z < printer.min_z-1e-6 or safe_z > printer.max_z+1e-6:
        raise GCodeError(f"Расчёт Z вне диапазона принтера: рабочая Z={work_z:.3f}, безопасная Z={safe_z:.3f}.")
    if air_test: work_z = min(printer.max_z, safe_z + max(1.0, material.air_test_delta_z))
    work_speed=min(material.work_speed,printer.max_work_speed)*60
    travel_speed=min(material.travel_speed,printer.max_travel_speed)*60
    lines=[]
    lines.extend(printer.start_template.format(safe_z=safe_z,park_x=printer.park_x,park_y=printer.park_y,install_wait_seconds=printer.install_wait_seconds,remove_wait_seconds=printer.remove_wait_seconds).splitlines())
    lines.append(f"; MODE: {'AIR TEST' if air_test else material.mode}")
    lines.append(f"; MATERIAL: {material.name}")
    if material.mode=='Рисование':
        lines.append(f"; PEN CONTACT Z: {_fmt(printer.work_z)}")
        lines.append(f"; PEN PRESS DEPTH: {_fmt(getattr(material,'drawing_press_depth',0.10))} mm")
        lines.append(f"; PEN LIFT HEIGHT: {_fmt(getattr(material,'drawing_lift_height',5.0))} mm")
    cut_len=0; travel_len=0; cur=(printer.park_x,printer.park_y)
    for pass_no in range(material.passes):
        lines.append(f"; PASS {pass_no+1}/{material.passes}")
        for pi,path in enumerate(paths,1):
            if len(path)<2:continue
            x0=path[0][0]+printer.tool_offset_x; y0=path[0][1]+printer.tool_offset_y
            lines.append(f"G1 Z{_fmt(safe_z)} F600 ; tool up")
            if material.mode=='Рисование':
                lines.append("M400 ; wait until pen is fully lifted before XY travel")
            lines.append(f"G1 X{_fmt(x0)} Y{_fmt(y0)} F{_fmt(travel_speed)} ; travel path {pi}")
            travel_len+=math.hypot(x0-cur[0],y0-cur[1]);cur=(x0,y0)
            lines.append(f"G1 Z{_fmt(work_z)} F300 ; tool down")
            if material.mode=='Рисование':
                lines.append("M400 ; wait until pen reaches drawing Z")
            for x,y in path[1:]:
                x+=printer.tool_offset_x;y+=printer.tool_offset_y
                lines.append(f"G1 X{_fmt(x)} Y{_fmt(y)} F{_fmt(work_speed)}")
                cut_len+=math.hypot(x-cur[0],y-cur[1]);cur=(x,y)
            lines.append(f"G1 Z{_fmt(safe_z)} F600 ; tool up")
            if material.mode=='Рисование':
                lines.append("M400 ; pen fully clear before next move")
    lines.extend(printer.end_template.format(safe_z=safe_z,park_x=printer.park_x,park_y=printer.park_y,install_wait_seconds=printer.install_wait_seconds,remove_wait_seconds=printer.remove_wait_seconds).splitlines())
    gcode='\n'.join(lines)+'\n'
    validate_gcode(gcode, printer, require_pause=True)
    est=(cut_len/max(0.1,work_speed/60))+(travel_len/max(0.1,travel_speed/60))+len(paths)*material.passes*0.6+4
    b=bound_info['tool_bounds']
    return gcode, JobStats(cut_len,travel_len,est,b,len(paths),material.passes)

def validate_gcode(gcode: str, printer: PrinterProfile, require_pause=True):
    errors=[]; absolute=True; pos={'X':0.0,'Y':0.0,'Z':0.0}; module_installed=False; service_wait_count=0
    allowed={'G0','G1','G28','G90','G91','G4','M400','M104','M140'}
    xmin,ymin,xmax,ymax=printer.safe_bounds
    for n,raw in enumerate(gcode.splitlines(),1):
        code=raw.split(';',1)[0].strip()
        if not code:continue
        parts=code.split(); cmd=parts[0].upper()
        if cmd not in allowed: errors.append(f"Строка {n}: неизвестная/неразрешенная команда {cmd}");continue
        if cmd=='G90': absolute=True;continue
        if cmd=='G91': absolute=False;continue
        if cmd=='M400':
            if any(p.upper()=='U1' for p in parts[1:]):
                errors.append(f"Строка {n}: M400 U1 запрещён для UMTS — прошивка A1 уводит головку в зону очистки сопла")
                continue
            wait_s=None
            for p in parts[1:]:
                if p[:1].upper()=='S':
                    try: wait_s=float(p[1:])
                    except ValueError: errors.append(f"Строка {n}: неверный параметр {p}")
            if wait_s is not None and wait_s>=1:
                service_wait_count+=1
                if service_wait_count==1: module_installed=True
                elif service_wait_count>=2: module_installed=False
            continue
        if cmd in ('M104','M140'):
            sval=None
            for p in parts[1:]:
                if p[:1].upper()=='S':
                    try:sval=float(p[1:])
                    except ValueError:errors.append(f"Строка {n}: неверный параметр {p}")
            if sval is None or abs(sval)>1e-9:
                errors.append(f"Строка {n}: нагрев запрещён ({cmd} допускается только с S0)")
            continue
        if cmd=='G28':
            if getattr(printer,'manual_home_required',False):
                errors.append(f"Строка {n}: автоматический homing внутри UMTS-задания запрещён; выполните homing вручную до запуска файла")
            elif module_installed:
                errors.append(f"Строка {n}: homing после установки UMTS запрещен")
            continue
        if cmd in ('G0','G1'):
            vals={}
            for p in parts[1:]:
                if len(p)>1 and p[0].upper() in 'XYZEF':
                    try: vals[p[0].upper()]=float(p[1:])
                    except ValueError: errors.append(f"Строка {n}: неверный параметр {p}")
            if 'E' in vals:errors.append(f"Строка {n}: экструзия E запрещена")
            for ax in 'XYZ':
                if ax in vals:pos[ax]=vals[ax] if absolute else pos[ax]+vals[ax]
            if 'Z' in vals and not (printer.min_z-1e-6 <= pos['Z'] <= printer.max_z+1e-6):
                errors.append(f"Строка {n}: Z вне допустимого диапазона: Z={pos['Z']:.3f}")
            if module_installed and ('X' in vals or 'Y' in vals):
                if not (xmin-1e-6<=pos['X']<=xmax+1e-6 and ymin-1e-6<=pos['Y']<=ymax+1e-6):
                    errors.append(f"Строка {n}: X/Y вне безопасной области: X={pos['X']:.3f}, Y={pos['Y']:.3f}")
    upper=gcode.upper()
    for banned in ('M109','M190','G29','M82','M83'):
        if re.search(rf'(^|\n)\s*{banned}\b',upper):errors.append(f"Запрещенная команда {banned}")
    if require_pause and service_wait_count<2:errors.append("Нет двух обязательных ожиданий установки/снятия UMTS на краю стола")
    if not re.search(r'G1\s+Z[-+\d.]',gcode,re.I):errors.append("Нет управляемого подъема Z")
    if errors: raise GCodeError('\n'.join(dict.fromkeys(errors)))
    return True
