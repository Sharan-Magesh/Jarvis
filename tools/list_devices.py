import sounddevice as sd

print(sd.query_devices())          # prints all devices
print("Default device:", sd.default.device) 
