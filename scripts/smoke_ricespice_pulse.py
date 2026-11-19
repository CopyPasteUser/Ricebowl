#!/usr/bin/env python3
"""SG2 real PulseAudio protocol smoke, isolated from the user's audio session.

Only CI may opt in. A private 0700 runtime tree, socket and a real disposable
PulseAudio process provide two null sinks; pactl operations exercise the
production RiceSpice adapter. No system audio state or daemon is modified.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from macrice.de import audio_devices


def require(condition: bool, explanation: str) -> None:
    if not condition:
        raise RuntimeError(explanation)


def wait_for(predicate, process, message: str, timeout: float = 8) -> object:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Disposable PulseAudio server exited before " + message)
        try:
            value = predicate()
            if value:
                return value
        except (audio_devices.AudioDeviceError, OSError) as exc:
            last_error = type(exc).__name__ + ': ' + str(exc)[:120]
        time.sleep(0.08)
    if message == "client stream discovery":
        # Diagnose only field type/primitive ID values from CI-owned null sinks,
        # never application names or a host audio server's stream metadata.
        try:
            records = json.loads(audio_devices._run(
                "--format=json", "list", "sink-inputs"))
            schema = [{
                key: (type(row.get(key)).__name__,
                      row.get(key) if type(row.get(key)) in (int, bool) else None)
                for key in ("index", "sink", "client", "mute")
            } for row in records[:3]]
            print("SG2 private PulseAudio stream schema: " + repr(schema),
                  file=sys.stderr)
        except (ValueError, KeyError, audio_devices.AudioDeviceError):
            pass
    raise RuntimeError("Timeout during real PulseAudio " + message
                       + (f" ({last_error})" if last_error else ""))


def main() -> None:
    require(os.environ.get("RICEBOWL_SG2_DISPOSABLE") == "1",
            "Real audio smoke requires explicit disposable CI mode")
    for tool in ("pulseaudio", "pactl", "pacat"):
        require(shutil.which(tool) is not None, "Missing CI audio tool: " + tool)
    with tempfile.TemporaryDirectory(prefix="ricebowl-sg2-audio-") as folder:
        root = Path(folder)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        home = root / "home"
        home.mkdir(mode=0o700)
        config = root / "config"
        config.mkdir(mode=0o700)
        socket = runtime / "pulse.sock"
        env = {**os.environ,
               "HOME": str(home), "XDG_RUNTIME_DIR": str(runtime),
               "XDG_CONFIG_HOME": str(config),
               "PULSE_SERVER": "unix:" + str(socket),
               "PULSE_AUTOSPAWN": "0"}
        command = [
            "pulseaudio", "-n", "--daemonize=no", "--exit-idle-time=-1",
            "--log-target=stderr",
            "--load=module-native-protocol-unix socket=" + str(socket)
            + " auth-anonymous=1",
            "--load=module-null-sink sink_name=sg2_a",
            "--load=module-null-sink sink_name=sg2_b",
        ]
        server = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        player = None
        old_env = {name: os.environ.get(name) for name in
                   ("HOME", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
                    "PULSE_SERVER", "PULSE_AUTOSPAWN")}
        try:
            os.environ.update({name: env[name] for name in old_env})
            data = wait_for(lambda: audio_devices.inspect(), server,
                            "device discovery")
            outputs = data["outputs"]
            require({d["name"] for d in outputs} == {"sg2_a", "sg2_b"},
                    "Disposable provider did not expose two isolated sinks")
            previous = next(d["name"] for d in outputs if d["default"])
            other = next(d["name"] for d in outputs if d["name"] != previous)
            changed = audio_devices.set_default("sink", other,
                                                 expected_current=previous)
            require(changed["changed"] and changed["current"] == other,
                    "Real audio default readback did not confirm the write")
            try:
                audio_devices.set_default("sink", previous,
                                          expected_current=previous)
            except audio_devices.AudioDeviceError as exc:
                require(exc.code == "audio_selection_conflict",
                        "Incorrect real audio stale-selection failure")
            else:
                raise RuntimeError("Stale GUI audio selection was accepted")

            # Monitor sources are genuine PulseAudio sources (no microphone
            # capture or user hardware access is necessary for this test).
            # PulseAudio may follow a new default sink with a new monitor
            # source. Review source identity *after the sink transaction.
            sources = audio_devices.inspect()["inputs"]
            if len(sources) >= 2:
                active = next(d["name"] for d in sources if d["default"])
                alternate = next(d["name"] for d in sources if d["name"] != active)
                observed = audio_devices.set_default("source", alternate,
                                                       expected_current=active)
                require(observed["current"] == alternate,
                        "Real recording-source default readback failed")

            player = subprocess.Popen(
                ["pacat", "--playback", "--raw", "--format=s16le",
                 "--rate=8000", "--channels=1", "/dev/zero"],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            def active_stream():
                if player.poll() is not None:
                    raise RuntimeError("Disposable playback process exited")
                rows = audio_devices.playback_streams()["streams"]
                return next((s for s in rows if type(s.get("client")) is int), None)

            stream = wait_for(active_stream, server, "client stream discovery")
            moved_to = next(d for d in outputs if d["index"] != stream["sink"])
            moved = audio_devices.set_stream_output(
                stream["index"], moved_to["name"], expected_sink=stream["sink"],
                expected_client=stream["client"])
            require(moved["sink"] == moved_to["index"],
                    "Real playback routing readback failed")
            volume = audio_devices.set_stream_volume(
                stream["index"], 70, expected=moved["volume"],
                expected_client=stream["client"])
            require(abs(volume["volume"] - 70) <= 1,
                    "Real per-stream volume readback failed")
            muted = audio_devices.set_stream_mute(
                stream["index"], True, expected=volume["mute"],
                expected_client=stream["client"])
            require(muted["mute"] is True,
                    "Real per-stream mute readback failed")

            player.terminate()
            player.wait(timeout=3)
            try:
                audio_devices.set_stream_mute(
                    stream["index"], False, expected=True,
                    expected_client=stream["client"])
            except audio_devices.AudioDeviceError:
                pass
            else:
                raise RuntimeError("Removed real audio stream accepted mutation")

            server.terminate()
            server.wait(timeout=3)
            try:
                audio_devices.inspect()
            except audio_devices.AudioDeviceError:
                pass
            else:
                raise RuntimeError("Lost real audio provider was reported healthy")
            print("SG2 real isolated PulseAudio: defaults, recording source, "
                  "live client routing/volume/mute, stale selection, "
                  "stream loss and provider loss: PASS")
        finally:
            if player is not None and player.poll() is None:
                player.kill()
                player.wait(timeout=3)
            if server.poll() is None:
                server.kill()
                server.wait(timeout=3)
            for name, old in old_env.items():
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired,
            audio_devices.AudioDeviceError) as exc:
        print("SG2 disposable audio smoke failed: " + str(exc),
              file=sys.stderr)
        raise SystemExit(1)
