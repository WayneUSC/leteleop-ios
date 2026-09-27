# LeTeleop-iOS

原生 iOS 位姿控制客户端，以及用于验证控制流程的 Python 模拟后端。

[English](README.md) · [iOS 构建说明](ios/README.md) · [协议](docs/protocol.md)

**当前是仅支持模拟后端的 alpha 版本。** 它适合研究手机位姿、离合控制和会话录制；尚未实现真实机械臂控制、标定后的运动学或标准 LeRobot 数据集导出。

## 可以做什么

- 用 SwiftUI / ARKit 发送手机位姿，操作按住移动、夹爪目标和录制开关。
- 通过 TCP 逐行发送 JSON，服务器按离合锚点计算相对位姿。
- 校验输入、限制为一个控制客户端，并在释放、超时或断连时保持模拟状态。
- 录制本地 JSON 会话，重启后保留已有文件。

模拟后端是简化的末端状态模型，不是经过验证的逆运动学或物理仿真。ARKit 更新率与网络时延受设备和环境影响，没有 60 Hz 或低于 20 ms 的保证。

## 本地运行

需要 Python 3.10 或更新版本：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m leteleop.cli --host 127.0.0.1 --port 8765 --robot mock
```

另开终端执行 `python examples/send_mock_session.py`，即可向本地模拟后端发送示例会话。iOS 工程生成、权限和真机构建见 [iOS 说明](ios/README.md)。

手机连接需要显式绑定电脑可信局域网地址。协议没有认证或加密，只用于隔离的开发网络。不要接入真实执行器或暴露到公网。首次连接、超时或重连后，需要释放再按下离合；释放时夹爪目标也不会变化。

## 开源范围

- 本地 JSON 是项目自己的诊断格式，不是 LeRobot v2/v3 标准；直接上传文件不会获得训练兼容性。
- [LeRobot 已有手机遥操作方案](https://github.com/huggingface/lerobot/blob/main/docs/source/phone_teleop.mdx)。本项目的重点是便于阅读和修改的原生客户端与实验流程，不宣称首创。
- Python 测试覆盖数据与控制逻辑；iOS 编译检查与真机验证是不同环节。尚未完成真实机械臂、设备跟踪或时延实验。

欢迎提供可复现的问题、设备测试记录和经过独立验证的适配器。采用 [Apache 2.0](LICENSE) 许可证，由 [@WayneUSC](https://github.com/WayneUSC) 维护。
