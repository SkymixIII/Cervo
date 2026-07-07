#!/usr/bin/env python3
"""Assemble frame-1 access unit from .rsv: reference SPS/PPS + rsv SEI+slices (avcC framed)."""
import struct, re, sys
exec(open("/private/tmp/mxf_spike/carve.py").read().split("if __name__")[0])  # dechunk()

# --- 1) reference parameter sets (SPS + all PPS) from ref3.h264 (byte-identical to rsv encoder) ---
ref=open("/private/tmp/mxf_spike/ref3.h264","rb").read()
starts=[m.start() for m in re.finditer(b"\x00\x00\x01",ref)]
ref_nals=[]
for i,s in enumerate(starts):
    p=s+3; e=starts[i+1] if i+1<len(starts) else len(ref)
    pl=ref[p:e]
    while pl and pl[-1]==0: pl=pl[:-1]
    ref_nals.append((pl[0]&0x1f,pl))
sps=[p for t,p in ref_nals if t==7][:1]
pps=[p for t,p in ref_nals if t==8][:5]
aud=[p for t,p in ref_nals if t==9][:1]
print(f"reference: SPS={len(sps)} PPS={len(pps)} sizes={[len(x) for x in pps]}")

# --- 2) rsv essence: avcC 4-byte length-prefixed NAL chain (SEI + 8 IDR slices of frame 1) ---
buf=open("/private/tmp/mxf_spike/head.bin","rb").read()
ess=dechunk(buf,30_000_000)

def avcc_walk(ess,pos,stop_after_slices=8):
    """walk avcC [u32 len][nal] chain; collect until N IDR slices captured then stop at next AUD."""
    out=[]; idr=0
    while pos+4<=len(ess):
        L=struct.unpack(">I",ess[pos:pos+4])[0]
        if not (1<=L<=5_000_000): break
        nal=ess[pos+4:pos+4+L]
        if len(nal)<L: break
        t=nal[0]&0x1f
        if (nal[0]&0x80)!=0 or t not in (1,5,6,9,12): break
        if t==9 and idr>=stop_after_slices: break   # next frame
        out.append((t,nal)); pos=pos+4+L
        if t==5: idr+=1
        if idr>=stop_after_slices and t==5:
            # peek: continue only if next is another slice
            if pos+4<=len(ess):
                L2=struct.unpack(">I",ess[pos:pos+4])[0]
                if pos+4<len(ess) and 1<=L2<=5_000_000 and (ess[pos+4]&0x1f)==5:
                    continue
            break
    return out,pos

# find frame-1 AUD in avcC framing: 00 00 00 02 09
anchor=ess.find(b"\x00\x00\x00\x02\x09")
print(f"avcC AUD anchor @0x{anchor:x}")
nals,endp=avcc_walk(ess,anchor)
from collections import Counter
c=Counter(t for t,_ in nals)
name={1:"nonIDR",5:"IDR",6:"SEI",9:"AUD",12:"FILL"}
print("rsv frame-1 NALs:", {name.get(k,k):v for k,v in c.items()},
      " slice sizes:", [len(p) for t,p in nals if t==5])

# --- 3) assemble annex-B: AUD, SPS, PPS*5, then rsv SEI+slices ---
def sc(nal): return b"\x00\x00\x00\x01"+nal
out=bytearray()
for a in aud: out+=sc(a)
for s in sps: out+=sc(s)
for p in pps: out+=sc(p)
for t,nal in nals:
    if t in (6,5,1): out+=sc(nal)   # SEI + slices (skip rsv's own AUD)
open("/private/tmp/mxf_spike/rsv_frame1.h264","wb").write(out)
print(f"wrote rsv_frame1.h264: {len(out)} bytes")
