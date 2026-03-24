#-*- coding: UTF-8 -*- 
import cv2
import time
import socket

# Server IP address
HOST = '172.27.86.36'
# Server port
PORT = 8080
ADDRESS = (HOST, PORT)

# Create a socket
tcpClient = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# Connect to remote IP
tcpClient.connect(ADDRESS)

# Timer
start = time.perf_counter()
# Read image
cv_image = cv2.imread("unknown/people.jpg")
# Compress image
img_encode = cv2.imencode('.jpg', cv_image, [cv2.IMWRITE_JPEG_QUALITY, 99])[1]
# Convert to byte stream
bytedata = img_encode.tobytes()
# Flag data, including the length of the byte stream to be sent, separated by ','
flag_data = (str(len(bytedata))).encode() + ",".encode() + " ".encode()
tcpClient.send(flag_data)
# Receive server response
data = tcpClient.recv(1024)
if ("ok" == data.decode()):
    # Server has received flag data, start sending image byte stream data
    tcpClient.send(bytedata)
# Receive server response
data = tcpClient.recv(1024)
if ("ok" == data.decode()):
    # Calculate send completion delay
    print("Delay: " + str(int((time.perf_counter() - start) * 1000)) + "ms")
