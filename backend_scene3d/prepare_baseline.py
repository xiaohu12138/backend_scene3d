"""Build the default display cache once during deployment, never from a read request."""
import hashlib
import json
import time
from pathlib import Path
from .config import Settings
from .jobs import Jobs,write_json
from .schemas import Parameters

def main():
    settings=Settings.load()
    digest=hashlib.sha256((settings.data/'cesium_data/wrf3d/manifest.json').read_bytes()+
                           Path(__file__).with_name('mechanics.py').read_bytes()+
                           Path(__file__).with_name('datasets.py').read_bytes()).hexdigest()
    pointer=settings.runs/'baseline.json'
    if pointer.exists() and json.loads(pointer.read_text()).get('version')==digest:
        print('Scene3D baseline already current.');return
    jobs=Jobs(settings);owner='__scene3d_baseline__'
    plan=jobs.plan(owner,Parameters())
    run=jobs.submit(owner,plan['id'],plan['id'])
    while run['status'] in {'queued','running'}:
        time.sleep(.5);run=jobs.get(run['id'],owner)
    jobs.close()
    if run['status']!='succeeded':raise RuntimeError(run.get('error','Baseline preparation failed'))
    write_json(pointer,{'version':digest,'run_id':run['id']})
    print('Baseline prepared:',run['id'])

if __name__=='__main__':main()
