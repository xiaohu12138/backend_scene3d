# 一键启动

双击 `start-all.bat`，会启动并检查当前项目的登录、数据目录、数据处理worker、旧业务后端、Redis、AgentScope、两个前端，以及Scene3D网关、SSH隧道和服务器计算服务。

本机Python统一使用 `D:\Anaconda\envs\weather-agent\python.exe`。所有新启动的服务在后台运行，关闭启动窗口不会停止它们；进程退出后每5秒重试。SSH隧道每30秒检查并恢复指定的远程计算进程。不会启动Docker。

完成HTTP健康检查后打开主页面、智能体、三维场景和独立聊天页。隧道必须返回远程数据就绪，网关必须确认远程服务可用；仅有端口监听不算启动成功。失败时报告具体服务和日志，不打开半就绪页面。

日志和进程身份记录位于 `.local/launcher/`，按端口区分。重复启动复用已就绪服务；已有后台守护进程正在恢复时不会再启动一份。端口被其他程序占用时不会杀掉它。

`stop-managed-services.bat` 可停止由新版启动器创建的本机服务及其守护进程；不会停止启动器运行前已有的独立进程，也不会停止服务器计算服务。停止后可再次双击 `start-all.bat`。

只检查而不启动：`powershell -File .\start-all-websites.ps1 -CheckOnly`。
启动但不打开网页：`powershell -File .\start-all-websites.ps1 -NoBrowser`。

当前本地仍没有8006专用模型、8007 WRF及8010 ERA5历史服务的可运行入口，启动器会明确列出，不能将这些功能报为已启动。Scene3D读取已有WRF结果，不需要启动新的WRF模拟服务。
