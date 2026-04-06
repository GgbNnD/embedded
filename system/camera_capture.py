import cv2
import os
import time
import subprocess
import threading

class CameraCapture:
    def __init__(self):
        self.active = False
        self.latest_frame = None
        self._thread = None

    def start(self):
        if not self.active:
            self.active = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.active = False

    def _capture_loop(self):
        while self.active:
            try:
                # Capture to shared memory for speed
                # -n: nopreview, -t 1: timeout 1ms (fastest capture after ready), -o output
                subprocess.run(
                    ["rpicam-still", "-n", "-t", "1", "--width", "640", "--height", "480", "-o", "/dev/shm/preview.jpg"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                if os.path.exists("/dev/shm/preview.jpg"):
                    frame = cv2.imread("/dev/shm/preview.jpg")
                    if frame is not None:
                        self.latest_frame = frame
            except Exception as e:
                print(f"Camera capture error: {e}")
                time.sleep(1)
            
            # Prevent busy loop if capture is too fast, though rpicam-still is slow enough
            time.sleep(0.01)

    def get_frame(self):
        if self.latest_frame is not None:
            return self.latest_frame.copy()
        return None
