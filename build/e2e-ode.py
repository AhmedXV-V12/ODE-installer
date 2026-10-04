#!/usr/bin/env python3
"""End-to-end test of ODE_installer.iso in a virtual machine (QEMU/KVM).

  sudo python3 build/e2e-ode.py erase  [--medium M] [--iso ISO]
      UEFI machine, empty 16 GB disk: Erase disk and install, then start the
      installed IFelxOS2 through UEFI and through BIOS and sign in.
  sudo python3 build/e2e-ode.py manual [--medium M] [--iso ISO]
      The disk already holds a GPT table (BIOS boot, EFI, a data partition with
      a file on it, an empty partition). Opens GParted from the installer and
      closes it, installs on the empty partition, starts the installed system
      through UEFI and BIOS, and checks that the data partition was kept.

The installer starts from the medium M:
  cd        the ISO as a CD (default)
  usb       the ISO written to a USB stick as an image (dd, Etcher, Rufus "DD mode")
  fat       its files copied to a FAT32 USB stick (Rufus "ISO mode")
  isofile   the ISO as a file on an exFAT partition, the kernel started from a
            small FAT partition (how Ventoy keeps it)

Screens are saved to ODE_installer/docs/screenshots/e2e-<scenario>[-<medium>]/.
The coordinates are those of the installer window at 1280x800.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ODE_DIR = os.path.dirname(HERE)
os.environ.setdefault("IFX_VM", "/root/ode/vm")
sys.path.insert(0, HERE)
import vm  # noqa: E402  (QEMU driver: QMP clicks, typing, screenshots)

VMDIR = os.environ["IFX_VM"]
DISK = os.path.join(VMDIR, "disk.img")
DARK_BLUE = (0, 0, 139)
PASSWORD = "Test1234"
# exfatprogs and exfat-fuse unpacked, not installed (WSL's kernel has no exFAT)
TOOLS = os.environ.get("ODE_TOOLS", "/root/ode/tools")


def run(*argv):
    subprocess.check_call(argv)


def pixel(x, y):
    tmp = os.path.join(VMDIR, "probe.ppm")
    vm.qmp("screendump", {"filename": tmp})
    time.sleep(0.3)
    data = open(tmp, "rb").read()
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    off = (y * w + x) * 3
    return tuple(parts[3][off:off + 3])


def wait_pixel(x, y, color, timeout, every=2.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pixel(x, y) == color:
                return True
        except Exception:
            pass
        time.sleep(every)
    return False


class Run:
    def __init__(self, name):
        self.dir = os.path.join(ODE_DIR, "docs", "screenshots", "e2e-" + name)
        os.makedirs(self.dir, exist_ok=True)

    def shot(self, name):
        tmp = os.path.join(VMDIR, "shot.ppm")
        vm.qmp("screendump", {"filename": tmp})
        time.sleep(0.3)
        vm.ppm_to_png(tmp, os.path.join(self.dir, name + ".png"))
        print("   " + name, flush=True)

    @staticmethod
    def click(x, y, pause=1.2):
        vm.abs_move(x, y)
        time.sleep(0.15)
        vm.button("left", True)
        time.sleep(0.08)
        vm.button("left", False)
        time.sleep(pause)

    @staticmethod
    def type(text, pause=0.4):
        vm.type_text(text)
        time.sleep(pause)


def start(*args):
    run("python3", os.path.join(HERE, "vm.py"), "start", "--disk", DISK, *args)


def stop():
    try:
        vm.qmp("quit")
    except BaseException:
        pass
    time.sleep(3)


def installer_pages(r, mode):
    """Welcome -> terms -> disk -> type -> account -> summary -> install -> finish"""
    if not wait_pixel(560, 672, DARK_BLUE, 180):   # the Start button, beside its text
        r.shot("00-no-installer")
        raise SystemExit("the installer window did not appear")
    r.shot("01-welcome")
    r.click(640, 672)                       # Start
    r.click(210, 630)                       # Accept Terms
    r.shot("02-terms")
    r.click(1090, 720)                      # Next
    time.sleep(1)
    r.shot("03-disk")
    r.click(640, 215)                       # the first disk (the CD is not listed)
    r.click(640, 301)                       # the second, when the first is the USB medium
    r.click(1090, 720)
    time.sleep(1)
    if mode == "erase":
        r.click(355, 231, 3)                # Erase disk and install
        r.shot("04-type-erase")
        expect_next(r, "the disk check failed")
    else:
        r.click(925, 231, 3)                # Choose a partition
        r.shot("04-type-manual")
        r.click(390, 720, 8)                # Open GParted
        r.shot("05-gparted")
        # GParted is maximized; it closes with Ctrl+Q and the installer comes back
        vm.keys(["ctrl", "q"], True); time.sleep(0.1); vm.keys(["q", "ctrl"], False)
        time.sleep(4)
        r.shot("06-back-from-gparted")
        r.click(640, 485, 3)                # /dev/vda4
        r.shot("07-partition-chosen")
        expect_next(r, "the partition check failed")
    r.click(1090, 720)
    time.sleep(1)
    r.click(360, 334); r.type("ahmed")
    r.click(360, 430); r.type(PASSWORD)
    r.click(360, 526); r.type(PASSWORD)
    r.shot("08-account")
    r.click(1090, 720)
    time.sleep(1)
    r.shot("09-summary")
    r.click(1090, 720, 5)                   # Install
    r.shot("10-installing")
    end = time.time() + 30 * 60
    n = 0
    while time.time() < end:
        time.sleep(15)
        if pixel(1000, 720) == DARK_BLUE:   # Continue (beside its text): installed
            break
        if pixel(100, 720) == (200, 200, 200):   # only Back: failed
            r.shot("11-failed")
            raise SystemExit("the installation failed (see 11-failed.png)")
        n += 1
        if n % 8 == 0:
            r.shot("10-installing-%02d" % (n // 8))
    else:
        r.shot("11-timeout")
        raise SystemExit("the installation did not finish in 30 minutes")
    r.shot("11-installed")
    r.click(1090, 720)
    r.shot("12-finish")
    r.click(770, 470, 2)                    # Shut Down
    time.sleep(5)


def expect_next(r, why):
    """Next is enabled only when the backend's check passed"""
    if pixel(1000, 720) != DARK_BLUE:
        r.shot("xx-stopped")
        raise SystemExit(why + " (see xx-stopped.png)")


def installed(r, prefix, *args):
    start("--no-cd", *args)
    time.sleep(50)
    r.shot(prefix + "-login")
    r.type("wrong"); vm.keys(["ret"], True); time.sleep(0.1); vm.keys(["ret"], False)
    time.sleep(2)
    r.shot(prefix + "-wrong-password")
    r.type(PASSWORD); vm.keys(["ret"], True); time.sleep(0.1); vm.keys(["ret"], False)
    time.sleep(6)
    r.shot(prefix + "-session")
    stop()


def prepare_manual_disk():
    """GPT: BIOS boot, EFI (FAT32), data (ext4 with a marker file), empty"""
    run("truncate", "-s", "16G", DISK)
    # parted, not sfdisk: sfdisk ends with a global sync(), which hangs for as
    # long as any FUSE filesystem anywhere in WSL does not answer
    run("parted", "-s", DISK, "--", "mklabel", "gpt",
        "mkpart", "bios", "1MiB", "2MiB", "set", "1", "bios_grub", "on",
        "mkpart", "EFI", "fat32", "2MiB", "302MiB", "set", "2", "esp", "on",
        "mkpart", "data", "ext4", "302MiB", "2350MiB",
        "mkpart", "free", "ext4", "2350MiB", "100%")
    loop = subprocess.check_output(["losetup", "-f", "--show", "-P", DISK], text=True).strip()
    try:
        run("mkfs.vfat", "-F", "32", "-n", "EFI", loop + "p2")
        run("mkfs.ext4", "-q", "-L", "data", loop + "p3")
        mnt = os.path.join(VMDIR, "mnt")
        os.makedirs(mnt, exist_ok=True)
        run("mount", loop + "p3", mnt)
        open(os.path.join(mnt, "keep-me.txt"), "w").write("this partition must survive\n")
        run("umount", mnt)
    finally:
        run("losetup", "-d", loop)


def check_data_kept():
    loop = subprocess.check_output(["losetup", "-f", "--show", "-P", "-r", DISK], text=True).strip()
    mnt = os.path.join(VMDIR, "mnt")
    try:
        run("mount", "-o", "ro", loop + "p3", mnt)
        ok = os.path.exists(os.path.join(mnt, "keep-me.txt"))
        run("umount", mnt)
    finally:
        run("losetup", "-d", loop)
    print("data partition kept:", "yes" if ok else "NO")
    return ok


def loop_attach(img):
    return subprocess.check_output(["losetup", "-f", "--show", "-P", img], text=True).strip()


def make_medium(kind, iso):
    """the medium the VM starts the installer from, and how it is attached"""
    if kind == "cd":
        return iso, []
    if kind == "usb":
        return iso, ["--usb"]
    img = os.path.join(VMDIR, "medium.img")
    if os.path.exists(img):
        os.unlink(img)
    run("truncate", "-s", "2G", img)
    isomnt = os.path.join(VMDIR, "isomnt")
    mnt = os.path.join(VMDIR, "mnt")
    os.makedirs(isomnt, exist_ok=True)
    os.makedirs(mnt, exist_ok=True)
    if kind == "fat":
        run("parted", "-s", img, "--", "mklabel", "msdos",
            "mkpart", "primary", "fat32", "1MiB", "100%", "set", "1", "boot", "on")
    else:
        run("parted", "-s", img, "--", "mklabel", "msdos",
            "mkpart", "primary", "fat32", "1MiB", "301MiB", "set", "1", "esp", "on",
            "mkpart", "primary", "ntfs", "301MiB", "100%")
    loop = loop_attach(img)
    run("mount", "-o", "loop,ro", iso, isomnt)
    try:
        run("mkfs.vfat", "-F", "32", "-n", "ODE", loop + "p1")
        run("mount", loop + "p1", mnt)
        if kind == "fat":
            # every file of the ISO, as Rufus copies them
            run("cp", "-r", "--no-preserve=all", isomnt + "/.", mnt + "/")
        else:
            # only what the firmware needs to start the kernel
            for rel in ("EFI/BOOT/BOOTX64.EFI", "boot/vmlinuz", "boot/initrd.img", "boot/cmdline"):
                os.makedirs(os.path.dirname(os.path.join(mnt, rel)), exist_ok=True)
                run("cp", os.path.join(isomnt, rel), os.path.join(mnt, rel))
        run("umount", mnt)
        if kind == "isofile":
            run(os.path.join(TOOLS, "usr/sbin/mkfs.exfat"), "-L", "Ventoy", loop + "p2")
            run(os.path.join(TOOLS, "sbin/mount.exfat-fuse"), loop + "p2", mnt)
            run("cp", iso, os.path.join(mnt, "ODE_installer.iso"))
            run("umount", mnt)
    finally:
        subprocess.call(["umount", isomnt])
        subprocess.call(["losetup", "-d", loop])
    return img, ["--usb"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", choices=["erase", "manual"])
    p.add_argument("--medium", choices=["cd", "usb", "fat", "isofile"], default="cd")
    p.add_argument("--iso", default=os.path.join(ODE_DIR, "ODE_installer.iso"))
    a = p.parse_args()
    scenario = a.scenario
    os.makedirs(VMDIR, exist_ok=True)
    stop()
    for f in (DISK, os.path.join(VMDIR, "vars.fd")):
        if os.path.exists(f):
            os.unlink(f)
    test_iso = os.path.join(VMDIR, "test.iso")
    run("cp", a.iso, test_iso)
    medium, attach = make_medium(a.medium, test_iso)
    if scenario == "manual":
        prepare_manual_disk()
    r = Run(scenario if a.medium == "cd" else scenario + "-" + a.medium)

    print("== installer (UEFI, from %s)" % a.medium, flush=True)
    start("--iso", medium, "--disk-size", "16G", *attach)
    installer_pages(r, scenario)
    stop()
    if scenario == "manual" and not check_data_kept():
        raise SystemExit("the data partition was not kept")

    print("== installed system (UEFI)", flush=True)
    installed(r, "20-uefi")
    print("== installed system (BIOS)", flush=True)
    installed(r, "30-bios", "--bios")
    print("screens in", r.dir)


if __name__ == "__main__":
    main()
