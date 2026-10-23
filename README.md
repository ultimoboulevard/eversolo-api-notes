# Eversolo DMP-A6: API notes and interoperability report

Notes on the undocumented local HTTP API of the Eversolo DMP-A6 streamer (port 9529, the same API the Eversolo Control app uses), written for integrators and developers who need to drive the device from an external system: Home Assistant, Crestron, Control4, Loxone, Homey, or a custom bridge.

The material comes from one unit in daily use in a multi-room setup, May–October 2026, on firmware v1.5.90. It was mapped by capturing the official app's traffic, by probe scripts with control conditions, and from months of production logs.

## Contents

| File | What it is |
|---|---|
| [REPORT.md](REPORT.md) | The interoperability report: capability matrix, eight known failure modes with mitigations, recommendations per control system, security note. |
| [eversolo_probe.py](eversolo_probe.py) | Read-only probe: state, volume, mute, input, queue, display mode, native ReplayGain, and a playback-rate check that tells a frozen device from a healthy one. |

## Quick start

```
python3 eversolo_probe.py <device-ip>
python3 eversolo_probe.py <device-ip> --watch 20
```

Python 3.8+, standard library only. By default the script only reads; it sends no transport, volume or settings commands, so it is safe to run while music plays.

## Highlights

- No absolute volume over the network: only up/down steps, and the step size (0.5 or 1.0 dB) is a device setting the API does not report.
- Mute and unmute can be ignored while music is playing.
- On firmware v1.5.90, resuming playback within about 2 s of a seek freezes the device, which keeps reporting "playing". The report gives the dose-response data and the mitigation.
- Loads and queue operations return `status: 200` before the effect happens, and a playlist can come back stale from the device's cloud cache. Every state-changing call needs a read-back.
- The API has no authentication.

## What is not covered

Inputs other than the internal player and coaxial, output switching, power commands, other models in the range, and firmware later than v1.5.90. Wake-on-LAN is noted but not validated.

## Licences

- `eversolo_probe.py`: GNU GPL v3 or later ([LICENSE](LICENSE)). Other terms on request.
- `REPORT.md`: Creative Commons BY-NC-ND 4.0 ([LICENSE-REPORT](LICENSE-REPORT)). Share it with credit, unchanged, for non-commercial use. For commercial use, or for a report on your own device, contact the author.

## Author

Francesco Zaccaria, Zenobj (Amsterdam). Integration work for audio devices without official support: API mapping, bridges, Home Assistant and Homey integrations, delivered remotely.

## Disclaimer

Not affiliated with Eversolo or Zidoo. Endpoint names and behaviour can change with any firmware update. Use at your own risk; the probe sends only read requests unless `--probe-405` is given.
