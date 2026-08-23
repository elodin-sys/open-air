"""Local-only Design Studio server with validated concept saves."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from openair.designer.generator import build_design_studio
from openair.geometry.openvsp_model import (
    VSP_LOCK,
    _drain_vsp_errors,
    _try_import_vsp,
    write_vsp3,
)
from openair.geometry.vsp_import import (
    ImportRejected,
    geometry_changes,
    import_vsp3,
)
from openair.io import load_yaml
from openair.paths import DESIGNS_DIR, OPENVSP_DIR, configure_runtime
from openair.schemas import VehicleSpec

CONCEPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SKETCH_RE = re.compile(r"^sketch-(top|side|front)(-rectified)?\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_BRIEF_BYTES = 2 * 1024 * 1024


class WorkspaceError(ValueError):
    """Invalid workspace input or save payload."""


class WorkspaceConflict(WorkspaceError):
    """The requested workspace state conflicts with the filesystem."""


def concept_name(value: str | Path) -> str:
    """Validate a bare name or canonical ``designs/<name>`` argument."""
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise WorkspaceError("concept must stay inside designs/")
    parts = tuple(part for part in raw.parts if part not in {"", "."})
    if len(parts) == 1:
        name = parts[0]
    elif len(parts) == 2 and parts[0] == "designs":
        name = parts[1]
    else:
        raise WorkspaceError("concept must be a bare name or designs/<name>")
    if not CONCEPT_RE.fullmatch(name):
        raise WorkspaceError(
            "concept names must start with a letter or number and contain only "
            "letters, numbers, '.', '_' or '-'"
        )
    return name


def _decode_png(encoded: str, name: str) -> bytes:
    if encoded.startswith("data:"):
        try:
            header, encoded = encoded.split(",", 1)
        except ValueError as exc:
            raise WorkspaceError(f"{name}: invalid data URI") from exc
        if header != "data:image/png;base64":
            raise WorkspaceError(f"{name}: expected a PNG data URI")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WorkspaceError(f"{name}: invalid base64") from exc
    if not raw.startswith(PNG_SIGNATURE):
        raise WorkspaceError(f"{name}: decoded file is not a PNG")
    return raw


def _write_design_var_file(vsp3: Path, des_path: Path) -> list[str]:
    """Best-effort OpenVSP design-variable whitelist for the GUI session."""
    warnings: list[str] = []
    vsp = _try_import_vsp()
    if vsp is None:
        return ["OpenVSP Python API unavailable; .des file not written"]
    with VSP_LOCK:
        try:
            _drain_vsp_errors(vsp)
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(vsp3))
            vsp.Update()
            geoms = {str(vsp.GetGeomName(gid)): gid for gid in vsp.FindGeoms()}
            wing = geoms.get("wing")
            if not wing:
                return ["wing geom missing; .des file not written"]
            vsp.DeleteAllDesignVars()
            for name, group in (
                ("TotalSpan", "WingGeom"),
                ("Root_Chord", "XSec_1"),
                ("Sweep", "XSec_1"),
                ("X_Rel_Location", "XForm"),
            ):
                parm_id = vsp.GetParm(wing, name, group)
                if parm_id:
                    vsp.AddDesignVar(parm_id, vsp.XDDM_VAR)
                else:
                    warnings.append(f"design variable not found: wing.{group}.{name}")
            vsp.WriteDESFile(str(des_path))
            warnings.extend(_drain_vsp_errors(vsp))
            if not des_path.is_file():
                warnings.append("OpenVSP did not write the .des file")
        except Exception as exc:
            warnings.append(f"could not write .des whitelist: {exc}")
    return warnings


def launch_vsp_gui(vsp3: Path, des_path: Path | None = None) -> subprocess.Popen:
    """Launch the installed OpenVSP GUI against a session model."""
    configure_runtime()
    binary = OPENVSP_DIR / "vsp"
    if not binary.is_file():
        raise WorkspaceError(f"OpenVSP GUI binary is missing: {binary}")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise WorkspaceError(
            "OpenVSP GUI needs DISPLAY or WAYLAND_DISPLAY; run the designer "
            "from a graphical desktop session"
        )
    try:
        command = [str(binary), str(vsp3)]
        if des_path is not None and des_path.is_file():
            command.extend(["-des", str(des_path)])
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except OSError as exc:
        raise WorkspaceError(f"could not launch OpenVSP GUI: {exc}") from exc


def _merged_geometry_spec(
    seed: VehicleSpec,
    geometry: dict[str, Any],
) -> VehicleSpec:
    data = seed.model_dump(mode="python", exclude_computed_fields=True)
    for key, fields in geometry.items():
        data[key].update(fields)
    return VehicleSpec.model_validate(data)


@dataclass
class VspSession:
    """One temporary OpenVSP GUI process watched for representable saves."""

    seed_spec: VehicleSpec
    attachment_spec: VehicleSpec
    directory: Path
    vsp3_path: Path
    des_path: Path
    process: Any
    last_seen_stamp: tuple[int, int]
    last_applied_stamp: tuple[int, int]
    stable_since: float
    warnings: list[str] = field(default_factory=list)
    rejected_stamp: tuple[int, int] | None = None
    rejection_reasons: list[str] = field(default_factory=list)
    stable_delay_s: float = 0.25

    @classmethod
    def start(cls, spec: VehicleSpec) -> VspSession:
        directory = Path(tempfile.mkdtemp(prefix="openair-vsp-session-"))
        vsp3 = directory / f"{spec.name}.vsp3"
        des = directory / f"{spec.name}.des"
        try:
            write_result = write_vsp3(spec, vsp3)
            if not write_result.get("ok"):
                detail = "; ".join(write_result.get("errors") or [])
                reason = write_result.get("reason") or detail or "unknown error"
                raise WorkspaceError(f"could not build OpenVSP session: {reason}")
            warnings = _write_design_var_file(vsp3, des)
            stamp = cls._stamp(vsp3)
            if stamp is None:
                raise WorkspaceError("OpenVSP session file was not written")
            process = launch_vsp_gui(vsp3, des)
            now = time.monotonic()
            return cls(
                seed_spec=spec.model_copy(deep=True),
                attachment_spec=spec.model_copy(deep=True),
                directory=directory,
                vsp3_path=vsp3,
                des_path=des,
                process=process,
                last_seen_stamp=stamp,
                last_applied_stamp=stamp,
                stable_since=now,
                warnings=warnings,
            )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def status(self) -> dict[str, Any]:
        running = self.process.poll() is None
        stamp = self._stamp(self.vsp3_path)
        now = time.monotonic()
        if stamp is None:
            if running:
                return {
                    "ok": True,
                    "running": True,
                    "pending": True,
                    "changed": False,
                    "message": "OpenVSP is replacing the session file…",
                }
            return {
                "ok": False,
                "running": False,
                "pending": False,
                "changed": False,
                "rejected": ["OpenVSP session file disappeared"],
            }
        if stamp != self.last_seen_stamp:
            self.last_seen_stamp = stamp
            self.stable_since = now
            self.rejected_stamp = None
            self.rejection_reasons = []

        pending = (
            stamp != self.last_applied_stamp
            and stamp != self.rejected_stamp
            and now - self.stable_since < self.stable_delay_s
        )
        result: dict[str, Any] = {
            "ok": True,
            "running": running,
            "pending": pending,
            "changed": False,
        }
        if pending:
            result["message"] = "OpenVSP save detected; waiting for it to settle…"
            return result

        if stamp != self.last_applied_stamp and stamp != self.rejected_stamp:
            try:
                geometry = import_vsp3(
                    self.vsp3_path,
                    self.seed_spec,
                    attachment_spec=self.attachment_spec,
                )
                changes = geometry_changes(self.seed_spec, geometry)
                self.seed_spec = _merged_geometry_spec(self.seed_spec, geometry)
                self.last_applied_stamp = stamp
                result.update(
                    changed=True,
                    geometry=geometry,
                    changes=changes,
                    message=(
                        f"Imported {len(changes)} OpenVSP geometry change(s)."
                        if changes
                        else "OpenVSP saved; geometry is unchanged."
                    ),
                )
            except ImportRejected as exc:
                self.rejected_stamp = stamp
                self.rejection_reasons = exc.reasons
                result.update(
                    ok=False,
                    rejected=exc.reasons,
                    message="OpenVSP save is outside the supported geometry subset.",
                )
            except Exception as exc:
                self.rejected_stamp = stamp
                self.rejection_reasons = [f"OpenVSP import failed: {exc}"]
                result.update(
                    ok=False,
                    rejected=self.rejection_reasons,
                    message="OpenVSP save could not be imported.",
                )
        elif stamp == self.rejected_stamp:
            result.update(
                ok=False,
                rejected=self.rejection_reasons,
                message="Save again in OpenVSP after correcting the rejected edit.",
            )
        elif running:
            result["message"] = "OpenVSP session active — save in the GUI to sync."
        else:
            result["message"] = "OpenVSP session ended with no new changes."
        return result

    def cleanup(self, *, terminate: bool = False) -> None:
        if terminate and self.process.poll() is None:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            except ProcessLookupError:
                pass
        shutil.rmtree(self.directory, ignore_errors=True)


@dataclass
class ConceptWorkspace:
    """One constrained authoring session for a source concept."""

    name: str
    designs_dir: Path
    spec: VehicleSpec
    brief_md: str
    mode: str
    save_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    saved_once: bool = False
    vsp_session: VspSession | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def target(self) -> Path:
        return self.designs_dir / self.name

    @classmethod
    def new(
        cls,
        value: str | Path,
        *,
        designs_dir: Path | None = None,
        template_dir: Path | None = None,
    ) -> ConceptWorkspace:
        name = concept_name(value)
        root = Path(designs_dir or DESIGNS_DIR).resolve()
        template = Path(template_dir or (DESIGNS_DIR / "_template")).resolve()
        target = root / name
        if target.exists():
            raise WorkspaceConflict(
                f"Concept already exists: {target}. Use 'edit {name}' instead."
            )
        data = load_yaml(template / "design.yaml")
        data["name"] = name
        spec = VehicleSpec.model_validate(data)
        brief = (template / "brief.md").read_text(encoding="utf-8")
        return cls(
            name=name,
            designs_dir=root,
            spec=spec,
            brief_md=brief,
            mode="new",
        )

    @classmethod
    def edit(
        cls,
        value: str | Path,
        *,
        designs_dir: Path | None = None,
    ) -> ConceptWorkspace:
        name = concept_name(value)
        root = Path(designs_dir or DESIGNS_DIR).resolve()
        target = root / name
        design_yaml = target / "design.yaml"
        if not design_yaml.is_file():
            raise FileNotFoundError(
                f"Concept not found: {target}. Use 'new {name}' first."
            )
        spec = VehicleSpec.model_validate(load_yaml(design_yaml))
        brief_path = target / "brief.md"
        brief = (
            brief_path.read_text(encoding="utf-8")
            if brief_path.is_file()
            else "# Concept brief\n"
        )
        return cls(
            name=name,
            designs_dir=root,
            spec=spec,
            brief_md=brief,
            mode="edit",
            saved_once=True,
        )

    def html(self) -> str:
        return build_design_studio(
            self.spec,
            concept=self.name,
            source_name="design.yaml",
            mode=self.mode,
            brief_md=self.brief_md,
            save_token=self.save_token,
        )

    def _validate_payload(
        self,
        payload: Any,
    ) -> tuple[str, str, dict[str, bytes], VehicleSpec]:
        if not isinstance(payload, dict):
            raise WorkspaceError("save payload must be a JSON object")
        design_yaml = payload.get("design_yaml")
        brief_md = payload.get("brief_md")
        sketches = payload.get("sketches", [])
        if not isinstance(design_yaml, str):
            raise WorkspaceError("design_yaml must be a string")
        if not isinstance(brief_md, str):
            raise WorkspaceError("brief_md must be a string")
        if len(brief_md.encode("utf-8")) > MAX_BRIEF_BYTES:
            raise WorkspaceError("brief_md exceeds 2 MiB")
        if not isinstance(sketches, list):
            raise WorkspaceError("sketches must be a list")
        spec = self._validate_design_yaml(design_yaml)

        decoded: dict[str, bytes] = {}
        for item in sketches:
            if not isinstance(item, dict):
                raise WorkspaceError("each sketch must be an object")
            name = item.get("name")
            encoded = item.get("png_base64")
            if not isinstance(name, str) or not SKETCH_RE.fullmatch(name):
                raise WorkspaceError(f"sketch filename is not allowed: {name!r}")
            if name in decoded:
                raise WorkspaceError(f"duplicate sketch filename: {name}")
            if not isinstance(encoded, str):
                raise WorkspaceError(f"{name}: png_base64 must be a string")
            decoded[name] = _decode_png(encoded, name)
        return design_yaml, brief_md, decoded, spec

    def _validate_design_yaml(self, design_yaml: Any) -> VehicleSpec:
        if not isinstance(design_yaml, str):
            raise WorkspaceError("design_yaml must be a string")
        try:
            data = yaml.safe_load(design_yaml)
            if not isinstance(data, dict):
                raise WorkspaceError("design_yaml must contain a mapping")
            spec = VehicleSpec.model_validate(data)
        except (yaml.YAMLError, ValidationError) as exc:
            raise WorkspaceError(f"design.yaml validation failed: {exc}") from exc
        if spec.name != self.name:
            raise WorkspaceError(
                f"design name {spec.name!r} must match concept {self.name!r}"
            )
        return spec

    def open_vsp(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise WorkspaceError("OpenVSP payload must be a JSON object")
        spec = self._validate_design_yaml(payload.get("design_yaml"))
        with self._lock:
            if self.vsp_session is not None:
                raise WorkspaceConflict("an OpenVSP GUI session is already open")
            session = VspSession.start(spec)
            self.vsp_session = session
            return {
                "ok": True,
                "running": True,
                "vsp3": str(session.vsp3_path),
                "des": str(session.des_path) if session.des_path.is_file() else None,
                "warnings": session.warnings,
                "message": "OpenVSP opened. Save in the GUI to sync geometry.",
            }

    def vsp_status(self) -> dict[str, Any]:
        with self._lock:
            if self.vsp_session is None:
                return {
                    "ok": True,
                    "running": False,
                    "pending": False,
                    "changed": False,
                    "message": "No OpenVSP session is active.",
                }
            result = self.vsp_session.status()
            if not result.get("running") and not result.get("pending"):
                self.vsp_session.cleanup()
                self.vsp_session = None
            return result

    def close_vsp(self) -> None:
        with self._lock:
            if self.vsp_session is not None:
                self.vsp_session.cleanup(terminate=True)
                self.vsp_session = None

    def save(self, payload: Any) -> dict[str, Any]:
        """Validate and atomically publish one concept workspace."""
        design_yaml, brief_md, sketches, spec = self._validate_payload(payload)
        with self._lock:
            target = self.target
            if self.mode == "new" and not self.saved_once and target.exists():
                raise WorkspaceConflict(
                    f"Concept appeared while editing: {target}; refusing to overwrite."
                )
            if self.mode == "edit" and not target.is_dir():
                raise WorkspaceConflict(f"Concept was removed while editing: {target}")

            self.designs_dir.mkdir(parents=True, exist_ok=True)
            stage = Path(
                tempfile.mkdtemp(
                    prefix=f".{self.name}-studio-",
                    dir=self.designs_dir,
                )
            )
            backup: Path | None = None
            try:
                if target.is_dir():
                    shutil.copytree(target, stage, dirs_exist_ok=True)
                (stage / "design.yaml").write_text(design_yaml, encoding="utf-8")
                (stage / "brief.md").write_text(brief_md, encoding="utf-8")
                for name, raw in sketches.items():
                    (stage / name).write_bytes(raw)

                if target.exists():
                    backup = self.designs_dir / (
                        f".{self.name}-backup-{secrets.token_hex(8)}"
                    )
                    os.replace(target, backup)
                try:
                    os.replace(stage, target)
                except Exception:
                    if backup is not None and backup.exists() and not target.exists():
                        os.replace(backup, target)
                    raise
                if backup is not None:
                    shutil.rmtree(backup, ignore_errors=True)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

            self.spec = spec
            self.brief_md = brief_md
            self.saved_once = True
            written = ["design.yaml", "brief.md", *sorted(sketches)]
            return {
                "ok": True,
                "concept": self.name,
                "directory": str(target),
                "written": written,
                "next": f"/create-aero designs/{self.name}",
            }


class StudioHTTPServer(ThreadingHTTPServer):
    workspace: ConceptWorkspace


class StudioRequestHandler(BaseHTTPRequestHandler):
    server: StudioHTTPServer

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/vsp/status":
            if self.headers.get("X-Openair-Token") != self.server.workspace.save_token:
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"ok": False, "error": "invalid save token"},
                )
                return
            try:
                result = self.server.workspace.vsp_status()
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"OpenVSP status failed: {exc}"},
                )
                return
            self._json(HTTPStatus.OK, result)
            return
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        raw = self.server.workspace.html().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/api/save", "/api/vsp/open"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("X-Openair-Token") != self.server.workspace.save_token:
            self._json(
                HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid save token"}
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type != "application/json":
            self._json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"ok": False, "error": "Content-Type must be application/json"},
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "save request exceeds 64 MiB"},
            )
            return
        try:
            payload = json.loads(self.rfile.read(length))
            result = (
                self.server.workspace.open_vsp(payload)
                if self.path == "/api/vsp/open"
                else self.server.workspace.save(payload)
            )
        except WorkspaceConflict as exc:
            self._json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc)})
            return
        except (WorkspaceError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            action = "OpenVSP launch" if self.path == "/api/vsp/open" else "save"
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": f"{action} failed: {exc}"},
            )
            return
        if self.path == "/api/save":
            print(
                f"saved {result['directory']}\nnext: {result['next']}",
                flush=True,
            )
        else:
            print(f"opened OpenVSP: {result['vsp3']}", flush=True)
        self._json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def make_server(
    workspace: ConceptWorkspace,
    *,
    port: int = 0,
) -> StudioHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    server = StudioHTTPServer(("127.0.0.1", port), StudioRequestHandler)
    server.workspace = workspace
    return server


def serve_workspace(
    workspace: ConceptWorkspace,
    *,
    port: int = 0,
    open_browser: bool = False,
) -> None:
    server = make_server(workspace, port=port)
    host, actual_port = server.server_address
    url = f"http://{host}:{actual_port}/"
    print(f"Design Studio: {url}", flush=True)
    print(
        f"Save writes designs/{workspace.name}/; press Ctrl-C to stop.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nDesign Studio stopped.", flush=True)
    finally:
        workspace.close_vsp()
        server.server_close()
