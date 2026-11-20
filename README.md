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
