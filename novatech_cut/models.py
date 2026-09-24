from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Dict, Any

Point = Tuple[float, float]
Path = List[Point]

@dataclass
class PrinterProfile:
    name: str = "Bambu Lab A1 + UMTS"
    bed_width: float = 256.0
    bed_height: float = 256.0
    margin_left: float = 5.0
    margin_right: float = 5.0
    margin_bottom: float = 5.0
    margin_top: float = 5.0
    tool_offset_x: float = 0.0
    tool_offset_y: float = 0.0
    work_z: float = 0.0
    safe_z: float = 5.0
    park_x: float = 20.0
    park_y: float = 240.0
    max_work_speed: float = 120.0  # mm/s
    max_travel_speed: float = 200.0
    max_accel: float = 3000.0
    min_z: float = 0.0
    max_z: float = 256.0
    calibrated: bool = False
    pause_gcode: str = "M400 U1"
    start_template: str = (
        "; NOVATECH CUT SAFE START\n"
        "; UMTS MUST BE REMOVED BEFORE HOMING\n"
        "G90\n"
        "G28\n"
        "G90\n"
        "G1 Z{safe_z:.3f} F600\n"
        "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
        "M400\n"
        "; INSTALL UMTS, THEN RESUME\n"
        "M400 U1\n"
        "G90\n"
        "G1 Z{safe_z:.3f} F600\n"
    )
    end_template: str = (
        "G1 Z{safe_z:.3f} F600\n"
        "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
        "M400\n"
        "; REMOVE UMTS BEFORE ANY FUTURE HOMING\n"
        "M400 U1\n"
        "; END NOVATECH CUT JOB\n"
    )

    @property
    def safe_bounds(self):
        return (
            self.margin_left,
            self.margin_bottom,
            self.bed_width - self.margin_right,
            self.bed_height - self.margin_top,
        )

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]):
        return cls(**d)


@dataclass
class MaterialProfile:
    name: str
    mode: str = "Резка"
    passes: int = 1
    work_speed: float = 30.0
    travel_speed: float = 120.0
    accel: float = 1000.0
    work_z: float = 0.0
    safe_z: float = 5.0
    blade_offset: float = 0.25
    overcut: float = 0.4
    corner_extra: bool = True
    mirror_x: bool = False
    air_test_delta_z: float = 3.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


DEFAULT_MATERIALS = [
    MaterialProfile("Обычная бумага", passes=1, work_speed=45, blade_offset=0.20, overcut=0.25),
    MaterialProfile("Самоклеящаяся бумага", passes=1, work_speed=35, blade_offset=0.25, overcut=0.35),
    MaterialProfile("Виниловая пленка kiss-cut", passes=1, work_speed=25, blade_offset=0.25, overcut=0.45),
    MaterialProfile("Винил с прорезанием подложки", passes=2, work_speed=20, blade_offset=0.25, overcut=0.60),
    MaterialProfile("Тонкий картон", passes=2, work_speed=18, blade_offset=0.30, overcut=0.65),
    MaterialProfile("Трафаретная пленка", passes=1, work_speed=25, blade_offset=0.25, overcut=0.45),
    MaterialProfile("Рисование ручкой", mode="Рисование", passes=1, work_speed=40, blade_offset=0.0, overcut=0.0, corner_extra=False),
    MaterialProfile("Рисование маркером", mode="Рисование", passes=1, work_speed=30, blade_offset=0.0, overcut=0.0, corner_extra=False),
]


@dataclass
class SceneObject:
    name: str
    paths: List[Path]
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation_deg: float = 0.0
    mirror_x: bool = False
    mirror_y: bool = False
    source: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


@dataclass
class Project:
    version: int = 1
    printer: PrinterProfile = field(default_factory=PrinterProfile)
    material: MaterialProfile = field(default_factory=lambda: DEFAULT_MATERIALS[0])
    objects: List[SceneObject] = field(default_factory=list)
    notes: str = ""

    def to_dict(self):
        return {
            "version": self.version,
            "printer": self.printer.to_dict(),
            "material": self.material.to_dict(),
            "objects": [o.to_dict() for o in self.objects],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            version=d.get("version", 1),
            printer=PrinterProfile.from_dict(d.get("printer", {})),
            material=MaterialProfile.from_dict(d.get("material", DEFAULT_MATERIALS[0].to_dict())),
            objects=[SceneObject.from_dict(o) for o in d.get("objects", [])],
            notes=d.get("notes", ""),
        )
