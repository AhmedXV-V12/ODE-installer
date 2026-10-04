#!/bin/sh
# Makes the build environment for IFelxBoot inside WSL: a minimal Ubuntu 24.04
# tree with clang and lld, so WSL itself needs neither. build.sh runs this
# when it finds no compiler; it only has to happen once.
#   usage (inside WSL, as root): sh IFelxBoot/buildenv.sh
set -e
BUILDENV=${IFELXBOOT_BUILDENV:-/root/ifelxboot/buildenv}
if [ -x "$BUILDENV/usr/bin/clang" ] && [ -e "$BUILDENV/usr/bin/lld-link" ]; then
    echo "the build environment is ready: $BUILDENV"
    exit 0
fi
rm -rf "$BUILDENV"
mkdir -p "$(dirname "$BUILDENV")"
debootstrap --variant=minbase --components=main,universe noble "$BUILDENV" http://archive.ubuntu.com/ubuntu
cp /etc/resolv.conf "$BUILDENV/etc/resolv.conf"
mount -t proc proc "$BUILDENV/proc"
trap 'umount "$BUILDENV/proc"' EXIT
chroot "$BUILDENV" apt-get update
DEBIAN_FRONTEND=noninteractive chroot "$BUILDENV" apt-get -y --no-install-recommends install clang lld
chroot "$BUILDENV" apt-get clean
echo "the build environment is ready: $BUILDENV"
