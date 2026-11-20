"""Validate the existing transmission-dynamic-response/v1 import contract."""
import math

def validate_response(value,known_spans):
    if not isinstance(value,dict) or value.get('schema')!='transmission-dynamic-response/v1':raise ValueError('动态响应格式必须是 transmission-dynamic-response/v1')
    if value.get('units')!={'time':'s','displacement':'m'}:raise ValueError('动态数据必须使用秒和米')
    coordinates=value.get('coordinateSystem',{})
    if coordinates.get('type')!='span-local' or coordinates.get('components')!=['along','transverse','vertical']:
        raise ValueError('节点分量必须为档距局部坐标的 along/transverse/vertical')
    frames=value.get('frames');interval=value.get('sampleInterval');duration=value.get('duration')
    if not isinstance(frames,list) or not 2<=len(frames)<=3000:raise ValueError('动态响应需要2至3000帧')
    if not isinstance(interval,(float,int)) or not math.isfinite(interval) or interval<=0:raise ValueError('采样间隔无效')
    if not isinstance(duration,(float,int)) or not math.isfinite(duration) or duration<=0:raise ValueError('持续时间无效')
    sizes={};provided=None;last=-1
    for index,frame in enumerate(frames):
        if not isinstance(frame,dict):raise ValueError('每个动态时间帧必须是对象')
        t=frame.get('time');spans=frame.get('spans')
        if not isinstance(t,(float,int)) or not math.isfinite(t) or t<=last or abs(t-index*interval)>max(1e-6,interval*1e-5):raise ValueError('时间帧必须从0按采样间隔递增')
        if not isinstance(spans,dict) or not spans or set(spans)-set(known_spans):raise ValueError('动态文件包含未知或空档距')
        if provided is None:provided=set(spans)
        elif set(spans)!=provided:raise ValueError('各时间帧必须包含同一组档距')
        for span,wires in spans.items():
            if not isinstance(wires,dict):raise ValueError('档距导线数据必须是对象')
            if set(wires)!={'A','B','C','G'}:raise ValueError('提供的档距必须包含A/B/C/G四根导线')
            for wire,nodes in wires.items():
                if not isinstance(nodes,list) or not 2<=len(nodes)<=513:raise ValueError('节点数必须在2至513之间')
                key=(span,wire)
                if key in sizes and sizes[key]!=len(nodes):raise ValueError('同一导线各帧节点数量不一致')
                sizes[key]=len(nodes)
                for node in nodes:
                    if not isinstance(node,list) or len(node)!=3 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in node):raise ValueError('节点位移必须为三个有限数值')
        last=t
    if abs(last-duration)>max(1e-6,interval*1e-5):raise ValueError('持续时间与末帧时间不一致')
    return value
