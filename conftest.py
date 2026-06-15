# conftest.py — pytest bootstrap
# Stubs out Windows-only and audio packages so tests run cleanly on Linux CI.
import sys
import types

_STUBS = [
    'pyaudio', 'pyttsx3', 'pvporcupine', 'sounddevice', 'soundfile',
    'pygame', 'pyperclip', 'pyautogui', 'PyAutoGUI',
    'win32api', 'win32con', 'win32com', 'pywintypes',
    'cv2', 'mss',
]

for _mod in _STUBS:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# numpy needs to be real for sqlite/memory tests
# speech_recognition needs Microphone stub
import unittest.mock as _mock
if 'speech_recognition' not in sys.modules:
    sr = types.ModuleType('speech_recognition')
    sr.Recognizer = _mock.MagicMock
    sr.Microphone = _mock.MagicMock
    sr.WaitTimeoutError = Exception
    sr.UnknownValueError = Exception
    sys.modules['speech_recognition'] = sr
