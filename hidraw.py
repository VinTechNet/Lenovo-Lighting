"""Minimal Windows HID access via ctypes (no third-party deps).

Enough of the Win32 HID API to enumerate interfaces and push feature /
output reports at a keyboard lighting controller.
"""

import ctypes
from ctypes import wintypes

setupapi = ctypes.WinDLL("setupapi")
hid = ctypes.WinDLL("hid")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 1)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_ulong),
        ("VendorID", ctypes.c_ushort),
        ("ProductID", ctypes.c_ushort),
        ("VersionNumber", ctypes.c_ushort),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


PHIDP_PREPARSED_DATA = ctypes.c_void_p

setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]

hid.HidD_GetHidGuid.restype = None
hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.restype = wintypes.BOOL
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
hid.HidD_GetPreparsedData.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(PHIDP_PREPARSED_DATA),
]
hid.HidD_FreePreparsedData.restype = wintypes.BOOL
hid.HidD_FreePreparsedData.argtypes = [PHIDP_PREPARSED_DATA]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidP_GetCaps.argtypes = [PHIDP_PREPARSED_DATA, ctypes.POINTER(HIDP_CAPS)]
hid.HidD_SetFeature.restype = wintypes.BOOL
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
hid.HidD_SetOutputReport.restype = wintypes.BOOL
hid.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]
for _fn in (hid.HidD_GetProductString, hid.HidD_GetManufacturerString):
    _fn.restype = wintypes.BOOL
    _fn.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_ulong]


def _hid_guid():
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    return g


def _open(path, access=GENERIC_READ | GENERIC_WRITE, share=None):
    if share is None:
        share = FILE_SHARE_READ | FILE_SHARE_WRITE
    return kernel32.CreateFileW(
        path,
        access,
        share,
        None,
        OPEN_EXISTING,
        0,
        None,
    )


def enumerate_devices():
    """Yield dicts describing every present HID interface collection."""
    guid = _hid_guid()
    dev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if dev_info == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    results = []
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                dev_info, None, ctypes.byref(guid), index, ctypes.byref(iface)
            ):
                break
            index += 1

            required = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info, ctypes.byref(iface), None, 0, ctypes.byref(required), None
            )
            if not required.value:
                continue

            buf = ctypes.create_string_buffer(required.value)
            detail = ctypes.cast(
                buf, ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W)
            )
            # cbSize is the size of the fixed part only, not the whole buffer.
            detail.contents.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info,
                ctypes.byref(iface),
                detail,
                required.value,
                ctypes.byref(required),
                None,
            ):
                continue

            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            info = _probe(path)
            if info:
                results.append(info)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)
    return results


def _probe(path):
    # Ask for no access: lets us read metadata even on exclusively-held devices.
    handle = _open(path, 0)
    if handle == INVALID_HANDLE_VALUE:
        return None
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
            return None

        preparsed = ctypes.c_void_p()
        if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return None
        try:
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != 0x00110000:
                return None
        finally:
            hid.HidD_FreePreparsedData(preparsed)

        return {
            "path": path,
            "vid": attrs.VendorID,
            "pid": attrs.ProductID,
            "version": attrs.VersionNumber,
            "usage_page": caps.UsagePage,
            "usage": caps.Usage,
            "input_len": caps.InputReportByteLength,
            "output_len": caps.OutputReportByteLength,
            "feature_len": caps.FeatureReportByteLength,
            "product": _string(hid.HidD_GetProductString, handle),
            "manufacturer": _string(hid.HidD_GetManufacturerString, handle),
        }
    finally:
        kernel32.CloseHandle(handle)


def _string(fn, handle):
    buf = ctypes.create_unicode_buffer(256)
    if fn(handle, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", ctypes.c_ushort),
        ("ReportID", ctypes.c_ubyte),
        ("IsAlias", ctypes.c_ubyte),
        ("BitField", ctypes.c_ushort),
        ("LinkCollection", ctypes.c_ushort),
        ("LinkUsage", ctypes.c_ushort),
        ("LinkUsagePage", ctypes.c_ushort),
        ("IsRange", ctypes.c_ubyte),
        ("IsStringRange", ctypes.c_ubyte),
        ("IsDesignatorRange", ctypes.c_ubyte),
        ("IsAbsolute", ctypes.c_ubyte),
        ("HasNull", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("BitSize", ctypes.c_ushort),
        ("ReportCount", ctypes.c_ushort),
        ("Reserved2", ctypes.c_ushort * 5),
        ("UnitsExp", ctypes.c_ulong),
        ("Units", ctypes.c_ulong),
        ("LogicalMin", ctypes.c_long),
        ("LogicalMax", ctypes.c_long),
        ("PhysicalMin", ctypes.c_long),
        ("PhysicalMax", ctypes.c_long),
        ("UsageMin", ctypes.c_ushort),
        ("UsageMax", ctypes.c_ushort),
        ("StringMin", ctypes.c_ushort),
        ("StringMax", ctypes.c_ushort),
        ("DesignatorMin", ctypes.c_ushort),
        ("DesignatorMax", ctypes.c_ushort),
        ("DataIndexMin", ctypes.c_ushort),
        ("DataIndexMax", ctypes.c_ushort),
    ]


assert ctypes.sizeof(HIDP_VALUE_CAPS) == 72, ctypes.sizeof(HIDP_VALUE_CAPS)


HIDP_INPUT, HIDP_OUTPUT, HIDP_FEATURE = 0, 1, 2

hid.HidP_GetValueCaps.restype = ctypes.c_long
hid.HidP_GetValueCaps.argtypes = [
    ctypes.c_int, ctypes.POINTER(HIDP_VALUE_CAPS), ctypes.POINTER(ctypes.c_ushort),
    PHIDP_PREPARSED_DATA,
]


def value_caps(path, report_type=HIDP_FEATURE):
    """Return the declared value fields for a report type, in descriptor order."""
    handle = _open(path, 0)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        preparsed = PHIDP_PREPARSED_DATA()
        if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            caps = HIDP_CAPS()
            hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
            n = {
                HIDP_INPUT: caps.NumberInputValueCaps,
                HIDP_OUTPUT: caps.NumberOutputValueCaps,
                HIDP_FEATURE: caps.NumberFeatureValueCaps,
            }[report_type]
            arr = (HIDP_VALUE_CAPS * n)()
            length = ctypes.c_ushort(n)
            status = hid.HidP_GetValueCaps(
                report_type, arr, ctypes.byref(length), preparsed
            )
            if status != 0x00110000:
                raise OSError(f"HidP_GetValueCaps failed: 0x{status & 0xFFFFFFFF:08X}")
            return [
                {
                    "report_id": c.ReportID,
                    "usage_page": c.UsagePage,
                    "usage_min": c.UsageMin,
                    "usage_max": c.UsageMax if c.IsRange else c.UsageMin,
                    "is_range": bool(c.IsRange),
                    "bit_size": c.BitSize,
                    "report_count": c.ReportCount,
                    "logical_min": c.LogicalMin,
                    "logical_max": c.LogicalMax,
                }
                for c in arr[: length.value]
            ]
        finally:
            hid.HidD_FreePreparsedData(preparsed)
    finally:
        kernel32.CloseHandle(handle)


class HidDevice:
    """An open handle to one HID collection."""

    def __init__(self, path, exclusive=False):
        self.path = path
        self.exclusive = False
        if exclusive:
            # Share mode 0 locks every other process out of the device.
            self.handle = _open(path, GENERIC_READ | GENERIC_WRITE, share=0)
            if self.handle != INVALID_HANDLE_VALUE:
                self.exclusive = True
                return
        self.handle = _open(path)
        if self.handle == INVALID_HANDLE_VALUE:
            # Retry write-only: some lighting collections refuse read access.
            self.handle = _open(path, GENERIC_WRITE)
        if self.handle == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())

    def set_feature(self, data: bytes) -> bool:
        buf = ctypes.create_string_buffer(data, len(data))
        return bool(hid.HidD_SetFeature(self.handle, buf, len(data)))

    def get_feature(self, report_id: int, length: int) -> bytes:
        buf = ctypes.create_string_buffer(length)
        buf[0] = bytes([report_id])
        if not hid.HidD_GetFeature(self.handle, buf, length):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw

    def write(self, data: bytes) -> bool:
        written = wintypes.DWORD(0)
        return bool(
            kernel32.WriteFile(
                self.handle, data, len(data), ctypes.byref(written), None
            )
        )

    def close(self):
        if self.handle and self.handle != INVALID_HANDLE_VALUE:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
