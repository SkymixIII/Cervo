#!/usr/bin/env python3
"""PoC: de-chunk Sony .rsv recovery container -> H.264 Annex-B access units."""
import struct, sys

SONY=bytes.fromhex("060e2b34025301010c0201")  # Sony private KLV key prefix (11B)

def ber(buf,off):
    b0=buf[off]
    if b0<0x80: return b0,1
    n=b0&0x7f
    return int.from_bytes(buf[off+1:off+1+n],"big"),1+n

def dechunk(buf, limit):
    """Remove Sony KLV metadata clusters, return contiguous essence bytes."""
    out=bytearray(); pos=0
    while pos<limit and pos<len(buf):
        if buf[pos:pos+11]==SONY:
            ln,hl=ber(buf,pos+16)
            pos+=16+hl+ln
        else:
            nxt=buf.find(SONY,pos)
            if nxt<0 or nxt>limit: nxt=min(limit,len(buf))
            out+=buf[pos:nxt]
            pos=nxt
    return bytes(out)

NAME={1:"nonIDR",5:"IDR",6:"SEI",7:"SPS",8:"PPS",9:"AUD",10:"EOS",12:"FILL"}

def scan_all_records(ess):
    """Scan for every self-validating Sony NAL record:
       [u32 len][00][u32 len+4][02 01][nal header]. Returns list of (offset,type,payload)."""
    recs=[]; i=0; N=len(ess)
    while i+11<N:
        j=ess.find(b"\x02\x01",i)
        if j<0: break
        rs=j-9
        if rs<0: i=j+2; continue
        nal_len=struct.unpack(">I",ess[rs:rs+4])[0]
        if ess[rs+4]==0 and nal_len>0 and nal_len<=5_000_000:
            chk=struct.unpack(">I",ess[rs+5:rs+9])[0]
            if chk==nal_len+4:
                p=j+2
                if p+nal_len<=N:
                    hdr=ess[p]
                    t=hdr&0x1f
                    if (hdr&0x80)==0 and t in (1,5,6,7,8,9,10,12):
                        recs.append((rs,t,ess[p:p+nal_len]))
                        i=p+nal_len
                        continue
        i=j+2
    return recs

if __name__=="__main__":
    buf=open("/private/tmp/mxf_spike/head.bin","rb").read()
    LIMIT=int(sys.argv[1]) if len(sys.argv)>1 else 30_000_000
    ess=dechunk(buf,LIMIT)
    print(f"de-chunked essence: {len(ess)} bytes (from first {LIMIT} of head.bin)")
    recs=scan_all_records(ess)
    print(f"scanned {len(recs)} valid Sony NAL records")
    nals=[(t,p) for _,t,p in recs]
    # report first access units (split on AUD)
    aus=[]; cur=[]
    for t,p in nals:
        if t==9 and cur: aus.append(cur); cur=[]
        cur.append((t,p))
    if cur: aus.append(cur)
    for ai,au in enumerate(aus[:3]):
        comp={}
        for t,p in au: comp[NAME.get(t,t)]=comp.get(NAME.get(t,t),0)+1
        tot=sum(len(p) for _,p in au)
        print(f"  AU{ai+1}: {comp}  total={tot} bytes")
    # Emit annex-B for FIRST access unit only
    au1=aus[0]
    with open("/private/tmp/mxf_spike/rsv_au1.h264","wb") as f:
        for t,p in au1:
            f.write(b"\x00\x00\x00\x01"); f.write(p)
    print(f"wrote rsv_au1.h264 ({sum(len(p) for _,p in au1)+4*len(au1)} bytes, {len(au1)} NALs)")
