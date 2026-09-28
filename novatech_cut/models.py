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
    # Physical tool-tip offset relative to the nozzle:
    # tool_tip = nozzle + offset. Therefore CAM moves the nozzle to
    # desired_tool_point - offset.
    tool_offset_x: float = 0.0
    tool_offset_y: float = 0.0
    tool_offset_version: int = 2
    # Separate persistent calibration for knife and pen. "z" is working Z
    # for the knife and first-contact Z (without pressure) for the pen.
    tool_calibrations: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "knife": {"offset_x": 0.0, "offset_y": 0.0, "z": 0.0, "safe_z": 5.0, "xy_calibrated": False, "z_calibrated": False, "calibrated": False},
        "pen": {"offset_x": 0.0, "offset_y": 0.0, "z": 0.0, "safe_z": 5.0, "xy_calibrated": False, "z_calibrated": False, "calibrated": False},
    })
    work_z: float = 0.0
    safe_z: float = 5.0
    # Z calibration v2: work_z means FIRST CONTACT, not drawing pressure.
    z_calibration_version: int = 2
    # Accessible front-edge parking point used for installing/removing UMTS.
    park_x: float = 230.0
    park_y: float = 10.0
    manual_home_required: bool = True
    # Bambu firmware M400 U1 always parks in its own pause/wiper location.
    # UMTS therefore uses an in-place timed service hold at park_x/park_y.
    service_wait_version: int = 3
    install_wait_seconds: float = 10.0
    remove_wait_seconds: float = 10.0
    max_work_speed: float = 120.0  # mm/s
    max_travel_speed: float = 200.0
    max_accel: float = 3000.0
    min_z: float = 0.0
    max_z: float = 256.0
    calibrated: bool = False
    pause_gcode: str = "M400 S{install_wait_seconds:.0f}"
    start_template: str = (
        "; SIBIR CUT UMTS START V3\n"
        "; IMPORTANT: HOME THE PRINTER MANUALLY WITH UMTS REMOVED BEFORE STARTING THIS JOB\n"
        "; No firmware pause command is used: M400 U1 would move the head to the wiper area.\n"
        "M104 S0\n"
        "M140 S0\n"
        "G90\n"
        "G1 Z{safe_z:.3f} F600\n"
        "; MOVE TO ACCESSIBLE FRONT EDGE FOR UMTS INSTALLATION\n"
        "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
        "M400\n"
        "; INSTALL UMTS NOW - HEAD REMAINS HERE DURING THIS TIMED HOLD\n"
        "M400 S{install_wait_seconds:.0f}\n"
        "G90\n"
        "G1 Z{safe_z:.3f} F600\n"
    )
    end_template: str = (
        "G1 Z{safe_z:.3f} F600\n"
        "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
        "M400\n"
        "; REMOVE UMTS NOW - HEAD REMAINS HERE DURING THIS TIMED HOLD\n"
        "M400 S{remove_wait_seconds:.0f}\n"
        "; END SIBIR CUT JOB\n"
    )

    @staticmethod
    def tool_key_for_mode(mode: str) -> str:
        return "pen" if str(mode or "").strip().lower() == "рисование".lower() else "knife"

    def get_tool_calibration(self, key_or_mode: str) -> Dict[str, Any]:
        key = key_or_mode if key_or_mode in ("knife", "pen") else self.tool_key_for_mode(key_or_mode)
        base = {"offset_x": 0.0, "offset_y": 0.0, "z": 0.0, "safe_z": 5.0, "xy_calibrated": False, "z_calibrated": False, "calibrated": False}
        raw = self.tool_calibrations.get(key, {}) if isinstance(self.tool_calibrations, dict) else {}
        if isinstance(raw, dict):
            base.update(raw)
        for k in ("offset_x", "offset_y", "z", "safe_z"):
            try: base[k] = float(base.get(k, 0.0))
            except Exception: base[k] = 0.0 if k != "safe_z" else 5.0
        if "xy_calibrated" not in raw and base.get("calibrated"): base["xy_calibrated"] = True
        if "z_calibrated" not in raw and base.get("calibrated"): base["z_calibrated"] = True
        base["xy_calibrated"] = bool(base.get("xy_calibrated", False))
        base["z_calibrated"] = bool(base.get("z_calibrated", False))
        base["calibrated"] = bool(base["xy_calibrated"] and base["z_calibrated"])
        return base

    def set_tool_calibration(
        self, key: str, *, offset_x=None, offset_y=None, z=None, safe_z=None,
        xy_calibrated=None, z_calibrated=None, calibrated=None
    ) -> Dict[str, Any]:
        if key not in ("knife", "pen"):
            raise ValueError("tool calibration key must be knife or pen")
        if not isinstance(self.tool_calibrations, dict):
            self.tool_calibrations = {}
        cur = self.get_tool_calibration(key)
        if offset_x is not None: cur["offset_x"] = float(offset_x)
        if offset_y is not None: cur["offset_y"] = float(offset_y)
        if z is not None: cur["z"] = float(z)
        if safe_z is not None: cur["safe_z"] = float(safe_z)
        if xy_calibrated is not None: cur["xy_calibrated"] = bool(xy_calibrated)
        if z_calibrated is not None: cur["z_calibrated"] = bool(z_calibrated)
        if calibrated is not None:
            cur["xy_calibrated"] = bool(calibrated)
            cur["z_calibrated"] = bool(calibrated)
        cur["calibrated"] = bool(cur.get("xy_calibrated") and cur.get("z_calibrated"))
        self.tool_calibrations[key] = cur
        return dict(cur)

    def apply_tool_calibration(self, mode: str) -> Dict[str, Any]:
        key = self.tool_key_for_mode(mode)
        cur = self.get_tool_calibration(key)
        self.tool_offset_x = float(cur["offset_x"])
        self.tool_offset_y = float(cur["offset_y"])
        self.work_z = float(cur["z"])
        self.safe_z = float(cur["safe_z"])
        self.calibrated = bool(cur["calibrated"])
        return cur

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
        data=dict(d or {})
        had_z_v2=('z_calibration_version' in data and int(data.get('z_calibration_version') or 0)>=2)
        had_offset_v2=('tool_offset_version' in data and int(data.get('tool_offset_version') or 0)>=2)
        had_tool_calibrations=isinstance(data.get('tool_calibrations'),dict)
        had_service_v2=('service_wait_version' in data and int(data.get('service_wait_version') or 0)>=2)
        had_service_v3=('service_wait_version' in data and int(data.get('service_wait_version') or 0)>=3)
        obj=cls(**data)
        if not had_offset_v2:
            # Up to 0.2.15 the generator added tool_offset to XY, although the
            # UI described it as "tool tip relative to nozzle". Negate legacy
            # values so existing physical nozzle trajectories stay unchanged,
            # then use the physically correct convention from v2 onward.
            obj.tool_offset_x = -float(obj.tool_offset_x)
            obj.tool_offset_y = -float(obj.tool_offset_y)
            obj.tool_offset_version = 2
        if not had_tool_calibrations and obj.calibrated:
            legacy = {
                "offset_x": float(obj.tool_offset_x),
                "offset_y": float(obj.tool_offset_y),
                "z": float(obj.work_z),
                "safe_z": float(obj.safe_z),
                "xy_calibrated": True,
                "z_calibrated": True,
                "calibrated": True,
            }
            obj.tool_calibrations = {"knife": dict(legacy), "pen": dict(legacy)}
        else:
            # Fill missing keys from defaults without discarding future-safe
            # dictionary data that older projects may not contain.
            merged = cls().tool_calibrations
            if isinstance(obj.tool_calibrations, dict):
                for key in ("knife", "pen"):
                    if isinstance(obj.tool_calibrations.get(key), dict):
                        merged[key].update(obj.tool_calibrations[key])
            obj.tool_calibrations = merged
        if not had_z_v2:
            # Previous builds stored work_z as an arbitrary pressed working Z.
            # Drawing now derives pressure from a separately calibrated first-contact Z.
            obj.calibrated=False
            obj.z_calibration_version=2

        # Migrate the old Novatech Cut default profile. Older builds parked at
        # X20/Y240 and executed G28 inside the print job. On A1 this is a poor
        # fit for UMTS because the service/start sequence can occupy the
        # purge/wipe area and delay installation.
        old_default_start = (
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
        defaults=cls()
        if obj.start_template == old_default_start:
            obj.start_template=defaults.start_template
            obj.manual_home_required=True
        if not had_service_v2 or 'M400 U1' in obj.start_template or 'M400 U1' in obj.end_template:
            # Firmware pause M400 U1 ignores our XY park and relocates the toolhead
            # to Bambu's pause/wiper area. Migrate old profiles to an in-place timed hold.
            obj.start_template=defaults.start_template
            obj.end_template=defaults.end_template
            obj.pause_gcode=defaults.pause_gcode
            obj.service_wait_version=3
            if float(getattr(obj,'install_wait_seconds',0) or 0)<=0: obj.install_wait_seconds=10.0
            if float(getattr(obj,'remove_wait_seconds',0) or 0)<=0: obj.remove_wait_seconds=10.0
        if not had_service_v3:
            # 0.2.9 shipped with very long default service holds (300/180 s).
            # Shorten only those legacy defaults; preserve any user-custom value.
            if abs(float(getattr(obj,'install_wait_seconds',0) or 0)-300.0)<1e-9: obj.install_wait_seconds=10.0
            if abs(float(getattr(obj,'remove_wait_seconds',0) or 0)-180.0)<1e-9: obj.remove_wait_seconds=10.0
            obj.service_wait_version=3
        # Rebrand only untouched 0.2.10 default templates. Custom user G-code
        # is preserved exactly as entered.
        old_brand_start_v3 = (
            "; NOVATECH CUT UMTS START V3\n"
            "; IMPORTANT: HOME THE PRINTER MANUALLY WITH UMTS REMOVED BEFORE STARTING THIS JOB\n"
            "; No firmware pause command is used: M400 U1 would move the head to the wiper area.\n"
            "M104 S0\n"
            "M140 S0\n"
            "G90\n"
            "G1 Z{safe_z:.3f} F600\n"
            "; MOVE TO ACCESSIBLE FRONT EDGE FOR UMTS INSTALLATION\n"
            "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
            "M400\n"
            "; INSTALL UMTS NOW - HEAD REMAINS HERE DURING THIS TIMED HOLD\n"
            "M400 S{install_wait_seconds:.0f}\n"
            "G90\n"
            "G1 Z{safe_z:.3f} F600\n"
        )
        old_brand_end_v3 = (
            "G1 Z{safe_z:.3f} F600\n"
            "G1 X{park_x:.3f} Y{park_y:.3f} F6000\n"
            "M400\n"
            "; REMOVE UMTS NOW - HEAD REMAINS HERE DURING THIS TIMED HOLD\n"
            "M400 S{remove_wait_seconds:.0f}\n"
            "; END NOVATECH CUT JOB\n"
        )
        if obj.start_template == old_brand_start_v3: obj.start_template=defaults.start_template
        if obj.end_template == old_brand_end_v3: obj.end_template=defaults.end_template
        if ((abs(obj.park_x-20.0)<1e-9 and abs(obj.park_y-240.0)<1e-9)
                or (abs(obj.park_x-128.0)<1e-9 and abs(obj.park_y-10.0)<1e-9)):
            obj.park_x=230.0
            obj.park_y=10.0
        return obj


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
    drawing_style: str = "Контур + заливка"
    fill_spacing: float = 1.0
    fill_angle: float = 45.0
    fill_crosshatch: bool = False
    fill_inset: float = 0.2
    # Drawing Z is derived from calibrated first-contact Z:
    # work = contact - press_depth, safe = contact + lift_height.
    drawing_press_depth: float = 0.10
    drawing_lift_height: float = 5.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        data=dict(d or {})
        allowed=set(cls.__dataclass_fields__.keys())
        return cls(**{k:v for k,v in data.items() if k in allowed})


DEFAULT_MATERIALS = [
    MaterialProfile("Обычная бумага", passes=1, work_speed=45, blade_offset=0.20, overcut=0.25),
    MaterialProfile("Самоклеящаяся бумага", passes=1, work_speed=35, blade_offset=0.25, overcut=0.35),
    MaterialProfile("Виниловая пленка kiss-cut", passes=1, work_speed=25, blade_offset=0.25, overcut=0.45),
    MaterialProfile("Винил с прорезанием подложки", passes=2, work_speed=20, blade_offset=0.25, overcut=0.60),
    MaterialProfile("Тонкий картон", passes=2, work_speed=18, blade_offset=0.30, overcut=0.65),
    MaterialProfile("Трафаретная пленка", passes=1, work_speed=25, blade_offset=0.25, overcut=0.45),
    MaterialProfile("Рисование ручкой", mode="Рисование", passes=1, work_speed=40, blade_offset=0.0, overcut=0.0, corner_extra=False, drawing_style="Контур + заливка", fill_spacing=0.8, fill_angle=45.0, fill_crosshatch=False, fill_inset=0.15, drawing_press_depth=0.10, drawing_lift_height=5.0),
    MaterialProfile("Рисование маркером", mode="Рисование", passes=1, work_speed=30, blade_offset=0.0, overcut=0.0, corner_extra=False, drawing_style="Контур + заливка", fill_spacing=1.8, fill_angle=45.0, fill_crosshatch=True, fill_inset=0.25, drawing_press_depth=0.05, drawing_lift_height=5.0),
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
