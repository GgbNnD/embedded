import cv2
import numpy as np
from pyzbar import pyzbar
from PIL import Image

def detect_and_decode_qr(image_path):
    # 1. Read image
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Cannot load image {image_path}")
        return []

    original_img = img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Image preprocessing (Key step: dealing with complex backgrounds)
    # Use adaptive thresholding, better than global thresholding for uneven lighting and complex backgrounds
    # blockSize: neighborhood size (must be odd), C: constant subtracted from the mean
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )

    # Optional: Morphological operations to remove noise and connect broken lines
    kernel = np.ones((3, 3), np.uint8)
    dilated_binary = cv2.dilate(binary, kernel, iterations=2)
    eroded_binary = cv2.erode(dilated_binary, kernel, iterations=1)

    # 3. Find contours
    contours, _ = cv2.findContours(eroded_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    qr_results = []
    found_qr_regions = []

    # 4. Filter possible QR code regions
    # QR codes usually have a large area and approximately rectangular shape
    img_area = img.shape[0] * img.shape[1]
    
    potential_rois = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # Filter noise that is too small (< 1% of image area) and regions that are too large (whole background)
        if 0.01 * img_area < area < 0.9 * img_area:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = float(w)/h
            
            # QR code aspect ratio is usually close to 1 (between 0.8 - 1.2)
            if 0.8 <= aspect_ratio <= 1.2:
                potential_rois.append((x, y, w, h))

    # If no obvious geometric contours are found, try decoding the full image or binary image directly
    # Because some QR code backgrounds are very clean, contour finding might fail instead
    if not potential_rois:
        print("No obvious contours detected, trying full image decoding directly...")
        # Note: rect format returned by pyzbar is usually (left, top, width, height)
        decoded_objects = pyzbar.decode(Image.fromarray(cv2.cvtColor(original_img, cv2.COLOR_BGR2RGB)))
        
        if decoded_objects:
            for obj in decoded_objects:
                left, top, width, height = obj.rect
                # Unified format: convert to (x_start, y_start, x_end, y_end)
                location = (left, top, left + width, top + height)
                
                qr_results.append({
                    "data": obj.data.decode('utf-8'),
                    "type": obj.type,
                    "location_in_original": location
                })
                
                # If recognition is successful in full image mode, draw a box for easy viewing
                cv2.rectangle(original_img, (left, top), (left + width, top + height), (255, 0, 0), 2)
        
        # Save result and return
        cv2.imwrite("qrcode/result_detected.jpg", original_img)
        return qr_results

    # 5. Decode the filtered regions (ROI strategy)
    # Merge overlapping regions to avoid duplicate decoding
    final_rois = []
    for r in potential_rois:
        is_new = True
        for existing in final_rois:
            if is_overlapping(r, existing):
                is_new = False
                break
        if is_new:
            final_rois.append(r)

    for (x, y, w, h) in final_rois:
        # Add some padding to prevent cutting off positioning patterns
        padding = int(w * 0.1)
        x_start = max(0, x - padding)
        y_start = max(0, y - padding)
        x_end = min(img.shape[1], x + w + padding)
        y_end = min(img.shape[0], y + h + padding)

        # Crop Region of Interest (ROI)
        roi = original_img[y_start:y_end, x_start:x_end]
        
        # 尝试解码 ROI
        # pyzbar 接受 PIL Image 对象
        pil_roi = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
        decoded_objects = pyzbar.decode(pil_roi)

        for obj in decoded_objects:
            qr_data = obj.data.decode('utf-8')
            # 记录结果，同时记录在原图中的大致位置
            qr_results.append({
                "data": qr_data,
                "type": obj.type,
                "location_in_original": (x_start, y_start, x_end, y_end)
            })
            
            # 可视化调试 (可选)
            cv2.rectangle(original_img, (x_start, y_start), (x_end, y_end), (0, 255, 0), 2)
            cv2.putText(original_img, qr_data[:20] + "...", (x_start, y_start - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # 显示结果图片 (按 q 退出)
    # cv2.imshow("Detected QR Codes", original_img)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    # 保存带标记的图片
    cv2.imwrite("qrcode/result_detected.jpg", original_img)
    
    return qr_results

def is_overlapping(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    
    # 简单的矩形重叠判断
    if x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2:
        return True
    return False

# --- 主程序 ---
if __name__ == "__main__":
    # 替换为你的图片路径
    image_file = "qrcode/qrcode_background.jpg" 
    
    # 如果没有测试图片，生成一个用于演示
    # import qrcode
    # qr = qrcode.make("https://www.python.org")
    # qr.save(image_file)
    # print(f"已生成测试图片: {image_file} (实际使用时请替换为复杂背景图片)")

    results = detect_and_decode_qr(image_file)

    if results:
        print(f"\n成功识别到 {len(results)} 个二维码:")
        for i, res in enumerate(results):
            print(f"[{i+1}] 内容: {res['data']}")
            print(f"    类型: {res['type']}")
            print(f"    位置: {res['location_in_original']}")
    else:
        print("\n未识别到二维码。")