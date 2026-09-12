# Native receiver protocol v1

Development protocol shared by future Linux, Mac and Windows senders. An iPad
app listens on loopback TCP port 27184; the host connects over usbmux.

Host sends eight ASCII bytes `IPDS0001`, followed by the 64 ASCII hex characters
of the per-installation token (no newline). Receiver compares against its private
token file and responds with eight ASCII bytes `READY001`. Other connections
are closed. Tokens are installed over authenticated SSH and excluded from Git.

Each frame is a uint32 big-endian payload length followed by one complete H.264
access unit in AVCC form: repeated uint32 big-endian NAL length + NAL bytes.
Maximum frame payload: 8 MiB. Include SPS/PPS before an IDR at stream start and
after format changes. SPS determines dimensions. No B frames in the initial
sender. The receiver requests immediate presentation instead of timestamped
playout. The initial prototype supports one session and one frame in flight.

After each frame the receiver returns four big-endian uint32 counters:
received access units, a reserved zero field, images enqueued for display,
and rendering errors. The reserved field was a callback counter in the initial
manual-decoder experiment. The working receiver gives compressed samples to
AVSampleBufferDisplayLayer, which handles decoding and rendering internally.
Enqueue count does not prove physical panel presentation. These acknowledgments
bound frame submission and expose rendering failures; verify visible playback too.

Disconnect, malformed length, failed authentication or socket timeout ends a
session. The listener remains available while the app is foregrounded. On
reconnect the format resets and waits for SPS/PPS plus an IDR. Renderer congestion
or failure flushes the display queue and skips dependent frames until the next IDR.

This version does not implement audio, input, timestamp synchronization, codec
negotiation or encrypted transport independent of USB. Bind only to loopback;
do not expose this listener to the LAN. Hardware H.264 capability is queried
separately from decoder success; the iOS SDK does not expose the macOS-only
per-session hardware-selection property used by some examples.
