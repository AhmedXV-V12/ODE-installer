/* Minimal UEFI definitions, written for IFelxBoot.
 *
 * Nothing here comes from gnu-efi or EDK2: the structures below are laid out
 * from the UEFI specification, in the order the specification gives, because a
 * boot loader that claims to be written from scratch should not carry someone
 * else's headers. Only what IFelxBoot actually calls is declared. */

#ifndef IFELX_EFI_H
#define IFELX_EFI_H

typedef unsigned char      UINT8;
typedef unsigned short     UINT16;
typedef unsigned int       UINT32;
typedef unsigned long long UINT64;
typedef signed long long   INT64;
typedef UINT64             UINTN;
typedef UINT64             EFI_STATUS;
typedef void              *EFI_HANDLE;
typedef void              *EFI_EVENT;
typedef UINT16             CHAR16;
typedef unsigned char      BOOLEAN;
typedef UINT64             EFI_PHYSICAL_ADDRESS;

#define NULL  ((void *)0)
#define TRUE  1
#define FALSE 0

#define EFIAPI __attribute__((ms_abi))

#define EFI_SUCCESS            0
#define EFI_LOAD_ERROR         0x8000000000000001ULL
#define EFI_INVALID_PARAMETER  0x8000000000000002ULL
#define EFI_UNSUPPORTED        0x8000000000000003ULL
#define EFI_BUFFER_TOO_SMALL   0x8000000000000005ULL
#define EFI_NOT_FOUND          0x800000000000000EULL
#define EFI_ERR(s)             (((s) & 0x8000000000000000ULL) != 0)

typedef struct { UINT32 Data1; UINT16 Data2; UINT16 Data3; UINT8 Data4[8]; } EFI_GUID;

typedef struct {
    UINT64 Signature;
    UINT32 Revision;
    UINT32 HeaderSize;
    UINT32 CRC32;
    UINT32 Reserved;
} EFI_TABLE_HEADER;

/* ---------------------------------------------------------- text output */
struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL;
typedef EFI_STATUS (EFIAPI *EFI_TEXT_RESET)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, BOOLEAN);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_STRING)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, CHAR16 *);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_TEST)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, CHAR16 *);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_QUERY)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, UINTN, UINTN *, UINTN *);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_SET_MODE)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, UINTN);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_SET_ATTR)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, UINTN);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_CLEAR)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_SET_CURSOR)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, UINTN, UINTN);
typedef EFI_STATUS (EFIAPI *EFI_TEXT_ENABLE_CURSOR)(struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, BOOLEAN);

typedef struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL {
    EFI_TEXT_RESET         Reset;
    EFI_TEXT_STRING        OutputString;
    EFI_TEXT_TEST          TestString;
    EFI_TEXT_QUERY         QueryMode;
    EFI_TEXT_SET_MODE      SetMode;
    EFI_TEXT_SET_ATTR      SetAttribute;
    EFI_TEXT_CLEAR         ClearScreen;
    EFI_TEXT_SET_CURSOR    SetCursorPosition;
    EFI_TEXT_ENABLE_CURSOR EnableCursor;
    void                  *Mode;
} EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL;

/* --------------------------------------------------------- device paths */
typedef struct {
    UINT8 Type;
    UINT8 SubType;
    UINT8 Length[2];
} EFI_DEVICE_PATH_PROTOCOL;

#define DP_TYPE_MEDIA   0x04
#define DP_MEDIA_VENDOR 0x03
#define DP_MEDIA_FILE   0x04
#define DP_TYPE_END     0x7F
#define DP_END_ENTIRE   0xFF

/* ------------------------------------------------------- boot services */
typedef enum { AllocateAnyPages, AllocateMaxAddress, AllocateAddress } EFI_ALLOCATE_TYPE;
typedef enum {
    EfiReservedMemoryType, EfiLoaderCode, EfiLoaderData, EfiBootServicesCode,
    EfiBootServicesData, EfiRuntimeServicesCode, EfiRuntimeServicesData,
    EfiConventionalMemory, EfiUnusableMemory, EfiACPIReclaimMemory,
    EfiACPIMemoryNVS, EfiMemoryMappedIO, EfiMemoryMappedIOPortSpace,
    EfiPalCode, EfiPersistentMemory, EfiMaxMemoryType
} EFI_MEMORY_TYPE;
typedef enum { AllHandles, ByRegisterNotify, ByProtocol } EFI_LOCATE_SEARCH_TYPE;
typedef enum { EFI_NATIVE_INTERFACE } EFI_INTERFACE_TYPE;

typedef struct {
    EFI_TABLE_HEADER Hdr;

    /* task priority */
    void *RaiseTPL;
    void *RestoreTPL;

    /* memory */
    EFI_STATUS (EFIAPI *AllocatePages)(EFI_ALLOCATE_TYPE, EFI_MEMORY_TYPE, UINTN, EFI_PHYSICAL_ADDRESS *);
    EFI_STATUS (EFIAPI *FreePages)(EFI_PHYSICAL_ADDRESS, UINTN);
    EFI_STATUS (EFIAPI *GetMemoryMap)(UINTN *, void *, UINTN *, UINTN *, UINT32 *);
    EFI_STATUS (EFIAPI *AllocatePool)(EFI_MEMORY_TYPE, UINTN, void **);
    EFI_STATUS (EFIAPI *FreePool)(void *);

    /* events and timers */
    void *CreateEvent;
    void *SetTimer;
    EFI_STATUS (EFIAPI *WaitForEvent)(UINTN, EFI_EVENT *, UINTN *);
    void *SignalEvent;
    void *CloseEvent;
    void *CheckEvent;

    /* protocol handlers */
    EFI_STATUS (EFIAPI *InstallProtocolInterface)(EFI_HANDLE *, EFI_GUID *, EFI_INTERFACE_TYPE, void *);
    void *ReinstallProtocolInterface;
    EFI_STATUS (EFIAPI *UninstallProtocolInterface)(EFI_HANDLE, EFI_GUID *, void *);
    EFI_STATUS (EFIAPI *HandleProtocol)(EFI_HANDLE, EFI_GUID *, void **);
    void *Reserved;
    void *RegisterProtocolNotify;
    EFI_STATUS (EFIAPI *LocateHandle)(EFI_LOCATE_SEARCH_TYPE, EFI_GUID *, void *, UINTN *, EFI_HANDLE *);
    EFI_STATUS (EFIAPI *LocateDevicePath)(EFI_GUID *, EFI_DEVICE_PATH_PROTOCOL **, EFI_HANDLE *);
    void *InstallConfigurationTable;

    /* images */
    EFI_STATUS (EFIAPI *LoadImage)(BOOLEAN, EFI_HANDLE, EFI_DEVICE_PATH_PROTOCOL *, void *, UINTN, EFI_HANDLE *);
    EFI_STATUS (EFIAPI *StartImage)(EFI_HANDLE, UINTN *, CHAR16 **);
    EFI_STATUS (EFIAPI *Exit)(EFI_HANDLE, EFI_STATUS, UINTN, CHAR16 *);
    EFI_STATUS (EFIAPI *UnloadImage)(EFI_HANDLE);
    EFI_STATUS (EFIAPI *ExitBootServices)(EFI_HANDLE, UINTN);

    /* misc */
    void *GetNextMonotonicCount;
    EFI_STATUS (EFIAPI *Stall)(UINTN);
    EFI_STATUS (EFIAPI *SetWatchdogTimer)(UINTN, UINT64, UINTN, CHAR16 *);

    /* driver support */
    void *ConnectController;
    void *DisconnectController;

    /* open and close protocol */
    EFI_STATUS (EFIAPI *OpenProtocol)(EFI_HANDLE, EFI_GUID *, void **, EFI_HANDLE, EFI_HANDLE, UINT32);
    void *CloseProtocol;
    void *OpenProtocolInformation;

    /* library */
    void *ProtocolsPerHandle;
    EFI_STATUS (EFIAPI *LocateHandleBuffer)(EFI_LOCATE_SEARCH_TYPE, EFI_GUID *, void *, UINTN *, EFI_HANDLE **);
    EFI_STATUS (EFIAPI *LocateProtocol)(EFI_GUID *, void *, void **);
    void *InstallMultipleProtocolInterfaces;
    void *UninstallMultipleProtocolInterfaces;

    /* crc */
    void *CalculateCrc32;

    /* misc */
    void (EFIAPI *CopyMem)(void *, void *, UINTN);
    void (EFIAPI *SetMem)(void *, UINTN, UINT8);
    void *CreateEventEx;
} EFI_BOOT_SERVICES;

typedef struct {
    EFI_TABLE_HEADER Hdr;
    CHAR16 *FirmwareVendor;
    UINT32  FirmwareRevision;
    EFI_HANDLE ConsoleInHandle;
    void      *ConIn;
    EFI_HANDLE ConsoleOutHandle;
    EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *ConOut;
    EFI_HANDLE StandardErrorHandle;
    EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *StdErr;
    void   *RuntimeServices;
    EFI_BOOT_SERVICES *BootServices;
    UINTN   NumberOfTableEntries;
    void   *ConfigurationTable;
} EFI_SYSTEM_TABLE;

/* ------------------------------------------------------------ protocols */
#define EFI_LOADED_IMAGE_PROTOCOL_GUID \
    {0x5B1B31A1,0x9562,0x11d2,{0x8E,0x3F,0x00,0xA0,0xC9,0x69,0x72,0x3B}}
#define EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID \
    {0x0964e5b22,0x6459,0x11d2,{0x8e,0x39,0x00,0xa0,0xc9,0x69,0x72,0x3b}}
#define EFI_FILE_INFO_GUID \
    {0x09576e92,0x6d3f,0x11d2,{0x8e,0x39,0x00,0xa0,0xc9,0x69,0x72,0x3b}}
#define EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID \
    {0x9042a9de,0x23dc,0x4a38,{0x96,0xfb,0x7a,0xde,0xd0,0x80,0x51,0x6a}}
#define EFI_DEVICE_PATH_PROTOCOL_GUID \
    {0x09576e91,0x6d3f,0x11d2,{0x8e,0x39,0x00,0xa0,0xc9,0x69,0x72,0x3b}}
#define EFI_LOAD_FILE2_PROTOCOL_GUID \
    {0x4006c0c1,0xfcb3,0x403e,{0x99,0x6d,0x4a,0x6c,0x87,0x24,0xe0,0x6d}}
/* the device path Linux looks for when it asks for an initrd */
#define LINUX_EFI_INITRD_MEDIA_GUID \
    {0x5568e427,0x68fc,0x4f3d,{0xac,0x74,0xca,0x55,0x52,0x31,0xcc,0x68}}

typedef struct {
    UINT32 Revision;
    EFI_HANDLE ParentHandle;
    EFI_SYSTEM_TABLE *SystemTable;
    EFI_HANDLE DeviceHandle;
    EFI_DEVICE_PATH_PROTOCOL *FilePath;
    void *Reserved;
    UINT32 LoadOptionsSize;
    void  *LoadOptions;
    void  *ImageBase;
    UINT64 ImageSize;
    EFI_MEMORY_TYPE ImageCodeType;
    EFI_MEMORY_TYPE ImageDataType;
    void *Unload;
} EFI_LOADED_IMAGE_PROTOCOL;

struct _EFI_FILE_PROTOCOL;
typedef struct _EFI_FILE_PROTOCOL {
    UINT64 Revision;
    EFI_STATUS (EFIAPI *Open)(struct _EFI_FILE_PROTOCOL *, struct _EFI_FILE_PROTOCOL **, CHAR16 *, UINT64, UINT64);
    EFI_STATUS (EFIAPI *Close)(struct _EFI_FILE_PROTOCOL *);
    EFI_STATUS (EFIAPI *Delete)(struct _EFI_FILE_PROTOCOL *);
    EFI_STATUS (EFIAPI *Read)(struct _EFI_FILE_PROTOCOL *, UINTN *, void *);
    EFI_STATUS (EFIAPI *Write)(struct _EFI_FILE_PROTOCOL *, UINTN *, void *);
    EFI_STATUS (EFIAPI *GetPosition)(struct _EFI_FILE_PROTOCOL *, UINT64 *);
    EFI_STATUS (EFIAPI *SetPosition)(struct _EFI_FILE_PROTOCOL *, UINT64);
    EFI_STATUS (EFIAPI *GetInfo)(struct _EFI_FILE_PROTOCOL *, EFI_GUID *, UINTN *, void *);
    EFI_STATUS (EFIAPI *SetInfo)(struct _EFI_FILE_PROTOCOL *, EFI_GUID *, UINTN, void *);
    EFI_STATUS (EFIAPI *Flush)(struct _EFI_FILE_PROTOCOL *);
} EFI_FILE_PROTOCOL;

typedef struct {
    UINT64 Revision;
    EFI_STATUS (EFIAPI *OpenVolume)(void *, EFI_FILE_PROTOCOL **);
} EFI_SIMPLE_FILE_SYSTEM_PROTOCOL;

#define EFI_FILE_MODE_READ 0x0000000000000001ULL

typedef struct {
    UINT32 RedMask, GreenMask, BlueMask, ReservedMask;
} EFI_PIXEL_BITMASK;

typedef struct {
    UINT32 Version;
    UINT32 HorizontalResolution;
    UINT32 VerticalResolution;
    UINT32 PixelFormat;
    EFI_PIXEL_BITMASK PixelInformation;
    UINT32 PixelsPerScanLine;
} EFI_GRAPHICS_OUTPUT_MODE_INFORMATION;

typedef struct {
    UINT32 MaxMode;
    UINT32 Mode;
    EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *Info;
    UINTN  SizeOfInfo;
    EFI_PHYSICAL_ADDRESS FrameBufferBase;
    UINTN  FrameBufferSize;
} EFI_GRAPHICS_OUTPUT_PROTOCOL_MODE;

typedef struct { UINT8 Blue, Green, Red, Reserved; } EFI_GRAPHICS_OUTPUT_BLT_PIXEL;
typedef enum { EfiBltVideoFill, EfiBltVideoToBltBuffer, EfiBltBufferToVideo,
               EfiBltVideoToVideo } EFI_GRAPHICS_OUTPUT_BLT_OPERATION;

typedef struct _EFI_GRAPHICS_OUTPUT_PROTOCOL {
    EFI_STATUS (EFIAPI *QueryMode)(struct _EFI_GRAPHICS_OUTPUT_PROTOCOL *, UINT32, UINTN *,
                                   EFI_GRAPHICS_OUTPUT_MODE_INFORMATION **);
    EFI_STATUS (EFIAPI *SetMode)(struct _EFI_GRAPHICS_OUTPUT_PROTOCOL *, UINT32);
    EFI_STATUS (EFIAPI *Blt)(struct _EFI_GRAPHICS_OUTPUT_PROTOCOL *, EFI_GRAPHICS_OUTPUT_BLT_PIXEL *,
                             EFI_GRAPHICS_OUTPUT_BLT_OPERATION, UINTN, UINTN, UINTN, UINTN,
                             UINTN, UINTN, UINTN);
    EFI_GRAPHICS_OUTPUT_PROTOCOL_MODE *Mode;
} EFI_GRAPHICS_OUTPUT_PROTOCOL;

#define EFI_BLOCK_IO_PROTOCOL_GUID \
    {0x964e5b21,0x6459,0x11d2,{0x8e,0x39,0x00,0xa0,0xc9,0x69,0x72,0x3b}}

typedef struct {
    UINT32  MediaId;
    BOOLEAN RemovableMedia;
    BOOLEAN MediaPresent;
    BOOLEAN LogicalPartition;
    BOOLEAN ReadOnly;
    BOOLEAN WriteCaching;
    UINT32  BlockSize;
    UINT32  IoAlign;
    UINT64  LastBlock;
} EFI_BLOCK_IO_MEDIA;

struct _EFI_BLOCK_IO_PROTOCOL;
typedef struct _EFI_BLOCK_IO_PROTOCOL {
    UINT64 Revision;
    EFI_BLOCK_IO_MEDIA *Media;
    EFI_STATUS (EFIAPI *Reset)(struct _EFI_BLOCK_IO_PROTOCOL *, BOOLEAN);
    EFI_STATUS (EFIAPI *ReadBlocks)(struct _EFI_BLOCK_IO_PROTOCOL *, UINT32, UINT64, UINTN, void *);
    EFI_STATUS (EFIAPI *WriteBlocks)(struct _EFI_BLOCK_IO_PROTOCOL *, UINT32, UINT64, UINTN, void *);
    EFI_STATUS (EFIAPI *FlushBlocks)(struct _EFI_BLOCK_IO_PROTOCOL *);
} EFI_BLOCK_IO_PROTOCOL;

typedef struct _EFI_LOAD_FILE2_PROTOCOL {
    EFI_STATUS (EFIAPI *LoadFile)(struct _EFI_LOAD_FILE2_PROTOCOL *, EFI_DEVICE_PATH_PROTOCOL *,
                                  BOOLEAN, UINTN *, void *);
} EFI_LOAD_FILE2_PROTOCOL;

typedef struct {
    UINT64 Size;
    UINT64 FileSize;
    UINT64 PhysicalSize;
    UINT8  CreateTime[16];
    UINT8  LastAccessTime[16];
    UINT8  ModificationTime[16];
    UINT64 Attribute;
    CHAR16 FileName[1];
} EFI_FILE_INFO;

#endif
