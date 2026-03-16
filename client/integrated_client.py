import socket
import cv2
import os

HOST = '127.0.0.1'
PORT = 8080

def send_image_for_recognition(image_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        
        with open(image_path, "rb") as f:
            img_bytes = f.read()
            
        cmd = f"RECOGNIZE,{len(img_bytes)}"
        s.sendall(cmd.encode('utf-8'))
        
        resp = s.recv(1024)
        if resp == b'ok':
            s.sendall(img_bytes)
            result = s.recv(1024)
            print(f"识别结果: {result.decode('utf-8')}")

def register_face(name, image_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        
        with open(image_path, "rb") as f:
            img_bytes = f.read()
            
        cmd = f"REGISTER,{name},{len(img_bytes)}"
        s.sendall(cmd.encode('utf-8'))
        
        resp = s.recv(1024)
        if resp == b'ok':
            s.sendall(img_bytes)
            result = s.recv(1024)
            print(f"录入结果: {result.decode('utf-8')}")

def send_material_data(person, action, material):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        
        cmd = f"DATA,{person},{action},{material}"
        s.sendall(cmd.encode('utf-8'))
        
        result = s.recv(1024)
        print(f"数据保存结果: {result.decode('utf-8')}")

def generate_qr(name, mat_id):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        cmd = f"GEN_QR,{name},{mat_id}"
        s.sendall(cmd.encode('utf-8'))
        result = s.recv(1024)
        print(f"服务器回复: {result.decode('utf-8')}")

if __name__ == "__main__":
    print("选择操作:")
    print("1. 人脸录入 (REGISTER)")
    print("2. 人脸识别 (RECOGNIZE)")
    print("3. 发送物资数据 (DATA)")
    print("4. 生成物资二维码 (GEN_QR)")
    
    choice = input("请输入选项: ")
    
    if choice == "1":
        name = input("输入姓名: ")
        img_path = input("输入图片路径: ")
        if os.path.exists(img_path):
            register_face(name, img_path)
        else:
            print("文件不存在")
    elif choice == "2":
        img_path = input("输入需识别图片路径: ")
        if os.path.exists(img_path):
            send_image_for_recognition(img_path)
        else:
            print("文件不存在")
    elif choice == "3":
        person = input("人员姓名: ")
        action = input("进出状态(入库/出库): ")
        material = input("物资信息: ")
        send_material_data(person, action, material)
    elif choice == "4":
        name = input("物资名称: ")
        mat_id = input("物资编号: ")
        generate_qr(name, mat_id)
