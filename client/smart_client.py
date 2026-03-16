import socket
import cv2
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

HOST = '127.0.0.1'
PORT = 8080
QR_SYNC_DIR = 'qrcode_sync'

class ClientUI:
    def __init__(self, root):
        self.root = root
        self.root.title("智能物资管理系统 - 客户端")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.state = "IDLE"  # IDLE, FACE, QR, PROCESSING
        self.current_action = None
        self.current_person = None
        self.scanned_materials = set()
        
        self.cap = None
        self.detector = cv2.QRCodeDetector()
        
        self.setup_ui()
        self.reset_state()
        
        # 启动同步线程
        threading.Thread(target=self.sync_materials, daemon=True).start()
        
        # 启动视频刷新循环
        self.video_loop()

    def setup_ui(self):
        # 左右分栏
        left_frame = ttk.Frame(self.root, padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(self.root, padding=10, width=250)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # --- 左侧视频区 ---
        self.lbl_video = tk.Label(left_frame, bg="black", text="摄像头未开启", fg="white", font=("Arial", 16))
        self.lbl_video.pack(fill=tk.BOTH, expand=True)
        
        # --- 右侧控制与日志区 ---
        ttk.Label(right_frame, text="主菜单", font=("Arial", 14, "bold")).pack(pady=10)
        
        self.btn_outbound = ttk.Button(right_frame, text="物资出库", command=lambda: self.start_action("出库"))
        self.btn_outbound.pack(fill=tk.X, pady=5)
        
        self.btn_inbound = ttk.Button(right_frame, text="物资入库", command=lambda: self.start_action("入库"))
        self.btn_inbound.pack(fill=tk.X, pady=5)
        
        ttk.Separator(right_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        self.frame_controls = ttk.Frame(right_frame)
        self.frame_controls.pack(fill=tk.X, pady=5)
        
        self.btn_capture = ttk.Button(self.frame_controls, text="📸 拍照识别身份", command=self.capture_face)
        self.btn_finish_qr = ttk.Button(self.frame_controls, text="✅ 完成物资扫描", command=self.finish_scan)
        self.btn_cancel = ttk.Button(self.frame_controls, text="❌ 取消操作", command=self.reset_state)
        
        ttk.Label(right_frame, text="操作日志:", font=("Arial", 10)).pack(anchor=tk.W, pady=(15, 5))
        self.txt_log = tk.Text(right_frame, width=30, height=15, state=tk.DISABLED, font=("Arial", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def log(self, msg):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def sync_materials(self):
        self.log("开始同步物资二维码...")
        if not os.path.exists(QR_SYNC_DIR):
            os.makedirs(QR_SYNC_DIR)
            
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                s.sendall(b"SYNC_MAT")
                
                resp = s.recv(1024).decode('utf-8')
                if resp.startswith("COUNT"):
                    count = int(resp.split(",")[1])
                    self.log(f"服务器共有 {count} 个二维码。")
                    
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
                    self.log("二维码同步完成。")
                else:
                    self.log("无需同步或同步出错。")
        except Exception as e:
            self.log(f"同步连接失败: {e}")

    def update_buttons(self):
        # 隐藏所有动态按钮
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
        self.update_buttons()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.lbl_video.config(image='', text="摄像头未开启")
        self.log("等待操作...")

    def start_action(self, action):
        self.current_action = action
        self.state = "FACE"
        self.log(f"=== 开始 {action} ===")
        self.log("请正对摄像头，点击[拍照识别身份]。")
        self.update_buttons()
        
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("错误", "无法打开摄像头！")
            self.reset_state()

    def capture_face(self):
        if not self.cap or not self.cap.isOpened():
            return
            
        ret, frame = self.cap.read()
        if not ret:
            self.log("获取画面失败")
            return
            
        self.state = "PROCESSING"
        self.update_buttons()
        self.log("正在验证身份...")
        
        threading.Thread(target=self.do_recognize, args=(frame,), daemon=True).start()

    def do_recognize(self, frame):
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success:
            self.root.after(0, lambda: self.log("图像编码失败"))
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
            self.root.after(0, lambda: self.log(f"网络异常: {e}"))
            
        if person and person != "Unknown" and "Failed" not in person and "No face" not in person:
            self.current_person = person
            self.root.after(0, self.on_recognize_success)
        else:
            self.root.after(0, lambda: self.log(f"验证失败: {person}"))
            self.root.after(0, self.reset_state)

    def on_recognize_success(self):
        self.log(f"身份验证成功！欢迎 {self.current_person}。")
        self.log("请将物资二维码对准摄像头，系统将自动记录。扫描完毕后点击[完成物资扫描]。")
        self.state = "QR"
        self.scanned_materials.clear()
        self.update_buttons()

    def finish_scan(self):
        if not self.scanned_materials:
            ans = messagebox.askyesno("提示", "当前未扫描到任何物资，是否取消操作？")
            if ans:
                self.reset_state()
            return
            
        self.state = "PROCESSING"
        self.update_buttons()
        self.log("正在上传数据...")
        
        materials = list(self.scanned_materials)
        threading.Thread(target=self.do_upload_data, args=(materials,), daemon=True).start()

    def do_upload_data(self, materials):
        materials_str = " | ".join(materials)
        success = False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((HOST, PORT))
                cmd = f"DATA,{self.current_person},{self.current_action},{materials_str}"
                s.sendall(cmd.encode('utf-8'))
                result = s.recv(1024).decode('utf-8')
                self.root.after(0, lambda: self.log(f"服务器回复: {result}"))
                success = True
        except Exception as e:
            self.root.after(0, lambda: self.log(f"上传失败: {e}"))
            
        if success:
            self.root.after(0, lambda: messagebox.showinfo("成功", f"物资{self.current_action}记录已保存！"))
        self.root.after(0, self.reset_state)

    def video_loop(self):
        if self.cap and self.cap.isOpened() and self.state in ["FACE", "QR"]:
            ret, frame = self.cap.read()
            if ret:
                display_frame = frame.copy()
                
                # 如果是扫码模式，检测二维码
                if self.state == "QR":
                    data, bbox, _ = self.detector.detectAndDecode(frame)
                    if data and data not in self.scanned_materials:
                        self.scanned_materials.add(data)
                        self.log(f"[*] 扫描到物资: {data}")
                        
                    if bbox is not None:
                        n = len(bbox)
                        for j in range(n):
                            cv2.line(display_frame, tuple(int(x) for x in bbox[j][0]), tuple(int(x) for x in bbox[(j+1) % n][0]), (0, 255, 0), 3)

                    cv2.putText(display_frame, f"Scanned: {len(self.scanned_materials)}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                elif self.state == "FACE":
                    cv2.putText(display_frame, "Please face the camera", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

                # 转换为Tkinter可用的图像
                cv2image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(cv2image)
                # 调整大小以适应标签
                img = img.resize((530, 400), Image.Resampling.LANCZOS)
                imgtk = ImageTk.PhotoImage(image=img)
                self._current_image = imgtk  # 保持引用，防止被垃圾回收
                self.lbl_video.configure(image=imgtk, text="")
        
        self.root.after(30, self.video_loop)

    def on_closing(self):
        if self.cap:
            self.cap.release()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ClientUI(root)
    root.mainloop()
