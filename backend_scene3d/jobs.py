"""Durable, owner-bound plans and idempotent background calculations."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import sqlite3
import threading
import time
from .datasets import Dataset
from .mechanics import Lines
from .schemas import Parameters

def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)

class Jobs:
    def __init__(self,settings):
        self.settings=settings;settings.runs.mkdir(parents=True,exist_ok=True)
        self.database=settings.runs/'tasks.sqlite3'; self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='scene3d')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS submissions (owner TEXT, key TEXT, plan TEXT UNIQUE, run TEXT, PRIMARY KEY(owner,key))')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database,timeout=30)
        try:
            with db:yield db
        finally:db.close()

    def save(self,record):
        with self.lock,self.connect() as db:
            previous=db.execute('SELECT body FROM records WHERE id=?',(record['id'],)).fetchone()
            if previous and json.loads(previous[0]).get('cancel_requested'):
                record['cancel_requested']=True
            db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',(record['id'],record['owner'],json.dumps(record,ensure_ascii=False)))

    def get(self,identifier,owner):
        with self.connect() as db:
            row=db.execute('SELECT body FROM records WHERE id=? AND owner=?',(identifier,owner)).fetchone()
        if not row:raise KeyError('任务不存在或不可访问')
        return json.loads(row[0])

    def list(self,owner):
        with self.connect() as db:rows=db.execute('SELECT body FROM records WHERE owner=?',(owner,)).fetchall()
        return sorted([json.loads(r[0]) for r in rows if json.loads(r[0])['id'].startswith('s3d_')],key=lambda r:r['created_at'],reverse=True)[:100]

    def plan(self,owner,parameters):
        dataset=Dataset(self.settings.data)
        digest=hashlib.sha256((dataset.assets/'wrf3d/manifest.json').read_bytes()).hexdigest()
        record={'id':'s3p_'+uuid4().hex,'owner':owner,'parameters':parameters.model_dump(),
                'created_at':time.time(),'status':'waiting_confirmation','source_sha256':digest,
                'dataset':dataset.describe()}
        self.save(record);return record

    def submit(self,owner,plan_id,key):
        with self.lock:
            plan=self.get(plan_id,owner)
            with self.connect() as db:
                row=db.execute('SELECT plan,run FROM submissions WHERE owner=? AND key=?',(owner,key)).fetchone()
                previous=db.execute('SELECT run FROM submissions WHERE plan=? AND owner=?',(plan_id,owner)).fetchone()
                if row and row[0]!=plan_id:raise ValueError('幂等键已用于另一计划')
                if row or previous:return self.get((row[1] if row else previous[0]),owner)
                if time.time()-plan['created_at']>1800:raise ValueError('计划已过期，请重新检查参数')
                digest=hashlib.sha256((self.settings.data/'cesium_data/wrf3d/manifest.json').read_bytes()).hexdigest()
                if digest!=plan['source_sha256']:raise ValueError('数据版本已变化，请重新生成计划')
                run=dict(plan,id='s3d_'+uuid4().hex,plan_id=plan_id,status='queued',progress=0)
                db.execute('INSERT INTO records VALUES(?,?,?)',(run['id'],owner,json.dumps(run,ensure_ascii=False)))
                db.execute('INSERT INTO submissions VALUES(?,?,?,?)',(owner,key,plan_id,run['id']))
            self.pool.submit(self.execute,run)
            return run

    def resume(self):
        with self.connect() as db:rows=db.execute('SELECT body FROM records').fetchall()
        for (raw,) in rows:
            record=json.loads(raw)
            if record['status']=='running':
                record.update(status='failed',error='服务重启中断了计算；原任务保留，未自动重放。')
                self.save(record)
            elif record['status']=='queued':self.pool.submit(self.execute,record)

    def import_response(self,parent_id,owner,payload):
        from .responses import validate_response
        parent=self.get(parent_id,owner)
        if parent['status']!='succeeded':raise ValueError('先选择已完成的基础场景任务')
        geometry=json.loads((self.settings.runs/parent_id/'geometry.json').read_text(encoding='utf-8'))
        validate_response(payload,[s['id'] for s in geometry['spans']])
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        key='response_'+parent_id+'_'+digest[:32]
        with self.lock:
            with self.connect() as db:row=db.execute('SELECT run FROM submissions WHERE owner=? AND key=?',(owner,key)).fetchone()
            if row:return self.get(row[0],owner)
            plan=self.plan(owner,Parameters(**parent['parameters']))
            plan.update(response=payload,parent_run_id=parent_id)
            self.save(plan)
            return self.submit(owner,plan['id'],key)

    def execute(self,run):
        try:
            if self.get(run['id'],run['owner']).get('cancel_requested'):
                run.update(status='cancelled');self.save(run);return
            run.update(status='running',progress=1);self.save(run)
            data=Dataset(self.settings.data);lines=Lines(data,Parameters(**run['parameters']))
            folder=self.settings.runs/run['id'];geometry=lines.describe()
            write_json(folder/'geometry.json',geometry)
            dynamic=run.get('response');rows=[];count=len(dynamic['frames']) if dynamic else len(data.manifest['frames'])
            for i in range(count):
                if self.get(run['id'],run['owner']).get('cancel_requested'):
                    run.update(status='cancelled');self.save(run);return
                frame=lines.frame(0 if dynamic else i,dynamic['frames'][i]['spans'] if dynamic else None)
                if dynamic:
                    frame.update(index=i,time=f"{dynamic['frames'][i]['time']:.3f} s",response_time=dynamic['frames'][i]['time'])
                    nodes=[]
                    for wire in frame['wires']:
                        raw=dynamic['frames'][i]['spans'].get(wire['span_id'],{}).get(wire['wire'])
                        if not raw:continue
                        for n,xyz in enumerate(raw):
                            nodes.append({'id':wire['id']+'-'+str(n),'wire_id':wire['id'],'group_id':wire['group_id'],
                                          'point_index':round(n*128/(len(raw)-1)),
                                          'magnitude':sum(v*v for v,part in zip(xyz,('longitudinal','transverse','vertical')) if part in lines.parameters.components)**.5})
                    largest=max(nodes,key=lambda n:n['magnitude'])
                    largest['maximum']=True;frame['response_nodes']=nodes;frame['maximum_response']=largest['magnitude']
                write_json(folder/'frames'/f'{i:03}.json',frame)
                maximum=frame['maximum_response'] if dynamic else max(s['displacement'] for s in frame['spans'])
                rows.append({'index':i,'time':frame['time'],'maximum_displacement':maximum,
                             'maximum_tower_force':max(sum(v*v for v in load)**.5 for load in frame['tower_loads'].values()),
                             'maximum_wind_speed':max(s['wind']['speed'] for s in frame['spans'])})
                run['progress']=round((i+1)/count*95);self.save(run)
            result={'format':'scene3d-result/v1','run_id':run['id'],'dataset':data.describe(),
                    'parameters':run['parameters'],'frames':rows,'groups':geometry['groups'],
                    'minimum_sampled_clearance':lines.minimum_clearance,
                    'maximum_displacement':max(r['maximum_displacement'] for r in rows),
                    'notices':geometry['notices']}
            if dynamic:
                result.update(mode='dynamic_response',sample_interval=dynamic['sampleInterval'],duration=dynamic['duration'],
                              response_source=str(dynamic.get('source','imported'))[:120])
                result['notices']=['导入文件提供节点位移；杆塔荷载栏仍为原WRF近似模型，不代表导入文件的结构力。']+result['notices']
            write_json(folder/'result.json',result)
            run.update(status='succeeded',progress=100,summary=result);self.save(run)
        except Exception as error:
            # Keep host paths out of public errors; detailed traceback stays in server logs.
            import traceback
            traceback.print_exc()
            run.update(status='failed',error=str(error) if isinstance(error,ValueError) else '服务器计算失败，请查看任务日志')
            self.save(run)

    def close(self):self.pool.shutdown(wait=True,cancel_futures=False)
