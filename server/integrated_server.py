import socket
import cv2
import numpy as np
import os
import face_recognition
import csv
import json
import sys
from datetime import datetime
import argparse
import threading
import qrcode
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from material_detector_yolo.detector import MaterialDetector
except Exception:
    MaterialDetector = None

KNOWN_FACES_DIR = 'known'
LOG_FILE = 'material_log.csv'
TRANSACTION_LOG_FILE = 'material_transaction_log.csv'
QR_DIR = 'qrcode'
TOLERANCE = 0.5

DEFAULT_MATERIAL_MODEL = os.path.join(
    BASE_DIR,
    'material_detector_yolo',
    'artifacts',
    'yolov8n_material',
    'weights',
    'best.pt',
)
DEFAULT_MATERIAL_CLASSES = os.path.join(BASE_DIR, 'material_detector_yolo', 'configs', 'classes.txt')

known_faces = []
known_names = []
server_socket = None
server_running = False
log_callback = None
image_callback = None
material_detector = None
material_config = {
    'model_path': DEFAULT_MATERIAL_MODEL,
    'class_path': DEFAULT_MATERIAL_CLASSES,
    'device': '0',
    'conf': 0.35,
    'iou': 0.45,
    'imgsz': 640,
}

def log_msg(msg):
    print(msg)
    if log_callback:
        log_callback(msg)

def load_known_faces():
    global known_faces, known_names
    known_faces = []
    known_names = []
    if not os.path.exists(KNOWN_FACES_DIR):
        os.makedirs(KNOWN_FACES_DIR)
    log_msg("正在加载已知人脸...")
    for filename in os.listdir(KNOWN_FACES_DIR):
        if filename.endswith(('.png', '.jpg', '.jpeg', '.JPEG', '.JPG')):
            path = os.path.join(KNOWN_FACES_DIR, filename)
            image = face_recognition.load_image_file(path)
            locations = face_recognition.face_locations(image)
            encodings = face_recognition.face_encodings(image, locations)
            if len(encodings) > 0:
                name = os.path.splitext(filename)[0]
                known_faces.append(encodings[0])
                known_names.append(name)
                log_msg(f"已录入: {name}")
    log_msg(f"已知人脸库加载完成，共 {len(known_names)} 人。")

def recognize_face(img_bytes):
    img = np.asarray(bytearray(img_bytes), dtype="uint8")
    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
    if img is None:
        return "Image Decode Failed"
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    locations = face_recognition.face_locations(rgb_img)
    encodings = face_recognition.face_encodings(rgb_img, locations)
    
    recognized_names = []
    for face_encoding in encodings:
        name = "Unknown"
        if known_faces:
            matches = face_recognition.compare_faces(known_faces, face_encoding, TOLERANCE)
            if True in matches:
                distances = face_recognition.face_distance(known_faces, face_encoding)
                best_match_index = np.argmin(distances)
                if matches[best_match_index]:
                    name = known_names[best_match_index]
        recognized_names.append(name)
    
    if not recognized_names:
        return "No face detected"
    return ",".join(recognized_names)

def recognize_qr(img_bytes):
    img = np.asarray(bytearray(img_bytes), dtype="uint8")
    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
    if img is None:
        return "Image Decode Failed"
    
    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(img)
    
    if data:
        return data
    return "No QR Detected"

def register_face(name, img_bytes):
    img = np.asarray(bytearray(img_bytes), dtype="uint8")
    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
    if img is None:
        return "Image Decode Failed"
    
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb_img)
    encodings = face_recognition.face_encodings(rgb_img, locations)
    
    if len(encodings) > 0:
        cv2.imwrite(os.path.join(KNOWN_FACES_DIR, f"{name}.jpg"), img)
        known_faces.append(encodings[0])
        known_names.append(name)
        return "Register Success"
    else:
        return "No face detected, register failed"


def _recv_exact(client_socket, total_len):
    payload = b""
    while len(payload) < total_len:
        packet = client_socket.recv(min(256000, total_len - len(payload)))
        if not packet:
            break
        payload += packet
    return payload


def _send_json_payload(client_socket, payload):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    client_socket.send(f"RESULT,{len(body)}".encode('utf-8'))
    ack = client_socket.recv(1024)
    if ack != b'ok':
        raise ConnectionError(f"Unexpected client ack: {ack!r}")
    client_socket.sendall(body)


def init_material_detector(
    model_path=None,
    class_path=None,
    device='0',
    conf=0.35,
    iou=0.45,
    imgsz=640,
):
    global material_detector, material_config

    material_config = {
        'model_path': model_path or DEFAULT_MATERIAL_MODEL,
        'class_path': class_path or DEFAULT_MATERIAL_CLASSES,
        'device': str(device),
        'conf': float(conf),
        'iou': float(iou),
        'imgsz': int(imgsz),
    }

    if MaterialDetector is None:
        log_msg('物资检测模块不可用：未安装 material_detector_yolo 依赖。')
        material_detector = None
        return

    if not os.path.isfile(material_config['model_path']):
        log_msg(f"未找到物资检测模型：{material_config['model_path']}")
        material_detector = None
        return

    class_path_value = material_config['class_path'] if os.path.isfile(material_config['class_path']) else None

    try:
        material_detector = MaterialDetector(
            model_path=material_config['model_path'],
            class_names=class_path_value,
            conf_threshold=material_config['conf'],
            iou_threshold=material_config['iou'],
            device=material_config['device'],
            imgsz=material_config['imgsz'],
        )
        log_msg(
            f"物资检测器已加载: model={material_config['model_path']} "
            f"device={material_detector.device} conf={material_config['conf']} iou={material_config['iou']}"
        )
    except Exception as e:
        material_detector = None
        log_msg(f"物资检测器加载失败: {e}")


def recognize_materials(img_bytes):
    if material_detector is None:
        raise RuntimeError('material detector is not initialized')
    result = material_detector.predict_jpeg_bytes(img_bytes)
    return {
        'ok': True,
        'counts': result.get('counts', {}),
        'total_objects': result.get('total_objects', 0),
        'detections': result.get('detections', []),
        'latency_ms': result.get('latency_ms', 0),
        'device': result.get('device', 'unknown'),
    }


def save_transaction_log(payload):
    timestamp = payload.get('timestamp') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tx_id = payload.get('tx_id', '')
    person = payload.get('person', '')
    expected_action = payload.get('expected_action', '')
    actual_action = payload.get('actual_action', '')
    before_counts = payload.get('before_counts', {})
    after_counts = payload.get('after_counts', {})
    delta = payload.get('delta', {})
    detail = payload.get('detail', {})
    client_id = payload.get('client_id', '')

    file_exists = os.path.isfile(TRANSACTION_LOG_FILE)
    with open(TRANSACTION_LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'Timestamp',
                'TxID',
                'Person',
                'Expected Action',
                'Actual Action',
                'Before Counts(JSON)',
                'After Counts(JSON)',
                'Delta(JSON)',
                'Detail(JSON)',
                'Client ID',
            ])
        writer.writerow([
            timestamp,
            tx_id,
            person,
            expected_action,
            actual_action,
            json.dumps(before_counts, ensure_ascii=False),
            json.dumps(after_counts, ensure_ascii=False),
            json.dumps(delta, ensure_ascii=False),
            json.dumps(detail, ensure_ascii=False),
            client_id,
        ])

    log_msg(
        f"交易记录已保存: {timestamp} | {person} | expected={expected_action} "
        f"actual={actual_action} | delta={json.dumps(delta, ensure_ascii=False)}"
    )

def save_material_log(timestamp, person, action, material):
    file_exists = os.path.isfile(LOG_FILE)
    try:
        with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Timestamp', 'Person', 'Action', 'Material Info'])
            writer.writerow([timestamp, person, action, material])
        log_msg(f"已保存物资记录: {timestamp} | {person} | {action} | {material}")
    except Exception as e:
        log_msg(f"保存物资记录失败: {e}")

def generate_qr(name, mat_id):
    if not os.path.exists(QR_DIR):
        os.makedirs(QR_DIR)
    data = f"Name:{name}, ID:{mat_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filepath = os.path.join(QR_DIR, f"{mat_id}_{name}.png")
    with open(filepath, "wb") as f:
        img.save(f)
    log_msg(f"生成二维码成功: {filepath}")
    return filepath

def handle_client(client_socket, client_address):
    log_msg(f"连接成功！来自 {client_address}")
    try:
        while server_running:
            data = client_socket.recv(1024)
            if not data:
                break
            
            cmd_parts = data.decode('utf-8').strip().split(",")
            cmd = cmd_parts[0]
            
            if cmd == "RECOGNIZE":
                total_len = int(cmd_parts[1])
                client_socket.send(b"ok")
                img_bytes = _recv_exact(client_socket, total_len)
                    
                if image_callback:
                    image_callback(img_bytes)
                    
                result = recognize_face(img_bytes)
                log_msg(f"识别请求完成: {result}")
                client_socket.send(result.encode('utf-8'))
                
            elif cmd == "RECOGNIZE_QR":
                total_len = int(cmd_parts[1])
                client_socket.send(b"ok")
                img_bytes = _recv_exact(client_socket, total_len)
                
                # Image callback optional for QR
                # if image_callback:
                #    image_callback(img_bytes)
                    
                result = recognize_qr(img_bytes)
                log_msg(f"QR识别请求完成: {result}")
                client_socket.send(result.encode('utf-8'))

            elif cmd == "DETECT_MATERIALS":
                total_len = int(cmd_parts[1])
                client_socket.send(b"ok")
                img_bytes = _recv_exact(client_socket, total_len)

                try:
                    result = recognize_materials(img_bytes)
                    log_msg(f"物资检测完成: total={result.get('total_objects', 0)}")
                except Exception as e:
                    result = {'ok': False, 'error': str(e)}
                    log_msg(f"物资检测失败: {e}")

                _send_json_payload(client_socket, result)

            elif cmd == "REGISTER":
                name = cmd_parts[1]
                total_len = int(cmd_parts[2])
                client_socket.send(b"ok")
                img_bytes = _recv_exact(client_socket, total_len)
                    
                if image_callback:
                    image_callback(img_bytes)
                    
                result = register_face(name, img_bytes)
                log_msg(f"录入请求完成 ({name}): {result}")
                client_socket.send(result.encode('utf-8'))
                
            elif cmd == "DATA":
                person = cmd_parts[1]
                action = cmd_parts[2]
                timestamp = cmd_parts[3]
                material = ",".join(cmd_parts[4:])
                save_material_log(timestamp, person, action, material)
                client_socket.send(b"Data Saved")

            elif cmd == "DATA_JSON":
                total_len = int(cmd_parts[1])
                client_socket.send(b"ok")
                payload_bytes = _recv_exact(client_socket, total_len)
                try:
                    payload = json.loads(payload_bytes.decode('utf-8'))
                    save_transaction_log(payload)
                    client_socket.send(b"Saved")
                except Exception as e:
                    client_socket.send(f"Error:{e}".encode('utf-8'))
                 
            elif cmd == "GEN_QR":
                mat_name = cmd_parts[1]
                mat_id = cmd_parts[2]
                filepath = generate_qr(mat_name, mat_id)
                client_socket.send(f"QR Generated: {filepath}".encode('utf-8'))
                
            elif cmd == "SYNC_MAT":
                if not os.path.exists(QR_DIR):
                    os.makedirs(QR_DIR)
                files = [f for f in os.listdir(QR_DIR) if f.endswith('.png')]
                client_socket.send(f"COUNT,{len(files)}".encode('utf-8'))
                
                for f in files:
                    resp = client_socket.recv(1024)
                    if resp != b'ok':
                        break
                    
                    filepath = os.path.join(QR_DIR, f)
                    with open(filepath, "rb") as img_file:
                        img_bytes = img_file.read()
                    
                    file_info = f"FILE,{f},{len(img_bytes)}"
                    client_socket.send(file_info.encode('utf-8'))
                    
                    resp = client_socket.recv(1024)
                    if resp == b'ready':
                        client_socket.sendall(img_bytes)
                
                client_socket.send(b"SYNC_DONE")
            else:
                client_socket.send(b"Unknown Command")
    except Exception as e:
        log_msg(f"客户端异常 {client_address}: {e}")
    finally:
        client_socket.close()
        log_msg(f"连接已断开: {client_address}")

def server_loop():
    global server_socket, server_running
    HOST = ''
    PORT = 8080
    ADDRESS = (HOST, PORT)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 允许地址重用
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind(ADDRESS)
        server_socket.listen(5)
        server_socket.settimeout(1.0)
        log_msg(f"TCP 服务器已启动，监听端口: {PORT}")
        
        while server_running:
            try:
                client_socket, client_address = server_socket.accept()
                client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address), daemon=True)
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if server_running:
                    log_msg(f"接收连接异常: {e}")
    except Exception as e:
        log_msg(f"服务器启动失败: {e}")
    finally:
        if server_socket:
            server_socket.close()
        log_msg("服务器已停止。")


def update_detector_settings(model_path, class_path, device, conf, iou, imgsz):
    init_material_detector(
        model_path=model_path,
        class_path=class_path,
        device=device,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
    )

def start_server_thread():
    global server_running
    if not server_running:
        server_running = True
        init_material_detector(
            model_path=material_config['model_path'],
            class_path=material_config['class_path'],
            device=material_config['device'],
            conf=material_config['conf'],
            iou=material_config['iou'],
            imgsz=material_config['imgsz'],
        )
        threading.Thread(target=server_loop, daemon=True).start()

def stop_server():
    global server_running
    server_running = False

class ServerUI:
    def __init__(self, root):
        self.root = root
        self.root.title("智能物资管理服务器")
        self.root.geometry("780x580")
        
        global log_callback
        log_callback = self.append_log
        
        global image_callback
        image_callback = self.update_image
        
        self.imgtk = None
        
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # --- Tab 1: 服务器控制与日志 ---
        tab_server = ttk.Frame(notebook)
        notebook.add(tab_server, text="服务器控制")
        
        control_frame = ttk.Frame(tab_server)
        control_frame.pack(fill=tk.X, pady=5)
        
        self.btn_start = ttk.Button(control_frame, text="启动服务器", command=self.ui_start_server)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        
        self.btn_stop = ttk.Button(control_frame, text="停止服务器", command=self.ui_stop_server, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        self.image_label = tk.Label(tab_server, text="等待接收图片...", bg="gray", height=15)
        self.image_label.pack(fill=tk.X, pady=5)
        
        self.log_text = tk.Text(tab_server, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)

        detector_frame = ttk.LabelFrame(tab_server, text="YOLO 物资检测配置")
        detector_frame.pack(fill=tk.X, pady=6)

        ttk.Label(detector_frame, text="模型路径:").grid(row=0, column=0, padx=5, pady=4, sticky=tk.W)
        self.entry_det_model = ttk.Entry(detector_frame, width=68)
        self.entry_det_model.grid(row=0, column=1, padx=5, pady=4, sticky=tk.W)
        self.entry_det_model.insert(0, material_config['model_path'])

        ttk.Label(detector_frame, text="类别文件:").grid(row=1, column=0, padx=5, pady=4, sticky=tk.W)
        self.entry_det_classes = ttk.Entry(detector_frame, width=68)
        self.entry_det_classes.grid(row=1, column=1, padx=5, pady=4, sticky=tk.W)
        self.entry_det_classes.insert(0, material_config['class_path'])

        ttk.Label(detector_frame, text="设备:").grid(row=2, column=0, padx=5, pady=4, sticky=tk.W)
        self.entry_det_device = ttk.Entry(detector_frame, width=10)
        self.entry_det_device.grid(row=2, column=1, padx=(5, 0), pady=4, sticky=tk.W)
        self.entry_det_device.insert(0, material_config['device'])

        ttk.Label(detector_frame, text="conf:").grid(row=2, column=1, padx=(95, 0), pady=4, sticky=tk.W)
        self.entry_det_conf = ttk.Entry(detector_frame, width=8)
        self.entry_det_conf.grid(row=2, column=1, padx=(140, 0), pady=4, sticky=tk.W)
        self.entry_det_conf.insert(0, str(material_config['conf']))

        ttk.Label(detector_frame, text="iou:").grid(row=2, column=1, padx=(220, 0), pady=4, sticky=tk.W)
        self.entry_det_iou = ttk.Entry(detector_frame, width=8)
        self.entry_det_iou.grid(row=2, column=1, padx=(255, 0), pady=4, sticky=tk.W)
        self.entry_det_iou.insert(0, str(material_config['iou']))

        ttk.Label(detector_frame, text="imgsz:").grid(row=2, column=1, padx=(335, 0), pady=4, sticky=tk.W)
        self.entry_det_imgsz = ttk.Entry(detector_frame, width=8)
        self.entry_det_imgsz.grid(row=2, column=1, padx=(385, 0), pady=4, sticky=tk.W)
        self.entry_det_imgsz.insert(0, str(material_config['imgsz']))

        ttk.Button(detector_frame, text="加载/更新检测器", command=self.ui_apply_detector).grid(
            row=3, column=1, padx=5, pady=6, sticky=tk.W
        )
        
        # --- Tab 2: 二维码生成 ---
        tab_qr = ttk.Frame(notebook)
        notebook.add(tab_qr, text="二维码生成")
        
        ttk.Label(tab_qr, text="物资名称:").grid(row=0, column=0, padx=5, pady=10, sticky=tk.W)
        self.entry_qr_name = ttk.Entry(tab_qr, width=30)
        self.entry_qr_name.grid(row=0, column=1, padx=5, pady=10)
        
        ttk.Label(tab_qr, text="物资编号:").grid(row=1, column=0, padx=5, pady=10, sticky=tk.W)
        self.entry_qr_id = ttk.Entry(tab_qr, width=30)
        self.entry_qr_id.grid(row=1, column=1, padx=5, pady=10)
        
        btn_gen_qr = ttk.Button(tab_qr, text="生成二维码", command=self.ui_generate_qr)
        btn_gen_qr.grid(row=2, column=0, columnspan=2, pady=20)
        
        # --- Tab 3: 人脸录入 ---
        tab_face = ttk.Frame(notebook)
        notebook.add(tab_face, text="人脸录入")
        
        ttk.Label(tab_face, text="姓名:").grid(row=0, column=0, padx=5, pady=10, sticky=tk.W)
        self.entry_face_name = ttk.Entry(tab_face, width=30)
        self.entry_face_name.grid(row=0, column=1, padx=5, pady=10, sticky=tk.W)
        
        ttk.Label(tab_face, text="图片文件:").grid(row=1, column=0, padx=5, pady=10, sticky=tk.W)
        self.entry_face_path = ttk.Entry(tab_face, width=30)
        self.entry_face_path.grid(row=1, column=1, padx=5, pady=10, sticky=tk.W)
        
        btn_browse = ttk.Button(tab_face, text="浏览...", command=self.ui_browse_image)
        btn_browse.grid(row=1, column=2, padx=5, pady=10)
        
        btn_register = ttk.Button(tab_face, text="录入并保存", command=self.ui_register_face)
        btn_register.grid(row=2, column=0, columnspan=3, pady=20)
        
        # 预加载人脸
        threading.Thread(target=load_known_faces, daemon=True).start()

    def ui_start_server(self):
        start_server_thread()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

    def ui_stop_server(self):
        stop_server()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    def ui_apply_detector(self):
        model_path = self.entry_det_model.get().strip()
        class_path = self.entry_det_classes.get().strip()
        device = self.entry_det_device.get().strip() or '0'

        try:
            conf = float(self.entry_det_conf.get().strip())
            iou = float(self.entry_det_iou.get().strip())
            imgsz = int(self.entry_det_imgsz.get().strip())
        except ValueError:
            messagebox.showwarning("警告", "conf/iou/imgsz 参数格式错误")
            return

        update_detector_settings(
            model_path=model_path,
            class_path=class_path,
            device=device,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
        )
        messagebox.showinfo("完成", "物资检测器配置已更新，请查看日志确认是否加载成功")

    def ui_generate_qr(self):
        name = self.entry_qr_name.get().strip()
        mat_id = self.entry_qr_id.get().strip()
        if not name or not mat_id:
            messagebox.showwarning("警告", "请输入物资名称和编号")
            return
        filepath = generate_qr(name, mat_id)
        messagebox.showinfo("成功", f"二维码已生成:\n{filepath}")

    def ui_browse_image(self):
        filepath = filedialog.askopenfilename(title="选择图片", filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")])
        if filepath:
            self.entry_face_path.delete(0, tk.END)
            self.entry_face_path.insert(0, filepath)

    def ui_register_face(self):
        name = self.entry_face_name.get().strip()
        filepath = self.entry_face_path.get().strip()
        if not name or not filepath:
            messagebox.showwarning("警告", "请输入姓名并选择图片文件")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("错误", "图片文件不存在")
            return
        
        try:
            with open(filepath, "rb") as f:
                img_bytes = f.read()
            result = register_face(name, img_bytes)
            log_msg(f"本地人脸录入 ({name}): {result}")
            if "Success" in result:
                messagebox.showinfo("成功", f"人脸录入成功: {name}")
                self.entry_face_name.delete(0, tk.END)
                self.entry_face_path.delete(0, tk.END)
            else:
                messagebox.showwarning("失败", f"人脸录入失败: {result}")
        except Exception as e:
            messagebox.showerror("错误", f"录入过程发生异常: {e}")

    def update_image(self, img_bytes):
        def _update():
            try:
                img = np.asarray(bytearray(img_bytes), dtype="uint8")
                img = cv2.imdecode(img, cv2.IMREAD_COLOR)
                if img is not None:
                    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    h, w = rgb_img.shape[:2]
                    max_size = 300
                    if w > max_size or h > max_size:
                        scale = max_size / max(w, h)
                        rgb_img = cv2.resize(rgb_img, (int(w*scale), int(h*scale)))
                    
                    pil_img = Image.fromarray(rgb_img)
                    self.imgtk = ImageTk.PhotoImage(image=pil_img)
                    self.image_label.config(image=self.imgtk, text="", height=0)
            except Exception as e:
                log_msg(f"显示图片异常: {e}")
                
        self.root.after(0, _update)

    def append_log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="智能物资管理服务器")
    parser.add_argument('--type', choices=['cli', 'ui'], default='ui', help='运行方式: cli 或 ui')
    parser.add_argument('--material-model', default=DEFAULT_MATERIAL_MODEL, help='物资检测模型路径 (.pt/.onnx)')
    parser.add_argument('--material-classes', default=DEFAULT_MATERIAL_CLASSES, help='物资类别文件路径')
    parser.add_argument('--material-device', default='0', help='物资检测设备，如 0/cpu/cuda:0')
    parser.add_argument('--material-conf', type=float, default=0.35, help='物资检测置信度阈值')
    parser.add_argument('--material-iou', type=float, default=0.45, help='物资检测 IoU 阈值')
    parser.add_argument('--material-imgsz', type=int, default=640, help='物资检测输入尺寸')
    args = parser.parse_args()

    material_config['model_path'] = args.material_model
    material_config['class_path'] = args.material_classes
    material_config['device'] = str(args.material_device)
    material_config['conf'] = float(args.material_conf)
    material_config['iou'] = float(args.material_iou)
    material_config['imgsz'] = int(args.material_imgsz)

    if args.type == 'cli':
        print("以命令行(CLI)模式运行服务器...")
        load_known_faces()
        init_material_detector(
            model_path=material_config['model_path'],
            class_path=material_config['class_path'],
            device=material_config['device'],
            conf=material_config['conf'],
            iou=material_config['iou'],
            imgsz=material_config['imgsz'],
        )
        start_server_thread()
        try:
            while True:
                # 阻塞主线程，保持服务器运行
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n正在停止服务器...")
            stop_server()
    else:
        root = tk.Tk()
        app = ServerUI(root)
        root.protocol("WM_DELETE_WINDOW", lambda: (stop_server(), root.destroy()))
        root.mainloop()
