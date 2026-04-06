import time
import RPi.GPIO as GPIO

class HardwareManager:
    def __init__(self, servo_pin=14):
        self.servo_pin = servo_pin
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.servo_pin, GPIO.OUT)
            self.pwm = GPIO.PWM(self.servo_pin, 50)
            self.pwm.start(0)
            self.close_door()
        except Exception as e:
            print(f"Failed to initialize GPIO: {e}")
            self.pwm = None

    def set_angle(self, angle):
        if not self.pwm:
            return
        angle = max(0, min(180, angle))
        duty = 2.5 + (10.0 * angle / 180.0)
        GPIO.output(self.servo_pin, True)
        self.pwm.ChangeDutyCycle(duty)
        time.sleep(0.5)
        GPIO.output(self.servo_pin, False)
        self.pwm.ChangeDutyCycle(0)

    def close_door(self):
        self.set_angle(0)
        
    def open_door(self):
        self.set_angle(90)

    def cleanup(self):
        if self.pwm:
            self.pwm.stop()
            GPIO.cleanup()
