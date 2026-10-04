# Example: itelxOS 1.2 in ODE

itelxOS is not a Linux system, so it brings its own backend.

* `config.json`: names and texts of itelxOS, 256 MiB minimum
* `ode-install`: unpacks the squashfs (`rootfs/`, `esp/`, `bios/`, `tools/`),
  partitions (erase: MBR with a 256 MiB EFI partition and an itelx partition,
  type 0x7F), writes ITFS with `tools/itfs mkfs`, writes IFelxBoot and the itelx
  kernel to the EFI partition, writes itelx's MBR and stage2 with
  `tools/itelx-installboot`, adds the UEFI entry `itelxOS` and checks the ITFS.

The squashfs is the itelxOS installation tree (`make installer` in the itelxOS
sources):

```bash
sudo tools/make-custom-ode.sh --iso ODE_installer.iso \
    --config examples/itelxOS/config.json \
    --squashfs itelx-filesystem.squashfs \
    --backend examples/itelxOS/ode-install \
    -o ODE_installer_itelx.iso
```

itelxOS 1.2 drives SATA (AHCI), IDE and NVMe disks and a PS/2 keyboard; in a
virtual machine give it a SATA disk, not virtio.
