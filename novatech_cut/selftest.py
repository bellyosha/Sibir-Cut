from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

from .geometry import path_length, load_raster
from .gcode import generate_gcode, validate_gcode
from .models import Project, SceneObject
from .pack3mf import build_gcode_3mf, inspect_gcode_3mf
from .pipeline import prepare_paths

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
    cv2.putText(img,'NOVATECH',(180,2250),cv2.FONT_HERSHEY_SIMPLEX,5,0,12,cv2.LINE_AA)
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

def run_self_test() -> None:
    project = Project()
    project.printer.calibrated = True
    square = [(20.0, 20.0), (40.0, 20.0), (40.0, 40.0), (20.0, 40.0), (20.0, 20.0)]
    paths = [square]
    gcode, stats = generate_gcode(paths, project.printer, project.material, air_test=True)
    validate_gcode(gcode, project.printer, require_pause=True)
    upper = gcode.upper()
    for banned in ("M104", "M109", "M140", "M190", "G29", "M82", "M83"):
        if banned in upper:
            raise RuntimeError(f"Self-test found forbidden command: {banned}")
    if path_length(square) <= 0 or stats.cut_length_mm <= 0:
        raise RuntimeError("Self-test path statistics are invalid")
    with tempfile.TemporaryDirectory(prefix="novatech-cut-selftest-") as td:
        out = Path(td) / "selftest.gcode.3mf"
        build_gcode_3mf(out, gcode, stats, profile_name=project.printer.name)
        if inspect_gcode_3mf(out) is not True:
            raise RuntimeError("Self-test 3MF inspection failed")
        _raster_regression_test(td)

def main() -> int:
    try:
        run_self_test()
    except Exception:
        traceback.print_exc()
        return 2
    return 0
