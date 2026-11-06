"""Data models for DivingStation Protocol v2.

Every model maps directly onto the wire format defined in
`docs/ds_protocol_v2.md` in the separately maintained
DivingStationProtocolSpecs repository.

The docstrings in this module are also used as the input for generating
`api.md` (see `scripts/gen_api_doc.py`). Descriptions of classes, enum
members and module constants are written as string literals placed
immediately after their target (attribute docstrings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKELETON_NODE_COUNT = 25
"""Number of skeleton position elements per hand"""

SKELETON_ROTATION_COUNT = 19
"""Number of skeleton rotation elements per hand (the wrist and the 5 fingertip nodes are excluded)"""

ERGONOMICS_COUNT = 20
"""Number of ergonomics data elements per hand (5 fingers × 4 joints)"""

RAW_SENSOR_COUNT = 5
"""Number of raw sensor Transforms per hand (one per finger)"""

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DeviceFamilyType(IntEnum):
    """Enum representing the kind of device

    Corresponds to the `device_type` field of `/DS2/HC/Device`.
    ContactGlove3 is the primary target.
    """

    ContactGlove = 0
    """ContactGlove"""
    ContactSheet = 1
    """ContactSheet"""
    ContactGlove2 = 2
    """ContactGlove2"""
    ContactGlove3 = 3
    """ContactGlove3"""


class LedColor(IntEnum):
    """Enum representing the device display-color setting

    Corresponds to the `color` field of `/DS2/HC/Device`.
    **Migrating the display-color type name**

    The public display-color type is `DeviceColor`. Replace the old import with
    `from contactglovesdk import DeviceColor` and update references such as
    `LedColor.Green` to `DeviceColor.Green`. The `GloveData.color` field name,
    numeric color values, and OSC wire format stay the same.

    `LedColor` remains an exported compatibility alias of `DeviceColor`, so
    existing imports still work. Prefer `DeviceColor` for new code.
    Serialized enum values retain the `LedColor` identity for interoperability
    with older processes.
    """

    Magenta = 0
    """Magenta"""
    Red = 1
    """Red"""
    Orange = 2
    """Orange"""
    Yellow = 3
    """Yellow"""
    Green = 4
    """Green"""
    Cyan = 5
    """Cyan"""
    Blue = 6
    """Blue"""
    Achromatic = 7
    """Achromatic"""


DeviceColor = LedColor
"""Preferred public name for the display-color enum; preserves its serialized identity."""


class DeviceConnectedState(IntEnum):
    """Enum representing the connection state of the device

    Corresponds to the `connected_state` field of `/DS2/HC/Device`.
    """

    Unknown = 0
    """State unknown"""
    Connected = 1
    """Connected"""
    Unconnected = 2
    """Not connected"""
    Pairing = 3
    """Attempting to connect"""


class ButtonStatus(IntEnum):
    """Enum representing the press state of a button

    Corresponds to each button field of `/DS2/HC/Controller`.
    """

    Unpressed = 0
    """Not pressed"""
    Touching = 1
    """Touched (detected by the touch sensor)"""
    Pressed = 2
    """Pressed"""


class TrackingState(IntEnum):
    """Enum representing the tracking state of IK-derived data.

    Corresponds to the `tracking_state` field of `/DS2/HC/Ergonomics`,
    `/DS2/HC/HandSkeleton` and `/DS2/HC/HandSkeletonRaw`.
    Values marked `IkFailed` or `NotAttempted` may be used for display and
    diagnostics, but must not be used for control, velocity estimation or
    interpolation. Only `Tracked` values are valid for those uses.

    `NotAttempted` means the required IK pass was not performed. It includes
    earlier processing failures or missing input, and cases where pose calculation
    was deemed unnecessary, such as update-interval control reusing an existing
    pose. This state does not itself indicate an IK failure.

    `SkeletonData` reports retarget IK; `RawSkeletonData` and `ErgonomicsData`
    report source-skeleton IK. Their states can differ at the same time.
    """

    Tracked = 0
    """A valid value obtained from the current IK pass"""
    IkFailed = 1
    """A value for which the IK pass was attempted but failed"""
    NotAttempted = 2
    """A value for which IK was not performed, including intentional update-interval skips as well as earlier failures or missing input"""


class ErgonomicsIndex(IntEnum):
    """Enum indicating the joint that each element of `ErgonomicsData.values` represents

    The indices cover one hand (`ERGONOMICS_COUNT` = 20 elements), and
    `values[i]` corresponds to `ErgonomicsIndex(i)`. Values are in degrees,
    and a bending angle is 0 degrees when the finger is extended.
    """

    ThumbCMC = 0
    """Bending angle of the thumb CMC joint"""
    ThumbMCP = 1
    """Bending angle of the thumb MCP joint"""
    ThumbIP = 2
    """Bending angle of the thumb IP joint"""
    ThumbTilt = 3
    """Tilt angle of the thumb MCP joint"""
    IndexMCP = 4
    """Bending angle of the index finger MCP joint"""
    IndexPIP = 5
    """Bending angle of the index finger PIP joint"""
    IndexDIP = 6
    """Bending angle of the index finger DIP joint"""
    IndexTilt = 7
    """Tilt angle of the index finger MCP joint"""
    MiddleMCP = 8
    """Bending angle of the middle finger MCP joint"""
    MiddlePIP = 9
    """Bending angle of the middle finger PIP joint"""
    MiddleDIP = 10
    """Bending angle of the middle finger DIP joint"""
    MiddleTilt = 11
    """Tilt angle of the middle finger MCP joint"""
    RingMCP = 12
    """Bending angle of the ring finger MCP joint"""
    RingPIP = 13
    """Bending angle of the ring finger PIP joint"""
    RingDIP = 14
    """Bending angle of the ring finger DIP joint"""
    RingTilt = 15
    """Tilt angle of the ring finger MCP joint"""
    LittleMCP = 16
    """Bending angle of the little finger MCP joint"""
    LittlePIP = 17
    """Bending angle of the little finger PIP joint"""
    LittleDIP = 18
    """Bending angle of the little finger DIP joint"""
    LittleTilt = 19
    """Tilt angle of the little finger MCP joint"""


class SkeletonNode(IntEnum):
    """Enum indicating the joint that each element of `SkeletonData.positions` represents

    The indices cover one hand (`SKELETON_NODE_COUNT` = 25 elements), and
    `positions[i]` corresponds to `SkeletonNode(i)`.
    """

    Wrist = 0
    """Wrist"""
    ThumbCMC = 1
    """Thumb CMC joint"""
    ThumbMCP = 2
    """Thumb MCP joint"""
    ThumbIP = 3
    """Thumb IP joint"""
    ThumbTip = 4
    """Thumb tip"""
    IndexCMC = 5
    """Index finger CMC joint"""
    IndexMCP = 6
    """Index finger MCP joint"""
    IndexPIP = 7
    """Index finger PIP joint"""
    IndexDIP = 8
    """Index finger DIP joint"""
    IndexTip = 9
    """Index finger tip"""
    MiddleCMC = 10
    """Middle finger CMC joint"""
    MiddleMCP = 11
    """Middle finger MCP joint"""
    MiddlePIP = 12
    """Middle finger PIP joint"""
    MiddleDIP = 13
    """Middle finger DIP joint"""
    MiddleTip = 14
    """Middle finger tip"""
    RingCMC = 15
    """Ring finger CMC joint"""
    RingMCP = 16
    """Ring finger MCP joint"""
    RingPIP = 17
    """Ring finger PIP joint"""
    RingDIP = 18
    """Ring finger DIP joint"""
    RingTip = 19
    """Ring finger tip"""
    LittleCMC = 20
    """Little finger CMC joint"""
    LittleMCP = 21
    """Little finger MCP joint"""
    LittlePIP = 22
    """Little finger PIP joint"""
    LittleDIP = 23
    """Little finger DIP joint"""
    LittleTip = 24
    """Little finger tip"""


class SkeletonRotationNode(IntEnum):
    """Enum indicating the joint that each element of `SkeletonData.rotations` represents

    The indices cover one hand (`SKELETON_ROTATION_COUNT` = 19 elements), and
    `rotations[i]` corresponds to `SkeletonRotationNode(i)`.
    Unlike `SkeletonNode`, the wrist and the 5 fingertip nodes are excluded
    because they carry no rotation value.
    """

    ThumbCMC = 0
    """Thumb CMC joint"""
    ThumbMCP = 1
    """Thumb MCP joint"""
    ThumbIP = 2
    """Thumb IP joint"""
    IndexCMC = 3
    """Index finger CMC joint"""
    IndexMCP = 4
    """Index finger MCP joint"""
    IndexPIP = 5
    """Index finger PIP joint"""
    IndexDIP = 6
    """Index finger DIP joint"""
    MiddleCMC = 7
    """Middle finger CMC joint"""
    MiddleMCP = 8
    """Middle finger MCP joint"""
    MiddlePIP = 9
    """Middle finger PIP joint"""
    MiddleDIP = 10
    """Middle finger DIP joint"""
    RingCMC = 11
    """Ring finger CMC joint"""
    RingMCP = 12
    """Ring finger MCP joint"""
    RingPIP = 13
    """Ring finger PIP joint"""
    RingDIP = 14
    """Ring finger DIP joint"""
    LittleCMC = 15
    """Little finger CMC joint"""
    LittleMCP = 16
    """Little finger MCP joint"""
    LittlePIP = 17
    """Little finger PIP joint"""
    LittleDIP = 18
    """Little finger DIP joint"""


class RawSensorIndex(IntEnum):
    """Enum indicating the sensor that each element of `RawSensorData.transforms` represents

    The indices cover one hand (`RAW_SENSOR_COUNT` = 5 elements), and
    `transforms[i]` corresponds to `RawSensorIndex(i)`.
    """

    Thumb = 0
    """Thumb"""
    Index = 1
    """Index finger"""
    Middle = 2
    """Middle finger"""
    Ring = 3
    """Ring finger"""
    Little = 4
    """Little finger"""


# ---------------------------------------------------------------------------
# Primitive geometry types
# ---------------------------------------------------------------------------


@dataclass
class Vec3:
    """Three-dimensional vector"""

    x: float = 0.0
    """X component"""
    y: float = 0.0
    """Y component"""
    z: float = 0.0
    """Z component"""


@dataclass
class Quaternion:
    """Quaternion representing a rotation"""

    w: float = 1.0
    """Scalar component"""
    x: float = 0.0
    """X component"""
    y: float = 0.0
    """Y component"""
    z: float = 0.0
    """Z component"""


@dataclass
class Transform:
    """Transform combining a position and a rotation

    Used as each element of `RawSensorData.transforms`.
    """

    position: Vec3 = field(default_factory=Vec3)
    """Position"""
    rotation: Quaternion = field(default_factory=Quaternion)
    """Rotation"""


# ---------------------------------------------------------------------------
# Connection info
# ---------------------------------------------------------------------------


@dataclass
class Host:
    """Data class holding the host information of DivingStation

    Passed to `connect_to_host()` / `disconnect()`. The receive port on the
    SDK (local) side is managed by `ContactGloveClient`, so it is not part of
    this class.
    """

    host_name: str
    """Host name (for example `"localhost"`)"""
    ip_address: str
    """IP address (for example `"127.0.0.1"`)"""
    port: int = 25791
    """OSC receive port number on the DivingStation side"""


# ---------------------------------------------------------------------------
# Data models (one per OSC address)
# ---------------------------------------------------------------------------


@dataclass
class GloveData:
    """Data class holding the information of a glove device

    Corresponds to the data received from the OSC address `/DS2/HC/Device`.

    Record layout (10 fields per device)::

        string id, string pair_id,
        int battery_percentage, int is_haptics, int is_left,
        int device_type, int color, int connected_state,
        string name, int is_external_power_present
    """

    id: str = ""
    """Device ID"""
    pair_id: str = ""
    """ID of the paired glove (an empty string if there is none)"""
    battery_percentage: int = -1
    """Remaining battery level [0 - 100]. -1 means an invalid value"""
    is_haptics: bool = False
    """Whether the haptics feature is present"""
    is_left: bool = False
    """Whether this is a left-hand glove"""
    device_type: DeviceFamilyType = DeviceFamilyType.ContactGlove
    """Kind of device"""
    color: DeviceColor = DeviceColor.Achromatic
    """Device display-color setting"""
    connected_state: DeviceConnectedState = DeviceConnectedState.Unknown
    """Connection state"""
    name: str = ""
    """Device name"""
    is_external_power_present: bool = False
    """Whether external power is detected"""


@dataclass
class ControllerData:
    """Data class holding the input state of the controller

    Corresponds to the data received from the OSC address `/DS2/HC/Controller`.

    Record layout (15 fields per controller)::

        string id, int is_left,
        int a, int b, int sys,
        int trigger_button, int joystick_button, int trackpad_button,
        float trigger, float grip_value, float grip_force,
        float joystick_x, float joystick_y,
        float trackpad_x, float trackpad_y
    """

    id: str = ""
    """Glove ID"""
    is_left: bool = False
    """Whether this is the left hand"""
    a_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the A button"""
    b_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the B button"""
    sys_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the system button"""
    trigger_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the trigger button"""
    joystick_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the joystick button"""
    trackpad_button: ButtonStatus = ButtonStatus.Unpressed
    """Press state of the trackpad touch"""
    trigger: float = 0.0
    """Trigger value (0.0 to 1.0)"""
    grip_value: float = 0.0
    """Grip value (0.0 to 1.0)"""
    grip_force: float = 0.0
    """Grip force (0.0 to 1.0)"""
    joystick_x: float = 0.0
    """Joystick X axis value (-1.0 to 1.0)"""
    joystick_y: float = 0.0
    """Joystick Y axis value (-1.0 to 1.0)"""
    trackpad_x: float = 0.0
    """Trackpad X axis value (-1.0 to 1.0)"""
    trackpad_y: float = 0.0
    """Trackpad Y axis value (-1.0 to 1.0)"""


@dataclass
class ErgonomicsData:
    """Data class holding the finger opening and bending angle data

    Corresponds to the data received from the OSC address `/DS2/HC/Ergonomics`.

    Record layout (25 fields per hand)::

        string id, int is_left,
        int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
        float[20] values

    `values[i]` corresponds to `ErgonomicsIndex(i)`.
    Angles are in degrees, and a bending angle is 0 degrees when the finger
    is extended.
    """

    id: str = ""
    """Glove ID"""
    is_left: bool = False
    """Whether this is the left hand"""
    timestamp_ms: int = 0
    """Time at which the frame was generated (Unix time, milliseconds)"""
    tracking_state: TrackingState = TrackingState.Tracked
    """IK-derived tracking state"""
    values: List[float] = field(default_factory=lambda: [0.0] * ERGONOMICS_COUNT)
    """Opening and bending angle value per joint (20 elements per hand, degrees)"""


@dataclass
class SkeletonData:
    """Data class holding the hand skeleton data (joint positions and rotations)

    Corresponds to the data received from the OSC address `/DS2/HC/HandSkeleton`.

    Record layout (one record per message, 157 fields)::

        string id, string profile_uuid, int is_left,
        int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
        float[75]  # 25 nodes × (p_x, p_y, p_z)
        float[76]  # 19 nodes × (q_w, q_x, q_y, q_z)

    `positions[i]` corresponds to `SkeletonNode(i)` (25 elements).
    `rotations[i]` corresponds to `SkeletonRotationNode(i)` (19 elements; the
    wrist and the 5 fingertip nodes are excluded).

    Positions are in meters and are expressed in model-rooted space (the
    coordinate system whose origin is the wrist). Rotations are local
    quaternions relative to the parent node.
    """

    id: str = ""
    """Glove ID"""
    profile_uuid: str = ""
    """Fixed UUID of the retarget profile"""
    is_left: bool = False
    """Whether this is the left hand"""
    timestamp_ms: int = 0
    """Time at which the frame was generated (Unix time, milliseconds)"""
    tracking_state: TrackingState = TrackingState.Tracked
    """Tracking state derived from the retarget IK"""
    positions: List[Vec3] = field(
        default_factory=lambda: [Vec3() for _ in range(SKELETON_NODE_COUNT)]
    )
    """Position per node (25 elements). See `SkeletonNode` for the indices"""
    rotations: List[Quaternion] = field(
        default_factory=lambda: [Quaternion() for _ in range(SKELETON_ROTATION_COUNT)]
    )
    """Rotation per node (19 elements). See `SkeletonRotationNode` for the indices"""


@dataclass
class RawSkeletonData:
    """Data class holding the hand skeleton data before retargeting.

    Corresponds to the data received from the OSC address
    `/DS2/HC/HandSkeletonRaw`. There is one record per message, and it has the
    same position and rotation layout as `SkeletonData` except for
    `profile_uuid`.
    """

    id: str = ""
    """Glove ID"""
    is_left: bool = False
    """Whether this is the left hand"""
    timestamp_ms: int = 0
    """Time at which the frame was generated (Unix time, milliseconds)"""
    tracking_state: TrackingState = TrackingState.Tracked
    """Tracking state derived from the IK of the source skeleton"""
    positions: List[Vec3] = field(
        default_factory=lambda: [Vec3() for _ in range(SKELETON_NODE_COUNT)]
    )
    """Position per node (25 elements). See `SkeletonNode` for the indices"""
    rotations: List[Quaternion] = field(
        default_factory=lambda: [Quaternion() for _ in range(SKELETON_ROTATION_COUNT)]
    )
    """Rotation per node (19 elements). See `SkeletonRotationNode` for the indices"""


@dataclass
class RetargetProfileInfo:
    """Data class holding the response that carries retarget profile information.

    Corresponds to the data received from the OSC address
    `/DS2/HC/HandSkeleton/Profile`.
    `status` is 0 (present), 1 (the UUID is valid but no such profile exists)
    or 2 (malformed query).
    """

    request_id: int = 0
    """Client-supplied value that correlates a request with its response"""
    profile_uuid: str = ""
    """Retarget profile UUID, depending on the status"""
    status: int = 0
    """Result of retrieving the profile information (0, 1, 2)"""
    name: str = ""
    """User-facing profile name"""
    description: str = ""
    """Description of the profile"""


@dataclass
class RawSensorData:
    """Data class holding the raw sensor Transform data for one hand

    Corresponds to the data received from the OSC address
    `/DS2/HC/RawSensorTransforms`. Each Transform is expressed in the same
    right-handed model-rooted space as `/DS2/HC/HandSkeleton`. The position is
    the sensor center position with the `wrist` as the origin, and the
    rotation is the orientation from the sensor local frame to model-rooted
    space.

    Record layout (39 fields per hand)::

        string id, int is_left,
        int generated_at_ms_hi, int generated_at_ms_lo,
        float[35]  # 5 sensors × (p_x, p_y, p_z, q_w, q_x, q_y, q_z)

    `transforms[i]` corresponds to `RawSensorIndex(i)` (5 elements, in the
    order thumb, index finger, middle finger, ring finger, little finger).
    """

    id: str = ""
    """Glove ID"""
    is_left: bool = False
    """Whether this is the left hand"""
    timestamp_ms: int = 0
    """Time at which the frame was generated (Unix time, milliseconds)"""
    transforms: List[Transform] = field(
        default_factory=lambda: [Transform() for _ in range(RAW_SENSOR_COUNT)]
    )
    """Position and rotation per sensor (5 elements per hand). See `RawSensorIndex` for the indices"""
