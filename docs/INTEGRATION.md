# Scene3D integration

- 独立仓库：backend_scene3d。
- 平台页面：webpage_sys `/scene3d?run_id=s3d_...`，Vue中保留三维地形、杆塔和导线。
- 统一底图：webpage_sys/src/utils/basemaps.js，二维包装组件与三维场景共用。GCJ02影像投影单独适配，源地形和业务数据保持WGS84。
- 业务Agent：weather_agentscope/agents/scene3d，key=scene3d，模板前缀 `[weather-template:scene3d:v1]`。
- 使用现有BusinessAgentDefinition/SubAgentTemplate/ToolBase，DomainPolicy隔离工具，TeamSay回报。
- 工具：weather_scene3d_datasets / prepare / run / result / cancel。
- run与cancel使用原生ASK和bypass_immune。计划绑定用户、成员和会话；拒绝确认时没有计算提交。
- 返回统一weather_result 2.0。主Agent的只读结果工具读取run_id；结果卡发送weather-agent-open-scene3d。
- Vue宿主校验消息origin/source及run_id格式后导航，不接受工具生成的任意URL。
- 配置项：WEATHER_AGENTSCOPE_SCENE3D_BASE（默认http://127.0.0.1:8013）、VITE_SCENE3D_BASE（同默认值）。
- 修改不涉及原有icing/nowcast/wrf模板、计算合同或依赖锁文件。

## 源码整理

原浏览器的风场解码、最大风搜索、张力、荷载、线路响应已进入服务器模块；Vue只消费服务器几何、纹理和统计。原WebGPU显示内核迁入scene3d/windRenderer.js，删除了CPU业务采样和解码函数。

完成页面、服务器任务、动态导入、结果恢复及原方程数值核验后，旧nanjing的13份展示/处理源码已先归档至服务器 `hhj/scene3d-migration-backups/legacy-source-20261020-202050.tar.gz`，再从旧活动目录移除；旧1290预览服务已停止。

旧数据目录的Cesium运行资源和动态示例仍是运行依赖。源WRF、DEM、cesium_data、versions和历史任务保留。新处理入口为本仓库 `scripts/preprocess/`，不再包含旧区域卫星底图切片入口。
