# aiagentctrl: Agent-Friendly PiCar-X Controller

SPDX-License-Identifier: GPL-2.0-or-later

What it is
- A single-file CLI to drive, steer, move the camera head (pan/tilt), read ultrasonic distance, and stop the SunFounder PiCar‑X.
- Outputs a one-line dict by default or exact JSON with `--json`.

Prereqs
- Run from the repository root so the local `picarx` module is importable.
- PiCar‑X 3.0.x stack (uses `fusion_hat`); also works with many legacy name variants.

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
- `ultrasonic`
  - Prints distance in centimeters as `distance_cm`.
- `stop`
  - Immediately stops motors.

Environment variables
- `PICARX_MAX_SPEED` (default 60): speed clamp for `drive`.
- `PICARX_MAX_ANGLE` (default 35): clamp for steering and pan/tilt.
- `PICARX_FAKE=1`: mock hardware for CI/dry‑run; returns plausible ultrasonic values.
- `PICARX_I2C_BUS`: override I2C bus if needed (e.g., `11` on some Pi 5 setups). If unset, the controller auto‑prefers bus 11 when `/dev/i2c-11` exists, otherwise bus 1.
 - `PICARX_PREFER_LOCAL` (default `1`): set to `0` to ignore the current repo module, useful when using a site‑installed or alternate checkout.
 - `PICARX_MODULE_DIR`: prepend a specific path to `sys.path` before import (e.g., point at a `v2.0` checkout directory).

Examples
- Plain shell
  - `python3 aiagentctrl.py --help`
  - `PICARX_FAKE=1 python3 aiagentctrl.py ultrasonic --json`
  - `python3 aiagentctrl.py steer --angle 20`
  - `python3 aiagentctrl.py head --pan -15 --tilt 10 --json`
  - `python3 aiagentctrl.py drive --speed 30 --seconds 0.5 --direction forward`

- Codex exec snippet
  - `PICARX_FAKE=1 python3 aiagentctrl.py steer --angle 999 --json`  # shows clamped value

Troubleshooting
- Import path: run from the repo root so `picarx` is resolved; `aiagentctrl.py` adds `.` to `sys.path` as a fallback.
- JSON output: add `--json` for a single JSON object on stdout.
- Motors keep running? Use `python3 aiagentctrl.py stop` or Ctrl‑C; the controller also stops on any error.
