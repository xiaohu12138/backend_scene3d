<!-- scene3d-current-start -->
## 三维场景业务与平台关系

2026-11-20：本仓库已独立发布到 [xiaohu12138/backend_scene3d](https://github.com/xiaohu12138/backend_scene3d)，为私有仓库。协作者需要仓库访问权限才能克隆。

三维场景在智慧气象中属于一个业务子 Agent，整体链路为：主 Agent 调用三维场景子 Agent，子 Agent 通过本机网关提交服务器任务，Vue 页面展示相同任务的结果。本仓库承担后端计算服务职责，不导入其他同级项目的 Python 代码。

| 配套组件 | 仓库或路径 | 配置 |
|---|---|---|
| 三维业务子 Agent | [weather_agentscope](https://github.com/dying311/weather_agentscope) 的 `agents/scene3d` | `WEATHER_AGENTSCOPE_SCENE3D_BASE` 指向本机网关 |
| Vue 三维页面 | [webpage_sys](https://github.com/Leon-Developer-Java/webpage_sys) 的 `/scene3d` | `VITE_SCENE3D_BASE` 指向本机网关 |
| 服务器 API | 本仓库 `backend_scene3d.api` | 默认监听服务器 `127.0.0.1:8013` |
| 本机网关与隧道 | 本仓库 `gateway` 和 `tunnel` | 本机 8013 网关，经本机 18013 隧道访问服务器 8013 |

### Windows 客户端准备

使用项目的 Python 3.11 以上环境，在本仓库运行 `python -m pip install -e ".[client]"` 安装网关和 SSH 客户端依赖。复制 `.env.example` 为 `.env`，配置登录服务、服务器地址和路径；内部服务密钥必须与服务器一致。使用 `scripts/configure-ssh.ps1` 保存当前用户的加密 SSH 密码，并单独核对、配置 `.local/known_hosts` 中的服务器主机密钥。

### 一键启动脚本

平台启动文件已纳入 [deployment/windows](deployment/windows/README.md)。将其中的 `.bat`、`.ps1` 和 `STARTUP.md` 复制到所有业务仓库的共同父目录，检查本机解释器、Redis 和服务依赖后，双击 `start-all.bat`。不能直接在本仓库的部署子目录运行这些脚本。

`stop-managed-services.bat` 只停止受管的本机服务及守护进程。服务器进程需使用 `bash scripts/stop-server.sh` 单独停止；重新启动本机隧道会再次拉起已配置的远端计算服务。

服务器气象数据、Cesium 运行资源、实际 `.env`、密钥、任务结果和虚拟环境不随代码发布，需要按下文单独准备。当前服务处理已有南京数据，未实现通用 DEM 在线下载。本次后端 10 项测试通过；没有在上传时执行新的远端计算。
<!-- scene3d-current-end -->

# backend_scene3d

独立的三维风场与输电线路计算服务。Python 代码不导入任何同级项目，计算进程部署在数据服务器；Vue 页面与 AgentScope 通过 HTTP 对接同一任务。

## 安装和运行

Python 3.11+：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
# 配置 SCENE3D_DATA_ROOT、SCENE3D_RUN_ROOT 和至少32字节的 SCENE3D_SERVICE_SECRET
.venv/bin/python -m backend_scene3d.prepare_baseline
bash scripts/start-server.sh
```

`SCENE3D_DATA_ROOT` 是服务器已有南京数据目录，需包含：

```text
cesium_data/
  terrain_global/manifest.json + 地形.bin瓦片
  wrf3d/manifest.json + 分块.u16风场及.f32静态字段
cesium-app/
  cesium/                         原渲染资源（Cesium 1.144.0）
  transmission-response-demo.json
  transmission-response-cfd-template.json
```

源数据保持只读。默认场景及用户任务写入 `SCENE3D_RUN_ROOT`，不覆盖 `cesium_data`。数据、运行目录、凭据、虚拟环境均不提交 Git。

## 平台接入

服务器 API 默认监听 `127.0.0.1:8013`。本机 `gateway` 监听8013，通过本机18013 SSH隧道访问服务器8013：

```powershell
python -m backend_scene3d.tunnel
python -m uvicorn backend_scene3d.gateway:create_app --factory --host 127.0.0.1 --port 8013
```

网关通过 `backend_auth /api/auth/me` 核验原始 Bearer Token，检查用户角色和撤销状态，然后签发60秒、限定 audience 的内部身份。服务器按用户隔离任务和幂等键。浏览器、子 Agent 不接触SSH密码和服务密钥。

Windows SSH密码使用当前用户DPAPI加密，位于被Git忽略的 `.local/ssh-password.xml`；服务器主机密钥固定在 `.local/known_hosts`。可用 `scripts/configure-ssh.ps1` 保存本机凭据。Linux可使用独立隧道或反向代理接入，不依赖Windows代码。

## 显示资源就绪检查

`GET /api/health` 在基础显示资源齐全时返回 HTTP 200 和 `data_ready: true`；未齐全时返回 HTTP 503、`data_ready: false`、逐项 `checks` 和缺失项 `missing`。检查包含 WRF 清单与其引用的风场分块、地形清单、WRF 地形高度、Cesium 主脚本和样式、默认场景索引、结果、几何及逐帧文件。

健康检查不会生成默认场景、提交计算或修改数据，也不遍历全部地形瓦片验证其内容。缺少默认场景时需按安装步骤执行准备命令；文件不完整时应补齐部署资源，不能将端口已监听视为可显示。

## 接口

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 服务和数据就绪 |
| `GET /api/scene3d/datasets` | 可用数据集 |
| `GET /api/scene3d/datasets/nanjing/baseline` | 部署时预生成的默认场景 |
| `POST /api/scene3d/plans` | 校验、冻结参数及数据版本，计划有效30分钟 |
| `POST /api/scene3d/runs` | 使用plan_id和幂等键提交 |
| `GET /api/scene3d/runs` | 当前用户任务 |
| `GET /api/scene3d/runs/{id}` | 进度和状态 |
| `GET /api/scene3d/runs/{id}/result` | 未放大的结果和逐帧统计 |
| `GET /api/scene3d/runs/{id}/geometry` | 服务器计算的杆塔及线路几何 |
| `GET /api/scene3d/runs/{id}/frames/{index}` | 导线节点、绝缘子、荷载及风场采样 |
| `POST /api/scene3d/runs/{id}/responses` | 校验并处理动态响应，生成新任务 |
| `POST /api/scene3d/runs/{id}/cancel` | 请求取消，不删除结果 |

任务状态为 queued/running/succeeded/failed/cancelled。同一计划重复提交返回原任务；重启中断的运行任务记录为失败，保留结果，不自动重复计算。只有queued任务会在恢复后继续执行。

## 保留的业务口径

沿用原南京页面的地形编码、前32层显示采样、边界最近邻采样、张力兼容方程、12m分量风偏限制和演示净空调整。保留中部、西北、东南山地、山地跨越四组模拟线路，支持增加最大风速线路。

动态响应沿用 `transmission-dynamic-response/v1`，节点分量为沿线、横向、竖向位移，单位米。允许部分线路输入；同一导线各帧节点数须一致。

原模型是模拟线路的近似展示，不等于CFD或有限元结构动力学求解，也不构成真实线路净空认证。运动放大、脉动和地形夸张只影响显示。

## 服务器数据预处理

原 WRF 转换、全球地形切片和风速等值面数值处理已迁入 `scripts/preprocess/`。这些命令在服务器运行，输出使用新的版本目录，不覆盖已有数据：

```bash
python scripts/preprocess/wrf_fields.py /path/to/wrfout /path/to/new-version/wrf3d
python scripts/preprocess/terrain.py /path/to/wgs84-dem.tif /path/to/new-version/terrain_global
python scripts/preprocess/wind_isosurfaces.py /path/to/wrfout /path/to/new-version/wind_isosurfaces
```

WRF 转换使用核心依赖 netCDF4；等值面需安装 `pip install -e '.[preprocess]'`；地形切片需服务器环境提供 `osgeo.gdal`。当前部署直接读取已生成数据，不重复切片。区域卫星影像切片不再作为本页面底图来源。

## 验证

```bash
python -m unittest discover -s tests -v
```

包含权限、所有权、幂等提交、后台计算、取消竞争和原JavaScript张力方程的27组数值对照。前端和AgentScope接入说明见 `docs/INTEGRATION.md`。
