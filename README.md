# ContactGlove Python SDK V2

English | [日本語](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/README_JA.md)

Receive ContactGlove3 Pro data from DivingStation over OSC. The SDK provides
polling and callbacks for glove, ergonomics, skeleton, sensor, and controller
data, and supports haptic requests.

## Requirements

- Python 3.10 or later; operation has been confirmed on Windows 11, macOS, and Ubuntu.
- ContactGlove3 Pro and a running DivingStation installation. Configure and approve the connection in DivingStation.
- `python-osc>=1.7.5` and `matplotlib>=3.7.5` are installed automatically; matplotlib is used by the viewer example.

## Installation

### From PyPI (recommended)

Install the published [contactglovesdk package on PyPI](https://pypi.org/project/contactglovesdk/) in a Python 3.10+ environment:

```sh
python -m pip install contactglovesdk
```

### From a distribution ZIP

Download `ContactGloveSDKv2Python-X.Y.Z.zip` from the [latest GitHub Release](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/releases/latest). This distribution includes the wheel, examples, API reference and license documents. Choose the named distribution ZIP, not GitHub's automatically generated **Source code** archives.

Download the matching `.zip.sha256` file from the same release and verify the ZIP's SHA-256 checksum. Extract the ZIP, open a terminal in the extracted directory, and install its bundled wheel. Replace `X.Y.Z` with the downloaded version:

```sh
python -m pip install ./contactglovesdk-X.Y.Z-py3-none-any.whl
```

## Receive data

Start DivingStation and connect the glove first. This example assumes DivingStation is on the same machine and uses its default OSC port. Approve the connection in DivingStation if prompted. Press Ctrl+C to stop.

```python
import time
from contactglovesdk import ContactGloveClient, Host

host = Host("DivingStation", "127.0.0.1", 25791)
with ContactGloveClient() as client:
    client.register_callback_for_glove_data_stream(print)
    client.connect_to_host(host)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect(host)
```

## Documentation and support

- [Setup, usage and troubleshooting](https://docs.melt-interface-technologies.com/en/docs/contact/sdks/contact-glove-v2-python)
- [API reference](https://docs.melt-interface-technologies.com/en/docs/contact/sdks/contact-glove-v2-python/api)
- [Contact support](https://melt-interface-technologies.com/en/contact/)
- [Development guide](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/DEVELOPMENT.md)

The customer distribution also includes the API reference and license documents in its `doc/` folder.

## License

The SDK is licensed under [Apache License 2.0](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/LICENSE.md). See [NOTICE](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/NOTICE.md) and [third-party notices](https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/THIRD_PARTY_NOTICES.md) for attribution and dependency licenses.
