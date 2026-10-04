#!/bin/bash
# Makes an ODE installer for your own system from a finished ODE medium,
# without rebuilding ODE. Everything is taken from the original ISO as it is
# (Linux kernel, the installer system in the initrd, the window, init,
# ode-find-medium, GRUB, IFelxBoot, the boot catalogue); only this changes:
#
#   /ifelxos/filesystem.squashfs   your system (a squashfs, or a directory packed here)
#   initrd: /app/config.json       names and texts of your system (see config.json)
#   initrd: /usr/sbin/ode-install  only with --backend: when your system is not a
#                                  Linux tree the stock backend can install
#
#   usage (Linux/WSL, root):
#     tools/make-custom-ode.sh --iso ODE_installer.iso --config my.json \
#         (--squashfs my.squashfs | --tree my-rootfs/) [--backend my-ode-install] \
#         [-o MyOS_installer.iso]
#
# Needs xorriso, zstd, cpio, squashfs-tools and python3.
# The stock backend (fix_src/ode-install) expects a Linux root filesystem: it
# formats ext4, creates the account with chroot useradd and sets up GRUB and
# IFelxBoot through ifelx-update-boot. For anything else write a backend with
# the same command line and output (examples/itelxOS/ode-install is one).
set -euo pipefail
SRC_ISO= CONFIG= SQUASHFS= TREE= BACKEND= OUT=custom_ode_installer.iso
while [ $# -gt 0 ]; do
    case "$1" in
        --iso) SRC_ISO=$2; shift ;;
        --config) CONFIG=$2; shift ;;
        --squashfs) SQUASHFS=$2; shift ;;
        --tree) TREE=$2; shift ;;
        --backend) BACKEND=$2; shift ;;
        -o) OUT=$2; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done
[ "$(id -u)" = 0 ] || { echo "run as root (device nodes in the initrd)" >&2; exit 1; }
[ -f "$SRC_ISO" ] || { echo "--iso: no ODE medium at '$SRC_ISO'" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "--config: no file '$CONFIG'" >&2; exit 1; }
[ -n "$SQUASHFS$TREE" ] || { echo "give --squashfs or --tree" >&2; exit 1; }
[ -z "$BACKEND" ] || [ -f "$BACKEND" ] || { echo "--backend: no file '$BACKEND'" >&2; exit 1; }
for t in xorriso zstd cpio mksquashfs python3; do
    command -v $t >/dev/null || { echo "missing tool: $t" >&2; exit 1; }
done
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$CONFIG" ||
    { echo "$CONFIG is not valid JSON" >&2; exit 1; }

WORK=$(mktemp -d /tmp/custom-ode.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

if [ -n "$TREE" ]; then
    echo "== packing $TREE"
    mksquashfs "$TREE" "$WORK/filesystem.squashfs" -comp xz -noappend -all-root -quiet >/dev/null
else
    cp "$SQUASHFS" "$WORK/filesystem.squashfs"
fi
chmod 644 "$WORK/filesystem.squashfs"
echo "filesystem.squashfs: $(stat -c %s "$WORK/filesystem.squashfs") bytes"

echo "== the initrd of $(basename "$SRC_ISO")"
xorriso -osirrox on -indev "$SRC_ISO" -extract /boot/initrd.img "$WORK/initrd.orig" >/dev/null 2>&1
mkdir "$WORK/rd"
(cd "$WORK/rd" && zstd -dc ../initrd.orig | cpio -idm --quiet --no-absolute-filenames)
[ -f "$WORK/rd/app/config.json" ] && [ -x "$WORK/rd/usr/sbin/ode-install" ] ||
    { echo "the initrd does not look like the ODE installer's" >&2; exit 1; }
install -m 644 "$CONFIG" "$WORK/rd/app/config.json"
if [ -n "$BACKEND" ]; then
    install -m 755 "$BACKEND" "$WORK/rd/usr/sbin/ode-install"
    sh -n "$WORK/rd/usr/sbin/ode-install"
fi
(cd "$WORK/rd" && find . -mindepth 1 | LC_ALL=C sort | cpio -o -H newc --quiet) | zstd -19 -T0 -q > "$WORK/initrd.img"

echo "== the ISO: the original with the files replaced, boot records kept"
xorriso -indev "$SRC_ISO" -outdev "$WORK/out.iso" -boot_image any replay \
    -map "$WORK/initrd.img" /boot/initrd.img \
    -map "$WORK/filesystem.squashfs" /ifelxos/filesystem.squashfs \
    -commit >/dev/null 2>"$WORK/xorriso.log" || { cat "$WORK/xorriso.log" >&2; exit 1; }
mv "$WORK/out.iso" "$OUT"
sha256sum "$OUT" | tee "$OUT.sha256"
