from __future__ import annotations
import math, re
from typing import List, Tuple, Iterable
from xml.etree import ElementTree as ET
from .models import Point, Path, SceneObject

EPS = 1e-6

def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0]-b[0], a[1]-b[1])

def path_length(path: Path) -> float:
    return sum(dist(a,b) for a,b in zip(path, path[1:]))

def is_closed(path: Path, tol: float=1e-4) -> bool:
    return len(path) > 2 and dist(path[0], path[-1]) <= tol

def bbox(paths: List[Path]):
    pts=[p for path in paths for p in path]
    if not pts: return (0,0,0,0)
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return min(xs),min(ys),max(xs),max(ys)

def transform_path(path: Path, x=0, y=0, scale=1.0, rotation_deg=0.0, mirror_x=False, mirror_y=False):
    a=math.radians(rotation_deg); ca,sa=math.cos(a),math.sin(a)
    out=[]
    for px,py in path:
        px*= -1 if mirror_x else 1
        py*= -1 if mirror_y else 1
        px*=scale; py*=scale
        rx=px*ca-py*sa; ry=px*sa+py*ca
        out.append((rx+x, ry+y))
    return out

def transformed_paths(obj: SceneObject):
    return [transform_path(p,obj.x,obj.y,obj.scale,obj.rotation_deg,obj.mirror_x,obj.mirror_y) for p in obj.paths]

def _bezier3(p0,p1,p2,p3,t):
    u=1-t
    return (u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0],
            u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1])

def _bezier2(p0,p1,p2,t):
    u=1-t
    return (u*u*p0[0]+2*u*t*p1[0]+t*t*p2[0],u*u*p0[1]+2*u*t*p1[1]+t*t*p2[1])

def _svg_arc_points(p0, rx, ry, phi_deg, large_arc, sweep, p1, steps_hint=12):
    if rx == 0 or ry == 0 or dist(p0,p1) < EPS:
        return [p1]
    rx,ry=abs(rx),abs(ry);phi=math.radians(phi_deg%360);cp,sp=math.cos(phi),math.sin(phi)
    dx=(p0[0]-p1[0])/2;dy=(p0[1]-p1[1])/2
    xp=cp*dx+sp*dy;yp=-sp*dx+cp*dy
    lam=xp*xp/(rx*rx)+yp*yp/(ry*ry)
    if lam>1:
        k=math.sqrt(lam);rx*=k;ry*=k
    num=max(0.0,rx*rx*ry*ry-rx*rx*yp*yp-ry*ry*xp*xp)
    den=max(EPS,rx*rx*yp*yp+ry*ry*xp*xp)
    coef=math.sqrt(num/den)
    if bool(large_arc)==bool(sweep):coef=-coef
    cxp=coef*(rx*yp/ry);cyp=coef*(-ry*xp/rx)
    cx=cp*cxp-sp*cyp+(p0[0]+p1[0])/2;cy=sp*cxp+cp*cyp+(p0[1]+p1[1])/2
    def vang(ux,uy,vx,vy):
        dot=max(-1,min(1,ux*vx+uy*vy));a=math.acos(dot)
        return -a if ux*vy-uy*vx<0 else a
    ux=(xp-cxp)/rx;uy=(yp-cyp)/ry;vx=(-xp-cxp)/rx;vy=(-yp-cyp)/ry
    a0=vang(1,0,ux,uy);da=vang(ux,uy,vx,vy)
    if not sweep and da>0:da-=2*math.pi
    if sweep and da<0:da+=2*math.pi
    n=max(steps_hint,int(abs(da)*max(rx,ry)/0.75))
    out=[]
    for i in range(1,n+1):
        a=a0+da*i/n
        x=cx+cp*rx*math.cos(a)-sp*ry*math.sin(a);y=cy+sp*rx*math.cos(a)+cp*ry*math.sin(a)
        out.append((x,y))
    return out

def parse_svg_path(d: str, curve_steps: int=16) -> List[Path]:
    tokens=re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?', d.replace(',', ' '))
    i=0; cmd=None; cur=(0.0,0.0); start=None; paths=[]; path=[]; last_cubic=None; last_quad=None
    def num():
        nonlocal i
        if i>=len(tokens) or re.match(r'[A-Za-z]',tokens[i]):raise ValueError('Недостаточно параметров SVG path')
        v=float(tokens[i]); i+=1; return v
    while i<len(tokens):
        if re.match(r'[A-Za-z]',tokens[i]): cmd=tokens[i]; i+=1
        if cmd is None: raise ValueError('SVG path без команды')
        rel=cmd.islower(); C=cmd.upper()
        if C=='M':
            x,y=num(),num(); x+=cur[0] if rel else 0; y+=cur[1] if rel else 0
            if path: paths.append(path)
            cur=(x,y); start=cur; path=[cur]; cmd='l' if rel else 'L';last_cubic=last_quad=None
        elif C=='L':
            x,y=num(),num(); x+=cur[0] if rel else 0; y+=cur[1] if rel else 0; cur=(x,y); path.append(cur);last_cubic=last_quad=None
        elif C=='H':
            x=num(); x+=cur[0] if rel else 0; cur=(x,cur[1]); path.append(cur);last_cubic=last_quad=None
        elif C=='V':
            y=num(); y+=cur[1] if rel else 0; cur=(cur[0],y); path.append(cur);last_cubic=last_quad=None
        elif C=='C':
            x1,y1,x2,y2,x,y=[num() for _ in range(6)]
            if rel:
                x1+=cur[0];y1+=cur[1];x2+=cur[0];y2+=cur[1];x+=cur[0];y+=cur[1]
            p0=cur
            for st in range(1,curve_steps+1): path.append(_bezier3(p0,(x1,y1),(x2,y2),(x,y),st/curve_steps))
            cur=(x,y);last_cubic=(x2,y2);last_quad=None
        elif C=='S':
            x2,y2,x,y=[num() for _ in range(4)]
            if rel:x2+=cur[0];y2+=cur[1];x+=cur[0];y+=cur[1]
            x1,y1=(2*cur[0]-last_cubic[0],2*cur[1]-last_cubic[1]) if last_cubic else cur
            p0=cur
            for st in range(1,curve_steps+1):path.append(_bezier3(p0,(x1,y1),(x2,y2),(x,y),st/curve_steps))
            cur=(x,y);last_cubic=(x2,y2);last_quad=None
        elif C=='Q':
            x1,y1,x,y=[num() for _ in range(4)]
            if rel: x1+=cur[0];y1+=cur[1];x+=cur[0];y+=cur[1]
            p0=cur
            for st in range(1,curve_steps+1): path.append(_bezier2(p0,(x1,y1),(x,y),st/curve_steps))
            cur=(x,y);last_quad=(x1,y1);last_cubic=None
        elif C=='T':
            x,y=num(),num()
            if rel:x+=cur[0];y+=cur[1]
            x1,y1=(2*cur[0]-last_quad[0],2*cur[1]-last_quad[1]) if last_quad else cur
            p0=cur
            for st in range(1,curve_steps+1):path.append(_bezier2(p0,(x1,y1),(x,y),st/curve_steps))
            cur=(x,y);last_quad=(x1,y1);last_cubic=None
        elif C=='A':
            rx,ry,rot,large,sweep,x,y=[num() for _ in range(7)]
            if rel:x+=cur[0];y+=cur[1]
            path.extend(_svg_arc_points(cur,rx,ry,rot,int(large)!=0,int(sweep)!=0,(x,y),curve_steps));cur=(x,y);last_cubic=last_quad=None
        elif C=='Z':
            if start and (not path or dist(path[-1],start)>EPS): path.append(start)
            cur=start or cur; cmd=None;last_cubic=last_quad=None
            if path: paths.append(path); path=[]
        else:
            raise ValueError(f'Неподдерживаемая SVG-команда: {cmd}')
    if path: paths.append(path)
    return [p for p in paths if len(p)>=2]

def _svg_points(s):
    nums=[float(x) for x in re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?',s)]
    return list(zip(nums[0::2], nums[1::2]))

def _matmul(a,b):
    A,B,C,D,E,F=a;g,h,i,j,k,l=b
    return (A*g+C*h, B*g+D*h, A*i+C*j, B*i+D*j, A*k+C*l+E, B*k+D*l+F)

def _parse_transform(text):
    m=(1,0,0,1,0,0)
    for name,args in re.findall(r'([A-Za-z]+)\s*\(([^)]*)\)',text or ''):
        v=[float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?',args)];name=name.lower();t=(1,0,0,1,0,0)
        if name=='matrix' and len(v)>=6:t=tuple(v[:6])
        elif name=='translate' and v:t=(1,0,0,1,v[0],v[1] if len(v)>1 else 0)
        elif name=='scale' and v:t=(v[0],0,0,v[1] if len(v)>1 else v[0],0,0)
        elif name=='rotate' and v:
            a=math.radians(v[0]);ca,sa=math.cos(a),math.sin(a);r=(ca,sa,-sa,ca,0,0)
            if len(v)>=3:t=_matmul(_matmul((1,0,0,1,v[1],v[2]),r),(1,0,0,1,-v[1],-v[2]))
            else:t=r
        elif name=='skewx' and v:t=(1,0,math.tan(math.radians(v[0])),1,0,0)
        elif name=='skewy' and v:t=(1,math.tan(math.radians(v[0])),0,1,0,0)
        m=_matmul(m,t)
    return m

def _apply_mat(p,m):
    a,b,c,d,e,f=m;x,y=p;return (a*x+c*y+e,b*x+d*y+f)

def load_svg(filename: str) -> List[Path]:
    root=ET.parse(filename).getroot(); out=[]
    ns=lambda tag: tag.split('}')[-1]
    vb=root.attrib.get('viewBox','').replace(',',' ').split(); sx=sy=25.4/96.0;vx=vy=0.0
    def unit_mm(v):
        mt=re.match(r'\s*([-+\d.eE]+)\s*(mm|cm|in|px)?',v or '')
        if not mt:return None
        n=float(mt.group(1));u=mt.group(2) or 'px';return n*({'mm':1,'cm':10,'in':25.4,'px':25.4/96}[u])
    if len(vb)==4:
        vx,vy,vw,vh=map(float,vb);w=unit_mm(root.attrib.get('width'));h=unit_mm(root.attrib.get('height'))
        if w and h and vw and vh:sx=w/vw;sy=h/vh
    root_map=(sx,0,0,sy,-vx*sx,-vy*sy)
    def walk(e,parent=(1,0,0,1,0,0)):
        local=_matmul(parent,_parse_transform(e.attrib.get('transform','')));t=ns(e.tag);ps=[]
        try:
            if t=='path' and e.attrib.get('d'):ps=parse_svg_path(e.attrib['d'])
            elif t in ('polyline','polygon'):
                q=_svg_points(e.attrib.get('points',''))
                if t=='polygon' and q and q[0]!=q[-1]:q.append(q[0])
                ps=[q] if len(q)>=2 else []
            elif t=='line':ps=[[(float(e.attrib.get('x1',0)),float(e.attrib.get('y1',0))),(float(e.attrib.get('x2',0)),float(e.attrib.get('y2',0)))]]
            elif t=='rect':
                x=float(e.attrib.get('x',0));y=float(e.attrib.get('y',0));w=float(e.attrib.get('width',0));h=float(e.attrib.get('height',0));ps=[[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]]
            elif t=='circle':
                cx=float(e.attrib.get('cx',0));cy=float(e.attrib.get('cy',0));r=float(e.attrib.get('r',0));n=72;q=[(cx+r*math.cos(2*math.pi*k/n),cy+r*math.sin(2*math.pi*k/n)) for k in range(n)];q.append(q[0]);ps=[q]
            elif t=='ellipse':
                cx=float(e.attrib.get('cx',0));cy=float(e.attrib.get('cy',0));rx=float(e.attrib.get('rx',0));ry=float(e.attrib.get('ry',0));n=72;q=[(cx+rx*math.cos(2*math.pi*k/n),cy+ry*math.sin(2*math.pi*k/n)) for k in range(n)];q.append(q[0]);ps=[q]
        except (ValueError,KeyError):raise
        for q in ps:out.append([_apply_mat(_apply_mat(pt,local),root_map) for pt in q])
        for child in list(e):walk(child,local)
    walk(root)
    return out

def load_dxf(filename: str) -> List[Path]:
    import ezdxf
    doc=ezdxf.readfile(filename); msp=doc.modelspace(); out=[]
    for e in msp:
        typ=e.dxftype()
        if typ=='LINE': out.append([(float(e.dxf.start.x),float(e.dxf.start.y)),(float(e.dxf.end.x),float(e.dxf.end.y))])
        elif typ in ('LWPOLYLINE','POLYLINE'):
            if typ=='LWPOLYLINE': p=[(float(x),float(y)) for x,y,*_ in e.get_points()]
            else: p=[(float(v.dxf.location.x),float(v.dxf.location.y)) for v in e.vertices]
            if getattr(e,'closed',False) and p and p[0]!=p[-1]:p.append(p[0])
            if len(p)>=2: out.append(p)
        elif typ in ('CIRCLE','ARC'):
            c=e.dxf.center; r=float(e.dxf.radius)
            a0=0 if typ=='CIRCLE' else math.radians(float(e.dxf.start_angle)); a1=2*math.pi if typ=='CIRCLE' else math.radians(float(e.dxf.end_angle))
            if typ=='ARC' and a1<=a0:a1+=2*math.pi
            n=max(12,int(abs(a1-a0)*r/0.5))
            p=[(float(c.x)+r*math.cos(a0+(a1-a0)*k/n),float(c.y)+r*math.sin(a0+(a1-a0)*k/n)) for k in range(n+1)]
            if typ=='CIRCLE' and p[0]!=p[-1]:p.append(p[0])
            out.append(p)
        elif typ=='SPLINE':
            try:
                pts=[(float(p.x),float(p.y)) for p in e.flattening(0.15)]
                if len(pts)>=2: out.append(pts)
            except Exception: pass
    return out

def _morphological_skeleton(bw):
    import numpy as np
    # Zhang-Suen thinning: preserves a continuous one-pixel centerline instead
    # of returning only local distance-map maxima. Vectorized NumPy keeps this
    # fast enough for the 1200 px centerline working limit.
    img=(bw>0).astype(np.uint8)
    if img.size==0 or not img.any():
        return np.zeros_like(bw)
    img[[0,-1],:]=0
    img[:,[0,-1]]=0

    for _ in range(256):
        changed=False
        for phase in (0,1):
            c=img[1:-1,1:-1]
            p2=img[:-2,1:-1]; p3=img[:-2,2:]; p4=img[1:-1,2:]; p5=img[2:,2:]
            p6=img[2:,1:-1]; p7=img[2:,:-2]; p8=img[1:-1,:-2]; p9=img[:-2,:-2]
            n=p2+p3+p4+p5+p6+p7+p8+p9
            a=((p2==0)&(p3==1)).astype(np.uint8)
            a+=((p3==0)&(p4==1)); a+=((p4==0)&(p5==1)); a+=((p5==0)&(p6==1))
            a+=((p6==0)&(p7==1)); a+=((p7==0)&(p8==1)); a+=((p8==0)&(p9==1)); a+=((p9==0)&(p2==1))
            if phase==0:
                remove=(c==1)&(n>=2)&(n<=6)&(a==1)&((p2*p4*p6)==0)&((p4*p6*p8)==0)
            else:
                remove=(c==1)&(n>=2)&(n<=6)&(a==1)&((p2*p4*p8)==0)&((p2*p6*p8)==0)
            if remove.any():
                c[remove]=0
                changed=True
        if not changed:
            break
    return (img*255).astype(np.uint8)

def _trace_skeleton(skel, min_points=3):
    import numpy as np
    ys,xs=np.where(skel>0); nodes={(int(x),int(y)) for x,y in zip(xs,ys)}
    if not nodes:return []
    nbrs={}
    for n in nodes:
        x,y=n; nbrs[n]=[(x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1) if (dx or dy) and (x+dx,y+dy) in nodes]
    edges=set(); paths=[]
    def ek(a,b):return tuple(sorted((a,b)))
    starts=[n for n in nodes if len(nbrs[n])!=2]
    def walk(start,nxt):
        p=[start,nxt];prev,startcur=start,nxt;edges.add(ek(prev,startcur))
        while True:
            opts=[q for q in nbrs[startcur] if q!=prev and ek(startcur,q) not in edges]
            if len(nbrs[startcur])!=2 or not opts:break
            q=opts[0];edges.add(ek(startcur,q));p.append(q);prev,startcur=startcur,q
        return p
    for st in starts:
        for nb in nbrs[st]:
            if ek(st,nb) not in edges:
                p=walk(st,nb)
                if len(p)>=min_points:paths.append(p)
    for st in nodes:
        rem=[nb for nb in nbrs[st] if ek(st,nb) not in edges]
        if not rem:continue
        p=[st];prev=None;cur=st
        while True:
            opts=[q for q in nbrs[cur] if q!=prev and ek(cur,q) not in edges]
            if not opts:break
            q=opts[0];edges.add(ek(cur,q));p.append(q);prev,cur=cur,q
            if cur==st:break
        if len(p)>=min_points:paths.append(p)
    return paths

def load_raster(filename: str, threshold=128, invert=False, min_area=10, external_only=True, smoothing=1.0, centerline=False) -> List[Path]:
    import cv2, numpy as np
    try:
        data=np.fromfile(filename,dtype=np.uint8)
        raw=cv2.imdecode(data,cv2.IMREAD_UNCHANGED) if data.size else None
    except Exception as exc:
        raise ValueError(f'Не удалось прочитать изображение: {exc}') from exc
    if raw is None:
        raise ValueError('Не удалось декодировать изображение. Проверьте реальный формат файла.')

    # Preserve PNG transparency. AI-generated images often keep RGB pixels
    # under transparent areas black; decoding straight to grayscale turns the
    # transparent background into a giant black object. Composite alpha over
    # white first, then convert to grayscale.
    if raw.ndim==3 and raw.shape[2]==4:
        bgr=raw[:,:,:3].astype(np.float32)
        alpha=raw[:,:,3:4].astype(np.float32)/255.0
        composed=(bgr*alpha+255.0*(1.0-alpha)).clip(0,255).astype(np.uint8)
        img=cv2.cvtColor(composed,cv2.COLOR_BGR2GRAY)
    elif raw.ndim==3 and raw.shape[2]>=3:
        img=cv2.cvtColor(raw[:,:,:3],cv2.COLOR_BGR2GRAY)
    else:
        img=raw

    # Very large photos used to freeze the GUI and could create hundreds of
    # thousands of points. Centerline mode is more expensive, so use a tighter
    # working bound while preserving the physical scale.
    h0,w0=img.shape[:2]
    max_dim=1200 if centerline else 1800
    scale=1.0
    if max(h0,w0)>max_dim:
        scale=max_dim/float(max(h0,w0))
        img=cv2.resize(img,(max(1,int(round(w0*scale))),max(1,int(round(h0*scale)))),interpolation=cv2.INTER_AREA)

    if smoothing>0:
        k=max(1,int(round(smoothing))*2+1)
        if k%2==0:k+=1
        img=cv2.GaussianBlur(img,(k,k),0)

    flag=cv2.THRESH_BINARY_INV if not invert else cv2.THRESH_BINARY
    _,bw=cv2.threshold(img,int(threshold),255,flag)

    if centerline:
        occupancy=cv2.countNonZero(bw)/float(max(1,bw.size))
        # If almost the whole canvas became foreground, the background was
        # almost certainly selected. Flip it automatically instead of trying
        # to skeletonize a full sheet for minutes.
        if occupancy>0.80:
            flipped=cv2.bitwise_not(bw)
            flipped_occupancy=cv2.countNonZero(flipped)/float(max(1,flipped.size))
            if flipped_occupancy<occupancy:
                bw=flipped

    out=[]
    mm_per_px=(25.4/96.0)/scale

    if centerline:
        skel=_morphological_skeleton(bw)
        raw_paths=_trace_skeleton(skel)
        # Hard guard against pathological scans/noise.
        raw_paths=sorted(raw_paths,key=len,reverse=True)[:2500]
        total_points=0
        for raw in raw_paths:
            p=[(x*mm_per_px,y*mm_per_px) for x,y in raw]
            p=simplify_path(p,max(0.05,smoothing*mm_per_px))
            if len(p)>=2:
                out.append(p)
                total_points+=len(p)
                if total_points>=60000:
                    break
        return out

    mode=cv2.RETR_EXTERNAL if external_only else cv2.RETR_TREE
    contours,_=cv2.findContours(bw,mode,cv2.CHAIN_APPROX_TC89_KCOS)
    contours=sorted(contours,key=lambda q:abs(cv2.contourArea(q)),reverse=True)[:2500]
    effective_min_area=max(1.0,float(min_area)*scale*scale)
    total_points=0
    for contour in contours:
        if abs(cv2.contourArea(contour))<effective_min_area:
            continue
        eps=max(0.75,float(smoothing))*0.9
        contour=cv2.approxPolyDP(contour,eps,True)
        p=[(float(q[0][0])*mm_per_px,float(q[0][1])*mm_per_px) for q in contour]
        if len(p)>=3:
            p.append(p[0])
            out.append(p)
            total_points+=len(p)
            if total_points>=60000:
                break
    return out

def remove_duplicate_paths(paths: List[Path], tol=0.02) -> List[Path]:
    seen=set();out=[]
    for p in paths:
        if len(p)<2:continue
        key=tuple((round(x/tol),round(y/tol)) for x,y in p)
        rkey=tuple(reversed(key))
        k=min(key,rkey)
        if k not in seen:seen.add(k);out.append(p)
    return out

def join_close_endpoints(paths: List[Path], tol=0.05) -> List[Path]:
    paths=[list(p) for p in paths if len(p)>=2]
    if len(paths)<2 or tol<=0:
        return paths

    # Closed raster contours do not need endpoint joining. This avoids the old
    # O(n^2) scan when an image contains thousands of islands.
    closed=[p for p in paths if is_closed(p,tol)]
    open_paths=[p for p in paths if not is_closed(p,tol)]
    if len(open_paths)<2:
        return closed+open_paths

    # For modest vector drawings keep the exact greedy behaviour.
    if len(open_paths)<=350:
        changed=True
        while changed:
            changed=False
            for i in range(len(open_paths)):
                if changed:break
                for j in range(i+1,len(open_paths)):
                    a,b=open_paths[i],open_paths[j]
                    variants=[(a[-1],b[0],a+b[1:]),(a[-1],b[-1],a+list(reversed(b[:-1]))),(a[0],b[-1],b+a[1:]),(a[0],b[0],list(reversed(b))+a[1:])]
                    for p1,p2,merged in variants:
                        if dist(p1,p2)<=tol:
                            open_paths[i]=merged;open_paths.pop(j);changed=True;break
                    if changed:break
        return closed+open_paths

    # Large centerline jobs: spatial hash gives near O(n) endpoint matching.
    cell=max(tol,1e-6)
    buckets={}
    alive={i:list(p) for i,p in enumerate(open_paths)}
    def key(pt):return (int(math.floor(pt[0]/cell)),int(math.floor(pt[1]/cell)))
    def add_endpoint(i,side,pt):buckets.setdefault(key(pt),set()).add((i,side))
    def remove_endpoint(i,side,pt):
        k=key(pt);s=buckets.get(k)
        if s:
            s.discard((i,side))
            if not s:buckets.pop(k,None)
    for i,p in alive.items():
        add_endpoint(i,0,p[0]);add_endpoint(i,1,p[-1])

    def nearest(pt,exclude):
        kx,ky=key(pt);best=None
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for j,side in buckets.get((kx+dx,ky+dy),()):
                    if j==exclude or j not in alive:continue
                    q=alive[j][0] if side==0 else alive[j][-1]
                    d=dist(pt,q)
                    if d<=tol and (best is None or d<best[0]):best=(d,j,side)
        return best

    for i in list(alive):
        if i not in alive:continue
        while True:
            p=alive[i]
            hit=nearest(p[-1],i)
            if hit is None:break
            _,j,side=hit;q=alive[j]
            remove_endpoint(i,0,p[0]);remove_endpoint(i,1,p[-1]);remove_endpoint(j,0,q[0]);remove_endpoint(j,1,q[-1])
            if side==1:q=list(reversed(q))
            alive[i]=p+q[1:]
            del alive[j]
            add_endpoint(i,0,alive[i][0]);add_endpoint(i,1,alive[i][-1])
    return closed+list(alive.values())

def simplify_path(path: Path, tolerance=0.03) -> Path:
    if len(path)<=2:return path
    try:
        from shapely.geometry import LineString
        g=LineString(path).simplify(tolerance,preserve_topology=True)
        return [(float(x),float(y)) for x,y in g.coords]
    except Exception:return path


def hatch_fill_paths(paths: List[Path], spacing: float=1.0, angle_deg: float=45.0, inset: float=0.0, crosshatch: bool=False) -> List[Path]:
    """Generate pen hatch lines inside closed contours using an even/odd fill rule."""
    spacing=max(0.1,float(spacing))
    try:
        from shapely.geometry import Polygon, LineString, GeometryCollection, LineString as SLineString
        from shapely.affinity import rotate as shp_rotate
    except Exception as exc:
        raise ValueError(f'Заливка требует Shapely: {exc}') from exc

    polygons=[]
    for path in paths:
        if len(path)<4 or not is_closed(path,0.05):
            continue
        try:
            poly=Polygon(path)
            if not poly.is_valid:
                poly=poly.buffer(0)
            if not poly.is_empty and poly.area>1e-4:
                if poly.geom_type=='Polygon': polygons.append(poly)
                elif poly.geom_type=='MultiPolygon': polygons.extend(list(poly.geoms))
        except Exception:
            continue
    if not polygons:
        return []

    geom=GeometryCollection()
    for poly in sorted(polygons,key=lambda g:g.area,reverse=True):
        geom=geom.symmetric_difference(poly)
    if inset>0 and not geom.is_empty:
        shrunk=geom.buffer(-float(inset),join_style=2)
        if not shrunk.is_empty:
            geom=shrunk
    if geom.is_empty:
        return []

    def lines_for_angle(angle):
        cx,cy=geom.centroid.x,geom.centroid.y
        rotation_origin=(float(cx),float(cy))
        rotated=shp_rotate(geom,-float(angle),origin=rotation_origin,use_radians=False)
        minx,miny,maxx,maxy=rotated.bounds
        pad=max(spacing*2.0,1.0)
        y=miny+spacing*0.5
        out=[];reverse=False
        while y<=maxy+1e-9:
            cut=rotated.intersection(LineString([(minx-pad,y),(maxx+pad,y)]))
            segs=[]
            if cut.is_empty:
                y+=spacing;continue
            if cut.geom_type=='LineString':
                segs=[cut]
            elif cut.geom_type=='MultiLineString':
                segs=list(cut.geoms)
            elif hasattr(cut,'geoms'):
                segs=[g for g in cut.geoms if g.geom_type=='LineString']
            segs.sort(key=lambda g:g.bounds[0])
            if reverse:
                segs=list(reversed(segs))
            for seg in segs:
                coords=list(seg.coords)
                if len(coords)<2:continue
                if reverse: coords=list(reversed(coords))
                back=shp_rotate(SLineString(coords),float(angle),origin=rotation_origin,use_radians=False)
                pts=[(float(x),float(y0)) for x,y0 in back.coords]
                if len(pts)>=2:out.append(pts)
                reverse=not reverse
            y+=spacing
        return out

    result=lines_for_angle(angle_deg)
    if crosshatch:
        result.extend(lines_for_angle(float(angle_deg)+90.0))
    return result

def optimize_order(paths: List[Path]) -> List[Path]:
    if not paths:return []
    closed=[p for p in paths if is_closed(p)]
    openp=[p for p in paths if not is_closed(p)]
    def area(p):
        return abs(sum(p[i][0]*p[i+1][1]-p[i+1][0]*p[i][1] for i in range(len(p)-1))/2)
    # Small enclosed contours before large outer contours.
    closed.sort(key=area)
    ordered=closed[:]
    cur=ordered[-1][-1] if ordered else (0.0,0.0)

    # Exact greedy nearest-neighbour is O(n^2); keep it only where cheap.
    if len(openp)<=500:
        remaining=openp[:]
        while remaining:
            best=None
            for idx,p in enumerate(remaining):
                d1=dist(cur,p[0]);d2=dist(cur,p[-1])
                cand=(min(d1,d2),idx,d2<d1)
                if best is None or cand<best:best=cand
            _,idx,rev=best
            p=remaining.pop(idx)
            p=list(reversed(p)) if rev else p
            ordered.append(p);cur=p[-1]
        return ordered

    # Large centerline sets: deterministic sweep order, then orient each path
    # toward the current tool position. Complexity O(n log n).
    openp.sort(key=lambda p:(min(p[0][1],p[-1][1]),min(p[0][0],p[-1][0])))
    for p in openp:
        if dist(cur,p[-1])<dist(cur,p[0]):p=list(reversed(p))
        ordered.append(p);cur=p[-1]
    return ordered

def _unit(a,b):
    d=dist(a,b)
    return (0,0) if d<EPS else ((b[0]-a[0])/d,(b[1]-a[1])/d)

def _arc(center:Point, a1:float, a2:float, radius:float, ccw:bool, step_deg=10):
    if ccw:
        while a2<a1:a2+=2*math.pi
        span=a2-a1
    else:
        while a2>a1:a2-=2*math.pi
        span=a2-a1
    n=max(1,int(abs(math.degrees(span))/step_deg))
    return [(center[0]+radius*math.cos(a1+span*k/n),center[1]+radius*math.sin(a1+span*k/n)) for k in range(1,n+1)]

def compensate_dragknife(path: Path, offset: float, overcut: float=0.0) -> Path:
    if offset<=0 or len(path)<2:return list(path)
    closed=is_closed(path)
    core=path[:-1] if closed else path
    if len(core)<2:return list(path)
    out=[]
    segdirs=[_unit(core[i], core[(i+1)%len(core)]) for i in range(len(core) if closed else len(core)-1)]
    first=core[0]; u0=segdirs[0]
    out.append((first[0]+offset*u0[0],first[1]+offset*u0[1]))
    nverts=len(core)
    last_vertex=nverts if closed else nverts-1
    for i in range(1,last_vertex):
        p=core[i%nverts]; up=segdirs[(i-1)%len(segdirs)]; un=segdirs[i%len(segdirs)]
        pin=(p[0]+offset*up[0],p[1]+offset*up[1]); out.append(pin)
        cross=up[0]*un[1]-up[1]*un[0]
        a1=math.atan2(up[1],up[0]);a2=math.atan2(un[1],un[0])
        out.extend(_arc(p,a1,a2,offset,ccw=cross>=0))
    if closed:
        p=core[0]; up=segdirs[-1]; un=segdirs[0]
        pin=(p[0]+offset*up[0],p[1]+offset*up[1]);out.append(pin)
        cross=up[0]*un[1]-up[1]*un[0]
        out.extend(_arc(p,math.atan2(up[1],up[0]),math.atan2(un[1],un[0]),offset,cross>=0)); out.append(out[0])
        if overcut>0 and len(out)>1:
            u=_unit(out[0],out[1]);out.append((out[0][0]+u[0]*overcut,out[0][1]+u[1]*overcut))
    else:
        p=core[-1];u=segdirs[-1];end=(p[0]+offset*u[0],p[1]+offset*u[1]);out.append(end)
        if overcut>0:out.append((end[0]+u[0]*overcut,end[1]+u[1]*overcut))
    return out
