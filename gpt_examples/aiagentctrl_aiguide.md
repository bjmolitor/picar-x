# aiagentctrl: Agent-Friendly PiCar-X Controller

SPDX-License-Identifier: GPL-2.0-or-later

What it is
- A single‑file CLI for SunFounder PiCar‑X v2.0 (robot_hat), to drive, steer, move the camera head (pan/tilt), read ultrasonic distance, capture camera snapshots, and stop.
- Outputs a one‑line dict by default or exact JSON with `--json`.

Prereqs
- v2.0 stack: uses `robot_hat` (I2C at 0x14 on bus 1) and `vilib` for camera.
- Run from repo root or install editable: `python3 -m pip install -e . --break-system-packages`.
- If not installing, prefix examples/CLI with `PYTHONPATH=.`.

Safety notes
- Motors always stop after each command (dead‑man stop), and on Ctrl‑C/SIGTERM.
- Values are clamped: speed ≤ `PICARX_MAX_SPEED` (default 60), angles within ±`PICARX_MAX_ANGLE` (default 35°).
- For any live tests, keep speed ≤ 35 and duration ≤ 1.0 s.

Command reference
- `drive --speed <int> --seconds <float, default 0.0> --direction {forward,backward}`
  - Speed is clamped to `0..PICARX_MAX_SPEED`.
  - Duration 0.0 returns immediately; motors still stop on command exit.
- `steer --angle <int>`
  - Angle clamped to `[-PICARX_MAX_ANGLE, PICARX_MAX_ANGLE]`.
- `head --pan <int?> --tilt <int?>`
  - Each angle clamped to `[-PICARX_MAX_ANGLE, PICARX_MAX_ANGLE]`.
  - Immediate movement; position persists until changed again (e.g., `--pan 0 --tilt 0`).
- `ultrasonic`
  - Prints distance in centimeters as `distance_cm`.
- `stop`
  - Immediately stops motors.
- `snapshot [--path <file>] [--vflip] [--hflip]`
  - Captures one image via `vilib`. Default path: `gpt_examples/aiagent_camera/snap-<timestamp>.jpg` (auto-created).

Environment variables
- `PICARX_MAX_SPEED` (default 60): speed clamp for `drive`.
- `PICARX_MAX_ANGLE` (default 35): clamp for steering and pan/tilt.
- `PICARX_FAKE=1`: mock hardware (no motion) with plausible `ultrasonic`.
- `PICARX_I2C_BUS` (default 1 on v2): override I2C bus.
- `PICARX_PREFER_LOCAL` (default `1`): set `0` to prefer site‑installed module.
- `PICARX_MODULE_DIR`: prepend a specific path to import (`v2.0` checkout, etc.).
- `PICARX_STATE_FILE`: file to persist head state (default `/opt/picar-x/aiagentctrl_state.json`).

Examples (v2)
- Plain shell
  - `python3 aiagentctrl.py --help`
  - `PICARX_PREFER_LOCAL=1 PICARX_I2C_BUS=1 python3 aiagentctrl.py drive --speed 30 --seconds 0.5 --direction forward --json`
  - `python3 aiagentctrl.py head --pan -12 --tilt 7 --json`  # smooth move and persist
  - `python3 aiagentctrl.py snapshot --path /home/admin/Pictures/test.jpg --json`
  - `PICARX_FAKE=1 python3 aiagentctrl.py steer --angle 999 --json`  # clamp demo

Troubleshooting
- Import path: install editable or prefix with `PYTHONPATH=.` from repo root.
- Ultrasonic: if returning negative/erratic, check sensor cabling and `robot_hat` I2C on bus 1.
- Camera: if snapshot hangs, verify camera is enabled and working (`example/7.display.py`), then re‑try.
- Motors keep running? Use `python3 aiagentctrl.py stop` or Ctrl‑C; the controller also stops on any error.
