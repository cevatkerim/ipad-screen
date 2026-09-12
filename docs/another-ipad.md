# Set up another USB iPad

Stop the current session with the bar's **Stop** button or Ctrl+C in its terminal.
Connect the new iPad with a data-capable USB cable, unlock it, and accept **Trust
This Computer**. Keep the device jailbroken and unlocked during setup.

## Prerequisites on each iPad

- A working rootless jailbreak, with OpenSSH installed and listening on port 22.
- Login as `mobile`, using that device's password. This project does not jailbreak
  devices or install SSH. Use your jailbreak's package manager for those steps.
- `/var/jb/usr/bin/uicache` and `/var/jb/usr/bin/uiopen` must exist. Rootful layouts
  are not supported by the current installer.
- iPadOS 15+ is the build target. Actual runtime compatibility must be tested;
  the Pro 10.5 on 17.7.10 was verified first.

## Pair and choose the correct profile

Run from the private `ipad-screen` checkout:

```sh
./scripts/ipad.py devices
ideviceinfo -u YOUR_DEVICE_ID -k ProductType
ideviceinfo -u YOUR_DEVICE_ID -k ProductVersion
```

Use the device ID printed by discovery. Avoid selecting a different connected
Apple device. Verify the model in Settings → General → About when uncertain:
“9.7-inch” and “9th generation” are different iPads.

| Profile | Device | Landscape resolution |
| --- | --- | --- |
| `pro105` | iPad Pro 10.5-inch | 2224×1668 |
| `pro97` | iPad Pro 9.7-inch | 2048×1536 |
| `ipad9` | iPad 9th generation | 2160×1620 |

The second device connected during development reported `iPad6,4`, iPadOS
16.7.16. It uses `pro97`. Its native pixel dimensions follow
[Apple's Pro 9.7 specifications](https://support.apple.com/en-la/111965).

Put the mobile password in a private `.env` outside the repository:

```text
PASSWORD=your-device-password
```

```sh
chmod 600 ../.env
./scripts/ipad.py pair --udid YOUR_DEVICE_ID --model pro97 --env-file ../.env
./scripts/ipad.py ssh 'id -un'
```

Choose the matching `--model` from the table. Pairing appends your existing
`~/.ssh/id_ed25519.pub` only when absent, preserving other keys. Use `--key PATH`
for another existing SSH key. If you have none, create one with `ssh-keygen -t
ed25519` first; do not overwrite an existing key. A passphrase-protected key must
be unlocked in your SSH agent for unattended app launch.

PASSWORD is parsed literally, never sourced as shell code. The first SSH host key
is accepted over the selected USB transport and saved locally. Subsequent changes
are rejected. Pairing is separate from Apple's USB trust dialog.

## Install the native app

```sh
# Needed once per app version, not for every iPad:
./scripts/build-app
# Targets only the active paired device:
./scripts/install-app.py
```

The builder needs clang, the iOS SDK and signing tools described in the README.
If `build/iPadScreen.app` is already built, reuse it for the next iPad. The installer
copies that bundle, registers its icon, provisions a random token for that device,
and requests launch. Open **iPad Screen** on the iPad if needed. The screen stays
black until a stream arrives; tap the small bottom-left display icon for status.

Test an animated pattern before using it for work:

```sh
./scripts/native.py --mode test --test-size 1280x720 --seconds 15
./scripts/native.py --mode extend --seconds 30
./scripts/native.py --mode mirror --seconds 15
```

Check that the image moves on the actual device, that `errors=0`, and that the
temporary monitor disappears afterward. Queued frame counts alone do not prove
visible playback. If hardware encoding fails, add `--encoder software` for the
desktop tests. If the app closes, inspect its own launch/crash diagnostics before
assuming the USB link is faulty.

## Use the Omarchy icon and switch back

Install the public [Omarchy plugin](https://github.com/cevatkerim/omarchy-ipad-screen)
and point its `control.py configure` command at this checkout. The bar automatically
uses the active device's saved model; it refreshes within five seconds.

Pairing another iPad saves both profiles in ignored `.runtime/devices.json` and
selects the new one in `.runtime/device.json`. Each new device has a separate
receiver token. The original prototype pairing retains its existing token.
To switch back, stop streaming, connect the previously paired iPad and run:

```sh
./scripts/ipad.py select --udid PREVIOUS_DEVICE_ID
```

No password or reinstall is needed unless the app, host pairing state, or device
was reset. Update the companion on each iPad separately when its code changes.
Never commit or publish `.runtime/`, `.env`, SSH keys, or copied device logs.

## Troubleshooting

- No device listed: check the cable, unlock/Trust, and that usbmuxd is installed.
- SSH refused: ensure the jailbreak is active and OpenSSH is running as expected.
- Host key changed: verify the selected physical device and investigate a reinstall
  before editing the project's known-hosts file.
- App installed but port unavailable: keep it foregrounded; try opening its icon
  and look for an immediate launch failure. It must reach its listening state.
- Receiver rejected handshake: run the installer for the selected device to
  provision its current token, then retry.
- A terminal session is running: stop it there before starting from the plugin.
- Leftover `ipad-screen` monitor after a forced kill: inspect `hyprctl monitors -j`
  and remove only that output with `hyprctl output remove ipad-screen`.

The plugin's log is `.runtime/plugin-session.log`; encoder diagnostics are in
`.runtime/encoder.log`. Stop from the panel or `systemctl --user stop ipad-screen`.
