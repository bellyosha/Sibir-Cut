# Технические заметки Novatech Cut 0.2.6

Дата проверки: 24.09.2026.

## Архитектура

- `models.py` — профиль A1/UMTS, материалы, объекты и формат проекта.
- `geometry.py` — SVG/DXF/raster import, affine transforms, simplification, ordering and drag-knife compensation.
- `pipeline.py` — единый конвейер подготовки траекторий.
- `gcode.py` — generator, statistics and second-pass safety validator.
- `pack3mf.py` — packaging and structural inspection of `.gcode.3mf`.
- `app.py` — Russian desktop UI.

## Bambu-specific decisions

The verified pause command used by Bambu Studio profiles is `M400 U1`. Starting with 0.2.6 the UMTS job contains no automatic `G28`; the operator must home manually before launching the file with UMTS removed. The file explicitly sends `M104 S0` and `M140 S0`, parks at the accessible front edge, then pauses for installation. Non-zero heating, extrusion and ABL are rejected. A second pause is emitted after returning to the front-edge park so the user can remove UMTS.

The `.gcode.3mf` writer creates the OPC/3MF container, `Metadata/plate_1.gcode`, uppercase MD5, plate metadata, slice metadata, project metadata and thumbnails. The archive is re-opened and checksum-validated by tests.

## Hardware validation boundary

No physical Bambu Lab A1 is attached to the execution environment. Therefore hardware acceptance of the generated `.gcode.3mf` against a specific firmware is **not claimed**. The first real test must be air-only.

## Windows build boundary

The repository contains the Windows CI workflow that builds and self-tests the frozen executable and installer.
