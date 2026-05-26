import sys
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport.sport_client import SportClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python robot_controller_test.py networkInterface")
        print("Example: python robot_controller_test.py enp2s0")
        return

    network_interface = sys.argv[1]

    print("Initializing Unitree high-level SDK...")
    print(f"Network interface: {network_interface}")

    ChannelFactoryInitialize(0, network_interface)

    sport_client = SportClient()
    sport_client.SetTimeout(10.0)
    sport_client.Init()

    print("SDK initialized.")

    input("Make sure the robot area is clear. Press Enter to send BalanceStand...")

    ret = sport_client.BalanceStand()
    print("BalanceStand ret:", ret)

    time.sleep(1)

    input("Press Enter to test a very small forward movement...")

    print("Moving forward slowly for 0.5 seconds...")
    sport_client.Move(0.15, 0.0, 0.0)
    time.sleep(0.5)

    print("Stopping...")
    sport_client.StopMove()

    print("Test finished.")


if __name__ == "__main__":
    main()