# Hardware safety

Safe default tests may read system information, configuration, existing file metadata, raw RF, and IQ. Recoverable setter tests must read the old value, write one documented alternative, verify it, restore the old value, and verify restoration.

The following operations are disabled unless their exact gate is `1`:

| Operation | Gate |
|---|---|
| Bootloader entry | `MXS_ENABLE_BOOTLOADER` |
| Factory reset | `MXS_ENABLE_FACTORY_RESET` |
| Filesystem mutation | `MXS_ENABLE_UNSAFE` |
| Filesystem format | `MXS_ENABLE_FILESYSTEM_FORMAT` |
| Raw register write | `MXS_ENABLE_RAW_REGISTER_WRITES` |
| Frame injection | `MXS_ENABLE_FRAME_INJECTION` |
| Manufacturing test | `MXS_ENABLE_MANUFACTURING_TESTS` |
| Noisemap flash store or deletion | `MXS_ENABLE_NOISEMAP_FLASH_WRITE` |

MXS checks the device-reported sensor mode after checking a gate. Filesystem and noisemap mutations, formatting, bootloader entry, factory reset, and manufacturing tests require STOP. Frame injection and raw register writes permit STOP or MANUAL because their local XEP workflows define MANUAL use. Do not guess register addresses, test codes, bootloader keys, or safe alternative values. Default hardware tests never store or delete a noisemap, mutate files, enter a bootloader, reset factory state, inject frames, or write registers.
