from __future__ import annotations

import copy
import errno
import json
import os
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable
from .discovery import clean_printer_serial

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None


class BambuLanError(RuntimeError):
    pass


def _network_error_kind(exc: Exception) -> str:
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if isinstance(exc, ConnectionRefusedError) or code in (10061, errno.ECONNREFUSED):
        return "refused"
    if isinstance(exc, (TimeoutError, socket.timeout)) or code in (10060, errno.ETIMEDOUT):
        return "timeout"
    if isinstance(exc, socket.gaierror):
        return "address"
    if isinstance(exc, ssl.SSLError):
        return "tls"
    return "network"


def connection_error_text(host: str, exc: Exception) -> str:
    kind = _network_error_kind(exc)
    if kind == "refused":
        return (f"Принтер по адресу {host} отклонил подключение к порту 8883 (WinError 10061 / connection refused).\n\n"
                "Пароль и Serial ещё не проверялись. Сверьте IP с экраном принтера, включите LAN Only и Developer Mode, если он есть в прошивке, затем повторите подключение.\n"
                "ПК и принтер должны быть в одной локальной сети; гостевая Wi-Fi сеть и изоляция устройств могут мешать. Используйте «Проверить LAN», чтобы проверить порты 8883 и 990.")
    if kind == "timeout":
        return (f"Нет ответа от {host}:8883: истекло время ожидания.\n\n"
                "Проверьте актуальный IP, питание/Wi-Fi принтера, одну локальную сеть, гостевую изоляцию, маршрут VPN и разрешение Sibir Cut в брандмауэре Windows. Используйте «Проверить LAN».")
    if kind == "address":
        return f"Не удалось найти адрес «{host}». Введите IP с экрана принтера без http:// и без номера порта."
    if kind == "tls":
        return (f"Порт {host}:8883 доступен, но защищённое MQTT-соединение не установлено.\n\n"
                "Проверьте LAN Only / Developer Mode и перезапустите принтер. Sibir Cut использует TLS на порту 8883; менять его на 1883 не нужно.")
    return f"Не удалось подключиться к {host}:8883. Проверьте IP и LAN/Developer Mode.\nТехническая причина: {exc}"


def check_lan_services(host: str, timeout: float = 2.0) -> str:
    host = str(host or "").strip()
    if not host:
        raise BambuLanError("Введите IP принтера для проверки LAN.")
    lines = [f"Проверка адреса: {host}"]
    labels = {"refused": "соединение отклонено", "timeout": "нет ответа", "address": "адрес не найден", "network": "сетевая ошибка", "tls": "ошибка TLS"}
    for name, port in (("MQTT", 8883), ("FTPS", 990)):
        try:
            with socket.create_connection((host, port), timeout=max(0.1, min(float(timeout), 5.0))):
                lines.append(f"{name}, порт {port}: TCP доступен")
        except Exception as exc:
            lines.append(f"{name}, порт {port}: {labels[_network_error_kind(exc)]}")
    lines.extend(["", "Это проверка сети. Access code, Serial и разрешение команд она не проверяет.",
                  "Сверьте IP с экраном принтера. Для стороннего управления включите LAN Only / Developer Mode, если он предусмотрен прошивкой. Проверьте одну локальную сеть, гостевую изоляцию, VPN и брандмауэр Windows."])
    return "\n".join(lines)


def _merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge_dict(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def _next_sequence(value: int) -> tuple[int, str]:
    value = (int(value) + 1) % 2_000_000_000
    return value, str(value)


def _hex_flag(value: Any, bit: int) -> bool:
    try:
        raw = str(value or "0").strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
        return bool((int(raw or "0", 16) >> int(bit)) & 1)
    except Exception:
        return False


def build_gcode_request(sequence_id: str, gcode: str) -> dict[str, Any]:
    gcode = str(gcode or "").strip()
    if not gcode:
        raise BambuLanError("Пустая команда G-code")
    return {
        "print": {
            "sequence_id": str(sequence_id),
            "command": "gcode_line",
            "param": gcode,
        }
    }


def build_pushall_request(sequence_id: str) -> dict[str, Any]:
    return {"pushing": {"sequence_id": str(sequence_id), "command": "pushall"}}


def build_home_request(sequence_id: str) -> dict[str, Any]:
    # Same MQTT command used by current OrcaSlicer when fun bit 32 is set.
    return {
        "print": {
            "sequence_id": str(sequence_id),
            "command": "back_to_center",
        }
    }


def build_xyz_ctrl_request(sequence_id: str, axis: str, direction: int, mode: int) -> dict[str, Any]:
    axis = str(axis or "").upper()
    if axis not in ("X", "Y", "Z"):
        raise BambuLanError(f"Неподдерживаемая ось: {axis}")
    return {
        "print": {
            "sequence_id": str(sequence_id),
            "command": "xyz_ctrl",
            "axis": axis,
            "dir": 1 if int(direction) >= 0 else -1,
            "mode": 1 if int(mode) else 0,
        }
    }


def _config_file() -> Path:
    base = os.getenv("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".sibir-cut"
    return root / "SibirCut" / "lan.json"


def load_lan_config() -> dict[str, Any]:
    p = _config_file()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_lan_config(data: dict[str, Any]) -> None:
    p = _config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class BambuLanClient:
    """Local Bambu MQTT client with Orca-compatible homing/axis control."""

    def __init__(
        self,
        host: str,
        access_code: str,
        serial: str = "",
        on_update: Callable[[], None] | None = None,
    ) -> None:
        if mqtt is None:
            raise BambuLanError("Не установлен пакет paho-mqtt")
        self.host = str(host or "").strip()
        self.access_code = str(access_code or "").strip()
        self.serial = clean_printer_serial(serial)
        if not self.host:
            raise BambuLanError("Укажите IP-адрес принтера")
        if not self.access_code:
            raise BambuLanError("Укажите LAN access code")
        if str(serial or "").strip() and not self.serial:
            raise BambuLanError("Serial должен быть серийным номером принтера с экрана, без UUID/URN и пробелов. Можно оставить его пустым для автоопределения.")

        self.report_topic = f"device/{self.serial}/report" if self.serial else "device/+/report"
        self.request_topic = f"device/{self.serial}/request" if self.serial else ""
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        self._connected = False
        self._verified = False
        self._closing = False
        self._last_error = ""
        self._last_report_monotonic = 0.0
        self._seq = int(time.time() * 1000) % 1_000_000_000
        self._connect_event = threading.Event()
        self._report_event = threading.Event()
        self._on_update = on_update
        self._position = {"x": None, "y": None, "z": None, "source": "unknown"}

        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"sibir-cut-{os.getpid()}-{self._seq}",
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            self._client = mqtt.Client(
                client_id=f"sibir-cut-{os.getpid()}-{self._seq}",
                protocol=mqtt.MQTTv311,
            )
        self._client.username_pw_set("bblp", self.access_code)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.tls_insecure_set(True)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message
        self._client.on_subscribe = self._handle_subscribe

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._connected and self._verified)

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def connect(self, timeout: float = 6.0) -> None:
        timeout = max(1.0, min(float(timeout), 30.0))
        auto_serial = not self.serial
        self._closing = False
        self._connect_event.clear()
        self._report_event.clear()
        deadline = time.monotonic() + timeout
        try:
            self._client.connect_timeout = timeout
            self._client.connect(self.host, 8883, keepalive=30)
            self._client.loop_start()
        except Exception as exc:
            self.close()
            raise BambuLanError(connection_error_text(self.host, exc)) from exc
        if not self._connect_event.wait(max(0.0, deadline-time.monotonic())):
            self.close()
            raise BambuLanError(
                "Принтер не подтвердил MQTT-подключение. Проверьте IP, LAN access code, "
                "серийный номер, LAN Only/Developer Mode и нахождение ПК в одной сети."
            )
        if not self._connected:
            err = self.last_error or "MQTT-подключение отклонено"
            self.close()
            raise BambuLanError(err)
        if self.serial:
            try:
                self.request_status()
            except Exception:
                self.close()
                raise
        received = self._report_event.wait(max(8.0, timeout))
        if not received or not self.connected:
            err = self.last_error
            if not err:
                err = ("MQTT-соединение установлено, но Serial не получен из статуса. Введите серийный номер принтера с его экрана вручную (не номер AMS), затем повторите подключение."
                       if auto_serial else f"MQTT-соединение установлено, но нет статуса для Serial {self.serial}. Сверьте SN с экраном принтера (не AMS) и проверьте LAN/Developer Mode. Профиль не активирован.")
            self.close()
            raise BambuLanError(err)
        if auto_serial:
            try:
                self._client.subscribe(self.report_topic, qos=0)
                self._client.unsubscribe("device/+/report")
                self.request_status()
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        self._closing = True
        try:
            self._client.disconnect()
        except Exception:
            pass
        try:
            self._client.loop_stop()
        except Exception:
            pass
        with self._lock:
            self._connected = False
            self._verified = False

    def _notify(self) -> None:
        cb = self._on_update
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _handle_connect(self, client, userdata, flags, reason_code, *extra) -> None:
        try:
            rc = int(reason_code)
        except Exception:
            try:
                rc = int(getattr(reason_code, "value", 1))
            except Exception:
                rc = 1
        with self._lock:
            self._connected = rc == 0
            self._verified = False
            self._report_event.clear()
            self._state.clear()
            self._position = {"x": None, "y": None, "z": None, "source": "unknown"}
            self._last_report_monotonic = 0.0
            self._last_error = ("" if rc == 0 else
                "Принтер отклонил LAN access code. Скопируйте код с экрана принтера; пароль Wi-Fi и пароль Bambu-аккаунта не подходят."
                if rc in (4, 5, 134, 135) else f"MQTT отклонил подключение (код {rc}). Проверьте LAN/Developer Mode и данные принтера.")
        if rc == 0:
            try:
                result = client.subscribe(self.report_topic, qos=0)
                if result[0] != 0:
                    raise BambuLanError("Не удалось подписаться на MQTT-статус принтера.")
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._connected = False
        self._connect_event.set()
        self._notify()

    def _handle_disconnect(self, client, userdata, *args) -> None:
        with self._lock:
            self._connected = False
            self._verified = False
            if not self._closing and not self._last_error:
                self._last_error = "MQTT-соединение разорвано принтером. Проверьте LAN/Developer Mode и повторите подключение."
        self._connect_event.set()
        self._report_event.set()
        self._notify()

    def _handle_subscribe(self, client, userdata, mid, reason_codes, *extra) -> None:
        codes = [getattr(value, "value", value) for value in reason_codes]
        if any(int(value) >= 128 for value in codes):
            with self._lock:
                self._last_error = ("Принтер не разрешил подписку для автоопределения Serial. Введите SN с экрана принтера вручную."
                                    if not self.serial else "Принтер отклонил подписку на статус. Проверьте Serial и LAN/Developer Mode.")
                self._connected = False
                self._verified = False
            self._connect_event.set()
            self._report_event.set()
            self._notify()

    @staticmethod
    def _extract_report_position(print_state: dict[str, Any]) -> dict[str, float] | None:
        # Some firmware/network layers may expose position fields even though
        # they are absent from the public push_status schema. Accept only an
        # unambiguous XYZ triplet.
        candidates = [print_state.get("position"), print_state.get("pos"), print_state.get("xyz")]
        candidates.append(print_state)
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            vals = {}
            for a in ("x", "y", "z"):
                v = obj.get(a)
                if isinstance(v, (int, float)):
                    vals[a] = float(v)
                elif isinstance(v, str):
                    try:
                        vals[a] = float(v)
                    except Exception:
                        pass
            if len(vals) == 3:
                return vals
        return None

    def _handle_message(self, client, userdata, message) -> None:
        match = re.fullmatch(r"device/([A-Za-z0-9_-]+)/report", str(getattr(message, "topic", "")))
        if not match:
            return
        try:
            data = json.loads(message.payload.decode("utf-8", errors="replace"))
            if not isinstance(data, dict) or not isinstance(data.get("print"), dict) or not data["print"]:
                return
        except Exception:
            return
        with self._lock:
            incoming_serial = clean_printer_serial(match.group(1))
            if not incoming_serial or (self.serial and incoming_serial != self.serial):
                return
            if not self.serial:
                self.serial = incoming_serial
                self.report_topic = f"device/{self.serial}/report"
                self.request_topic = f"device/{self.serial}/request"
            _merge_dict(self._state, data)
            self._verified = True
            self._last_report_monotonic = time.monotonic()
            p = data.get("print") if isinstance(data.get("print"), dict) else {}
            reported = self._extract_report_position(p)
            if reported:
                self._position.update(reported)
                self._position["source"] = "printer"
        self._report_event.set()
        self._notify()

    def _publish(self, payload: dict[str, Any], *, require_report: bool = True) -> None:
        if not self._connected or (require_report and not self.connected):
            raise BambuLanError("Нет подключения к принтеру")
        if not self.serial or not self.request_topic:
            raise BambuLanError("Serial ещё не подтверждён. Управление принтером недоступно.")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            info = self._client.publish(self.request_topic, raw, qos=0)
            rc = getattr(info, "rc", 0)
            success = getattr(mqtt, "MQTT_ERR_SUCCESS", 0)
            if rc != success:
                raise BambuLanError(f"MQTT publish вернул код {rc}")
        except BambuLanError:
            raise
        except Exception as exc:
            raise BambuLanError(f"Не удалось отправить команду: {exc}") from exc

    def _sequence(self) -> str:
        with self._lock:
            self._seq, seq = _next_sequence(self._seq)
            return seq

    def request_status(self) -> None:
        self._publish(build_pushall_request(self._sequence()), require_report=False)

    def send_gcode(self, gcode: str) -> None:
        self._publish(build_gcode_request(self._sequence(), gcode))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def position_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._position)

    def set_known_position(self, x=None, y=None, z=None, source: str = "command") -> None:
        with self._lock:
            if x is not None:
                self._position["x"] = float(x)
            if y is not None:
                self._position["y"] = float(y)
            if z is not None:
                self._position["z"] = float(z)
            self._position["source"] = str(source)

    def invalidate_position(self) -> None:
        with self._lock:
            self._position = {"x": None, "y": None, "z": None, "source": "unknown"}

    def status_summary(self) -> dict[str, Any]:
        snap = self.snapshot()
        p = snap.get("print") if isinstance(snap.get("print"), dict) else {}
        fun = p.get("fun")
        with self._lock:
            age = None if not self._last_report_monotonic else max(0.0, time.monotonic() - self._last_report_monotonic)
        return {
            "connected": self.connected,
            "gcode_state": str(p.get("gcode_state") or "—"),
            "nozzle_temp": p.get("nozzle_temper"),
            "nozzle_target": p.get("nozzle_target_temper"),
            "bed_temp": p.get("bed_temper"),
            "bed_target": p.get("bed_target_temper"),
            "wifi_signal": p.get("wifi_signal"),
            "home_flag": p.get("home_flag"),
            "fun": fun,
            "supports_mqtt_homing": _hex_flag(fun, 32),
            "supports_mqtt_axis_ctrl": _hex_flag(fun, 38),
            "report_age": age,
        }

    def go_home(self, printing: bool = False) -> str:
        st = self.status_summary()
        self.invalidate_position()
        if st.get("supports_mqtt_homing"):
            self._publish(build_home_request(self._sequence()))
            return "back_to_center"
        # Orca fallback: only X while printing; full G28 while idle.
        self.send_gcode("G28 X" if printing else "G28")
        return "G28 X" if printing else "G28"

    def jog_axis_orca(self, axis: str, input_val: float, speed: int = 3000, core_xy: bool = False) -> str:
        """Use the same control strategy as OrcaSlicer.

        Native xyz_ctrl supports Orca's 1/10 mm style jogs. Fine sub-mm moves
        use Orca's protected relative-G-code fallback with higher precision.
        """
        axis = str(axis or "").upper()
        if axis not in ("X", "Y", "Z"):
            raise BambuLanError(f"Неподдерживаемая ось: {axis}")
        value = float(input_val)
        st = self.status_summary()

        # Current Orca uses mqtt xyz_ctrl when supported. Its protocol exposes
        # two movement modes (small / 10 mm), so keep sub-mm calibration on G-code.
        use_native = st.get("supports_mqtt_axis_ctrl") and abs(value) in (1.0, 10.0)
        if use_native:
            direction = 1 if value > 0 else -1
            if not core_xy and axis in ("Y", "Z"):
                direction = -direction
            mode = 1 if abs(value) >= 10.0 else 0
            self._publish(build_xyz_ctrl_request(self._sequence(), axis, direction, mode))
            method = "xyz_ctrl"
        else:
            physical_value = value
            if not core_xy and axis in ("Y", "Z"):
                physical_value = -physical_value
            gcode = (
                "M211 S\n"
                "M211 X1 Y1 Z1\n"
                "M1002 push_ref_mode\n"
                "G91\n"
                f"G1 {axis}{physical_value:.3f} F{int(speed)}\n"
                "M1002 pop_ref_mode\n"
                "M211 R"
            )
            self.send_gcode(gcode)
            method = "orca_gcode"

        with self._lock:
            key = axis.lower()
            cur = self._position.get(key)
            if isinstance(cur, (int, float)):
                # UI coordinate follows requested logical movement direction.
                self._position[key] = float(cur) + value
                self._position["source"] = "tracked"
        return method

    def move_absolute(self, x=None, y=None, z=None, feed: int = 1200) -> None:
        words = []
        if x is not None:
            words.append(f"X{float(x):.3f}")
        if y is not None:
            words.append(f"Y{float(y):.3f}")
        if z is not None:
            words.append(f"Z{float(z):.3f}")
        if not words:
            return
        self.send_gcode("G90\nG1 " + " ".join(words) + f" F{int(feed)}\nM400")
        self.set_known_position(x=x, y=y, z=z, source="command")


def lan_self_test() -> None:
    dst = {"print": {"gcode_state": "IDLE", "nozzle_temper": 25.0}}
    _merge_dict(dst, {"print": {"bed_temper": 24.0}})
    if dst["print"].get("gcode_state") != "IDLE" or dst["print"].get("bed_temper") != 24.0:
        raise RuntimeError("LAN partial report merge failed")

    req = build_gcode_request("42", "G90\nG1 Z5 F600")
    if req.get("print", {}).get("command") != "gcode_line" or "G1 Z5" not in req["print"].get("param", ""):
        raise RuntimeError("LAN gcode_line payload failed")

    push = build_pushall_request("43")
    if push.get("pushing", {}).get("command") != "pushall":
        raise RuntimeError("LAN pushall payload failed")

    home = build_home_request("44")
    if home.get("print", {}).get("command") != "back_to_center":
        raise RuntimeError("LAN back_to_center payload failed")

    axis = build_xyz_ctrl_request("45", "Z", -1, 1)
    if axis.get("print", {}).get("command") != "xyz_ctrl" or axis["print"].get("axis") != "Z":
        raise RuntimeError("LAN xyz_ctrl payload failed")

    if not _hex_flag(hex((1 << 32) | (1 << 38)), 32) or not _hex_flag(hex((1 << 32) | (1 << 38)), 38):
        raise RuntimeError("LAN Orca fun-bit parser failed")
