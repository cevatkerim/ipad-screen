# Project working agreements

- Commit logical milestones frequently so the investigation history is preserved.
  Describe what was actually validated, including unresolved failures.
- Targets: USB, mirror and extend, jailbroken iPad Pro 10.5 and iPad 9. Prioritize
  crisp text and balanced desktop use. Linux first; Mac and Windows host apps later.
- Read README.md, docs/investigation.md and docs/protocol.md before changing the
  transport or receiver. Do not call queued frame counts decoded/presented frames.
- Keep .env, passwords, receiver tokens, device IDs, SSH keys, screenshots and
  runtime logs out of commits. Device state lives in ignored .runtime/.
- Device actions must target the paired iPad. Preserve unrelated apps, keys and
  configuration. Temporary Hyprland outputs must be removed when sessions stop.
- Native rendering is verified on the Pro 10.5/iPadOS 17.7.10. The Pro 9.7 on
  16.7.16/Dopamine also accepts native extend/mirror streams without renderer
  errors; visual smoothness confirmation for that device is still pending. Treat iPad 9 and
  Mac/Windows support as unverified until tested on those actual devices.
