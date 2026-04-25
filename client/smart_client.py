from __future__ import annotations

import socket
import cv2
import os
import threading
import json
import random
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from datetime import datetime
import subprocess
import time

try:
    import RPi.GPIO as GPIO

    GPIO_AVAILABLE = True
except Exception:
    GPIO_AVAILABLE = False
    GPIO = None


SERVO_PIN = 14
if GPIO_AVAILABLE:
    assert GPIO is not None
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SERVO_PIN, GPIO.OUT)
    pwm = GPIO.PWM(SERVO_PIN, 50)
    pwm.start(0)
else:
    pwm = None


def set_angle(angle):
    if not GPIO_AVAILABLE or pwm is None:
        return

    assert GPIO is not None

    angle = max(0, min(180, angle))
    duty = 2.5 + (10.0 * angle / 180.0)
    GPIO.output(SERVO_PIN, True)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.5)
    GPIO.output(SERVO_PIN, False)
    pwm.ChangeDutyCycle(0)


def cleanup_gpio():
    if not GPIO_AVAILABLE or pwm is None:
        return

    assert GPIO is not None
    pwm.stop()
    GPIO.cleanup()


set_angle(0)

HOST = '192.168.160.147'
PORT = 8080


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        packet = sock.recv(min(256000, size - len(data)))
        if not packet:
            break
        data += packet
    return data


class ClientUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Material Management System - Client")
        self.root.geometry("840x620")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.state = "IDLE"  # IDLE, FACE, OPERATE, PROCESSING
        self.current_action = None
        self.current_person = None
        self.before_snapshot = None
        self.after_snapshot = None

        self.camera_active = False
        self.latest_frame = None

        self.setup_ui()
        self.reset_state()
        self.video_loop()

    def setup_ui(self):
        left_frame = ttk.Frame(self.root, padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_frame = ttk.Frame(self.root, padding=10, width=280)
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

        self.btn_capture = ttk.Button(self.frame_controls, text="Capture Face ID", command=self.capture_face)
        self.btn_finish_op = ttk.Button(
            self.frame_controls,
            text="Finish Operation",
            command=self.finish_operation,
        )
        self.btn_cancel = ttk.Button(self.frame_controls, text="Cancel", command=self.reset_state)

        ttk.Label(right_frame, text="Operation Log:", font=("Arial", 10)).pack(anchor=tk.W, pady=(15, 5))
        self.txt_log = tk.Text(right_frame, width=34, height=18, state=tk.DISABLED, font=("Arial", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def log(self, msg):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def log_async(self, msg):
        self.root.after(0, lambda: self.log(msg))

    def update_buttons(self):
        self.btn_capture.pack_forget()
        self.btn_finish_op.pack_forget()
        self.btn_cancel.pack_forget()

        if self.state == "IDLE":
            self.btn_outbound.config(state=tk.NORMAL)
            self.btn_inbound.config(state=tk.NORMAL)
        elif self.state == "FACE":
            self.btn_outbound.config(state=tk.DISABLED)
            self.btn_inbound.config(state=tk.DISABLED)
            self.btn_capture.pack(fill=tk.X, pady=5)
            self.btn_cancel.pack(fill=tk.X, pady=5)
        elif self.state == "OPERATE":
            self.btn_outbound.config(state=tk.DISABLED)
            self.btn_inbound.config(state=tk.DISABLED)
            self.btn_finish_op.pack(fill=tk.X, pady=5)
            self.btn_cancel.pack(fill=tk.X, pady=5)
        elif self.state == "PROCESSING":
            self.btn_outbound.config(state=tk.DISABLED)
            self.btn_inbound.config(state=tk.DISABLED)
            self.btn_cancel.pack(fill=tk.X, pady=5)

    def reset_state(self):
        self.state = "IDLE"
        self.current_action = None
        self.current_person = None
        self.before_snapshot = None
        self.after_snapshot = None
        self.camera_active = False
        self.latest_frame = None
        self.update_buttons()
        self.lbl_video.config(image='', text="Camera Off")
        self.log("Waiting...")

    def camera_capture_loop(self):
        while self.camera_active:
            try:
                subprocess.run(
                    [
                        "rpicam-still",
                        "-n",
                        "-t",
                        "1",
                        "--width",
                        "640",
                        "--height",
                        "480",
                        "-o",
                        "/dev/shm/preview.jpg",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                if os.path.exists("/dev/shm/preview.jpg"):
                    frame = cv2.imread("/dev/shm/preview.jpg")
                    if frame is not None:
                        self.latest_frame = frame
            except Exception as e:
                print(f"Camera capture error: {e}")
                time.sleep(1)

            time.sleep(0.01)

    def ensure_camera_running(self):
        if self.camera_active:
            return
        self.camera_active = True
        threading.Thread(target=self.camera_capture_loop, daemon=True).start()

    def start_action(self, action):
        self.current_action = action
        self.state = "FACE"
        self.log(f"=== Start {action} ===")
        self.log("Please face the camera and click [Capture Face ID].")
        self.update_buttons()
        self.ensure_camera_running()

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
        attempt = 1
        delay = 2.0
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(10.0)
                    s.connect((HOST, PORT))
                    cmd = f"RECOGNIZE,{len(img_bytes)}"
                    s.sendall(cmd.encode('utf-8'))

                    resp = s.recv(1024)
                    if resp == b'ok':
                        s.sendall(img_bytes)
                        person = s.recv(1024).decode('utf-8')
                break
            except Exception as e:
                self.root.after(
                    0,
                    lambda a=attempt, d=delay, err=e: self.log(
                        f"Network error (attempt {a}, next in {d}s): {err}"
                    ),
                )
                time.sleep(delay)
                attempt += 1
                delay = min(delay * 1.5, 30.0)

        if person and person != "Unknown" and "Failed" not in person and "No face" not in person:
            self.current_person = person
            self.root.after(0, self.on_recognize_success)
        else:
            self.root.after(0, lambda: self.log(f"Verification failed: {person}"))
            self.root.after(0, self.reset_state)

    def send_detect_materials(self, frame):
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success:
            raise RuntimeError('Image encoding failed')

        img_bytes = encoded_image.tobytes()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(15.0)
            s.connect((HOST, PORT))
            cmd = f"DETECT_MATERIALS,{len(img_bytes)}"
            s.sendall(cmd.encode('utf-8'))

            resp = s.recv(1024)
            if resp != b'ok':
                raise RuntimeError(f'Unexpected server ack: {resp}')

            s.sendall(img_bytes)

            header = s.recv(1024).decode('utf-8').strip()
            if not header.startswith('RESULT,'):
                raise RuntimeError(f'Unexpected result header: {header}')

            total_len = int(header.split(',', 1)[1])
            s.sendall(b'ok')
            body = recv_exact(s, total_len)
            if len(body) != total_len:
                raise RuntimeError('Detection payload length mismatch')

        payload = json.loads(body.decode('utf-8'))
        if not payload.get('ok', False):
            raise RuntimeError(payload.get('error', 'material detection failed'))
        return payload

    def detect_materials_with_retry(self, frame):
        attempt = 1
        delay = 1.5
        while True:
            try:
                return self.send_detect_materials(frame)
            except Exception as e:
                self.log_async(f"Material detect failed (attempt {attempt}, next in {delay}s): {e}")
                time.sleep(delay)
                attempt += 1
                if attempt > 4:
                    raise
                delay = min(delay * 1.5, 8.0)

    def format_counts(self, counts):
        if not counts:
            return "{}"
        items = [f"{k}:{v}" for k, v in sorted(counts.items())]
        return "{" + ", ".join(items) + "}"

    def on_recognize_success(self):
        self.log(f"Identity verified! Welcome {self.current_person}.")
        self.log("Capturing inventory snapshot BEFORE operation...")
        self.state = "PROCESSING"
        self.update_buttons()
        threading.Thread(target=self.prepare_operation_phase, daemon=True).start()

    def prepare_operation_phase(self):
        if self.latest_frame is None:
            self.root.after(0, lambda: self.log("No camera frame for before snapshot"))
            self.root.after(0, self.reset_state)
            return

        try:
            before = self.detect_materials_with_retry(self.latest_frame.copy())
            self.before_snapshot = before
            before_counts = before.get('counts', {})
            self.log_async(f"Before counts: {self.format_counts(before_counts)}")
            self.log_async("Opening door...")
            set_angle(90)
            self.log_async("Door opened. Perform your operation, then click [Finish Operation].")
            self.root.after(0, self.enter_operate_state)
        except Exception as e:
            self.log_async(f"Failed to prepare operation: {e}")
            self.root.after(0, self.reset_state)

    def enter_operate_state(self):
        self.state = "OPERATE"
        self.update_buttons()

    def finish_operation(self):
        if self.state != "OPERATE":
            return

        if self.latest_frame is None:
            self.log("No camera frame available")
            return

        self.state = "PROCESSING"
        self.update_buttons()
        self.log("Capturing inventory snapshot AFTER operation...")
        threading.Thread(target=self.complete_operation_flow, daemon=True).start()

    def close_door(self):
        self.log("Closing door...")
        set_angle(0)
        self.log("Door closed. Operation complete.")
        self.reset_state()

    def compute_delta(self, before_counts, after_counts):
        keys = sorted(set(before_counts.keys()) | set(after_counts.keys()))
        delta = {}
        for key in keys:
            diff = int(after_counts.get(key, 0)) - int(before_counts.get(key, 0))
            if diff != 0:
                delta[key] = diff
        return delta

    def classify_actual_action(self, delta):
        has_in = any(value > 0 for value in delta.values())
        has_out = any(value < 0 for value in delta.values())

        if has_in and has_out:
            return "Mixed"
        if has_in:
            return "Inbound"
        if has_out:
            return "Outbound"
        return "NoChange"

    def build_detail(self, delta):
        inbound = []
        outbound = []
        for material, value in sorted(delta.items()):
            if value > 0:
                inbound.append({'material': material, 'qty': value})
            elif value < 0:
                outbound.append({'material': material, 'qty': abs(value)})
        return {'inbound': inbound, 'outbound': outbound}

    def build_transaction_payload(self):
        before_counts = self.before_snapshot.get('counts', {}) if self.before_snapshot else {}
        after_counts = self.after_snapshot.get('counts', {}) if self.after_snapshot else {}
        delta = self.compute_delta(before_counts, after_counts)
        actual_action = self.classify_actual_action(delta)

        tx_id = datetime.now().strftime('%Y%m%d-%H%M%S') + f"-{random.randint(1000, 9999)}"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return {
            'tx_id': tx_id,
            'timestamp': timestamp,
            'person': self.current_person,
            'client_id': socket.gethostname(),
            'expected_action': (self.current_action or '').lower(),
            'actual_action': actual_action.lower(),
            'before_counts': before_counts,
            'after_counts': after_counts,
            'delta': delta,
            'detail': self.build_detail(delta),
            'face_result': self.current_person,
            'before_latency_ms': self.before_snapshot.get('latency_ms', 0) if self.before_snapshot else 0,
            'after_latency_ms': self.after_snapshot.get('latency_ms', 0) if self.after_snapshot else 0,
        }

    def send_transaction(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(15.0)
            s.connect((HOST, PORT))
            cmd = f"DATA_JSON,{len(body)}"
            s.sendall(cmd.encode('utf-8'))
            ack = s.recv(1024)
            if ack != b'ok':
                raise RuntimeError(f'Unexpected server ack: {ack}')

            s.sendall(body)
            result = s.recv(1024).decode('utf-8')
            if not result.startswith('Saved'):
                raise RuntimeError(result)
            return result

    def complete_operation_flow(self):
        try:
            if self.latest_frame is None:
                raise RuntimeError('No camera frame for after snapshot')

            self.after_snapshot = self.detect_materials_with_retry(self.latest_frame.copy())
            after_counts = self.after_snapshot.get('counts', {})
            self.log_async(f"After counts: {self.format_counts(after_counts)}")

            self.log_async("Closing door...")
            set_angle(0)
            self.log_async("Door closed. Calculating inventory changes...")

            payload = self.build_transaction_payload()
            delta = payload.get('delta', {})
            self.log_async(f"Delta: {json.dumps(delta, ensure_ascii=False)}")

            reply = self.send_transaction(payload)
            self.log_async(f"Server reply: {reply}")

            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Success",
                    f"Operation saved\nActual: {payload.get('actual_action')}\nDelta: {json.dumps(delta, ensure_ascii=False)}",
                ),
            )
        except Exception as e:
            self.log_async(f"Operation failed: {e}")
            self.root.after(0, lambda: messagebox.showerror("Failed", str(e)))
        finally:
            self.root.after(0, self.reset_state)

    def video_loop(self):
        if self.state in ["FACE", "OPERATE", "PROCESSING"] and self.latest_frame is not None:
            frame = self.latest_frame.copy()
            display_frame = frame

            if self.state == "FACE":
                cv2.putText(
                    display_frame,
                    "Please face the camera",
                    (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 0, 0),
                    2,
                )
            elif self.state == "OPERATE":
                before_counts = self.before_snapshot.get('counts', {}) if self.before_snapshot else {}
                text = f"Before: {self.format_counts(before_counts)}"
                cv2.putText(
                    display_frame,
                    text,
                    (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )

            cv2image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2image)
            img = img.resize((530, 400), Image.Resampling.LANCZOS)
            imgtk = ImageTk.PhotoImage(image=img)
            self._current_image = imgtk
            self.lbl_video.configure(image=imgtk, text="")

        self.root.after(100, self.video_loop)

    def on_closing(self):
        self.camera_active = False
        cleanup_gpio()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ClientUI(root)
    root.mainloop()
