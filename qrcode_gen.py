import qrcode
from PIL import Image

# 1. 配置二维码参数
qr = qrcode.QRCode(
    version=4,  # 尺寸从 1 到 40，1 最小。None 表示自动根据内容大小调整
    error_correction=qrcode.constants.ERROR_CORRECT_H,  # 纠错级别：L(7%), M(15%), Q(25%), H(30%)
    box_size=10,  # 每个小格子的像素大小
    border=4,     # 边框厚度（最小为 4）
)

# 2. 添加数据
data = "Hello, Python QR Code!"
qr.add_data(data)
qr.make(fit=True)  # 自动调整 version 以适应数据

# 3. 创建图像对象（自定义颜色）
# fill_color: 二维码颜色, back_color: 背景颜色
img = qr.make_image(fill_color="black", back_color="white")

# 4. (可选) 嵌入 Logo
# 如果不需要 Logo，跳过此步直接 save
# logo_path = "logo.png"  # 确保当前目录下有这张图片
# if logo_path:
#     try:
#         logo = Image.open(logo_path)
#         # 计算 Logo 放入的大小 (通常是二维码宽度的 1/4)
#         img_width, img_height = img.size
#         logo_size = int(img_width * 0.2) 
#         logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        
#         # 计算粘贴位置 (居中)
#         logo_pos = ((img_width - logo_size) // 2, (img_height - logo_size) // 2)
        
#         # 将 Logo 粘贴到二维码上
#         # 使用 alpha 通道混合，防止 Logo 背景覆盖二维码
#         if logo.mode == 'RGBA':
#             img.paste(logo, logo_pos, logo)
#         else:
#             img.paste(logo, logo_pos)
            
#         print("已嵌入 Logo")
#     except FileNotFoundError:
#         print(f"未找到 Logo 文件 {logo_path}，将生成无 Logo 版本")

# 5. 保存结果
img.save("qrcode/qrcode_custom.png")
print("自定义二维码已生成：qrcode_custom.png")