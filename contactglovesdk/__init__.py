"""
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
"""

from ._client import ContactGloveClient
from ._exceptions import (
    ContactGloveSDKError,
    InvalidIDError,
    NotConnectedError,
    SDKNotAvailableError,
)
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
    ErgonomicsIndex,
    GloveData,
    Host,
    DeviceColor,
    LedColor,
    Quaternion,
    RawSensorData,
    RawSkeletonData,
    RawSensorIndex,
    RetargetProfileInfo,
    SkeletonData,
    SkeletonNode,
    SkeletonRotationNode,
    Transform,
    TrackingState,
    Vec3,
)

__version__ = "1.0.0"

__all__ = [
    # Primary client class
    "ContactGloveClient",
    "Host",
    # Data models
    "GloveData",
    "ControllerData",
    "ErgonomicsData",
    "SkeletonData",
    "RawSkeletonData",
    "RawSensorData",
    "RetargetProfileInfo",
    "Transform",
    "Vec3",
    "Quaternion",
    # Enums
    "DeviceFamilyType",
    "DeviceColor",
    "LedColor",
    "DeviceConnectedState",
    "ButtonStatus",
    "TrackingState",
    "ErgonomicsIndex",
    "SkeletonNode",
    "SkeletonRotationNode",
    "RawSensorIndex",
    # Constants
    "ERGONOMICS_COUNT",
    "SKELETON_NODE_COUNT",
    "SKELETON_ROTATION_COUNT",
    "RAW_SENSOR_COUNT",
    # Exceptions
    "ContactGloveSDKError",
    "SDKNotAvailableError",
    "NotConnectedError",
    "InvalidIDError",
]
