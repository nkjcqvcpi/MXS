from mxs import X4M200
from mxs.constants import OutputControl, OutputFeature, ProfileId, SensorMode

with X4M200() as device:
    device.profile.load_profile(ProfileId.SLEEP)
    device.outputs.set_output_control(OutputFeature.SLEEP, OutputControl.ENABLE)
    device.profile.set_sensor_mode(SensorMode.RUN)
    print(device.messages.sleep.read(timeout=5))
