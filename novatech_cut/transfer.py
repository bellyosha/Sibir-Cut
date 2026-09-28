from __future__ import annotations

import ftplib
import os
import re
import socket
import ssl
import threading
from pathlib import Path
from typing import Callable, Any

FTPS_PORT = 990
FTPS_USER = "bblp"
BLOCK_SIZE = 64 * 1024


class BambuTransferError(RuntimeError):
    pass


class UploadCancelled(BambuTransferError):
    pass


def sanitize_remote_name(name: str) -> str:
    base = Path(str(name or "")).name.strip()
    if not base:
        raise BambuTransferError("Пустое имя файла")
    suffix = Path(base).suffix.lower()
    stem = base[:-len(suffix)] if suffix else base
    clean_stem = re.sub(r"[^A-Za-z0-9_+-]", "_", stem)
    clean_stem = re.sub(r"_+", "_", clean_stem).strip("_")
    if not clean_stem:
        clean_stem = "sibir_cut_job"
    clean_suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)
    clean = clean_stem + clean_suffix
    if len(clean) > 110:
        clean = clean_stem[: max(1, 110-len(clean_suffix))] + clean_suffix
    return clean


def remote_cache_path(name: str) -> str:
    return "/cache/" + sanitize_remote_name(name)


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """Bambu's port 990 starts TLS before the FTP banner.

    The data socket reuses the control-channel TLS session, which is required
    by a number of Bambu firmwares.
    """

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        if port:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        if source_address is not None:
            self.source_address = source_address
        raw = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            source_address=self.source_address,
        )
        try:
            self.sock = self.context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            try: raw.close()
            except Exception: pass
            raise
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            try:
                conn = self.context.wrap_socket(
                    conn,
                    server_hostname=self.host,
                    session=self.sock.session,
                )
            except Exception:
                try: conn.close()
                except Exception: pass
                raise
        return conn, size


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass
    return ctx


def upload_file(
    host: str,
    access_code: str,
    local_path: str | os.PathLike[str],
    *,
    remote_name: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 12.0,
) -> dict[str, Any]:
    host = str(host or "").strip()
    secret = str(access_code or "").strip()
    path = Path(local_path)
    if not host:
        raise BambuTransferError("Не указан IP принтера")
    if not secret:
        raise BambuTransferError("Не указан LAN access code")
    if not path.is_file():
        raise BambuTransferError(f"Файл не найден: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise BambuTransferError("Нельзя отправить пустой файл")
    remote = remote_cache_path(remote_name or path.name)

    ftp = ImplicitFTP_TLS(context=_context())
    sent = 0
    verified = False
    try:
        try:
            ftp.connect(host, FTPS_PORT, timeout=timeout)
        except Exception as exc:
            raise BambuTransferError(f"Не удалось подключиться к FTPS {host}:{FTPS_PORT}: {exc}") from exc
        try:
            ftp.login(FTPS_USER, secret)
        except ftplib.error_perm as exc:
            raise BambuTransferError("Принтер отклонил access code для передачи файла") from exc
        try:
            ftp.prot_p()
            ftp.set_pasv(True)
        except Exception as exc:
            raise BambuTransferError(f"Не удалось включить защищённый канал данных FTPS: {exc}") from exc

        try:
            ftp.delete(remote)
        except ftplib.error_perm as exc:
            if not str(exc).lstrip().startswith("550"):
                raise BambuTransferError(f"Не удалось заменить старый файл {remote}: {exc}") from exc
        except Exception:
            pass

        def on_block(block: bytes) -> None:
            nonlocal sent
            if cancel is not None and cancel.is_set():
                raise UploadCancelled("Передача отменена")
            sent += len(block)
            if progress is not None:
                try: progress(sent, size)
                except Exception: pass

        try:
            with path.open("rb") as fh:
                ftp.storbinary(f"STOR {remote}", fh, blocksize=BLOCK_SIZE, callback=on_block)
        except UploadCancelled:
            try: ftp.delete(remote)
            except Exception: pass
            raise
        except Exception as exc:
            try: ftp.delete(remote)
            except Exception: pass
            raise BambuTransferError(f"Ошибка передачи файла на принтер: {exc}") from exc

        if sent != size:
            try: ftp.delete(remote)
            except Exception: pass
            raise BambuTransferError(f"Передано не полностью: {sent} из {size} байт")

        try:
            ftp.voidcmd("TYPE I")
            remote_size = ftp.size(remote)
            if remote_size is not None and int(remote_size) != int(size):
                try: ftp.delete(remote)
                except Exception: pass
                raise BambuTransferError(
                    f"Размер файла на принтере не совпал: {remote_size} вместо {size} байт"
                )
            verified = remote_size is not None
        except BambuTransferError:
            raise
        except Exception:
            # A successful 226 after STOR is still accepted on firmware that
            # disables SIZE for cache files.
            verified = False

        return {
            "remote_path": remote.lstrip("/"),
            "remote_url": "ftp:///" + remote.lstrip("/"),
            "remote_name": Path(remote).name,
            "size_bytes": size,
            "verified_size": verified,
        }
    finally:
        try: ftp.quit()
        except Exception:
            try: ftp.close()
            except Exception: pass


def transfer_self_test() -> None:
    name = sanitize_remote_name("Тест нож.gcode")
    if not name.endswith(".gcode") or "/" in name or "\\" in name:
        raise RuntimeError("FTPS remote filename sanitizer failed")
    try:
        name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError("FTPS remote filename must be ASCII-safe") from exc
    path = remote_cache_path("../abc.gcode")
    if path != "/cache/abc.gcode":
        raise RuntimeError("FTPS cache path sanitizer failed")
