#!/usr/bin/env python3
"""logo.png -> logo.h

The loader shows the picture itself: the PNG is decoded here, at build time,
and written out as the raw BGRA pixels UEFI blits, so the boot logo and the
desktop logo are the same image rather than two drawings of it.
"""
import sys, zlib, struct

def decode_png(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n', 'not a png'
    pos, idat, pal, trns = 8, b'', None, None
    w = h = depth = ctype = 0
    while pos < len(d):
        ln = struct.unpack('>I', d[pos:pos+4])[0]
        typ = d[pos+4:pos+8]
        data = d[pos+8:pos+8+ln]
        if typ == b'IHDR':
            w, h, depth, ctype, comp, filt, inter = struct.unpack('>IIBBBBB', data)
            assert depth == 8 and inter == 0, 'need 8-bit non-interlaced png'
        elif typ == b'PLTE': pal = data
        elif typ == b'tRNS': trns = data
        elif typ == b'IDAT': idat += data
        elif typ == b'IEND': break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if f == 1:
            for i in range(ch, stride): line[i] = (line[i] + line[i-ch]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i-ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i-ch] if i >= ch else 0
                b = prev[i]
                c = prev[i-ch] if i >= ch else 0
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[y*stride:(y+1)*stride] = line
        prev = line
    px = []
    for y in range(h):
        row = []
        for x in range(w):
            i = y*stride + x*ch
            if ctype == 6: r, g, b, a = out[i], out[i+1], out[i+2], out[i+3]
            elif ctype == 2: r, g, b, a = out[i], out[i+1], out[i+2], 255
            elif ctype == 0: r = g = b = out[i]; a = 255
            elif ctype == 4: r = g = b = out[i]; a = out[i+1]
            else:
                idx = out[i]
                r, g, b = pal[idx*3], pal[idx*3+1], pal[idx*3+2]
                a = trns[idx] if trns and idx < len(trns) else 255
            row.append((r, g, b, a))
        px.append(row)
    return w, h, px

def box_scale(w, h, px, tw, th):
    out = []
    for ty in range(th):
        row = []
        y0, y1 = ty*h//th, max(ty*h//th + 1, (ty+1)*h//th)
        for tx in range(tw):
            x0, x1 = tx*w//tw, max(tx*w//tw + 1, (tx+1)*w//tw)
            r = g = b = a = n = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pr, pg, pb, pa = px[y][x]
                    r += pr; g += pg; b += pb; a += pa; n += 1
            row.append((r//n, g//n, b//n, a//n))
        out.append(row)
    return tw, th, out

def main():
    src, dst = sys.argv[1], sys.argv[2]
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    w, h, px = decode_png(src)
    if max(w, h) != target:
        s = target / max(w, h)
        w, h, px = box_scale(w, h, px, max(1, round(w*s)), max(1, round(h*s)))
    # the ground the loader paints, so the logo's own transparency is flattened
    # onto it instead of showing whatever the firmware left behind
    bg = (0x09, 0x09, 0x09)
    body = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[y][x]
            r = (r*a + bg[0]*(255-a)) // 255
            g = (g*a + bg[1]*(255-a)) // 255
            b = (b*a + bg[2]*(255-a)) // 255
            body.append('0x%02x,0x%02x,0x%02x,0x00' % (b, g, r))
    with open(dst, 'w') as f:
        f.write('/* generated from %s by mklogo.py - do not edit */\n' % src)
        f.write('#define LOGO_W %d\n#define LOGO_H %d\n' % (w, h))
        f.write('static const unsigned char logo_bgra[] = {\n')
        for i in range(0, len(body), 8):
            f.write('    ' + ','.join(body[i:i+8]) + ',\n')
        f.write('};\n')
    print('%s: %dx%d' % (dst, w, h))

main()
