# Local Protocol Source Map

This project independently implements the XeThru protocol in Python. The files
below are read-only sources under `./Legacy-SW`.

| Python feature | Legacy-SW reference |
|---|---|
| Classic MCP encoder and XOR checksum | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `packet_start`, `process_byte`, `packet_end`, `isSpecialByte` |
| Incremental classic and mixed-stream decoder | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `parseData`, `handleSingleByte`, `handleSpecialBytes`, `checkCrcAndSend` |
| No-escape marker, length, and unused checksum field | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createDataFloatCommandNoEscape`; `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `handleSingleByte` |
| Framing bytes and response/data enums | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/xtserial_definitions.h`: `serial_flag_byte_t`, `serial_protocol_response_t`, `serial_protocol_response_datatype_t` |
| Sensor modes and baud rates | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/xtid.h`: `XTID_SM_*`, `XTID_BAUDRATE_*`; `xtserial_definitions.h`: `sensor_mode_t` |
| Content IDs | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/xtid.h`: `XTS_ID_BASEBAND_IQ`, `XTS_ID_BASEBAND_AMPLITUDE_PHASE`, `XTS_ID_SLEEP_STATUS`; `xtserial_definitions.h`: `eContentID` |
| Sensor-mode command | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `createSetSensorModeCommand` |
| Ping and pong | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `createPingCommand`; `protocol_host_parser.c`: `parse_pong`; target `protocol_target.c`: `createPongCommand` |
| Baud-rate command | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `createSetBaudRateCommand`; `examples/generic/src/main.cpp`: baud transition sequence |
| X4 parameter IDs and setters | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/xtserial_definitions.h`: `serial_protocol_command_x4driver_id_t`; `protocol.c`: `createX4DriverSet*Command` |
| X4 driver initialization | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c`: `createX4DriverInitCommand` |
| ACK, ERROR, PONG, and REPLY parsing | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol_host_parser.c`: `parse_ack`, `parse_error`, `parse_pong`, `parse_reply` |
| Datatype-aware REPLY producers | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createReplyIntCommand`, `createReplyByteCommand`, `createReplyStringnCommand`, `createReplyFloatCommand` |
| X4M200 application commands | `XEP/xtXEP_source-3/xtSerial/src/protocol.c`: `createLoadProfileCommand`, `createGetDetectionZoneCommand`, `createGetDetectionZoneLimitsCommand`, output-control and noisemap builders |
| X4Driver getters and register operations | `XEP/xtXEP_source-3/xtSerial/src/protocol.c`: `createX4DriverGet*Command`, `createX4DriverReadFromSpiRegisterCommand`, `createX4DriverWriteToSpiRegisterCommand` |
| Filesystem commands | `XEP/xtXEP_source-3/xtSerial/src/protocol.c`: `createSearchForFileTypeCommand` through `createFormatFilesystemCommand`; callbacks in `xtXEP/src/XEPA/xep_application_mcp_callbacks.c` |
| GPIO commands | `XEP/xtXEP_source-3/xtSerial/src/protocol.c`: `createSetIOPinControlCommand`, `createGetIOPinControlCommand`, `createSetIOPinValueCommand`, `createGetIOPinValueCommand` |
| DataFloat classic layout | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createDataFloatCommand`; host `protocol_host_parser.c`: `parse_data_float` |
| DataFloat no-escape layout | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createDataFloatCommandNoEscape` |
| Baseband IQ APPDATA layout | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createAppdataBasebandIQCommand`, `createAppdataBasebandIQCommandNoEscape`; host `protocol_host_parser.c`: `parse_baseband_iq` |
| SleepStatus layout | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: `createAppdataSleepCommand`; host `protocol_host_parser.c`: `parse_sleep_status` |
| Respiration and vital-sign layouts | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: respiration, moving-list, detection-list, normalized-list, and vital-sign builders |
| Pulse-Doppler and noisemap layouts | `XEP/xtXEP_source-3/xtSerial/src/protocol_target.c`: float builders and `_createAppdataPDMatCommandNoEscape`, `_createAppdataPDMatByteCommandNoEscape` |
| Legacy recording field order | `Legacy-Documentation/Application-Notes/XTAN-05_XeThruFileFormats-v2.pdf`, sections 2.1-2.2, pages 4-5 |
| Raw-data initialization defaults and order | `ModuleConnector/Latest_MC_examples/PYTHON/xt_modules_plot_record_playback_radar_raw_data_message_2D.py`: `x4_par_settings`, `configure_x4` |
| Single ordered serial reader and command serialization | `MCPWrapper/mcp_wrapper_1.3.1/examples/generic/src/main.cpp`: `readThreadMethod`, wrapper command methods; `LinuxModuleIo.cpp`: `read`, `write`, `setBaudrate` |
| Wrapper response routing and 2 s timeout | `MCPWrapper/mcp_wrapper_1.3.1/src/mcp_wrapper.c`: `mcpw_init`, `mcpw_mcp_handle_protocol_packet`, ACK/ERROR/REPLY callbacks |
| Public wrapper behavior used for cross-checking | `MCPWrapper/mcp_wrapper_1.3.1/include/mcp_wrapper.h` |
| Reused license text | `MCPWrapper/mcp_wrapper_1.3.1/LICENSE.md` |
