"""Runtime protobuf loading for ZMK Studio RPC."""

from __future__ import annotations

import hashlib
import importlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from types import ModuleType
from typing import Iterable

from google.protobuf.message import Message


DEFAULT_WORKSPACE = pathlib.Path(".work/zmk-keyboard-abyss-tester-xiao")
STANDARD_PROTO_REL = pathlib.Path("dependencies/modules/msgs/zmk-studio-messages/proto/zmk")


class ProtoError(RuntimeError):
    pass


def _stable_hash(paths: Iterable[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _compile_proto(
    *,
    proto_files: list[pathlib.Path],
    include_dirs: list[pathlib.Path],
    out_dir: pathlib.Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        *[f"-I{include_dir}" for include_dir in include_dirs],
        f"--python_out={out_dir}",
        *[str(path) for path in proto_files],
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return

    protoc = shutil.which("protoc")
    if not protoc:
        raise ProtoError(result.stderr.strip() or "grpc_tools.protoc failed and protoc was not found")

    fallback = [
        protoc,
        *[f"-I{include_dir}" for include_dir in include_dirs],
        f"--python_out={out_dir}",
        *[str(path) for path in proto_files],
    ]
    fallback_result = subprocess.run(fallback, text=True, capture_output=True, check=False)
    if fallback_result.returncode != 0:
        raise ProtoError(
            fallback_result.stderr.strip()
            or result.stderr.strip()
            or "protobuf generation failed"
        )


def _module_name_for(proto_file: pathlib.Path, include_dir: pathlib.Path) -> str:
    rel = proto_file.relative_to(include_dir).with_suffix("")
    return ".".join((*rel.parts[:-1], f"{rel.name}_pb2"))


@dataclass
class GeneratedProtoSet:
    include_dir: pathlib.Path
    proto_files: list[pathlib.Path]
    out_dir: pathlib.Path
    modules: dict[str, ModuleType] = field(default_factory=dict)

    def load(self) -> "GeneratedProtoSet":
        if str(self.out_dir) not in sys.path:
            sys.path.insert(0, str(self.out_dir))
        importlib.invalidate_caches()
        for proto_file in self.proto_files:
            name = _module_name_for(proto_file, self.include_dir)
            self.modules[name] = importlib.import_module(name)
        return self

    def module(self, name: str) -> ModuleType:
        try:
            return self.modules[name]
        except KeyError as exc:
            raise ProtoError(f"Generated proto module is not loaded: {name}") from exc


def compile_proto_set(
    proto_files: list[pathlib.Path],
    *,
    include_dir: pathlib.Path,
    extra_include_dirs: Iterable[pathlib.Path] = (),
    cache_base: pathlib.Path | None = None,
) -> GeneratedProtoSet:
    proto_files = [path.resolve() for path in proto_files]
    include_dir = include_dir.resolve()
    include_dirs = [include_dir, *[path.resolve() for path in extra_include_dirs]]
    cache_base = cache_base or pathlib.Path(tempfile.gettempdir()) / "zmk-studio-rpc-proto"
    cache_key = _stable_hash(proto_files)
    out_dir = cache_base / cache_key

    sentinel = out_dir / ".complete"
    if not sentinel.exists():
        if out_dir.exists():
            shutil.rmtree(out_dir)
        _compile_proto(proto_files=proto_files, include_dirs=include_dirs, out_dir=out_dir)
        sentinel.write_text("ok\n")

    return GeneratedProtoSet(include_dir=include_dir, proto_files=proto_files, out_dir=out_dir).load()


def find_standard_proto_dir(workspace: pathlib.Path | str = DEFAULT_WORKSPACE) -> pathlib.Path:
    workspace_path = pathlib.Path(workspace)
    candidates = [
        workspace_path / STANDARD_PROTO_REL,
        pathlib.Path(STANDARD_PROTO_REL),
    ]
    for candidate in candidates:
        if (candidate / "studio.proto").exists():
            return candidate.resolve()

    for root in [workspace_path, pathlib.Path(".")]:
        for candidate in root.glob("**/zmk-studio-messages/proto/zmk"):
            if (candidate / "studio.proto").exists():
                return candidate.resolve()
    raise ProtoError("Could not find zmk-studio-messages/proto/zmk")


def find_proto_file(workspace: pathlib.Path | str, suffix: str) -> pathlib.Path:
    workspace_path = pathlib.Path(workspace)
    matches = list(workspace_path.glob(f"**/{suffix}"))
    if not matches:
        raise ProtoError(f"Could not find proto file matching {suffix!r} below {workspace_path}")
    if len(matches) > 1:
        matches.sort(key=lambda path: len(path.parts))
    return matches[0].resolve()


@dataclass
class ProtoBundle:
    """Loaded official ZMK Studio protobufs plus optional custom protobuf sets."""

    standard: GeneratedProtoSet
    custom_sets: list[GeneratedProtoSet] = field(default_factory=list)

    @classmethod
    def from_workspace(
        cls,
        workspace: pathlib.Path | str = DEFAULT_WORKSPACE,
        *,
        custom_proto_files: Iterable[pathlib.Path | str] = (),
    ) -> "ProtoBundle":
        standard_dir = find_standard_proto_dir(workspace)
        standard_files = [
            standard_dir / name
            for name in ("meta.proto", "core.proto", "behaviors.proto", "keymap.proto", "custom.proto", "studio.proto")
        ]
        standard = compile_proto_set(standard_files, include_dir=standard_dir)

        custom_sets: list[GeneratedProtoSet] = []
        for proto_file in custom_proto_files:
            path = pathlib.Path(proto_file).resolve()
            include_dir = _guess_custom_include_dir(path)
            custom_sets.append(compile_proto_set([path], include_dir=include_dir))

        return cls(standard=standard, custom_sets=custom_sets)

    @property
    def studio(self) -> ModuleType:
        return self.standard.module("studio_pb2")

    @property
    def core(self) -> ModuleType:
        return self.standard.module("core_pb2")

    @property
    def keymap(self) -> ModuleType:
        return self.standard.module("keymap_pb2")

    @property
    def custom(self) -> ModuleType:
        return self.standard.module("custom_pb2")

    @property
    def meta(self) -> ModuleType:
        return self.standard.module("meta_pb2")

    def load_custom_proto(self, proto_file: pathlib.Path | str) -> GeneratedProtoSet:
        path = pathlib.Path(proto_file).resolve()
        proto_set = compile_proto_set([path], include_dir=_guess_custom_include_dir(path))
        self.custom_sets.append(proto_set)
        return proto_set

    def message_class(self, dotted_name: str) -> type[Message]:
        package, _, message_name = dotted_name.rpartition(".")
        if not package:
            raise ProtoError(f"Message name must include a protobuf package: {dotted_name}")

        candidates = [proto_set.modules for proto_set in self.custom_sets]
        candidates.append(self.standard.modules)

        for modules in candidates:
            for module in modules.values():
                descriptor = getattr(module, "DESCRIPTOR", None)
                if descriptor and descriptor.package == package and hasattr(module, message_name):
                    return getattr(module, message_name)

        module_name = package.replace(".", os.sep).replace(os.sep, ".") + "_pb2"
        for modules in candidates:
            module = modules.get(module_name)
            if module and hasattr(module, message_name):
                return getattr(module, message_name)

        # Some official files are compiled without a zmk/ Python package because upstream imports
        # use sibling names such as "core.proto".
        short_module_name = package.split(".")[-1] + "_pb2"
        for modules in candidates:
            module = modules.get(short_module_name)
            if module and hasattr(module, message_name):
                return getattr(module, message_name)

        raise ProtoError(f"Could not find generated message class: {dotted_name}")


def _guess_custom_include_dir(proto_file: pathlib.Path) -> pathlib.Path:
    parts = proto_file.parts
    if "proto" in parts:
        index = len(parts) - 1 - list(reversed(parts)).index("proto")
        return pathlib.Path(*parts[: index + 1])
    return proto_file.parent
