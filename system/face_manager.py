import os
import cv2
import numpy as np
import face_recognition

class FaceManager:
    def __init__(self, known_dir='known', tolerance=0.5):
        self.known_dir = known_dir
        self.tolerance = tolerance
        self.known_faces = []
        self.known_names = []
        if not os.path.exists(self.known_dir):
            os.makedirs(self.known_dir)
        self.load_known_faces()

    def load_known_faces(self):
        self.known_faces = []
        self.known_names = []
        print("Loading known faces...")
        for filename in os.listdir(self.known_dir):
            if filename.endswith(('.png', '.jpg', '.jpeg', '.JPEG', '.JPG')):
                path = os.path.join(self.known_dir, filename)
                image = face_recognition.load_image_file(path)
                locations = face_recognition.face_locations(image)
                encodings = face_recognition.face_encodings(image, locations)
                if len(encodings) > 0:
                    name = os.path.splitext(filename)[0]
                    self.known_faces.append(encodings[0])
                    self.known_names.append(name)
                    print(f"Loaded: {name}")
        print(f"Known faces loaded, total: {len(self.known_names)}")

    def recognize_face(self, frame):
        rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb_img)
        encodings = face_recognition.face_encodings(rgb_img, locations)
        
        recognized_names = []
        for face_encoding in encodings:
            name = "Unknown"
            if self.known_faces:
                matches = face_recognition.compare_faces(self.known_faces, face_encoding, self.tolerance)
                if True in matches:
                    distances = face_recognition.face_distance(self.known_faces, face_encoding)
                    best_match_index = np.argmin(distances)
                    if matches[best_match_index]:
                        name = self.known_names[best_match_index]
            recognized_names.append(name)
        
        if not recognized_names:
            return "No face detected"
        return ",".join(recognized_names)

    def register_face(self, name, image_path):
        image = face_recognition.load_image_file(image_path)
        locations = face_recognition.face_locations(image)
        encodings = face_recognition.face_encodings(image, locations)
        
        if len(encodings) > 0:
            target_path = os.path.join(self.known_dir, f"{name}.jpg")
            img = cv2.imread(image_path)
            cv2.imwrite(target_path, img)
            self.known_faces.append(encodings[0])
            self.known_names.append(name)
            return True, "Register Success"
        else:
            return False, "No face detected, register failed"
