"""OSC message parsers for DivingStation Protocol v2.

Reference: `docs/ds_protocol_v2.md` in the separately maintained
DivingStationProtocolSpecs repository.

Parsing rules (from the spec):
- The first argument of every message is ``int version``; clients must
  discard the **entire** message when version != 2.
- Messages containing any malformed record are discarded in full.
  Clients do not skip only the bad record or fill in defaults.
- Maximum 8 records per message.
- ``timestamp_ms`` is transmitted as two unsigned 32-bit ints (hi, lo)
  that the client reassembles as ``(hi << 32) | lo``.

Each ``parse_*_message()`` function accepts the argument tuple delivered
by python-osc and returns either a non-empty list of parsed data objects
or an empty list (whole-message discard).
"""

from __future__ import annotations

import math
from typing import List, Optional, Union

from ._models import (
    ERGONOMICS_COUNT,
    RAW_SENSOR_COUNT,
    SKELETON_NODE_COUNT,
    SKELETON_ROTATION_COUNT,
    ButtonStatus,
    ControllerData,
    DeviceConnectedState,
    DeviceFamilyType,
    ErgonomicsData,
    GloveData,
    DeviceColor,
    Quaternion,
    RawSensorData,
    RawSkeletonData,
    RetargetProfileInfo,
    SkeletonData,
    TrackingState,
    Transform,
    Vec3,
)

_MAX_RECORDS = 8
_PROTOCOL_VERSION = 2


# ---------------------------------------------------------------------------
# Low-level argument reader
# ---------------------------------------------------------------------------

class _Reader:
    """Cursor-based reader over an OSC argument tuple.

    All ``read_*`` methods advance the cursor and return the value, or raise
    ``_ParseError`` if the next argument is absent or has the wrong type.
    """

    __slots__ = ("_args", "_idx")

    def __init__(self, args: tuple) -> None:
        self._args = args
        self._idx = 0

    @property
    def remaining(self) -> int:
        return len(self._args) - self._idx

    def peek_type(self) -> Optional[type]:
        if self._idx >= len(self._args):
            return None
        return type(self._args[self._idx])

    def read_str(self) -> str:
        v = self._args[self._idx] if self._idx < len(self._args) else _MISSING
        if not isinstance(v, str):
            raise _ParseError(f"expected str, got {type(v).__name__}")
        self._idx += 1
        return v

    def read_int(self) -> int:
        v = self._args[self._idx] if self._idx < len(self._args) else _MISSING
        # bool is a subclass of int in Python; treat it as a type error
        if not isinstance(v, int) or isinstance(v, bool):
            raise _ParseError(f"expected int, got {type(v).__name__}")
        self._idx += 1
        return v

    def read_float(self) -> float:
        v = self._args[self._idx] if self._idx < len(self._args) else _MISSING
        if not isinstance(v, float):
            raise _ParseError(f"expected float, got {type(v).__name__}")
        self._idx += 1
        if not math.isfinite(v):
            raise _ParseError("float must be finite")
        return v

    def read_timestamp(self) -> int:
        """Read hi/lo pair and reassemble as ``(hi << 32) | lo``."""
        hi = self.read_int()
        lo = self.read_int()
        return ((hi & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


class _ParseError(Exception):
    """Raised internally to signal a malformed record or message."""


_MISSING = object()  # sentinel used in error messages


def _is_valid_profile_uuid(value: str) -> bool:
    """Return whether *value* has the protocol's ASCII UUID form."""
    if len(value) != 36:
        return False
    for index, char in enumerate(value):
        if index in (8, 13, 18, 23):
            if char != "-":
                return False
        elif char not in "0123456789abcdefABCDEF":
            return False
    return True


def _read_tracking_state(reader: _Reader) -> TrackingState:
    try:
        return TrackingState(reader.read_int())
    except ValueError as exc:
        raise _ParseError("invalid tracking state") from exc


def _read_bool(reader: _Reader) -> bool:
    """Read a protocol boolean, which is encoded strictly as integer 0 or 1."""
    value = reader.read_int()
    if value not in (0, 1):
        raise _ParseError("boolean field must be 0 or 1")
    return bool(value)


def _read_button_status(reader: _Reader) -> ButtonStatus:
    try:
        return ButtonStatus(reader.read_int())
    except ValueError as exc:
        raise _ParseError("invalid button status") from exc


def _read_device_type(reader: _Reader) -> DeviceFamilyType:
    try:
        device_type = DeviceFamilyType(reader.read_int())
    except ValueError as exc:
        raise _ParseError("invalid device type") from exc
    if device_type != DeviceFamilyType.ContactGlove3:
        raise _ParseError("DivingStationProtocol v2 supports ContactGlove3 only")
    return device_type


def _read_device_color(reader: _Reader) -> DeviceColor:
    try:
        return DeviceColor(reader.read_int())
    except ValueError as exc:
        raise _ParseError("invalid device color") from exc


def _read_connected_state(reader: _Reader) -> DeviceConnectedState:
    try:
        return DeviceConnectedState(reader.read_int())
    except ValueError as exc:
        raise _ParseError("invalid connected state") from exc


def _is_in_range(value: float, minimum: float, maximum: float) -> bool:
    return math.isfinite(value) and minimum <= value <= maximum


def _read_valid_quaternion(reader: _Reader) -> Quaternion:
    quaternion = Quaternion(
        reader.read_float(), reader.read_float(), reader.read_float(), reader.read_float()
    )
    norm_squared = (
        quaternion.w * quaternion.w
        + quaternion.x * quaternion.x
        + quaternion.y * quaternion.y
        + quaternion.z * quaternion.z
    )
    if not math.isfinite(norm_squared) or abs(norm_squared - 1.0) > 0.01:
        raise _ParseError("quaternion must be normalized")
    return quaternion


def _read_skeleton_values(
    reader: _Reader, data: Union[SkeletonData, RawSkeletonData]
) -> None:
    """Populate the position and rotation fields shared by skeleton models."""
    positions = [
        Vec3(reader.read_float(), reader.read_float(), reader.read_float())
        for _ in range(SKELETON_NODE_COUNT)
    ]
    rotations = [_read_valid_quaternion(reader) for _ in range(SKELETON_ROTATION_COUNT)]
    # Keeping the decoder shared ensures both skeleton streams use identical
    # wire validation.
    data.positions = positions
    data.rotations = rotations


# ---------------------------------------------------------------------------
# Version and length validation helpers
# ---------------------------------------------------------------------------

def _check_version(args: tuple) -> None:
    """Raise _ParseError when version is absent or != 2."""
    if not args:
        raise _ParseError("empty message")
    v = args[0]
    if not isinstance(v, int) or isinstance(v, bool):
        raise _ParseError("version field must be int")
    if v != _PROTOCOL_VERSION:
        raise _ParseError(f"unsupported version {v}")


def _check_record_count(payload_len: int, record_len: int) -> int:
    """Validate that payload is an exact multiple of record_len and ≤ max.

    Returns the number of records.  Raises _ParseError otherwise.
    """
    if payload_len % record_len != 0:
        raise _ParseError(
            f"payload length {payload_len} is not a multiple of {record_len}"
        )
    n = payload_len // record_len
    if n > _MAX_RECORDS:
        raise _ParseError(f"record count {n} exceeds maximum {_MAX_RECORDS}")
    return n


# ---------------------------------------------------------------------------
# /DS2/HC/Device  — 10 fields per record
# ---------------------------------------------------------------------------
# int version, (string id, string pair_id,
#   int battery_percentage, int is_haptics, int is_left,
#   int device_type, int color, int connected_state,
#   string name, int is_external_power_present)*
# Total: 1 + 10n

_DEVICE_RECORD_LEN = 10


def parse_device_message(args: tuple) -> List[GloveData]:
    try:
        _check_version(args)
        payload = args[1:]
        n = _check_record_count(len(payload), _DEVICE_RECORD_LEN)
        result: List[GloveData] = []
        r = _Reader(payload)
        for _ in range(n):
            g = GloveData()
            g.id = r.read_str()
            g.pair_id = r.read_str()
            g.battery_percentage = r.read_int()
            if g.battery_percentage != -1 and not 0 <= g.battery_percentage <= 100:
                raise _ParseError("battery percentage must be -1 or between 0 and 100")
            g.is_haptics = _read_bool(r)
            g.is_left = _read_bool(r)
            g.device_type = _read_device_type(r)
            g.color = _read_device_color(r)
            g.connected_state = _read_connected_state(r)
            g.name = r.read_str()
            g.is_external_power_present = _read_bool(r)
            result.append(g)
        return result
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/Controller  — 15 fields per record
# ---------------------------------------------------------------------------
# int version, (string id, int is_left,
#   int a, int b, int sys,
#   int trigger_button, int joystick_button, int trackpad_button,
#   float trigger, float grip_value, float grip_force,
#   float joystick_x, float joystick_y,
#   float trackpad_x, float trackpad_y)*
# Total: 1 + 15n

_CONTROLLER_RECORD_LEN = 15


def parse_controller_message(args: tuple) -> List[ControllerData]:
    try:
        _check_version(args)
        payload = args[1:]
        n = _check_record_count(len(payload), _CONTROLLER_RECORD_LEN)
        result: List[ControllerData] = []
        r = _Reader(payload)
        for _ in range(n):
            c = ControllerData()
            c.id = r.read_str()
            c.is_left = _read_bool(r)
            c.a_button = _read_button_status(r)
            c.b_button = _read_button_status(r)
            c.sys_button = _read_button_status(r)
            c.trigger_button = _read_button_status(r)
            c.joystick_button = _read_button_status(r)
            c.trackpad_button = _read_button_status(r)
            c.trigger = r.read_float()
            c.grip_value = r.read_float()
            c.grip_force = r.read_float()
            c.joystick_x = r.read_float()
            c.joystick_y = r.read_float()
            c.trackpad_x = r.read_float()
            c.trackpad_y = r.read_float()
            if not (
                _is_in_range(c.trigger, 0.0, 1.0)
                and _is_in_range(c.grip_value, 0.0, 1.0)
                and _is_in_range(c.grip_force, 0.0, 1.0)
                and _is_in_range(c.joystick_x, -1.0, 1.0)
                and _is_in_range(c.joystick_y, -1.0, 1.0)
                and _is_in_range(c.trackpad_x, -1.0, 1.0)
                and _is_in_range(c.trackpad_y, -1.0, 1.0)
            ):
                raise _ParseError("controller analog value is out of range")
            result.append(c)
        return result
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/Ergonomics  — 25 fields per record
# ---------------------------------------------------------------------------
# int version, (string id, int is_left,
#   int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
#   float[20])*
# Total: 1 + 25n

_ERGONOMICS_RECORD_LEN = 25  # 1 str + 4 int + 20 float


def parse_ergonomics_message(args: tuple) -> List[ErgonomicsData]:
    try:
        _check_version(args)
        payload = args[1:]
        n = _check_record_count(len(payload), _ERGONOMICS_RECORD_LEN)
        result: List[ErgonomicsData] = []
        r = _Reader(payload)
        for _ in range(n):
            e = ErgonomicsData()
            e.id = r.read_str()
            e.is_left = _read_bool(r)
            e.timestamp_ms = r.read_timestamp()
            e.tracking_state = _read_tracking_state(r)
            e.values = [r.read_float() for _ in range(ERGONOMICS_COUNT)]
            result.append(e)
        return result
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/HandSkeleton  — one 157-field record per message
# ---------------------------------------------------------------------------
# int version, string id, string profile_uuid, int is_left,
#   int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
#   float[75]   # 25 nodes × (p_x, p_y, p_z)
#   float[76]   # 19 nodes × (q_w, q_x, q_y, q_z)
# Total: 158

def parse_handskeleton_message(args: tuple) -> List[SkeletonData]:
    try:
        _check_version(args)
        r = _Reader(args[1:])
        s = SkeletonData()
        s.id = r.read_str()
        s.profile_uuid = r.read_str()
        if not _is_valid_profile_uuid(s.profile_uuid):
            raise _ParseError("invalid profile UUID")
        s.is_left = _read_bool(r)
        s.timestamp_ms = r.read_timestamp()
        s.tracking_state = _read_tracking_state(r)
        _read_skeleton_values(r, s)
        if r.remaining != 0:
            raise _ParseError("unexpected HandSkeleton arguments")
        return [s]
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/HandSkeletonRaw  — one 156-field record per message
# ---------------------------------------------------------------------------

def parse_rawskeleton_message(args: tuple) -> List[RawSkeletonData]:
    try:
        _check_version(args)
        r = _Reader(args[1:])
        s = RawSkeletonData()
        s.id = r.read_str()
        s.is_left = _read_bool(r)
        s.timestamp_ms = r.read_timestamp()
        s.tracking_state = _read_tracking_state(r)
        _read_skeleton_values(r, s)
        if r.remaining != 0:
            raise _ParseError("unexpected HandSkeletonRaw arguments")
        return [s]
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/HandSkeleton/Profile  — one response per message
# ---------------------------------------------------------------------------

def parse_retarget_profile_info_message(args: tuple) -> List[RetargetProfileInfo]:
    try:
        _check_version(args)
        r = _Reader(args[1:])
        info = RetargetProfileInfo(
            request_id=r.read_int(),
            profile_uuid=r.read_str(),
            status=r.read_int(),
            name=r.read_str(),
            description=r.read_str(),
        )
        if r.remaining != 0:
            raise _ParseError("unexpected profile response arguments")
        if info.status == 0:
            if not _is_valid_profile_uuid(info.profile_uuid):
                raise _ParseError("invalid successful profile response")
        elif info.status == 1:
            if (
                not _is_valid_profile_uuid(info.profile_uuid)
                or info.name
                or info.description
            ):
                raise _ParseError("invalid missing-profile response")
        elif info.status == 2:
            if info.profile_uuid or info.name or info.description:
                raise _ParseError("invalid rejected-profile response")
        else:
            raise _ParseError("invalid profile response status")
        return [info]
    except _ParseError:
        return []


# ---------------------------------------------------------------------------
# /DS2/HC/RawSensorTransforms  — 39 fields per record
# ---------------------------------------------------------------------------
# int version, (string id, int is_left,
#   int generated_at_ms_hi, int generated_at_ms_lo,
#   float[35]   # 5 sensors × (p_x, p_y, p_z, q_w, q_x, q_y, q_z)
# )*
# Total: 1 + 39n

_RAWSENSOR_RECORD_LEN = (
    1              # id (str)
    + 3            # is_left, hi, lo (int)
    + RAW_SENSOR_COUNT * 7  # transforms (float)
)  # = 39


def parse_rawsensor_message(args: tuple) -> List[RawSensorData]:
    try:
        _check_version(args)
        payload = args[1:]
        n = _check_record_count(len(payload), _RAWSENSOR_RECORD_LEN)
        result: List[RawSensorData] = []
        r = _Reader(payload)
        for _ in range(n):
            d = RawSensorData()
            d.id = r.read_str()
            d.is_left = _read_bool(r)
            d.timestamp_ms = r.read_timestamp()
            d.transforms = [
                Transform(
                    position=Vec3(r.read_float(), r.read_float(), r.read_float()),
                    rotation=_read_valid_quaternion(r),
                )
                for _ in range(RAW_SENSOR_COUNT)
            ]
            result.append(d)
        return result
    except _ParseError:
        return []
