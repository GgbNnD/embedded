import csv
import os

class DataLogger:
    def __init__(self, log_file='material_log.csv'):
        self.log_file = log_file

    def log_action(self, timestamp, person, action, material):
        file_exists = os.path.isfile(self.log_file)
        try:
            with open(self.log_file, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['Timestamp', 'Person', 'Action', 'Material Info'])
                writer.writerow([timestamp, person, action, material])
            return True, f"Logged: {timestamp} | {person} | {action} | {material}"
        except Exception as e:
            return False, f"Log failed: {e}"
