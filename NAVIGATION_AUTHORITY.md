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
2. `POST /api/navigation/command`，每次提交任务内唯一的 `command_id` 和一个 primitive：`forward`、`backward`、`strafe_left`、`strafe_right`、`turn_left` 或 `turn_right`。服务创建固定截止时间的自动运动意图，允许的意图时长为 0.05–2.0 秒。
3. `RobotLink` 是唯一发送者。它按约 20 Hz 续发该意图，直到固定截止时间；截止后发送 STOP 并清除意图。接收端仍按 600 ms MOVE TTL 独立失效，PC 网络状态按 3 秒独立失效。视觉端不需要每 0.5 秒重新授权或重发动作。
4. `POST /api/navigation/pause` 只停止有效意图并保留任务租约；`/keepalive` 只续任务授权，不能产生非零运动；`/resume` 只恢复授权，必须提交新的 command_id 才能运动。`POST /api/navigation/stop` 或 `/release` 发送专用 STOP，并撤销导航租约。

浏览器的 STOP、DISARM、断开和释放也会撤销导航租约。租约过期时服务请求 STOP 后清除 task。导航 API 不会把 STOP 当作已确认的电机反馈；真正的停止状态仍需从机器狗遥测读取。

视觉定位短暂失败应调用 pause，进入等待重定位；定位恢复后由视觉端基于当前位姿重新规划，再提交新动作。接口仍然只适用于已有的安全看护和现场急停条件，不能代替遥控器急停。当前版本的导航调用方应使用 `src/go1loc/remote_control_adapter.py` 中的 `NavigationHttpClient`，不要把 `RobotLink` 直接传给旧式适配器。

## 当前模拟验收

`tests/test_cross_repo_navigation.py` 使用原生模拟接收端、PC `App` 和视觉仓库的 `NavigationHttpClient`，验证了授权、实际意图续发、固定截止停止、暂停、恢复不重放旧动作、新 command_id 和人工 STOP。该测试不连接真实 Go1。
