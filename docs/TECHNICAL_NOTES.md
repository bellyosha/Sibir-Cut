# Технические заметки Novatech Cut 0.2.8

Дата проверки: 24.09.2026.

## Архитектура

- `models.py` — профиль A1/UMTS, материалы, объекты и формат проекта.
- `geometry.py` — SVG/DXF/raster import, affine transforms, simplification, ordering and drag-knife compensation.
- `pipeline.py` — единый конвейер подготовки траекторий.
- `gcode.py` — generator, statistics and second-pass safety validator.
- `pack3mf.py` — packaging and structural inspection of `.gcode.3mf`.
- `app.py` — Russian desktop UI.

## Bambu-specific decisions

The verified pause command used by Bambu Studio profiles is `M400 U1`. Starting with 0.2.8 the UMTS job contains no automatic `G28`; the operator must home manually before launching the file with UMTS removed. The file explicitly sends `M104 S0` and `M140 S0`, parks at the accessible front edge, then pauses for installation. Non-zero heating, extrusion and ABL are rejected. A second pause is emitted after returning to the front-edge park so the user can remove UMTS.

The `.gcode.3mf` writer creates the OPC/3MF container, `Metadata/plate_1.gcode`, uppercase MD5, plate metadata, slice metadata, project metadata and thumbnails. The archive is re-opened and checksum-validated by tests.

## Hardware validation boundary

No physical Bambu Lab A1 is attached to the execution environment. Therefore hardware acceptance of the generated `.gcode.3mf` against a specific firmware is **not claimed**. The first real test must be air-only.

## Windows build boundary

The repository contains the Windows CI workflow that builds and self-tests the frozen executable and installer.


## Drawing Z safety

0.2.8 changes drawing Z semantics. PrinterProfile.work_z is treated as calibrated first-contact Z (no spring compression). MaterialProfile.drawing_press_depth derives drawing Z as contact_z - press_depth, while drawing_lift_height derives safe drawing Z as at least contact_z + lift_height. Pressure is hard-limited to 0…0.5 mm and lift must be at least 3 mm. In drawing mode every pen-up move is followed by M400 before XY travel, and every pen-down move is followed by M400 before drawing.


## Direct A1 G-code handoff

0.2.8 changes the hardware handoff path. The executable job is now plain `.gcode`, intended to be copied to microSD and started from the A1 screen. The application no longer uses `.gcode.3mf` as the primary UMTS job because the normal slicer/project workflow can introduce the standard A1 machine-start sequence before the custom path. Orca receives only a geometry-only `*_ORCA_PREVIEW.3mf`. The default UMTS install/remove park is X230 Y10, away from the A1 wipe area.
