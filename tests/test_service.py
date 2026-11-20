import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import jwt
from fastapi.testclient import TestClient
from backend_scene3d.api import create_app
from backend_scene3d.config import Settings
from backend_scene3d.datasets import Dataset
from backend_scene3d.mechanics import ecef,geodetic,tension,response,Lines
from backend_scene3d.responses import validate_response
from backend_scene3d.schemas import Parameters

class FakeDataset:
    def __init__(self,root):
        self.assets=root/'cesium_data'
        self.manifest={'bounds':{'west':118.63,'east':118.97,'south':31.91,'north':32.2},'times':['t0','t1'],
                       'frames':[{},{}],'dimensions':{'x':102,'y':102,'level':88,'time':2}}
    def describe(self):return {'id':'nanjing','name':'test','times':['t0','t1']}
    def elevation(self,lon,lat):return 10.
    def sample(self,index,lon,lat,height=60):return {'u':3.,'v':4.,'w':.5,'speed':math.sqrt(25.25),'level':0,'heightAgl':height,'frame':index}
    def maximum(self,index,height=60):return dict(self.sample(index,0,0,height),longitude=118.8,latitude=32.05,directionDegrees=53.13)

class MechanicsTest(unittest.TestCase):
    def test_dynamic_response_respects_component_mask(self):
        import numpy as np
        lines=Lines(FakeDataset(Path('.')),Parameters(components=['vertical']))
        span=lines.spans[0]
        base=lines.wire(span,'A')
        horizontal=lines.wire(span,'A',nodes=[[2,3,0],[2,3,0]])
        self.assertTrue(np.allclose(base,horizontal,atol=1e-9))
        vertical=lines.wire(span,'A',nodes=[[0,0,2],[0,0,2]])
        self.assertAlmostEqual(float(np.linalg.norm(vertical[64]-base[64])),2.,places=6)

    def test_original_ground_wire_tension_is_not_mass_scaled(self):
        dataset=FakeDataset(Path('.'))
        wind={'u':0.,'v':0.,'w':0.,'speed':0.}
        with patch.object(dataset,'sample',return_value=wind):
            lines=Lines(dataset,Parameters())
            lines.structure(0,[{'wind':wind} for _ in lines.spans])
        span=lines.spans[0];load=lines.loads[span['start']]
        self.assertAlmostEqual(load[0],4*span['tension']*span['te'],places=6)
        self.assertAlmostEqual(load[1],4*span['tension']*span['tn'],places=6)

    def test_terrain_triangles_match_cesium_heightmap_oracle(self):
        import numpy as np
        dataset=object.__new__(Dataset)
        dataset.terrain={'maximumLevel':0,'samples':2}
        with patch.object(dataset,'tile',return_value=np.array([[10.,20.],[30.,80.]])):
            for lon,lat,height in [(-135,45,17.5),(-45,45,22.5),(-135,-45,27.5),(-45,-45,52.5)]:
                self.assertAlmostEqual(dataset.elevation(lon,lat),height)

    def test_ecef_round_trip(self):
        for coordinate in [(118.8,32.06,230),(118.95,31.98,42),(-80,-40,1500)]:
            actual=geodetic(ecef(*coordinate))
            for expected,result in zip(coordinate,actual):self.assertAlmostEqual(expected,result,places=6)

    def test_original_reference_tension(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/legacy_mechanics.json').read_text())
        for case in fixture['cases']:
            self.assertAlmostEqual(tension(case['length'],case['ratio'],case['temperature']),case['tension'],places=6)

    def test_vertical_component_is_not_dropped(self):
        span={'te':1,'tn':0,'length':360,'tension':46651.5}
        wind={'u':3,'v':4,'w':5}
        r=response(wind,span,Parameters())
        self.assertGreater(r['vertical_displacement'],0)
        off=response(wind,span,Parameters(components=['transverse','longitudinal']))
        self.assertEqual(off['vertical_displacement'],0)
        self.assertAlmostEqual(r['transverse_displacement'],off['transverse_displacement'])

    def test_response_validator_rejects_missing_frame_and_nan(self):
        valid={'schema':'transmission-dynamic-response/v1','units':{'time':'s','displacement':'m'},
               'coordinateSystem':{'type':'span-local','components':['along','transverse','vertical']},
               'sampleInterval':.1,'duration':.1,'frames':[{'time':t,'spans':{'S001':{w:[[0,0,0],[0,0,0]] for w in 'ABCG'}}} for t in [0,.1]]}
        self.assertIs(validate_response(valid,['S001']),valid)
        bad=json.loads(json.dumps(valid));bad['frames'][1]['time']=.2
        with self.assertRaises(ValueError):validate_response(bad,['S001'])
        bad=json.loads(json.dumps(valid));bad['frames'][0]['spans']['S001']['A'][0][0]=float('nan')
        with self.assertRaises(ValueError):validate_response(bad,['S001'])

class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        (root/'data/cesium_data/wrf3d').mkdir(parents=True)
        (root/'data/cesium_data/wrf3d/manifest.json').write_text('{}')
        self.settings=Settings(root/'data',root/'runs','x'*64)
        self.patches=[patch('backend_scene3d.api.Dataset',FakeDataset),patch('backend_scene3d.jobs.Dataset',FakeDataset)]
        for item in self.patches:item.start()
        self.app=create_app(self.settings);self.client=TestClient(self.app);self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        for item in self.patches:item.stop()
        self.temp.cleanup()

    def headers(self,owner='alice',role=2):
        now=int(time.time())
        token=jwt.encode({'sub':owner,'role':role,'aud':'backend_scene3d','iat':now,'exp':now+60},self.settings.secret,algorithm='HS256')
        return {'Authorization':'Bearer '+token}

    def test_auth_and_read_only_role(self):
        self.assertEqual(self.client.get('/api/scene3d/datasets').status_code,401)
        self.assertEqual(self.client.get('/api/scene3d/datasets',headers=self.headers(role=1)).status_code,200)
        self.assertEqual(self.client.post('/api/scene3d/plans',json={},headers=self.headers(role=1)).status_code,403)
        self.assertEqual(self.client.post('/api/scene3d/plans',json={'temperature':100},headers=self.headers()).status_code,422)
        self.assertEqual(self.client.post('/api/scene3d/plans',json={'unexpected':1},headers=self.headers()).status_code,422)

    def test_owner_bound_idempotency_and_real_background_result(self):
        h=self.headers();plan=self.client.post('/api/scene3d/plans',json={},headers=h).json()
        self.assertEqual(self.client.get('/api/scene3d/plans/'+plan['id'],headers=self.headers('bob')).status_code,404)
        payload={'plan_id':plan['id'],'idempotency_key':plan['id']}
        first=self.client.post('/api/scene3d/runs',json=payload,headers=h).json()
        second=self.client.post('/api/scene3d/runs',json=payload,headers=h).json()
        self.assertEqual(first['id'],second['id'])
        for _ in range(100):
            run=self.client.get('/api/scene3d/runs/'+first['id'],headers=h).json()
            if run['status'] not in {'running','queued'}:break
            time.sleep(.02)
        self.assertEqual(run['status'],'succeeded',run)
        self.assertEqual(self.client.get('/api/scene3d/runs/'+first['id']+'/geometry',headers=self.headers('bob')).status_code,404)
        geom=self.client.get('/api/scene3d/runs/'+first['id']+'/geometry',headers=h).json()
        self.assertEqual(len(geom['towers']),14)
        self.assertEqual(len(geom['spans']),10)
        self.assertGreaterEqual(geom['minimum_sampled_clearance'],14.9)

    def test_cancel_flag_survives_worker_progress_save(self):
        jobs=self.app.state.jobs
        record={'id':'s3d_'+'a'*32,'owner':'alice','status':'running','progress':1}
        jobs.save(record)
        cancelled=dict(record,cancel_requested=True);jobs.save(cancelled)
        jobs.save(dict(record,progress=60,cancel_requested=False))
        self.assertTrue(jobs.get(record['id'],'alice')['cancel_requested'])

if __name__=='__main__':unittest.main()
