import sounddevice as sd, soundfile as sf

# Replace with your mic index later—leave None for now
sd.default.device = 7
sr = 48000               # standard sample rate

print("Recording 3 seconds of audio…")
audio = sd.rec(3 * sr, samplerate=sr, channels=1, dtype='int16')
sd.wait()
sf.write('mic_test.wav', audio, sr)
print("Wrote mic_test.wav – play this file back now.")
