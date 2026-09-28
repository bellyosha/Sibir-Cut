from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
import struct
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import urlparse

SSDP_GROUP = "239.255.255.250"
SSDP_PORTS = (1990, 2021)
BAMBU_NT = "urn:bambulab-com:device:3dprinter:1"

MODEL_NAMES = {
    "N1": "Bambu Lab A1 mini",
    "N2S": "Bambu Lab A1",
    "C11": "Bambu Lab P1P",
    "C12": "Bambu Lab P1S",
    "C13": "Bambu Lab X1E",
    "BL-P001": "Bambu Lab X1 Carbon",
    "BL-P002": "Bambu Lab X1",
    "O1D": "Bambu Lab H2D",
}


@dataclass
class DiscoveredPrinter:
    ip: str
    serial: str = ""
    model_code: str = ""
    model_name: str = ""
    name: str = ""
    signal: str = ""
    firmware: str = ""
    connect_mode: str = ""
    bind_mode: str = ""
    secure_link: str = ""
    source: str = "ssdp"
    last_seen: float = 0.0

    def display_name(self) -> str:
        return self.name or self.model_name or self.model_code or "Bambu Lab"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _headers_from_packet(data: bytes | str) -> tuple[str, dict[str, str]]:
    if isinstance(data, bytes):
        text = data.decode("utf-8", errors="replace")
    else:
        text = str(data)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first = lines[0].strip() if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return first, headers


def _clean_location(value: str, fallback_ip: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback_ip
    if "://" in raw:
        try:
            parsed = urlparse(raw)
            if parsed.hostname:
                return parsed.hostname
        except Exception:
            pass
    candidate = raw.split("/", 1)[0].split(":", 1)[0].strip("[] ")
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except Exception:
        return fallback_ip or candidate


def parse_bambu_ssdp(data: bytes | str, addr: tuple[str, int] | None = None) -> DiscoveredPrinter | None:
    first, h = _headers_from_packet(data)
    nt = h.get("nt", "") or h.get("st", "")
    model = h.get("devmodel.bambu.com", "")
    usn = h.get("usn", "") or h.get("devserial.bambu.com", "")
    location = h.get("location", "")
    sender_ip = addr[0] if addr else ""

    looks_bambu = (
        "bambulab-com:device:3dprinter" in nt.lower()
        or bool(model)
        or any(k.startswith("dev") and k.endswith(".bambu.com") for k in h)
    )
    if not looks_bambu:
        return None

    ip = _clean_location(location, sender_ip)
    if not ip:
        return None
    serial = usn.strip()
    if serial.lower().startswith("uuid:"):
        serial = serial[5:].strip()
    model_name = MODEL_NAMES.get(model, model)
    return DiscoveredPrinter(
        ip=ip,
        serial=serial,
        model_code=model,
        model_name=model_name,
        name=h.get("devname.bambu.com", ""),
        signal=h.get("devsignal.bambu.com", ""),
        firmware=h.get("devversion.bambu.com", ""),
        connect_mode=h.get("devconnect.bambu.com", ""),
        bind_mode=h.get("devbind.bambu.com", ""),
        secure_link=h.get("devseclink.bambu.com", ""),
        source="ssdp",
        last_seen=time.time(),
    )


def _local_ipv4_addresses() -> list[str]:
    found: set[str] = set()
    try:
        host = socket.gethostname()
        for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                found.add(ip)
    except Exception:
        pass
    # Route lookup without sending application data; useful on Windows when
    # gethostname only returns a virtual/VPN adapter.
    for target in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                found.add(ip)
        except Exception:
            try:
                s.close()
            except Exception:
                pass
    return sorted(found)


def _candidate_subnets(local_ips: list[str] | None = None) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()
    for ip in local_ips or _local_ipv4_addresses():
        try:
            addr = ipaddress.ip_address(ip)
            if not isinstance(addr, ipaddress.IPv4Address) or addr.is_loopback or addr.is_link_local:
                continue
            # Most home/shop LANs use /24. This is deliberately bounded:
            # no wide enterprise/VPN scans.
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
            key = str(net)
            if key not in seen:
                seen.add(key)
                nets.append(net)
        except Exception:
            continue
    return nets[:6]


def _tcp_open(ip: str, port: int = 8883, timeout: float = 0.16) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except Exception:
        return False


class BambuLanScanner:
    """Discover Bambu printers via SSDP and bounded MQTT-port subnet probing."""

    def __init__(
        self,
        on_printer: Callable[[DiscoveredPrinter], None] | None = None,
        on_done: Callable[[list[DiscoveredPrinter]], None] | None = None,
    ) -> None:
        self.on_printer = on_printer
        self.on_done = on_done
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._found: dict[str, DiscoveredPrinter] = {}

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> list[DiscoveredPrinter]:
        with self._lock:
            return sorted(
                (DiscoveredPrinter(**p.to_dict()) for p in self._found.values()),
                key=lambda p: (p.model_name or p.model_code, p.name, p.ip),
            )

    @staticmethod
    def _key(p: DiscoveredPrinter) -> str:
        return p.serial or p.ip

    def _emit(self, p: DiscoveredPrinter) -> None:
        key = self._key(p)
        with self._lock:
            # A rich SSDP record always wins over a bare TCP:8883 candidate.
            if p.source == "tcp" and any(other.ip == p.ip and other.source == "ssdp" for other in self._found.values()):
                return
            old = self._found.get(key)
            if old is not None:
                # Prefer rich SSDP metadata over a bare port-scan candidate.
                if p.source == "tcp" and old.source == "ssdp":
                    return
                if not p.serial:
                    p.serial = old.serial
                if not p.model_code:
                    p.model_code = old.model_code
                if not p.model_name:
                    p.model_name = old.model_name
                if not p.name:
                    p.name = old.name
                if not p.signal:
                    p.signal = old.signal
                if not p.firmware:
                    p.firmware = old.firmware
            self._found[key] = p
            # If SSDP arrived after a TCP candidate for the same IP, remove duplicate.
            if p.serial:
                for k, other in list(self._found.items()):
                    if k != key and other.ip == p.ip and other.source == "tcp":
                        self._found.pop(k, None)
        if self.on_printer:
            try:
                self.on_printer(p)
            except Exception:
                pass

    @staticmethod
    def _make_listener(port: int) -> socket.socket | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
            except OSError:
                s.bind((SSDP_GROUP, port))
            try:
                mreq = struct.pack("=4s4s", socket.inet_aton(SSDP_GROUP), socket.inet_aton("0.0.0.0"))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except Exception:
                pass
            s.settimeout(0.18)
            return s
        except Exception:
            return None

    @staticmethod
    def _send_search() -> None:
        payloads = []
        for port in SSDP_PORTS:
            payloads.append(
                (
                    (
                        "M-SEARCH * HTTP/1.1\r\n"
                        f"HOST: {SSDP_GROUP}:{port}\r\n"
                        'MAN: "ssdp:discover"\r\n'
                        "MX: 1\r\n"
                        f"ST: {BAMBU_NT}\r\n\r\n"
                    ).encode("ascii"),
                    (SSDP_GROUP, port),
                )
            )
        for local_ip in _local_ipv4_addresses() or ["0.0.0.0"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                try:
                    if local_ip != "0.0.0.0":
                        s.bind((local_ip, 0))
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
                except Exception:
                    pass
                for data, dest in payloads:
                    try:
                        s.sendto(data, dest)
                    except Exception:
                        pass
                s.close()
            except Exception:
                pass

    def _listen_ssdp(self, duration: float) -> None:
        sockets = [s for s in (self._make_listener(p) for p in SSDP_PORTS) if s is not None]
        self._send_search()
        deadline = time.monotonic() + max(1.0, duration)
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                for s in sockets:
                    try:
                        data, addr = s.recvfrom(8192)
                    except socket.timeout:
                        continue
                    except Exception:
                        continue
                    p = parse_bambu_ssdp(data, addr)
                    if p is not None:
                        self._emit(p)
        finally:
            for s in sockets:
                try:
                    s.close()
                except Exception:
                    pass

    def _scan_mqtt_candidates(self, duration: float) -> None:
        nets = _candidate_subnets()
        if not nets or self._stop.is_set():
            return
        own = set(_local_ipv4_addresses())
        hosts: list[str] = []
        for net in nets:
            for addr in net.hosts():
                ip = str(addr)
                if ip not in own:
                    hosts.append(ip)
        # Keep scan bounded even on machines with many adapters/VPNs.
        hosts = hosts[:1524]
        deadline = time.monotonic() + max(1.0, duration)
        with concurrent.futures.ThreadPoolExecutor(max_workers=72) as pool:
            futures = {pool.submit(_tcp_open, ip): ip for ip in hosts}
            for future in concurrent.futures.as_completed(futures):
                if self._stop.is_set() or time.monotonic() > deadline:
                    break
                ip = futures[future]
                try:
                    opened = bool(future.result())
                except Exception:
                    opened = False
                if not opened:
                    continue
                with self._lock:
                    if any(p.ip == ip for p in self._found.values()):
                        continue
                self._emit(
                    DiscoveredPrinter(
                        ip=ip,
                        model_name="Bambu / MQTT 8883",
                        name="Кандидат Bambu",
                        source="tcp",
                        last_seen=time.time(),
                    )
                )

    def scan(self, duration: float = 5.5) -> list[DiscoveredPrinter]:
        self._stop.clear()
        self._found.clear()
        threads = [
            threading.Thread(target=self._listen_ssdp, args=(duration,), daemon=True),
            threading.Thread(target=self._scan_mqtt_candidates, args=(min(duration, 3.5),), daemon=True),
        ]
        for t in threads:
            t.start()
        deadline = time.monotonic() + max(1.0, duration) + 0.5
        for t in threads:
            remaining = max(0.0, deadline - time.monotonic())
            t.join(remaining)
        result = self.snapshot()
        if self.on_done:
            try:
                self.on_done(result)
            except Exception:
                pass
        return result


def discovery_self_test() -> None:
    packet = (
        "NOTIFY * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1990\r\n"
        "Server: UPnP/1.0\r\n"
        "Location: 192.168.1.42\r\n"
        f"NT: {BAMBU_NT}\r\n"
        "USN: 03919A123456789\r\n"
        "DevModel.bambu.com: N2S\r\n"
        "DevName.bambu.com: A1 Workshop\r\n"
        "DevSignal.bambu.com: -48\r\n"
        "DevConnect.bambu.com: lan\r\n"
        "DevVersion.bambu.com: 01.05.00.00\r\n\r\n"
    )
    p = parse_bambu_ssdp(packet, ("192.168.1.42", 2021))
    if p is None:
        raise RuntimeError("Bambu SSDP parser returned no printer")
    if p.ip != "192.168.1.42" or p.serial != "03919A123456789":
        raise RuntimeError("Bambu SSDP identity parsing failed")
    if p.model_name != "Bambu Lab A1" or p.name != "A1 Workshop":
        raise RuntimeError("Bambu SSDP model/name parsing failed")
    if parse_bambu_ssdp("NOTIFY * HTTP/1.1\r\nNT: something-else\r\n\r\n") is not None:
        raise RuntimeError("Non-Bambu SSDP packet was accepted")
