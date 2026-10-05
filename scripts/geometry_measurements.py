"""Mesh section and ray measurements shared by current verification tools."""

import numpy as np
import trimesh


def section_segments(mesh,z):
    return trimesh.intersections.mesh_plane(mesh,[0,0,1],[0,0,z])[:,:,:2]


def segment_distance(point,segments):
    a=segments[:,0];delta=segments[:,1]-a
    length=(delta*delta).sum(axis=1)
    t=np.clip(((point-a)*delta).sum(axis=1)/np.maximum(length,1e-20),0,1)
    return np.linalg.norm(a+t[:,None]*delta-point,axis=1)


def vertical_hits(mesh,xy):
    t=mesh.triangles;q=np.array(xy)
    v0=t[:,1,:2]-t[:,0,:2];v1=t[:,2,:2]-t[:,0,:2];v2=q-t[:,0,:2]
    den=v0[:,0]*v1[:,1]-v0[:,1]*v1[:,0];ok=abs(den)>1e-9
    a=np.divide(v2[:,0]*v1[:,1]-v2[:,1]*v1[:,0],den,out=np.zeros_like(den),where=ok)
    b=np.divide(v0[:,0]*v2[:,1]-v0[:,1]*v2[:,0],den,out=np.zeros_like(den),where=ok)
    hit=ok&(a>=-1e-8)&(b>=-1e-8)&(a+b<=1+1e-8)
    z=t[:,0,2]+a*(t[:,1,2]-t[:,0,2])+b*(t[:,2,2]-t[:,0,2])
    return sorted(set(np.round(z[hit],4)))
