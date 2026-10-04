# IFelxBoot

The UEFI boot loader of IFelxOS2, written from scratch against the UEFI
specification: a freestanding application in one C file, with no gnu-efi, no
EDK2 and no external library. It goes from firmware to kernel with nothing in
between: no menu, no countdown, no messages. What shows is the IFelx mark on a
dark screen, and then the system.

## Layout

```
src/ifelxboot.c        the loader
src/efi.h              the UEFI types and protocols it uses, from the specification
src/logo.h             the boot picture as raw BGRA pixels (generated)
logo/                  logobootloader.png and mklogo.py, which makes logo.h
build.sh               compiles out/BOOTX64.EFI and out/efi.img
buildenv.sh            makes the compiler environment inside WSL (once)
out/                   BOOTX64.EFI and efi.img, the build that is in use
tests/boot-test.py     boots it in QEMU/KVM in every situation it has to handle
```

## Where it runs

* **IFelxOS2.iso**: `/boot/efi.img` (the El Torito UEFI image) and
  `/EFI/BOOT/BOOTX64.EFI`. `build/pack-iso.sh` puts the current build there.
* **Installed IFelxOS2 disks**: `EFI/BOOT/BOOTX64.EFI` (and
  `EFI/IFelxOS2/BOOTX64.EFI` when ODE installed it) on the EFI partition.
  Both installers take it from the medium; the system image also carries it
  at `/dex/IFelxUi/installer/BOOTX64.EFI` (`ifelxui/installer/` here, which
  build.sh keeps up to date).
* **ODE_installer.iso**: `/boot/efi.img` and `/EFI/BOOT/BOOTX64.EFI`, with the
  installer's own command line in `/boot/cmdline`.

BIOS computers do not run it: they start through GRUB on all three.

## What it does

1. turns off the watchdog and the text cursor, and paints the IFelx ground
   with the logo in the centre
2. finds the system and reads `vmlinuz` and `initrd.img` into memory
3. publishes the initrd through the LoadFile2 protocol Linux asks for
4. starts the kernel with the command line

Where the system is, in this order:

1. **the volume the loader came from**, read as FAT: an installed disk keeps
   the kernel, the initrd and the command line on its own EFI partition
   (`\boot\vmlinuz`, `\boot\initrd.img`, `\boot\cmdline`)
2. **the medium the loader came from**, read as ISO 9660: a CD, or a USB stick
   written from the ISO. UEFI firmware only has to read FAT, so the loader
   reads ISO 9660 itself through EFI_BLOCK_IO (the primary volume descriptor at
   sector 16, then the directory records). The medium is found by device path:
   the loader runs from a FAT image that the firmware describes as a child of
   the whole medium (El Torito's image on a CD, the EFI partition on a stick)
3. any other FAT volume that carries `\boot\vmlinuz`
4. any other ISO 9660 medium

The command line is `\boot\cmdline` on the volume the system came from, or
`/boot/cmdline` on an ISO medium; without one, the built-in live command line
of IFelxOS2 is used.

## Building

Inside WSL, as root:

```bash
sh IFelxBoot/build.sh
```

It compiles with clang for the `x86_64-unknown-windows` target and links with
lld-link into a PE/COFF EFI application, then makes `out/efi.img` (FAT12,
1.44 MB) with it at `EFI/BOOT/BOOTX64.EFI`. When WSL has no clang or lld-link
it uses `/root/ifelxboot/buildenv`, an Ubuntu 24.04 tree with both, which
`buildenv.sh` makes the first time. A new boot picture: replace
`logo/logobootloader.png` (8-bit, not interlaced); build.sh remakes `logo.h`.

After a build, `build/pack-iso.sh` (IFelxOS2) and
`ODE_installer/build/build-ode.sh` (ODE) carry it into their ISOs.

## Testing

```bash
python3 IFelxBoot/tests/boot-test.py --disk <disk with IFelxOS2 installed> \
    --live iso/IFelxOS2.iso --ode ODE_installer/ODE_installer.iso --efi IFelxBoot/out/BOOTX64.EFI
```

The disk is copied, never changed. The cases are: the installed disk alone
starts the installed system (its login screen); IFelxOS2.iso as a CD and as a
USB stick, with the installed disk present, starts the live system; and the
same for ODE_installer.iso, which starts the installer. Screens are saved in
`tests/screens/`.

## Changes

* **2026-10-02**: a live or installer medium started the installed system
  instead of itself on a computer with IFelxOS2 installed: every FAT volume
  was searched for `\boot\vmlinuz` before the medium's ISO 9660 volume, and the
  installed EFI partition matched. The medium the loader came from now comes
  right after its own volume. A medium can carry its own command line in
  `/boot/cmdline`. The loader became a project of its own (it was
  `ifelxui/src/ifelxboot/`).
