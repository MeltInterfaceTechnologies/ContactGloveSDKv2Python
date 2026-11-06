"""Smoke test for contactglovesdk.

This script starts the OSC server, performs a connect() call,
and then cleanly disconnects. It's a smoke test runnable without DivingStation.
"""
import sys
import time

from contactglovesdk import ContactGloveClient, Host


def main():
    client = ContactGloveClient(local_host="127.0.0.1", local_port=0)
    port = client.start_server()
    print("Server started on port", port)
    if not isinstance(port, int) or port <= 0:
        print("Invalid port", port)
        return 2

    # register a simple callback
    client.register_callback_for_glove_data_stream(
        lambda d: print("device callback", d)
    )

    host = Host("unused-localhost", "127.0.0.1", 9)
    try:
        client.connect_to_host(host)
        print("Connect message sent")
        # wait briefly to simulate runtime
        time.sleep(0.5)
        client.disconnect(host)
        print("Disconnect message sent")
    except Exception as e:
        print("Exception during smoke test:", e)
        return 3
    finally:
        client.close()

    print("Smoke test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
