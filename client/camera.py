import cv2

# 0 represents the default camera (usually the first detected device)
# If it is a Raspberry Pi dedicated camera and not mapped to /dev/video0, you may need to try 1 or other numbers
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Cannot open camera")
    exit()

print("Camera started, press 'q' to exit...")

while True:
    # Read frame
    ret, frame = cap.read()
    
    if not ret:
        print("Cannot receive frame (stream end?). Exiting ...")
        break
    
    # Display result
    cv2.imshow('Camera Feed', frame)
    
    # 等待 1 毫秒，检测是否按下 'q' 键
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# 释放资源
cap.release()
cv2.destroyAllWindows()