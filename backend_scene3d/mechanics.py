"""Server-side port of the original visual-demo line mechanics.

Coordinates use WGS84 ECEF. No vertical exaggeration or motion amplification
enters physical results. These approximations are not CFD/structural certification.
"""
import copy
import math
import numpy as np

WEIGHT = 1.3475*9.80665
ATTACHMENTS = [('A',-7,34,2.4,35),('B',0,38,2.4,35),('C',7,34,2.4,35),('G',0,42,1.5,20)]
GROUPS = [dict(id='L1',name='中部线路',east=0,north=0),
          dict(id='L2',name='西北线路',east=-9000,north=7000),
          dict(id='L3',name='东南山地线路',longitude=118.951,latitude=31.988,rotation=90),
          dict(id='L4',name='山地跨越线路',positions=[(118.8200,32.0725),(118.8350,32.0725)])]

def ecef(lon, lat, height):
    lon,lat=math.radians(lon),math.radians(lat)
    n=6378137/math.sqrt(1-0.0066943799901413165*math.sin(lat)**2)
    return np.array([(n+height)*math.cos(lat)*math.cos(lon),
                     (n+height)*math.cos(lat)*math.sin(lon),
                     (n*(1-0.0066943799901413165)+height)*math.sin(lat)])

def geodetic(points):
    p=np.asarray(points); x,y,z=p[...,0],p[...,1],p[...,2]
    radius=np.hypot(x,y); lat=np.arctan2(z,radius*(1-0.0066943799901413165))
    for _ in range(7):
        n=6378137/np.sqrt(1-0.0066943799901413165*np.sin(lat)**2)
        h=radius/np.cos(lat)-n
        lat=np.arctan2(z,radius*(1-0.0066943799901413165*n/(n+h)))
    return np.stack([np.degrees(np.arctan2(y,x)),np.degrees(lat),h],axis=-1)

def axes(lon,lat):
    lo,la=math.radians(lon),math.radians(lat)
    return np.array([[-math.sin(lo),math.cos(lo),0],
                     [-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)],
                     [math.cos(la)*math.cos(lo),math.cos(la)*math.sin(lo),math.sin(la)]])

def offset(origin, xyz):
    lon,lat,_=geodetic(np.asarray(origin))
    return np.asarray(origin)+np.asarray(xyz)@axes(lon,lat)

def distance(a,b):
    east=(b['longitude']-a['longitude'])*111320*math.cos(math.radians((a['latitude']+b['latitude'])/2))
    north=(b['latitude']-a['latitude'])*111320
    return math.hypot(east,north),east,north

def tension(length, ratio, temperature):
    reference=103670*ratio; ea=65e9*425.24e-6
    target=reference/ea+WEIGHT**2*length**2/(24*reference**2)-20.5e-6*(temperature-20)
    wl=WEIGHT**2*length**2/24
    strain=lambda t:t/ea+wl/(t*t)
    critical=(2*wl*ea)**(1/3)
    low=max(reference*0.2,critical*1.000001); high=max(reference*1.5,103670*.85)
    while strain(high)<target and high<103670*.98: high*=1.25
    if target>strain(low):
        for _ in range(60):
            mid=(low+high)/2
            if strain(mid)<target: low=mid
            else: high=mid
        return (low+high)/2
    return low

def response(wind, span, parameters):
    along=wind['u']*span['te']+wind['v']*span['tn']
    normal_e=wind['u']-along*span['te']; normal_n=wind['v']-along*span['tn']
    normal=math.hypot(normal_e,normal_n)
    factor=.5*1.225*1*.0268*span['length']**2/(8*span['tension'])
    clamp=lambda v:max(-12,min(12,v))
    transverse=clamp(factor*normal*abs(normal)) if 'transverse' in parameters.components else 0
    longitudinal=clamp(factor*.1*along*abs(along)) if 'longitudinal' in parameters.components else 0
    vertical=clamp(factor*wind['w']*abs(wind['w'])) if 'vertical' in parameters.components else 0
    east=(transverse*normal_e/normal if normal else 0)+longitudinal*span['te']
    north=(transverse*normal_n/normal if normal else 0)+longitudinal*span['tn']
    return {'wind':wind,'transverse_speed':normal,'along_speed':along,
            'transverse_displacement':transverse,'longitudinal_displacement':longitudinal,
            'vertical_displacement':vertical,'displacement':math.sqrt(east*east+north*north+vertical*vertical),
            'enu':[east,north,vertical]}

class Lines:
    def __init__(self,dataset,parameters):
        self.dataset,self.parameters=dataset,parameters
        b=dataset.manifest['bounds']; centre=((b['west']+b['east'])/2,(b['south']+b['north'])/2)
        self.groups=copy.deepcopy(GROUPS)
        if parameters.maximum_wind_line:
            maximum=dataset.maximum(0,parameters.sample_height)
            self.groups.append(dict(id='LMAX',name='最大风速线路',longitude=maximum['longitude'],
                                    latitude=maximum['latitude'],rotation=maximum['directionDegrees']+90))
        self.towers=[];self.spans=[]
        for group in self.groups:
            positions=group.get('positions'); layout=positions or [(-540,-80),(-180,0),(180,35),(540,120)]
            lo=group.get('longitude',centre[0]+group.get('east',0)/(111320*math.cos(math.radians(centre[1]))))
            la=group.get('latitude',centre[1]+group.get('north',0)/111320)
            rotation=math.radians(group.get('rotation',0)); current=[]
            for i,(x,y) in enumerate(layout):
                east=x*math.cos(rotation)-y*math.sin(rotation); north=x*math.sin(rotation)+y*math.cos(rotation)
                lon,lat=(x,y) if positions else (lo+east/(111320*math.cos(math.radians(la))),la+north/111320)
                prefix='' if group['id']=='L1' else group['id']+'-'
                tower=dict(id=f'{prefix}T{i+1:03}',group_id=group['id'],longitude=lon,latitude=lat,
                           height=42.,ground_height=dataset.elevation(lon,lat))
                current.append(tower);self.towers.append(tower)
            for i,(a,b) in enumerate(zip(current,current[1:])):
                length,east,north=distance(a,b)
                t=tension(length,parameters.tension_ratio,parameters.temperature)
                self.spans.append(dict(id=f'{"" if group["id"]=="L1" else group["id"]+"-"}S{i+1:03}',
                    group_id=group['id'],start=a['id'],end=b['id'],length=length,tension=t,
                    te=east/length,tn=north/length,sag=WEIGHT*length*length/(8*t)))
        self.by_id={t['id']:t for t in self.towers}
        self.states={};self.loads={}
        self.minimum_clearance=None
        for attempt in range(3):
            minimum=math.inf;lifts={t['id']:0. for t in self.towers}
            for span in self.spans:
                for wire,*_ in ATTACHMENTS:
                    points=geodetic(self.wire(span,wire))
                    deficit=0.
                    for lon,lat,height in points:
                        clearance=float(height)-dataset.elevation(float(lon),float(lat))
                        minimum=min(minimum,clearance);deficit=max(deficit,15-clearance)
                    for key in (span['start'],span['end']): lifts[key]=max(lifts[key],deficit)
            self.minimum_clearance=minimum
            if minimum>=14.9:break
            if attempt==2:raise ValueError('模拟线路地形净空检查未通过')
            for tower in self.towers:
                if lifts[tower['id']]>0:tower['height']+=math.ceil((lifts[tower['id']]+1)*42/34)

    def anchor(self,tower,wire,endpoint=True):
        _,y,z,length,_=next(a for a in ATTACHMENTS if a[0]==wire)
        xyz=ecef(tower['longitude'],tower['latitude'],tower['ground_height'])
        anchor=offset(xyz,[0,y,z*tower['height']/42])
        return offset(anchor,self.states.get((tower['id'],wire),[0,0,-length])) if endpoint else anchor

    def wire(self,span,wire,enu=None,nodes=None):
        a,b=self.by_id[span['start']],self.by_id[span['end']]
        start,end=self.anchor(a,wire),self.anchor(b,wire)
        middle=(start+end)/2; lo,la,_=geodetic(middle); basis=axes(lo,la)
        up=middle/np.array([6378137**2,6378137**2,6356752.314245179**2]);up/=np.linalg.norm(up)
        s=np.linspace(0,1,129)
        points=start[None,:]*(1-s[:,None])+end[None,:]*s[:,None]
        points-=4*s[:,None]*(1-s[:,None])*span['sag']*(.58 if wire=='G' else 1)*up
        if enu is not None:points+=np.sin(math.pi*s[:,None])*(np.asarray(enu)@basis)
        if nodes is not None:
            values=np.asarray(nodes,dtype=float);node_s=np.linspace(0,1,len(values))
            values=values*np.array([part in self.parameters.components for part in ('longitudinal','transverse','vertical')])
            vals=np.stack([np.interp(s,node_s,values[:,i]) for i in range(3)],axis=-1)
            tangent=span['te']*basis[0]+span['tn']*basis[1]
            transverse=-span['tn']*basis[0]+span['te']*basis[1]
            points+=vals[:,0,None]*tangent+vals[:,1,None]*transverse+vals[:,2,None]*up
        return points

    def structure(self,index,responses):
        loads={(t['id'],wire):np.zeros(3) for t in self.towers for wire,*_ in ATTACHMENTS}
        self.loads={t['id']:np.zeros(3) for t in self.towers}
        for span,r in zip(self.spans,responses):
            w=r['wind']; vw=w['w'] if 'vertical' in self.parameters.components else 0
            speed=math.sqrt(w['u']**2+w['v']**2+vw**2)
            q=.5*1.225*.0268*speed*speed
            windload=q*span['length']/2*np.array([w['u'],w['v'],vw])/speed if speed else np.zeros(3)
            weight=np.array([0,0,-WEIGHT*span['length']/2])
            t=span['tension']*np.array([span['te'],span['tn'],0])
            for wire,*_ in ATTACHMENTS:
                f=.75 if wire=='G' else 1
                loads[(span['start'],wire)]+=t+(windload+weight)*f
                loads[(span['end'],wire)]+=-t+(windload+weight)*f
        for tower in self.towers:
            wind=self.dataset.sample(index,tower['longitude'],tower['latitude'],tower['height']/2)
            if wind['speed']:
                vec=np.array([wind['u'],wind['v'],wind['w'] if 'vertical' in self.parameters.components else 0])
                self.loads[tower['id']]+=.5*1.225*1.8*wind['speed']**2*20*vec/wind['speed']
            for wire,y,z,length,mass in ATTACHMENTS:
                load=loads[(tower['id'],wire)]; horizontal=math.hypot(load[0],load[1])
                angle=min(math.radians(28),math.atan2(horizontal,max(1,mass*9.80665+abs(load[2]))))
                scale=length*math.sin(angle)/horizontal if horizontal else 0
                self.states[(tower['id'],wire)]=[load[0]*scale,load[1]*scale,-length*math.cos(angle)]
                self.loads[tower['id']]+=load-np.array([0,0,mass*9.80665])

    def frame(self,index,dynamic=None):
        responses=[]
        for span in self.spans:
            a,b=self.by_id[span['start']],self.by_id[span['end']]
            wind=self.dataset.sample(index,(a['longitude']+b['longitude'])/2,(a['latitude']+b['latitude'])/2,(a['height']+b['height'])/2)
            responses.append(response(wind,span,self.parameters))
        self.structure(index,responses)
        wires=[]
        for span,r in zip(self.spans,responses):
            for wire,*_ in ATTACHMENTS:
                baseline=self.wire(span,wire)
                nodes=(dynamic or {}).get(span['id'],{}).get(wire)
                displaced=self.wire(span,wire,None if dynamic else r['enu'],nodes)
                wires.append({'id':span['id']+'-'+wire,'span_id':span['id'],'wire':wire,'group_id':span['group_id'],
                              'base':baseline.tolist(),'positions':displaced.tolist()})
        return {'index':index,'time':self.dataset.manifest['times'][index],
                'wires':wires,'spans':[dict(id=s['id'],group_id=s['group_id'],tension=s['tension'],sag=s['sag'],**r) for s,r in zip(self.spans,responses)],
                'tower_loads':{k:v.tolist() for k,v in self.loads.items()},
                'insulators':[{'tower_id':t['id'],'wire':w,'anchor':self.anchor(t,w,False).tolist(),
                               'endpoint':self.anchor(t,w).tolist()} for t in self.towers for w,*_ in ATTACHMENTS]}

    def describe(self):
        return {'groups':self.groups,'towers':self.towers,'spans':self.spans,
                'minimum_sampled_clearance':self.minimum_clearance,'simulated':True,
                'notices':['线路为模拟线路，15 m 是采样净空演示目标，不是工程净空认证。',
                           '风偏采用原演示近似模型，非 CFD 或有限元结构动力学结果。',
                           '运动放大和地形夸张仅用于显示，统计值保持未放大数值。']}
