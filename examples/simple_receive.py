"""Simple example for contactglovesdk.

Run this after starting DivingStation and ensuring the DS is listening.
"""
import argparse
import time
from typing import Optional

from contactglovesdk import ContactGloveClient, Host

DEFAULT_DS_HOST = "127.0.0.1"
DEFAULT_DS_PORT = 25791


def on_device(d):
    print("Device:", d)


def on_erg(e):
    print("Ergonomics:", e)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive ContactGlove data from DivingStation")
    parser.add_argument(
        "--ds-host",
        default=DEFAULT_DS_HOST,
        help=f"DivingStation IP address (default: {DEFAULT_DS_HOST})",
    )
    parser.add_argument(
        "--ds-port",
        type=int,
        default=DEFAULT_DS_PORT,
        help=f"DivingStation OSC port (default: {DEFAULT_DS_PORT})",
    )
    parser.add_argument(
        "--local-host",
        default="0.0.0.0",
        help="Local interface for the OSC receiver (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=0,
        help="Local OSC receiver port. 0 lets the OS choose one (default: 0)",
    )
    parser.add_argument(
        "--send-port",
        type=int,
        default=0,
        help="Local UDP source port for OSC sends. 0 lets the OS choose one (default: 0)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        help="Stop after this many seconds. Runs until Ctrl+C if omitted.",
    )
    return parser.parse_args()


def _sleep_until_done(seconds: Optional[float]) -> None:
    if seconds is None:
        while True:
            time.sleep(1)
    else:
        time.sleep(seconds)


def main() -> None:
    args = _parse_args()
    host = Host("DivingStation", args.ds_host, args.ds_port)

    client = ContactGloveClient(
        local_host=args.local_host,
        local_port=args.local_port,
        send_port=args.send_port,
    )
    client.register_callback_for_glove_data_stream(on_device)
    client.register_callback_for_ergonomics_stream(on_erg)
    client.connect_to_host(host)
    print("Listening on port", client.local_port)
    print("Sending from port", client.send_port)

    try:
        _sleep_until_done(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.disconnect(host)
        finally:
            client.close()


if __name__ == "__main__":
    main()
