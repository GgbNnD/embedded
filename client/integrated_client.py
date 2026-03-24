import socket
import cv2
import os

HOST = '192.168.168.149'
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
            print(f"Recognition result: {result.decode('utf-8')}")

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
            print(f"Registration result: {result.decode('utf-8')}")

def send_material_data(person, action, material):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        
        cmd = f"DATA,{person},{action},{material}"
        s.sendall(cmd.encode('utf-8'))
        
        result = s.recv(1024)
        print(f"Data save result: {result.decode('utf-8')}")

def generate_qr(name, mat_id):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        cmd = f"GEN_QR,{name},{mat_id}"
        s.sendall(cmd.encode('utf-8'))
        result = s.recv(1024)
        print(f"Server reply: {result.decode('utf-8')}")

if __name__ == "__main__":
    print("Select operation:")
    print("1. Face Registration (REGISTER)")
    print("2. Face Recognition (RECOGNIZE)")
    print("3. Send Material Data (DATA)")
    print("4. Generate Material QR (GEN_QR)")
    
    choice = input("Enter option: ")
    
    if choice == "1":
        name = input("Enter name: ")
        img_path = input("Enter image path: ")
        if os.path.exists(img_path):
            register_face(name, img_path)
        else:
            print("File does not exist")
    elif choice == "2":
        img_path = input("Enter image path for recognition: ")
        if os.path.exists(img_path):
            send_image_for_recognition(img_path)
        else:
            print("File does not exist")
    elif choice == "3":
        person = input("Person name: ")
        action = input("Status (Inbound/Outbound): ")
        material = input("Material info: ")
        send_material_data(person, action, material)
    elif choice == "4":
        name = input("Material name: ")
        mat_id = input("Material ID: ")
        generate_qr(name, mat_id)
