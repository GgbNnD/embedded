import tkinter as tk
from tkinter import ttk
import cv2
from PIL import Image, ImageTk
import threading
import subprocess
import time
import os

class QRCodeTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("QR Code Camera Test")
        self.root.geometry("800x650")
        
        self.running = False
        self.latest_frame = None
        self.detector = cv2.QRCodeDetector()
        
        self.setup_ui()
        
        # Start camera automatically
        self.start_camera()

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main_frame, text="RPi Camera QR Code Test", font=("Arial", 16, "bold")).pack(pady=10)

        # Video Display
        self.video_label = tk.Label(main_frame, bg="black", text="Waiting for camera...", fg="white")
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Result Display Area
        info_frame = ttk.LabelFrame(main_frame, text="Detection Result", padding=10)
        info_frame.pack(fill=tk.X, pady=10)

        self.result_var = tk.StringVar(value="No QR code detected")
        ttk.Label(info_frame, textvariable=self.result_var, font=("Arial", 12), wraplength=750).pack()

        # Controls
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="Restart Camera", command=self.restart_camera).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Quit", command=self.on_closing).pack(side=tk.LEFT, padx=10)

        # Status Bar
        self.status_var = tk.StringVar(value="Initializing...")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

    def start_camera(self):
        if self.running:
            return
            
        self.running = True
        self.status_var.set("Starting camera thread...")
        
        # Start capture thread
        threading.Thread(target=self.capture_loop, daemon=True).start()
        
        # Start UI update loop
        self.update_ui_loop()

    def stop_camera(self):
        self.running = False
        self.status_var.set("Camera stopped")

    def restart_camera(self):
        self.stop_camera()
        # Give a little time for the thread to exit
        self.root.after(500, self.start_camera)

    def capture_loop(self):
        """Continuously captures images using rpicam-still"""
        print("Capture thread started")
        while self.running:
            try:
                # Use rpicam-still to capture to shared memory for performance
                # -n: no preview window
                # -t 1: minimal timeout
                # --width 640 --height 480: lower resolution for speed
                # -o /dev/shm/test_preview.jpg: write to RAM disk
                cmd = [
                    "rpicam-still", 
                    "-n", 
                    "-t", "1", 
                    "--width", "640", 
                    "--height", "480", 
                    "-o", "/dev/shm/test_preview.jpg"
                ]
                
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                if os.path.exists("/dev/shm/test_preview.jpg"):
                    # Use cv2.imread to read the image
                    frame = cv2.imread("/dev/shm/test_preview.jpg")
                    if frame is not None:
                        self.latest_frame = frame
                    else:
                        print("Failed to read image from /dev/shm")
                
            except Exception as e:
                print(f"Camera error: {e}")
                time.sleep(1)
            
            # Avoid CPU hogging
            time.sleep(0.05)

    def update_ui_loop(self):
        if not self.running:
            return

        if self.latest_frame is not None:
            # Process frame
            frame = self.latest_frame.copy()
            
            # Detect QR Code
            start_time = time.time()
            data, bbox, _ = self.detector.detectAndDecode(frame)
            fps = 1.0 / (time.time() - start_time + 0.001) # Simple processing FPS

            if data:
                self.result_var.set(f"Content: {data}")
                self.status_var.set(f"QR Code Detected! (FPS: {fps:.1f})")
                
                # Draw bounding box
                if bbox is not None:
                    n = len(bbox)
                    for j in range(n):
                        pt1 = tuple(int(x) for x in bbox[j][0])
                        pt2 = tuple(int(x) for x in bbox[(j+1) % n][0])
                        cv2.line(frame, pt1, pt2, (0, 255, 0), 3)
            else:
                self.status_var.set(f"Scanning... (FPS: {fps:.1f})")

            # Convert to Tkinter image
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2image)
            
            # Resize for display if needed (maintain aspect ratio)
            display_width = 780
            w_percent = (display_width / float(img.size[0]))
            h_size = int((float(img.size[1]) * float(w_percent)))
            img = img.resize((display_width, h_size), Image.Resampling.LANCZOS)
            
            imgtk = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=imgtk, text="")
            self.video_label.image = imgtk # Keep reference

        # Schedule next update
        self.root.after(50, self.update_ui_loop)

    def on_closing(self):
        self.running = False
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = QRCodeTestApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
