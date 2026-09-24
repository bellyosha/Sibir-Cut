from __future__ import annotations

import tempfile
from pathlib import Path

from .geometry import path_length
from .gcode import generate_gcode, validate_gcode
from .models import Project
from .pack3mf import build_gcode_3mf, inspect_gcode_3mf

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

def main() -> int:
    try:
        run_self_test()
    except Exception:
        return 2
    return 0
