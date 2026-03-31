import socket
import cv2
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from datetime import datetime
import subprocess
import time
import RPi.GPIO as GPIO

# --- 舵机配置 ---
SERVO_PIN = 14
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, 50)
pwm.start(0)

def set_angle(angle):
    """控制舵机转动到指定角度并归零"""
    angle = max(0, min(180, angle))
    duty = 2.5 + (10.0 * angle / 180.0)
    GPIO.output(SERVO_PIN, True)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.5)
    GPIO.output(SERVO_PIN, False)
    pwm.ChangeDutyCycle(0)

# 初始化门为关闭状态 (90度)
set_angle(0)

HOST = '192.168.168.149'
PORT = 8080
QR_SYNC_DIR = 'qrcode_sync'

class ClientUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Material Management System - Client")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.state = "IDLE"  # IDLE, FACE, QR, PROCESSING
        self.current_action = None
        self.current_person = None
        self.scanned_materials = set()
        
        self.camera_active = False
        self.latest_frame = None
        # self.detector = cv2.QRCodeDetector() # Local detection removed
        self.last_qr_request_time = 0
        self.is_requesting_qr = False
        
        self.setup_ui()
        self.reset_state()
        
        # Start sync thread
        threading.Thread(target=self.sync_materials, daemon=True).start()
        
        # Start video refresh loop (UI update)
        self.video_loop()

    def setup_ui(self):
        # Split layout
        left_frame = ttk.Frame(self.root, padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(self.root, padding=10, width=250)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # --- Left Video Area ---
        self.lbl_video = tk.Label(left_frame, bg="black", text="Camera Off", fg="white", font=("Arial", 16))
        self.lbl_video.pack(fill=tk.BOTH, expand=True)
        
        # --- Right Control & Log Area ---
        ttk.Label(right_frame, text="Main Menu", font=("Arial", 14, "bold")).pack(pady=10)
        
        self.btn_outbound = ttk.Button(right_frame, text="Outbound", command=lambda: self.start_action("Outbound"))
        self.btn_outbound.pack(fill=tk.X, pady=5)
        
        self.btn_inbound = ttk.Button(right_frame, text="Inbound", command=lambda: self.start_action("Inbound"))
        self.btn_inbound.pack(fill=tk.X, pady=5)
        
        ttk.Separator(right_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        self.btn_close_door = ttk.Button(right_frame, text="Close Door", command=self.close_door)
        self.btn_close_door.pack(fill=tk.X, pady=5)
        
        ttk.Separator(right_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        self.frame_controls = ttk.Frame(right_frame)
        self.frame_controls.pack(fill=tk.X, pady=5)
        
        self.btn_capture = ttk.Button(self.frame_controls, text="Capture Face ID", command=self.capture_face)
        self.btn_finish_qr = ttk.Button(self.frame_controls, text="Finish Scan", command=self.finish_scan)
        self.btn_cancel = ttk.Button(self.frame_controls, text="Cancel", command=self.reset_state)
        
        ttk.Label(right_frame, text="Operation Log:", font=("Arial", 10)).pack(anchor=tk.W, pady=(15, 5))
        self.txt_log = tk.Text(right_frame, width=30, height=15, state=tk.DISABLED, font=("Arial", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def log(self, msg):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def sync_materials(self):
        self.log("Syncing QR codes...")
        if not os.path.exists(QR_SYNC_DIR):
            os.makedirs(QR_SYNC_DIR)
            
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                s.sendall(b"SYNC_MAT")
                
                resp = s.recv(1024).decode('utf-8')
                if resp.startswith("COUNT"):
                    count = int(resp.split(",")[1])
                    self.log(f"Server has {count} QR codes.")
                    
                    for i in range(count):
                        s.sendall(b"ok")
                        file_info = s.recv(1024).decode('utf-8').split(",")
                        if file_info[0] == "FILE":
                            filename = file_info[1]
                            filesize = int(file_info[2])
                            s.sendall(b"ready")
                            
                            img_bytes = b""
                            while len(img_bytes) < filesize:
                                packet = s.recv(min(256000, filesize - len(img_bytes)))
                                if not packet:
                                    break
                                img_bytes += packet
                                
                            filepath = os.path.join(QR_SYNC_DIR, filename)
                            with open(filepath, "wb") as f:
                                f.write(img_bytes)
                    self.log("QR Sync completed.")
                else:
                    self.log("No sync needed or error.")
        except Exception as e:
            self.log(f"Sync failed: {e}")

    def update_buttons(self):
        # Hide dynamic buttons
        self.btn_capture.pack_forget()
        self.btn_finish_qr.pack_forget()
        self.btn_cancel.pack_forget()
        
        if self.state == "IDLE":
            self.btn_outbound.config(state=tk.NORMAL)
            self.btn_inbound.config(state=tk.NORMAL)
        elif self.state == "FACE":
            self.btn_outbound.config(state=tk.DISABLED)
            self.btn_inbound.config(state=tk.DISABLED)
            self.btn_capture.pack(fill=tk.X, pady=5)
            self.btn_cancel.pack(fill=tk.X, pady=5)
        elif self.state == "QR":
            self.btn_finish_qr.pack(fill=tk.X, pady=5)
            self.btn_cancel.pack(fill=tk.X, pady=5)
        elif self.state == "PROCESSING":
            self.btn_cancel.pack(fill=tk.X, pady=5)

    def reset_state(self):
        self.state = "IDLE"
        self.current_action = None
        self.current_person = None
        self.scanned_materials.clear()
        self.camera_active = False # Stop camera thread
        self.latest_frame = None
        self.update_buttons()
        self.lbl_video.config(image='', text="Camera Off")
        self.log("Waiting...")

    def camera_capture_loop(self):
        """Thread to capture images using rpicam-still continuously"""
        while self.camera_active:
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

    def start_action(self, action):
        self.current_action = action
        self.state = "FACE"
        self.log(f"=== Start {action} ===")
        self.log("Please face the camera and click [Capture Face ID].")
        self.update_buttons()
        
        self.camera_active = True
        threading.Thread(target=self.camera_capture_loop, daemon=True).start()

    def capture_face(self):
        if self.latest_frame is None:
            self.log("No camera frame available")
            return
            
        frame = self.latest_frame.copy()
            
        self.state = "PROCESSING"
        self.update_buttons()
        self.log("Verifying identity...")
        
        threading.Thread(target=self.do_recognize, args=(frame,), daemon=True).start()

    def do_recognize(self, frame):
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success:
            self.root.after(0, lambda: self.log("Image encoding failed"))
            self.root.after(0, self.reset_state)
            return
            
        img_bytes = encoded_image.tobytes()
        person = None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                cmd = f"RECOGNIZE,{len(img_bytes)}"
                s.sendall(cmd.encode('utf-8'))
                
                resp = s.recv(1024)
                if resp == b'ok':
                    s.sendall(img_bytes)
                    person = s.recv(1024).decode('utf-8')
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Network error: {e}"))
            
        if person and person != "Unknown" and "Failed" not in person and "No face" not in person:
            self.current_person = person
            self.root.after(0, self.on_recognize_success)
        else:
            self.root.after(0, lambda: self.log(f"Verification failed: {person}"))
            self.root.after(0, self.reset_state)

    def do_recognize_qr(self, frame):
        try:
            success, encoded_image = cv2.imencode('.jpg', frame)
            if not success:
                return

            img_bytes = encoded_image.tobytes()
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                cmd = f"RECOGNIZE_QR,{len(img_bytes)}"
                s.sendall(cmd.encode('utf-8'))
                
                resp = s.recv(1024)
                if resp == b'ok':
                    s.sendall(img_bytes)
                    result = s.recv(1024).decode('utf-8')
                    # result may be "No QR Detected" or the QR data
                    if result and "No QR Detected" not in result and "Failed" not in result:
                        self.root.after(0, lambda r=result: self.handle_qr_result(r))
        except Exception as e:
            print(f"QR Recognition Error: {e}")
        finally:
            self.is_requesting_qr = False

    def handle_qr_result(self, qr_data):
        if qr_data not in self.scanned_materials:
            self.scanned_materials.add(qr_data)
            self.log(f"[*] Remote Scanned: {qr_data}")

    def on_recognize_success(self):
        self.log(f"Identity verified! Welcome {self.current_person}.")
        self.log("Opening door...")
        set_angle(90)
        self.log("Align QR code with camera. Auto-scan on server. Click [Finish Scan] when done.")
        self.state = "QR"
        self.scanned_materials.clear()
        self.update_buttons()

    def close_door(self):
        self.log("Closing door...")
        set_angle(0)
        self.log("Door closed. Operation complete.")
        self.reset_state()

    def finish_scan(self):
        if not self.scanned_materials:
            ans = messagebox.askyesno("Info", "No materials scanned, cancel operation?")
            if ans:
                self.reset_state()
            return
            
        self.state = "PROCESSING"
        self.update_buttons()
        self.log("Uploading data...")
        
        materials = list(self.scanned_materials)
        threading.Thread(target=self.do_upload_data, args=(materials,), daemon=True).start()

    def do_upload_data(self, materials):
        materials_str = " | ".join(materials)
        success = False
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                cmd = f"DATA,{self.current_person},{self.current_action},{timestamp},{materials_str}"
                s.sendall(cmd.encode('utf-8'))
                result = s.recv(1024).decode('utf-8')
                self.root.after(0, lambda: self.log(f"Server reply: {result}"))
                success = True
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Upload failed: {e}"))
            
        if success:
            self.root.after(0, lambda: messagebox.showinfo("Success", f"Material {self.current_action} record saved!"))
        self.root.after(0, self.reset_state)

    def video_loop(self):
        if self.state in ["FACE", "QR"] and self.latest_frame is not None:
            # Get latest frame
            frame = self.latest_frame.copy()
            display_frame = frame
            
            # QR Detection
            if self.state == "QR":
                current_time = time.time()
                if not self.is_requesting_qr and (current_time - self.last_qr_request_time) > 0.5: # 2 FPS limit
                    self.is_requesting_qr = True
                    self.last_qr_request_time = current_time
                    threading.Thread(target=self.do_recognize_qr, args=(frame.copy(),), daemon=True).start()

                cv2.putText(display_frame, f"Remote Scan: {len(self.scanned_materials)}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            elif self.state == "FACE":
                cv2.putText(display_frame, "Please face the camera", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

            # Convert for Tkinter
            cv2image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2image)
            img = img.resize((530, 400), Image.Resampling.LANCZOS)
            imgtk = ImageTk.PhotoImage(image=img)
            self._current_image = imgtk
            self.lbl_video.configure(image=imgtk, text="")
        
        self.root.after(100, self.video_loop)

    def on_closing(self):
        self.camera_active = False # Signal thread to stop
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ClientUI(root)
    root.mainloop()
