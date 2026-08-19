# Go2 VR 沉浸式控制系统

将 Go2 Air 的摄像头画面实时推送到 VIVE Pro 头显，并通过 VIVE Wand 手柄控制机器人移动。

## 系统架构

```text
Go2 Air (WebRTC) ──► go2_driver_node (ROS2) ──► /dev/shm/go2_cam.jpg
                                                        │
                                                   vr_viewer.py
                                                        │
                                          SteamVR Overlay ──► VIVE Pro 头显
VIVE Wand trackpad ──► vr_viewer.py ──► robot_motion_server_ros2.py
                                                        │
                                               /cmd_vel_out (ROS2 Twist)
                                                        │
                                              go2_driver_node ──► 机器人
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `vr_viewer.py` | 主程序：读摄像头 JPEG → 推 SteamVR Overlay；VIVE Wand 手柄输入 → 发送运动指令 |
| `vr_controller.html` | 网页版手柄控制器（手机/平板可用，作为手柄替代） |
| `go2_camera_server.py` | 摄像头 HTTP 服务器（`/video_feed` MJPEG 流） |
| `actions.json` | SteamVR Input action manifest（定义 trackpad / trigger 动作） |
| `bindings_vive_controller.json` | VIVE Wand 按键绑定配置 |

## 依赖

```bash
pip install openvr pillow
# 需要 SteamVR 安装并运行
# 需要 ROS2 + go2_ros2_sdk（提供 go2_driver_node）
```

## 启动顺序

### 1. 连接机器人 WiFi
```bash
nmcli dev wifi connect "Go2_18636" password "88888888" ifname wlx1cbfce35e632
```

### 2. 启动 ROS2 驱动（Terminal 1）
```bash
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
export CONN_TYPE=webrtc ROBOT_IP=192.168.12.1
ros2 launch go2_robot_sdk robot_minimal.launch.py
# 等待出现：[FFmpeg] decoded frame #1
```

### 3. 启动 Motion Server（Terminal 2）
```bash
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
cd ~/go2/voice_control_essential
python3 robot_motion_server_ros2.py
# 监听 :8003
```

### 4. 启动 VR Viewer（Terminal 3，SteamVR 已运行）
```bash
cd ~/go2/vr_control
python3 vr_viewer.py
# 戴上头显后可看到机器人摄像头画面
```

### 5. 切换 Sport Mode（必须，否则机器人不响应移动命令）
```bash
source /opt/ros/jazzy/setup.bash && source ~/ros2_ws/install/setup.bash
ros2 topic pub /webrtc_req go2_interfaces/msg/WebRtcReq \
  "{api_id: 1016, topic: 'rt/api/sport/request'}" --once
```

## 手柄控制

| 操作 | 效果 |
|------|------|
| 触摸 trackpad 并向上滑 | 前进 |
| 触摸 trackpad 并向下滑 | 后退 |
| 触摸 trackpad 并向左滑 | 左转 |
| 触摸 trackpad 并向右滑 | 右转 |
| 松开 trackpad | 停止 |
| 键盘 W/S/A/D（在 vr_viewer 终端） | 同上（调试用） |

## 常见问题

**视频画面不动**：WebRTC 连接断了，重启 Terminal 1 的 ROS2 driver。

**手柄没反应**：先检查 SteamVR 显示手柄连接状态；若连接正常但无输入，检查手柄电量。

**机器人不动**：确认已发送 Sport Mode 命令（api_id 1016）；检查 Terminal 2 motion server 在运行。

**Overlay 黑屏**：头显需要佩戴到位触发 SteamVR proximity sensor，SteamVR 待机时拒绝 overlay 更新。
