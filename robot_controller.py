import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport.sport_client import SportClient


class RobotController:
    def __init__(self, network_interface):
        print("Initializing Unitree high-level SDK...")
        print(f"Network interface: {network_interface}")

        ChannelFactoryInitialize(0, network_interface)

        self.sport_client = SportClient()
        self.sport_client.SetTimeout(10.0)
        self.sport_client.Init()

        print("RobotController initialized.")

    def stop(self):
        print("[RobotController] STOP")
        ret = self.sport_client.StopMove()
        print("[RobotController] StopMove ret:", ret)
        return ret

    def stand_up(self):
        print("[RobotController] STAND UP")
        ret = self.sport_client.StandUp()
        print("[RobotController] StandUp ret:", ret)
        return ret

    def stand_down(self):
        print("[RobotController] STAND DOWN")
        ret = self.sport_client.StandDown()
        print("[RobotController] StandDown ret:", ret)
        return ret

    def balance_stand(self):
        print("[RobotController] BALANCE STAND")
        ret = self.sport_client.BalanceStand()
        print("[RobotController] BalanceStand ret:", ret)
        return ret

    def recovery_stand(self):
        print("[RobotController] RECOVERY STAND")
        ret = self.sport_client.RecoveryStand()
        print("[RobotController] RecoveryStand ret:", ret)
        return ret

    def move_short(self, vx, vy, vyaw, duration=0.5):
        print(f"[RobotController] Move vx={vx}, vy={vy}, vyaw={vyaw}, duration={duration}")
        self.balance_stand()
        time.sleep(0.5)
        ret = self.sport_client.Move(vx, vy, vyaw)
        print("[RobotController] Move ret:", ret)
        time.sleep(duration)
        self.stop()
        return ret

    def execute_command(self, command):
        if command == "stop":
            self.stop()

        elif command == "stand_up":
            self.stand_up()

        elif command == "stand_down":
            self.stand_down()

        elif command == "balance":
            self.balance_stand()

        elif command == "recovery":
            self.recovery_stand()

        elif command == "forward":
            self.move_short(0.15, 0.0, 0.0, duration=2.0)

        elif command == "backward":
            self.move_short(-0.12, 0.0, 0.0, duration=2.0)

        elif command == "turn_left":
            self.move_short(0.0, 0.0, 0.35, duration=2.0)

        elif command == "turn_right":
            self.move_short(0.0, 0.0, -0.35, duration=2.0)

        else:
            print("[RobotController] Unknown command. Doing nothing.")
