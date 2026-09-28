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
CONNECT_TIMEOUT = 20.0
DATA_TIMEOUT = 30.0
FINAL_REPLY_TIMEOUT = 2.5


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


def remote_upload_path(name: str) -> str:
    """Path visible as a user-uploaded file on the printer storage.

    Bambu/Orca user uploads are stored at the FTPS root. /cache is primarily
    firmware/cloud staging and is not the right target for a file the user
    intends to start later from the printer screen.
    """
    return sanitize_remote_name(name)


# Kept for compatibility with old imports/tests. New manual uploads use root.
def remote_cache_path(name: str) -> str:
    return "/cache/" + sanitize_remote_name(name)


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """Implicit FTPS control channel used by Bambu printers.

    The A1 family is special: depending on firmware it may accept PROT P but
    still behave unreliably when the data socket is TLS-wrapped. Therefore this
    client can deliberately keep the data socket plain while the authenticated
    control channel remains encrypted.
    """

    def __init__(self, *args, skip_data_tls: bool = False, **kwargs):
        self.skip_data_tls = bool(skip_data_tls)
        super().__init__(*args, **kwargs)

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
            try:
                raw.close()
            except Exception:
                pass
            raise
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        # Bypass FTP_TLS.ntransfercmd so we control data-channel wrapping.
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p and not self.skip_data_tls:
            try:
                conn = self.context.wrap_socket(
                    conn,
                    server_hostname=self.host,
                    session=self.sock.session,
                )
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                raise
        return conn, size


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        # Bambu LAN FTPS is most predictable with TLS 1.2 on the control
        # channel; newer Python versions otherwise negotiate 1.3 when offered.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass
    return ctx


def _open_client(host: str, access_code: str, *, clear_data: bool) -> ImplicitFTP_TLS:
    ftp = ImplicitFTP_TLS(context=_context(), skip_data_tls=clear_data)
    try:
        ftp.connect(host, FTPS_PORT, timeout=CONNECT_TIMEOUT)
    except Exception as exc:
        try:
            ftp.close()
        except Exception:
            pass
        raise BambuTransferError(f"Не удалось подключиться к FTPS {host}:{FTPS_PORT}: {exc}") from exc
    try:
        ftp.login(FTPS_USER, access_code)
    except ftplib.error_perm as exc:
        try:
            ftp.close()
        except Exception:
            pass
        raise BambuTransferError("Принтер отклонил LAN access code для передачи файла") from exc
    try:
        ftp.set_pasv(True)
        if clear_data:
            # A1/A1 Mini compatibility path: encrypted control connection,
            # clear passive data connection.
            ftp.prot_c()
        else:
            ftp.prot_p()
    except Exception as exc:
        try:
            ftp.close()
        except Exception:
            pass
        raise BambuTransferError(
            "Не удалось настроить FTPS-канал данных "
            + ("PROT C" if clear_data else "PROT P")
            + f": {exc}"
        ) from exc
    return ftp


def _send_manual(
    ftp: ImplicitFTP_TLS,
    path: Path,
    remote: str,
    *,
    size: int,
    progress: Callable[[int, int], None] | None,
    cancel: threading.Event | None,
) -> tuple[int, bool]:
    """Manual STOR, intentionally not ftplib.storbinary().

    A1 firmware is known to hang in storbinary's final voidresp() even after all
    bytes have already been accepted. We send the file ourselves, close only the
    data socket, then give the control channel a very short chance to return 226.
    No print/start command is sent here or anywhere in this module.
    """
    sent = 0
    ftp.voidcmd("TYPE I")
    conn = ftp.transfercmd(f"STOR {remote}")
    try:
        conn.setblocking(True)
        conn.settimeout(DATA_TIMEOUT)
        with path.open("rb") as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UploadCancelled("Передача отменена")
                block = fh.read(BLOCK_SIZE)
                if not block:
                    break
                conn.sendall(block)
                sent += len(block)
                if progress is not None:
                    try:
                        progress(sent, size)
                    except Exception:
                        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if sent != size:
        raise BambuTransferError(f"Передано не полностью: {sent} из {size} байт")

    # A1 can leave the control connection waiting for 226 after the data socket
    # is already finished. Do not turn that firmware quirk into a failed upload.
    acknowledged = False
    try:
        old_timeout = ftp.sock.gettimeout()
    except Exception:
        old_timeout = None
    try:
        try:
            ftp.sock.settimeout(FINAL_REPLY_TIMEOUT)
        except Exception:
            pass
        try:
            ftp.voidresp()
            acknowledged = True
        except (socket.timeout, TimeoutError):
            acknowledged = False
        except ftplib.error_temp:
            # Some firmwares answer 426 even though the complete file was
            # written. Since this workflow never auto-starts a print, the user
            # can simply select the uploaded file from the printer screen.
            acknowledged = False
    finally:
        if old_timeout is not None:
            try:
                ftp.sock.settimeout(old_timeout)
            except Exception:
                pass
    return sent, acknowledged


def upload_file(
    host: str,
    access_code: str,
    local_path: str | os.PathLike[str],
    *,
    remote_name: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float | None = None,  # retained for API compatibility
) -> dict[str, Any]:
    """Upload a file to an A1 over LAN only; never start it.

    The preferred A1 path is PROT C (TLS control + plain data). If firmware
    refuses that mode before any file bytes are transferred, one PROT P/session
    reuse attempt is made as a compatibility fallback.
    """
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

    remote = remote_upload_path(remote_name or path.name)
    last_error: Exception | None = None

    # A1 first: encrypted control + clear data. Protected-data fallback covers
    # firmware revisions that insist on PROT P.
    for clear_data in (True, False):
        if cancel is not None and cancel.is_set():
            raise UploadCancelled("Передача отменена")
        ftp: ImplicitFTP_TLS | None = None
        try:
            ftp = _open_client(host, secret, clear_data=clear_data)
            sent, acknowledged = _send_manual(
                ftp,
                path,
                remote,
                size=size,
                progress=progress,
                cancel=cancel,
            )
            return {
                "remote_path": remote,
                "remote_url": "ftp:///" + remote,
                "remote_name": remote,
                "size_bytes": size,
                "bytes_sent": sent,
                "acknowledged": acknowledged,
                "verified_size": False,
                "data_mode": "PROT C" if clear_data else "PROT P",
                "started": False,
            }
        except UploadCancelled:
            raise
        except BambuTransferError as exc:
            last_error = exc
        except (socket.timeout, TimeoutError) as exc:
            last_error = BambuTransferError(f"Таймаут FTPS при передаче: {exc}")
        except Exception as exc:
            last_error = BambuTransferError(f"Ошибка передачи файла на принтер: {exc}")
        finally:
            # Do not call QUIT here: if firmware is late with 226, QUIT would
            # wait on the same stale control response and recreate the timeout.
            if ftp is not None:
                try:
                    ftp.close()
                except Exception:
                    pass

    if last_error is not None:
        raise last_error
    raise BambuTransferError("Не удалось передать файл на принтер")


def transfer_self_test() -> None:
    name = sanitize_remote_name("Тест нож.gcode")
    if not name.endswith(".gcode") or "/" in name or "\\" in name:
        raise RuntimeError("FTPS remote filename sanitizer failed")
    try:
        name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError("FTPS remote filename must be ASCII-safe") from exc
    if remote_upload_path("../abc.gcode") != "abc.gcode":
        raise RuntimeError("Manual upload must target the printer storage root")
    if remote_cache_path("../abc.gcode") != "/cache/abc.gcode":
        raise RuntimeError("Legacy cache path helper failed")
