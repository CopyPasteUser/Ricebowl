"""On-demand RiceSpice audio-device inventory and explicit default selection.

Use the existing PulseAudio-compatible server (including pipewire-pulse) via
fixed pactl arguments. No privileged helper, shell, config writes or daemon.
The native shell's existing WirePlumber volume controls remain independent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any


API_VERSION = 1
MAX_REPLY = 512 * 1024
MAX_DEVICES = 32
MAX_STREAMS = 64
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:+-]{0,159}\Z")
_KINDS = {"sink": "sinks", "source": "sources"}


class AudioDeviceError(ValueError):
    def __init__(self, message: str, code: str = "audio_unavailable",
                 *, may_have_changed: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.may_have_changed = may_have_changed


def _run(*args: str) -> str:
    binary = shutil.which("pactl")
    if binary is None:
        raise AudioDeviceError("pactl is not installed")
    try:
        result = subprocess.run([binary, *args], capture_output=True, timeout=4,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioDeviceError("Audio server is unreachable or timed out") from exc
    if result.returncode:
        raise AudioDeviceError("Audio server rejected the requested operation")
    if len(result.stdout) > MAX_REPLY:
        raise AudioDeviceError("Audio server returned oversized device data",
                               "audio_response_invalid")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AudioDeviceError("Audio server returned invalid text",
                               "audio_response_invalid") from exc


def _devices(kind: str, payload: str) -> list[dict[str, Any]]:
    if kind not in _KINDS:
        raise AudioDeviceError("Unsupported audio device type", "invalid_audio_kind")
    try:
        entries = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise AudioDeviceError("Audio device inventory is malformed",
                               "audio_response_invalid") from exc
    if type(entries) is not list or len(entries) > MAX_DEVICES:
        raise AudioDeviceError("Audio device inventory is missing or oversized",
                               "audio_response_invalid")
    result = []
    names = set()
    indices = set()
    for entry in entries:
        if type(entry) is not dict:
            raise AudioDeviceError("Invalid audio device entry", "audio_response_invalid")
        name, index, desc = (entry.get("name"), entry.get("index"),
                             entry.get("description", ""))
        if (type(name) is not str or not _NAME.fullmatch(name)
                or name in names or type(index) is not int or index in indices
                or not 0 <= index < 2**32 or type(desc) is not str):
            raise AudioDeviceError("Invalid or ambiguous audio device identity",
                                   "audio_response_invalid")
        names.add(name)
        indices.add(index)
        result.append({"name": name, "index": index,
                       "description": "".join(ch for ch in desc[:160]
                                              if ch.isprintable())[:120]})
    return result


def _current(kind: str) -> str:
    command = "get-default-sink" if kind == "sink" else "get-default-source"
    value = _run(command).strip()
    if not _NAME.fullmatch(value):
        raise AudioDeviceError("Default audio device is unavailable",
                               "audio_response_invalid")
    return value


def _enumerate(kind: str) -> tuple[list[dict[str, Any]], str | None]:
    devices = _devices(kind, _run("--format=json", "list", _KINDS[kind]))
    if not devices:
        return [], None
    current = _current(kind)
    if current not in {device["name"] for device in devices}:
        raise AudioDeviceError("Default device is not in the current inventory",
                               "audio_response_invalid")
    return devices, current


def inspect() -> dict[str, Any]:
    """Read genuine playback/recording devices; no active setting is changed."""
    output, current_output = _enumerate("sink")
    inputs, current_input = _enumerate("source")
    return {"api_version": API_VERSION, "ok": True, "backend": "pactl",
            "read_only": True, "outputs": [{**d, "default": d["name"] == current_output}
                                           for d in output],
            "inputs": [{**d, "default": d["name"] == current_input} for d in inputs],
            "mutates_active_desktop": False}


def set_default(kind: str, name: str, *, expected_current: str | None = None) -> dict[str, Any]:
    """Change exactly one verified audio default after explicit user selection.

    This changes the default for new streams. Individual existing playback
    streams may stay routed to their previous devices, depending on the audio
    server's stream-restore policy.
    """
    if kind not in _KINDS:
        raise AudioDeviceError("Choose sink or source", "invalid_audio_kind")
    if type(name) is not str or not _NAME.fullmatch(name):
        raise AudioDeviceError("Invalid audio device name", "invalid_audio_device")
    if expected_current is not None and (type(expected_current) is not str
                                         or not _NAME.fullmatch(expected_current)):
        raise AudioDeviceError("Invalid expected default device", "invalid_audio_device")
    devices, before = _enumerate(kind)
    if name not in {device["name"] for device in devices}:
        raise AudioDeviceError("Selected audio device is not available", "audio_device_missing")
    if expected_current is not None and before != expected_current:
        raise AudioDeviceError("Default audio device changed since review",
                               "audio_selection_conflict")
    if before == name:
        return {"api_version": API_VERSION, "ok": True, "backend": "pactl",
                "changed": False, "kind": kind, "current": name,
                "mutates_active_desktop": False}
    try:
        _run("set-default-sink" if kind == "sink" else "set-default-source", name)
    except AudioDeviceError as exc:
        raise AudioDeviceError(str(exc), exc.code, may_have_changed=True) from exc
    try:
        after = _current(kind)
    except AudioDeviceError as exc:
        raise AudioDeviceError("Audio default may have changed; verification failed",
                               "audio_verification_failed", may_have_changed=True) from exc
    if after != name:
        raise AudioDeviceError("Audio default did not match the requested device",
                               "audio_verification_failed", may_have_changed=True)
    return {"api_version": API_VERSION, "ok": True, "backend": "pactl",
            "changed": True, "kind": kind, "previous": before, "current": after,
            "mutates_active_desktop": True}


def _streams(payload: str) -> list[dict[str, Any]]:
    """Parse bounded PulseAudio sink-inputs, preserving actual per-stream state."""
    try:
        records = json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise AudioDeviceError("Invalid playback-stream inventory") from exc
    if type(records) is not list or len(records) > MAX_STREAMS:
        raise AudioDeviceError("Playback-stream inventory is missing or oversized")
    found = set()
    streams = []
    for record in records:
        if type(record) is not dict:
            raise AudioDeviceError("Invalid playback-stream entry")
        index, sink, muted = record.get("index"), record.get("sink"), record.get("mute")
        if (type(index) is not int or not 0 <= index < 2**32 or index in found
                or type(sink) is not int or not 0 <= sink < 2**32
                or type(muted) is not bool):
            raise AudioDeviceError("Invalid playback-stream identity or state")
        found.add(index)
        volume = record.get("volume")
        if type(volume) is not dict or not 1 <= len(volume) <= 32:
            raise AudioDeviceError("Invalid playback-stream volume")
        levels = []
        for channel in volume.values():
            value = channel.get("value") if type(channel) is dict else None
            if type(value) is not int or not 0 <= value <= 2**23:
                raise AudioDeviceError("Invalid playback-stream volume channel")
            levels.append(value)
        percent = round(sum(levels) / len(levels) * 100 / 65536)
        props = record.get("properties", {})
        if type(props) is not dict:
            raise AudioDeviceError("Invalid playback stream metadata")
        label = props.get("application.name") or props.get("media.name") or f"Stream {index}"
        if type(label) is not str:
            label = f"Stream {index}"
        label = "".join(ch for ch in label[:140] if ch.isprintable())[:100]
        streams.append({"index": index, "sink": sink, "mute": muted,
                        "volume": percent, "label": label or f"Stream {index}"})
    return streams


def playback_streams() -> dict[str, Any]:
    """Read real application streams and available playback device identities."""
    devices, _current = _enumerate("sink")
    streams = _streams(_run("--format=json", "list", "sink-inputs"))
    return {"outputs": devices, "streams": streams}


def _stream(index: int) -> dict[str, Any]:
    if type(index) is not int or not 0 <= index < 2**32:
        raise AudioDeviceError("Invalid playback stream identifier")
    current = next((item for item in playback_streams()["streams"]
                    if item["index"] == index), None)
    if current is None:
        raise AudioDeviceError("Playback stream disappeared; refresh before applying")
    return current


def set_stream_output(index: int, sink: str, *, expected_sink: int) -> dict[str, Any]:
    if type(sink) is not str or not _NAME.fullmatch(sink) or type(expected_sink) is not int:
        raise AudioDeviceError("Choose an available playback output")
    before = playback_streams()
    current = next((item for item in before["streams"] if item["index"] == index), None)
    if (type(index) is not int or current is None or current["sink"] != expected_sink):
        raise AudioDeviceError("Playback stream changed; refresh before applying")
    target = next((item for item in before["outputs"] if item["name"] == sink), None)
    if target is None:
        raise AudioDeviceError("Chosen output is unavailable")
    if target["index"] == current["sink"]:
        return current
    try:
        _run("move-sink-input", str(index), sink)
        after = _stream(index)
    except AudioDeviceError as exc:
        raise AudioDeviceError("Stream routing may have changed; refresh and inspect",
                               may_have_changed=True) from exc
    if after["sink"] != target["index"]:
        raise AudioDeviceError("Stream routing could not be verified", may_have_changed=True)
    return after


def set_stream_volume(index: int, percent: int, *, expected: int) -> dict[str, Any]:
    if (type(index) is not int or type(percent) is not int or type(expected) is not int
            or not 0 <= percent <= 150 or not 0 <= expected <= 1000):
        raise AudioDeviceError("Invalid playback stream volume")
    current = _stream(index)
    if current["volume"] != expected:
        raise AudioDeviceError("Stream volume changed; refresh before applying")
    if current["volume"] == percent:
        return current
    try:
        _run("set-sink-input-volume", str(index), f"{percent}%")
        after = _stream(index)
    except AudioDeviceError as exc:
        raise AudioDeviceError("Stream volume may have changed; refresh and inspect",
                               may_have_changed=True) from exc
    if abs(after["volume"] - percent) > 1:
        raise AudioDeviceError("Stream volume could not be verified", may_have_changed=True)
    return after


def set_stream_mute(index: int, enabled: bool, *, expected: bool) -> dict[str, Any]:
    if type(index) is not int or type(enabled) is not bool or type(expected) is not bool:
        raise AudioDeviceError("Invalid playback mute selection")
    current = _stream(index)
    if current["mute"] != expected:
        raise AudioDeviceError("Stream mute changed; refresh before applying")
    if enabled == expected:
        return current
    try:
        _run("set-sink-input-mute", str(index), "1" if enabled else "0")
        after = _stream(index)
    except AudioDeviceError as exc:
        raise AudioDeviceError("Stream mute may have changed; refresh and inspect",
                               may_have_changed=True) from exc
    if after["mute"] != enabled:
        raise AudioDeviceError("Stream mute could not be verified", may_have_changed=True)
    return after


def invalid(error: AudioDeviceError) -> dict[str, Any]:
    return {"api_version": API_VERSION, "ok": False, "backend": "pactl",
            "may_have_changed": error.may_have_changed,
            "error": {"code": error.code, "message": str(error)}}
