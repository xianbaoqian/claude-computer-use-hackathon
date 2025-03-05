import sys
import os
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
                            QScrollArea, QSplitter, QFrame, QGridLayout, QSlider, QDial, QTabWidget, QToolButton)
from PyQt5.QtGui import QPixmap, QImage, QFont, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPropertyAnimation, QEasingCurve, pyqtProperty, QTimer, QSize, QPointF, QPoint, QParallelAnimationGroup, QSequentialAnimationGroup
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
from PyQt5.QtWidgets import (QGraphicsOpacityEffect, QGraphicsBlurEffect)
import random
from PyQt5.QtMultimedia import QSound
import urllib.request
import socket

# Screen dimensions constants
SCREENSHOT_WIDTH = 600
SCREENSHOT_HEIGHT = 600
DISPLAY_WIDTH = 600
DISPLAY_HEIGHT = 600

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
            
            # Set up a headless browser with fixed dimensions
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            
            # Set window size to match content plus some margin
            chrome_options.add_argument("--window-size=600,600")
            
            self.progress_update.emit("Launching browser...", 20)
            driver = webdriver.Chrome(options=chrome_options)
            
            self.progress_update.emit(f"Loading page: {self.url}", 30)
            try:
                driver.get(self.url)
                print(f"Driver reported page loaded with title: {driver.title}")
            except Exception as e:
                print(f"Page load exception: {str(e)}")
                self.error.emit(f"Error loading page: {str(e)}")
                driver.quit()
                return
            
            # Wait for page to load
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(1)  # Small delay to ensure everything renders
            
            self.progress_update.emit("Page loaded, capturing screenshot...", 70)
            
            # Take a simple screenshot - no scaling needed
            fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            driver.save_screenshot(temp_path)
            
            # No scaling needed - content is already the right size
            print(f"Screenshot saved to: {temp_path}")
            
            self.screenshot_path = temp_path
            self.progress_update.emit("Screenshot captured!", 100)
            
            # Close the browser
            driver.quit()
            
            self.screenshot_ready.emit(self.screenshot_path)
            
        except Exception as e:
            self.error.emit(f"Error capturing website: {str(e)}")
            

class ActionThread(QThread):
    """Thread for clicking on elements with visible feedback"""
    progress_update = pyqtSignal(str, int)
    result_ready = pyqtSignal(str, str)
    error = pyqtSignal(str)
    
    def __init__(self, url, coords, coords_type):
        super().__init__()
        self.url = url
        self.coords = coords
        self.coords_type = coords_type
    
    def run(self):
        try:
            self.progress_update.emit("Setting up browser...", 10)
            
            # Set up a visible browser (not headless) to show the interaction
            chrome_options = Options()
            # Make browser visible to see the interaction
            # chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--window-size=800,800")
            chrome_options.add_argument("--no-sandbox")
            
            self.progress_update.emit("Launching browser...", 20)
            driver = webdriver.Chrome(options=chrome_options)
            
            # Load the webpage
            self.progress_update.emit(f"Loading page: {self.url}", 30)
            try:
                driver.get(self.url)
                print(f"Driver reported page loaded with title: {driver.title}")
            except Exception as e:
                print(f"Page load exception: {str(e)}")
                self.error.emit(f"Error loading page: {str(e)}")
                driver.quit()
                return
            
            # Wait for page to load
            self.progress_update.emit("Waiting for page to load...", 40)
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Take a "before" screenshot
            before_screenshot = tempfile.mktemp(suffix='.png')
            driver.save_screenshot(before_screenshot)
            self.progress_update.emit("Pre-click screenshot captured", 50)
            
            # Get viewport size
            viewport_width = driver.execute_script("return window.innerWidth")
            viewport_height = driver.execute_script("return window.innerHeight")
            
            # Calculate click position in pixels
            if self.coords_type == 'point':
                x_rel, y_rel = self.coords
                x_px = int(x_rel * viewport_width)
                y_px = int(y_rel * viewport_height)
            else:  # bbox
                # Click in the middle of the box
                x_min, y_min, x_max, y_max = self.coords
                x_rel = (x_min + x_max) / 2
                y_rel = (y_min + y_max) / 2
                x_px = int(x_rel * viewport_width)
                y_px = int(y_rel * viewport_height)
                
                print(f"Bounding box: ({x_min}, {y_min}, {x_max}, {y_max})")
                print(f"Clicking on center point: ({x_rel}, {y_rel}) -> {x_px}px, {y_px}px")
            
            # Highlight the element before clicking (using JavaScript)
            highlight_script = """
            var clickPoint = document.elementFromPoint(arguments[0], arguments[1]);
            if (clickPoint) {
                // Save original styles
                var originalOutline = clickPoint.style.outline;
                var originalBoxShadow = clickPoint.style.boxShadow;
                
                // Apply highlight
                clickPoint.style.outline = '3px solid #FF5722';
                clickPoint.style.boxShadow = '0 0 10px #FF5722';
                
                // Return element info for logging
                return {
                    tagName: clickPoint.tagName,
                    id: clickPoint.id,
                    className: clickPoint.className,
                    text: clickPoint.textContent.substring(0, 50)
                };
            }
            return null;
            """
            
            # Try to highlight and get element info
            element_info = driver.execute_script(highlight_script, x_px, y_px)
            if element_info:
                info_text = f"Element: {element_info.get('tagName', 'Unknown')} "
                if element_info.get('id'):
                    info_text += f"ID: {element_info['id']} "
                if element_info.get('className'):
                    info_text += f"Class: {element_info['className']} "
                if element_info.get('text'):
                    info_text += f"Text: {element_info['text']}"
                    
                self.progress_update.emit(f"Target: {info_text}", 55)
            
            # Take screenshot of highlighted element
            highlight_screenshot = tempfile.mktemp(suffix='.png')
            driver.save_screenshot(highlight_screenshot)
            
            # Small delay to see the highlight
            time.sleep(0.5)
            
            self.progress_update.emit(f"Clicking at coordinates ({x_rel:.3f}, {y_rel:.3f})...", 60)
            
            # Create ActionChains to move and click
            actions = ActionChains(driver)
            # First move to (0,0) to ensure relative movement works correctly
            actions.move_to_element(driver.find_element(By.TAG_NAME, "body"))
            actions.move_by_offset(x_px, y_px)
            actions.click()
            actions.perform()
            
            self.progress_update.emit("Click performed! Observing changes...", 70)
            
            # Wait longer to observe changes
            time.sleep(2)
            
            # Take a screenshot of results
            fd, result_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            driver.save_screenshot(result_path)
            
            # Get page title and content for summary
            page_title = driver.title
            try:
                page_content = driver.find_element(By.TAG_NAME, "body").text[:500]
            except:
                page_content = "Content could not be extracted"
                
            # Create a more detailed summary with before/after comparison
            summary = f"Page Title: {page_title}\n\n"
            summary += f"Clicked at: ({x_rel:.3f}, {y_rel:.3f})\n"
            if element_info:
                summary += f"Element: {element_info.get('tagName', 'Unknown')}\n"
                if element_info.get('id') or element_info.get('className'):
                    summary += f"Identifier: {element_info.get('id', '')} {element_info.get('className', '')}\n"
            summary += f"\nContent Preview:\n{page_content}..."
            
            self.progress_update.emit("Action completed! Processing results...", 90)
            
            # Keep browser open for a bit longer to see the result
            time.sleep(1)
            
            # Close the browser
            driver.quit()
            
            # Return the result with the final screenshot
            self.result_ready.emit(result_path, summary)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
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


class InteractiveImageViewer(QWidget):
    """Advanced image viewer with zoom, pan and HUD overlay"""
    element_clicked = pyqtSignal(QPointF)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create scroll area first - this will be our main container
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea { 
                background: transparent; 
                border: none; 
            }
            QScrollBar:horizontal {
                height: 15px;
                background: #1A2327;
                border-radius: 7px;
            }
            QScrollBar:vertical {
                width: 15px;
                background: #1A2327;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
                background: #00BCD4;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
                background: #00E5FF;
            }
        """)
        
        # Image container widget
        self.image_container = QWidget()
        self.image_container.setStyleSheet("""
            background-color: #0A1014;
            border: 2px solid #FF5500;  /* Add a bright border to see the container */
        """)
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(15, 15, 15, 15)  # Add some padding
        self.image_layout.setAlignment(Qt.AlignCenter)
        
        # Image label with a smaller size constraint
        self.image_label = QLabel("No image captured yet")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("""
            background-color: #111111; 
            border-radius: 8px; 
            border: 2px solid #00BCD4;
            color: #B0BEC5;
            font-size: 16px;
        """)
        self.image_layout.addWidget(self.image_label, 0, Qt.AlignCenter)
        
        # Set the image container as the scroll area widget
        self.scroll_area.setWidget(self.image_container)
        
        # Main layout gets the scroll area
        self.main_layout.addWidget(self.scroll_area)
        
        # HUD controls overlay
        self.hud_container = QWidget(self)
        self.hud_container.setGeometry(self.rect())
        hud_layout = QVBoxLayout(self.hud_container)
        hud_layout.setContentsMargins(10, 10, 10, 10)
        
        # Zoom controls container - at the top
        self.zoom_controls = QWidget()
        zoom_layout = QHBoxLayout(self.zoom_controls)
        zoom_layout.setContentsMargins(10, 5, 10, 5)
        
        # Zoom label
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("color: #00E5FF; font-weight: bold;")
        zoom_layout.addWidget(zoom_label)
        
        # Zoom slider
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555555;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #0D47A1, stop:1 #00BCD4);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00E5FF;
                border: 2px solid #FFFFFF;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
        """)
        self.zoom_slider.valueChanged.connect(self.update_zoom)
        self.zoom_slider.setFixedWidth(150)
        zoom_layout.addWidget(self.zoom_slider)
        
        # Zoom value display
        self.zoom_value = QLabel("100%")
        self.zoom_value.setStyleSheet("color: #00E5FF; min-width: 50px;")
        zoom_layout.addWidget(self.zoom_value)
        
        # Reset button
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #263238;
                color: #00E5FF;
                border: 1px solid #00BCD4;
                border-radius: 12px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #37474F;
                border: 1px solid #00E5FF;
            }
        """)
        self.reset_btn.clicked.connect(self.reset_view)
        zoom_layout.addWidget(self.reset_btn)
        
        # Style zoom controls panel
        self.zoom_controls.setStyleSheet("""
            background-color: rgba(13, 25, 38, 200);
            border-radius: 15px;
            border: 1px solid #00E5FF;
        """)
        
        # Add zoom controls to HUD
        hud_layout.addWidget(self.zoom_controls, 0, Qt.AlignTop)
        hud_layout.addStretch()
        
        # Coordinates display
        self.coord_display = QLabel("Coordinates: ---, ---")
        self.coord_display.setStyleSheet("""
            color: #00E5FF;
            background-color: rgba(13, 25, 38, 200);
            border-radius: 10px;
            padding: 5px 10px;
            font-family: 'Courier New';
            border: 1px solid #00E5FF;
        """)
        self.coord_display.setAlignment(Qt.AlignCenter)
        hud_layout.addWidget(self.coord_display, 0, Qt.AlignBottom | Qt.AlignRight)
        
        # Make sure HUD is on top
        self.hud_container.raise_()
        
        # State variables
        self.pixmap = None
        self.zoom_level = 100
        self.original_pixmap = None
        
        # Enable mouse tracking
        self.setMouseTracking(True)
        self.image_label.setMouseTracking(True)
    
    def set_image(self, image_path):
        """Load and display an image with improved visibility"""
        try:
            # Skip if this is a text message
            if isinstance(image_path, str) and (image_path.startswith("No image") or image_path.startswith("Failed")):
                self.image_label.setText(image_path)
                self.pixmap = None
                self.original_pixmap = None
                print(f"Setting text message: {image_path}")
                return
            
            print(f"LOADING IMAGE FROM: {image_path}")
            print(f"File exists: {os.path.exists(image_path)}")
            print(f"File size: {os.path.getsize(image_path)} bytes")
            
            # Create and check pixmap directly
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                print(f"ERROR: Pixmap is NULL for {image_path}")
                self.image_label.setText(f"Failed to load image: {image_path}")
                return
            
            print(f"Pixmap loaded successfully: {pixmap.width()}x{pixmap.height()}")
            
            # CRITICAL FIX - make sure we're using a QLabel that can display a pixmap
            if not isinstance(self.image_label, QLabel):
                print("ERROR: image_label is not a QLabel")
                return
            
            # Make sure any text is cleared
            self.image_label.clear()
            
            # Ensure the label can display pixmaps
            self.image_label.setPixmap(pixmap)
            
            # Set a fixed size to ensure visibility
            self.image_label.setFixedSize(pixmap.size())
            
            # Force the layout to update
            self.image_layout.update()
            self.image_container.update()
            self.scroll_area.update()
            
            # Force redraw
            self.image_label.repaint()
            self.image_container.repaint()
            
            # Make everything explicitly visible
            self.image_label.setVisible(True)
            self.image_container.setVisible(True)
            
            print(f"Image displayed with size: {pixmap.width()}x{pixmap.height()}")
        except Exception as e:
            print(f"ERROR DISPLAYING IMAGE: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def update_zoom(self, value):
        """Update the zoom level of the image"""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return
            
        self.zoom_level = value
        
        # Calculate new size
        new_width = int(self.original_pixmap.width() * value / 100)
        new_height = int(self.original_pixmap.height() * value / 100)
        
        # Scale the image
        scaled_pixmap = self.original_pixmap.scaled(
            new_width, 
            new_height,
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        
        # Update the image label
        self.image_label.setPixmap(scaled_pixmap)
        
        # Adjust the size of the image container to match the image size
        self.image_label.setFixedSize(scaled_pixmap.size())
        
        # Update zoom display
        self.zoom_value.setText(f"{value}%")
        
        # Update the coordinates display
        self.coord_display.setText(f"Zoom: {value}%")
    
    def reset_view(self):
        """Reset zoom to 100%"""
        self.zoom_slider.setValue(100)
    
    def resizeEvent(self, event):
        """Handle resize events to keep HUD properly positioned"""
        super().resizeEvent(event)
        self.hud_container.setGeometry(self.rect())
    
    def mouseMoveEvent(self, event):
        """Track mouse movement for coordinate display"""
        if not self.pixmap or self.pixmap.isNull():
            return
            
        # Get position relative to the scroll area's viewport
        viewport_pos = self.scroll_area.viewport().mapFrom(self, event.pos())
        
        # Get position in the image label's coordinate system
        label_pos = self.image_label.mapFrom(self.scroll_area.viewport(), viewport_pos)
        
        # Check if the position is within the image label
        if self.image_label.rect().contains(label_pos):
            # Convert to normalized coordinates (0-1)
            x_rel = max(0, min(1, label_pos.x() / self.image_label.width()))
            y_rel = max(0, min(1, label_pos.y() / self.image_label.height()))
            
            # Update coordinate display
            self.coord_display.setText(f"Coordinates: {x_rel:.3f}, {y_rel:.3f}")
    
    def mousePressEvent(self, event):
        """Handle mouse clicks to select elements"""
        if not self.pixmap or self.pixmap.isNull() or event.button() != Qt.LeftButton:
            return
            
        # Get position relative to the scroll area's viewport
        viewport_pos = self.scroll_area.viewport().mapFrom(self, event.pos())
        
        # Get position in the image label's coordinate system
        label_pos = self.image_label.mapFrom(self.scroll_area.viewport(), viewport_pos)
        
        # Check if the position is within the image label
        if self.image_label.rect().contains(label_pos):
            # Convert to normalized coordinates (0-1)
            x_rel = max(0, min(1, label_pos.x() / self.image_label.width()))
            y_rel = max(0, min(1, label_pos.y() / self.image_label.height()))
            
            # Emit the click signal with coordinates
            self.element_clicked.emit(QPointF(x_rel, y_rel))


class FuturisticTabWidget(QTabWidget):
    """Custom tab widget with futuristic styling"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabPosition(QTabWidget.North)
        self.setDocumentMode(True)
        self.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #00BCD4;
                border-radius: 10px;
                background-color: #1A2327;
            }
            QTabBar::tab {
                background-color: #263238;
                color: #B0BEC5;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                min-width: 100px;
                padding: 8px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1A2327;
                color: #00E5FF;
                border-top: 2px solid #00E5FF;
            }
            QTabBar::tab:hover {
                background-color: #37474F;
            }
        """)
        
        # Add glow effect to selected tab
        self.currentChanged.connect(self.update_tab_effects)
        
    def update_tab_effects(self, index):
        # Placeholder for future tab transition effects
        pass


class FuturisticStatusPanel(QWidget):
    """Animated status panel with futuristic design"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        
        # Main layout
        self.layout = QHBoxLayout(self)
        
        # Progress indicator (circular)
        self.progress_dial = QDial()
        self.progress_dial.setNotchesVisible(True)
        self.progress_dial.setRange(0, 100)
        self.progress_dial.setValue(0)
        self.progress_dial.setFixedSize(60, 60)
        self.progress_dial.setEnabled(False)  # Purely visual
        self.progress_dial.setStyleSheet("""
            QDial {
                background-color: #0D1926;
                color: #00E5FF;
            }
        """)
        
        # Status message with animated text
        self.status_label = AnimatedLabel("SYSTEM READY")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #00E5FF;
            font-family: 'Courier New';
        """)
        
        # Details area
        self.details = QLabel("Awaiting commands...")
        self.details.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.details.setStyleSheet("""
            color: #B0BEC5;
            font-style: italic;
        """)
        
        # Action buttons container
        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        
        # Cancel button that appears during operations
        self.cancel_btn = QPushButton("ABORT")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #B71C1C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        self.cancel_btn.setVisible(False)
        action_layout.addWidget(self.cancel_btn)
        
        # Add all to main layout
        self.layout.addWidget(self.progress_dial)
        self.layout.addWidget(self.status_label, 1)
        self.layout.addWidget(self.details, 2)
        self.layout.addWidget(action_container)
        
        # Set futuristic panel styling
        self.setStyleSheet("""
            FuturisticStatusPanel {
                background-color: #0D1926;
                border: 1px solid #00BCD4;
                border-radius: 10px;
            }
        """)
        
        # Animation timer for "scanning" effect
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.update_scan_animation)
        self.scan_counter = 0
        
    def set_progress(self, value):
        self.progress_dial.setValue(value)
        
    def set_status(self, message, details=""):
        self.status_label.setText(message)
        if details:
            self.details.setText(details)
        self.status_label.flash()
            
    def start_operation(self, message):
        """Start an operation with animated scanning effect"""
        self.set_status(message, "Processing...")
        self.cancel_btn.setVisible(True)
        self.scan_counter = 0
        self.scan_timer.start(100)
        
    def end_operation(self, success=True):
        """End the current operation"""
        self.scan_timer.stop()
        self.cancel_btn.setVisible(False)
        if success:
            self.set_status("OPERATION COMPLETE", "Task completed successfully")
        else:
            self.set_status("OPERATION FAILED", "An error occurred")
            
    def update_scan_animation(self):
        """Update the scanning animation effect"""
        self.scan_counter += 5
        if self.scan_counter > 100:
            self.scan_counter = 0
        self.progress_dial.setValue(self.scan_counter)


class GlowingButton(QPushButton):
    """Button with animated glowing effect"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("""
            GlowingButton {
                background-color: #0D47A1;
                color: white;
                border: none;
                border-radius: 15px;
                padding: 12px 24px;
                font-weight: bold;
            }
            GlowingButton:hover {
                background-color: #1565C0;
            }
        """)
        
        # Create glow effect animation
        self.glow_animation = QPropertyAnimation(self, b"styleSheet")
        self.glow_animation.setDuration(800)
        self.glow_animation.setStartValue("""
            GlowingButton {
                background-color: #0D47A1;
                color: white;
                border: none;
                border-radius: 15px;
                padding: 12px 24px;
                font-weight: bold;
            }
        """)
        self.glow_animation.setEndValue("""
            GlowingButton {
                background-color: #1E88E5;
                color: white;
                border: 2px solid #4FC3F7;
                border-radius: 15px;
                padding: 12px 24px;
                font-weight: bold;
            }
        """)
        self.glow_animation.setLoopCount(3)
        
    def pulse(self):
        """Start pulsing animation"""
        self.glow_animation.start()


class MatrixLoadingAnimation(QWidget):
    """Matrix-style loading animation"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 40)
        self.characters = "01"
        self.columns = 20
        self.positions = [0] * self.columns
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.active = False
        
    def start(self):
        self.active = True
        self.timer.start(100)
        
    def stop(self):
        self.active = False
        self.timer.stop()
        
    def paintEvent(self, event):
        if not self.active:
            return
            
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        
        char_width = self.width() / self.columns
        char_height = 20
        
        painter.setPen(QColor(0, 230, 118))
        painter.setFont(QFont("Courier", 10))
        
        for i in range(self.columns):
            x = i * char_width
            y = self.positions[i] * char_height
            
            # Draw random binary digit
            char = self.characters[random.randint(0, len(self.characters)-1)]
            painter.drawText(x, y % self.height(), char)
            
            # Move position
            self.positions[i] += 1
            if self.positions[i] * char_height > self.height():
                self.positions[i] = 0


class SciFiProgressMeter(QWidget):
    """Futuristic progress meter with segments"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.value = 0
        self.segments = 20
        
    def setValue(self, value):
        self.value = max(0, min(100, value))
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw background
        painter.fillRect(self.rect(), QColor(13, 25, 38))
        
        # Calculate segment width
        segment_width = self.width() / self.segments
        filled_segments = int(self.value / 100 * self.segments)
        
        # Draw filled segments
        for i in range(filled_segments):
            x = i * segment_width
            segment_rect = QRect(int(x), 0, int(segment_width - 2), self.height())
            
            # Use gradient for segments
            if i < self.segments * 0.3:
                color = QColor(0, 229, 255)  # Cyan
            elif i < self.segments * 0.7:
                color = QColor(0, 255, 170)  # Cyan-green
            else:
                color = QColor(0, 255, 85)   # Green
                
            painter.fillRect(segment_rect, color)
            
        # Draw text
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self.value}%")


class HolographicImageDisplay(QWidget):
    """Image display with holographic effect"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.scanline_pos = 0
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.update_scanline)
        
    def set_image(self, image_path):
        self.pixmap = QPixmap(image_path)
        self.update()
        self.scan_timer.start(30)
        
    def update_scanline(self):
        self.scanline_pos += 5
        if self.scanline_pos > self.height():
            self.scanline_pos = 0
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Fill background
        painter.fillRect(self.rect(), QColor(0, 10, 20))
        
        if self.pixmap and not self.pixmap.isNull():
            # Draw the image
            scaled_pixmap = self.pixmap.scaled(
                self.size(), 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # Calculate position to center the image
            x = (self.width() - scaled_pixmap.width()) // 2
            y = (self.height() - scaled_pixmap.height()) // 2
            
            # Draw base image
            painter.drawPixmap(x, y, scaled_pixmap)
            
            # Draw holographic frame
            frame_color = QColor(0, 229, 255, 150)
            pen = QPen(frame_color)
            pen.setWidth(3)
            painter.setPen(pen)
            frame_rect = QRect(x-10, y-10, scaled_pixmap.width()+20, scaled_pixmap.height()+20)
            painter.drawRect(frame_rect)
            
            # Draw corner brackets
            corner_size = 20
            
            # Top-left
            painter.drawLine(x-10, y-10, x-10+corner_size, y-10)
            painter.drawLine(x-10, y-10, x-10, y-10+corner_size)
            
            # Top-right
            painter.drawLine(x+scaled_pixmap.width()+10, y-10, x+scaled_pixmap.width()+10-corner_size, y-10)
            painter.drawLine(x+scaled_pixmap.width()+10, y-10, x+scaled_pixmap.width()+10, y-10+corner_size)
            
            # Bottom-left
            painter.drawLine(x-10, y+scaled_pixmap.height()+10, x-10+corner_size, y+scaled_pixmap.height()+10)
            painter.drawLine(x-10, y+scaled_pixmap.height()+10, x-10, y+scaled_pixmap.height()+10-corner_size)
            
            # Bottom-right
            painter.drawLine(x+scaled_pixmap.width()+10, y+scaled_pixmap.height()+10, x+scaled_pixmap.width()+10-corner_size, y+scaled_pixmap.height()+10)
            painter.drawLine(x+scaled_pixmap.width()+10, y+scaled_pixmap.height()+10, x+scaled_pixmap.width()+10, y+scaled_pixmap.height()+10-corner_size)
            
            # Draw scan line
            scan_rect = QRect(x, y + self.scanline_pos % scaled_pixmap.height(), scaled_pixmap.width(), 2)
            painter.fillRect(scan_rect, QColor(0, 255, 255, 150))
            
            # Draw digital readout text
            painter.setPen(QColor(0, 229, 255))
            painter.setFont(QFont("Courier New", 8))
            painter.drawText(x, y+scaled_pixmap.height()+25, f"RESOLUTION: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            painter.drawText(x, y+scaled_pixmap.height()+40, f"SCAN: {self.scanline_pos / scaled_pixmap.height()*100:.1f}%")


class SoundEffects:
    """Class to manage sound effects (disabled for now)"""
    @staticmethod
    def _try_play(sound_path):
        """Stub method - sound effects disabled"""
        # Just log that we would have played the sound
        print(f"[Sound disabled] Would have played: {sound_path}")

    @staticmethod
    def button_click():
        # No actual sound playback
        print("[Sound disabled] Button click sound")
        
    @staticmethod
    def scan_complete():
        # No actual sound playback
        print("[Sound disabled] Scan complete sound")
        
    @staticmethod
    def error():
        # No actual sound playback
        print("[Sound disabled] Error sound")


class WebAutomationApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.api_url = "http://127.0.0.1:7860/"
        self.client = None
        self.screenshot_path = None
        
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Web Automation Assistant")
        # Make window size more compact, especially height
        self.setGeometry(100, 100, 1000, 600)  # Reduced from 700 to 600
        
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
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        
        # Title with futuristic styling
        title_label = QLabel("NEURAL WEB AUTOMATION")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; margin-bottom: 8px; color: #00E5FF;")
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
        self.system_prompt.setFixedHeight(50)  # Reduced from default
        prompt_layout.addWidget(self.system_prompt)
        
        prompt_layout.addWidget(QLabel("User Prompt:"))
        self.user_prompt = QLineEdit("Find the main call-to-action button in this image and give me its coordinates.")
        self.user_prompt.setFixedHeight(50)  # Reduced from default
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
        
        # Replace the status message with the futuristic status panel
        self.status_panel = FuturisticStatusPanel()
        self.status_panel.setMinimumHeight(60)  # Reduced from 80
        left_layout.addWidget(self.status_panel)
        
        left_panel.setLayout(left_layout)
        
        # Right panel - Use tabbed interface instead of splitter
        self.right_panel = FuturisticTabWidget()
        
        # First tab - Interactive image viewer
        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)
        image_layout.setContentsMargins(5, 5, 5, 5)
        
        self.image_viewer = InteractiveImageViewer()
        image_layout.addWidget(self.image_viewer)
        
        # Add the tab with an icon
        self.right_panel.addTab(image_tab, "CAPTURE VIEW")
        
        # AI response tab
        response_tab = QWidget()
        response_layout = QVBoxLayout(response_tab)
        response_layout.setContentsMargins(10, 10, 10, 10)
        
        response_header = QLabel("AI ANALYSIS RESULTS")
        response_header.setStyleSheet("font-size: 18px; color: #00E5FF;")
        response_layout.addWidget(response_header)
        
        self.response_area = QTextEdit()
        self.response_area.setReadOnly(True)
        self.response_area.setStyleSheet("""
            font-size: 14px; 
            line-height: 1.6;
            background-color: #0A192F;
            border: 1px solid #00BCD4;
            color: #E0F7FA;
            padding: 15px;
        """)
        response_layout.addWidget(self.response_area)
        
        response_tab.setLayout(response_layout)
        self.right_panel.addTab(response_tab, "AI ANALYSIS")
        
        # Results tab
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        
        self.result_viewer = InteractiveImageViewer()
        results_layout.addWidget(self.result_viewer)
        
        self.summary_area = QTextEdit()
        self.summary_area.setReadOnly(True)
        self.summary_area.setMaximumHeight(150)
        self.summary_area.setStyleSheet("""
            font-size: 14px; 
            background-color: #0A192F;
            border: 1px solid #00BCD4;
            color: #E0F7FA;
        """)
        results_layout.addWidget(self.summary_area)
        
        results_tab.setLayout(results_layout)
        self.right_panel.addTab(results_tab, "RESULTS")
        
        # Add panels to main layout with adjusted ratio
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(self.right_panel, 3)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # Connect signals
        self.image_viewer.element_clicked.connect(self.handle_element_click)
    
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
        self.image_viewer.set_image("No image")
        self.response_area.clear()
        self.summary_area.clear()
        self.result_viewer.set_image("No image")
        
        # Create and start worker thread
        self.capture_thread = WebCaptureThread(url)
        self.capture_thread.progress_update.connect(self.update_status)
        self.capture_thread.screenshot_ready.connect(self.handle_screenshot)
        self.capture_thread.error.connect(self.handle_error)
        self.capture_thread.start()
    
    def handle_screenshot(self, screenshot_path):
        """Display the captured screenshot with a clean, simple approach"""
        self.screenshot_path = screenshot_path
        
        if not os.path.exists(screenshot_path):
            self.update_status(f"Screenshot file not found: {screenshot_path}", 0)
            return
        
        print(f"DIRECT DISPLAY: Loading image from {screenshot_path}")
        
        # Create a clean image display without extra controls
        direct_display = QLabel()
        direct_pixmap = QPixmap(screenshot_path)
        
        if not direct_pixmap.isNull():
            # Set pixmap with appropriate scaling for the view
            scaled_pixmap = direct_pixmap.scaled(
                direct_pixmap.width(),  # Original width
                direct_pixmap.height(),  # Original height
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # Set the pixmap directly
            direct_display.setPixmap(scaled_pixmap)
            direct_display.setAlignment(Qt.AlignCenter)
            
            # Create a clean tab with just the image
            image_tab = QWidget()
            image_layout = QVBoxLayout(image_tab)
            image_layout.setContentsMargins(10, 10, 10, 10)
            image_layout.addWidget(direct_display, 1, Qt.AlignCenter)
            
            # Replace the current tab
            self.right_panel.removeTab(0)
            self.right_panel.insertTab(0, image_tab, "CAPTURE VIEW")
            self.right_panel.setCurrentIndex(0)
            
            print("Display complete - image size: " + 
                  f"{direct_pixmap.width()}x{direct_pixmap.height()}")
        else:
            print("ERROR: Failed to load pixmap for display")
        
        # Enable buttons
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        
        # Update status
        self.update_status("Capture complete - ready for analysis", 100)
        self.status_panel.status_label.flash()
    
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
        """Handle the model's response and show highlighted image"""
        response_text = result.get("response", "")
        self.coordinates_data = result.get("coordinates")
        
        # Display the response
        self.response_area.setText(response_text)
        
        # Switch to the AI Analysis tab to show results
        self.right_panel.setCurrentIndex(1)
        
        # Highlight the detected element on the image if coordinates were found
        if self.coordinates_data:
            # Generate a highlighted image and show it
            highlight_path = self.create_highlighted_image()
            
            # Show the coordinates in the status area and the dedicated display
            coords = self.coordinates_data['coords']
            if self.coordinates_data['type'] == 'point':
                coords_text = f"Coordinates: ({coords[0]:.3f}, {coords[1]:.3f})"
            else:  # bbox
                coords_text = f"Coordinates: ({coords[0]:.3f}, {coords[1]:.3f}, {coords[2]:.3f}, {coords[3]:.3f})"
            
            # Update coordinate display
            self.show_coordinates_display(coords_text)
            
            # Update status
            self.update_status(f"Element detected! {coords_text}", 100)
            
            # Enable execute button
            self.execute_btn.setEnabled(True)
        else:
            self.update_status("No clickable element detected in the AI response.", 100)
        
        # Re-enable buttons
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
    
    def create_highlighted_image(self):
        """Create a highlighted image with more prominent visualization"""
        if not self.coordinates_data or not self.screenshot_path:
            return None
        
        try:
            # Load the image
            img = Image.open(self.screenshot_path)
            width, height = img.size
            
            # Make sure image is in RGB mode
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Create a more visible drawing context
            draw = ImageDraw.Draw(img)
            
            if self.coordinates_data['type'] == 'point':
                # Get coordinates
                x, y = self.coordinates_data['coords']
                center_x = int(x * width)
                center_y = int(y * height)
                
                # Make a more visible targeting element
                radius = max(15, min(width, height) // 25)
                
                # 1. Draw pulsing circles (multiple rings with different colors)
                colors = ["#00E5FF", "#FF5722", "#FFEB3B"]
                for i, color in enumerate(colors):
                    r = radius - (i * 3)
                    if r > 0:
                        draw.ellipse(
                            (center_x - r, center_y - r, center_x + r, center_y + r),
                            outline=color,
                            width=3
                        )
                
                # 2. Draw crosshair with extended lines
                line_length = radius * 2
                # Horizontal line
                draw.line(
                    (center_x - line_length, center_y, center_x - radius, center_y),
                    fill="#FF5722",
                    width=2
                )
                # Vertical line
                draw.line(
                    (center_x, center_y - line_length, center_x, center_y + line_length),
                    fill="#FF5722",
                    width=2
                )
                
                # 3. Add coordinate text near the point
                font_size = 20
                # PIL doesn't come with fonts, so we'll draw the text outline
                coord_text = f"({x:.3f}, {y:.3f})"
                # Draw text with outline effect
                for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1)]:
                    draw.text(
                        (center_x + radius + dx, center_y - radius + dy),
                        coord_text,
                        fill="#000000"
                    )
                draw.text(
                    (center_x + radius, center_y - radius),
                    coord_text,
                    fill="#FFFFFF"
                )
                
            else:  # bbox
                # Get coordinates
                x_min, y_min, x_max, y_max = self.coordinates_data['coords']
                
                # Convert to pixel coordinates
                x_min_px = int(x_min * width)
                y_min_px = int(y_min * height)
                x_max_px = int(x_max * width)
                y_max_px = int(y_max * height)
                
                # Calculate dimensions
                box_width = x_max_px - x_min_px
                box_height = y_max_px - y_min_px
                
                # 1. Draw semi-transparent highlight overlay
                # Create a transparent overlay for the inside of the box
                overlay = Image.new('RGBA', (box_width, box_height), (255, 87, 34, 80))  # Semi-transparent orange
                img.paste(overlay, (x_min_px, y_min_px), overlay)
                
                # 2. Draw border with multiple lines for visibility
                for i in range(3):
                    draw.rectangle(
                        [(x_min_px+i, y_min_px+i), (x_max_px-i, y_max_px-i)],
                        outline="#00E5FF",
                        width=2
                    )
                
                # 3. Add corner brackets for a targeting effect
                corner_len = min(30, box_width//4, box_height//4)
                
                # Draw corner brackets with bright color
                for x, y in [(x_min_px, y_min_px), (x_max_px, y_min_px), 
                             (x_min_px, y_max_px), (x_max_px, y_max_px)]:
                    # Determine direction for each corner
                    dx = 1 if x == x_min_px else -1
                    dy = 1 if y == y_min_px else -1
                    
                    # Horizontal line
                    draw.line(
                        (x, y, x + (corner_len * dx), y),
                        fill="#FFEB3B",
                        width=3
                    )
                    # Vertical line
                    draw.line(
                        (x, y, x, y + (corner_len * dy)),
                        fill="#FFEB3B",
                        width=3
                    )
                
                # 4. Add coordinate text
                coord_text = f"({x_min:.2f}, {y_min:.2f}, {x_max:.2f}, {y_max:.2f})"
                text_x = x_min_px + 5
                text_y = y_min_px - 25 if y_min_px > 25 else y_max_px + 5
                
                # Draw text with outline for visibility
                for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1)]:
                    draw.text(
                        (text_x + dx, text_y + dy),
                        coord_text,
                        fill="#000000"
                    )
                draw.text(
                    (text_x, text_y),
                    coord_text,
                    fill="#FFFFFF"
                )
            
            # Save highlighted image
            highlight_path = "temp_highlight_image.png"
            img.save(highlight_path)
            
            # Also make sure to display this highlighted image
            self.display_image_in_tab(highlight_path, 0, "CAPTURE VIEW")
            
            return highlight_path
            
        except Exception as e:
            print(f"Error creating highlighted image: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def display_image_in_tab(self, image_path, tab_index, tab_name):
        """Display an image in the specified tab with a clean approach"""
        if not image_path or not os.path.exists(image_path):
            print(f"Image not found: {image_path}")
            return
        
        # Create a clean image display
        direct_display = QLabel()
        direct_pixmap = QPixmap(image_path)
        
        if not direct_pixmap.isNull():
            # Set the pixmap directly
            direct_display.setPixmap(direct_pixmap)
            direct_display.setAlignment(Qt.AlignCenter)
            
            # Create a clean tab with just the image
            image_tab = QWidget()
            image_layout = QVBoxLayout(image_tab)
            image_layout.setContentsMargins(10, 10, 10, 10)
            image_layout.addWidget(direct_display, 1, Qt.AlignCenter)
            
            # Replace the tab
            self.right_panel.removeTab(tab_index)
            self.right_panel.insertTab(tab_index, image_tab, tab_name)
            
            print(f"Image displayed in tab {tab_index} ({tab_name})")
        else:
            print(f"ERROR: Failed to load pixmap for tab {tab_index}")
    
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
        if not os.path.exists(screenshot_path):
            self.update_status("Screenshot not found after action", 0)
            return
        
        # Display the new screenshot in the Results tab
        self.display_image_in_tab(screenshot_path, 2, "RESULTS")
        
        # Switch to the Results tab
        self.right_panel.setCurrentIndex(2)
        
        # Display the summary
        self.summary_area.setText(summary)
        
        # Update status with a coordinate indicator widget at bottom of screen
        coords = self.coordinates_data['coords']
        if self.coordinates_data['type'] == 'point':
            coords_text = f"Coordinates: ({coords[0]:.3f}, {coords[1]:.3f})"
        else:
            coords_text = f"Coordinates: ({coords[0]:.3f}, {coords[1]:.3f}, {coords[2]:.3f}, {coords[3]:.3f})"
        
        # Create a coordinates display at the bottom of the UI
        self.show_coordinates_display(coords_text)
        
        # Re-enable buttons
        self.execute_btn.setEnabled(True)
        self.analyze_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        
        self.update_status("Action completed successfully!", 100)
    
    def show_coordinates_display(self, coords_text):
        """Show a futuristic coordinates display at the bottom of the UI"""
        # Create or update the coordinates display label
        if not hasattr(self, 'coords_display'):
            self.coords_display = QLabel(self)
            self.coords_display.setAlignment(Qt.AlignCenter)
            self.coords_display.setStyleSheet("""
                background-color: rgba(0, 229, 255, 100);
                color: white;
                border: 1px solid #00E5FF;
                border-radius: 10px;
                padding: 5px 10px;
                font: bold 14px 'Courier New';
            """)
        
        # Set the text and position it at the bottom right
        self.coords_display.setText(coords_text)
        self.coords_display.adjustSize()
        
        # Position at bottom right
        x = self.width() - self.coords_display.width() - 20
        y = self.height() - self.coords_display.height() - 20
        self.coords_display.move(x, y)
        
        # Make sure it's visible and on top
        self.coords_display.setVisible(True)
        self.coords_display.raise_()
    
    def update_status(self, message, progress):
        """Update the status panel"""
        self.status_panel.set_status(message)
        self.status_panel.set_progress(progress)
    
    def handle_error(self, error_msg):
        """Handle errors from worker threads"""
        self.update_status(f"Error: {error_msg}", 0)
        self.status_panel.set_status("Error: " + error_msg, "")
        
        # Re-enable buttons
        self.capture_btn.setEnabled(True)
        self.analyze_btn.setEnabled(bool(self.screenshot_path))
        self.execute_btn.setEnabled(bool(getattr(self, 'coordinates_data', None)))

    def handle_element_click(self, point):
        """Handle user clicking on image directly"""
        # This enables clicking directly on the image to select elements
        if self.screenshot_path:
            self.coordinates_data = {'type': 'point', 'coords': (point.x(), point.y())}
            self.draw_element_highlight(point.x(), point.y())
            self.execute_btn.setEnabled(True)
            self.update_status(f"Element selected at ({point.x():.3f}, {point.y():.3f})", 100)
        
    def draw_element_highlight(self, x, y):
        """Draw futuristic highlight on selected element"""
        if not self.screenshot_path:
            return
        
        # Create a copy of the screenshot
        img = Image.open(self.screenshot_path)
        width, height = img.size
        draw = ImageDraw.Draw(img)
        
        # Calculate pixel coordinates
        center_x = int(x * width)
        center_y = int(y * height)
        radius = max(20, min(width, height) // 20)
        
        # Draw targeting reticle/crosshair (more futuristic)
        # Outer circle
        draw.ellipse((center_x - radius, center_y - radius, 
                     center_x + radius, center_y + radius), 
                     outline="#00E5FF", width=2)
        
        # Inner circle
        inner_radius = radius // 2
        draw.ellipse((center_x - inner_radius, center_y - inner_radius, 
                     center_x + inner_radius, center_y + inner_radius), 
                     outline="#00E5FF", width=1)
        
        # Crosshair lines
        line_length = radius * 1.5
        # Horizontal
        draw.line((center_x - line_length, center_y, 
                   center_x - radius, center_y), 
                   fill="#00E5FF", width=2)
        draw.line((center_x + radius, center_y, 
                   center_x + line_length, center_y), 
                   fill="#00E5FF", width=2)
        # Vertical
        draw.line((center_x, center_y - line_length, 
                   center_x, center_y - radius), 
                   fill="#00E5FF", width=2)
        draw.line((center_x, center_y + radius, 
                   center_x, center_y + line_length), 
                   fill="#00E5FF", width=2)
        
        # Draw diagonal corners (like a targeting system)
        corner_size = radius // 2
        # Top-left
        draw.line((center_x - radius, center_y - radius, 
                   center_x - radius + corner_size, center_y - radius), 
                   fill="#00E5FF", width=2)
        draw.line((center_x - radius, center_y - radius, 
                   center_x - radius, center_y - radius + corner_size), 
                   fill="#00E5FF", width=2)
        # Top-right
        draw.line((center_x + radius, center_y - radius, 
                   center_x + radius - corner_size, center_y - radius), 
                   fill="#00E5FF", width=2)
        draw.line((center_x + radius, center_y - radius, 
                   center_x + radius, center_y - radius + corner_size), 
                   fill="#00E5FF", width=2)
        # Bottom-left
        draw.line((center_x - radius, center_y + radius, 
                   center_x - radius + corner_size, center_y + radius), 
                   fill="#00E5FF", width=2)
        draw.line((center_x - radius, center_y + radius, 
                   center_x - radius, center_y + radius - corner_size), 
                   fill="#00E5FF", width=2)
        # Bottom-right
        draw.line((center_x + radius, center_y + radius, 
                   center_x + radius - corner_size, center_y + radius), 
                   fill="#00E5FF", width=2)
        draw.line((center_x + radius, center_y + radius, 
                   center_x + radius, center_y + radius - corner_size), 
                   fill="#00E5FF", width=2)
        
        # Save and display the highlighted image
        temp_path = "temp_highlight_image.png"
        img.save(temp_path)
        self.image_viewer.set_image(temp_path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WebAutomationApp()
    window.show()
    sys.exit(app.exec_()) 