#!/usr/bin/env python3
"""Extend PoC: carve a SEQUENCE of frames from .rsv -> annex-B -> MP4."""
import struct, re, sys
exec(open("/private/tmp/mxf_spike/carve.py").read().split("if __name__")[0])  # dechunk()

LIMIT=int(sys.argv[1]) if len(sys.argv)>1 else 300_000_000

# reference parameter sets (byte-identical to rsv encoder)
ref=open("/private/tmp/mxf_spike/ref3.h264","rb").read()
starts=[m.start() for m in re.finditer(b"\x00\x00\x01",ref)]
rn=[]
for i,s in enumerate(starts):
    p=s+3; e=starts[i+1] if i+1<len(starts) else len(ref)
    pl=ref[p:e]
    while pl and pl[-1]==0: pl=pl[:-1]
    rn.append((pl[0]&0x1f,pl))
sps=[p for t,p in rn if t==7][:1]
pps=[p for t,p in rn if t==8][:5]

buf=open("/private/tmp/mxf_spike/head.bin","rb").read()
ess=dechunk(buf,LIMIT)
print(f"de-chunked essence {len(ess)} bytes")

def walk_frame(ess,pos):
    """walk one frame's avcC chain from an AUD; stop at next AUD. returns (nals,endpos) or (None,_)."""
    nals=[]; slices=0
    # first NAL must be AUD
    L=struct.unpack(">I",ess[pos:pos+4])[0]
    if not (L==2 and (ess[pos+4]&0x1f)==9): return None,pos+4
    while pos+4<=len(ess):
        L=struct.unpack(">I",ess[pos:pos+4])[0]
        if not (1<=L<=5_000_000): break
        nal=ess[pos+4:pos+4+L]
        if len(nal)<L: break
        t=nal[0]&0x1f
        if (nal[0]&0x80)!=0 or t not in (1,5,6,9,12): break
        if t==9 and nals: break     # next frame's AUD
        nals.append((t,nal)); pos=pos+4+L
        if t in (1,5): slices+=1
    if slices==0: return None,pos
    return nals,pos

# collect frames: scan AUD anchors, walk each
frames=[]; pos=ess.find(b"\x00\x00\x00\x02\x09"); MAXF=int(sys.argv[2]) if len(sys.argv)>2 else 200
while pos>=0 and len(frames)<MAXF:
    nals,endp=walk_frame(ess,pos)
    if nals:
        frames.append(nals)
        pos=ess.find(b"\x00\x00\x00\x02\x09",endp)
    else:
        pos=ess.find(b"\x00\x00\x00\x02\x09",pos+1)
print(f"carved {len(frames)} frames")
from collections import Counter
kinds=Counter()
for fr in frames:
    has_idr=any(t==5 for t,_ in fr)
    kinds["IDR" if has_idr else "I-nonIDR"]+=1
print("frame kinds:", dict(kinds), " slice counts:", [sum(1 for t,_ in fr if t in (1,5)) for fr in frames[:8]],"...")

def sc(n): return b"\x00\x00\x00\x01"+n
out=bytearray()
for fi,fr in enumerate(frames):
    for a in [n for t,n in fr if t==9][:1]: out+=sc(a)
    if fi==0:
        for s in sps: out+=sc(s)
        for p in pps: out+=sc(p)
    for t,n in fr:
        if t in (6,5,1): out+=sc(n)
open("/private/tmp/mxf_spike/rsv_seq.h264","wb").write(out)
print(f"wrote rsv_seq.h264 {len(out)} bytes ({len(frames)} frames)")
