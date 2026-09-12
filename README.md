# iPad Screen

Use a jailbroken iPad as a USB-connected second screen. Target devices are the
iPad Pro 10.5-inch and iPad (9th generation), with Linux first and dedicated Mac
and Windows host apps later. Both extended desktop and mirroring are in scope.
Priorities: crisp text, then balanced desktop motion and responsiveness.

## Current state

This is an investigation repository with an experimental Linux viewer, not a
finished display app. Passwordless SSH and native-resolution frame delivery to
Safari have been verified on the connected iPad Pro 10.5 running iPadOS 17.7.10.
The iPad 9 profile is implemented but has not been tested on that device.

The first successful 25-second extension test sent 16 lossless PNG frames at
2224×1668. This is a correctness baseline, too slow for normal desktop work.
Next: continuous capture and hardware-encoded H.264, followed by a native iPad
receiver. See [the investigation](docs/investigation.md) for evidence and the
platform plan.

## Linux setup

Requires Python 3, OpenSSH, libimobiledevice tools, a running usbmuxd, Hyprland
with Lua configuration support (tested on 0.56.2), and `grim`. The iPad must be
USB-connected, trusted, jailbroken, and running an SSH server as `mobile`.
Safari viewing requires an unlocked device.

```sh
./scripts/ipad.py devices
./scripts/ipad.py pair --udid YOUR_DEVICE_ID --env-file ../.env
./scripts/ipad.py ssh 'id -un'
```

Pairing reads `PASSWORD` literally from the supplied `.env`; it never sources
the file as shell code. It appends `~/.ssh/id_ed25519.pub` to the iPad's existing
authorized keys, then verifies a passwordless login. Use `--key PATH` to select
another existing key. The private key stays in its original location.

The first SSH host key is trusted on first use over the selected USB connection;
subsequent changes are rejected. Device selection and known hosts are stored in
the ignored `.runtime/` directory. Pair again with another UDID to switch the
active iPad; this prototype supports one display session at a time.

## Try the display

```sh
# iPad Pro 10.5: 2224×1668, desktop UI scale 2
./scripts/screen.py --mode extend

# iPad 9: 2160×1620, after pairing that device
./scripts/screen.py --mode extend --model ipad9

# Mirror the focused monitor, or explicitly choose an existing output
./scripts/screen.py --mode mirror
./scripts/screen.py --mode mirror --output eDP-1

# Bounded experiment; cleans up automatically
./scripts/screen.py --mode extend --seconds 30
```

Safari opens automatically. In extend mode the temporary `ipad-screen` monitor
appears to the right of existing monitors; move a window onto it using the normal
desktop controls. Use the host's keyboard and mouse. iPad touch controls the
viewer buttons only; desktop touch input is not implemented.

The Full screen button requests browser fullscreen. If unavailable, Safari's
Add to Home Screen flow may provide a larger viewport. The current session URL
changes each launch, so saved shortcuts are not yet reusable across sessions.
Safari chrome reduces the visible area and causes downscaling despite delivery
at native resolution; pixel-perfect presentation needs fullscreen or a native app.

Ctrl+C stops capture and forwarding, and removes the output created by this
session. No Hyprland configuration files are changed. A forced kill or host crash
can leave the output behind; inspect `hyprctl monitors -j` and then remove only
the project output with `hyprctl output remove ipad-screen` if necessary.

Listeners bind only to loopback. HTTP travels through SSH over USB; Wi-Fi and
personal hotspot are not required. The viewer uses a random per-session URL.
Frames stay in memory; only capability reports and aggregate transfer counts
are saved to `.runtime/last-session.json`. That directory and `.env` files are
excluded from Git.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
```

Transport tests cover malformed/truncated framing and simultaneous multi-megabyte
traffic through constrained socket buffers. Live display tests require the iPad
and a running Hyprland session. Mac/Windows apps and hardware video encoding are
not implemented yet.
