import sys
import os
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
                            QScrollArea, QSplitter, QFrame, QGridLayout)
from PyQt5.QtGui import QPixmap, QImage, QFont, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPropertyAnimation, QEasingCurve, pyqtProperty
import requests
from gradio_client import Client, handle_file
from PIL import Image, ImageDraw
from io import BytesIO
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import tempfile

# Screen dimensions constants
SCREENSHOT_WIDTH = 1200
SCREENSHOT_HEIGHT = 1200
DISPLAY_WIDTH = 1200
DISPLAY_HEIGHT = 1200

class AnimatedLabel(QLabel):
    """A label that can flash with an animated color effect"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        # Initialize _color first before other setup
        self._color = QColor(255, 255, 255)
        
        # Then set up animation
        self.animation = QPropertyAnimation(self, b"color")
        self.animation.setDuration(800)
        self.animation.setLoopCount(3)
        self.animation.setStartValue(QColor(255, 255, 255))
        self.animation.setEndValue(QColor(255, 120, 0))
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        
    def flash(self):
        self.animation.start()
        
    def get_color(self):
        # Add safety check to handle case where _color might not be initialized
        if not hasattr(self, '_color'):
            self._color = QColor(255, 255, 255)
        return self._color
        
    def set_color(self, color):
        self._color = color
        self.setStyleSheet(f"color: rgb({color.red()}, {color.green()}, {color.blue()});")
        
    color = pyqtProperty(QColor, get_color, set_color)

class WebCaptureThread(QThread):
    """Thread for capturing website screenshots without freezing UI"""
    progress_update = pyqtSignal(str, int)
    screenshot_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.screenshot_path = None
    
    def run(self):
        try:
            self.progress_update.emit("Setting up browser...", 10)
            
            # Set up a headless browser with mobile emulation
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            
            # Mobile emulation settings
            mobile_emulation = {
                "deviceMetrics": { "width": 375, "height": 812, "pixelRatio": 3.0 },
                "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
            }
            chrome_options.add_experimental_option("mobileEmulation", mobile_emulation)
            
            self.progress_update.emit("Launching browser...", 20)
            driver = webdriver.Chrome(options=chrome_options)
            
            # Set window size slightly larger than our target
            driver.set_window_size(650, 850)
            
            self.progress_update.emit(f"Loading page: {self.url}", 30)
            driver.get(self.url)
            
            # Wait for page to load
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            self.progress_update.emit("Page loaded, capturing screenshot...", 70)
            
            # Take a screenshot
            fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            driver.save_screenshot(temp_path)
            
            # Crop to SCREENSHOT_WIDTH x SCREENSHOT_HEIGHT
            img = Image.open(temp_path)
            cropped_img = img.crop((0, 0, SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT))
            cropped_img.save(temp_path)
            
            self.screenshot_path = temp_path
            self.progress_update.emit("Screenshot captured!", 100)
            
            # Close the browser
            driver.quit()
            
            self.screenshot_ready.emit(self.screenshot_path)
            
        except Exception as e:
            self.error.emit(f"Error capturing website: {str(e)}")
            

class ActionThread(QThread):
    """Thread for performing actions on the website based on model response"""
    progress_update = pyqtSignal(str, int)
    result_ready = pyqtSignal(str, str)  # Screenshot path, summary
    error = pyqtSignal(str)
    
    def __init__(self, url, coordinates, coordinates_type):
        super().__init__()
        self.url = url
        self.coordinates = coordinates
        self.coordinates_type = coordinates_type  # 'bbox' or 'point'
    
    def run(self):
        try:
            self.progress_update.emit("Setting up browser for interaction...", 10)
            
            # Set up a headless browser with mobile emulation
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            
            # Mobile emulation settings
            mobile_emulation = {
                "deviceMetrics": { "width": 375, "height": 812, "pixelRatio": 3.0 },
                "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
            }
            chrome_options.add_experimental_option("mobileEmulation", mobile_emulation)
            
            self.progress_update.emit("Launching browser...", 20)
            driver = webdriver.Chrome(options=chrome_options)
            
            # Set window size
            driver.set_window_size(650, 850)
            
            self.progress_update.emit(f"Loading page: {self.url}", 30)
            driver.get(self.url)
            
            # Wait for page to load
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Convert normalized coordinates to actual pixels
            window_width = driver.execute_script("return document.documentElement.clientWidth")
            window_height = driver.execute_script("return document.documentElement.clientHeight")
            
            self.progress_update.emit("Preparing to click on element...", 50)
            
            if self.coordinates_type == 'point':
                x, y = self.coordinates
                click_x = int(x * window_width)
                click_y = int(y * window_height)
                
                # Execute JavaScript to click at the specific coordinates
                driver.execute_script(f"document.elementFromPoint({click_x}, {click_y}).click();")
                self.progress_update.emit(f"Clicked at point ({click_x}, {click_y})", 60)
                
            else:  # bbox
                x_min, y_min, x_max, y_max = self.coordinates
                center_x = int((x_min + x_max) * window_width / 2)
                center_y = int((y_min + y_max) * window_height / 2)
                
                # Click in the center of the bounding box
                driver.execute_script(f"document.elementFromPoint({center_x}, {center_y}).click();")
                self.progress_update.emit(f"Clicked at center of box: ({center_x}, {center_y})", 60)
            
            # Wait for any page transitions
            self.progress_update.emit("Waiting for page transition...", 70)
            time.sleep(2)  # Simple wait for the page to load
            
            # Take a screenshot of new page
            fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            driver.save_screenshot(temp_path)
            
            # Crop to SCREENSHOT_WIDTH x SCREENSHOT_HEIGHT
            img = Image.open(temp_path)
            cropped_img = img.crop((0, 0, SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT))
            cropped_img.save(temp_path)
            
            # Get page title and basic content for summary
            page_title = driver.title
            page_content = driver.find_element(By.TAG_NAME, "body").text[:500]  # Get first 500 chars
            summary = f"Page Title: {page_title}\n\nContent Preview:\n{page_content}..."
            
            self.progress_update.emit("Action completed! Processing results...", 90)
            
            # Close the browser
            driver.quit()
            
            self.result_ready.emit(temp_path, summary)
            
        except Exception as e:
            self.error.emit(f"Error performing action: {str(e)}")


class ModelThread(QThread):
    """Thread for running API calls to the model"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, client, image_path, system_prompt, user_prompt):
        super().__init__()
        self.client = client
        self.image_path = image_path
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
    
    def run(self):
        try:
            result = self.client.predict(
                image_input=handle_file(self.image_path) if self.image_path else None,
                system_prompt=self.system_prompt,
                user_prompt=self.user_prompt,
                chat_history=[],
                api_name="/generate_response"
            )
            
            response_text = result[0][0][1] if result and result[0] and len(result[0]) > 0 else ""
            
            # Extract coordinates
            coordinates_data = self.extract_coordinates(response_text)
            
            self.finished.emit({
                "response": response_text,
                "coordinates": coordinates_data,
                "raw_result": result
            })
        except Exception as e:
            self.error.emit(str(e))
    
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


class WebAutomationApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.api_url = "http://127.0.0.1:7860/"
        self.client = None
        self.screenshot_path = None
        
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Web Automation Assistant")
        self.setGeometry(100, 100, 1400, 900)
        
        # Styling
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
            QPushButton:disabled {
                background-color: #555555;
                color: #999999;
            }
            QLineEdit, QTextEdit {
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
                background-color: #3D3D3D;
                color: #FFFFFF;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                text-align: center;
                background-color: #3D3D3D;
            }
            QProgressBar::chunk {
                background-color: #0071e3;
                width: 1px;
            }
            QScrollArea {
                border: none;
                background-color: #2D2D2D;
            }
            QSplitter {
                background-color: #2D2D2D;
            }
            QFrame {
                background-color: #3D3D3D;
                border-radius: 8px;
            }
        """)
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # Left panel - inputs and controls
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Web Automation Assistant")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 15px;")
        left_layout.addWidget(title_label)
        
        # Add a description
        desc_label = QLabel("This app automates web interactions by using AI to identify and click buttons on websites.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 12px; color: #BBBBBB; margin-bottom: 15px;")
        left_layout.addWidget(desc_label)
        
        # Create section for API connection
        api_section = QFrame()
        api_layout = QVBoxLayout()
        api_section.setLayout(api_layout)
        
        api_header = QLabel("1. Connect to API")
        api_header.setStyleSheet("font-size: 16px;")
        api_layout.addWidget(api_header)
        
        api_input_layout = QHBoxLayout()
        api_input_layout.addWidget(QLabel("API URL:"))
        self.api_input = QLineEdit(self.api_url)
        self.api_input.setPlaceholderText("Enter Gradio API URL")
        api_input_layout.addWidget(self.api_input)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_to_api)
        api_input_layout.addWidget(self.connect_btn)
        api_layout.addLayout(api_input_layout)
        
        # Connection status
        self.api_status = AnimatedLabel("Not connected")
        self.api_status.setStyleSheet("color: #FF5555; font-style: italic;")
        api_layout.addWidget(self.api_status)
        
        left_layout.addWidget(api_section)
        
        # Create section for website input
        web_section = QFrame()
        web_layout = QVBoxLayout()
        web_section.setLayout(web_layout)
        
        web_header = QLabel("2. Enter Website URL")
        web_header.setStyleSheet("font-size: 16px;")
        web_layout.addWidget(web_header)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com")
        web_layout.addWidget(self.url_input)
        
        url_btn_layout = QHBoxLayout()
        self.capture_btn = QPushButton("Capture Website")
        self.capture_btn.clicked.connect(self.capture_website)
        self.capture_btn.setEnabled(False)  # Disabled until API is connected
        url_btn_layout.addWidget(self.capture_btn)
        web_layout.addLayout(url_btn_layout)
        
        left_layout.addWidget(web_section)
        
        # Create section for AI prompt
        prompt_section = QFrame()
        prompt_layout = QVBoxLayout()
        prompt_section.setLayout(prompt_layout)
        
        prompt_header = QLabel("3. AI Instructions")
        prompt_header.setStyleSheet("font-size: 16px;")
        prompt_layout.addWidget(prompt_header)
        
        prompt_layout.addWidget(QLabel("System Prompt:"))
        self.system_prompt = QLineEdit("You are an assistant that analyzes web screenshots to find buttons and elements.")
        prompt_layout.addWidget(self.system_prompt)
        
        prompt_layout.addWidget(QLabel("User Prompt:"))
        self.user_prompt = QLineEdit("Find the main call-to-action button in this image and give me its coordinates.")
        prompt_layout.addWidget(self.user_prompt)
        
        self.analyze_btn = QPushButton("Analyze Screenshot")
        self.analyze_btn.clicked.connect(self.analyze_screenshot)
        self.analyze_btn.setEnabled(False)  # Disabled until screenshot is captured
        prompt_layout.addWidget(self.analyze_btn)
        
        left_layout.addWidget(prompt_section)
        
        # Create section for running the action
        action_section = QFrame()
        action_layout = QVBoxLayout()
        action_section.setLayout(action_layout)
        
        action_header = QLabel("4. Execute Action")
        action_header.setStyleSheet("font-size: 16px;")
        action_layout.addWidget(action_header)
        
        self.execute_btn = QPushButton("Click Element")
        self.execute_btn.clicked.connect(self.execute_action)
        self.execute_btn.setEnabled(False)  # Disabled until AI analysis is complete
        action_layout.addWidget(self.execute_btn)
        
        left_layout.addWidget(action_section)
        
        # Progress bar
        self.progress_section = QFrame()
        progress_layout = QVBoxLayout()
        self.progress_section.setLayout(progress_layout)
        
        progress_layout.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_message = AnimatedLabel("Ready")
        self.status_message.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.status_message)
        
        left_layout.addWidget(self.progress_section)
        
        # Add spacer at the bottom
        left_layout.addStretch()
        
        left_panel.setLayout(left_layout)
        
        # Right panel - output display
        right_panel = QSplitter(Qt.Vertical)
        
        # Image display area
        image_display_widget = QWidget()
        image_display_layout = QVBoxLayout()
        image_display_layout.setContentsMargins(20, 20, 20, 20)
        
        image_header = QLabel(f"Captured Website ({SCREENSHOT_WIDTH}x{SCREENSHOT_HEIGHT})")
        image_header.setStyleSheet("font-size: 16px;")
        image_display_layout.addWidget(image_header)
        
        # Create a scroll area for the image
        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setAlignment(Qt.AlignCenter)
        
        self.image_display = QLabel("No image captured yet")
        self.image_display.setAlignment(Qt.AlignCenter)
        self.image_display.setMinimumHeight(450)
        self.image_display.setStyleSheet("background-color: #222222; border-radius: 4px;")
        
        image_scroll.setWidget(self.image_display)
        image_display_layout.addWidget(image_scroll)
        
        image_display_widget.setLayout(image_display_layout)
        right_panel.addWidget(image_display_widget)
        
        # AI response area
        response_widget = QWidget()
        response_layout = QVBoxLayout()
        response_layout.setContentsMargins(20, 20, 20, 20)
        
        response_header = QLabel("AI Analysis")
        response_header.setStyleSheet("font-size: 16px;")
        response_layout.addWidget(response_header)
        
        self.response_area = QTextEdit()
        self.response_area.setReadOnly(True)
        self.response_area.setStyleSheet("font-size: 14px; line-height: 1.4;")
        response_layout.addWidget(self.response_area)
        
        response_widget.setLayout(response_layout)
        right_panel.addWidget(response_widget)
        
        # Summary area for after clicking
        summary_widget = QWidget()
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(20, 20, 20, 20)
        
        summary_header = QLabel("Results After Click")
        summary_header.setStyleSheet("font-size: 16px;")
        summary_layout.addWidget(summary_header)
        
        self.result_image = QLabel("No results yet")
        self.result_image.setAlignment(Qt.AlignCenter)
        self.result_image.setMinimumHeight(300)
        self.result_image.setStyleSheet("background-color: #222222; border-radius: 4px;")
        summary_layout.addWidget(self.result_image)
        
        summary_layout.addWidget(QLabel("Summary:"))
        self.summary_area = QTextEdit()
        self.summary_area.setReadOnly(True)
        self.summary_area.setStyleSheet("font-size: 14px; line-height: 1.4;")
        summary_layout.addWidget(self.summary_area)
        
        summary_widget.setLayout(summary_layout)
        right_panel.addWidget(summary_widget)
        
        # Set size of the splitter sections - give more space to images
        right_panel.setSizes([400, 200, 300])  # Previously [300, 200, 300]
        
        # Add panels to main layout
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 3)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
    
    def connect_to_api(self):
        """Connect to the Gradio API"""
        try:
            self.api_url = self.api_input.text()
            self.client = Client(self.api_url)
            
            self.api_status.setText("Connected!")
            self.api_status.setStyleSheet("color: #00FF00; font-style: italic;")
            self.api_status.flash()
            
            self.capture_btn.setEnabled(True)
            self.update_status("Connected to API successfully", 100)
        except Exception as e:
            self.api_status.setText(f"Connection failed")
            self.api_status.setStyleSheet("color: #FF5555; font-style: italic;")
            self.update_status(f"Error connecting: {str(e)}", 0)
    
    def capture_website(self):
        """Capture a screenshot of the website"""
        url = self.url_input.text()
        if not url:
            self.update_status("Please enter a URL first", 0)
            return
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            self.url_input.setText(url)
        
        # Disable buttons during processing
        self.capture_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.execute_btn.setEnabled(False)
        
        # Clear previous data
        self.image_display.setText("Capturing website...")
        self.response_area.clear()
        self.summary_area.clear()
        self.result_image.setText("No results yet")
        
        # Create and start worker thread
        self.capture_thread = WebCaptureThread(url)
        self.capture_thread.progress_update.connect(self.update_status)
        self.capture_thread.screenshot_ready.connect(self.handle_screenshot)
        self.capture_thread.error.connect(self.handle_error)
        self.capture_thread.start()
    
    def handle_screenshot(self, screenshot_path):
        """Display the captured screenshot"""
        self.screenshot_path = screenshot_path
        self.display_image(screenshot_path, self.image_display)
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        self.update_status("Screenshot captured successfully! Ready for analysis.", 100)
        self.status_message.flash()
    
    def analyze_screenshot(self):
        """Send the screenshot to the API for analysis"""
        if not self.screenshot_path:
            self.update_status("No screenshot available. Capture a website first.", 0)
            return
        
        # Disable buttons during processing
        self.analyze_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        self.execute_btn.setEnabled(False)
        
        self.update_status("Sending screenshot to AI for analysis...", 30)
        
        # Create and start worker thread
        self.model_thread = ModelThread(
            self.client,
            self.screenshot_path,
            self.system_prompt.text(),
            self.user_prompt.text()
        )
        self.model_thread.finished.connect(self.handle_model_response)
        self.model_thread.error.connect(self.handle_error)
        self.model_thread.start()
    
    def handle_model_response(self, result):
        """Handle the model's response"""
        response_text = result.get("response", "")
        self.coordinates_data = result.get("coordinates")
        
        # Display the response
        self.response_area.setText(response_text)
        
        # Highlight the detected element on the image if coordinates were found
        if self.coordinates_data:
            self.draw_and_display_highlight(self.coordinates_data)
            self.execute_btn.setEnabled(True)
            self.update_status("Element detected! Ready to click.", 100)
        else:
            self.update_status("No clickable element detected in the AI response.", 100)
        
        # Re-enable buttons
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        
        self.status_message.flash()
    
    def execute_action(self):
        """Execute the click action on the detected element"""
        if not self.coordinates_data:
            self.update_status("No element coordinates available. Run analysis first.", 0)
            return
        
        # Disable buttons during processing
        self.execute_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        
        url = self.url_input.text()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Extract coordinates and type
        coords = self.coordinates_data.get('coords')
        coords_type = self.coordinates_data.get('type')
        
        self.update_status("Executing click on detected element...", 30)
        
        # Create and start worker thread
        self.action_thread = ActionThread(url, coords, coords_type)
        self.action_thread.progress_update.connect(self.update_status)
        self.action_thread.result_ready.connect(self.handle_action_result)
        self.action_thread.error.connect(self.handle_error)
        self.action_thread.start()
    
    def handle_action_result(self, screenshot_path, summary):
        """Handle the results after clicking the element"""
        # Display the new screenshot
        self.display_image(screenshot_path, self.result_image)
        
        # Display the summary
        self.summary_area.setText(summary)
        
        # Re-enable buttons
        self.execute_btn.setEnabled(True)
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        
        self.update_status("Action completed successfully!", 100)
        self.status_message.flash()
    
    def display_image(self, image_path, display_widget):
        """Display an image in the specified widget"""
        try:
            pixmap = QPixmap(image_path)
            
            if pixmap.isNull():
                display_widget.setText("Failed to load image")
                return
            
            # Scale to larger dimensions while preserving aspect ratio
            pixmap = pixmap.scaled(DISPLAY_WIDTH, DISPLAY_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            display_widget.setPixmap(pixmap)
            display_widget.setAlignment(Qt.AlignCenter)
        except Exception as e:
            display_widget.setText(f"Error displaying image: {str(e)}")
    
    def draw_and_display_highlight(self, coordinates_data):
        """Draw a highlight on the detected element in the image"""
        if not coordinates_data or not self.screenshot_path:
            return
        
        try:
            # Load the image
            img = Image.open(self.screenshot_path)
            width, height = img.size
            
            # Make sure image is in RGB mode
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Draw highlight
            draw = ImageDraw.Draw(img)
            
            if coordinates_data['type'] == 'point':
                # Draw a point marker (circle with cross)
                x, y = coordinates_data['coords']
                center_x = int(x * width)
                center_y = int(y * height)
                
                radius = max(10, min(width, height) // 30)
                
                # Draw cross
                draw.line([(center_x - radius, center_y), (center_x + radius, center_y)], fill="red", width=3)
                draw.line([(center_x, center_y - radius), (center_x, center_y + radius)], fill="red", width=3)
                
                # Draw circle
                draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), 
                             outline="red", width=2)
                
            else:  # bbox
                # Draw rectangle for bounding box
                x_min, y_min, x_max, y_max = coordinates_data['coords']
                
                # Convert normalized coordinates to pixel coordinates
                x_min_px = int(x_min * width)
                y_min_px = int(y_min * height)
                x_max_px = int(x_max * width)
                y_max_px = int(y_max * height)
                
                # Draw rectangle with semi-transparent fill
                # First draw a semi-transparent fill
                for i in range(3):  # Make the border more visible with multiple lines
                    draw.rectangle(
                        [(x_min_px+i, y_min_px+i), (x_max_px-i, y_max_px-i)],
                        outline="red",
                        width=2
                    )
            
            # Flash effect animation on the border
            temp_path = "temp_highlight_image.png"
            img.save(temp_path)
            self.display_image(temp_path, self.image_display)
            
        except Exception as e:
            self.update_status(f"Error highlighting element: {str(e)}", 0)
    
    def update_status(self, message, progress):
        """Update the status message and progress bar"""
        self.status_message.setText(message)
        self.progress_bar.setValue(progress)
    
    def handle_error(self, error_msg):
        """Handle errors from worker threads"""
        self.update_status(f"Error: {error_msg}", 0)
        self.status_message.setStyleSheet("color: #FF5555;")
        
        # Re-enable buttons
        self.capture_btn.setEnabled(True)
        self.analyze_btn.setEnabled(bool(self.screenshot_path))
        self.execute_btn.setEnabled(bool(getattr(self, 'coordinates_data', None)))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WebAutomationApp()
    window.show()
    sys.exit(app.exec_()) 