import face_recognition
import cv2
import os
import numpy as np
from pathlib import Path

# 配置文件夹路径
KNOWN_FACES_DIR = 'known'
UNKNOWN_FACES_DIR = 'unknown'
OUTPUT_DIR = 'output'
TOLERANCE = 0.6  # 人脸匹配阈值，越小越严格
FRAME_THICKNESS = 3  # 边框粗细
FONT_THICKNESS = 2  # 字体粗细
MODEL = 'hog'  # 检测模型: 'hog' (CPU快) 或 'cnn' (GPU准但慢)

# 创建输出目录
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

print("正在加载已知人脸...")

known_faces = []
known_names = []

# 1. 加载已知人脸
for filename in os.listdir(KNOWN_FACES_DIR):
    if filename.endswith(('.png', '.jpg', '.jpeg', '.JPEG', '.JPG')):
        # 构建完整路径
        path = os.path.join(KNOWN_FACES_DIR, filename)
        
        # 加载图片
        image = face_recognition.load_image_file(path)
        
        # 检测人脸位置
        locations = face_recognition.face_locations(image, model=MODEL)
        
        # 获取人脸编码 (假设每张图片只有一个人，取第一个)
        encodings = face_recognition.face_encodings(image,locations)
        
        if len(encodings) > 0:
            # 使用文件名（不含扩展名）作为名字
            name = os.path.splitext(filename)[0]
            known_faces.append(encodings[0])
            known_names.append(name)
            print(f"已录入: {name}")
        else:
            print(f"警告: 在 {filename} 中未检测到人脸。")

if len(known_faces) == 0:
    print("错误: known 文件夹中没有找到任何有效的人脸！请检查图片。")
    exit(1)

print(f"\n已知人脸库加载完成，共 {len(known_names)} 人。开始识别未知图片...\n")

# 2. 处理未知人脸
for filename in os.listdir(UNKNOWN_FACES_DIR):
    if filename.endswith(('.png', '.jpg', '.jpeg', '.JPEG', '.JPG')):
        path = os.path.join(UNKNOWN_FACES_DIR, filename)
        print(f"正在处理: {filename}")
        
        # 加载图片
        image = face_recognition.load_image_file(path)
        
        # 检测人脸位置
        locations = face_recognition.face_locations(image, model=MODEL)
        
        # 获取人脸编码
        encodings = face_recognition.face_encodings(image, locations)
        
        # 将 PIL 图片转换为 OpenCV 格式 (RGB -> BGR) 以便绘图
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # 遍历检测到的每一张人脸
        for face_location, face_encoding in zip(locations, encodings):
            top, right, bottom, left = face_location
            
            # 默认标记为 Unknown
            name = "Unknown"
            color = (0, 0, 255)  # 红色表示未知 (BGR)
            
            # 与已知人脸比对
            matches = face_recognition.compare_faces(known_faces, face_encoding, TOLERANCE)
            
            # 如果匹配成功，找出最相似的一个
            if True in matches:
                # 计算距离，距离越小越相似
                distances = face_recognition.face_distance(known_faces, face_encoding)
                first_match_index = np.argmin(distances)
                
                if matches[first_match_index]:
                    name = known_names[first_match_index]
                    color = (0, 255, 0)  # 绿色表示已知 (BGR)
            print(name)
            
            # --- 绘制边框 ---
            # cv2.rectangle(图像, 左上角坐标, 右下角坐标, 颜色(BGR), 线宽)
            # 注意：face_location 返回的是 (top, right, bottom, left)
            cv2.rectangle(image_bgr, (left, top), (right, bottom), color, FRAME_THICKNESS)
            
            # --- 绘制姓名标签背景 ---
            # 在人脸下方画一个实心矩形作为文字背景
            label_top = bottom
            label_bottom = bottom + 35
            cv2.rectangle(image_bgr, (left, label_top), (right, label_bottom), color, cv2.FILLED)
            
            # --- 绘制姓名文字 ---
            # cv2.putText(图像, 文字, 左下角坐标, 字体, 缩放, 颜色, 厚度)
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(image_bgr, name, (left + 6, label_bottom - 6), font, 0.75, (255, 255, 255), FONT_THICKNESS)
        
        # 保存结果
        output_path = os.path.join(OUTPUT_DIR, filename)
        cv2.imwrite(output_path, image_bgr)
        print(f" -> 识别完成，结果已保存至: {output_path}")

print("\n所有图片处理完毕！")