#!/usr/bin/env python3
"""Boot tests for IFelxBoot in a virtual machine (QEMU/KVM, OVMF).

Each case starts a UEFI machine and looks at what came up:
  installed   the disk alone                        -> the installed system (login screen)
  live-cd     IFelxOS2.iso as a CD + the disk        -> the live system (desktop, no login)
  live-usb    IFelxOS2.iso as a USB stick + the disk -> the live system
  ode-cd      ODE_installer.iso as a CD + the disk   -> the ODE installer window
  ode-usb     ODE_installer.iso as a USB stick + ... -> the ODE installer window
The disk must hold an installed IFelxOS2 (an e2e test leaves one). The live
and installer cases are the reason for the search order: with an installed
system on the disk, the medium must still start itself.

  sudo python3 IFelxBoot/tests/boot-test.py --disk installed.img --live IFelxOS2.iso
                [--ode ODE_installer.iso] [--efi IFelxBoot/out/BOOTX64.EFI] [--screens DIR]

--efi first copies that loader onto the disk's EFI partition, so the installed
case runs the build under test. Screens go to IFelxBoot/tests/screens/.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
os.environ.setdefault("IFX_VM", "/root/ifelxboot/vm")
sys.path.insert(0, os.path.join(PROJECT, "build"))
import vm  # noqa: E402  (QMP driver: screenshots and input)

VMDIR = os.environ["IFX_VM"]
SCREENS = os.path.join(HERE, "screens")


def screen():
    """the current screen as a pixel reader, or None while it is not 1280x800
    (the firmware's and the kernel's early screens are smaller)"""
    tmp = os.path.join(VMDIR, "probe.ppm")
    vm.qmp("screendump", {"filename": tmp})
    time.sleep(0.3)
    data = open(tmp, "rb").read()
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    pix = parts[3]
    if (w, h) != (vm.W, vm.H) or len(pix) < w * h * 3:
        return None
    return lambda x, y: tuple(pix[(y * w + x) * 3:(y * w + x) * 3 + 3])


def near(a, b, tol=4):
    return len(a) == len(b) and all(abs(p - q) <= tol for p, q in zip(a, b))


def classify():
    """the screen at 1280x800: IFelxUi's login card, its panel, or ODE's window"""
    px = screen()
    if px is None:
        return "unknown"
    if px(560, 672) == (0, 0, 139):
        return "ode"
    if near(px(640, 600), (26, 26, 26)) and px(668, 473)[2] > px(668, 473)[0] + 30:
        return "login"
    if near(px(300, 743), (27, 27, 27)):
        return "desktop"
    return "unknown"


def stop():
    try:
        vm.qmp("quit")
    except BaseException:
        pass
    time.sleep(3)


def start(disk, iso=None, usb=False):
    argv = ["python3", os.path.join(PROJECT, "build", "vm.py"), "start", "--disk", disk]
    if iso:
        argv += ["--iso", iso] + (["--usb"] if usb else [])
    else:
        argv += ["--no-cd"]
    subprocess.check_call(argv, stdout=subprocess.DEVNULL)


def wait_for(expected, timeout=120):
    end = time.time() + timeout
    seen = "unknown"
    while time.time() < end:
        time.sleep(4)
        try:
            seen = classify()
        except Exception:
            continue
        # the live session may show its login briefly before it signs in
        if seen == expected or (seen != "unknown" and expected != "desktop"):
            break
    return seen


def put_loader(disk, efi):
    loop = subprocess.check_output(["losetup", "-f", "--show", "-P", disk], text=True).strip()
    mnt = os.path.join(VMDIR, "esp")
    os.makedirs(mnt, exist_ok=True)
    try:
        esp = None
        for name in sorted(os.listdir("/sys/class/block")):
            if not name.startswith(os.path.basename(loop) + "p"):
                continue
            t = subprocess.run(["blkid", "-p", "-o", "value", "-s", "PART_ENTRY_TYPE", "/dev/" + name],
                               capture_output=True, text=True).stdout.strip().lower()
            if t in ("0xef", "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"):
                esp = "/dev/" + name
                break
        if not esp:
            raise SystemExit("no EFI partition on " + disk)
        subprocess.check_call(["mount", esp, mnt])
        for rel in ("EFI/BOOT/BOOTX64.EFI", "EFI/IFelxOS2/BOOTX64.EFI"):
            if os.path.exists(os.path.join(mnt, rel)):
                shutil.copy(efi, os.path.join(mnt, rel))
                print("   loader under test copied to", rel)
        subprocess.check_call(["umount", mnt])
    finally:
        subprocess.call(["losetup", "-d", loop])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--disk", required=True)
    p.add_argument("--live", required=True)
    p.add_argument("--ode")
    p.add_argument("--efi")
    p.add_argument("--screens", default=SCREENS)
    a = p.parse_args()
    os.makedirs(VMDIR, exist_ok=True)
    os.makedirs(a.screens, exist_ok=True)
    stop()
    disk = os.path.join(VMDIR, "disk.img")
    subprocess.check_call(["cp", "--sparse=always", a.disk, disk])
    vars_fd = os.path.join(VMDIR, "vars.fd")
    if os.path.exists(vars_fd):
        os.unlink(vars_fd)
    if a.efi:
        put_loader(disk, a.efi)

    cases = [("installed", None, False, "login"),
             ("live-cd", a.live, False, "desktop"),
             ("live-usb", a.live, True, "desktop")]
    if a.ode:
        cases += [("ode-cd", a.ode, False, "ode"), ("ode-usb", a.ode, True, "ode")]
    failed = 0
    for name, iso, usb, expected in cases:
        start(disk, iso, usb)
        seen = wait_for(expected)
        tmp = os.path.join(VMDIR, "shot.ppm")
        vm.qmp("screendump", {"filename": tmp})
        time.sleep(0.3)
        vm.ppm_to_png(tmp, os.path.join(a.screens, name + ".png"))
        ok = seen == expected
        failed += not ok
        print("%-10s expected %-8s saw %-8s %s" % (name, expected, seen, "ok" if ok else "FAIL"), flush=True)
        stop()
    os.unlink(disk)
    print("all passed" if not failed else "%d failed" % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
