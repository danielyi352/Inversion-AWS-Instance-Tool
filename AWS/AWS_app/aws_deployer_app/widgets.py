from __future__ import annotations

import subprocess
from pathlib import Path
import stat
import shlex
import time

import boto3
import paramiko
from botocore.exceptions import ClientError
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QHBoxLayout,
    QWidget,
    QLineEdit,
    QDialog,
    QListWidget,
    QVBoxLayout,
    QDialogButtonBox,
)

__all__ = [
    "DropLineEdit",
    "FileUploadWorker",
    "DownloadWorker",
    "InstanceControlDialog",
    "RemoteBrowserDialog",
]


class DropLineEdit(QLineEdit):
    """QLineEdit that supports drag-and-drop of a single file."""

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    # pylint: disable=invalid-name
    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.setText(urls[0].toLocalFile())


class FileUploadWorker(QThread):
    """SFTP upload + docker cp with byte-level progress signal."""

    progress = Signal(int)
    stats = Signal(int, int, float)  # bytes transferred, total bytes, rate (B/s)
    status = Signal(str)
    error = Signal(str)
    done = Signal()

    def __init__(self, host: str, key_path: Path, local_path: Path,
                 remote_tmp: str, container: str, dest_dir: str):
        super().__init__()
        self._host = host
        self._key_path = key_path
        self._local_path = local_path
        self._remote_tmp = remote_tmp
        self._container = container
        self._dest_dir = dest_dir
        self._last_bytes = 0
        self._last_ts = time.monotonic()
        self._cancelled = False
        self._client: paramiko.SSHClient | None = None
        self._sftp = None

    def cancel(self):
        """Request cancellation and tear down open SSH/SFTP sessions."""
        self._cancelled = True
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass

    # pylint: disable=broad-except
    def run(self) -> None:  # noqa: D401
        try:
            if self._cancelled:
                raise RuntimeError("Upload cancelled.")
            self.status.emit("Establishing SSH/SFTP session…")
            key = paramiko.RSAKey.from_private_key_file(str(self._key_path))
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self._host,
                username="ec2-user",
                pkey=key,
                timeout=10,
                banner_timeout=15,
                auth_timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
            self._client = client
            sftp = client.open_sftp()
            self._sftp = sftp
            self.status.emit("Uploading to instance temp path…")
            size = self._local_path.stat().st_size

            def _cb(x, _):
                if self._cancelled:
                    raise RuntimeError("Upload cancelled.")
                now = time.monotonic()
                delta_bytes = x - self._last_bytes
                delta_t = max(now - self._last_ts, 1e-6)
                rate = delta_bytes / delta_t
                self._last_bytes = x
                self._last_ts = now
                self.progress.emit(int(x * 100 / size))
                self.stats.emit(int(x), size, rate)

            sftp.put(str(self._local_path), self._remote_tmp, callback=_cb)
            remote_tmp_q = shlex.quote(self._remote_tmp)
            container_dest_q = shlex.quote(f"{self._container}:{self._dest_dir}")
            self.status.emit("Copying into container…")
            cmd = (
                f"docker cp {remote_tmp_q} {container_dest_q} && "
                f"rm -f {remote_tmp_q}"
            )
            _stdin, _stdout, stderr = client.exec_command(cmd)
            # Some docker commands occasionally emit newline-only stderr; strip
            # to avoid surfacing a blank error dialog.
            err = stderr.read().decode().strip()
            if err:
                raise RuntimeError(err)
            self.status.emit("Finalizing…")
            self.progress.emit(100)
            self.done.emit()
        except Exception as exc:
            msg = str(exc) or "Upload failed (no error message)."
            if self._cancelled:
                msg = "Upload cancelled."
            self.error.emit(msg)


class DownloadWorker(QThread):
    """Downloads a file from the container to the local host with progress."""

    progress = Signal(int)
    stats = Signal(int, int, float)  # bytes transferred, total bytes, rate (B/s)
    status = Signal(str)
    error = Signal(str)
    done = Signal(Path)  # emits local path

    def __init__(self, host: str, key_path: Path, container: str,
                 remote_path: str, local_dest: Path):
        super().__init__()
        self._host = host
        self._key_path = key_path
        self._container = container
        self._remote_path = remote_path
        self._local_dest = local_dest
        self._last_bytes = 0
        self._last_ts = time.monotonic()
        self._cancelled = False
        self._client: paramiko.SSHClient | None = None
        self._sftp = None

    def cancel(self):
        """Request cancellation and tear down open SSH/SFTP sessions."""
        self._cancelled = True
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass

    # pylint: disable=broad-except
    def run(self) -> None:  # noqa: D401
        try:
            if self._cancelled:
                raise RuntimeError("Download cancelled.")
            self.status.emit("Establishing SSH/SFTP session…")
            key = paramiko.RSAKey.from_private_key_file(str(self._key_path))
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self._host,
                username="ec2-user",
                pkey=key,
                timeout=10,
                banner_timeout=15,
                auth_timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
            self._client = client

            filename = Path(self._remote_path).name
            tmp_path = f"/tmp/{filename}"

            # Copy from container to tmp on instance
            container_path_q = shlex.quote(f"{self._container}:{self._remote_path}")
            tmp_path_q = shlex.quote(tmp_path)
            self.status.emit("Copying from container to host…")
            cmd = f"docker cp {container_path_q} {tmp_path_q}"
            _stdin, _stdout, stderr = client.exec_command(cmd)
            err = stderr.read().decode().strip()
            if err:
                raise RuntimeError(err)

            sftp = client.open_sftp()
            self._sftp = sftp

            # Determine if the copied path on the EC2 host is a file or a
            # directory. Paramiko's SFTPAttributes exposes `st_mode`, which we
            # can interrogate with the `stat` module.
            attrs = sftp.stat(tmp_path)

            # --------------------------------------------------------------
            # Directory branch: create a tar.gz archive on the EC2 host so we
            # can transfer a single file rather than attempting a recursive
            # SFTP copy (which Paramiko lacks out-of-the-box).
            # --------------------------------------------------------------
            if stat.S_ISDIR(attrs.st_mode):
                tmp_tar = f"{tmp_path}.tar.gz"

                # Compress the directory into a single archive on the host
                self.status.emit("Archiving directory…")
                cmd_tar = f"tar -czf {tmp_tar} -C /tmp {filename}"
                _stdin, _stdout, stderr = client.exec_command(cmd_tar)
                err = stderr.read().decode().strip()
                if err:
                    raise RuntimeError(err)

                size = sftp.stat(tmp_tar).st_size
                self._last_bytes = 0
                self._last_ts = time.monotonic()

                def _cb(x, _):  # type: ignore
                    if self._cancelled:
                        raise RuntimeError("Download cancelled.")
                    now = time.monotonic()
                    delta_bytes = x - self._last_bytes
                    delta_t = max(now - self._last_ts, 1e-6)
                    rate = delta_bytes / delta_t
                    self._last_bytes = x
                    self._last_ts = now
                    self.progress.emit(int(x * 100 / size))
                    self.stats.emit(int(x), size, rate)

                local_full = self._local_dest / f"{filename}.tar.gz"
                self.status.emit("Downloading archive…")
                sftp.get(tmp_tar, str(local_full), callback=_cb)
                # Clean up remote artefacts
                sftp.remove(tmp_tar)
                client.exec_command(f"rm -rf {tmp_path}")

            # --------------------------------------------------------------
            # File branch: behave as before, downloading the single file.
            # --------------------------------------------------------------
            else:
                size = attrs.st_size
                self._last_bytes = 0
                self._last_ts = time.monotonic()

                def _cb(x, _):  # type: ignore
                    if self._cancelled:
                        raise RuntimeError("Download cancelled.")
                    now = time.monotonic()
                    delta_bytes = x - self._last_bytes
                    delta_t = max(now - self._last_ts, 1e-6)
                    rate = delta_bytes / delta_t
                    self._last_bytes = x
                    self._last_ts = now
                    self.progress.emit(int(x * 100 / size))
                    self.stats.emit(int(x), size, rate)

                local_full = self._local_dest / filename
                self.status.emit("Downloading file…")
                sftp.get(tmp_path, str(local_full), callback=_cb)
                sftp.remove(tmp_path)

            client.close()
            self.status.emit("Finalizing…")
            self.progress.emit(100)
            self.done.emit(local_full)
        except Exception as exc:
            msg = str(exc) or "Download failed (no error message)."
            if self._cancelled:
                msg = "Download cancelled."
            self.error.emit(msg)


class InstanceControlDialog(QWidget):
    """Small dialog that lets the user terminate or SSH into the instance."""

    def __init__(self, instance_id: str, public_dns: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Instance Controls")
        self._iid = instance_id
        self._dns = public_dns

        iid_lbl = QLabel(instance_id)
        dns_lbl = QLabel(public_dns)
        term_btn = QPushButton("Terminate Instance")
        ssh_btn = QPushButton("Connect (SSH)")

        layout = QHBoxLayout(self)
        layout.addWidget(QLabel("Instance:"))
        layout.addWidget(iid_lbl)
        layout.addWidget(QLabel("DNS:"))
        layout.addWidget(dns_lbl)
        layout.addStretch()
        layout.addWidget(ssh_btn)
        layout.addWidget(term_btn)

        ssh_btn.clicked.connect(self._open_ssh)
        term_btn.clicked.connect(self._terminate)

    # ---------------------------------------------------------------------
    # Slots
    # ---------------------------------------------------------------------

    def _open_ssh(self):
        cmd = ["osascript", "-e",
               f'tell application "Terminal" to do script "ssh ec2-user@{self._dns}"']
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _terminate(self):
        profile = "default"
        region = "us-west-2"
        ec2 = boto3.Session(profile_name=profile, region_name=region).client("ec2")
        try:
            ec2.terminate_instances(InstanceIds=[self._iid])
            QMessageBox.information(self, "Terminate", "Termination initiated")
            self.close()
        except ClientError as exc:
            QMessageBox.critical(self, "Error", str(exc))


class RemoteBrowserDialog(QDialog):
    """Simple dialog to browse container filesystem and pick a file."""

    class _LsWorker(QThread):
        result = Signal(list)
        error = Signal(str)

        def __init__(self, host: str, key_path: Path, container: str, path: str, parent=None):
            super().__init__(parent)
            self._host = host
            self._key_path = key_path
            self._container = container
            self._path = path
            self._client: paramiko.SSHClient | None = None
            self._cancelled = False

        def cancel(self):
            self._cancelled = True
            if self._client is not None:
                self._client.close()

        def run(self):
            try:
                entries = self._run_ls()
                if not self._cancelled:
                    self.result.emit(entries)
            except Exception as exc:  # pragma: no cover - UI feedback only
                if not self._cancelled:
                    self.error.emit(str(exc))
            finally:
                if self._client is not None:
                    self._client.close()
                    self._client = None

        def _run_ls(self) -> list[str]:
            if not Path(self._key_path).exists():
                raise FileNotFoundError(f"SSH key {self._key_path} not found. Provide the .pem locally.")
            key = paramiko.RSAKey.from_private_key_file(str(self._key_path))
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(self._host, username="ec2-user", pkey=key, timeout=10, banner_timeout=10)
            container_q = shlex.quote(self._container)
            inner = f"ls -Ap {shlex.quote(self._path)}"
            cmd = f"docker exec {container_q} sh -c {shlex.quote(inner)}"
            _stdin, stdout, stderr = self._client.exec_command(cmd, timeout=15)
            data = stdout.read().decode().splitlines()
            err = stderr.read().decode().strip()
            if err:
                raise RuntimeError(err)
            return data

    def __init__(self, host: str, key_path: Path, container: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select file in container")
        self._host = host
        self._key_path = key_path
        self._container = container
        self._cwd = "/"
        self._ls_thread: RemoteBrowserDialog._LsWorker | None = None

        self._label = QLabel(self._cwd)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double)

        btn_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._list)
        layout.addWidget(btn_box)

        self._refresh()

    @staticmethod
    def _run_ls(host: str, key_path: Path, container: str, path: str) -> list[str]:
        if not Path(key_path).exists():
            raise FileNotFoundError(f"SSH key {key_path} not found. Provide the .pem locally.")
        key = paramiko.RSAKey.from_private_key_file(str(key_path))
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="ec2-user", pkey=key, timeout=10)
        container_q = shlex.quote(container)
        inner = f"ls -Ap {shlex.quote(path)}"
        cmd = f"docker exec {container_q} sh -c {shlex.quote(inner)}"
        try:
            _stdin, stdout, stderr = client.exec_command(cmd)
            err = stderr.read().decode().strip()
            if err:
                raise RuntimeError(err)
            return stdout.read().decode().splitlines()
        finally:
            client.close()

    def _refresh(self):
        self._label.setText(self._cwd)
        self._list.clear()
        self._list.addItem("Loading …")
        self._list.setEnabled(False)

        if self._ls_thread and self._ls_thread.isRunning():
            self._ls_thread.cancel()
            self._ls_thread.wait()

        self._ls_thread = self._LsWorker(self._host, self._key_path, self._container, self._cwd, parent=self)
        self._ls_thread.result.connect(self._apply_listing)
        self._ls_thread.error.connect(self._handle_ls_error)
        self._ls_thread.finished.connect(lambda: setattr(self, "_ls_thread", None))
        self._ls_thread.start()

    def _apply_listing(self, entries: list[str]):
        self._list.clear()
        if self._cwd != "/":
            self._list.addItem("..")
        for name in entries:
            if name:
                self._list.addItem(name)
        self._list.setEnabled(True)

    def _handle_ls_error(self, msg: str):
        self._list.clear()
        self._list.setEnabled(True)
        cleaned = (msg or "").strip()
        if not cleaned:
            cleaned = (
                "Could not list the container path. Possible causes:\n"
                "- SSH key not found or permission denied\n"
                "- Container not running\n"
                "- Network/SSM connectivity issue\n\n"
                f"Host: {self._host}\nContainer: {self._container}\nPath: {self._cwd}"
            )
        QMessageBox.critical(self, "Remote Error", cleaned)

    def _on_double(self, item):
        if not self._list.isEnabled():
            return
        name = item.text()
        if name == "..":
            self._cwd = "/" if self._cwd == "/" else "/".join(self._cwd.rstrip("/").split("/")[:-1]) or "/"
            self._refresh()
            return
        if name.endswith("/"):
            self._cwd = (self._cwd.rstrip("/") + "/" + name.rstrip("/"))
            self._refresh()
            return
        self.accept()

    def closeEvent(self, event):
        if self._ls_thread and self._ls_thread.isRunning():
            self._ls_thread.cancel()
            self._ls_thread.wait(2000)
        super().closeEvent(event)

    def selected_path(self) -> str:
        current = self._list.currentItem()
        if current is None:
            return ""
        name = current.text()
        if name == "..":
            return ""
        if self._cwd.endswith("/"):
            return self._cwd + name
        return f"{self._cwd}/{name}"