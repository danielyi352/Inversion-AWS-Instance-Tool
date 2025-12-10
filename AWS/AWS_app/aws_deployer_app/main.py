# -*- coding: utf-8 -*-
"""AWS EC2 container deployer GUI.

This single-file PySide6 application lets a user pick an ECR repository and
spin up an appropriately sized EC2 instance (CPU or GPU), then runs the
container on it.  It is intentionally dependency-light and uses AWS CLI for
all AWS interactions so that the SSO flow works exactly the same as in a
terminal.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import shutil
import threading
import webbrowser
from urllib.request import urlopen
from pathlib import Path
from typing import List, Tuple

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    SSOError,
    TokenRetrievalError,
)
from PySide6.QtWidgets import QProgressDialog

# Qt imports
from PySide6.QtCore import QThread, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressBar,
    QDialog,
)

from aws_utils import (
    AwsWorker,
    DeployRequest,
    DeploymentWorker,
    profile_sso_region,
)

from widgets import (
    DropLineEdit,
    FileUploadWorker,
    DownloadWorker,
    InstanceControlDialog,
    RemoteBrowserDialog,
)

APP_VERSION = "1.0.0"

# Optional override URLs for update checking and download
UPDATE_VERSION_URL = os.environ.get(
    "APP_UPDATE_URL",
    "https://raw.githubusercontent.com/danielvega/inversion-lab/main/AWS/AWS_app/aws_deployer_app/version.txt",
)
UPDATE_DOWNLOAD_URL = os.environ.get(
    "APP_DOWNLOAD_URL",
    "https://raw.githubusercontent.com/danielvega/inversion-lab/main/AWS/AWS_app/Inversion%20Deployer.dmg",
)

US_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
]

# Path to persist GUI settings when "Remember settings" is enabled
SETTINGS_FILE = Path.home() / ".aws_deployer_settings.json"

# ---------------------------------------------------------------------------
# Transfer formatting helpers (shared by upload/download progress)
# ---------------------------------------------------------------------------


def format_bytes(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(num)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{num}B"


def format_rate(rate_bps: float) -> str:
    if rate_bps <= 0:
        return "0 B/s"
    return f"{format_bytes(int(rate_bps))}/s"


def compose_transfer_label(
    action: str, transferred: int, total: int, rate: float
) -> str:
    total_txt = format_bytes(total) if total else "?"
    return (
        f"{action}… {format_bytes(transferred)} / {total_txt} " f"({format_rate(rate)})"
    )


# Dataclass definitions now live in aws_utils
# Helper functions live in functions.py

# ---------------------------------------------------------------------------
# Background worker to list running EC2 instances (moved up for early access)
# ---------------------------------------------------------------------------


class InstancesWorker(QThread):
    """Fetch running EC2 instances (ID, public DNS, key name)."""

    data_ready = Signal(list)  # list[(iid, dns, key, name, inst_type)]
    error = Signal(str)

    def __init__(self, profile: str, region: str):
        super().__init__()
        self._profile = profile
        self._region = region

    def run(self):  # noqa: D401
        try:
            session = boto3.Session(
                profile_name=self._profile, region_name=self._region
            )
            ec2 = session.client("ec2")
            resp = ec2.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )
            instances: list[list] = []  # mutable list of tuples with extra fields
            for reservation in resp.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    iid = inst.get("InstanceId")
                    dns = inst.get("PublicDnsName", "")
                    key_name = inst.get("KeyName", "")
                    inst_type = inst.get("InstanceType", "")
                    # Extract 'Name' tag if present
                    name_tag = ""
                    for tag in inst.get("Tags", []):
                        if tag.get("Key") == "Name":
                            name_tag = tag.get("Value", "")
                            break
                    if iid:
                        instances.append((iid, dns, key_name, name_tag, inst_type))
            self.data_ready.emit(instances)
        except (
            ClientError,
            BotoCoreError,
            NoCredentialsError,
            TokenRetrievalError,
            SSOError,
        ) as exc:  # pragma: no cover
            self.error.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover
            self.error.emit(str(exc))
            return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MainWindow(QWidget):
    # Signal emitted from background thread when an update is available
    # Args: (remote_version: str, download_url: str)
    _update_available = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inversion Deployer")
        self.resize(500, 300)

        # Set application/window icon
        logo_path = Path(__file__).with_name("Logo.png")
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.region_combo = QComboBox()
        self.region_combo.addItems(US_REGIONS)

        self.account_edit = QLineEdit()
        self.account_edit.setPlaceholderText("123456789012")

        self.repo_combo = QComboBox()
        self.keypair_combo = QComboBox()
        self.CREATE_KEY_TEXT = "Create new key…"
        self.keypair_combo.addItem(self.CREATE_KEY_TEXT)
        self.sg_combo = QComboBox()

        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(1, 2048)
        self.volume_spin.setValue(30)

        self.instance_combo = QComboBox()
        self.instance_combo.addItems(
            [
                "t3.micro",
                "c7i.large",
                "c7i.4xlarge",
                "c7i.8xlarge",
                "c7i.12xlarge",
                "c7i.24xlarge",
                "g4dn.xlarge",
                "g4dn.2xlarge",
                "g4dn.4xlarge",
                "g4dn.8xlarge",
                "g4dn.16xlarge",
                "g4dn.12xlarge",
                "g4dn.metal",
                "p5.48xlarge",
                "c5a.8xlarge",
                "hpc7a.96xlarge",
            ]
        )

        self.profile_edit = QLineEdit("default")

        # --------------------------------------------------
        # Running instances dropdown (populated on refresh)
        # --------------------------------------------------
        self.instances_combo = QComboBox()
        self.instances_combo.setEnabled(False)
        self.instances_combo.currentIndexChanged.connect(self._on_instance_selected)

        self.sso_button = QPushButton("AWS SSO Login")
        self.refresh_button = QPushButton("Refresh AWS Data")
        self.deploy_button = QPushButton("Deploy")
        self.deploy_button.setEnabled(False)

        self.terminate_button = QPushButton("Terminate Instance")
        self.terminate_button.setEnabled(False)

        # Connect/reconnect button
        self.connect_button = QPushButton("Connect (SSH)")
        self.connect_button.setEnabled(False)

        self.stacked_widget = QStackedWidget()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        # ------------------ File-transfer section ------------------
        self.transfer_group = QWidget()
        tform = QHBoxLayout(self.transfer_group)

        # Source file selector (drag-drop enabled line edit)
        self.src_edit = DropLineEdit()
        self.src_edit.setPlaceholderText("Drag file or click Browse…")
        self.browse_btn = QPushButton("Browse…")
        tform.addWidget(self.src_edit)
        tform.addWidget(self.browse_btn)

        # Destination combo inside container
        self.dest_combo = QComboBox()
        self.dest_combo.setMinimumWidth(150)
        self.dest_refresh_btn = QPushButton("Reload")
        self.upload_btn = QPushButton("Upload")
        tform.addWidget(self.dest_combo)
        tform.addWidget(self.dest_refresh_btn)
        tform.addWidget(self.upload_btn)

        self.transfer_group.setEnabled(False)

        # Remember settings checkbox
        self.remember_check = QCheckBox("Remember settings")

        # ------------------ Download section ------------------
        self.download_group = QWidget()
        dform = QHBoxLayout(self.download_group)

        self.container_combo = QComboBox()
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("/path/in/container/file.txt")
        self.remote_browse_btn = QPushButton("Remote…")
        self.local_dir_edit = DropLineEdit()
        self.local_dir_edit.setPlaceholderText("Local destination directory …")
        self.local_browse_btn = QPushButton("Browse…")
        self.download_btn = QPushButton("Download")

        for w in (
            self.container_combo,
            self.remote_edit,
            self.remote_browse_btn,
            self.local_dir_edit,
            self.local_browse_btn,
            self.download_btn,
        ):
            dform.addWidget(w)

        self.download_group.setEnabled(False)

        # ------------------ AWS Configuration Settings ------------------

        form = QFormLayout()
        form.addRow("AWS Profile", self.profile_edit)
        form.addRow("AWS Region", self.region_combo)
        form.addRow("AWS Account ID", self.account_edit)
        form.addRow("ECR Repository", self.repo_combo)
        form.addRow("Instance Type", self.instance_combo)
        form.addRow("Key Pair", self.keypair_combo)
        form.addRow("Security Group", self.sg_combo)
        form.addRow("Volume Size (GiB)", self.volume_spin)
        # Running Instances combo is now placed in the right-hand panel

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.sso_button)
        buttons_layout.addWidget(self.refresh_button)
        buttons_layout.addWidget(self.terminate_button)
        buttons_layout.addWidget(self.connect_button)
        buttons_layout.addWidget(self.deploy_button)

        # --------------------------------------------------------------
        # Layout hierarchy
        #   root_layout (vertical)
        #     ├── columns_layout (horizontal)
        #     │     ├── left_layout   (AWS settings)
        #     │     └── right_layout  (placeholder)
        #     └── bottom_layout (vertical) – actions, logs, widgets
        # --------------------------------------------------------------

        root_layout = QVBoxLayout(self)

        # -------------------- Columns (top) -------------------------
        columns_layout = QHBoxLayout()
        root_layout.addLayout(columns_layout)

        # Left column -------------------------------------------------
        left_layout = QVBoxLayout()
        left_layout.addLayout(form)
        columns_layout.addLayout(left_layout, stretch=3)

        # Right column ------------------------------------------------
        right_layout = QVBoxLayout()
        # ------------------ AWS SSO status indicator -----------------
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("AWS SSO Status"))
        self.sso_status_lbl = QLabel()
        self._set_sso_indicator(False)  # red by default
        self.sso_status_lbl.setFixedSize(12, 12)
        status_row.addWidget(self.sso_status_lbl)
        status_row.addStretch()
        right_layout.addLayout(status_row)

        right_layout.addWidget(QLabel("Running Instances"))
        right_layout.addWidget(self.instances_combo)
        right_layout.addStretch()
        columns_layout.addLayout(right_layout, stretch=2)

        # ------------------- Bottom section -------------------------
        bottom_layout = QVBoxLayout()
        root_layout.addLayout(bottom_layout)

        # Action buttons row
        bottom_layout.addLayout(buttons_layout)

        # Progress/logs and other widgets
        bottom_layout.addWidget(self.stacked_widget)
        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.log_text)
        bottom_layout.addWidget(self.remember_check)
        bottom_layout.addWidget(self.transfer_group)
        bottom_layout.addWidget(self.download_group)

        # Instance control buttons (connect / terminate)
        action_btns = QHBoxLayout()
        action_btns.addStretch()
        action_btns.addWidget(self.connect_button)
        action_btns.addWidget(self.terminate_button)
        bottom_layout.addLayout(action_btns)

        self.deploy_worker = None  # placeholder
        self.current_instance_id = None
        self.current_public_dns = None

        # Load persisted settings if present
        self._loading_settings = False
        self.saved_settings = {}
        self.load_settings()

        # --------------------------------------------------
        # Signal connections (restored)
        # --------------------------------------------------
        self.sso_button.clicked.connect(self.on_sso_login)
        self.refresh_button.clicked.connect(self.refresh_aws_data)
        self.deploy_button.clicked.connect(self.deploy)
        self.terminate_button.clicked.connect(self.terminate_current_instance)
        self.connect_button.clicked.connect(self.open_ssh_terminal)
        self.keypair_combo.currentTextChanged.connect(self.on_keypair_changed)
        self.remember_check.stateChanged.connect(self.on_remember_toggled)
        self.browse_btn.clicked.connect(self._choose_file)
        self.upload_btn.clicked.connect(self._upload_file)
        self.dest_refresh_btn.clicked.connect(self._populate_container_dirs)
        self.local_browse_btn.clicked.connect(self._choose_local_dir)
        self.download_btn.clicked.connect(self._download_file)
        self.remote_browse_btn.clicked.connect(self._browse_remote)

        self._prev_keypair_text = None

        # ---------------- Post-init state -----------------
        self.instances_map: dict[str, Tuple[str, str]] = {}  # label -> (iid, dns)
        self._aws_cache: dict | None = None
        self._aws_cache_ts: float = 0.0
        self._transfer_state: dict[QProgressDialog, dict] = {}
        self._transfer_timer = QTimer(self)
        self._transfer_timer.setInterval(1000)
        self._transfer_timer.timeout.connect(self._tick_transfer_watchdog)

        # ------------------- SSO status poll timer -------------------
        self.sso_timer = QTimer(self)
        self.sso_timer.setInterval(300_000)  # 5 minutes
        self.sso_timer.timeout.connect(self._update_sso_status)
        self.sso_timer.start()
        # Perform an immediate check at startup
        self._update_sso_status()
        self._augment_path()
        self._check_prereqs()
        # Connect update signal to slot (thread-safe GUI update)
        self._update_available.connect(self._on_update_available)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    @Slot()
    def on_sso_login(self):
        profile = self.profile_edit.text().strip() or "default"
        try:
            # Validate region
            selected_region = self.region_combo.currentText()
            cfg_region = profile_sso_region(profile)
            if cfg_region and cfg_region != selected_region:
                QMessageBox.critical(
                    self,
                    "SSO Error",
                    f"Selected AWS region ({selected_region}) does not match SSO configured region ({cfg_region}) for profile '{profile}'.",
                )
                return

            ret = subprocess.call(["aws", "sso", "login", "--profile", profile])
            if ret != 0:
                QMessageBox.critical(
                    self,
                    "SSO Error",
                    "AWS SSO login failed. Ensure your SSO credentials are configured and region is correct.",
                )
                return

            QMessageBox.information(
                self, "SSO", "Login successful! Now click Refresh AWS Data."
            )
            self.deploy_button.setEnabled(False)
            self._set_sso_indicator(True)
        except FileNotFoundError:
            QMessageBox.critical(
                self, "AWS CLI Missing", "AWS CLI not found. Please install AWS CLI v2."
            )

    @Slot()
    def refresh_aws_data(self):
        profile = self.profile_edit.text().strip() or "default"
        region = self.region_combo.currentText()

        self.refresh_button.setEnabled(False)
        use_cache = (
            self._aws_cache is not None
            and (time.monotonic() - self._aws_cache_ts) < 300
        )
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            use_cache = False

        if use_cache:
            self.populate_data(self._aws_cache)  # type: ignore[arg-type]
        else:
            self.worker = AwsWorker(profile, region)
            self.worker.data_ready.connect(self.populate_data)
            self.worker.error.connect(self.aws_error)
            self.worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
            self.worker.start()

        # Launch worker to fetch currently running instances
        self.instances_combo.clear()
        self.instances_combo.setEnabled(False)
        self.instances_worker = InstancesWorker(profile, region)
        self.instances_worker.data_ready.connect(self.populate_instances)
        self.instances_worker.error.connect(self.aws_error)
        self.instances_worker.finished.connect(
            lambda: self.refresh_button.setEnabled(True)
        )
        self.instances_worker.start()
        self._aws_error_shown = False
        self._aws_error_last_msg = None

    @Slot(dict)
    def populate_data(self, data):
        self._aws_cache = data
        self._aws_cache_ts = time.monotonic()

        self.repo_combo.clear()
        self.repo_combo.addItems(data.get("repositories", []))

        self.keypair_combo.clear()
        self.keypair_combo.addItems(data.get("key_pairs", []))
        # Ensure sentinel present at end
        if self.keypair_combo.findText(self.CREATE_KEY_TEXT) == -1:
            self.keypair_combo.addItem(self.CREATE_KEY_TEXT)

        self.sg_combo.clear()
        self.sg_combo.addItems(data.get("security_groups", []))

        self.deploy_button.setEnabled(True)

        # Enable instances combo if already populated
        if self.instances_combo.count():
            self.instances_combo.setEnabled(True)

        # Apply saved dynamic values (repo, key_pair, security_group) after AWS data fetch
        if self.remember_check.isChecked() and self.saved_settings:
            for combo, key in [
                (self.repo_combo, "repository"),
                (self.keypair_combo, "key_pair"),
                (self.sg_combo, "security_group"),
            ]:
                val = self.saved_settings.get(key)
                if val:
                    idx = combo.findText(val)
                    if idx == -1:
                        combo.addItem(val)
                        idx = combo.findText(val)
                    combo.setCurrentIndex(idx)

    @Slot(str)
    def aws_error(self, msg):
        hint = ""
        if "Token has expired" in msg or "SSO" in msg:
            hint = "\n\nClick 'AWS SSO Login' and try Refresh again."
        if self._aws_error_shown and self._aws_error_last_msg == msg:
            return
        QMessageBox.critical(self, "AWS Error", msg + hint)
        self._aws_error_shown = True
        self._aws_error_last_msg = msg

    # ------------------------------------------------------------------
    # Running instances helpers
    # ------------------------------------------------------------------

    @Slot(list)
    def populate_instances(self, instances):
        """Populate dropdown with (instance_id, dns, key_name) entries."""

        self.instances_map.clear()
        self.instances_combo.clear()

        for iid, dns, key, name_tag, inst_type in instances:
            display_name = name_tag or iid
            label = f"{display_name}:{inst_type}"
            self.instances_map[label] = (iid, dns, key)
            self.instances_combo.addItem(label)

        self.instances_combo.setEnabled(bool(instances))

    def _on_instance_selected(self, index: int):
        if index == -1:
            return
        label = self.instances_combo.itemText(index)
        if label not in self.instances_map:
            return
        iid, dns, key = self.instances_map[label]
        self.current_instance_id = iid
        self.current_public_dns = dns
        self.current_keypair = key or getattr(self, "current_keypair", "")

        # Sync key-pair combo to the instance's key (adds if missing)
        if key:
            if self.keypair_combo.findText(key) == -1:
                self.keypair_combo.addItem(key)
            self.keypair_combo.setCurrentText(key)

        # Enable actions now that an instance is selected
        self.connect_button.setEnabled(bool(dns))
        self.terminate_button.setEnabled(True)
        self.transfer_group.setEnabled(True)
        self.download_group.setEnabled(True)

        # Refresh container and directory combos for the newly selected instance
        self._populate_container_dirs()
        self._populate_containers()

    def deploy(self):
        if self.deploy_worker is not None and self.deploy_worker.isRunning():
            QMessageBox.warning(self, "Deploy", "Deployment already in progress.")
            return

        if not self.account_edit.text().strip():
            QMessageBox.critical(self, "Input Error", "AWS Account ID cannot be empty.")
            return

        req = DeployRequest(
            profile=self.profile_edit.text().strip() or "default",
            region=self.region_combo.currentText(),
            account_id=self.account_edit.text().strip(),
            repository=self.repo_combo.currentText(),
            instance_type=self.instance_combo.currentText(),
            key_pair=self.keypair_combo.currentText(),
            security_group=self.sg_combo.currentText(),
            volume_size=self.volume_spin.value(),
        )

        self.deploy_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        self.deploy_worker = DeploymentWorker(req)
        self.deploy_worker.success.connect(self.deploy_success)
        self.deploy_worker.error.connect(self.deploy_error)
        self.deploy_worker.progress.connect(self.update_progress)
        self.deploy_worker.log.connect(self.append_log)
        self.deploy_worker.finished.connect(lambda: self.deploy_button.setEnabled(True))
        self.deploy_worker.finished.connect(self.enable_actions_if_instance)
        self.deploy_worker.start()

    @Slot(object)
    def deploy_success(self, result):
        self.current_instance_id = result.instance_id
        self.current_keypair = self.keypair_combo.currentText()
        self.current_public_dns = result.public_dns
        ctrl = InstanceControlDialog(result.instance_id, result.public_dns, parent=self)
        ctrl.show()
        self.terminate_button.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.transfer_group.setEnabled(True)
        self.download_group.setEnabled(True)
        self._populate_container_dirs()
        self._populate_containers()
        container = (
            f"{self.profile_edit.text().strip() or 'default'}-"
            f"{self.repo_combo.currentText()}-container"
        )
        self._enter_container_shell(container)

    @Slot(str)
    def deploy_error(self, msg):
        QMessageBox.critical(self, "Deployment Error", msg)
        # Reset UI state
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.terminate_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.transfer_group.setEnabled(False)
        self.download_group.setEnabled(False)

    @Slot(int)
    def update_progress(self, value: int):
        self.progress_bar.setValue(value)
        if value == 100 and self.current_instance_id:
            self.terminate_button.setEnabled(True)
            self.connect_button.setEnabled(True)

    @Slot(str)
    def append_log(self, msg: str):
        self.log_text.append(msg)

    @Slot()
    def enable_actions_if_instance(self):
        if self.current_instance_id:
            self.terminate_button.setEnabled(True)
            self.connect_button.setEnabled(True)

    # ------------------------------------------------------------------
    # SSH key resolution helpers (shared by transfer/browse features)
    # ------------------------------------------------------------------

    def _current_keypair_name(self) -> str:
        name = getattr(self, "current_keypair", "")
        if not name:
            name = self.keypair_combo.currentText().strip()
        return name

    def _resolve_key_path(self) -> Path | None:
        candidates: list[Path] = []
        override = os.environ.get("SSH_KEY_PATH")
        if override:
            candidates.append(Path(override).expanduser())
        key_name = self._current_keypair_name()
        if key_name:
            candidates.append(Path.home() / ".ssh" / f"{key_name}.pem")
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate
        return None

    def _require_key_file(self) -> Path | None:
        key_path = self._resolve_key_path()
        if key_path:
            return key_path
        key_name = self._current_keypair_name() or "current key pair"
        override = os.environ.get("SSH_KEY_PATH")
        tried = []
        if override:
            tried.append(f"SSH_KEY_PATH ({override})")
        tried.append(f"~/.ssh/{key_name}.pem")
        QMessageBox.critical(
            self,
            "Key missing",
            "Could not find the SSH private key needed for this instance.\n"
            f"Tried: {', '.join(tried)}.\n"
            "Set SSH_KEY_PATH before launching the app or copy the .pem into ~/.ssh.",
        )
        return None

    # ------------------------------------------------------------------
    # Close handling
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        # Save settings only if remember is checked at close
        if self.remember_check.isChecked():
            self.save_settings()
        event.accept()

    # ------------------------------------------------------------------
    # Terminate current instance
    # ------------------------------------------------------------------

    @Slot()
    def terminate_current_instance(self):
        if not self.current_instance_id:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Termination",
            f"Terminate instance {self.current_instance_id}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Capture current details before clearing so thread has valid values
        instance_id = self.current_instance_id
        region = self.region_combo.currentText()
        profile = self.profile_edit.text().strip() or "default"

        # Mark as no instance so user can close app immediately
        self.current_instance_id = None
        self.current_public_dns = None
        self.terminate_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.transfer_group.setEnabled(False)
        self.download_group.setEnabled(False)

        # Clear progress bar and log to indicate shutdown
        self.progress_bar.setValue(0)
        self.log_text.clear()

        # Run termination in background thread so UI stays responsive
        class _TermThread(QThread):
            def __init__(self_inner, iid: str, reg: str, prof: str, parent=None):
                super().__init__(parent)
                self_inner.iid = iid
                self_inner.reg = reg
                self_inner.prof = prof

            def run(self_inner):
                subprocess.call(
                    [
                        "aws",
                        "ec2",
                        "terminate-instances",
                        "--instance-ids",
                        self_inner.iid,
                        "--region",
                        self_inner.reg,
                        "--profile",
                        self_inner.prof,
                    ]
                )

        t = _TermThread(instance_id, region, profile, self)
        t.finished.connect(
            lambda: QMessageBox.information(self, "Terminate", "Termination initiated.")
        )
        t.start()

    # ------------------------------------------------------------------
    # Connect via external terminal
    # ------------------------------------------------------------------

    @Slot()
    def open_ssh_terminal(self):
        if not self.current_public_dns:
            return
        # Use the key pair selected during deployment if available
        key_file = self._resolve_key_path()
        key_arg = f"-i {shlex.quote(str(key_file))} " if key_file else ""

        cmd = f"ssh {key_arg}ec2-user@{self.current_public_dns}"

        if sys.platform.startswith("darwin"):
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'tell application "Terminal" to do script "{cmd}"',
                ]
            )
        elif sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/k", cmd])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", cmd])

    def _open_terminal_with_command(self, command: str):
        if sys.platform.startswith("darwin"):
            escaped = command.replace('"', '\\"')
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'tell application "Terminal" to do script "{escaped}"',
                ]
            )
        elif sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/k", command])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", command])

    def _enter_container_shell(self, container: str):
        key_file = self._resolve_key_path()
        if not key_file or not self.current_public_dns:
            return
        quoted_key = shlex.quote(str(key_file))
        container_cmd = (
            f"ssh -tt -i {quoted_key} -o StrictHostKeyChecking=no "
            f"ec2-user@{self.current_public_dns} "
            f"'docker exec -it {shlex.quote(container)} /bin/bash'"
        )
        self._open_terminal_with_command(container_cmd)

    # ------------------------------------------------------------------
    # Settings persistence helpers
    # ------------------------------------------------------------------

    def on_remember_toggled(self, state):
        if not self._loading_settings:
            if self.remember_check.isChecked():
                self.save_settings()
            else:
                if SETTINGS_FILE.exists():
                    try:
                        with SETTINGS_FILE.open() as fp:
                            data = json.load(fp)
                        data["remember"] = False
                        with SETTINGS_FILE.open("w") as fp:
                            json.dump(data, fp, indent=2)
                    except (OSError, json.JSONDecodeError):
                        pass

    def gather_settings(self):
        return {
            "remember": self.remember_check.isChecked(),
            "profile": self.profile_edit.text().strip(),
            "region": self.region_combo.currentText(),
            "account_id": self.account_edit.text().strip(),
            "repository": self.repo_combo.currentText(),
            "instance_type": self.instance_combo.currentText(),
            "key_pair": self.keypair_combo.currentText(),
            "security_group": self.sg_combo.currentText(),
            "volume_size": self.volume_spin.value(),
        }

    def save_settings(self):
        if self._loading_settings:
            return
        data = self.gather_settings()
        try:
            with SETTINGS_FILE.open("w") as fp:
                json.dump(data, fp, indent=2)
        except OSError as exc:
            print(f"Could not save settings: {exc}")

    def load_settings(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            with SETTINGS_FILE.open() as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return

        self.saved_settings = data
        self._loading_settings = True

        remember_flag = data.get("remember", False)
        self.remember_check.setChecked(remember_flag)

        self.profile_edit.setText(data.get("profile", self.profile_edit.text()))
        region_val = data.get("region")
        if region_val and self.region_combo.findText(region_val) != -1:
            self.region_combo.setCurrentText(region_val)
        self.account_edit.setText(data.get("account_id", ""))
        self.instance_combo.setCurrentText(
            data.get("instance_type", self.instance_combo.currentText())
        )
        self.volume_spin.setValue(
            int(data.get("volume_size", self.volume_spin.value()))
        )

        # For repository, key pair, sg values we may set after data is fetched
        for combo, key in [
            (self.repo_combo, "repository"),
            (self.keypair_combo, "key_pair"),
            (self.sg_combo, "security_group"),
        ]:
            val = data.get(key)
            if val:
                idx = combo.findText(val)
                if idx == -1:
                    combo.addItem(val)
                    idx = combo.findText(val)
                combo.setCurrentIndex(idx)

        self._loading_settings = False

    # ------------------------------------------------------------------
    # Key pair combo handler
    # ------------------------------------------------------------------

    def on_keypair_changed(self, text: str):
        if text == self.CREATE_KEY_TEXT:
            name, ok = QInputDialog.getText(
                self, "Create Key Pair", "Enter new key pair name:"
            )
            if ok and name.strip():
                name = name.strip()
                # Insert new name if not existing
                if self.keypair_combo.findText(name) == -1:
                    # Insert before sentinel (last item)
                    sentinel_index = self.keypair_combo.findText(self.CREATE_KEY_TEXT)
                    self.keypair_combo.insertItem(sentinel_index, name)
                # Select it
                idx = self.keypair_combo.findText(name)
                self.keypair_combo.setCurrentIndex(idx)
                self._prev_keypair_text = name
            else:
                # Revert to previous if cancel
                if (
                    self._prev_keypair_text
                    and self.keypair_combo.findText(self._prev_keypair_text) != -1
                ):
                    self.keypair_combo.setCurrentText(self._prev_keypair_text)
                else:
                    # fallback first item if any
                    if self.keypair_combo.count() > 1:
                        self.keypair_combo.setCurrentIndex(0)
        else:
            self._prev_keypair_text = text

    # ------------------------------------------------------------------
    # File transfer helpers
    # ------------------------------------------------------------------

    def _choose_file(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "Select file to upload")
        if path:
            self.src_edit.setText(path)

    def _populate_container_dirs(self):
        """Fill dest_combo with top-level dirs inside running container."""
        if not self.current_public_dns:
            return
        # Ensure container list is refreshed for the current instance
        self._populate_containers()

        container = self.container_combo.currentText().strip()
        # If container list is empty or selection is blank, try to pick the first available
        if not container and self.container_combo.count():
            self.container_combo.setCurrentIndex(0)
            container = self.container_combo.currentText().strip()
        if not container:
            # Fallback to legacy pattern if container detection fails
            container = (
                f"{self.profile_edit.text().strip() or 'default'}-"
                f"{self.repo_combo.currentText()}-container"
            )
        key_file = self._require_key_file()
        if not key_file:
            return
        self.dest_combo.clear()
        self.dest_combo.addItem("Loading …")
        ssh_base = [
            "ssh",
            "-i",
            str(key_file),
            "-o",
            "StrictHostKeyChecking=no",
            f"ec2-user@{self.current_public_dns}",
        ]
        container_q = shlex.quote(container)
        cmd = ssh_base + [f"docker exec {container_q} sh -c 'ls -1d /*'"]
        try:
            out = subprocess.check_output(
                cmd, text=True, stderr=subprocess.STDOUT, timeout=15
            )
            dirs: List[str] = [x for x in out.strip().split("\n") if x.startswith("/")]
            self.dest_combo.clear()
            self.dest_combo.addItems(dirs or ["/workspace"])
        except subprocess.TimeoutExpired:
            self.dest_combo.clear()
            self.dest_combo.addItem("/workspace")
            self.log_text.append(
                "Listing container directories timed out; showing /workspace only. Click Reload to retry."
            )
        except subprocess.CalledProcessError as exc:
            self.dest_combo.clear()
            self.dest_combo.addItem("/workspace")
            output = (exc.output or "").strip()
            if output:
                self.log_text.append(f"Failed to list container directories: {output}")
            else:
                self.log_text.append(
                    "Failed to list container directories; showing /workspace fallback."
                )
        except subprocess.SubprocessError as exc:
            self.dest_combo.clear()
            self.dest_combo.addItem("/workspace")
            self.log_text.append(f"Error listing container directories: {exc}")

    def _upload_file(self):
        src = self.src_edit.text().strip()
        if not src or not Path(src).exists():
            QMessageBox.warning(self, "Upload", "Select a valid source file.")
            return
        dest_dir = self.dest_combo.currentText() or "/workspace"
        key_file = self._require_key_file()
        if not key_file:
            return
        # Use the container selected in the combo box, else fall back to legacy pattern
        container = (
            self.container_combo.currentText()
            or f"{self.profile_edit.text().strip() or 'default'}-{self.repo_combo.currentText()}-container"
        )
        dns = self.current_public_dns

        filename = Path(src).name
        remote_tmp = f"/tmp/{filename}"

        dlg = QProgressDialog("Uploading …", None, 0, 100, self)
        dlg.setWindowTitle("File Upload")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setAutoClose(False)
        dlg.setLabelText("Uploading …")
        dlg.setCancelButtonText("Cancel")

        worker = FileUploadWorker(
            host=dns,
            key_path=key_file,
            local_path=Path(src),
            remote_tmp=remote_tmp,
            container=container,
            dest_dir=dest_dir,
        )

        worker.progress.connect(dlg.setValue)
        worker.stats.connect(
            lambda transferred, total, rate: self._update_transfer_label(
                dlg, "Uploading", transferred, total, rate
            )
        )
        worker.status.connect(lambda text: self._update_transfer_status(dlg, text))
        self._init_transfer_state(dlg, "Uploading …")

        def _on_cancel():
            worker.cancel()
            self._stop_transfer_state(dlg)
            dlg.close()

        def _on_done():
            QMessageBox.information(self, "Upload", "Done")
            dlg.close()
            self._reset_transfer_label(dlg, "Uploading …")
            self._stop_transfer_state(dlg)

        def _on_error(msg: str):
            if msg.strip() == "Upload cancelled.":
                QMessageBox.information(self, "Upload", "Upload cancelled.")
            else:
                QMessageBox.critical(self, "Upload", msg)
            dlg.close()
            self._reset_transfer_label(dlg, "Uploading …")
            self._stop_transfer_state(dlg)

        dlg.canceled.connect(_on_cancel)
        worker.done.connect(_on_done)
        worker.error.connect(_on_error)
        worker.start()
        dlg.exec()

    def _choose_local_dir(self):
        from PySide6.QtWidgets import QFileDialog

        dir_path = QFileDialog.getExistingDirectory(self, "Select download folder")
        if dir_path:
            self.local_dir_edit.setText(dir_path)

    def _populate_containers(self):
        """Fill container combo with running docker containers."""
        if not self.current_public_dns:
            return
        key_file = self._require_key_file()
        if not key_file:
            return
        cmd = [
            "ssh",
            "-i",
            str(key_file),
            "-o",
            "StrictHostKeyChecking=no",
            f"ec2-user@{self.current_public_dns}",
            "docker ps --format '{{.Names}}'",
        ]
        try:
            out = subprocess.check_output(cmd, text=True, timeout=10)
            names = [n for n in out.strip().split("\n") if n]
            if names:
                self.container_combo.clear()
                self.container_combo.addItems(names)
        except subprocess.SubprocessError:
            pass

    def _download_file(self):
        container = self.container_combo.currentText()
        remote_path = self.remote_edit.text().strip()
        local_dir = Path(self.local_dir_edit.text().strip())
        if not (container and remote_path and local_dir.exists()):
            QMessageBox.warning(self, "Download", "Fill all fields correctly.")
            return
        key_file = self._require_key_file()
        if not key_file:
            return
        dns = self.current_public_dns

        dlg = QProgressDialog("Downloading …", None, 0, 100, self)
        dlg.setWindowTitle("File Download")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setAutoClose(False)
        dlg.setLabelText("Downloading …")
        dlg.setCancelButtonText("Cancel")

        worker = DownloadWorker(
            host=dns,
            key_path=key_file,
            container=container,
            remote_path=remote_path,
            local_dest=local_dir,
        )

        worker.progress.connect(dlg.setValue)
        worker.stats.connect(
            lambda transferred, total, rate: self._update_transfer_label(
                dlg, "Downloading", transferred, total, rate
            )
        )
        worker.status.connect(lambda text: self._update_transfer_status(dlg, text))
        self._init_transfer_state(dlg, "Downloading …")

        def _on_cancel():
            worker.cancel()
            self._stop_transfer_state(dlg)
            dlg.close()

        def _done(path: Path):
            QMessageBox.information(self, "Download", f"Saved to {path}")
            dlg.close()
            self._reset_transfer_label(dlg, "Downloading …")
            self._stop_transfer_state(dlg)

        def _err(msg: str):
            cleaned = (msg or "").strip()
            if not cleaned:
                cleaned = (
                    "Download failed but no error message was returned. "
                    "Check the container path and your network connection, "
                    "then try again."
                )
            if cleaned == "Download cancelled.":
                QMessageBox.information(self, "Download", "Download cancelled.")
            else:
                QMessageBox.critical(self, "Download", cleaned)
            dlg.close()
            self._reset_transfer_label(dlg, "Downloading …")
            self._stop_transfer_state(dlg)

        dlg.canceled.connect(_on_cancel)
        worker.done.connect(_done)
        worker.error.connect(_err)
        worker.start()
        dlg.exec()

    def _browse_remote(self):
        container = self.container_combo.currentText()
        if not container:
            return
        key_file = self._require_key_file()
        if not key_file:
            return
        dlg = RemoteBrowserDialog(
            self.current_public_dns, key_file, container, parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            sel = dlg.selected_path()
            if sel:
                self.remote_edit.setText(sel)

    # ------------------------------------------------------------------
    # Transfer progress helpers (shared by upload/download dialogs)
    # ------------------------------------------------------------------

    def _update_transfer_label(
        self,
        dlg: QProgressDialog,
        action: str,
        transferred: int,
        total: int,
        rate: float,
    ):
        state = self._transfer_state.get(dlg)
        if state is None:
            return
        state["action"] = action
        state["bytes"] = transferred
        state["total"] = total
        state["rate"] = rate
        state["ts"] = time.monotonic()
        self._refresh_transfer_label(dlg)

    def _reset_transfer_label(self, dlg: QProgressDialog, text: str):
        dlg.setLabelText(text)

    def _update_transfer_status(self, dlg: QProgressDialog, status: str):
        state = self._transfer_state.get(dlg)
        if state is None:
            return
        state["status"] = status
        state["ts"] = time.monotonic()
        self._refresh_transfer_label(dlg)

    def _refresh_transfer_label(self, dlg: QProgressDialog):
        state = self._transfer_state.get(dlg)
        if state is None:
            return
        action = state.get("action", "Transferring")
        transferred = int(state.get("bytes", 0))
        total = int(state.get("total", 0))
        rate = float(state.get("rate", 0.0))
        status = state.get("status", "")
        base = compose_transfer_label(action, transferred, total, rate)
        if status:
            base = f"{base}\n{status}"
        stale = state.get("stale_hint")
        if stale:
            base = f"{base}\n{stale}"
        dlg.setLabelText(base)

    def _init_transfer_state(self, dlg: QProgressDialog, action: str):
        self._transfer_state[dlg] = {
            "action": action,
            "bytes": 0,
            "total": 0,
            "rate": 0.0,
            "status": "Preparing transfer…",
            "ts": time.monotonic(),
            "stale_hint": "",
        }
        if not self._transfer_timer.isActive():
            self._transfer_timer.start()

    def _stop_transfer_state(self, dlg: QProgressDialog):
        self._transfer_state.pop(dlg, None)
        if not self._transfer_state and self._transfer_timer.isActive():
            self._transfer_timer.stop()

    def _tick_transfer_watchdog(self):
        now = time.monotonic()
        for dlg, state in list(self._transfer_state.items()):
            # If no updates for 15s, show a hint to the user
            idle = now - state.get("ts", now)
            if idle > 15:
                state["stale_hint"] = "No data for a few seconds… still working."
            elif state.get("stale_hint"):
                state["stale_hint"] = ""
            self._refresh_transfer_label(dlg)

    # ------------------------------------------------------------------
    # Prereq checks (aws CLI)
    # ------------------------------------------------------------------

    def _check_prereqs(self):
        if self._find_aws_cli():
            return
        QMessageBox.warning(
            self,
            "AWS CLI required",
            "AWS CLI v2 was not found in your PATH.\n"
            "Please install AWS CLI v2 from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html\n"
            "Then restart the app.",
        )

    def _augment_path(self):
        """Ensure common install locations for aws CLI are on PATH."""
        home = Path.home()
        extras = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/local/aws-cli/v2/current/bin",
            str(home / "miniconda3/bin"),
            str(home / "anaconda3/bin"),
        ]
        cur = os.environ.get("PATH", "")
        parts = cur.split(os.pathsep) if cur else []
        for p in extras:
            if p not in parts:
                parts.insert(0, p)
        os.environ["PATH"] = os.pathsep.join(parts)

    def _find_aws_cli(self) -> str | None:
        # Common install locations (Homebrew, system, AWS CLI v2 bundle, conda)
        home = Path.home()
        candidates = [
            shutil.which("aws"),
            "/opt/homebrew/bin/aws",
            "/usr/local/bin/aws",
            "/usr/bin/aws",
            "/usr/local/aws-cli/v2/current/bin/aws",
            str(home / "miniconda3/bin/aws"),
            str(home / "anaconda3/bin/aws"),
        ]
        for path in candidates:
            if path and Path(path).exists():
                return path
        # Fallback: ask a login shell (zsh then bash) which may pick up user PATH/conda
        for shell in ("/bin/zsh", "/bin/bash"):
            try:
                out = subprocess.check_output(
                    [shell, "-lc", "command -v aws"], text=True, timeout=3
                ).strip()
                if out and Path(out).exists():
                    return out
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _version_tuple(self, ver: str):
        return tuple(int(x) for x in ver.strip().split(".") if x.isdigit())

    def _check_for_update(self):
        if not UPDATE_VERSION_URL:
            return
        try:
            with urlopen(UPDATE_VERSION_URL, timeout=3) as resp:
                remote_ver = resp.read().decode().strip()
        except Exception:
            return
        if not remote_ver:
            return
        try:
            if self._version_tuple(remote_ver) <= self._version_tuple(APP_VERSION):
                return
        except Exception:
            return
        # Emit signal to show dialog on main thread (thread-safe)
        if UPDATE_DOWNLOAD_URL:
            self._update_available.emit(remote_ver, UPDATE_DOWNLOAD_URL)

    @Slot(str, str)
    def _on_update_available(self, remote_ver: str, download_url: str):
        """Handle update notification on the main thread (slot for _update_available signal)."""
        reply = QMessageBox.information(
            self,
            "Update available",
            f"A new version ({remote_ver}) is available. Download now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            webbrowser.open(download_url)

    # ------------------------------------------------------------------
    # AWS SSO session status helpers
    # ------------------------------------------------------------------

    def _set_sso_indicator(self, ok: bool):
        color = "#2ecc71" if ok else "#e74c3c"  # green / red
        self.sso_status_lbl.setStyleSheet(
            f"background-color:{color}; border-radius:6px;"
        )

    def _update_sso_status(self):
        """Ping sts get-caller-identity to see if credentials are valid."""
        profile = self.profile_edit.text().strip() or "default"
        try:
            subprocess.check_output(
                [
                    "aws",
                    "sts",
                    "get-caller-identity",
                    "--profile",
                    profile,
                ],
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            self._set_sso_indicator(True)
        except (subprocess.SubprocessError, FileNotFoundError):
            self._set_sso_indicator(False)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
