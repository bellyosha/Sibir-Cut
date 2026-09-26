from __future__ import annotations

import copy
import json
import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover - surfaced as a clear runtime error in GUI
    mqtt = None


class BambuLanError(RuntimeError):
    pass


def _merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Merge partial MQTT reports without dropping fields from prior reports."""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge_dict(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


def _next_sequence(value: int) -> tuple[int, str]:
    value = (int(value) + 1) % 2_000_000_000
    return value, str(value)


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
    return {
        "pushing": {
            "sequence_id": str(sequence_id),
            "command": "pushall",
        }
    }


def _config_file() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".sibir-cut"
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
    """Small local-only Bambu MQTT client for status + explicit G-code commands."""

    def __init__(
        self,
        host: str,
        access_code: str,
        serial: str,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        if mqtt is None:
            raise BambuLanError("Не установлен пакет paho-mqtt")
        self.host = str(host or "").strip()
        self.access_code = str(access_code or "").strip()
        self.serial = str(serial or "").strip()
        if not self.host:
            raise BambuLanError("Укажите IP-адрес принтера")
        if not self.access_code:
            raise BambuLanError("Укажите LAN access code")
        if not self.serial:
            raise BambuLanError("Укажите серийный номер принтера")

        self.report_topic = f"device/{self.serial}/report"
        self.request_topic = f"device/{self.serial}/request"
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        self._connected = False
        self._last_error = ""
        self._last_report_monotonic = 0.0
        self._seq = int(time.time() * 1000) % 1_000_000_000
        self._connect_event = threading.Event()
        self._on_update = on_update

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

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._connected)

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def connect(self, timeout: float = 6.0) -> None:
        self._connect_event.clear()
        try:
            self._client.connect(self.host, 8883, keepalive=30)
            self._client.loop_start()
        except Exception as exc:
            raise BambuLanError(f"Не удалось подключиться к {self.host}:8883: {exc}") from exc
        if not self._connect_event.wait(max(1.0, float(timeout))):
            self.close()
            raise BambuLanError(
                "Принтер не подтвердил MQTT-подключение. Проверьте IP, LAN access code, "
                "серийный номер, LAN Only/Developer Mode и нахождение ПК в одной сети."
            )
        if not self.connected:
            err = self.last_error or "MQTT-подключение отклонено"
            self.close()
            raise BambuLanError(err)
        self.request_status()

    def close(self) -> None:
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
            self._last_error = "" if rc == 0 else f"MQTT вернул код подключения {rc}"
        if rc == 0:
            try:
                client.subscribe(self.report_topic, qos=0)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._connected = False
        self._connect_event.set()
        self._notify()

    def _handle_disconnect(self, client, userdata, *args) -> None:
        with self._lock:
            self._connected = False
        self._notify()

    def _handle_message(self, client, userdata, message) -> None:
        try:
            data = json.loads(message.payload.decode("utf-8", errors="replace"))
            if not isinstance(data, dict):
                return
        except Exception:
            return
        with self._lock:
            _merge_dict(self._state, data)
            self._last_report_monotonic = time.monotonic()
        self._notify()

    def _publish(self, payload: dict[str, Any]) -> None:
        if not self.connected:
            raise BambuLanError("Нет подключения к принтеру")
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
        self._publish(build_pushall_request(self._sequence()))

    def send_gcode(self, gcode: str) -> None:
        self._publish(build_gcode_request(self._sequence(), gcode))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def status_summary(self) -> dict[str, Any]:
        snap = self.snapshot()
        p = snap.get("print") if isinstance(snap.get("print"), dict) else {}
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
            "report_age": age,
        }


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
