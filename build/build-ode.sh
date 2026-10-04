#!/bin/bash
# Builds ODE_installer.iso: the ODE installer, which installs IFelxOS2.
#
# The installer is a small Ubuntu 24.04 system that runs entirely from its
# initrd: Xorg, openbox, GParted and the installer window (app.py, pygame).
# The system it installs is not in the initrd: IFelxOS2's filesystem.squashfs
# sits on the medium as /ifelxos/filesystem.squashfs and is read from there.
# The kernel and its modules are the ones of the previous ODE image (Ubuntu
# 6.8.0-142, simpledrm built in), taken from an earlier ODE image (BASE_ISO).
# The medium starts on UEFI through IFelxBoot (IFELXBOOT, a separate project)
# and on BIOS through GRUB.
#
#   usage: sudo build/build-ode.sh [--rootfs] [output.iso]
#     --rootfs        rebuild the Ubuntu base from scratch (otherwise it is reused)
#     --rootfs-only   rebuild the Ubuntu base and stop
#
# Runs inside WSL (Ubuntu 24.04) as root; the work area is /root/ode.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"           # the repository
IFELXBOOT=${IFELXBOOT:-"$(dirname "$HERE")/IFelxBoot"}
WORK=${WORK:-/root/ode}
ROOTFS=$WORK/rootfs          # the Ubuntu base, kept between builds
STAGE=$WORK/stage            # the base plus the installer: the initrd's contents
ISODIR=$WORK/isodir
KDIR=$WORK/kernel
BASE_ISO=${BASE_ISO:-"$HERE/input/ODE_base.iso"}        # kernel + modules come from here
IFELXOS_ISO=${IFELXOS_ISO:-"$HERE/input/IFelxOS2.iso"}  # its live/filesystem.squashfs is installed
APP_SRC="$HERE/ODE_installer_code_app.bin"
OVERLAY="$HERE/fix_src"
KVER=6.8.0-142-generic
MIRROR=http://archive.ubuntu.com/ubuntu

REBUILD_ROOTFS=0
ROOTFS_ONLY=0
OUT_ISO="$HERE/ODE_installer.iso"
for a in "$@"; do
    case "$a" in
        --rootfs) REBUILD_ROOTFS=1 ;;
        --rootfs-only) REBUILD_ROOTFS=1; ROOTFS_ONLY=1 ;;
        *) OUT_ISO=$a ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$BASE_ISO" ] || { echo "no base ISO at $BASE_ISO" >&2; exit 1; }
[ -f "$IFELXOS_ISO" ] || { echo "no IFelxOS2 ISO at $IFELXOS_ISO" >&2; exit 1; }
mkdir -p "$WORK"

PACKAGES="
  busybox-static kmod procps
  e2fsprogs dosfstools parted gparted squashfs-tools efibootmgr grub-pc-bin grub2-common
  xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-video-fbdev xserver-xorg-video-vesa
  udev
  x11-xserver-utils x11-xkb-utils xkb-data openbox
  python3 python3-pygame
  fonts-dejavu-core adwaita-icon-theme hicolor-icon-theme librsvg2-common shared-mime-info
"

chroot_mounts() {
    mount -t proc proc "$1/proc"
    mount -t sysfs sysfs "$1/sys"
    mount --bind /dev "$1/dev"
    mount --bind /dev/pts "$1/dev/pts"
}
chroot_umounts() {
    for m in dev/pts dev sys proc; do umount "$1/$m" 2>/dev/null || true; done
}

# ------------------------------------------------------------ Ubuntu base
build_rootfs() {
    echo "== Ubuntu 24.04 base at $ROOTFS"
    chroot_umounts "$ROOTFS"
    rm -rf "$ROOTFS"
    debootstrap --variant=minbase --components=main,universe noble "$ROOTFS" "$MIRROR"
    cat > "$ROOTFS/etc/apt/sources.list" <<EOF
deb $MIRROR noble main universe
deb $MIRROR noble-updates main universe
deb http://security.ubuntu.com/ubuntu noble-security main universe
EOF
    printf 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n' \
        > "$ROOTFS/etc/apt/apt.conf.d/99ode"
    # documentation and translations are never read here
    cat > "$ROOTFS/etc/dpkg/dpkg.cfg.d/01ode-nodoc" <<EOF
path-exclude=/usr/share/doc/*
path-exclude=/usr/share/man/*
path-exclude=/usr/share/info/*
path-exclude=/usr/share/locale/*
path-include=/usr/share/locale/locale.alias
path-exclude=/usr/share/lintian/*
EOF
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    chroot_mounts "$ROOTFS"
    trap 'chroot_umounts "$ROOTFS"' EXIT
    chroot "$ROOTFS" apt-get update
    DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS" apt-get -y dist-upgrade
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS" apt-get -y install $PACKAGES
    chroot "$ROOTFS" apt-get clean
    chroot_umounts "$ROOTFS"
    trap - EXIT
    rm -rf "$ROOTFS"/usr/share/doc/* "$ROOTFS"/usr/share/man/* "$ROOTFS"/usr/share/info/* \
           "$ROOTFS"/var/lib/apt/lists/* "$ROOTFS"/var/cache/apt/* "$ROOTFS"/var/log/* \
           "$ROOTFS"/var/cache/debconf/*-old "$ROOTFS"/var/lib/dpkg/*-old
    find "$ROOTFS/usr/share/locale" -mindepth 1 -maxdepth 1 ! -name locale.alias -exec rm -rf {} +
    : > "$ROOTFS/etc/resolv.conf"
    du -sh "$ROOTFS"
}

if [ "$REBUILD_ROOTFS" = 1 ] || [ ! -x "$ROOTFS/usr/bin/Xorg" ] || [ ! -x "$ROOTFS/usr/sbin/gpartedbin" -a ! -x "$ROOTFS/usr/libexec/gpartedbin" ]; then
    build_rootfs
fi
# packages added to the list after the base was made go into it without a rebuild
MISSING=""
for p in $PACKAGES; do
    chroot "$ROOTFS" dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then
    echo "== adding to the base:$MISSING"
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    chroot_mounts "$ROOTFS"
    trap 'chroot_umounts "$ROOTFS"' EXIT
    chroot "$ROOTFS" apt-get update
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS" apt-get -y install $MISSING
    chroot "$ROOTFS" apt-get clean
    chroot_umounts "$ROOTFS"
    trap - EXIT
    rm -rf "$ROOTFS"/var/lib/apt/lists/* "$ROOTFS"/var/cache/apt/*
    find "$ROOTFS/usr/share/locale" -mindepth 1 -maxdepth 1 ! -name locale.alias -exec rm -rf {} +
    : > "$ROOTFS/etc/resolv.conf"
fi
[ "$ROOTFS_ONLY" = 1 ] && exit 0

# --------------------------------------------------- kernel and its modules
if [ ! -d "$KDIR/lib/modules/$KVER" ] || [ ! -f "$KDIR/vmlinuz" ]; then
    echo "== kernel $KVER from $(basename "$BASE_ISO")"
    rm -rf "$KDIR"; mkdir -p "$KDIR/rd"
    xorriso -osirrox on -indev "$BASE_ISO" -extract /boot/vmlinuz "$KDIR/vmlinuz" \
            -extract /boot/initrd.img "$KDIR/initrd.img" >/dev/null 2>&1
    (cd "$KDIR/rd" && gzip -dc ../initrd.img | cpio -idm --quiet "lib/modules/$KVER/*")
    mkdir -p "$KDIR/lib/modules"
    mv "$KDIR/rd/lib/modules/$KVER" "$KDIR/lib/modules/"
    rm -rf "$KDIR/rd" "$KDIR/initrd.img"
fi

# ------------------------------------------------ IFelxBoot (UEFI start)
# The medium starts on UEFI through IFelxBoot, the same loader as IFelxOS2.iso
# and installed IFelxOS2 disks, built by the IFelxBoot project; BIOS computers
# start it through GRUB. IFelxBoot reads the kernel, the initrd and this
# medium's command line (/boot/cmdline) from the ISO 9660 volume itself.
echo "== IFelxBoot"
sh "$IFELXBOOT/build.sh"
BOOTEFI="$IFELXBOOT/out/BOOTX64.EFI"
BOOTIMG="$IFELXBOOT/out/efi.img"
[ -s "$BOOTEFI" ] && [ -s "$BOOTIMG" ] || { echo "IFelxBoot did not build" >&2; exit 1; }

# ----------------------------------------------------- the IFelxOS2 image
SQ=$WORK/ifelxos.squashfs
SRC_ID="$(stat -c '%s %Y' "$IFELXOS_ISO")"
if [ ! -f "$SQ" ] || [ "$(cat "$SQ.src" 2>/dev/null)" != "$SRC_ID" ]; then
    echo "== IFelxOS2 image from $(basename "$IFELXOS_ISO")"
    rm -f "$SQ"
    xorriso -osirrox on -indev "$IFELXOS_ISO" -extract /live/filesystem.squashfs "$SQ" >/dev/null 2>&1
    chmod 644 "$SQ"
    echo "$SRC_ID" > "$SQ.src"
fi
[ -s "$SQ" ] || { echo "no filesystem.squashfs in $IFELXOS_ISO" >&2; exit 1; }
# room the installed system needs: its unpacked size, half again for use, 6 GiB at least
UNPACKED_MIB=$(unsquashfs -lls "$SQ" 2>/dev/null | awk '$1 ~ /^-/ {s += $3} END {printf "%d", s / 1048576}')
MIN_ROOT_MIB=$(( UNPACKED_MIB * 3 / 2 ))
[ "$MIN_ROOT_MIB" -lt 6144 ] && MIN_ROOT_MIB=6144
echo "IFelxOS2 unpacks to $UNPACKED_MIB MiB; the root partition needs $MIN_ROOT_MIB MiB"

# ---------------------------------------------------------------- stage
echo "== staging the installer system"
rm -rf "$STAGE"
cp -a "$ROOTFS" "$STAGE"
# Packages that come in as dependencies but are never used here, removed from
# the copy that becomes the initrd (it all lives in memory). Xorg runs without
# acceleration and SDL draws in software, so Mesa's drivers and LLVM are never
# loaded; Ghostscript only serves an optional imlib2 loader; cpp serves xrdb;
# numpy is optional for pygame; systemd never runs (udev does, on its own).
SLIM_PACKAGES="libllvm20 mesa-libgallium libegl-mesa0 libglx-mesa0 libgl1-mesa-dri
  cpp cpp-13 cpp-13-x86-64-linux-gnu cpp-x86-64-linux-gnu libisl23 libmpfr6 libmpc3
  python3-numpy liblapack3 libblas3 libgfortran5
  humanity-icon-theme ubuntu-mono
  libgs10 libgs10-common libspectre1 poppler-data fonts-urw-base35 fonts-freefont-ttf
  timgm6mb-soundfont
  systemd systemd-sysv systemd-dev libpam-systemd dbus-user-session"
for p in $SLIM_PACKAGES; do
    for list in "$STAGE/var/lib/dpkg/info/$p.list" "$STAGE/var/lib/dpkg/info/$p:amd64.list"; do
        [ -f "$list" ] || continue
        while IFS= read -r f; do
            if [ -f "$STAGE$f" ] || [ -L "$STAGE$f" ]; then rm -f "$STAGE$f"; fi
        done < "$list"
    done
done
rm -rf "$STAGE"/usr/share/icons/Humanity* "$STAGE"/usr/share/icons/ubuntu-mono-* \
       "$STAGE"/usr/lib/x86_64-linux-gnu/dri "$STAGE"/usr/lib/x86_64-linux-gnu/gbm \
       "$STAGE"/usr/lib/x86_64-linux-gnu/imlib2/loaders/ps.so "$STAGE"/usr/share/sounds
chroot "$STAGE" fc-cache -f >/dev/null 2>&1 || true

mkdir -p "$STAGE/usr/lib/modules"
cp -a "$KDIR/lib/modules/$KVER" "$STAGE/usr/lib/modules/"
depmod -b "$STAGE" "$KVER"

# systemd-sysv (pulled in by dependencies, never started) owns shutdown as a link
rm -f "$STAGE/usr/sbin/shutdown" "$STAGE/init"
install -m 755 "$OVERLAY/init"             "$STAGE/init"
install -m 755 "$OVERLAY/ode-x11"          "$STAGE/usr/bin/ode-x11"
install -m 755 "$OVERLAY/ode-xorg-conf"    "$STAGE/usr/sbin/ode-xorg-conf"
install -m 755 "$OVERLAY/ode-install"      "$STAGE/usr/sbin/ode-install"
install -m 755 "$OVERLAY/ode-find-medium"  "$STAGE/usr/sbin/ode-find-medium"
install -m 755 "$OVERLAY/shutdown"         "$STAGE/usr/sbin/shutdown"
install -m 755 "$OVERLAY/openbox-autostart" "$STAGE/etc/xdg/openbox/autostart"
sed -i "s/^MIN_ROOT_MIB=.*/MIN_ROOT_MIB=\${ODE_MIN_ROOT_MIB:-$MIN_ROOT_MIB}/" "$STAGE/usr/sbin/ode-install"
# GParted opens maximized, so it is never a small window on a black screen
# (its main window is titled "/dev/sda - GParted"; its dialogs keep their size)
sed -i 's|</applications>|  <application title="*GParted" type="normal"><maximized>yes</maximized><focus>yes</focus></application>\n</applications>|' \
    "$STAGE/etc/xdg/openbox/rc.xml"
grep -qF 'title="*GParted"' "$STAGE/etc/xdg/openbox/rc.xml" || { echo "openbox rc.xml was not patched" >&2; exit 1; }

echo ode > "$STAGE/etc/hostname"
printf '127.0.0.1\tlocalhost\n127.0.1.1\tode\n' > "$STAGE/etc/hosts"
rm -rf "$STAGE/root"; mkdir -m 700 "$STAGE/root"
cp "$STAGE/etc/skel/.profile" "$STAGE/etc/skel/.bashrc" "$STAGE/root/" 2>/dev/null || true
mkdir -p "$STAGE/run/ode" "$STAGE/var/log"
rm -f "$STAGE/dev/console"; mknod -m 600 "$STAGE/dev/console" c 5 1
rm -f "$STAGE/dev/null"; mknod -m 666 "$STAGE/dev/null" c 1 3

# the installer window
rm -rf "$STAGE/app"; mkdir -p "$STAGE/app/fonts"
install -m 644 "$APP_SRC/app.py" "$APP_SRC/ODE.py" "$APP_SRC/logo.png" "$STAGE/app/"
for f in ARIAL.TTF ARIALBD.TTF; do        # optional, see ODE_installer_code_app.bin/fonts/README
    [ -f "$APP_SRC/fonts/$f" ] && install -m 644 "$APP_SRC/fonts/$f" "$STAGE/app/fonts/"
done
python3 - "$APP_SRC/config.json" "$STAGE/app/config.json" "$MIN_ROOT_MIB" <<'EOF'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
cfg.setdefault("system", {})["min_root_mib"] = int(sys.argv[3])
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), indent=2, ensure_ascii=False)
EOF
cat > "$STAGE/app/app.bin" <<'EOF'
#!/bin/sh
# the installer window; ode-x11 starts it inside the X session
cd /app && exec /usr/bin/python3 -B /app/app.py "$@"
EOF
chmod 755 "$STAGE/app/app.bin"
chroot "$STAGE" /usr/bin/python3 -B -c "import ast, pygame; [ast.parse(open('/app/' + f).read()) for f in ('app.py', 'ODE.py')]; print('pygame', pygame.version.ver)" </dev/null
chroot "$STAGE" ldconfig
du -sh "$STAGE"

# ---------------------------------------------------------------- initrd
echo "== packing the initrd"
(cd "$STAGE" && find . -mindepth 1 | LC_ALL=C sort | cpio -o -H newc --quiet) | zstd -19 -T0 -q > "$WORK/initrd.img"
ls -la "$WORK/initrd.img"

# ------------------------------------------------------------------- ISO
echo "== writing the ISO"
rm -rf "$ISODIR"
mkdir -p "$ISODIR/boot/grub" "$ISODIR/ifelxos"
cp "$KDIR/vmlinuz" "$ISODIR/boot/vmlinuz"
cp "$WORK/initrd.img" "$ISODIR/boot/initrd.img"
cp "$OVERLAY/grub.cfg" "$ISODIR/boot/grub/grub.cfg"
ln "$SQ" "$ISODIR/ifelxos/filesystem.squashfs"
# UEFI: IFelxBoot, in the El Torito image and where firmwares that read ISO
# 9660 themselves look for it, with the command line for this medium (without
# it IFelxBoot would use IFelxOS2's live one)
cp "$BOOTIMG" "$ISODIR/boot/efi.img"
mkdir -p "$ISODIR/EFI/BOOT"
cp "$BOOTEFI" "$ISODIR/EFI/BOOT/BOOTX64.EFI"
echo "quiet loglevel=3 ifelx.loader=ifelxboot" > "$ISODIR/boot/cmdline"
# BIOS: GRUB from El Torito (CD) or from the hybrid MBR (USB stick). Its core
# finds the medium by a file only this build carries.
STAMP="ode-$(date +%Y%m%d%H%M%S)"
mkdir -p "$ISODIR/.disk" "$ISODIR/boot/grub/i386-pc" "$ISODIR/boot/grub/fonts"
echo "ODE Installer" > "$ISODIR/.disk/$STAMP"
cp /usr/lib/grub/i386-pc/*.mod /usr/lib/grub/i386-pc/*.lst "$ISODIR/boot/grub/i386-pc/"
cp /usr/share/grub/unicode.pf2 "$ISODIR/boot/grub/fonts/"
printf 'search --no-floppy --set=root --file /.disk/%s\nset prefix=($root)/boot/grub\n' "$STAMP" > "$WORK/eltorito.cfg"
grub-mkimage -O i386-pc-eltorito -p /boot/grub -c "$WORK/eltorito.cfg" \
    -o "$ISODIR/boot/grub/i386-pc/eltorito.img" biosdisk iso9660 search part_msdos part_gpt
rm -f "$WORK/build.iso"
xorriso -as mkisofs -graft-points -r -V ODE_INSTALLER -o "$WORK/build.iso" \
    -c boot/boot.catalog \
    -b boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
    --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
    --efi-boot boot/efi.img -efi-boot-part --efi-boot-image \
    --protective-msdos-label \
    "$ISODIR" >/dev/null 2>&1 || { echo "xorriso failed" >&2; exit 1; }
xorriso -indev "$WORK/build.iso" -report_el_torito plain 2>/dev/null | grep -E "boot img|img path" || true

# the image in the project is kept, not overwritten
if [ -f "$OUT_ISO" ]; then
    stamp=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$HERE/archive"
    mv "$OUT_ISO" "$HERE/archive/ODE_installer.previous-$stamp.iso"
    echo "kept the previous image as archive/ODE_installer.previous-$stamp.iso"
fi
cp "$WORK/build.iso" "$OUT_ISO"
rm -f "$WORK/build.iso"
echo
echo "done: $OUT_ISO"
ls -la "$OUT_ISO"
(cd "$(dirname "$OUT_ISO")" && sha256sum "$(basename "$OUT_ISO")" | tee "$(basename "$OUT_ISO").sha256")
