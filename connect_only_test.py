import sys

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport.sport_client import SportClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python connect_only_test.py networkInterface")
        print("Example: python connect_only_test.py wlx503eaaae9bc1")
        return

    network_interface = sys.argv[1]

    print("Initializing Unitree high-level SDK...")
    print(f"Network interface: {network_interface}")

    ChannelFactoryInitialize(0, network_interface)

    sport_client = SportClient()
    sport_client.SetTimeout(10.0)
    sport_client.Init()

    print("SportClient initialized successfully.")
    print("No movement command was sent.")


if __name__ == "__main__":
    main()