#-*- coding: UTF-8 -*- 
import cv2
import time
import socket

# 服务端ip地址
HOST = '172.27.86.36'
# 服务端端口号
PORT = 8080
ADDRESS = (HOST, PORT)

# 创建一个套接字
tcpClient = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# 连接远程ip
tcpClient.connect(ADDRESS)

# 计时
start = time.perf_counter()
# 读取图像
cv_image = cv2.imread("unknown/people.jpg")
# 压缩图像
img_encode = cv2.imencode('.jpg', cv_image, [cv2.IMWRITE_JPEG_QUALITY, 99])[1]
# 转换为字节流
bytedata = img_encode.tobytes()
# 标志数据，包括待发送的字节流长度等数据，用‘,’隔开
flag_data = (str(len(bytedata))).encode() + ",".encode() + " ".encode()
tcpClient.send(flag_data)
# 接收服务端的应答
data = tcpClient.recv(1024)
if ("ok" == data.decode()):
    # 服务端已经收到标志数据，开始发送图像字节流数据
    tcpClient.send(bytedata)
# 接收服务端的应答
data = tcpClient.recv(1024)
if ("ok" == data.decode()):
    # 计算发送完成的延时
    print("延时：" + str(int((time.perf_counter() - start) * 1000)) + "ms")
