#!/usr/bin/env python3
"""Drives an IFelxOS2 virtual machine for end-to-end tests.

A QEMU machine (KVM, UEFI or BIOS, 1280x800 screen, USB tablet and keyboard)
is started in the background and controlled through QMP: screenshots, clicks
at screen coordinates, typing, key combinations. Each call is one step, so a
test can look at the screen between steps.

  vm.py start  --iso X.iso --disk disk.img [--bios] [--no-cd] [--disk-size 8G]
               [--gpu vga|virtio]   (virtio-gpu has a hardware cursor plane)
  vm.py shot   out.png
  vm.py click  X Y [--right]
  vm.py drag   X1 Y1 X2 Y2 [STEPS]  (left button held, moved in steps)
  vm.py scroll X Y N                (wheel, N notches; negative scrolls up)
  vm.py type   "text"
  vm.py key    ctrl-alt-f1        (qcodes joined by '-')
  vm.py wait   SECONDS
  vm.py stop
"""
import json, os, socket, struct, subprocess, sys, time, zlib

VM = os.environ.get("IFX_VM", "/root/ifx/vm")
QMP = os.path.join(VM, "qmp.sock")
W, H = 1280, 800


def qmp(cmd, args=None):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(QMP)
    f = s.makefile("rw")
    json.loads(f.readline())                      # greeting
    f.write(json.dumps({"execute": "qmp_capabilities"}) + "\n"); f.flush()
    json.loads(f.readline())
    msg = {"execute": cmd}
    if args is not None:
        msg["arguments"] = args
    f.write(json.dumps(msg) + "\n"); f.flush()
    while True:
        r = json.loads(f.readline())
        if "return" in r or "error" in r:
            s.close()
            if "error" in r:
                raise SystemExit("qmp %s: %s" % (cmd, r["error"]))
            return r["return"]


def ppm_to_png(ppm, png):
    data = open(ppm, "rb").read()
    # P6\n<w> <h>\n<max>\n<rgb...>
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    pix = parts[3]
    raw = b"".join(b"\x00" + pix[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    open(png, "wb").write(out)


def abs_move(x, y):
    qmp("input-send-event", {"events": [
        {"type": "abs", "data": {"axis": "x", "value": int(x * 32767 / (W - 1))}},
        {"type": "abs", "data": {"axis": "y", "value": int(y * 32767 / (H - 1))}}]})


def button(name, down):
    qmp("input-send-event", {"events": [{"type": "btn", "data": {"down": down, "button": name}}]})


def keys(codes, down):
    qmp("input-send-event", {"events": [
        {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": c}}} for c in codes]})


SHIFTED = {'!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8',
           '(': '9', ')': '0', '_': 'minus', '+': 'equal', ':': 'semicolon', '"': 'apostrophe',
           '<': 'comma', '>': 'dot', '?': 'slash', '|': 'backslash', '~': 'grave_accent'}
PLAIN = {' ': 'spc', '-': 'minus', '=': 'equal', ';': 'semicolon', "'": 'apostrophe', ',': 'comma',
         '.': 'dot', '/': 'slash', '\\': 'backslash', '`': 'grave_accent', '\n': 'ret', '\t': 'tab'}


def type_text(text):
    for ch in text:
        if ch.isalpha() and ch.isupper():
            seq = ["shift", ch.lower()]
        elif ch.isalnum():
            seq = [ch]
        elif ch in SHIFTED:
            seq = ["shift", SHIFTED[ch]]
        elif ch in PLAIN:
            seq = [PLAIN[ch]]
        else:
            continue
        keys(seq, True)
        time.sleep(0.03)
        keys(list(reversed(seq)), False)
        time.sleep(0.05)


def start(argv):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--iso")
    p.add_argument("--disk", required=True)
    p.add_argument("--disk-size", default="8G")
    p.add_argument("--bios", action="store_true")
    p.add_argument("--no-cd", action="store_true")
    p.add_argument("--audio", action="store_true", help="add an HDA sound card")
    p.add_argument("--usb", action="store_true",
                   help="attach the ISO as a USB stick (as written with dd/Rufus DD mode) instead of a CD")
    p.add_argument("--gpu", choices=["vga", "virtio"], default="vga",
                   help="std VGA (bochs-drm, no cursor plane) or virtio-gpu (cursor plane)")
    a = p.parse_args(argv)
    gpu = ("VGA,edid=on,xres=%d,yres=%d" if a.gpu == "vga"
           else "virtio-vga,edid=on,xres=%d,yres=%d") % (W, H)
    os.makedirs(VM, exist_ok=True)
    if not os.path.exists(a.disk):
        subprocess.check_call(["truncate", "-s", a.disk_size, a.disk])
    cmd = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-smp", "2",
           "-m", "3072", "-device", gpu,
           "-device", "qemu-xhci", "-device", "usb-tablet", "-device", "usb-kbd",
           "-drive", "file=%s,format=raw,if=none,id=hd0" % a.disk,
           "-device", "virtio-blk-pci,drive=hd0,bootindex=1",
           "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
           "-display", "none", "-qmp", "unix:%s,server=on,wait=off" % QMP,
           "-serial", "file:%s/serial.log" % VM]
    if a.audio:
        cmd += ["-audiodev", "none,id=snd0", "-device", "intel-hda",
                "-device", "hda-duplex,audiodev=snd0"]
    if not a.bios:
        vars_fd = os.path.join(VM, "vars.fd")
        if not os.path.exists(vars_fd):
            subprocess.check_call(["cp", "/usr/share/OVMF/OVMF_VARS_4M.fd", vars_fd])
        cmd += ["-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
                "-drive", "if=pflash,format=raw,file=%s" % vars_fd]
    if a.iso and not a.no_cd and a.usb:
        cmd += ["-drive", "file=%s,format=raw,readonly=on,if=none,id=stick" % a.iso,
                "-device", "usb-storage,drive=stick,bootindex=0"]
    elif a.iso and not a.no_cd:
        cmd += ["-drive", "file=%s,media=cdrom,readonly=on,if=none,id=cd0" % a.iso,
                "-device", "ide-cd,drive=cd0,bootindex=0"]
    if os.path.exists(QMP):
        os.unlink(QMP)
    log = open(os.path.join(VM, "qemu.log"), "w")
    pr = subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
    open(os.path.join(VM, "qemu.pid"), "w").write(str(pr.pid))
    for _ in range(50):
        if os.path.exists(QMP):
            break
        time.sleep(0.1)
    print("started pid %d (%s)" % (pr.pid, "BIOS" if a.bios else "UEFI"))


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    c, rest = sys.argv[1], sys.argv[2:]
    if c == "start":
        start(rest)
    elif c == "shot":
        tmp = os.path.join(VM, "shot.ppm")
        qmp("screendump", {"filename": tmp})
        time.sleep(0.3)
        ppm_to_png(tmp, rest[0])
        print("shot", rest[0])
    elif c == "click":
        x, y = float(rest[0]), float(rest[1])
        b = "right" if "--right" in rest else "left"
        abs_move(x, y); time.sleep(0.15)
        button(b, True); time.sleep(0.08); button(b, False); time.sleep(0.1)
    elif c == "drag":
        x1, y1, x2, y2 = map(float, rest[:4])
        steps = int(rest[4]) if len(rest) > 4 else 20
        abs_move(x1, y1); time.sleep(0.15)
        button("left", True); time.sleep(0.1)
        for i in range(1, steps + 1):
            abs_move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
            time.sleep(0.016)
        time.sleep(0.1); button("left", False); time.sleep(0.1)
    elif c == "scroll":
        abs_move(float(rest[0]), float(rest[1])); time.sleep(0.1)
        n = int(rest[2])
        b = "wheel-down" if n > 0 else "wheel-up"
        for _ in range(abs(n)):
            button(b, True); time.sleep(0.03); button(b, False); time.sleep(0.05)
    elif c == "move":
        abs_move(float(rest[0]), float(rest[1]))
    elif c == "type":
        type_text(rest[0])
    elif c == "key":
        codes = rest[0].split("-")
        keys(codes, True); time.sleep(0.1); keys(list(reversed(codes)), False)
    elif c == "wait":
        time.sleep(float(rest[0]))
    elif c == "stop":
        try:
            qmp("quit")
        except Exception:
            pass
        print("stopped")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
