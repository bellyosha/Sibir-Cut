from __future__ import annotations

import ipaddress
import re
import select
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Callable, Iterable
from urllib.parse import urlparse

SSDP_GROUP = "239.255.255.250"
SSDP_PORT = 2021
SSDP_ALT_PORT = 1990
BAMBU_ST = "urn:bambulab-com:device:3dprinter:1"
MQTT_PORT = 8883


@dataclass
class DiscoveredBambu:
    ip: str
    serial: str = ""
    name: str = ""
    model: str = ""
    version: str = ""
    source: str = "SSDP"

    def key(self) -> str:
        return (self.serial or self.ip).strip().upper()

    def to_dict(self) -> dict:
        return asdict(self)


def _headers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.replace("\r\n", "\n").split("\n")[1:]:
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _location_ip(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        ipaddress.ip_address(value)
        return value
    except Exception:
        pass
    try:
        u = urlparse(value if "://" in value else "//" + value)
        host = u.hostname or ""
        ipaddress.ip_address(host)
        return host
    except Exception:
        return ""


def parse_ssdp_packet(data: bytes | str, source_ip: str = "") -> DiscoveredBambu | None:
    try:
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
    except Exception:
        return None
    first = text.replace("\r\n", "\n").split("\n", 1)[0].strip().upper()
    if not (first.startswith("NOTIFY ") or first.startswith("HTTP/1.1 200") or first.startswith("M-SEARCH ")):
        return None
    h = _headers(text)
    nt = (h.get("nt") or h.get("st") or "").lower()
    has_bambu_headers = any(k.endswith(".bambu.com") for k in h)
    if "bambulab-com:device:3dprinter" not in nt and not has_bambu_headers:
        return None

    ip = _location_ip(h.get("location", "")) or source_ip
    try:
        ipaddress.ip_address(ip)
    except Exception:
        return None

    serial = (h.get("usn") or h.get("devsn.bambu.com") or "").strip()
    # Some SSDP stacks prefix USN with uuid: or append ::service.
    if serial.lower().startswith("uuid:"):
        serial = serial[5:]
    if "::" in serial:
        serial = serial.split("::", 1)[0]
    name = (h.get("devname.bambu.com") or h.get("devname") or "").strip()
    model = (h.get("devmodel.bambu.com") or h.get("devmodel") or "").strip()
    version = (h.get("devversion.bambu.com") or h.get("devversion") or "").strip()
    return DiscoveredBambu(ip=ip, serial=serial, name=name, model=model, version=version, source="SSDP")


def _msearch(port: int) -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_GROUP}:{port}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {BAMBU_ST}\r\n\r\n"
    ).encode("ascii")


def _make_listener(port: int) -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        s.bind(("", port))
        try:
            mreq = socket.inet_aton(SSDP_GROUP) + socket.inet_aton("0.0.0.0")
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception:
            pass
        s.setblocking(False)
        return s
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        return None


def _make_probe_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", 0))
    s.setblocking(False)
    return s


def _emit(
    found: dict[str, DiscoveredBambu],
    item: DiscoveredBambu,
    on_found: Callable[[DiscoveredBambu], None] | None,
) -> None:
    key = item.key()
    previous = found.get(key)
    if previous:
        # SSDP data wins over a bare MQTT-port candidate.
        if not previous.serial and item.serial:
            previous.serial = item.serial
        if item.name:
            previous.name = item.name
        if item.model:
            previous.model = item.model
        if item.version:
            previous.version = item.version
        if item.source == "SSDP":
            previous.source = "SSDP"
        item = previous
    else:
        # If the same IP was already seen without a serial, replace that entry.
        old_key = next((k for k, v in found.items() if v.ip == item.ip and k != key), None)
        if old_key:
            old = found.pop(old_key)
            item.name = item.name or old.name
            item.model = item.model or old.model
            item.version = item.version or old.version
        found[item.key()] = item
    if on_found:
        try:
            on_found(item)
        except Exception:
            pass


def discover_ssdp(
    timeout: float = 6.0,
    on_found: Callable[[DiscoveredBambu], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[DiscoveredBambu]:
    """Listen for Bambu NOTIFY and send active M-SEARCH probes.

    Current Bambu discovery is observed on UDP 2021; 1990 is also listened/probed
    for compatibility with older firmware and community implementations.
    """
    found: dict[str, DiscoveredBambu] = {}
    listeners = [x for x in (_make_listener(SSDP_PORT), _make_listener(SSDP_ALT_PORT)) if x is not None]
    probe = _make_probe_socket()
    sockets = listeners + [probe]
    deadline = time.monotonic() + max(1.0, float(timeout))
    next_probe = 0.0
    try:
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            now = time.monotonic()
            if now >= next_probe:
                for port in (SSDP_PORT, SSDP_ALT_PORT):
                    packet = _msearch(port)
                    for addr in (SSDP_GROUP, "255.255.255.255"):
                        try:
                            probe.sendto(packet, (addr, port))
                        except Exception:
                            pass
                next_probe = now + 1.5

            try:
                ready, _, _ = select.select(sockets, [], [], 0.25)
            except Exception:
                ready = []
            for s in ready:
                try:
                    data, addr = s.recvfrom(8192)
                except Exception:
                    continue
                item = parse_ssdp_packet(data, addr[0] if addr else "")
                if item:
                    _emit(found, item, on_found)
    finally:
        for s in sockets:
            try:
                s.close()
            except Exception:
                pass
    return list(found.values())


def _local_ipv4s() -> list[str]:
    ips: set[str] = set()
    # Default-route address is the best starting point.
    for remote in (("8.8.8.8", 80), ("1.1.1.1", 80)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(remote)
            ips.add(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            ips.add(info[4][0])
    except Exception:
        pass
    out = []
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip)
            if a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified:
                continue
            out.append(str(a))
        except Exception:
            pass
    return sorted(set(out))


def candidate_subnets() -> list[ipaddress.IPv4Network]:
    nets: set[ipaddress.IPv4Network] = set()
    for ip in _local_ipv4s():
        try:
            # /24 fallback is intentional: fast enough for a desktop scan and
            # matches the simple shop LAN used by 3D Ceh.
            nets.add(ipaddress.ip_network(f"{ip}/24", strict=False))
        except Exception:
            pass
    return sorted(nets, key=str)


def _mqtt_port_open(ip: str, timeout: float = 0.16) -> bool:
    try:
        with socket.create_connection((ip, MQTT_PORT), timeout=timeout):
            return True
    except Exception:
        return False


def discover_mqtt_candidates(
    known_ips: Iterable[str] = (),
    on_found: Callable[[DiscoveredBambu], None] | None = None,
    stop_event: threading.Event | None = None,
    workers: int = 48,
) -> list[DiscoveredBambu]:
    known = set(str(x) for x in known_ips)
    targets: list[str] = []
    local = set(_local_ipv4s())
    for net in candidate_subnets():
        for host in net.hosts():
            ip = str(host)
            if ip in known or ip in local:
                continue
            targets.append(ip)

    found: list[DiscoveredBambu] = []
    if not targets:
        return found
    with ThreadPoolExecutor(max_workers=max(8, min(int(workers), 64))) as pool:
        futs = {pool.submit(_mqtt_port_open, ip): ip for ip in targets}
        for fut in as_completed(futs):
            if stop_event is not None and stop_event.is_set():
                break
            ip = futs[fut]
            try:
                ok = bool(fut.result())
            except Exception:
                ok = False
            if ok:
                item = DiscoveredBambu(ip=ip, name="Bambu MQTT candidate", source="MQTT 8883")
                found.append(item)
                if on_found:
                    try:
                        on_found(item)
                    except Exception:
                        pass
    return found


def discover_bambu(
    ssdp_timeout: float = 6.0,
    on_found: Callable[[DiscoveredBambu], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[DiscoveredBambu]:
    """Cumulative discovery: SSDP first, then /24 MQTT fallback."""
    merged: dict[str, DiscoveredBambu] = {}

    def capture(item: DiscoveredBambu) -> None:
        _emit(merged, item, on_found)

    if on_phase:
        on_phase("SSDP / UDP 2021")
    for item in discover_ssdp(ssdp_timeout, capture, stop_event):
        _emit(merged, item, None)
    if stop_event is not None and stop_event.is_set():
        return list(merged.values())

    if on_phase:
        on_phase("fallback: scan MQTT/TLS 8883")
    known_ips = [x.ip for x in merged.values()]
    for item in discover_mqtt_candidates(known_ips, capture, stop_event):
        _emit(merged, item, None)

    return list(merged.values())


def discovery_self_test() -> None:
    packet = (
        "NOTIFY * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:2021\r\n"
        "NT: urn:bambulab-com:device:3dprinter:1\r\n"
        "USN: 01S00A123456789\r\n"
        "Location: http://192.168.1.55:8883/desc\r\n"
        "DevName.bambu.com: A1 Workshop\r\n"
        "DevModel.bambu.com: N2S\r\n"
        "DevVersion.bambu.com: 01.05.00.00\r\n\r\n"
    )
    item = parse_ssdp_packet(packet, "192.168.1.55")
    if item is None:
        raise RuntimeError("Bambu SSDP parser returned no device")
    if item.ip != "192.168.1.55" or item.serial != "01S00A123456789":
        raise RuntimeError("Bambu SSDP IP/serial parsing failed")
    if item.name != "A1 Workshop" or item.model != "N2S":
        raise RuntimeError("Bambu SSDP name/model parsing failed")
