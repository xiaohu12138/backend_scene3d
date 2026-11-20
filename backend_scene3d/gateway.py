"""Local platform-authenticated proxy; all scientific work stays on the remote server."""
from contextlib import asynccontextmanager
import os
import time
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response, StreamingResponse
from .config import ROOT
from dotenv import load_dotenv

def create_app():
    load_dotenv(ROOT/'.env')
    remote=os.environ.get('SCENE3D_REMOTE_URL','http://127.0.0.1:18013').rstrip('/')
    auth=os.environ.get('SCENE3D_AUTH_BASE','http://127.0.0.1:8005').rstrip('/')
    secret=os.environ.get('SCENE3D_SERVICE_SECRET','')
    if len(secret.encode())<32:raise RuntimeError('SCENE3D_SERVICE_SECRET is not configured')
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=5),trust_env=False) as client:
            app.state.client=client
            yield
    app=FastAPI(title='Scene3D platform gateway',lifespan=lifespan)
    app.add_middleware(GZipMiddleware,minimum_size=1000)
    app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5177','http://localhost:5177','http://127.0.0.1:5173','http://localhost:5173'],allow_methods=['GET','POST','OPTIONS'],allow_headers=['Authorization','Content-Type'])

    @app.get('/api/health')
    async def health(request:Request):
        try:
            response=await request.app.state.client.get(remote+'/api/health')
            body=response.json()
            if response.status_code!=200 or body.get('service')!='backend_scene3d' or not body.get('data_ready'):
                raise ValueError()
            return {'service':'backend_scene3d_gateway','status':'online','compute':'remote','remote_ready':True}
        except (httpx.HTTPError,ValueError):raise HTTPException(503,'远程三维计算服务暂时不可用')

    async def forward(request,path,require_auth=True):
        client=request.app.state.client;headers={}
        if require_auth:
            authorization=request.headers.get('authorization','')
            if not authorization.startswith('Bearer '):raise HTTPException(401,'请先登录智慧气象')
            try:
                verified=await client.get(auth+'/api/auth/me',headers={'Authorization':authorization})
                body=verified.json();user=body.get('data') or {}
            except (httpx.HTTPError,ValueError):raise HTTPException(503,'认证服务暂时不可用')
            if verified.status_code!=200 or not user.get('uuid'):
                raise HTTPException(401 if verified.status_code!=403 else 403,'登录已失效或没有访问权限')
            role=int(user.get('role',0))
            if role<1 or (request.method!='GET' and role<2):raise HTTPException(403,'没有三维计算权限')
            headers['Authorization']='Bearer '+jwt.encode({'sub':str(user['uuid']),'role':role,'aud':'backend_scene3d','iat':int(time.time()),'exp':int(time.time())+60},secret,algorithm='HS256')
        if request.headers.get('content-type'):headers['Content-Type']=request.headers['content-type']
        length=request.headers.get('content-length')
        if length and int(length)>8*1024*1024:raise HTTPException(413,'请求文件过大')
        try:
            outgoing=client.build_request(request.method,remote+path,params=request.query_params,headers=headers,content=await request.body())
            response=await client.send(outgoing,stream=True)
        except httpx.HTTPError:raise HTTPException(503,'远程三维服务连接失败，请检查 SSH 隧道和服务器')
        async def chunks():
            try:
                async for chunk in response.aiter_bytes():yield chunk
            finally:await response.aclose()
        return StreamingResponse(chunks(),status_code=response.status_code,media_type=response.headers.get('content-type'),headers={'Cache-Control':'no-store' if require_auth else 'public, max-age=3600'})

    @app.api_route('/api/scene3d/{path:path}',methods=['GET','POST'])
    async def business(request:Request,path:str):
        if '..' in path.split('/'):raise HTTPException(404,'接口不存在')
        return await forward(request,'/api/scene3d/'+path)

    @app.get('/scene3d-runtime/cesium/{path:path}')
    async def runtime(request:Request,path:str):
        if '..' in path.split('/'):raise HTTPException(404,'资源不存在')
        return await forward(request,'/scene3d-runtime/cesium/'+path,False)
    return app
