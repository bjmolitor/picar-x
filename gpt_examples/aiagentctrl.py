#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Purpose: Minimal, agent-friendly CLI to control SunFounder PiCar-X (drive, steer, head pan/tilt, ultrasonic),
# with safety clamps, signal-safe immediate stop, and JSON/human outputs. Compatible across 3.0.x and legacy names.

import argparse
import json
import os
import signal
import sys
import time
from typing import Any, Dict, Optional
from datetime import datetime


# ---- Globals for signal handling ----
_PX_OBJ = None  # set after we create the car instance
_STATE_PATH_DEFAULT = "/opt/picar-x/aiagentctrl_state.json"


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, str(default))
        return int(v)
    except Exception:
        return default


def _clamp(val: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, val))


def _safe_stop(px: Any) -> None:
    try:
        if px is None:
            return
        # Try best-effort stop using common names
        if hasattr(px, 'stop') and callable(getattr(px, 'stop')):
            px.stop()
        elif hasattr(px, 'motors') and hasattr(px.motors, 'set_power'):
            try:
                px.motors.set_power(0)
            except Exception:
                pass
    except Exception:
        pass


def _get_state_path() -> str:
    return os.environ.get("PICARX_STATE_FILE", _STATE_PATH_DEFAULT)


def _load_state() -> Dict[str, Any]:
    try:
        with open(_get_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    path = _get_state_path()
    tmp = path + ".tmp"
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        # fallback to home dir if /opt not writable
        try:
            home_fallback = os.path.join(os.path.expanduser("~"), ".aiagentctrl_state.json")
            with open(home_fallback, "w", encoding="utf-8") as f:
                json.dump(state, f, separators=(",", ":"))
        except Exception:
            pass


def _signal_handler(signum, frame):
    # Immediate stop and exit
    _safe_stop(_PX_OBJ)
    # Use standard shells' 128+signal exit code convention
    os._exit(128 + int(signum))


def _setup_signals():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


def _compat_patch_fusion_hat_modules():
    """Patch fusion_hat module layout differences for 3.0.x vs current.

    - Ensure fusion_hat.utils exposes LazyReader.
    - Provide fusion_hat.config module aliasing fusion_hat._config.Config.
    """
    try:
        import types, sys as _sys, contextlib, io
        # Patch utils for LazyReader, suppressing module's print
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                import fusion_hat.utils as fu  # type: ignore
            if not hasattr(fu, 'LazyReader'):
                try:
                    from fusion_hat._utils import LazyReader  # type: ignore
                    setattr(fu, 'LazyReader', LazyReader)
                except Exception:
                    pass
        except Exception:
            pass
        # Patch config module alias
        try:
            import importlib
            importlib.import_module('fusion_hat.config')
        except Exception:
            try:
                from fusion_hat import _config as _cfg  # type: ignore
                mod = types.ModuleType('fusion_hat.config')
                # Wrap to adapt signature: Config(config_file=...)
                def _CompatConfig(config_path: str = None, *a, **kw):  # type: ignore
                    # Allow both positional path and keyword config_file
                    if 'config_file' in kw:
                        return _cfg.Config(*a, **kw)
                    return _cfg.Config(*a, config_file=config_path, **kw)
                setattr(mod, 'Config', _CompatConfig)
                _sys.modules['fusion_hat.config'] = mod
            except Exception:
                pass
    except Exception:
        # Ignore; fake mode may not need this
        pass


def _compat_patch_picarx_music():
    """Provide a stub picarx.music to avoid I2C speaker init on import.

    The local PiCarX imports Music from picarx.music which, in turn, uses
    fusion_hat.music and enables the speaker via I2C. On systems without the
    HAT or I2C, this raises. Install a minimal stub before importing Picarx.
    """
    try:
        import types, sys as _sys
        if 'picarx.music' in _sys.modules:
            return  # already imported; avoid overriding

        class _StubMusic:
            def __init__(self):
                self._volume = 0
            def set_volume(self, v: int):
                self._volume = int(v)
            def stop(self):
                pass
            def play_sound_background(self, *a, **kw):
                pass

        class _StubSoundFiles:
            DOUBLE_HORN = 'DOUBLE_HORN'
            START_ENGINE = 'START_ENGINE'

        mod = types.ModuleType('picarx.music')
        setattr(mod, 'Music', _StubMusic)
        setattr(mod, 'SoundFiles', _StubSoundFiles)
        _sys.modules['picarx.music'] = mod
    except Exception:
        pass


def _maybe_set_i2c_bus_from_env_or_pi5():
    """Adjust fusion_hat I2C default bus.

    - If PICARX_I2C_BUS is set, use it.
    - Else, if /dev/i2c-11 exists (common on Pi 5), prefer 11.
    - Otherwise leave default (1).
    """
    try:
        import os as _os
        import fusion_hat._i2c as _i2c  # type: ignore
        env_bus = _os.environ.get('PICARX_I2C_BUS')
        if env_bus is not None and env_bus.strip() != '':
            _i2c.I2C.DEFAULT_BUS = int(env_bus)
            return
        if _os.path.exists('/dev/i2c-11'):
            _i2c.I2C.DEFAULT_BUS = 11
    except Exception:
        pass


# ---- Fake hardware for dry-run/CI ----
class _FakePicarx:
    def __init__(self):
        self._power = 0
        self._steering_angle = 0
        self._pan = 0
        self._tilt = 0

    # Drive
    def forward(self, power: float):
        self._power = float(_clamp(power, 0, 100))

    def backward(self, power: float):
        self._power = -float(_clamp(power, 0, 100))

    def stop(self):
        self._power = 0

    # Steering
    def set_steering_angle(self, angle: float):
        self._steering_angle = float(angle)

    # Head
    def set_camera_pan_angle(self, angle: float):
        self._pan = float(angle)

    def set_camera_tilt_angle(self, angle: float):
        self._tilt = float(angle)

    # Ultrasonic
    def get_distance(self) -> float:
        # Return a plausible, stable-ish value without flapping
        base = 30.0
        jitter = (time.time() * 1000.0) % 7  # 0..7
        return round(base + (jitter - 3.5), 2)


def _resolve_picarx_class():
    """Best-effort to obtain the PiCar-X class across versions/layouts.

    Tries these in order:
      - picarx.Picarx
      - picarx.PiCarX
      - picarx.PicarX
      - picarx.picarx.Picarx / PiCarX / PicarX
    Returns the class object or raises ImportError.
    """
    import importlib

    candidates = [
        ('picarx', 'Picarx'),
        ('picarx', 'PiCarX'),
        ('picarx', 'PicarX'),
        ('picarx.picarx', 'Picarx'),
        ('picarx.picarx', 'PiCarX'),
        ('picarx.picarx', 'PicarX'),
    ]
    last_err = None
    for mod_name, cls_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                return cls
        except Exception as e:
            last_err = e
            continue
    # If we got here, try importing the package, then attribute from submodule
    # Some packages set attribute on __init__ at runtime
    try:
        import importlib
        pkg = importlib.import_module('picarx')
        sub = importlib.import_module('picarx.picarx')
        for name in ('Picarx', 'PiCarX', 'PicarX'):
            cls = getattr(pkg, name, None) or getattr(sub, name, None)
            if cls is not None:
                return cls
    except Exception as e:
        last_err = e
    if last_err:
        raise ImportError(f"Could not locate Picarx class: {last_err}")
    raise ImportError("Could not locate Picarx class")


def _call_method(px: Any, names, *args, **kwargs):
    """Attempt a method call by trying a list of candidate names."""
    for name in names:
        if hasattr(px, name) and callable(getattr(px, name)):
            return getattr(px, name)(*args, **kwargs)
    raise AttributeError(f"None of the methods exist: {names}")


def _do_drive(px: Any, speed: int, seconds: float, direction: str, max_speed: int) -> Dict[str, Any]:
    # Clamp speed for safety
    sp = int(_clamp(speed, 0, max_speed))
    # Best-effort drive using common names; fallback to motors.set_power
    if direction == 'forward':
        try:
            _call_method(px, ['forward'], sp)
        except Exception:
            if hasattr(px, 'motors') and hasattr(px.motors, 'set_power'):
                px.motors.set_power(sp, getattr(px, 'steering_angle', 0))
            else:
                raise
    else:
        try:
            _call_method(px, ['backward'], sp)
        except Exception:
            if hasattr(px, 'motors') and hasattr(px.motors, 'set_power'):
                px.motors.set_power(-sp, getattr(px, 'steering_angle', 0))
            else:
                raise

    if seconds > 0:
        time.sleep(seconds)

    return {
        'ok': True,
        'action': 'drive',
        'direction': direction,
        'requested_speed': int(speed),
        'applied_speed': sp,
        'seconds': float(seconds),
        'max_speed': max_speed,
    }


def _do_steer(px: Any, angle: int, max_angle: int) -> Dict[str, Any]:
    a = int(_clamp(angle, -max_angle, max_angle))
    _call_method(px, ['set_steering_angle', 'steer', 'set_dir_servo_angle'], a)
    return {
        'ok': True,
        'action': 'steer',
        'requested_angle': int(angle),
        'applied_angle': a,
        'max_angle': max_angle,
    }


def _do_head(px: Any, pan: Optional[int], tilt: Optional[int], max_angle: int) -> Dict[str, Any]:
    applied: Dict[str, int] = {}
    state = _load_state()
    prev_head = state.get('head', {})

    target_pan = int(prev_head.get('pan', 0)) if pan is None else int(_clamp(pan, -max_angle, max_angle))
    target_tilt = int(prev_head.get('tilt', 0)) if tilt is None else int(_clamp(tilt, -max_angle, max_angle))

    _call_method(px, ['set_camera_pan_angle', 'set_cam_pan_angle', 'set_pan_angle'], target_pan)
    _call_method(px, ['set_camera_tilt_angle', 'set_cam_tilt_angle', 'set_tilt_angle'], target_tilt)

    if pan is not None:
        applied['pan'] = target_pan
    if tilt is not None:
        applied['tilt'] = target_tilt
    # Persist head state so it remains across commands
    try:
        state = _load_state()
        head = state.get('head', {})
        head['pan'] = target_pan
        head['tilt'] = target_tilt
        state['head'] = head
        _save_state(state)
    except Exception:
        pass
    return {
        'ok': True,
        'action': 'head',
        'requested_pan': None if pan is None else int(pan),
        'requested_tilt': None if tilt is None else int(tilt),
        'applied': applied,
        'max_angle': max_angle,
    }


def _do_snapshot(px: Any, out_path: Optional[str] = None, vflip: bool = False, hflip: bool = False) -> Dict[str, Any]:
    # Use vilib for camera handling (v2 stack includes vilib)
    try:
        from vilib import Vilib
    except Exception as e:
        return {'ok': False, 'action': 'snapshot', 'error': f'vilib import failed: {e}'}

    # Determine output path
    if out_path:
        out_dir = os.path.dirname(out_path)
        out_name = os.path.splitext(os.path.basename(out_path))[0]
    else:
        out_dir = os.path.join('/opt', 'picar-x', 'snapshots')
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        out_name = f'snap-{ts}'
        out_path = os.path.join(out_dir, out_name + '.jpg')
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        # Fallback to home Pictures directory
        home_dir = os.path.join(os.path.expanduser('~'), 'Pictures')
        os.makedirs(home_dir, exist_ok=True)
        out_dir = home_dir
        out_path = os.path.join(out_dir, out_name + '.jpg')

    try:
        Vilib.camera_start(vflip=bool(vflip), hflip=bool(hflip))
        # Small delay to warm up
        time.sleep(0.2)
        # Vilib.take_photo takes base name and path (dir)
        Vilib.take_photo(out_name, out_dir)
        # Attempt to close camera
        try:
            Vilib.camera_close()
        except Exception:
            pass
        return {'ok': True, 'action': 'snapshot', 'path': out_path}
    except Exception as e:
        return {'ok': False, 'action': 'snapshot', 'error': str(e), 'path': out_path}


def _do_ultrasonic(px: Any) -> Dict[str, Any]:
    distance_cm: Optional[float] = None
    err: Optional[str] = None
    try:
        if hasattr(px, 'ultrasonic'):
            u = px.ultrasonic
            # Avoid starting threads; read directly if possible
            if hasattr(u, 'read') and callable(getattr(u, 'read')):
                distance_cm = float(u.read())
            elif hasattr(u, 'get_value') and callable(getattr(u, 'get_value')):
                distance_cm = float(u.get_value())
        if distance_cm is None and hasattr(px, 'get_distance') and callable(px.get_distance):
            distance_cm = float(px.get_distance())
    except Exception as e:
        err = str(e)
    return {
        'ok': err is None,
        'action': 'ultrasonic',
        'distance_cm': distance_cm,
        'error': err,
    }


def _do_stop(px: Any) -> Dict[str, Any]:
    _safe_stop(px)
    return {'ok': True, 'action': 'stop'}


def _make_px(fake: bool):
    if fake:
        return _FakePicarx()
    # Prefer local project path unless disabled
    # Optional explicit module dir (e.g. to point at a v2 checkout)
    module_dir = os.environ.get('PICARX_MODULE_DIR')
    added_module_dir = False
    if module_dir:
        sys.path.insert(0, os.path.abspath(module_dir))
        added_module_dir = True
    prefer_local = os.environ.get('PICARX_PREFER_LOCAL', '1') != '0'
    added_local = False
    if prefer_local:
        sys.path.insert(0, os.path.abspath('.'))
        added_local = True
    # Ensure fusion_hat compatibility before importing picarx module
    _compat_patch_fusion_hat_modules()
    _compat_patch_picarx_music()
    _maybe_set_i2c_bus_from_env_or_pi5()
    try:
        cls = _resolve_picarx_class()
        try:
            return cls()
        except TypeError:
            return cls()
    except ImportError:
        # Fallback: try site-installed picarx by removing local path
        if added_local:
            try:
                sys.path.remove(os.path.abspath('.'))
            except ValueError:
                pass
        if added_module_dir:
            try:
                sys.path.remove(os.path.abspath(module_dir))
            except Exception:
                pass
        cls = _resolve_picarx_class()
        try:
            return cls()
        except TypeError:
            return cls()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Agent-friendly PiCar-X controller')
    parser.add_argument('--json', action='store_true', help='Print JSON output (single object)')

    sub = parser.add_subparsers(dest='command', required=True)

    p_drive = sub.add_parser('drive', help='Drive forward/backward at speed for seconds')
    p_drive.add_argument('--json', action='store_true', help=argparse.SUPPRESS)
    p_drive.add_argument('--speed', type=int, required=True, help='Speed 0..PICARX_MAX_SPEED')
    p_drive.add_argument('--seconds', type=float, default=0.0, help='Duration seconds (0=return immediately)')
    p_drive.add_argument('--direction', choices=['forward', 'backward'], required=True)

    p_steer = sub.add_parser('steer', help='Set steering angle')
    p_steer.add_argument('--json', action='store_true', help=argparse.SUPPRESS)
    p_steer.add_argument('--angle', type=int, required=True, help='Angle -PICARX_MAX_ANGLE..PICARX_MAX_ANGLE')

    p_head = sub.add_parser('head', help='Set head pan/tilt angles')
    p_head.add_argument('--json', action='store_true', help=argparse.SUPPRESS)
    p_head.add_argument('--pan', type=int, help='Pan angle -PICARX_MAX_ANGLE..PICARX_MAX_ANGLE')
    p_head.add_argument('--tilt', type=int, help='Tilt angle -PICARX_MAX_ANGLE..PICARX_MAX_ANGLE')

    p_ultra = sub.add_parser('ultrasonic', help='Read ultrasonic distance (cm)')
    p_ultra.add_argument('--json', action='store_true', help=argparse.SUPPRESS)
    p_stop = sub.add_parser('stop', help='Stop motors immediately')
    p_stop.add_argument('--json', action='store_true', help=argparse.SUPPRESS)

    p_snap = sub.add_parser('snapshot', help='Capture an image from the camera')
    p_snap.add_argument('--json', action='store_true', help=argparse.SUPPRESS)
    p_snap.add_argument('--path', type=str, help='Output image path (default: /opt/picar-x/snapshots/snap-<ts>.jpg)')
    p_snap.add_argument('--vflip', action='store_true', help='Vertical flip')
    p_snap.add_argument('--hflip', action='store_true', help='Horizontal flip')

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Safety clamps (defaults)
    max_speed = _env_int('PICARX_MAX_SPEED', 60)
    max_angle = _env_int('PICARX_MAX_ANGLE', 35)
    fake = os.environ.get('PICARX_FAKE', '0') == '1'

    _setup_signals()

    global _PX_OBJ
    _PX_OBJ = _make_px(fake)

    # Restore previously set head position so it persists across commands
    if args.command != 'head':
        try:
            st = _load_state().get('head', {})
            if 'pan' in st:
                _call_method(_PX_OBJ, ['set_camera_pan_angle', 'set_cam_pan_angle', 'set_pan_angle'], int(_clamp(st['pan'], -max_angle, max_angle)))
            if 'tilt' in st:
                _call_method(_PX_OBJ, ['set_camera_tilt_angle', 'set_cam_tilt_angle', 'set_tilt_angle'], int(_clamp(st['tilt'], -max_angle, max_angle)))
        except Exception:
            pass

    result: Dict[str, Any] = {'ok': False}

    try:
        if args.command == 'drive':
            # Additional immediate clamp for acceptance live tests if user forgets
            seconds = float(args.seconds)
            # Execute
            result = _do_drive(_PX_OBJ, args.speed, seconds, args.direction, max_speed)

        elif args.command == 'steer':
            result = _do_steer(_PX_OBJ, args.angle, max_angle)

        elif args.command == 'head':
            result = _do_head(_PX_OBJ, args.pan, args.tilt, max_angle)

        elif args.command == 'ultrasonic':
            result = _do_ultrasonic(_PX_OBJ)

        elif args.command == 'stop':
            result = _do_stop(_PX_OBJ)

        elif args.command == 'snapshot':
            result = _do_snapshot(_PX_OBJ, getattr(args, 'path', None), getattr(args, 'vflip', False), getattr(args, 'hflip', False))

        else:
            raise ValueError(f"Unknown command: {args.command}")

        result.setdefault('max_speed', max_speed)
        result.setdefault('max_angle', max_angle)

    except SystemExit:
        raise
    except Exception as e:
        result = {'ok': False, 'error': str(e), 'action': args.command}
    finally:
        # Dead-man stop after each command
        _safe_stop(_PX_OBJ)

    if args.json:
        print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))
    else:
        # Human-readable single-line dict
        print(result)
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
