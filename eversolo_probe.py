#!/usr/bin/env python3
# Copyright (C) 2026 Francesco Zaccaria (Zenobj)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See LICENSE. For use under other terms, contact the author.
"""Read-only interoperability probe for the Eversolo DMP-A6 (Zidoo API, port 9529).

Companion to the "Eversolo DMP-A6: Interoperability Report" (REPORT.md).

By default this script sends ONLY read requests (getModel, getState,
getPlayQueue, getReplaygainList). It never sends transport,
volume, mute, input or settings commands, so it is safe to run while music
is playing.

    python3 eversolo_probe.py <device-ip>
    python3 eversolo_probe.py <device-ip> --watch 20     # playback-rate check
    python3 eversolo_probe.py <device-ip> --probe-405    # see warning below

--probe-405 sends a GET with no parameters to endpoint names that, on the
tested unit, do not exist (HTTP 405): absolute volume and volume-step
readers. It is how their absence was established. Use only with the owner's
consent.

Python 3.8+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PORT = 9529
TIMEOUT_S = 4.0

STATES = {0: "idle", 3: "playing", 4: "paused/transitioning"}
VU_MODES = {0: "cover", 1: "VU meter", -1: "home"}
RG_MODES = {0: "Off", 1: "Track", 2: "Album"}

# Rate thresholds for the freeze check (failure mode F1 in the report).
RATE_HEALTHY = 0.80
RATE_FROZEN = 0.30

PROBE_405 = [
    "/ZidooMusicControl/v2/setVolume",
    "/ZidooMusicControl/v2/getVolumeSetting",
    "/ZidooMusicControl/v2/getVolumeStep",
    "/ZidooMusicControl/v2/getAudioSetting",
]


def get(base: str, path: str) -> tuple[int, dict | None]:
    """GET base+path. Returns (http_status, json or None). Status 0 = unreachable."""
    try:
        with urllib.request.urlopen(base + path, timeout=TIMEOUT_S) as r:
            body = r.read()
            try:
                return r.status, json.loads(body or b"{}")
            except ValueError:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError):
        return 0, None


def line(label: str, value) -> None:
    print(f"  {label:<26} {value}")


def section(title: str) -> None:
    print(f"\n{title}")


def check_model(base: str) -> bool:
    section("Device")
    code, data = get(base, "/ZidooControlCenter/getModel")
    if code == 0:
        line("reachable", "NO - no answer on port 9529")
        print("\n  The device may be in network standby (the API does not answer"
              "\n  at all in that state), off, or on another address.")
        return False
    line("reachable", f"yes (HTTP {code})")
    if isinstance(data, dict):
        for k in ("model", "modelName", "firmware", "firmwareVersion",
                  "version", "deviceName"):
            if k in data:
                line(k, data[k])
        extra = sorted(k for k in data if k not in
                       ("model", "modelName", "firmware", "firmwareVersion",
                        "version", "deviceName", "status"))
        if extra:
            line("other getModel fields", ", ".join(extra))
    return True


def check_state(base: str) -> dict:
    section("State (getState)")
    code, st = get(base, "/ZidooMusicControl/v2/getState")
    if not isinstance(st, dict):
        line("getState", f"failed (HTTP {code})")
        return {}
    s = st.get("state")
    line("state", f"{s} = {STATES.get(s, 'unknown')}")
    pos, dur = int(st.get("position") or 0), int(st.get("duration") or 0)
    line("position / duration", f"{pos / 1000:.1f} s / {dur / 1000:.1f} s")

    pm = st.get("playingMusic") or {}
    ep = st.get("everSoloPlayInfo") or {}
    external = ep.get("souceType") == 3      # sic: "souce", as spelt by the API
    if external:
        line("active input", f"EXTERNAL: {ep.get('playTypeSubtitle') or '?'}")
        line("track metadata", "stale on external inputs - do not display")
    else:
        line("active input", "internal player")
        if pm:
            line("track", f"{pm.get('artist', '?')} - {pm.get('title', '?')}")
            line("source service", pm.get("streamId") or "?")
    if "isCanSeek" in ep:
        line("seek allowed (isCanSeek)", ep.get("isCanSeek"))

    vd = st.get("volumeData") or {}
    raw = vd.get("currenttVolume", vd.get("currentVolume"))   # sic: two t's
    mx = vd.get("maxVolume")
    if raw is not None:
        line("volume (raw / max)", f"{raw} / {mx}  (raw unit = 0.5 dB on the tested unit)")
        try:
            if int(raw) % 2:
                line("volume step hint", "raw is odd -> step is 0.5 dB per press")
        except (TypeError, ValueError):
            pass
    if "isMute" in vd:
        line("mute flag (isMute)", vd.get("isMute"))
    if "intputTag" in vd:                     # sic: "intput", as spelt by the API
        line("input tag (intputTag)", vd.get("intputTag"))

    vu = st.get("vuDisplayMode")
    if vu is not None:
        line("display mode", f"{vu} = {VU_MODES.get(vu, 'unknown')}")
    for k in ("loopModel", "loopMode"):
        if k in st:
            v = st.get(k)
            meaning = {0: "repeat list", 1: "repeat one", 2: "SHUFFLE",
                       3: "in order"}.get(v, "unknown")
            line(f"repeat/shuffle ({k})", f"{v} = {meaning}")
            if v == 2:
                line("warning", "playlist loads will be reordered (F5)")
    return st


def check_queue(base: str) -> None:
    section("Queue")
    code, q = get(base, "/ZidooMusicControl/v2/getPlayQueue?start=0&count=2000")
    if not isinstance(q, dict):
        line("getPlayQueue", f"failed (HTTP {code})")
        return
    items = q.get("array") or []
    line("items in device queue", len(items))
    if items:
        first = items[0]
        line("first item internal id", f"{first.get('id')}  (not a service track ID)")


def check_replaygain(base: str) -> None:
    section("Native ReplayGain")
    code, d = get(base, "/SystemSettings/playSettings/getReplaygainList")
    if not isinstance(d, dict) or d.get("status") != 200:
        line("getReplaygainList", f"not available (HTTP {code})")
        return
    idx = d.get("currentIndex")
    line("current setting", f"{idx} = {RG_MODES.get(idx, 'unknown')}")


def watch_rate(base: str, seconds: float) -> None:
    section(f"Playback rate over {seconds:.0f} s (freeze check, F1)")
    samples = []
    end = time.monotonic() + seconds
    while True:
        _, st = get(base, "/ZidooMusicControl/v2/getState")
        if isinstance(st, dict):
            samples.append((time.monotonic(), int(st.get("position") or 0),
                            st.get("state")))
        if time.monotonic() >= end:
            break
        time.sleep(1.5)
    if len(samples) < 3:
        line("result", "not enough samples (device unreachable?)")
        return
    t0, p0, _ = samples[0]
    t1, p1, s1 = samples[-1]
    moved_ms = p1 - p0
    elapsed_ms = (t1 - t0) * 1000
    rate = moved_ms / elapsed_ms if elapsed_ms > 0 else 0.0
    line("reported state", f"{s1} = {STATES.get(s1, 'unknown')}")
    line("position advance / time", f"{moved_ms} ms / {elapsed_ms:.0f} ms")
    line("rate", f"{rate:.3f}")
    # A frozen device still REPORTS playing and still creeps forward (~2.5%
    # of real time), so over a short window it can move only a few hundred ms.
    # Trust the reported state first: only a non-playing state means stopped.
    if s1 != 3 or moved_ms == 0:
        verdict = "STOPPED or paused"
    elif rate >= RATE_HEALTHY:
        verdict = "HEALTHY - playing in real time"
    elif rate <= RATE_FROZEN:
        verdict = "FROZEN - reports playing but is not (see F1)"
    else:
        verdict = "UNCLEAR - repeat with a longer window"
    if moved_ms < 0:
        verdict += " (position went back: track change or seek during the window)"
    line("verdict", verdict)


def probe_405(base: str) -> None:
    section("Absent endpoints (--probe-405)")
    for path in PROBE_405:
        code, _ = get(base, path)
        note = "absent, as on the tested unit" if code == 405 else "DIFFERENT from the tested unit"
        line(path.rsplit("/", 1)[-1], f"HTTP {code} - {note}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only probe for the Eversolo DMP-A6 local API.")
    ap.add_argument("host", help="device IP address or hostname")
    ap.add_argument("--watch", type=float, default=0.0, metavar="SECONDS",
                    help="sample playback position for SECONDS to detect a freeze")
    ap.add_argument("--probe-405", action="store_true",
                    help="confirm that absolute-volume and step endpoints are absent")
    args = ap.parse_args()

    base = f"http://{args.host}:{PORT}"
    print(f"Eversolo probe - {base} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if not check_model(base):
        return 2
    check_state(base)
    check_queue(base)
    check_replaygain(base)
    if args.watch > 0:
        watch_rate(base, args.watch)
    if args.probe_405:
        probe_405(base)
    print("\nNo commands were sent to the device." if not args.probe_405 else
          "\nOnly read requests and the 405 probes were sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
