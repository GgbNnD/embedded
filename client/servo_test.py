import RPi.GPIO as GPIO
import time

# 设置GPIO模式为BCM编码
GPIO.setmode(GPIO.BCM)

# 舵机连接的GPIO引脚
SERVO_PIN = 14

# 将GPIO引脚设置为输出模式
GPIO.setup(SERVO_PIN, GPIO.OUT)

# 创建PWM实例，设置频率为50Hz（舵机控制的通用频率）
pwm = GPIO.PWM(SERVO_PIN, 50)

# 启动PWM，初始占空比设为0（不产生转动）
pwm.start(0)

def set_angle(angle):
    """
    控制舵机转动到指定角度 (0-180度)
    一般舵机的脉冲宽度范围在0.5ms~2.5ms周期为20ms(50Hz)
    对应占空比: 2.5% ~ 12.5%
    """
    # 限制角度在0到180度之间
    angle = max(0, min(180, angle))
    
    # 计算对应的占空比
    duty = 2.5 + (10.0 * angle / 180.0)
    
    # 允许PWM输出并改变占空比
    GPIO.output(SERVO_PIN, True)
    pwm.ChangeDutyCycle(duty)
    
    # 给予舵机足够的时间转动到指定位置
    time.sleep(0.5)
    
    # 转动后将占空比归零，可以防止舵机抖动发热
    GPIO.output(SERVO_PIN, False)
    pwm.ChangeDutyCycle(0)

try:
    print("开始舵机测试 (接在 GPIO 14 上)... 按 Ctrl+C 退出。")
    while True:
        print("舵机转动至 0 度")
        set_angle(0)
        time.sleep(1)
        
        print("舵机转动至 90 度")
        set_angle(90)
        time.sleep(1)
        
        print("舵机转动至 170 度")
        set_angle(170)
        time.sleep(1)

except KeyboardInterrupt:
    print("\n用户中断测试")
finally:
    # 停止PWM并清理GPIO资源
    pwm.stop()
    GPIO.cleanup()
    print("GPIO资源已释放")
