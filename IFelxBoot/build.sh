#!/bin/sh
# Builds IFelxBoot.
#
#   logo/logobootloader.png -> src/logo.h        (the picture, as raw pixels)
#   src/ifelxboot.c         -> out/BOOTX64.EFI   (PE/COFF, freestanding, no external library)
#   out/BOOTX64.EFI         -> out/efi.img       (FAT, what El Torito hands to the firmware)
#
# In the IFelxOS2 tree, BOOTX64.EFI is also copied to ifelxui/installer/, the
# copy IFelxOS2's own installer writes to the EFI partition.
#
#   usage (inside WSL, as root): sh IFelxBoot/build.sh
#
# clang and lld-link are taken from PATH when they are there, otherwise from
# the build environment buildenv.sh makes (/root/ifelxboot/buildenv).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
PROJECT=$(dirname "$HERE")
OUT=$HERE/out
BUILDENV=${IFELXBOOT_BUILDENV:-/root/ifelxboot/buildenv}
LOGO=${LOGO:-$HERE/logo/logobootloader.png}

if [ ! -f "$HERE/src/logo.h" ] || [ "$LOGO" -nt "$HERE/src/logo.h" ]; then
    python3 "$HERE/logo/mklogo.py" "$LOGO" "$HERE/src/logo.h" 256 >/dev/null
fi

CFLAGS="-target x86_64-unknown-windows -ffreestanding -fno-stack-protector -fshort-wchar \
        -mno-red-zone -Wall -Wextra -O2"
# -Brepro: no time stamp in the image, so the same source gives the same file
LDFLAGS="-subsystem:efi_application -entry:efi_main -nodefaultlib -Brepro"
mkdir -p "$OUT"
if command -v clang >/dev/null 2>&1 && command -v lld-link >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    clang $CFLAGS -c "$HERE/src/ifelxboot.c" -o "$OUT/ifelxboot.o"
    # shellcheck disable=SC2086
    lld-link $LDFLAGS "$OUT/ifelxboot.o" -out:"$OUT/BOOTX64.EFI"
    rm -f "$OUT/ifelxboot.o"
else
    [ -x "$BUILDENV/usr/bin/clang" ] || sh "$HERE/buildenv.sh"
    rm -rf "$BUILDENV/build/ifelxboot"
    mkdir -p "$BUILDENV/build/ifelxboot"
    cp "$HERE/src/ifelxboot.c" "$HERE/src/efi.h" "$HERE/src/logo.h" "$BUILDENV/build/ifelxboot/"
    chroot "$BUILDENV" sh -c "cd /build/ifelxboot &&
        clang $CFLAGS -c ifelxboot.c -o ifelxboot.o &&
        lld-link $LDFLAGS ifelxboot.o -out:BOOTX64.EFI"
    cp "$BUILDENV/build/ifelxboot/BOOTX64.EFI" "$OUT/BOOTX64.EFI"
fi

rm -f "$OUT/efi.img"
mkfs.vfat -C -F 12 -n IFELXBOOT "$OUT/efi.img" 1440 >/dev/null
mmd -i "$OUT/efi.img" ::/EFI ::/EFI/BOOT
mcopy -i "$OUT/efi.img" "$OUT/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI

[ -d "$PROJECT/ifelxui/installer" ] && cp "$OUT/BOOTX64.EFI" "$PROJECT/ifelxui/installer/BOOTX64.EFI"
echo "IFelxBoot: $(stat -c %s "$OUT/BOOTX64.EFI") bytes, sha256 $(sha256sum "$OUT/BOOTX64.EFI" | cut -c1-16)"
