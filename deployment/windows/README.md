# Windows 平台启动脚本

本目录保存平台根目录的一键启动与停止脚本。部署时将本目录中的 `.bat`、`.ps1` 和 `STARTUP.md` 复制到所有业务仓库的共同父目录，不能直接在本目录运行。

预期目录包括 `backend_scene3d`、`weather_agentscope`、`webpage_sys`、`backend_auth`、`backend_upload`、`backend_system`、`backend_agent` 和 `DB`。Python 环境和本机依赖需按实际部署调整并安装；私有 `.env`、SSH 凭据、数据库与气象数据另行配置，不在 Git 中发布。

双击 `start-all.bat` 启动。`stop-managed-services.bat` 停止本机受管服务，但不会停止服务器计算服务；服务器可使用 `scripts/stop-server.sh` 单独停止。后续再次启动隧道会重新启动远端计算服务。

Scene3D 的服务器运行环境、数据准备与接口见仓库 README 和 `docs/INTEGRATION.md`。启动器对当前不存在运行入口的模型、WRF 和 ERA5 服务仅报告不可用，不伪造就绪状态。
