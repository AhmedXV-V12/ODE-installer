#include "efi.h"
#include "logo.h"

/* IFelxBoot - the IFelxOS2 boot loader.
 *
 * Written from scratch against the UEFI specification. It exists because the
 * machine should go from firmware to desktop with nothing in between: no menu,
 * no countdown, no messages, no log. What the user sees is the IFelx mark in
 * the middle of a black screen, and then the desktop.
 *
 * What it does, in order:
 *   1. turns off the watchdog and the text cursor, and takes the screen
 *   2. paints the IFelx ground and blits logo.png in the centre - the picture
 *      itself, converted to raw pixels at build time, not a drawing of it
 *   3. finds the volume that carries the system and reads the kernel and the
 *      initrd into memory
 *   4. publishes the initrd through the protocol Linux asks for
 *   5. starts the kernel with the command line built in below
 *
 * There is no configuration file and no interactive path: a loader that asks
 * questions is a loader that costs a second. */

#define KERNEL_PATH  L"\\boot\\vmlinuz"
#define INITRD_PATH  L"\\boot\\initrd.img"
#define CMDLINE_PATH L"\\boot\\cmdline"

/* quiet on every channel: the kernel prints nothing, systemd prints nothing,
 * udev prints nothing, and the cursor never appears */
static CHAR16 g_cmdline[] =
    L"boot=live username=user quiet splash loglevel=0 rd.systemd.show_status=false "
    L"systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 "
    L"console=tty1 ifelx.loader=ifelxboot";

/* room for a command line read from the volume; an installed system needs a
 * different one from the live medium, and that is the only thing about this
 * loader that is ever configured */
static CHAR16 g_cmdbuf[512];

static EFI_SYSTEM_TABLE  *ST;
static EFI_BOOT_SERVICES *BS;

static EFI_GUID gop_guid   = EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID;
static EFI_GUID sfs_guid   = EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID;
static EFI_GUID li_guid    = EFI_LOADED_IMAGE_PROTOCOL_GUID;
static EFI_GUID dp_guid    = EFI_DEVICE_PATH_PROTOCOL_GUID;
static EFI_GUID lf2_guid   = EFI_LOAD_FILE2_PROTOCOL_GUID;
static EFI_GUID fi_guid    = EFI_FILE_INFO_GUID;
static EFI_GUID initrd_guid = LINUX_EFI_INITRD_MEDIA_GUID;
static EFI_GUID blkio_guid = EFI_BLOCK_IO_PROTOCOL_GUID;

/* ------------------------------------------------------------- helpers */


static void copy(void *d, const void *s, UINTN n) {
    UINT8 *a = d;
    const UINT8 *b = s;
    while (n--) *a++ = *b++;
}

static UINTN dp_len(EFI_DEVICE_PATH_PROTOCOL *dp) {
    UINTN n = 0;
    while (!(dp->Type == DP_TYPE_END && dp->SubType == DP_END_ENTIRE)) {
        UINTN l = dp->Length[0] | ((UINTN)dp->Length[1] << 8);
        if (l < 4) break;
        n += l;
        dp = (EFI_DEVICE_PATH_PROTOCOL *)((UINT8 *)dp + l);
    }
    return n;                     /* without the end node */
}

static UINTN str16_len(CHAR16 *s) {
    UINTN n = 0;
    while (s[n]) n++;
    return n;
}

/* device path of a file on a volume: <volume path> + FILEPATH(name) + END */
static EFI_DEVICE_PATH_PROTOCOL *file_device_path(EFI_HANDLE vol, CHAR16 *name) {
    EFI_DEVICE_PATH_PROTOCOL *vdp = NULL;
    if (EFI_ERR(BS->HandleProtocol(vol, &dp_guid, (void **)&vdp)) || !vdp) return NULL;
    UINTN head = dp_len(vdp);
    UINTN nchars = str16_len(name) + 1;
    UINTN fnode = 4 + nchars * 2;
    UINTN total = head + fnode + 4;
    UINT8 *buf = NULL;
    if (EFI_ERR(BS->AllocatePool(EfiLoaderData, total, (void **)&buf)) || !buf) return NULL;
    copy(buf, vdp, head);
    UINT8 *p = buf + head;
    p[0] = DP_TYPE_MEDIA;
    p[1] = DP_MEDIA_FILE;
    p[2] = (UINT8)(fnode & 0xFF);
    p[3] = (UINT8)(fnode >> 8);
    copy(p + 4, name, nchars * 2);
    p += fnode;
    p[0] = DP_TYPE_END;
    p[1] = DP_END_ENTIRE;
    p[2] = 4;
    p[3] = 0;
    return (EFI_DEVICE_PATH_PROTOCOL *)buf;
}

/* ---------------------------------------------------------------- files */

static EFI_STATUS read_file(EFI_HANDLE vol, CHAR16 *path, void **out, UINTN *size,
                            EFI_MEMORY_TYPE type) {
    EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs = NULL;
    EFI_FILE_PROTOCOL *root = NULL, *f = NULL;
    EFI_STATUS st;

    st = BS->HandleProtocol(vol, &sfs_guid, (void **)&fs);
    if (EFI_ERR(st)) return st;
    st = fs->OpenVolume(fs, &root);
    if (EFI_ERR(st)) return st;
    st = root->Open(root, &f, path, EFI_FILE_MODE_READ, 0);
    if (EFI_ERR(st)) { root->Close(root); return st; }

    UINT64 fsize = 0;
    UINT8 info[512];
    UINTN isz = sizeof info;
    if (!EFI_ERR(f->GetInfo(f, &fi_guid, &isz, info)))
        fsize = ((EFI_FILE_INFO *)info)->FileSize;
    if (!fsize) {
        f->SetPosition(f, 0xFFFFFFFFFFFFFFFFULL);
        f->GetPosition(f, &fsize);
        f->SetPosition(f, 0);
    }
    if (!fsize) { f->Close(f); root->Close(root); return EFI_LOAD_ERROR; }

    void *buf = NULL;
    st = BS->AllocatePool(type, (UINTN)fsize, &buf);
    if (EFI_ERR(st)) { f->Close(f); root->Close(root); return st; }

    /* read in one call where the firmware allows it, in chunks where it does
       not: some firmwares cap a single read */
    UINTN done = 0;
    while (done < fsize) {
        UINTN want = (UINTN)(fsize - done);
        if (want > 16 * 1024 * 1024) want = 16 * 1024 * 1024;
        UINTN got = want;
        st = f->Read(f, &got, (UINT8 *)buf + done);
        if (EFI_ERR(st) || got == 0) break;
        done += got;
    }
    f->Close(f);
    root->Close(root);
    if (done != fsize) { BS->FreePool(buf); return EFI_LOAD_ERROR; }
    *out = buf;
    *size = (UINTN)fsize;
    return EFI_SUCCESS;
}

static BOOLEAN volume_has(EFI_HANDLE vol, CHAR16 *path) {
    EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs = NULL;
    EFI_FILE_PROTOCOL *root = NULL, *f = NULL;
    if (EFI_ERR(BS->HandleProtocol(vol, &sfs_guid, (void **)&fs))) return FALSE;
    if (EFI_ERR(fs->OpenVolume(fs, &root))) return FALSE;
    EFI_STATUS st = root->Open(root, &f, path, EFI_FILE_MODE_READ, 0);
    if (!EFI_ERR(st)) f->Close(f);
    root->Close(root);
    return !EFI_ERR(st);
}

/* the device the loader itself was read from: the EFI partition of an
   installed disk, or the El Torito image / EFI partition of a medium */
static EFI_HANDLE loader_device(EFI_HANDLE self) {
    EFI_LOADED_IMAGE_PROTOCOL *li = NULL;
    if (EFI_ERR(BS->HandleProtocol(self, &li_guid, (void **)&li)) || !li) return NULL;
    return li->DeviceHandle;
}

/* any FAT volume other than the loader's own that carries the kernel */
static EFI_HANDLE find_other_volume(EFI_HANDLE own) {
    UINTN n = 0;
    EFI_HANDLE *h = NULL;
    if (EFI_ERR(BS->LocateHandleBuffer(ByProtocol, &sfs_guid, NULL, &n, &h))) return NULL;
    EFI_HANDLE found = NULL;
    for (UINTN i = 0; i < n; i++)
        if (h[i] != own && volume_has(h[i], KERNEL_PATH)) { found = h[i]; break; }
    BS->FreePool(h);
    return found;
}

/* -------------------------------------------------------------- ISO 9660
 *
 * UEFI firmware reads FAT, and that is all it is required to read. The system
 * on a CD lives on an ISO 9660 volume, so the loader reads that itself: the
 * primary volume descriptor at sector 16, then the directory records, which is
 * the whole of what is needed to find two files. Names are compared without
 * case and without the ";1" version suffix, which is how ISO 9660 stores them.
 */

#define ISO_SECTOR 2048

typedef struct {
    EFI_BLOCK_IO_PROTOCOL *bio;
    UINT32 media;
    UINT32 bs;
} isovol_t;

static EFI_STATUS iso_read(isovol_t *v, UINT64 sector, UINTN count, void *buf) {
    /* ISO sectors are 2048 bytes; a device that reports smaller blocks is read
       in its own units */
    UINT64 lba = sector * (ISO_SECTOR / v->bs);
    UINTN  n   = count * ISO_SECTOR;
    return v->bio->ReadBlocks(v->bio, v->media, lba, n, buf);
}

static int name_eq(const UINT8 *rec_name, UINTN len, CHAR16 *want) {
    UINTN wl = str16_len(want);
    UINTN rl = len;
    /* ISO 9660 stores "VMLINUZ.;1": the version suffix and the separator dot a
       name without an extension is padded with are both part of the format,
       not of the name */
    if (rl >= 2 && rec_name[rl - 2] == ';') rl -= 2;
    if (rl >= 1 && rec_name[rl - 1] == '.') rl -= 1;
    if (rl != wl) return 0;
    for (UINTN i = 0; i < rl; i++) {
        UINT8 a = rec_name[i], b = (UINT8)want[i];
        if (a >= 'A' && a <= 'Z') a = (UINT8)(a - 'A' + 'a');
        if (b >= 'A' && b <= 'Z') b = (UINT8)(b - 'A' + 'a');
        if (a != b) return 0;
    }
    return 1;
}

/* walks one directory extent looking for a name; returns its extent and size */
static int iso_lookup(isovol_t *v, UINT32 dir_lba, UINT32 dir_size, CHAR16 *name,
                      UINT32 *out_lba, UINT32 *out_size) {
    UINT8 *buf = NULL;
    UINTN sectors = (dir_size + ISO_SECTOR - 1) / ISO_SECTOR;
    if (EFI_ERR(BS->AllocatePool(EfiLoaderData, sectors * ISO_SECTOR, (void **)&buf)))
        return 0;
    if (EFI_ERR(iso_read(v, dir_lba, sectors, buf))) { BS->FreePool(buf); return 0; }

    int found = 0;
    for (UINTN off = 0; off + 33 < sectors * ISO_SECTOR;) {
        UINT8 *r = buf + off;
        UINT8 rlen = r[0];
        if (rlen == 0) {
            off = ((off / ISO_SECTOR) + 1) * ISO_SECTOR;   /* next sector */
            continue;
        }
        UINT32 lba  = (UINT32)r[2] | ((UINT32)r[3] << 8) | ((UINT32)r[4] << 16) | ((UINT32)r[5] << 24);
        UINT32 size = (UINT32)r[10] | ((UINT32)r[11] << 8) | ((UINT32)r[12] << 16) | ((UINT32)r[13] << 24);
        UINT8  nlen = r[32];
        if (nlen && name_eq(r + 33, nlen, name)) {
            *out_lba = lba;
            *out_size = size;
            found = 1;
            break;
        }
        off += rlen;
    }
    BS->FreePool(buf);
    return found;
}

/* reads /boot/<name> from an ISO 9660 volume */
static EFI_STATUS iso_read_boot_file(isovol_t *v, CHAR16 *name, void **out, UINTN *size,
                                     EFI_MEMORY_TYPE type) {
    UINT8 pvd[ISO_SECTOR];
    if (EFI_ERR(iso_read(v, 16, 1, pvd))) return EFI_NOT_FOUND;
    if (pvd[0] != 1 || pvd[1] != 'C' || pvd[2] != 'D' || pvd[3] != '0' || pvd[4] != '0' ||
        pvd[5] != '1')
        return EFI_NOT_FOUND;

    /* the root directory record sits at offset 156 of the descriptor */
    UINT8 *root = pvd + 156;
    UINT32 rlba  = (UINT32)root[2] | ((UINT32)root[3] << 8) | ((UINT32)root[4] << 16) |
                   ((UINT32)root[5] << 24);
    UINT32 rsize = (UINT32)root[10] | ((UINT32)root[11] << 8) | ((UINT32)root[12] << 16) |
                   ((UINT32)root[13] << 24);

    UINT32 dlba = 0, dsize = 0;
    if (!iso_lookup(v, rlba, rsize, L"boot", &dlba, &dsize)) return EFI_NOT_FOUND;
    UINT32 flba = 0, fsize = 0;
    if (!iso_lookup(v, dlba, dsize, name, &flba, &fsize)) return EFI_NOT_FOUND;
    if (!fsize) return EFI_NOT_FOUND;

    UINTN sectors = (fsize + ISO_SECTOR - 1) / ISO_SECTOR;
    void *buf = NULL;
    if (EFI_ERR(BS->AllocatePool(type, sectors * ISO_SECTOR, &buf))) return EFI_LOAD_ERROR;
    /* read in bounded runs: firmware block drivers dislike one huge request */
    UINTN done = 0;
    while (done < sectors) {
        UINTN run = sectors - done;
        if (run > 2048) run = 2048;                        /* 4 MiB at a time */
        if (EFI_ERR(iso_read(v, flba + done, run, (UINT8 *)buf + done * ISO_SECTOR))) {
            BS->FreePool(buf);
            return EFI_LOAD_ERROR;
        }
        done += run;
    }
    *out = buf;
    *size = fsize;
    return EFI_SUCCESS;
}

/* a block device whose sector 16 is an ISO 9660 primary volume descriptor */
static int iso_probe(EFI_HANDLE h, isovol_t *v) {
    EFI_BLOCK_IO_PROTOCOL *bio = NULL;
    UINT8 pvd[ISO_SECTOR];
    if (EFI_ERR(BS->HandleProtocol(h, &blkio_guid, (void **)&bio))) return 0;
    if (!bio || !bio->Media || !bio->Media->MediaPresent || !bio->Media->BlockSize) return 0;
    /* ISO sectors are read in the device's own units, which must divide them */
    if (bio->Media->BlockSize > ISO_SECTOR || ISO_SECTOR % bio->Media->BlockSize) return 0;
    v->bio = bio; v->media = bio->Media->MediaId; v->bs = bio->Media->BlockSize;
    if (EFI_ERR(iso_read(v, 16, 1, pvd))) return 0;
    return pvd[0] == 1 && pvd[1] == 'C' && pvd[2] == 'D' && pvd[3] == '0' && pvd[4] == '0' &&
           pvd[5] == '1';
}

static EFI_DEVICE_PATH_PROTOCOL *device_path(EFI_HANDLE h) {
    EFI_DEVICE_PATH_PROTOCOL *dp = NULL;
    if (EFI_ERR(BS->HandleProtocol(h, &dp_guid, (void **)&dp))) return NULL;
    return dp;
}

/* whether path a is b's parent: a's nodes are the first nodes of b */
static int dp_is_parent(EFI_DEVICE_PATH_PROTOCOL *a, EFI_DEVICE_PATH_PROTOCOL *b) {
    UINTN la = dp_len(a), lb = dp_len(b);
    if (!la || la >= lb) return 0;
    const UINT8 *x = (const UINT8 *)a, *y = (const UINT8 *)b;
    for (UINTN i = 0; i < la; i++)
        if (x[i] != y[i]) return 0;
    return 1;
}

/* The ISO 9660 medium the loader was started from. The loader runs from a FAT
   image on that medium - El Torito's on a CD, the EFI partition of a USB stick
   written from the ISO - and the firmware describes that image as a child of
   the whole medium, so the medium is the block device whose device path the
   loader's own extends. */
static int find_own_iso(EFI_HANDLE own, isovol_t *v) {
    if (!own) return 0;
    if (iso_probe(own, v)) return 1;                     /* started from the medium itself */
    EFI_DEVICE_PATH_PROTOCOL *odp = device_path(own);
    if (!odp) return 0;
    UINTN n = 0;
    EFI_HANDLE *h = NULL;
    if (EFI_ERR(BS->LocateHandleBuffer(ByProtocol, &blkio_guid, NULL, &n, &h))) return 0;
    int ok = 0;
    for (UINTN i = 0; i < n && !ok; i++) {
        EFI_DEVICE_PATH_PROTOCOL *dp = device_path(h[i]);
        if (dp && dp_is_parent(dp, odp) && iso_probe(h[i], v)) ok = 1;
    }
    BS->FreePool(h);
    return ok;
}

/* any whole medium that carries an ISO 9660 volume */
static int find_any_iso(isovol_t *v) {
    UINTN n = 0;
    EFI_HANDLE *h = NULL;
    EFI_BLOCK_IO_PROTOCOL *bio = NULL;
    if (EFI_ERR(BS->LocateHandleBuffer(ByProtocol, &blkio_guid, NULL, &n, &h))) return 0;
    int ok = 0;
    for (UINTN i = 0; i < n && !ok; i++) {
        if (EFI_ERR(BS->HandleProtocol(h[i], &blkio_guid, (void **)&bio)) || !bio || !bio->Media)
            continue;
        if (bio->Media->LogicalPartition) continue;      /* the whole medium only */
        ok = iso_probe(h[i], v);
    }
    BS->FreePool(h);
    return ok;
}

/* ------------------------------------------------------------- graphics */

static void paint_logo(void) {
    EFI_GRAPHICS_OUTPUT_PROTOCOL *gop = NULL;
    if (EFI_ERR(BS->LocateProtocol(&gop_guid, NULL, (void **)&gop)) || !gop || !gop->Mode)
        return;

    UINT32 w = gop->Mode->Info->HorizontalResolution;
    UINT32 h = gop->Mode->Info->VerticalResolution;

    /* the IFelx ground, so the screen never flashes white or blue */
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL bg;
    bg.Blue = 0x09; bg.Green = 0x09; bg.Red = 0x09; bg.Reserved = 0;
    gop->Blt(gop, &bg, EfiBltVideoFill, 0, 0, 0, 0, w, h, 0);

    if (LOGO_W == 0 || LOGO_H == 0) return;
    UINTN lw = LOGO_W, lh = LOGO_H;
    if (lw > w || lh > h) return;
    UINTN x = (w - lw) / 2, y = (h - lh) / 2;
    gop->Blt(gop, (EFI_GRAPHICS_OUTPUT_BLT_PIXEL *)logo_bgra, EfiBltBufferToVideo,
             0, 0, x, y, lw, lh, 0);
}

/* --------------------------------------------------------------- initrd */

static struct {
    UINT8 vendor[20];      /* vendor media node carrying the Linux initrd GUID */
    UINT8 end[4];
} g_initrd_dp;

static void *g_initrd;
static UINTN g_initrd_size;

static EFI_STATUS EFIAPI initrd_load(EFI_LOAD_FILE2_PROTOCOL *self,
                                     EFI_DEVICE_PATH_PROTOCOL *path, BOOLEAN policy,
                                     UINTN *size, void *buffer) {
    (void)self; (void)path;
    if (policy) return EFI_UNSUPPORTED;      /* boot policy is for boot managers */
    if (!size) return EFI_INVALID_PARAMETER;
    if (!buffer || *size < g_initrd_size) { *size = g_initrd_size; return EFI_BUFFER_TOO_SMALL; }
    copy(buffer, g_initrd, g_initrd_size);
    *size = g_initrd_size;
    return EFI_SUCCESS;
}

static EFI_LOAD_FILE2_PROTOCOL g_lf2 = { initrd_load };

static EFI_STATUS publish_initrd(void *data, UINTN size, EFI_HANDLE *out) {
    g_initrd = data;
    g_initrd_size = size;

    UINT8 *v = g_initrd_dp.vendor;
    v[0] = DP_TYPE_MEDIA;
    v[1] = DP_MEDIA_VENDOR;
    v[2] = 20; v[3] = 0;
    copy(v + 4, &initrd_guid, 16);
    g_initrd_dp.end[0] = DP_TYPE_END;
    g_initrd_dp.end[1] = DP_END_ENTIRE;
    g_initrd_dp.end[2] = 4;
    g_initrd_dp.end[3] = 0;

    EFI_HANDLE h = NULL;
    EFI_STATUS st = BS->InstallProtocolInterface(&h, &dp_guid, EFI_NATIVE_INTERFACE,
                                                 &g_initrd_dp);
    if (EFI_ERR(st)) return st;
    st = BS->InstallProtocolInterface(&h, &lf2_guid, EFI_NATIVE_INTERFACE, &g_lf2);
    if (EFI_ERR(st)) return st;
    *out = h;
    return EFI_SUCCESS;
}

/* An installed system boots from its own root filesystem, so the installer
 * writes \boot\cmdline next to the kernel on the EFI partition; a medium can
 * carry one in /boot/cmdline (the ODE installer does). Plain text, one line;
 * when it is absent the built-in live command line is used. */
static CHAR16 *cmdline_from(void *buf, UINTN size) {
    if (!size || size > (sizeof g_cmdbuf / 2) - 1) return g_cmdline;
    UINT8 *a = buf;
    UINTN n = 0;
    for (UINTN i = 0; i < size; i++) {
        if (a[i] == 0 || a[i] == 10 || a[i] == 13) break;
        g_cmdbuf[n++] = (CHAR16)a[i];
    }
    g_cmdbuf[n] = 0;
    return n ? g_cmdbuf : g_cmdline;
}

static CHAR16 *read_cmdline(EFI_HANDLE vol) {
    void *buf = NULL;
    UINTN size = 0;
    if (EFI_ERR(read_file(vol, CMDLINE_PATH, &buf, &size, EfiLoaderData))) return g_cmdline;
    CHAR16 *cmd = cmdline_from(buf, size);
    BS->FreePool(buf);
    return cmd;
}

static CHAR16 *iso_read_cmdline(isovol_t *v) {
    void *buf = NULL;
    UINTN size = 0;
    if (EFI_ERR(iso_read_boot_file(v, L"cmdline", &buf, &size, EfiLoaderData))) return g_cmdline;
    CHAR16 *cmd = cmdline_from(buf, size);
    BS->FreePool(buf);
    return cmd;
}

/* ----------------------------------------------------------------- main */

EFI_STATUS EFIAPI efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *systab) {
    ST = systab;
    BS = systab->BootServices;

    /* nothing is printed, and nothing may interrupt the load */
    BS->SetWatchdogTimer(0, 0, 0, NULL);
    if (ST->ConOut) {
        ST->ConOut->EnableCursor(ST->ConOut, FALSE);
        ST->ConOut->ClearScreen(ST->ConOut);
    }

    paint_logo();

    void *kernel = NULL, *initrd = NULL;
    UINTN ksize = 0, isize = 0;
    EFI_STATUS st = EFI_NOT_FOUND;

    /* Where the system is, in this order:
     *   1. the volume the loader came from: an installed disk keeps the kernel
     *      on its own EFI partition
     *   2. the medium the loader came from, read as ISO 9660: a CD, or a USB
     *      stick written from the ISO. It comes before every other volume, so
     *      a live or installer medium starts itself even on a computer that
     *      has IFelxOS2 installed - searching the FAT volumes first used to
     *      find the installed system's EFI partition and start that instead
     *   3. any other FAT volume that carries the kernel
     *   4. any other ISO 9660 medium */
    EFI_HANDLE own = loader_device(image);
    EFI_HANDLE vol = NULL;
    isovol_t iv;
    int iso = 0;
    if (own && volume_has(own, KERNEL_PATH))
        vol = own;
    else if (find_own_iso(own, &iv))
        iso = 1;
    else if (!(vol = find_other_volume(own)))
        iso = find_any_iso(&iv);

    if (vol) {
        st = read_file(vol, KERNEL_PATH, &kernel, &ksize, EfiLoaderCode);
        if (!EFI_ERR(st)) st = read_file(vol, INITRD_PATH, &initrd, &isize, EfiLoaderData);
        if (EFI_ERR(st)) {
            if (kernel) BS->FreePool(kernel);
            kernel = NULL;
            vol = NULL;
            iso = find_any_iso(&iv);
        }
    }
    CHAR16 *cmd = g_cmdline;
    if (vol) {
        cmd = read_cmdline(vol);
    } else {
        if (!iso) return EFI_NOT_FOUND;
        st = iso_read_boot_file(&iv, L"vmlinuz", &kernel, &ksize, EfiLoaderCode);
        if (EFI_ERR(st)) return st;
        st = iso_read_boot_file(&iv, L"initrd.img", &initrd, &isize, EfiLoaderData);
        if (EFI_ERR(st)) return st;
        cmd = iso_read_cmdline(&iv);
    }

    EFI_HANDLE initrd_handle = NULL;
    st = publish_initrd(initrd, isize, &initrd_handle);
    if (EFI_ERR(st)) return st;

    EFI_DEVICE_PATH_PROTOCOL *kdp = vol ? file_device_path(vol, KERNEL_PATH) : NULL;
    EFI_HANDLE kimg = NULL;
    st = BS->LoadImage(FALSE, image, kdp, kernel, ksize, &kimg);
    if (EFI_ERR(st)) return st;

    EFI_LOADED_IMAGE_PROTOCOL *kli = NULL;
    st = BS->HandleProtocol(kimg, &li_guid, (void **)&kli);
    if (EFI_ERR(st)) return st;
    kli->LoadOptions = cmd;
    kli->LoadOptionsSize = (UINT32)((str16_len(cmd) + 1) * 2);

    UINTN exitsz = 0;
    CHAR16 *exitdata = NULL;
    st = BS->StartImage(kimg, &exitsz, &exitdata);

    /* the kernel only returns when it failed to take over */
    if (initrd_handle) {
        BS->UninstallProtocolInterface(initrd_handle, &lf2_guid, &g_lf2);
        BS->UninstallProtocolInterface(initrd_handle, &dp_guid, &g_initrd_dp);
    }
    return st;
}
