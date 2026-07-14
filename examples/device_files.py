from mxs import X4M200

with X4M200() as device:
    for identifier in device.filesystem.find_all_files():
        print(
            identifier,
            device.filesystem.get_file_length(identifier.file_type, identifier.identifier),
        )
