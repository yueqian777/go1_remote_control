# 导航任务控制权

导航模块与网页手动控制共用 `pc/server.py` 内的同一个 `RobotLink`。导航没有第二个 SDK、UDP 或 TCP 控制端口，也不自动执行 `TAKE`、`ARM`。它只能在操作者已经建立并解锁的会话上工作。

配置文件增加本机导航密钥：

```json
{
  "token": "机器狗接收端配对密钥",
  "navigation_token": "仅本机导航 API 使用的密钥"
}
```

导航调用顺序是：

1. `POST /api/navigation/authorize`，提交 `task_id`。服务检查状态反馈新鲜、`control_active=true`、`armed=true`，创建短租约。
2. `POST /api/navigation/command`，每次提交唯一 `command_id` 和一个 primitive：`forward`、`backward`、`strafe_left`、`strafe_right`、`turn_left` 或 `turn_right`。primitive 映射到现有 `RobotLink` 单轴 heartbeat，TTL 默认 0.7 秒。
3. 每次动作由上层闭环用新的视觉 frame、匹配的 command_id、停止反馈和目标位姿确认后，才能提交下一次动作。
4. `POST /api/navigation/stop` 或 `/release` 发送专用 STOP，并撤销导航租约。

浏览器的 STOP、DISARM、断开和释放也会撤销导航租约。租约过期时服务请求 STOP 后清除 task。导航 API 不会把 STOP 当作已确认的电机反馈；真正的停止状态仍需从机器狗遥测读取。

本接口仍然只适用于已有的安全看护和现场急停条件，不能代替遥控器急停。当前版本的导航调用方应使用 `src/go1loc/remote_control_adapter.py` 中的 `NavigationHttpClient`，不要把 `RobotLink` 直接传给旧式适配器。
