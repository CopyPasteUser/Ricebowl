#!/usr/bin/python3
"""CI-only repair of the pinned generic portal's invalid PipeWire remote FD.

Only a disposable PipeWire daemon is reachable from this private runtime.
This fixture intentionally does NOT test the real portal's per-node grants,
sandbox isolation or user consent and MUST NOT be shipped as a runtime patch.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

START = "    fn create_remote_fd("
END = "    /// Create a new video source stream."
REQUIRES = ("UnixStream::pair()", ".connect_fd(server_fd, None)", "Ok(client_fd)")
REPLACEMENT = r"""    fn create_remote_fd(
        _context: &pipewire::context::ContextBox<'_>,
    ) -> Result<OwnedFd, PortalError> {
        use std::os::unix::fs::{FileTypeExt, PermissionsExt};
        use std::os::unix::net::UnixStream;
        use std::path::PathBuf;

        // CI fixture ONLY. No production PipeWire grants, consent or sandbox
        // semantics are provided by this direct private-daemon socket.
        if std::env::var("RICEBOWL_PORTAL_STRICT_CI").ok().as_deref() != Some("1")
            || std::env::var("RICEBOWL_PORTAL_BACKEND").ok().as_deref() != Some("generic")
        {
            return Err(PortalError::PipeWire("CI-only remote cannot run outside strict generic test".into()));
        }
        let runtime = PathBuf::from(std::env::var_os("XDG_RUNTIME_DIR")
            .ok_or_else(|| PortalError::PipeWire("missing private CI runtime".into()))?);
        let meta = runtime.symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("CI runtime not accessible: {e}")))?;
        if !runtime.is_absolute() || !meta.is_dir() || meta.file_type().is_symlink()
            || meta.permissions().mode() & 0o077 != 0
        {
            return Err(PortalError::PipeWire("CI runtime is not a private directory".into()));
        }
        let marker = runtime.join(".ricebowl-portal-ci").symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("CI marker missing: {e}")))?;
        if !marker.is_file() || marker.file_type().is_symlink() {
            return Err(PortalError::PipeWire("invalid CI-only session marker".into()));
        }
        let socket_path = runtime.join("pipewire-0");
        let socket_type = socket_path.symlink_metadata()
            .map_err(|e| PortalError::PipeWire(format!("private CI PipeWire socket missing: {e}")))?;
        if !socket_type.file_type().is_socket() {
            return Err(PortalError::PipeWire("private CI PipeWire path is not a socket".into()));
        }
        let socket = UnixStream::connect(&socket_path)
            .map_err(|e| PortalError::PipeWire(format!("private CI PipeWire connect failed: {e}")))?;
        eprintln!("PORTAL_CI_REMOTE_UNRESTRICTED: private test daemon only");
        Ok(socket.into())
    }

"""


def patch_source(source: str) -> str:
    """Replace only the known-broken socketpair implementation; fail closed."""
    if source.count(START) != 1:
        raise ValueError("unsupported pinned upstream source structure")
    begin = source.index(START)
    if source.count(END, begin) != 1:
        raise ValueError("unexpected source structure following remote FD function")
    end = source.index(END, begin)
    old = source[begin:end]
    if any(marker not in old for marker in REQUIRES):
        raise ValueError("upstream PipeWire remote implementation changed")
    return source[:begin] + REPLACEMENT + source[end:]


# The pinned backend has no add_buffer handler and may not advertise that it
# allocates buffers. PipeWire's ALLOC_BUFFERS flag means the *application*
# must allocate data in an add_buffer callback; that callback is absent.
STREAM_FLAGS = "StreamFlags::MAP_BUFFERS | StreamFlags::ALLOC_BUFFERS | StreamFlags::DRIVER"


def patch_stream_buffers(source: str) -> str:
    """Fix pinned upstream's real PipeWire format/buffer negotiation, CI only."""
    # Keep the source pin strict: fail if upstream already has a listener or
    # if any insertion anchor is absent/duplicated. Never ship this patch.
    anchors = (
        STREAM_FLAGS,
        "    stream: StreamBox<'static>,",
        "        // Connect as an output (we produce frames).",
        "        Ok(Self { stream, node_id })",
        "    /// Get the PipeWire node ID for this stream.",
        "pub fn queue_frame(",
    )
    if any(source.count(anchor) != 1 for anchor in anchors) or (
        ".param_changed(" in source or "ci_negotiate_video_buffers" in source
    ):
        raise ValueError("unsupported pinned upstream video buffer layout")
    source = source.replace(
        STREAM_FLAGS, "StreamFlags::MAP_BUFFERS | StreamFlags::DRIVER")
    source = source.replace(
        "    stream: StreamBox<'static>,",
        "    // Drop listener before the stream: it holds a callback on that stream.\n"
        "    ci_listener: pipewire::stream::StreamListener<()>,\n"
        "    stream: StreamBox<'static>,",
    )
    source = source.replace(
        "        // Connect as an output (we produce frames).",
        "        // The backend must acknowledge SPA_PARAM_Format with an explicit\n"
        "        // SPA_PARAM_Buffers proposal; otherwise MemFd buffers are absent.\n"
        "        let width = config.width;\n"
        "        let height = config.height;\n"
        "        let ci_listener = stream.add_local_listener::<()>()\n"
        "            .param_changed(move |stream, _, id, param| {\n"
        "                if id == libspa::sys::SPA_PARAM_Format && param.is_some() {\n"
        "                    Self::ci_negotiate_video_buffers(stream, width, height);\n"
        "                }\n"
        "            })\n"
        "            .register()\n"
        "            .map_err(|e| PortalError::PipeWire(format!(\"CI buffer callback failed: {e}\")))?;\n\n"
        "        // Connect as an output (we produce frames).",
    )
    source = source.replace(
        "        Ok(Self { stream, node_id })",
        "        Ok(Self { ci_listener, stream, node_id })",
    )
    source = source.replace(
        "    /// Get the PipeWire node ID for this stream.",
        "    /// CI-only: negotiate one actual MemFd-backed CPU video data block.\n    /// This backend's pinned upstream lacks the required param_changed event.\n    #[expect(unsafe_code, reason = \"Convert a checked SPA PodSerializer buffer to libspa Pod\")]\n    #[expect(clippy::cast_ptr_alignment, reason = \"PodSerializer produces SPA-aligned records\")]\n    fn ci_negotiate_video_buffers(stream: &pipewire::stream::Stream, width: u32, height: u32) {\n        use libspa::pod::{self, Value, serialize::PodSerializer};\n        let Some(stride) = width.checked_mul(4) else {\n            eprintln!(\"PORTAL_CI_BUFFER_FAIL: stride overflow\");\n            return;\n        };\n        let Some(size) = stride.checked_mul(height) else {\n            eprintln!(\"PORTAL_CI_BUFFER_FAIL: size overflow\");\n            return;\n        };\n        let Ok(stride) = i32::try_from(stride) else { return; };\n        let Ok(size) = i32::try_from(size) else { return; };\n        let property = |key, value| pod::Property {\n            key,\n            flags: pod::PropertyFlags::empty(),\n            value: Value::Int(value),\n        };\n        let parameter = Value::Object(pod::Object {\n            type_: libspa::sys::SPA_TYPE_OBJECT_ParamBuffers,\n            id: libspa::sys::SPA_PARAM_Buffers,\n            properties: vec![\n                property(libspa::sys::SPA_PARAM_BUFFERS_buffers, 8),\n                property(libspa::sys::SPA_PARAM_BUFFERS_blocks, 1),\n                property(libspa::sys::SPA_PARAM_BUFFERS_size, size),\n                property(libspa::sys::SPA_PARAM_BUFFERS_stride, stride),\n                property(libspa::sys::SPA_PARAM_BUFFERS_dataType,\n                         1 << libspa::sys::SPA_DATA_MemFd),\n            ],\n        });\n        let mut storage = Vec::<u8>::with_capacity(1024);\n        let Ok(_) = PodSerializer::serialize(\n            &mut std::io::Cursor::new(&mut storage), &parameter\n        ) else {\n            eprintln!(\"PORTAL_CI_BUFFER_FAIL: SPA ParamBuffers serialization failed\");\n            return;\n        };\n        // The serialized bytes live through update_params; no persistent\n        // borrowed pointers or uninitialized buffer memory escape this call.\n        let buffer = unsafe {\n            libspa::pod::Pod::from_raw(storage.as_ptr().cast::<libspa::sys::spa_pod>())\n        };\n        match stream.update_params(&mut [buffer]) {\n            Ok(()) => eprintln!(\"PORTAL_CI_BUFFERS_NEGOTIATED: {}x{} MemFd\", width, height),\n            Err(e) => eprintln!(\"PORTAL_CI_BUFFER_FAIL: update_params: {e}\"),\n        }\n    }\n\n" + "    /// Get the PipeWire node ID for this stream.",
    )
    return source


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("CI fixture must never modify a developer or production install")
    if len(sys.argv) != 3:
        raise SystemExit("usage: ci_portal_generic_remote.py .ci-generic-portal/src/pipewire/mod.rs .ci-generic-portal/src/pipewire/stream.rs")
    remote_path, stream_path = (Path(arg).resolve() for arg in sys.argv[1:])
    if not str(remote_path).endswith("/.ci-generic-portal/src/pipewire/mod.rs"):
        raise RuntimeError("remote source must be the disposable CI checkout")
    if stream_path != remote_path.parent / "stream.rs":
        raise RuntimeError("stream source must share the pinned CI checkout")
    if not remote_path.is_file() or not stream_path.is_file():
        raise RuntimeError("missing pinned CI source file")
    # Validate BOTH functions before writing either; abort on upstream drift.
    remote_source = patch_source(remote_path.read_text(encoding="utf-8"))
    stream_source = patch_stream_buffers(stream_path.read_text(encoding="utf-8"))
    remote_path.write_text(remote_source, encoding="utf-8")
    stream_path.write_text(stream_source, encoding="utf-8")
    print("PORTAL_CI_PATCH_OK: isolated FD and PipeWire buffer flags; not for production")
    return 0


if __name__ == "__main__":
    sys.exit(main())
