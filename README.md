# iPad Screen

Use a jailbroken iPad as a USB-connected second screen. Target devices are the
iPad Pro 10.5-inch and iPad (9th generation), with Linux first and dedicated Mac
and Windows host apps later. Both extended desktop and mirroring are in scope.
Priorities: crisp text, then balanced desktop motion and responsiveness.

## Current state

The native iPad companion and Linux command-line host now stream H.264 over USB.
The connected iPad Pro 10.5 (iPadOS 17.7.10) showed a smooth moving test pattern,
confirmed visually by the owner. A full-resolution 2224×1668 extended-desktop
test delivered 881 frames in 30 seconds with no reported rendering errors, using
VA-API hardware encoding on Linux and Apple's native video display layer.

This is still a prototype. The iPad 9 profile is implemented but untested on the
actual device. The second connected iPad turned out to be a **Pro 9.7-inch**;
its new `pro97` profile has passed native extend/mirror tests on iPadOS 16.7.16
with Dopamine (zero reported rendering errors; visual smoothness confirmation
pending). The Omarchy bar interface is available in the separate public
[plugin repository](https://github.com/cevatkerim/omarchy-ipad-screen). Mac/Windows
hosts and desktop touch input are future work. See [the investigation](docs/investigation.md) for evidence,
limitations, and the platform plan. Earlier browser and manual-decoder experiments
are preserved in Git history.

## Linux setup

Requires Python 3, OpenSSH, libimobiledevice tools, a running usbmuxd, Hyprland
with Lua configuration support (tested on 0.56.2), `wf-recorder`, and ffmpeg. The iPad must be
USB-connected, trusted, jailbroken, and running an SSH server as `mobile`.
The companion requires an unlocked device and a rootless jailbreak with
`/var/jb/usr/bin/uicache` and `uiopen`. Rootful installation paths are not yet handled.

```sh
./scripts/ipad.py devices
./scripts/ipad.py pair --udid YOUR_DEVICE_ID --model pro105 --env-file ../.env
./scripts/ipad.py ssh 'id -un'
```

Pairing reads `PASSWORD` literally from the supplied `.env`; it never sources
the file as shell code. It appends `~/.ssh/id_ed25519.pub` to the iPad's existing
authorized keys, then verifies a passwordless login. Use `--key PATH` to select
another existing key. The private key stays in its original location.

The first SSH host key is trusted on first use over the selected USB connection;
subsequent changes are rejected. Device selection and known hosts are stored in
the ignored `.runtime/` directory. Saved profiles preserve each pairing. Use `pair --model pro105|pro97|ipad9`
for a new device and `select --udid ...` to switch back. This prototype supports
one display session at a time. See [the second-iPad setup guide](docs/another-ipad.md).

## Build and install the companion

```sh
./scripts/build-app
./scripts/install-app.py
```

The Linux cross-build uses clang plus the existing iOS SDK, linker, and ldid in
`../iphone-control/.toolchain`. Set `IPAD_TOOLCHAIN` to use another local toolchain
with the same layout. SDK/toolchain files and built binaries are not committed.
The deployment target is iPadOS 15+, but only 17.7.10 has been tested.

Installation registers the app, provisions a random receiver token over SSH,
and verifies its listener after launch. Dopamine uses `/var/jb/Applications`
with mobile sudo and PASSWORD from `--env-file`; other tested rootless layouts
use `/var/mobile/Applications`. See [device setup](docs/another-ipad.md). Updates restart only this
app. The app's Home Screen icon is currently the system placeholder. In the app,
tap the small bottom-left display icon to open or close statistics. Choose
**Hide controls** to remove the icon and panel; a **two-finger tap anywhere**
restores the icon. Hidden controls stay hidden across reconnects and app launches.
Ordinary taps on the video do not open statistics. Auto-lock is disabled while
the app is active.

## Try the display

```sh
# iPad Pro 10.5: 2224×1668, desktop UI scale 2
./scripts/native.py --mode extend

# iPad 9: 2160×1620, after pairing that device
./scripts/native.py --mode extend --model ipad9

# Normally the saved paired-device model is used automatically, including pro97.

# Mirror the focused monitor, or explicitly choose an existing output
./scripts/native.py --mode mirror
./scripts/native.py --mode mirror --output eDP-1

# Bounded experiment; cleans up automatically
./scripts/native.py --mode extend --seconds 30

# Software encoding fallback; otherwise VA-API defaults to renderD128
./scripts/native.py --mode extend --encoder software

# Synthetic receiver test (does not capture the desktop)
./scripts/native.py --mode test --seconds 15
```

The companion opens automatically. In extend mode the temporary `ipad-screen` monitor
appears to the right of existing monitors; move a window onto it using the normal
desktop controls. Use the host's keyboard and mouse. iPad touch controls the
stats panel only; desktop touch input is not implemented. The app renders
fullscreen and preserves the source aspect ratio. Mirroring a screen with a
different aspect ratio produces letterboxing.

Ctrl+C stops capture and forwarding, and removes the output created by this
session. No Hyprland configuration files are changed. A forced kill or host crash
can leave the output behind; inspect `hyprctl monitors -j` and then remove only
the project output with `hyprctl output remove ipad-screen` if necessary.

Changing scale, position or resolution while streaming restarts the capture
process automatically, preserving the output's current settings and the USB
connection. A brief pause is expected while the new encoder starts. An encoder
exit or three-second stall also triggers recovery; repeated unexplained failures
are bounded to five retries in 30 seconds. Removing the selected output ends
the session. The session summary includes `capture_restarts`.

The native listener binds only to iPad loopback and authenticates a receiver
token before accepting frames. The host reaches it directly through usbmux;
Wi-Fi and personal hotspot are not required. Video frames stay in memory.
Aggregate counters go to `.runtime/native-session.json`, and capture diagnostics
go to `.runtime/encoder.log`. Credentials and `.runtime/` are excluded from Git.
See [protocol v1](docs/protocol.md) for framing and counter semantics.

The original lossless PNG/Safari baseline remains available as
`./scripts/screen.py --mode extend` (requires `grim`). It uses an SSH reverse
forward and is useful for quality comparisons, not smooth playback.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
```

Transport tests cover malformed/truncated framing and simultaneous multi-megabyte
traffic through constrained socket buffers, fragmented H.264 boundaries,
multiple slices per frame, and a real ffmpeg encode/decode round trip.
Live display tests require the iPad and a running Hyprland session. Frame enqueue
counters measure submission to Apple's renderer, not panel presentation or
end-to-end latency. Native H.264 uses chroma subsampling; compare colored text
against the lossless baseline before treating text quality as finished.
