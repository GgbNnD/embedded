import os
import cv2
import qrcode

class QRManager:
    def __init__(self, qr_dir='qrcode'):
        self.qr_dir = qr_dir
        if not os.path.exists(self.qr_dir):
            os.makedirs(self.qr_dir)
        self.detector = cv2.QRCodeDetector()

    def generate_qr(self, name, mat_id):
        data = f"Name:{name}, ID:{mat_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        filepath = os.path.join(self.qr_dir, f"{mat_id}_{name}.png")
        with open(filepath, "wb") as f:
            img.save(f)
        return filepath

    def recognize_qr(self, frame):
        data, bbox, _ = self.detector.detectAndDecode(frame)
        if data:
            return data
        return None
