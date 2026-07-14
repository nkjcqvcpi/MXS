from mxs import X4M200
from mxs.constants import SystemInfoCode

with X4M200() as device:
    for code in SystemInfoCode:
        try:
            print(code.name, device.module.get_system_info(code))
        except Exception as error:
            print(code.name, type(error).__name__, error)
