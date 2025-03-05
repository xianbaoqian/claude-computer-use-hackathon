import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
                            QScrollArea, QSplitter)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import requests
from gradio_client import Client, handle_file
from PIL import Image, ImageDraw
from io import BytesIO
import re

class WorkerThread(QThread):
    """Thread for running API calls without freezing the UI"""
    finished = pyqtSignal(list, object)
    error = pyqtSignal(str)
    
    def __init__(self, client, image_path, system_prompt, user_prompt, chat_history):
        super().__init__()
        self.client = client
        self.image_path = image_path
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.chat_history = chat_history
    
    def run(self):
        try:
            result = self.client.predict(
                image_input=handle_file(self.image_path) if self.image_path else None,
                system_prompt=self.system_prompt,
                user_prompt=self.user_prompt,
                chat_history=self.chat_history,
                api_name="/generate_response"
            )
            self.finished.emit(result[0], result[1])
        except Exception as e:
            self.error.emit(str(e))

class MagmaDesktopApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.api_url = "http://127.0.0.1:7860/"
        self.client = Client(self.api_url)
        self.image_path = None
        self.chat_history = []
        
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Magma Desktop")
        self.setGeometry(100, 100, 1200, 800)
        
        # Updated styling for better compatibility with dark mode
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2D2D2D;
                color: #FFFFFF;
            }
            QLabel {
                font-weight: bold;
                margin-top: 10px;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #0071e3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0077ED;
            }
            QPushButton:pressed {
                background-color: #005BBF;
            }
            QLineEdit, QTextEdit {
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
                background-color: #3D3D3D;
                color: #FFFFFF;
            }
            QScrollArea {
                border: none;
                background-color: #2D2D2D;
            }
            QSplitter {
                background-color: #2D2D2D;
            }
            QStatusBar {
                background-color: #2D2D2D;
                color: #FFFFFF;
            }
        """)
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # Left panel - inputs
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(10)
        
        # API URL
        api_layout = QHBoxLayout()
        api_layout.addWidget(QLabel("API URL:"))
        self.api_input = QLineEdit(self.api_url)
        self.api_input.setPlaceholderText("Enter Gradio API URL")
        api_layout.addWidget(self.api_input)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_to_api)
        api_layout.addWidget(self.connect_btn)
        left_layout.addLayout(api_layout)
        
        # Image section
        left_layout.addWidget(QLabel("Image:"))
        image_layout = QHBoxLayout()
        self.image_url_input = QLineEdit()
        self.image_url_input.setPlaceholderText("Enter image URL or upload")
        image_layout.addWidget(self.image_url_input)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_image)
        image_layout.addWidget(self.browse_btn)
        left_layout.addLayout(image_layout)
        
        # System prompt
        left_layout.addWidget(QLabel("System Prompt:"))
        self.system_prompt = QLineEdit("You are agent that can see, talk and act.")
        left_layout.addWidget(self.system_prompt)
        
        # User prompt
        left_layout.addWidget(QLabel("Your Question:"))
        self.user_prompt = QLineEdit()
        self.user_prompt.setPlaceholderText("What is in this image?")
        left_layout.addWidget(self.user_prompt)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.submit_btn = QPushButton("Submit")
        self.submit_btn.clicked.connect(self.submit_query)
        button_layout.addWidget(self.submit_btn)
        
        self.clear_btn = QPushButton("Clear Conversation")
        self.clear_btn.clicked.connect(self.clear_conversation)
        button_layout.addWidget(self.clear_btn)
        left_layout.addLayout(button_layout)
        
        # Status message
        self.status_message = QLabel("")
        left_layout.addWidget(self.status_message)
        
        left_panel.setLayout(left_layout)
        
        # Right panel - split for conversation and images
        right_panel = QSplitter(Qt.Vertical)
        
        # Conversation area
        conversation_widget = QWidget()
        conversation_layout = QVBoxLayout()
        conversation_layout.setContentsMargins(20, 20, 20, 20)
        conversation_layout.addWidget(QLabel("Conversation:"))
        self.conversation_area = QTextEdit()
        self.conversation_area.setReadOnly(True)
        self.conversation_area.setStyleSheet("font-size: 14px; line-height: 1.4;")
        conversation_layout.addWidget(self.conversation_area)
        conversation_widget.setLayout(conversation_layout)
        right_panel.addWidget(conversation_widget)
        
        # Image display area
        image_display_widget = QWidget()
        image_display_layout = QVBoxLayout()
        image_display_layout.setContentsMargins(20, 20, 20, 20)
        image_display_layout.addWidget(QLabel("Image with Bounding Box:"))
        
        # Create a scroll area for the image
        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setAlignment(Qt.AlignCenter)
        
        self.image_display = QLabel("No image loaded")
        self.image_display.setAlignment(Qt.AlignCenter)
        self.image_display.setMinimumHeight(300)
        
        image_scroll.setWidget(self.image_display)
        image_display_layout.addWidget(image_scroll)
        
        image_display_widget.setLayout(image_display_layout)
        right_panel.addWidget(image_display_widget)
        
        # Add panels to main layout
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 2)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
    
    def connect_to_api(self):
        """Connect to the Gradio API"""
        try:
            self.api_url = self.api_input.text()
            self.client = Client(self.api_url)
            self.status_message.setText(f"Connected to {self.api_url}")
            self.status_message.setStyleSheet("color: #00FF00")
        except Exception as e:
            self.status_message.setText(f"Error connecting: {str(e)}")
            self.status_message.setStyleSheet("color: red")
    
    def browse_image(self):
        """Open file dialog to select an image"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            self.image_path = file_path
            self.image_url_input.setText(file_path)
            self.display_image(file_path)
    
    def display_image(self, image_path):
        """Display the selected image"""
        try:
            if image_path.startswith(("http://", "https://")):
                try:
                    response = requests.get(image_path)
                    image_data = BytesIO(response.content)
                    pixmap = QPixmap()
                    pixmap.loadFromData(image_data.getvalue())
                except Exception as e:
                    self.status_message.setText(f"Error loading image URL: {str(e)}")
                    return
            else:
                if not os.path.exists(image_path):
                    self.status_message.setText(f"File not found: {image_path}")
                    return
                pixmap = QPixmap(image_path)
            
            if pixmap.isNull():
                self.status_message.setText("Failed to load image")
                return
            
            # Scale while preserving aspect ratio
            pixmap = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_display.setPixmap(pixmap)
            self.image_display.setAlignment(Qt.AlignCenter)
        except Exception as e:
            self.status_message.setText(f"Error displaying image: {str(e)}")
    
    def submit_query(self):
        """Submit a query to the API"""
        if not self.image_path and not self.image_url_input.text():
            self.status_message.setText("Please provide an image first")
            self.status_message.setStyleSheet("color: red")
            return
        
        # Use URL if provided, otherwise use local file path
        image_src = self.image_url_input.text() if self.image_url_input.text() else self.image_path
        
        # Disable the button to prevent multiple submissions
        self.submit_btn.setEnabled(False)
        self.status_message.setText("Processing request...")
        
        # Create and start worker thread
        self.worker = WorkerThread(
            self.client,
            image_src,
            self.system_prompt.text(),
            self.user_prompt.text(),
            self.chat_history
        )
        self.worker.finished.connect(self.handle_response)
        self.worker.error.connect(self.handle_error)
        self.worker.start()
    
    def handle_response(self, chat_history, bbox_image):
        """Handle the API response"""
        self.chat_history = chat_history
        
        # Get the last response to check for coordinates
        if chat_history and len(chat_history) > 0:
            last_exchange = chat_history[-1]
            if len(last_exchange) > 1:
                last_response = last_exchange[1]
                
                # Extract coordinates from response
                coordinates = self.extract_coordinates(last_response)
                if coordinates:
                    # Draw our own bounding box or point marker
                    self.draw_and_display_box(coordinates)
        
        # Update conversation display
        self.conversation_area.clear()
        for exchange in self.chat_history:
            user_msg, assistant_msg = exchange
            self.conversation_area.append(f"<b>You:</b> {user_msg}")
            self.conversation_area.append(f"<b>Magma:</b> {assistant_msg}")
            # Remove debug info from UI
            self.conversation_area.append("\n")
        
        # Re-enable the submit button
        self.submit_btn.setEnabled(True)
        self.status_message.setText("Response received")
        self.status_message.setStyleSheet("color: #00FF00")
        
        # Clear the prompt for next query
        self.user_prompt.clear()
    
    def handle_error(self, error_msg):
        """Handle errors from the API"""
        self.status_message.setText(f"Error: {error_msg}")
        self.status_message.setStyleSheet("color: #FF5555")
        self.submit_btn.setEnabled(True)
    
    def clear_conversation(self):
        """Clear the conversation history"""
        try:
            result = self.client.predict(
                image=handle_file(self.image_path) if self.image_path else None,
                api_name="/clear_conversation"
            )
            self.chat_history = []
            self.conversation_area.clear()
            self.status_message.setText("Conversation cleared")
            self.status_message.setStyleSheet("color: green")
        except Exception as e:
            self.status_message.setText(f"Error clearing conversation: {str(e)}")
            self.status_message.setStyleSheet("color: red")

    def extract_coordinates(self, text):
        """Extract coordinate pattern from text - handles both formats"""
        # Try four-value bounding box pattern first
        pattern_bbox = r"Coordinate: \(([0-9.]+), ([0-9.]+), ([0-9.]+), ([0-9.]+)\)"
        match = re.search(pattern_bbox, text)
        if match:
            try:
                x_min = float(match.group(1))
                y_min = float(match.group(2))
                x_max = float(match.group(3))
                y_max = float(match.group(4))
                return {'type': 'bbox', 'coords': (x_min, y_min, x_max, y_max)}
            except ValueError:
                return None
        
        # Try two-value center point pattern
        pattern_point = r"Coordinate: \(([0-9.]+), ([0-9.]+)\)"
        match = re.search(pattern_point, text)
        if match:
            try:
                x = float(match.group(1))
                y = float(match.group(2))
                return {'type': 'point', 'coords': (x, y)}
            except ValueError:
                return None
            
        return None

    def draw_and_display_box(self, coordinates_data):
        """Draw a bounding box or point marker on the image"""
        if not coordinates_data:
            return
        
        try:
            # Load the image
            if self.image_path:
                img = Image.open(self.image_path)
            elif self.image_url_input.text().startswith(("http://", "https://")):
                response = requests.get(self.image_url_input.text())
                img = Image.open(BytesIO(response.content))
            else:
                return
            
            # Make sure image is in RGB mode
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Draw bounding box or point
            draw = ImageDraw.Draw(img)
            width, height = img.size
            
            if coordinates_data['type'] == 'point':
                # Draw a point marker (circle with cross)
                x, y = coordinates_data['coords']
                # Convert normalized coordinates to pixel coordinates
                center_x = int(x * width)
                center_y = int(y * height)
                
                # Draw a visible point marker
                radius = max(10, min(width, height) // 30)  # Scale with image size
                
                # Draw cross
                draw.line([(center_x - radius, center_y), (center_x + radius, center_y)], fill="red", width=3)
                draw.line([(center_x, center_y - radius), (center_x, center_y + radius)], fill="red", width=3)
                
                # Draw circle
                draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), 
                             outline="red", width=2)
                
                self.status_message.setText(f"Drew point marker at coordinates: ({x}, {y})")
            else:
                # Draw rectangle for bounding box
                x_min, y_min, x_max, y_max = coordinates_data['coords']
                
                # Convert normalized coordinates to pixel coordinates
                x_min_px = int(x_min * width)
                y_min_px = int(y_min * height)
                x_max_px = int(x_max * width)
                y_max_px = int(y_max * height)
                
                # Draw rectangle for bounding box
                draw.rectangle(
                    [(x_min_px, y_min_px), (x_max_px, y_max_px)],
                    outline="red",
                    width=3
                )
                
                self.status_message.setText(f"Drew bounding box at coordinates: {coordinates_data['coords']}")
            
            # Save to a temporary file and display
            temp_path = "temp_bbox_image.png"
            img.save(temp_path)
            self.display_image(temp_path)
        except Exception as e:
            self.status_message.setText(f"Error drawing: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MagmaDesktopApp()
    window.show()
    sys.exit(app.exec_()) 