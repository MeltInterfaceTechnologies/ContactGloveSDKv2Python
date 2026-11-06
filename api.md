# ContactGlove Python SDK V2

ContactGlove Python SDK V2 is a Python library for working with ContactGlove.

## Requirements

The supported language is Python 3.10 or later.

The SDK itself is pure Python and does not require an OS-specific build.
Operation has been confirmed on Windows 11, macOS, and Ubuntu.
Check the viewer setup and DivingStation availability separately.

DivingStation must be installed and running beforehand.

This library depends on the following packages.

Package Name | version
--------- | ---------
python-osc | >=1.7.5
matplotlib | >=3.7.5 (used only by `examples/viewer`)

## Installation

### From PyPI

```sh
python -m pip install contactglovesdk
```

### From a distribution ZIP

Save the distribution ZIP on your computer and extract it, then install
the bundled wheel file from the extracted folder, replacing `X.Y.Z` with its version.

```sh
python -m pip install ./contactglovesdk-X.Y.Z-py3-none-any.whl
```

`pip` installs the dependencies (`python-osc`, `matplotlib`, and so on)
automatically.

## Usage

### Connecting to and disconnecting from DivingStation

Use the `ContactGloveClient.connect_to_host` method to connect to DivingStation.

The `Host` passed to `connect_to_host` carries three pieces of information: a host name, an IP address, and the receive port on the DivingStation side. The host name is chosen freely by the user to tell hosts apart. The IP address is the one assigned to the computer that runs DivingStation. The DivingStation receive port is the port on which DivingStation receives OSC requests from the SDK. It is normally 25791, but it can be changed in DivingStation; set it to the matching value if you do.

The receive port on the SDK (local) side is specified by the `local_port` constructor argument of `ContactGloveClient`. Passing `0` (the default) lets the OS assign a free port automatically, which you can read from the `client.local_port` property after connecting.

The source port used when sending OSC commands to DS is specified by the `send_port` constructor argument. Passing `0` (the default) lets the OS assign a free port. After the first send (for example a connect), the actual port number is available from the `client.send_port` property.

To retry while waiting for LAN approval or recovering from missing data, call `connect_to_host(host)` again on the same client without calling `disconnect` or `close`. It resends Connect from the same send socket and keeps the receive port, including when `send_port=0`. The SDK also resends Connect every 30 seconds automatically. A successful call does not confirm LAN approval. After DivingStation restarts, retries can restore the session; approve it again in DivingStation if required. Explicit Disconnect ends the session and can revoke pending or granted approval.

Use the `disconnect` method to close the connection to DivingStation. As the shutdown step for the whole SDK, `close()` (or the context manager form via a `with` statement) stops the local server and the send socket.

```python
from contactglovesdk import ContactGloveClient, Host

host = Host("localhost", "127.0.0.1", 25791)

with ContactGloveClient() as client:
    # Connect to DivingStation
    client.connect_to_host(host)

    # Do various things

    # Disconnect from DivingStation
    client.disconnect(host)
```

### Reading values

There are methods for reading the various kinds of glove-related information. The value returned is the most recent data received as of the moment of the call. The available values and methods are as follows.

Available value | Method name
--------- | ---------
Information about the glove itself | `get_data_for_glove`
Whether the glove supports haptics | `does_glove_support_haptics`
Opening/bending angle of each finger joint | `get_ergonomics_data_for_glove`
Position/rotation of each finger joint | `get_skeleton_data_for_glove`
Position/rotation of the raw sensors | `get_rawsensor_data_for_glove`
Input from the controller attached to the glove | `get_controller_data_for_glove`
IDs of all connected gloves | `get_ids_of_available_gloves`
Total number of connected gloves | `get_number_of_available_gloves`

Glove data arrives asynchronously. Register a callback before connecting to learn an actual glove ID, then wait for data before polling. The connection call starts the local session; it does not confirm that DivingStation has approved the connection or sent data.

```python
from threading import Event

from contactglovesdk import ContactGloveClient, DeviceConnectedState, Host, InvalidIDError

host = Host("localhost", "127.0.0.1", 25791)
received = Event()
glove_ids = []

def on_glove(glove):
    if glove.connected_state == DeviceConnectedState.Connected and not received.is_set():
        glove_ids.append(glove.id)
        received.set()

with ContactGloveClient() as client:
    client.register_callback_for_glove_data_stream(on_glove)
    client.connect_to_host(host)
    try:
        if received.wait(timeout=5):
            try:
                glove = client.get_data_for_glove(glove_ids[0])
                print(f"id={glove.id}")
            except InvalidIDError:
                print("The glove is no longer available")
        else:
            print("No glove data received within 5 seconds")
    finally:
        client.disconnect(host)
```

If data does not arrive, check that the glove is connected and enabled in DivingStation and that any required connection approval has been granted. For multiple gloves, select the intended ID rather than assuming the first one is the desired glove.

### Following value changes automatically

You can register callbacks that are invoked automatically whenever the various glove-related values are updated. Callbacks are invoked from the OSC receive thread, so implement the work inside a callback on the assumption that it is accessed from multiple threads. If a callback raises an exception, the SDK logs it with its traceback to the `contactglovesdk` logger (shown on stderr when logging is not configured) and keeps invoking the other callbacks.

Value that triggers the call | Method name
--------- | ---------
Information about the glove itself | `register_callback_for_glove_data_stream`
Opening/bending angle of each finger joint | `register_callback_for_ergonomics_stream`
Position/rotation of each finger joint | `register_callback_for_skeleton_stream`
Position/rotation of the raw sensors | `register_callback_for_rawsensor_stream`
Input from the controller attached to the glove | `register_callback_for_controller_data_stream`

They are used as follows.

```python
import time

from contactglovesdk import ContactGloveClient, GloveData, Host

host = Host("localhost", "127.0.0.1", 25791)

def on_glove(g: GloveData) -> None:
    print(f"[callback] id={g.id}  battery={g.battery_percentage}%"
          f"  left={g.is_left}  state={g.connected_state.name}")

with ContactGloveClient() as client:
    # Registering callbacks before connecting avoids missing updates
    client.register_callback_for_glove_data_stream(on_glove)

    client.connect_to_host(host)

    # Wait for 5 seconds
    time.sleep(5)

    client.disconnect(host)
```

### Haptics

The `vibrate_glove` method sends a vibration command to a glove that has the haptics feature. The command is sent to every DS host that is currently connected. Replace `YOUR_GLOVE_ID` with the actual ID received from DivingStation.

```python
client.vibrate_glove("YOUR_GLOVE_ID", frequency=200.0, amplitude=0.8, duration=0.2)
```

## Defined types and functions

The types and functions that this SDK defines and makes available are as follows.

### Classes

| Name | Description |
|------|-------------|
| [`ContactGloveClient`](#contactgloveclient) | Main class of ContactGlove Python SDK V2 |
| [`Host`](#host) | Data class holding the host information of DivingStation |
| [`GloveData`](#glovedata) | Data class holding the information of a glove device |
| [`ControllerData`](#controllerdata) | Data class holding the input state of the controller |
| [`ErgonomicsData`](#ergonomicsdata) | Data class holding the finger opening and bending angle data |
| [`SkeletonData`](#skeletondata) | Data class holding the hand skeleton data (joint positions and rotations) |
| [`RawSkeletonData`](#rawskeletondata) | Data class holding the hand skeleton data before retargeting. |
| [`RawSensorData`](#rawsensordata) | Data class holding the raw sensor Transform data for one hand |
| [`RetargetProfileInfo`](#retargetprofileinfo) | Data class holding the response that carries retarget profile information. |
| [`Transform`](#transform) | Transform combining a position and a rotation |
| [`Vec3`](#vec3) | Three-dimensional vector |
| [`Quaternion`](#quaternion) | Quaternion representing a rotation |

### Enumerations

| Name | Description |
|------|-------------|
| [`DeviceFamilyType`](#devicefamilytype) | Enum representing the kind of device |
| [`DeviceColor`](#devicecolor) | Enum representing the device display-color setting |
| [`DeviceConnectedState`](#deviceconnectedstate) | Enum representing the connection state of the device |
| [`ButtonStatus`](#buttonstatus) | Enum representing the press state of a button |
| [`TrackingState`](#trackingstate) | Enum representing the tracking state of IK-derived data. |
| [`ErgonomicsIndex`](#ergonomicsindex) | Enum indicating the joint that each element of `ErgonomicsData.values` represents |
| [`SkeletonNode`](#skeletonnode) | Enum indicating the joint that each element of `SkeletonData.positions` represents |
| [`SkeletonRotationNode`](#skeletonrotationnode) | Enum indicating the joint that each element of `SkeletonData.rotations` represents |
| [`RawSensorIndex`](#rawsensorindex) | Enum indicating the sensor that each element of `RawSensorData.transforms` represents |

### Exceptions

| Name | Description |
|------|-------------|
| [`ContactGloveSDKError`](#contactglovesdkerror) | Base class for the exceptions raised by the SDK |
| [`SDKNotAvailableError`](#sdknotavailableerror) | Raised when opening a local UDP socket fails (for example because the port is in use) |
| [`NotConnectedError`](#notconnectederror) | Raised when an operation that requires a connection is attempted while that connection does not exist |
| [`InvalidIDError`](#invalididerror) | Raised when no data for the specified glove ID exists in the current data store |

### Constants

| Name | Value | Description |
|------|-------|-------------|
| [`ERGONOMICS_COUNT`](#ergonomics_count) | `20` | Number of ergonomics data elements per hand (5 fingers × 4 joints) |
| [`SKELETON_NODE_COUNT`](#skeleton_node_count) | `25` | Number of skeleton position elements per hand |
| [`SKELETON_ROTATION_COUNT`](#skeleton_rotation_count) | `19` | Number of skeleton rotation elements per hand (the wrist and the 5 fingertip nodes are excluded) |
| [`RAW_SENSOR_COUNT`](#raw_sensor_count) | `5` | Number of raw sensor Transforms per hand (one per finger) |

---

#### DeviceFamilyType

```python
class DeviceFamilyType(IntEnum)
```

Enum representing the kind of device

Corresponds to the `device_type` field of `/DS2/HC/Device`.
ContactGlove3 is the primary target.

| Value | Description |
|-------|-------------|
| `ContactGlove` | ContactGlove |
| `ContactSheet` | ContactSheet |
| `ContactGlove2` | ContactGlove2 |
| `ContactGlove3` | ContactGlove3 |

---

#### DeviceColor

```python
class DeviceColor(IntEnum)
```

Enum representing the device display-color setting

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

| Value | Description |
|-------|-------------|
| `Magenta` | Magenta |
| `Red` | Red |
| `Orange` | Orange |
| `Yellow` | Yellow |
| `Green` | Green |
| `Cyan` | Cyan |
| `Blue` | Blue |
| `Achromatic` | Achromatic |

---

#### DeviceConnectedState

```python
class DeviceConnectedState(IntEnum)
```

Enum representing the connection state of the device

Corresponds to the `connected_state` field of `/DS2/HC/Device`.

| Value | Description |
|-------|-------------|
| `Unknown` | State unknown |
| `Connected` | Connected |
| `Unconnected` | Not connected |
| `Pairing` | Attempting to connect |

---

#### ButtonStatus

```python
class ButtonStatus(IntEnum)
```

Enum representing the press state of a button

Corresponds to each button field of `/DS2/HC/Controller`.

| Value | Description |
|-------|-------------|
| `Unpressed` | Not pressed |
| `Touching` | Touched (detected by the touch sensor) |
| `Pressed` | Pressed |

---

#### TrackingState

```python
class TrackingState(IntEnum)
```

Enum representing the tracking state of IK-derived data.

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

| Value | Description |
|-------|-------------|
| `Tracked` | A valid value obtained from the current IK pass |
| `IkFailed` | A value for which the IK pass was attempted but failed |
| `NotAttempted` | A value for which IK was not performed, including intentional update-interval skips as well as earlier failures or missing input |

---

#### ErgonomicsIndex

```python
class ErgonomicsIndex(IntEnum)
```

Enum indicating the joint that each element of `ErgonomicsData.values` represents

The indices cover one hand (`ERGONOMICS_COUNT` = 20 elements), and
`values[i]` corresponds to `ErgonomicsIndex(i)`. Values are in degrees,
and a bending angle is 0 degrees when the finger is extended.

| Value | Description |
|-------|-------------|
| `ThumbCMC` | Bending angle of the thumb CMC joint |
| `ThumbMCP` | Bending angle of the thumb MCP joint |
| `ThumbIP` | Bending angle of the thumb IP joint |
| `ThumbTilt` | Tilt angle of the thumb MCP joint |
| `IndexMCP` | Bending angle of the index finger MCP joint |
| `IndexPIP` | Bending angle of the index finger PIP joint |
| `IndexDIP` | Bending angle of the index finger DIP joint |
| `IndexTilt` | Tilt angle of the index finger MCP joint |
| `MiddleMCP` | Bending angle of the middle finger MCP joint |
| `MiddlePIP` | Bending angle of the middle finger PIP joint |
| `MiddleDIP` | Bending angle of the middle finger DIP joint |
| `MiddleTilt` | Tilt angle of the middle finger MCP joint |
| `RingMCP` | Bending angle of the ring finger MCP joint |
| `RingPIP` | Bending angle of the ring finger PIP joint |
| `RingDIP` | Bending angle of the ring finger DIP joint |
| `RingTilt` | Tilt angle of the ring finger MCP joint |
| `LittleMCP` | Bending angle of the little finger MCP joint |
| `LittlePIP` | Bending angle of the little finger PIP joint |
| `LittleDIP` | Bending angle of the little finger DIP joint |
| `LittleTilt` | Tilt angle of the little finger MCP joint |

---

#### SkeletonNode

```python
class SkeletonNode(IntEnum)
```

Enum indicating the joint that each element of `SkeletonData.positions` represents

The indices cover one hand (`SKELETON_NODE_COUNT` = 25 elements), and
`positions[i]` corresponds to `SkeletonNode(i)`.

| Value | Description |
|-------|-------------|
| `Wrist` | Wrist |
| `ThumbCMC` | Thumb CMC joint |
| `ThumbMCP` | Thumb MCP joint |
| `ThumbIP` | Thumb IP joint |
| `ThumbTip` | Thumb tip |
| `IndexCMC` | Index finger CMC joint |
| `IndexMCP` | Index finger MCP joint |
| `IndexPIP` | Index finger PIP joint |
| `IndexDIP` | Index finger DIP joint |
| `IndexTip` | Index finger tip |
| `MiddleCMC` | Middle finger CMC joint |
| `MiddleMCP` | Middle finger MCP joint |
| `MiddlePIP` | Middle finger PIP joint |
| `MiddleDIP` | Middle finger DIP joint |
| `MiddleTip` | Middle finger tip |
| `RingCMC` | Ring finger CMC joint |
| `RingMCP` | Ring finger MCP joint |
| `RingPIP` | Ring finger PIP joint |
| `RingDIP` | Ring finger DIP joint |
| `RingTip` | Ring finger tip |
| `LittleCMC` | Little finger CMC joint |
| `LittleMCP` | Little finger MCP joint |
| `LittlePIP` | Little finger PIP joint |
| `LittleDIP` | Little finger DIP joint |
| `LittleTip` | Little finger tip |

---

#### SkeletonRotationNode

```python
class SkeletonRotationNode(IntEnum)
```

Enum indicating the joint that each element of `SkeletonData.rotations` represents

The indices cover one hand (`SKELETON_ROTATION_COUNT` = 19 elements), and
`rotations[i]` corresponds to `SkeletonRotationNode(i)`.
Unlike `SkeletonNode`, the wrist and the 5 fingertip nodes are excluded
because they carry no rotation value.

| Value | Description |
|-------|-------------|
| `ThumbCMC` | Thumb CMC joint |
| `ThumbMCP` | Thumb MCP joint |
| `ThumbIP` | Thumb IP joint |
| `IndexCMC` | Index finger CMC joint |
| `IndexMCP` | Index finger MCP joint |
| `IndexPIP` | Index finger PIP joint |
| `IndexDIP` | Index finger DIP joint |
| `MiddleCMC` | Middle finger CMC joint |
| `MiddleMCP` | Middle finger MCP joint |
| `MiddlePIP` | Middle finger PIP joint |
| `MiddleDIP` | Middle finger DIP joint |
| `RingCMC` | Ring finger CMC joint |
| `RingMCP` | Ring finger MCP joint |
| `RingPIP` | Ring finger PIP joint |
| `RingDIP` | Ring finger DIP joint |
| `LittleCMC` | Little finger CMC joint |
| `LittleMCP` | Little finger MCP joint |
| `LittlePIP` | Little finger PIP joint |
| `LittleDIP` | Little finger DIP joint |

---

#### RawSensorIndex

```python
class RawSensorIndex(IntEnum)
```

Enum indicating the sensor that each element of `RawSensorData.transforms` represents

The indices cover one hand (`RAW_SENSOR_COUNT` = 5 elements), and
`transforms[i]` corresponds to `RawSensorIndex(i)`.

| Value | Description |
|-------|-------------|
| `Thumb` | Thumb |
| `Index` | Index finger |
| `Middle` | Middle finger |
| `Ring` | Ring finger |
| `Little` | Little finger |

---

#### ERGONOMICS_COUNT

```python
ERGONOMICS_COUNT: int = 20
```

Number of ergonomics data elements per hand (5 fingers × 4 joints)

---

#### SKELETON_NODE_COUNT

```python
SKELETON_NODE_COUNT: int = 25
```

Number of skeleton position elements per hand

---

#### SKELETON_ROTATION_COUNT

```python
SKELETON_ROTATION_COUNT: int = 19
```

Number of skeleton rotation elements per hand (the wrist and the 5 fingertip nodes are excluded)

---

#### RAW_SENSOR_COUNT

```python
RAW_SENSOR_COUNT: int = 5
```

Number of raw sensor Transforms per hand (one per finger)

## ContactGloveClient

```python
from contactglovesdk import ContactGloveClient
```

Main class of ContactGlove Python SDK V2

Polling results and each stream callback receive independent snapshots,
including nested lists and geometry values. Modifying one does not change
the SDK cache or values delivered to other callbacks.

Usage:

```python
import time

from contactglovesdk import ContactGloveClient, Host, InvalidIDError

host = Host("localhost", "127.0.0.1", 25791)
with ContactGloveClient() as client:
    # Register before connecting so the first update is not missed.
    client.register_callback_for_glove_data_stream(
        lambda g: print(g.id, g.battery_percentage)
    )
    client.connect_to_host(host)
    try:
        # Poll until an ID arrives or the five-second deadline expires.
        deadline = time.monotonic() + 5.0
        glove_ids = client.get_ids_of_available_gloves()
        while not glove_ids and time.monotonic() < deadline:
            time.sleep(0.1)
            glove_ids = client.get_ids_of_available_gloves()

        if glove_ids:
            try:
                glove = client.get_data_for_glove(glove_ids[0])
                print(glove.id)
            except InvalidIDError:
                print("The glove is no longer available")
        else:
            print("No glove data received within 5 seconds")
    finally:
        client.disconnect(host)
```

### Public Methods

| Return | Name | Description |
|--------|------|-------------|
|  | [`__init__`](#__init__) | Main class of ContactGlove Python SDK V2 |
| `int` | [`start_server`](#start_server) | Start the local OSC server without connecting to any host. |
| `int \| None` | [`local_port`](#local_port) | Port number used by the local OSC server. `None` while it is not running. |
| `int \| None` | [`send_port`](#send_port) | Port number used by the OSC send socket. `None` before the first send. |
| `None` | [`close`](#close) | Stop the local OSC server and the send socket. |
| `None` | [`connect_to_host`](#connect_to_host) | Connect to DivingStation and start the data streams. |
| `None` | [`disconnect`](#disconnect) | Disconnect from a DS. |
| `bool` | [`does_glove_support_haptics`](#does_glove_support_haptics) | Check whether the glove supports haptics. |
| `GloveData` | [`get_data_for_glove`](#get_data_for_glove) | Read the glove information for a glove ID. |
| `ControllerData` | [`get_controller_data_for_glove`](#get_controller_data_for_glove) | Read the controller input data for a glove ID. |
| `ErgonomicsData` | [`get_ergonomics_data_for_glove`](#get_ergonomics_data_for_glove) | Read the finger opening and bending angle data for a glove ID. |
| `SkeletonData` | [`get_skeleton_data_for_glove`](#get_skeleton_data_for_glove) | Read the joint position and rotation data for a glove ID. |
| `RawSkeletonData` | [`get_raw_skeleton_data_for_glove`](#get_raw_skeleton_data_for_glove) | Read the pre-retarget hand skeleton for a glove ID. |
| `RawSensorData` | [`get_rawsensor_data_for_glove`](#get_rawsensor_data_for_glove) | Read the raw sensor Transform data for a glove ID. |
| `list[str]` | [`get_ids_of_available_gloves`](#get_ids_of_available_gloves) | Read the IDs of every glove that is currently known. |
| `int` | [`get_number_of_available_gloves`](#get_number_of_available_gloves) | Read the total number of gloves that are currently known. |
| `None` | [`vibrate_glove`](#vibrate_glove) | Make the glove vibrate. |
| `None` | [`request_retarget_profile_info`](#request_retarget_profile_info) | Request the display name and description of a retarget profile from DivingStation. |
| `None` | [`register_callback_for_glove_data_stream`](#register_callback_for_glove_data_stream) | Register a callback invoked when the glove information is updated. |
| `None` | [`register_callback_for_controller_data_stream`](#register_callback_for_controller_data_stream) | Register a callback invoked when the controller data is updated. |
| `None` | [`register_callback_for_ergonomics_stream`](#register_callback_for_ergonomics_stream) | Register a callback invoked when the ergonomics data is updated. |
| `None` | [`register_callback_for_skeleton_stream`](#register_callback_for_skeleton_stream) | Register a callback invoked when the skeleton data is updated. |
| `None` | [`register_callback_for_raw_skeleton_stream`](#register_callback_for_raw_skeleton_stream) | Register a callback invoked when the pre-retarget skeleton is updated. |
| `None` | [`register_callback_for_rawsensor_stream`](#register_callback_for_rawsensor_stream) | Register a callback invoked when the raw sensor Transform data is updated. |
| `None` | [`register_callback_for_retarget_profile_info_stream`](#register_callback_for_retarget_profile_info_stream) | Register a callback that receives the retarget profile information response. |

### Class Attributes

| Return | Name | Description |
|--------|------|-------------|
| `int` | [`DEFAULT_DS_PORT`](#default_ds_port) | Default OSC receive port number on the DivingStation side |

---

#### `__init__`

```python
ContactGloveClient(local_host: str = "0.0.0.0", local_port: int = 0, send_port: int = 0)
```

#### Parameters

* `local_host` Network interface the local OSC server binds to (`"0.0.0.0"` for every interface).

* `local_port` Port number the local OSC server binds to (`0` lets the OS pick a free port automatically).

* `send_port` Local UDP port number used to send OSC to DS (`0` lets the OS pick a free port automatically).

---

#### start_server

```python
def start_server(self) -> int
```

Start the local OSC server without connecting to any host.

Use this when the local port number is needed before calling
`connect_to_host`.

#### Returns
The port number the server actually bound to.

#### Raises

* `SDKNotAvailableError` If binding the port failed.

---

#### local_port

```python
@property
def local_port(self) -> int | None
```

Port number used by the local OSC server. `None` while it is not running.

---

#### send_port

```python
@property
def send_port(self) -> int | None
```

Port number used by the OSC send socket. `None` before the first send.

---

#### close

```python
def close(self)
```

Stop the local OSC server and the send socket.

If any stream callback is still running, this waits for it to finish
before returning.

---

#### connect_to_host

```python
def connect_to_host(self, host: Host)
```

Connect to DivingStation and start the data streams.

Starts the local OSC server if it is not running yet, then sends
`/DS2/HC/Connect <local_port>` to `host`. While the connection is kept
alive, Connect is re-sent every 30 seconds from the same send socket.

Calling again for the same IP address and DS port resends Connect
without sending Disconnect or replacing the send socket, receive port,
or keepalive worker. Use this to retry while awaiting LAN approval or
recovering from lost data. The OS-selected source port is retained even
when `send_port` is `0`. Returning does not confirm LAN approval.
After DS restarts, Connect retries can restore the session; approve it
again in DS if required. Explicit `disconnect` ends the session and can
revoke pending or granted approval.

#### Parameters

* `host` Host information of the DS to connect to.

#### Raises

* `SDKNotAvailableError` If binding the local receive or send port failed.

---

#### disconnect

```python
def disconnect(self, host: Host)
```

Disconnect from a DS.

Sends `/DS2/HC/Disconnect <local_port>` to `host`. When the last
connection is closed, this waits until the stream callbacks that are
still running have finished.

#### Parameters

* `host` The same host information that was passed to `connect_to_host`.

#### Raises

* `NotConnectedError` If no connection to the given host exists.

---

#### does_glove_support_haptics

```python
def does_glove_support_haptics(self, glove_id: str) -> bool
```

Check whether the glove supports haptics.

#### Parameters

* `glove_id` ID of the glove to check.

#### Returns
Whether the haptics feature is present.

#### Raises

* `InvalidIDError` If no glove with the given ID exists.

---

#### get_data_for_glove

```python
def get_data_for_glove(self, glove_id: str) -> GloveData
```

Read the glove information for a glove ID.

#### Parameters

* `glove_id` ID of the glove to read.

#### Returns
A snapshot of the glove information.

#### Raises

* `InvalidIDError` If no glove with the given ID exists.

---

#### get_controller_data_for_glove

```python
def get_controller_data_for_glove(self, glove_id: str) -> ControllerData
```

Read the controller input data for a glove ID.

#### Parameters

* `glove_id` ID of the glove to read.

#### Returns
A snapshot of the controller input data.

#### Raises

* `InvalidIDError` If no data for the given ID has been received yet.

---

#### get_ergonomics_data_for_glove

```python
def get_ergonomics_data_for_glove(self, glove_id: str) -> ErgonomicsData
```

Read the finger opening and bending angle data for a glove ID.

#### Parameters

* `glove_id` ID of the glove to read.

#### Returns
A snapshot of the ergonomics data.

#### Raises

* `InvalidIDError` If no data for the given ID has been received yet.

---

#### get_skeleton_data_for_glove

```python
def get_skeleton_data_for_glove(self, glove_id: str) -> SkeletonData
```

Read the joint position and rotation data for a glove ID.

#### Parameters

* `glove_id` ID of the glove to read.

#### Returns
A snapshot of the skeleton data.

#### Raises

* `InvalidIDError` If no data for the given ID has been received yet.

---

#### get_raw_skeleton_data_for_glove

```python
def get_raw_skeleton_data_for_glove(self, glove_id: str) -> RawSkeletonData
```

Read the pre-retarget hand skeleton for a glove ID.

#### Returns
An independent snapshot, including positions and rotations.

#### Raises

* `InvalidIDError` If no data for the given ID has been received yet.

---

#### get_rawsensor_data_for_glove

```python
def get_rawsensor_data_for_glove(self, glove_id: str) -> RawSensorData
```

Read the raw sensor Transform data for a glove ID.

#### Parameters

* `glove_id` ID of the glove to read.

#### Returns
A snapshot of the raw sensor Transform data.

#### Raises

* `InvalidIDError` If no data for the given ID has been received yet.

---

#### get_ids_of_available_gloves

```python
def get_ids_of_available_gloves(self) -> list[str]
```

Read the IDs of every glove that is currently known.

#### Returns
A list of glove IDs.

---

#### get_number_of_available_gloves

```python
def get_number_of_available_gloves(self) -> int
```

Read the total number of gloves that are currently known.

#### Returns
The total number of gloves.

---

#### vibrate_glove

```python
def vibrate_glove(self, glove_id: str, frequency: float, amplitude: float, duration: float)
```

Make the glove vibrate.

The command is sent to every DS host that is currently connected.

#### Parameters

* `glove_id` ID of the glove to vibrate.

* `frequency` Vibration frequency (Hz, 100.0 to 500.0).

* `amplitude` Vibration amplitude (0.0 to 1.0).

* `duration` Vibration duration (seconds, 0.001 to 1.0).

#### Raises

* `InvalidIDError` If no glove with the given ID exists.

* `ValueError` If frequency, amplitude or duration is outside the range of the specification or is not a finite value.

---

#### request_retarget_profile_info

```python
def request_retarget_profile_info(self, profile_uuid: str, request_id: int)
```

Request the display name and description of a retarget profile from DivingStation.

The response is delivered to the callback registered with
`register_callback_for_retarget_profile_info_stream`.

#### Parameters

* `profile_uuid` The 36-character UUID to query.

* `request_id` Signed 32-bit integer that correlates a request with its response.

#### Raises

* `ValueError` If the UUID or the request ID does not match the format of the protocol.

---

#### register_callback_for_glove_data_stream

```python
def register_callback_for_glove_data_stream(self, callback: Callable[[GloveData], None])
```

Register a callback invoked when the glove information is updated.

Every time `/DS2/HC/Device` is received, the callback is invoked with
the updated `GloveData` as its argument. The callback is invoked from
the OSC receive thread. Records whose `connected_state` is
`Unconnected` are passed as well, but the data for that ID can no
longer be read at that point.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

#### Parameters

* `callback` Callback function to register.

---

#### register_callback_for_controller_data_stream

```python
def register_callback_for_controller_data_stream(self, callback: Callable[[ControllerData], None])
```

Register a callback invoked when the controller data is updated.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

#### Parameters

* `callback` Callback function to register.

---

#### register_callback_for_ergonomics_stream

```python
def register_callback_for_ergonomics_stream(self, callback: Callable[[ErgonomicsData], None])
```

Register a callback invoked when the ergonomics data is updated.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

#### Parameters

* `callback` Callback function to register.

---

#### register_callback_for_skeleton_stream

```python
def register_callback_for_skeleton_stream(self, callback: Callable[[SkeletonData], None])
```

Register a callback invoked when the skeleton data is updated.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

#### Parameters

* `callback` Callback function to register.

---

#### register_callback_for_raw_skeleton_stream

```python
def register_callback_for_raw_skeleton_stream(self, callback: Callable[[RawSkeletonData], None])
```

Register a callback invoked when the pre-retarget skeleton is updated.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

---

#### register_callback_for_rawsensor_stream

```python
def register_callback_for_rawsensor_stream(self, callback: Callable[[RawSensorData], None])
```

Register a callback invoked when the raw sensor Transform data is updated.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

#### Parameters

* `callback` Callback function to register.

---

#### register_callback_for_retarget_profile_info_stream

```python
def register_callback_for_retarget_profile_info_stream(self, callback: Callable[[RetargetProfileInfo], None])
```

Register a callback that receives the retarget profile information response.

Exceptions raised by the callback are logged to the `contactglovesdk`
logger and do not prevent other callbacks from being invoked.

---

#### DEFAULT_DS_PORT

```python
DEFAULT_DS_PORT: int = 25791
```

Default OSC receive port number on the DivingStation side

## Host

```python
from contactglovesdk import Host
```

Data class holding the host information of DivingStation

Passed to `connect_to_host()` / `disconnect()`. The receive port on the
SDK (local) side is managed by `ContactGloveClient`, so it is not part of
this class.

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`host_name`](#hosthost_name) | Host name (for example `"localhost"`) |
| `str` | [`ip_address`](#hostip_address) | IP address (for example `"127.0.0.1"`) |
| `int` | [`port`](#hostport) | OSC receive port number on the DivingStation side |

---

#### Host.host_name

```python
host_name: str
```

Host name (for example `"localhost"`)

---

#### Host.ip_address

```python
ip_address: str
```

IP address (for example `"127.0.0.1"`)

---

#### Host.port

```python
port: int = 25791
```

OSC receive port number on the DivingStation side

## GloveData

```python
from contactglovesdk import GloveData
```

Data class holding the information of a glove device

Corresponds to the data received from the OSC address `/DS2/HC/Device`.

Record layout (10 fields per device):

```
string id, string pair_id,
int battery_percentage, int is_haptics, int is_left,
int device_type, int color, int connected_state,
string name, int is_external_power_present
```

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#glovedataid) | Device ID |
| `str` | [`pair_id`](#glovedatapair_id) | ID of the paired glove (an empty string if there is none) |
| `int` | [`battery_percentage`](#glovedatabattery_percentage) | Remaining battery level [0 - 100]. -1 means an invalid value |
| `bool` | [`is_haptics`](#glovedatais_haptics) | Whether the haptics feature is present |
| `bool` | [`is_left`](#glovedatais_left) | Whether this is a left-hand glove |
| `DeviceFamilyType` | [`device_type`](#glovedatadevice_type) | Kind of device |
| `DeviceColor` | [`color`](#glovedatacolor) | Device display-color setting |
| `DeviceConnectedState` | [`connected_state`](#glovedataconnected_state) | Connection state |
| `str` | [`name`](#glovedataname) | Device name |
| `bool` | [`is_external_power_present`](#glovedatais_external_power_present) | Whether external power is detected |

---

#### GloveData.id

```python
id: str = ""
```

Device ID

---

#### GloveData.pair_id

```python
pair_id: str = ""
```

ID of the paired glove (an empty string if there is none)

---

#### GloveData.battery_percentage

```python
battery_percentage: int = -1
```

Remaining battery level [0 - 100]. -1 means an invalid value

---

#### GloveData.is_haptics

```python
is_haptics: bool = False
```

Whether the haptics feature is present

---

#### GloveData.is_left

```python
is_left: bool = False
```

Whether this is a left-hand glove

---

#### GloveData.device_type

```python
device_type: DeviceFamilyType = DeviceFamilyType.ContactGlove
```

Kind of device

---

#### GloveData.color

```python
color: DeviceColor = DeviceColor.Achromatic
```

Device display-color setting

---

#### GloveData.connected_state

```python
connected_state: DeviceConnectedState = DeviceConnectedState.Unknown
```

Connection state

---

#### GloveData.name

```python
name: str = ""
```

Device name

---

#### GloveData.is_external_power_present

```python
is_external_power_present: bool = False
```

Whether external power is detected

## ControllerData

```python
from contactglovesdk import ControllerData
```

Data class holding the input state of the controller

Corresponds to the data received from the OSC address `/DS2/HC/Controller`.

Record layout (15 fields per controller):

```
string id, int is_left,
int a, int b, int sys,
int trigger_button, int joystick_button, int trackpad_button,
float trigger, float grip_value, float grip_force,
float joystick_x, float joystick_y,
float trackpad_x, float trackpad_y
```

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#controllerdataid) | Glove ID |
| `bool` | [`is_left`](#controllerdatais_left) | Whether this is the left hand |
| `ButtonStatus` | [`a_button`](#controllerdataa_button) | Press state of the A button |
| `ButtonStatus` | [`b_button`](#controllerdatab_button) | Press state of the B button |
| `ButtonStatus` | [`sys_button`](#controllerdatasys_button) | Press state of the system button |
| `ButtonStatus` | [`trigger_button`](#controllerdatatrigger_button) | Press state of the trigger button |
| `ButtonStatus` | [`joystick_button`](#controllerdatajoystick_button) | Press state of the joystick button |
| `ButtonStatus` | [`trackpad_button`](#controllerdatatrackpad_button) | Press state of the trackpad touch |
| `float` | [`trigger`](#controllerdatatrigger) | Trigger value (0.0 to 1.0) |
| `float` | [`grip_value`](#controllerdatagrip_value) | Grip value (0.0 to 1.0) |
| `float` | [`grip_force`](#controllerdatagrip_force) | Grip force (0.0 to 1.0) |
| `float` | [`joystick_x`](#controllerdatajoystick_x) | Joystick X axis value (-1.0 to 1.0) |
| `float` | [`joystick_y`](#controllerdatajoystick_y) | Joystick Y axis value (-1.0 to 1.0) |
| `float` | [`trackpad_x`](#controllerdatatrackpad_x) | Trackpad X axis value (-1.0 to 1.0) |
| `float` | [`trackpad_y`](#controllerdatatrackpad_y) | Trackpad Y axis value (-1.0 to 1.0) |

---

#### ControllerData.id

```python
id: str = ""
```

Glove ID

---

#### ControllerData.is_left

```python
is_left: bool = False
```

Whether this is the left hand

---

#### ControllerData.a_button

```python
a_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the A button

---

#### ControllerData.b_button

```python
b_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the B button

---

#### ControllerData.sys_button

```python
sys_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the system button

---

#### ControllerData.trigger_button

```python
trigger_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the trigger button

---

#### ControllerData.joystick_button

```python
joystick_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the joystick button

---

#### ControllerData.trackpad_button

```python
trackpad_button: ButtonStatus = ButtonStatus.Unpressed
```

Press state of the trackpad touch

---

#### ControllerData.trigger

```python
trigger: float = 0.0
```

Trigger value (0.0 to 1.0)

---

#### ControllerData.grip_value

```python
grip_value: float = 0.0
```

Grip value (0.0 to 1.0)

---

#### ControllerData.grip_force

```python
grip_force: float = 0.0
```

Grip force (0.0 to 1.0)

---

#### ControllerData.joystick_x

```python
joystick_x: float = 0.0
```

Joystick X axis value (-1.0 to 1.0)

---

#### ControllerData.joystick_y

```python
joystick_y: float = 0.0
```

Joystick Y axis value (-1.0 to 1.0)

---

#### ControllerData.trackpad_x

```python
trackpad_x: float = 0.0
```

Trackpad X axis value (-1.0 to 1.0)

---

#### ControllerData.trackpad_y

```python
trackpad_y: float = 0.0
```

Trackpad Y axis value (-1.0 to 1.0)

## ErgonomicsData

```python
from contactglovesdk import ErgonomicsData
```

Data class holding the finger opening and bending angle data

Corresponds to the data received from the OSC address `/DS2/HC/Ergonomics`.

Record layout (25 fields per hand):

```
string id, int is_left,
int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
float[20] values
```

`values[i]` corresponds to `ErgonomicsIndex(i)`.
Angles are in degrees, and a bending angle is 0 degrees when the finger
is extended.

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#ergonomicsdataid) | Glove ID |
| `bool` | [`is_left`](#ergonomicsdatais_left) | Whether this is the left hand |
| `int` | [`timestamp_ms`](#ergonomicsdatatimestamp_ms) | Time at which the frame was generated (Unix time, milliseconds) |
| `TrackingState` | [`tracking_state`](#ergonomicsdatatracking_state) | IK-derived tracking state |
| `list[float]` | [`values`](#ergonomicsdatavalues) | Opening and bending angle value per joint (20 elements per hand, degrees) |

---

#### ErgonomicsData.id

```python
id: str = ""
```

Glove ID

---

#### ErgonomicsData.is_left

```python
is_left: bool = False
```

Whether this is the left hand

---

#### ErgonomicsData.timestamp_ms

```python
timestamp_ms: int = 0
```

Time at which the frame was generated (Unix time, milliseconds)

---

#### ErgonomicsData.tracking_state

```python
tracking_state: TrackingState = TrackingState.Tracked
```

IK-derived tracking state

---

#### ErgonomicsData.values

```python
values: list[float] = [0.0, ...]  # 20 elements
```

Opening and bending angle value per joint (20 elements per hand, degrees)

## SkeletonData

```python
from contactglovesdk import SkeletonData
```

Data class holding the hand skeleton data (joint positions and rotations)

Corresponds to the data received from the OSC address `/DS2/HC/HandSkeleton`.

Record layout (one record per message, 157 fields):

```
string id, string profile_uuid, int is_left,
int generated_at_ms_hi, int generated_at_ms_lo, int tracking_state,
float[75]  # 25 nodes × (p_x, p_y, p_z)
float[76]  # 19 nodes × (q_w, q_x, q_y, q_z)
```

`positions[i]` corresponds to `SkeletonNode(i)` (25 elements).
`rotations[i]` corresponds to `SkeletonRotationNode(i)` (19 elements; the
wrist and the 5 fingertip nodes are excluded).

Positions are in meters and are expressed in model-rooted space (the
coordinate system whose origin is the wrist). Rotations are local
quaternions relative to the parent node.

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#skeletondataid) | Glove ID |
| `str` | [`profile_uuid`](#skeletondataprofile_uuid) | Fixed UUID of the retarget profile |
| `bool` | [`is_left`](#skeletondatais_left) | Whether this is the left hand |
| `int` | [`timestamp_ms`](#skeletondatatimestamp_ms) | Time at which the frame was generated (Unix time, milliseconds) |
| `TrackingState` | [`tracking_state`](#skeletondatatracking_state) | Tracking state derived from the retarget IK |
| `list[Vec3]` | [`positions`](#skeletondatapositions) | Position per node (25 elements). See `SkeletonNode` for the indices |
| `list[Quaternion]` | [`rotations`](#skeletondatarotations) | Rotation per node (19 elements). See `SkeletonRotationNode` for the indices |

---

#### SkeletonData.id

```python
id: str = ""
```

Glove ID

---

#### SkeletonData.profile_uuid

```python
profile_uuid: str = ""
```

Fixed UUID of the retarget profile

---

#### SkeletonData.is_left

```python
is_left: bool = False
```

Whether this is the left hand

---

#### SkeletonData.timestamp_ms

```python
timestamp_ms: int = 0
```

Time at which the frame was generated (Unix time, milliseconds)

---

#### SkeletonData.tracking_state

```python
tracking_state: TrackingState = TrackingState.Tracked
```

Tracking state derived from the retarget IK

---

#### SkeletonData.positions

```python
positions: list[Vec3] = [Vec3(x=0.0, y=0.0, z=0.0), ...]  # 25 elements
```

Position per node (25 elements). See `SkeletonNode` for the indices

---

#### SkeletonData.rotations

```python
rotations: list[Quaternion] = [Quaternion(w=1.0, x=0.0, y=0.0, z=0.0), ...]  # 19 elements
```

Rotation per node (19 elements). See `SkeletonRotationNode` for the indices

## RawSkeletonData

```python
from contactglovesdk import RawSkeletonData
```

Data class holding the hand skeleton data before retargeting.

Corresponds to the data received from the OSC address
`/DS2/HC/HandSkeletonRaw`. There is one record per message, and it has the
same position and rotation layout as `SkeletonData` except for
`profile_uuid`.

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#rawskeletondataid) | Glove ID |
| `bool` | [`is_left`](#rawskeletondatais_left) | Whether this is the left hand |
| `int` | [`timestamp_ms`](#rawskeletondatatimestamp_ms) | Time at which the frame was generated (Unix time, milliseconds) |
| `TrackingState` | [`tracking_state`](#rawskeletondatatracking_state) | Tracking state derived from the IK of the source skeleton |
| `list[Vec3]` | [`positions`](#rawskeletondatapositions) | Position per node (25 elements). See `SkeletonNode` for the indices |
| `list[Quaternion]` | [`rotations`](#rawskeletondatarotations) | Rotation per node (19 elements). See `SkeletonRotationNode` for the indices |

---

#### RawSkeletonData.id

```python
id: str = ""
```

Glove ID

---

#### RawSkeletonData.is_left

```python
is_left: bool = False
```

Whether this is the left hand

---

#### RawSkeletonData.timestamp_ms

```python
timestamp_ms: int = 0
```

Time at which the frame was generated (Unix time, milliseconds)

---

#### RawSkeletonData.tracking_state

```python
tracking_state: TrackingState = TrackingState.Tracked
```

Tracking state derived from the IK of the source skeleton

---

#### RawSkeletonData.positions

```python
positions: list[Vec3] = [Vec3(x=0.0, y=0.0, z=0.0), ...]  # 25 elements
```

Position per node (25 elements). See `SkeletonNode` for the indices

---

#### RawSkeletonData.rotations

```python
rotations: list[Quaternion] = [Quaternion(w=1.0, x=0.0, y=0.0, z=0.0), ...]  # 19 elements
```

Rotation per node (19 elements). See `SkeletonRotationNode` for the indices

## RawSensorData

```python
from contactglovesdk import RawSensorData
```

Data class holding the raw sensor Transform data for one hand

Corresponds to the data received from the OSC address
`/DS2/HC/RawSensorTransforms`. Each Transform is expressed in the same
right-handed model-rooted space as `/DS2/HC/HandSkeleton`. The position is
the sensor center position with the `wrist` as the origin, and the
rotation is the orientation from the sensor local frame to model-rooted
space.

Record layout (39 fields per hand):

```
string id, int is_left,
int generated_at_ms_hi, int generated_at_ms_lo,
float[35]  # 5 sensors × (p_x, p_y, p_z, q_w, q_x, q_y, q_z)
```

`transforms[i]` corresponds to `RawSensorIndex(i)` (5 elements, in the
order thumb, index finger, middle finger, ring finger, little finger).

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `str` | [`id`](#rawsensordataid) | Glove ID |
| `bool` | [`is_left`](#rawsensordatais_left) | Whether this is the left hand |
| `int` | [`timestamp_ms`](#rawsensordatatimestamp_ms) | Time at which the frame was generated (Unix time, milliseconds) |
| `list[Transform]` | [`transforms`](#rawsensordatatransforms) | Position and rotation per sensor (5 elements per hand). See `RawSensorIndex` for the indices |

---

#### RawSensorData.id

```python
id: str = ""
```

Glove ID

---

#### RawSensorData.is_left

```python
is_left: bool = False
```

Whether this is the left hand

---

#### RawSensorData.timestamp_ms

```python
timestamp_ms: int = 0
```

Time at which the frame was generated (Unix time, milliseconds)

---

#### RawSensorData.transforms

```python
transforms: list[Transform] = [Transform(position=Vec3(x=0.0, y=0.0, z=0.0), rotation=Quaternion(w=1.0, x=0.0, y=0.0, z=0.0)), ...]  # 5 elements
```

Position and rotation per sensor (5 elements per hand). See `RawSensorIndex` for the indices

## RetargetProfileInfo

```python
from contactglovesdk import RetargetProfileInfo
```

Data class holding the response that carries retarget profile information.

Corresponds to the data received from the OSC address
`/DS2/HC/HandSkeleton/Profile`.
`status` is 0 (present), 1 (the UUID is valid but no such profile exists)
or 2 (malformed query).

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `int` | [`request_id`](#retargetprofileinforequest_id) | Client-supplied value that correlates a request with its response |
| `str` | [`profile_uuid`](#retargetprofileinfoprofile_uuid) | Retarget profile UUID, depending on the status |
| `int` | [`status`](#retargetprofileinfostatus) | Result of retrieving the profile information (0, 1, 2) |
| `str` | [`name`](#retargetprofileinfoname) | User-facing profile name |
| `str` | [`description`](#retargetprofileinfodescription) | Description of the profile |

---

#### RetargetProfileInfo.request_id

```python
request_id: int = 0
```

Client-supplied value that correlates a request with its response

---

#### RetargetProfileInfo.profile_uuid

```python
profile_uuid: str = ""
```

Retarget profile UUID, depending on the status

---

#### RetargetProfileInfo.status

```python
status: int = 0
```

Result of retrieving the profile information (0, 1, 2)

---

#### RetargetProfileInfo.name

```python
name: str = ""
```

User-facing profile name

---

#### RetargetProfileInfo.description

```python
description: str = ""
```

Description of the profile

## Transform

```python
from contactglovesdk import Transform
```

Transform combining a position and a rotation

Used as each element of `RawSensorData.transforms`.

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `Vec3` | [`position`](#transformposition) | Position |
| `Quaternion` | [`rotation`](#transformrotation) | Rotation |

---

#### Transform.position

```python
position: Vec3 = Vec3(x=0.0, y=0.0, z=0.0)
```

Position

---

#### Transform.rotation

```python
rotation: Quaternion = Quaternion(w=1.0, x=0.0, y=0.0, z=0.0)
```

Rotation

## Vec3

```python
from contactglovesdk import Vec3
```

Three-dimensional vector

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `float` | [`x`](#vec3x) | X component |
| `float` | [`y`](#vec3y) | Y component |
| `float` | [`z`](#vec3z) | Z component |

---

#### Vec3.x

```python
x: float = 0.0
```

X component

---

#### Vec3.y

```python
y: float = 0.0
```

Y component

---

#### Vec3.z

```python
z: float = 0.0
```

Z component

## Quaternion

```python
from contactglovesdk import Quaternion
```

Quaternion representing a rotation

### Public Attributes

| Type | Name | Description |
|------|------|-------------|
| `float` | [`w`](#quaternionw) | Scalar component |
| `float` | [`x`](#quaternionx) | X component |
| `float` | [`y`](#quaterniony) | Y component |
| `float` | [`z`](#quaternionz) | Z component |

---

#### Quaternion.w

```python
w: float = 1.0
```

Scalar component

---

#### Quaternion.x

```python
x: float = 0.0
```

X component

---

#### Quaternion.y

```python
y: float = 0.0
```

Y component

---

#### Quaternion.z

```python
z: float = 0.0
```

Z component

## ContactGloveSDKError

```python
from contactglovesdk import ContactGloveSDKError
```

```python
class ContactGloveSDKError(Exception)
```

Base class for the exceptions raised by the SDK

## SDKNotAvailableError

```python
from contactglovesdk import SDKNotAvailableError
```

```python
class SDKNotAvailableError(ContactGloveSDKError)
```

Raised when opening a local UDP socket fails (for example because the port is in use)

## NotConnectedError

```python
from contactglovesdk import NotConnectedError
```

```python
class NotConnectedError(ContactGloveSDKError)
```

Raised when an operation that requires a connection is attempted while that connection does not exist

## InvalidIDError

```python
from contactglovesdk import InvalidIDError
```

```python
class InvalidIDError(ContactGloveSDKError)
```

Raised when no data for the specified glove ID exists in the current data store
