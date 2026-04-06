import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import cv2
import threading
import time
from datetime import datetime
import os

from hardware_manager import HardwareManager
from camera_capture import CameraCapture
from face_manager import FaceManager
from qr_manager import QRManager
from data_logger import DataLogger

class SystemUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Material Management System")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Initialize modules
        self.hardware = HardwareManager(servo_pin=14)
        self.camera = CameraCapture()
        self.face_manager = FaceManager(known_dir='known', tolerance=0.5)
        self.qr_manager = QRManager(qr_dir='qrcode')
        self.logger = DataLogger(log_file='material_log.csv')
        
        self.state = "IDLE"  # IDLE, FACE, QR, PROCESSING
        self.current_action = None
        self.current_person = None
        self.scanned_materials = set()
        
        self.last_qr_request_time = 0
        self.is_requesting_qr = False
        
        self.setup_ui()
        self.reset_state()
        
        # Start video update loop
        self.video_loop()

    def setup_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # --- Tab 1: Operator Interface ---
        self.tab_main = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_main, text="Operation Interface")
        
        left_frame = ttk.Frame(self.tab_main, padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(self.tab_main, padding=10, width=250)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.lbl_video = tk.Label(left_frame, bg="black", text="Camera Off", fg="white", font=("Arial", 16))
        self.lbl_video.pack(fill=tk.BOTH, expand=True)
        
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
        
        self.btn_capture = ttk.Button(self.frame_controls, text="Capture Face", command=self.capture_face)
        self.btn_finish_qr = ttk.Button(self.frame_controls, text="Finish Scan", command=self.finish_scan)
        self.btn_cancel = ttk.Button(self.frame_controls, text="Cancel", command=self.reset_state)
        
        ttk.Label(right_frame, text="Operation Log:", font=("Arial", 10)).pack(anchor=tk.W, pady=(15, 5))
        self.txt_log = tk.Text(right_frame, width=30, height=15, state=tk.DISABLED, font=("Arial", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # --- Tab 2: Admin Tools ---
        self.tab_admin = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_admin, text="Admin Tools")
        
        # QR Generation
        frame_qr = ttk.LabelFrame(self.tab_admin, text="QR Generation")
        frame_qr.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(frame_qr, text="Material Name:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_qr_name = ttk.Entry(frame_qr, width=30)
        self.entry_qr_name.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(frame_qr, text="Material ID:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_qr_id = ttk.Entry(frame_qr, width=30)
        self.entry_qr_id.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Button(frame_qr, text="Generate QR", command=self.ui_generate_qr).grid(row=2, column=0, columnspan=2, pady=10)

        # Face Registration
        frame_face = ttk.LabelFrame(self.tab_admin, text="Face Registration")
        frame_face.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(frame_face, text="Name:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_face_name = ttk.Entry(frame_face, width=30)
        self.entry_face_name.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Label(frame_face, text="Image File:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.entry_face_path = ttk.Entry(frame_face, width=30)
        self.entry_face_path.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Button(frame_face, text="Browse...", command=self.ui_browse_image).grid(row=1, column=2, padx=5, pady=5)
        ttk.Button(frame_face, text="Register & Save", command=self.ui_register_face).grid(row=2, column=0, columnspan=3, pady=10)

    def log(self, msg):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def update_buttons(self):
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
        self.camera.stop()
        self.update_buttons()
        self.lbl_video.config(image='', text="Camera Off")
        self.log("Waiting...")

    def start_action(self, action):
        self.current_action = action
        self.state = "FACE"
        self.log(f"=== Start {action} ===")
        self.log("Please face the camera and click [Capture Face].")
        self.update_buttons()
        self.camera.start()

    def capture_face(self):
        frame = self.camera.get_frame()
        if frame is None:
            self.log("No camera frame available")
            return
            
        self.state = "PROCESSING"
        self.update_buttons()
        self.log("Verifying identity...")
        
        threading.Thread(target=self.do_recognize, args=(frame,), daemon=True).start()

    def do_recognize(self, frame):
        person = self.face_manager.recognize_face(frame)
        if person and person != "Unknown" and "No face" not in person:
            self.current_person = person
            self.root.after(0, self.on_recognize_success)
        else:
            self.root.after(0, lambda: self.log(f"Verification failed: {person}"))
            self.root.after(0, self.reset_state)

    def on_recognize_success(self):
        self.log(f"Identity verified! Welcome {self.current_person}.")
        self.log("Opening door...")
        self.hardware.open_door()
        self.log("Align QR to camera. Auto-scan enabled. Click [Finish Scan].")
        self.state = "QR"
        self.scanned_materials.clear()
        self.update_buttons()

    def close_door(self):
        self.log("Closing door...")
        self.hardware.close_door()
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
        self.log("Saving data...")
        
        materials = list(self.scanned_materials)
        self.do_save_data(materials)

    def do_save_data(self, materials):
        materials_str = " | ".join(materials)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        success, msg = self.logger.log_action(timestamp, self.current_person, self.current_action, materials_str)
        self.log(msg)
        
        if success:
            messagebox.showinfo("Success", f"{self.current_action} record saved!")
        self.reset_state()

    def do_recognize_qr(self, frame):
        try:
            result = self.qr_manager.recognize_qr(frame)
            if result:
                self.root.after(0, lambda r=result: self.handle_qr_result(r))
        finally:
            self.is_requesting_qr = False

    def handle_qr_result(self, qr_data):
        if qr_data not in self.scanned_materials:
            self.scanned_materials.add(qr_data)
            self.log(f"[*] Scanned: {qr_data}")

    def ui_generate_qr(self):
        name = self.entry_qr_name.get().strip()
        mat_id = self.entry_qr_id.get().strip()
        if not name or not mat_id:
            messagebox.showwarning("Warning", "Please enter material name and ID")
            return
        filepath = self.qr_manager.generate_qr(name, mat_id)
        messagebox.showinfo("Success", f"QR Code Generated:\n{filepath}")

    def ui_browse_image(self):
        filepath = filedialog.askopenfilename(title="Select Image", filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")])
        if filepath:
            self.entry_face_path.delete(0, tk.END)
            self.entry_face_path.insert(0, filepath)

    def ui_register_face(self):
        name = self.entry_face_name.get().strip()
        filepath = self.entry_face_path.get().strip()
        if not name or not filepath:
            messagebox.showwarning("Warning", "Please enter name and select image file")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("Error", "Image file does not exist")
            return
        
        success, msg = self.face_manager.register_face(name, filepath)
        if success:
            messagebox.showinfo("Success", f"Face registered successfully: {name}")
            self.entry_face_name.delete(0, tk.END)
            self.entry_face_path.delete(0, tk.END)
        else:
            messagebox.showwarning("Failed", f"Face registration failed: {msg}")

    def video_loop(self):
        if self.state in ["FACE", "QR"]:
            frame = self.camera.get_frame()
            if frame is not None:
                display_frame = frame.copy()
                
                # QR Detection
                if self.state == "QR":
                    current_time = time.time()
                    if not self.is_requesting_qr and (current_time - self.last_qr_request_time) > 0.5:
                        self.is_requesting_qr = True
                        self.last_qr_request_time = current_time
                        threading.Thread(target=self.do_recognize_qr, args=(frame.copy(),), daemon=True).start()

                    cv2.putText(display_frame, f"Scanned: {len(self.scanned_materials)}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                elif self.state == "FACE":
                    cv2.putText(display_frame, "Please face the camera", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

                # Convert for Tkinter
                cv2image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(cv2image)
                img = img.resize((530, 400), Image.Resampling.LANCZOS)
                imgtk = ImageTk.PhotoImage(image=img)
                self.lbl_video.configure(image=imgtk, text="")
                self._current_image = imgtk
        
        self.root.after(100, self.video_loop)

    def on_closing(self):
        self.camera.stop()
        self.hardware.cleanup()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = SystemUI(root)
    root.mainloop()
