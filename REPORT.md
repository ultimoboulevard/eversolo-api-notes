# Eversolo DMP-A6: Interoperability Report

**Zenobj** · Francesco Zaccaria · Version 1.0 · 19 October 2026 · Licence: CC BY-NC-ND 4.0 (see LICENSE-REPORT)

---

## 1. Summary

The Eversolo DMP-A6 can be controlled over the local network through an undocumented HTTP API on port 9529. This is the API the official Eversolo Control app uses. Transport, queue, playlist loading, inputs, display and native ReplayGain can all be driven from an external system. Four limits matter for an installer:

1. **No absolute volume.** Volume can only be stepped up or down, and the step size is a user setting the device does not report.
2. **Mute is unreliable while music is playing.** A mute or unmute sent during playback can be ignored.
3. **Seek can freeze the device** on firmware v1.5.90 if playback resumes too soon. The device keeps reporting "playing" while frozen.
4. **The device sometimes stops on its own** on firmware v1.5.90: about 12 times a day in our logs, mostly far from any command. No external fix exists for this.

**Verdict by control system**

| System | Fit | What it takes |
|---|---|---|
| Home Assistant | Yes, with gaps | The free community integration covers basic control. Queue handling, input switching and safe resume need custom logic. |
| Crestron, Control4, Loxone | Yes, through a bridge | All commands are plain HTTP GETs, so any processor can send them. Waits, read-backs and retries (sections 4 and 5) are better kept in a small bridge service than in the processor program. |
| Alexa / voice | Yes, through a bridge | No native skill was found. Voice works through the same bridge. |
| Scenes that set an exact volume | No | There is no absolute volume. Use relative steps, or a bridge that counts steps from a read-back. |

---

## 2. Scope and method

- **Unit:** one DMP-A6, used daily in a multi-room setup with Sonos and a custom iOS player, May–October 2026.
- **Firmware:** findings from July 2026 onwards are on v1.5.90 (released 22 July 2026), confirmed on the unit on 23 October 2026. Earlier findings are on the previous firmware.
- **How the API was mapped:**
  - captures of the official app's traffic (Eversolo Control 1.2.76, iOS) through a proxy;
  - one-off probe scripts for each behaviour, including dose-response runs with a control condition;
  - months of production logs from a server that drives the device.
- **Status labels used in this report:**
  - **Verified:** confirmed on this unit.
  - **Captured:** seen in the app's traffic but not confirmed on this unit.
  - **Not tested.**

All endpoints below are `GET http://<device>:9529/...` and return JSON with a `status` field (200 = accepted). The API has **no authentication** (see section 7).

---

## 3. Capability matrix

### 3.1 Transport

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Play/pause toggle | Verified | `/ZidooMusicControl/v2/playOrPause` | Toggle only. There is no pause-only or play-only command. |
| Next / previous | Verified | `/ZidooMusicControl/v2/playNext`, `/playLast` | — |
| Read state | Verified | `/ZidooMusicControl/v2/getState` | `state`: 3 = playing, 4 = paused or transitioning, 0 = idle. Also reports `position`, `duration`, track metadata and `volumeData`. |
| Explicit pause | Verified, via logic | read `getState`, toggle only if `state == 3` | The commands behave like asynchronous key presses. A late toggle can undo a pause, so confirm with a second read. |

### 3.2 Volume and mute

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Volume up/down | Verified | `/ZidooControlCenter/RemoteControl/sendkey?key=Key.VolumeUp` (`VolumeDown`) | Asynchronous: an immediate read-back returns the old value. |
| Read volume | Verified | `getState` → `volumeData.currenttVolume` (spelt with two t's), `maxVolume` | Raw scale 0–200 in 0.5 dB units. |
| Set absolute volume | **Not available** | — | `setVolume` and 12 other candidate names return HTTP 405. |
| Read the step size | **Not available** | — | `getVolumeSetting`, `getVolumeStep`, `getAudioSetting` and five more names return 405. The step per press (0.5 or 1.0 dB) is set by the user on the device. Changing it silently halves or doubles every scripted volume move. |
| Mute on/off | Verified, **conditional** | `/ZidooMusicControl/v2/setMuteVolume?isMute=1` (`=0`) | Can be ignored while music is playing. A mute set while stopped does take effect and survives the start of playback. Check `volumeData.isMute` after every mute command. |

### 3.3 Queue and playlists

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Read queue | Verified | `/ZidooMusicControl/v2/getPlayQueue?start=0&count=N` | Items carry an internal `id`, a signed 32-bit hash, which is **not** the streaming service's track ID. |
| Jump to a queue item | Verified | `/ZidooMusicControl/v2/playMusic?musicId=<internal id>&...` | Needs the internal `id` from `getPlayQueue`. |
| Load a playlist, replacing the queue | Verified | `/ZidooMusicControl/v2/addAirAbleMusicListToPlayQueue?playlistUrl=<airable url>&type=3&...` | "Play now": playback starts immediately. Returns in about 40 ms whatever the playlist size, because the device then fetches the tracks itself from its cloud provider (airable). |
| Insert after the current track | Verified | same endpoint with `type=1` | Does not interrupt the current track. Asynchronous: the queue grows a few seconds after the 200. |
| Clear queue | Verified | `/ZidooMusicControl/v2/removeAllPlayQueue` | Asynchronous: the 200 arrives before the queue is empty. Poll `getPlayQueue` until it is. |
| Set an arbitrary queue | **Not available** | — | Queues can only be built from a playlist the device fetches from the cloud. |
| Repeat/shuffle mode | Verified | `/ZidooMusicControl/v2/setLoopMode?loop=N` | 0/1 = repeat, 2 = shuffle, 3 = in order. The mode **persists** across sessions, and playlist loads inherit it: a device left on shuffle reorders every playlist sent to it. |

### 3.4 Seek

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Seek within a track | Verified, **with risk** | `/ZidooMusicControl/v2/seekTo?time=<ms>` | See failure mode F1. `getState` exposes `everSoloPlayInfo.isCanSeek`. |

### 3.5 Inputs

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Internal streaming player | Verified | `/ZidooMusicControl/v2/setInputList?tag=XMOS&index=0` | Returns paused on the last track played. Does not autoplay. |
| Coaxial input | Captured | `setInputList?tag=RCA&index=4` | Taken from the app's traffic and not confirmed on this unit. A wrong index leaves the device on a silent input, which looks like a fault. |
| Optical, USB-in, Bluetooth, ARC | Not tested | — | Index values unknown. |
| Read the active external input | Verified | `getState` → `everSoloPlayInfo.souceType == 3`, `playTypeSubtitle` (for example "Coaxial In") | On an external input the track metadata in `playingMusic` is **stale**: it still shows the last streamed track. It must not be displayed. |

### 3.6 Display, ReplayGain, power

| Function | Status | Endpoint | Notes |
|---|---|---|---|
| Display mode | Verified | `/ZidooMusicControl/v2/changVUDisplay` (spelt "chang") | Fixed three-state cycle: 0 = cover, 1 = VU meter, −1 = home. There is no direct setter (six candidate names return 405), so you reach a mode by cycling and reading the response. |
| Screen on/off | Verified, blind | `setPowerOption?tag=screen` | Blind toggle. Whether the screen is on is not reported anywhere. |
| Native ReplayGain | Verified | `/SystemSettings/playSettings/getReplaygainList`, then `setReplaygain?index=N` | 0 = Off, 1 = Track, 2 = Album. Confirm by reading `currentIndex` back. |
| Model information | Verified | `/ZidooControlCenter/getModel` | Reports model, firmware, device name, `net_mac` and `wif_mac` (the MAC for Wake-on-LAN can be read here), plus capability flags such as `ableRemoteSleep`, `ableRemoteShutdown`, `ableRemoteReboot`, `hasMultroom`, `hasDrcSetting`, `hasDspSetting`, `hasEqSetting`. The power commands those flags refer to were not tested. Useful as a reachability check. |
| Wake from network standby | **Not validated** | Wake-on-LAN | In network standby the HTTP API does not answer at all. Wake-on-LAN code exists in our system but has not been validated on this unit. It also needs WOL enabled in the device settings. |

---

## 4. Known failure modes

### F1. The device freezes after a seek (firmware v1.5.90)

- **Symptom.** After a seek, the device reports `state = 3` (playing) and the position keeps moving, but only at about 2.5% of real time. No audio.
- **Why it is hard to catch.** Neither `state`, nor "the position changed", nor the output field tells a frozen device from a healthy one.
- **Detection.** The only reliable test is the **rate**: position advance divided by elapsed time, over several samples. About 1.0 means healthy; about 0.02 means frozen. The test script in section 8 does this.
- **Cause, from a dose-response run with a control condition:**

  | Wait between seek and resume | Result |
  |---|---|
  | 0 s | frozen |
  | 2 s | frozen |
  | 5 s | healthy (2/2) |

  The threshold drifts with device uptime. Right after a reboot, 2 s was enough.
- **Mitigation.**
  - Wait at least 3 s after the seek is confirmed before resuming; 5 s on a device that has been running for days.
  - Skip the seek for positions under 10 s and start from 0:00 instead.
  - A frozen device recovers with a second play/pause cycle (6 of 8 attempts in our logs).

### F2. Spontaneous stops (firmware v1.5.90)

- **Symptom.** Playback goes from playing to stopped with `duration = 0`, as if someone had pressed stop.
- **Frequency.** None in more than six weeks of logs before 22 July 2026. Since then about 12 a day (count of 10 August). 77% of them happened more than 5 minutes after any command sent to the device.
- **Cause.** Firmware: the first occurrences coincide with the release of v1.5.90. As of August, no fixed release existed for the A6 series.
- **Mitigation.** None from outside. A control system can detect the stop and alert or resume, but it cannot tell it apart from a person pressing stop.

### F3. An outdated copy of a playlist from the cloud cache

- **Symptom.** A playlist reloaded under the same URL can play its previous contents, or not start at all, while the device still answers 200.
- **Mitigation.** After every load, read the head of the queue and compare it with what was sent. If it does not match:
  1. reload with a cache-busting parameter added to the URL;
  2. failing that, load from a brand-new playlist.

### F4. "Accepted" is not "done"

- Clear queue, insert after current, volume steps and play/pause all return 200 **before** the effect happens.
- A load can also return HTTP 200 with internal status 803 and not start. One retry after about 1.2 s has always been enough in our logs.
- **Rule.** Every state-changing command needs a read-back.

### F5. Shuffle inherited by playlist loads

- If repeat/shuffle was left on shuffle, every playlist load is reordered, with the first track often preserved.
- **Mitigation.** Set `setLoopMode?loop=3` before each load.

### F6. Mute ignored during playback

- A "mute all" scene sent while music is playing may not mute the Eversolo.
- An unmute sent while it is playing may be ignored, which leaves a room that "plays" in silence.
- **Mitigation.** Mute and unmute only while stopped or paused, and always confirm `isMute`.

### F7. Audible blip when a load starts

- Loading is always "play now": no command loads a track without starting it. About 0.5 s of the start of the track is heard before a pause can land.
- **Mitigation.** A mute set while stopped is respected (see F6). Mute, load, pause, unmute while paused, then resume.

### F8. Volume step changed on the device

- Changing the step from 1.0 to 0.5 dB on the device halves every scripted move, and no error appears anywhere.
- **Mitigation.** Measure the step from read-backs: raw change divided by number of presses. Raw values that land on odd numbers mean the step is 0.5 dB.

---

## 5. Recommendations by system

### Home Assistant
- The community integration (`hchris1/Eversolo`, installed via HACS) covers transport, volume and state.
- Its own issue tracker reports input selection as broken (issue #241, open since August 2026).
- A second community project states that it does not handle the streaming queue.
- For queue transfer, input switching or safe resume, add a small service that applies the waits and read-backs in section 4.

### Crestron, Control4, Loxone
- Commands are simple GET requests with no authentication, so the processor can send them directly.
- What the processor program should not have to carry is the sequencing:
  - seek → wait → confirm → resume;
  - mute only while paused;
  - verify every load;
  - retry once on status 803.
- A bridge service exposing a few safe high-level commands (play here, resume at position, switch to CD input) keeps the processor program simple. It can also be reused across projects.

### Scenes and keypads
- Use relative volume (rotary or up/down) rather than fixed levels.
- Avoid "mute everything" scenes that rely on the Eversolo obeying a mute during playback.

---

## 6. What this report does not cover

- Inputs other than the internal player and coaxial, and output switching (XLR/RCA/S/PDIF).
- Power off and reboot commands.
- Firmware later than v1.5.90. The 1.5.95/96 betas are reported to introduce other regressions; not evaluated.
- Other models in the range (A8, T8). Their API is related but was not tested.
- Long-term reliability of Wake-on-LAN.

---

## 7. Security note

- **The API on port 9529 accepts commands from any device on the local network**, with no authentication.
- A guest Wi-Fi network that shares the subnet with the streamer gives every guest full control of it.
- **Recommendation.** Put the streamer on a separate VLAN reachable only by the control system.

---

## 8. Test script

`eversolo_probe.py`, delivered with this report, runs **read-only** checks against a unit on site:

- reachability and model information;
- current state, volume (raw and maximum), mute flag, active input, display mode;
- queue length, repeat/shuffle mode where reported, native ReplayGain setting;
- with `--watch N`: the playback rate over N seconds, which reports healthy / frozen / stopped (failure mode F1).

It sends no transport, volume or settings commands. An optional `--probe-405` flag confirms that the absolute-volume and step-size endpoints still return 405. It sends GET requests without parameters to those names only. Use it only with the owner's consent.

```
python3 eversolo_probe.py 192.168.1.50
python3 eversolo_probe.py 192.168.1.50 --watch 20
```

Python 3.8 or later, standard library only.
