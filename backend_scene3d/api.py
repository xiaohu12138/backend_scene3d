"""Server API. Only the authenticated gateway can issue short-lived service tokens."""
from contextlib import asynccontextmanager
from pathlib import Path
import json
import time
import re
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
import numpy as np
from .config import Settings
from .datasets import Dataset
from .jobs import Jobs
from .readiness import display_readiness
from .schemas import Parameters, Submission

def create_app(settings=None):
    settings=settings or Settings.load();jobs=Jobs(settings)
    @asynccontextmanager
    async def lifespan(app):
        jobs.resume()
        yield
        jobs.close()
    app=FastAPI(title='backend_scene3d',version='0.1.0',lifespan=lifespan)
    app.add_middleware(GZipMiddleware,minimum_size=1000)
    app.state.jobs=jobs

    def identity(request:Request):
        token=request.headers.get('authorization','')
        try:
            payload=jwt.decode(token.removeprefix('Bearer '),settings.secret,algorithms=['HS256'],audience='backend_scene3d',options={'require':['exp','iat','sub','role']})
            if int(payload['role'])<1:raise ValueError()
            return payload
        except (jwt.PyJWTError,ValueError,TypeError):raise HTTPException(401,'需要有效的平台登录身份')

    def writer(user=Depends(identity)):
        if int(user['role'])<2:raise HTTPException(403,'当前账号没有计算权限')
        return user

    def public(record):return {k:v for k,v in record.items() if k not in {'owner','response'}}

    def owned(identifier,user):
        try:return jobs.get(identifier,user['sub'])
        except KeyError:raise HTTPException(404,'任务不存在或不可访问')

    def file_at(root,relative):
        target=(root/relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():raise HTTPException(404,'资产不存在')
        return FileResponse(target)

    @app.get('/api/health')
    def health():
        checks = display_readiness(settings)
        ready = all(checks.values())
        body = {'service': 'backend_scene3d', 'status': 'online' if ready else 'not_ready',
                'data_ready': ready, 'checks': checks,
                'missing': [name for name, available in checks.items() if not available]}
        return JSONResponse(body, status_code=200 if ready else 503)

    @app.get('/api/scene3d/datasets')
    def datasets(user=Depends(identity)):
        return {'items':[Dataset(settings.data).describe()]}

    @app.get('/api/scene3d/datasets/nanjing/render/{index}')
    def render_wind(index:int,user=Depends(identity)):
        dataset=Dataset(settings.data)
        if not 0<=index<len(dataset.manifest['frames']):raise HTTPException(404,'风场帧不存在')
        field=dataset.wind(index)
        speed=np.sqrt(sum(field[k]**2 for k in ('u','v','w')))
        texture=np.stack([field['u'],field['v'],field['w'],speed],axis=-1)
        return Response(np.nan_to_num(texture).astype('<f4').tobytes(),media_type='application/octet-stream')

    def baseline_root():
        pointer=settings.runs/'baseline.json'
        if not pointer.exists():raise HTTPException(409,'默认场景尚未准备，请运行部署准备命令')
        identifier=json.loads(pointer.read_text())['run_id']
        if not re.fullmatch(r's3d_[0-9a-f]{32}',identifier):raise HTTPException(503,'默认场景索引无效')
        return settings.runs/identifier

    @app.get('/api/scene3d/datasets/nanjing/baseline')
    def baseline(user=Depends(identity)):
        return file_at(baseline_root(),'result.json')

    @app.get('/api/scene3d/datasets/nanjing/baseline/{relative:path}')
    def baseline_asset(relative:str,user=Depends(identity)):
        if relative!='geometry' and not re.fullmatch(r'frames/[0-9]{1,4}',relative):raise HTTPException(404,'默认场景资产不存在')
        path='geometry.json' if relative=='geometry' else f'frames/{int(relative.split("/")[1]):03}.json'
        return file_at(baseline_root(),path)

    @app.post('/api/scene3d/plans')
    def plan(body:Parameters,user=Depends(writer)):
        return public(jobs.plan(user['sub'],body))

    @app.post('/api/scene3d/runs')
    def submit(body:Submission,user=Depends(writer)):
        try:return public(jobs.submit(user['sub'],body.plan_id,body.idempotency_key))
        except KeyError:raise HTTPException(404,'计划不存在或不可访问')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.get('/api/scene3d/runs')
    def runs(user=Depends(identity)):return {'items':[public(r) for r in jobs.list(user['sub'])]}

    @app.get('/api/scene3d/runs/{identifier}')
    def run(identifier:str,user=Depends(identity)):return public(owned(identifier,user))

    @app.get('/api/scene3d/plans/{identifier}')
    def read_plan(identifier:str,user=Depends(identity)):return public(owned(identifier,user))

    @app.post('/api/scene3d/runs/{identifier}/cancel')
    def cancel(identifier:str,user=Depends(writer)):
        with jobs.lock:
            record=owned(identifier,user)
            if record['status'] in {'queued','running'}:record['cancel_requested']=True;jobs.save(record)
            return public(record)

    @app.get('/api/scene3d/runs/{identifier}/result')
    def result(identifier:str,user=Depends(identity)):
        record=owned(identifier,user)
        if record['status']!='succeeded':raise HTTPException(409,'计算尚未完成')
        return record['summary']

    @app.post('/api/scene3d/runs/{identifier}/responses')
    async def import_response(identifier:str,request:Request,user=Depends(writer)):
        body=await request.body()
        if len(body)>8*1024*1024:raise HTTPException(413,'动态数据不得超过8MB')
        try:return public(jobs.import_response(identifier,user['sub'],json.loads(body)))
        except KeyError:raise HTTPException(404,'基础场景不存在或不可访问')
        except (ValueError,TypeError) as error:raise HTTPException(422,str(error))

    @app.get('/api/scene3d/examples/{kind}')
    def example(kind:str,user=Depends(identity)):
        names={'dynamic':'transmission-response-demo.json','template':'transmission-response-cfd-template.json'}
        if kind not in names:raise HTTPException(404,'示例不存在')
        return file_at(settings.data/'cesium-app',names[kind])

    @app.get('/api/scene3d/runs/{identifier}/geometry')
    def geometry(identifier:str,user=Depends(identity)):
        owned(identifier,user);return file_at(settings.runs/identifier,'geometry.json')

    @app.get('/api/scene3d/runs/{identifier}/frames/{index}')
    def frame(identifier:str,index:int,user=Depends(identity)):
        owned(identifier,user)
        if not 0<=index<10000:raise HTTPException(404,'帧不存在')
        return file_at(settings.runs/identifier,f'frames/{index:03}.json')

    @app.get('/api/scene3d/assets/{kind}/{relative:path}')
    def asset(kind:str,relative:str,user=Depends(identity)):
        if kind not in {'terrain_global','wrf3d'}:raise HTTPException(404,'资产类型不存在')
        if Path(relative).suffix not in {'.json','.bin','.u16','.f32'}:raise HTTPException(404,'资产不存在')
        return file_at(settings.data/'cesium_data'/kind,relative)

    @app.get('/scene3d-runtime/cesium/{relative:path}')
    def runtime(relative:str):
        # Only third-party rendering resources are public. Source datasets are not mounted.
        if Path(relative).suffix.lower() not in {'.js','.json','.css','.png','.jpg','.svg','.gif','.wasm','.ktx2','.woff','.woff2','.ttf'}:
            raise HTTPException(404,'资源不存在')
        return file_at(settings.data/'cesium-app/cesium',relative)
    return app
