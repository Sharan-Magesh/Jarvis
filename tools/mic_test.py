import sounddevice as sd
import numpy as np

duration = 3  # seconds
sr = 16000    # sample rate

print(f"Recording {duration}s of audio...")
audio = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype='int16')
sd.wait()
print("Recording complete. RMS volume:", np.sqrt(np.mean(audio**2)))
