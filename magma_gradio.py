import torch
from PIL import Image, ImageDraw
from io import BytesIO
import requests
import gradio as gr
import re
import numpy as np
from transformers import AutoModelForCausalLM, AutoProcessor

# Global variables to store the model and processor
global_model = None
global_processor = None
last_image = None  # Store the last image for drawing bounding boxes

def load_model():
    """Load the model and processor once and reuse"""
    global global_model, global_processor
    
    if global_model is None or global_processor is None:
        print("Loading model and processor...")
        global_processor = AutoProcessor.from_pretrained("microsoft/Magma-8B", trust_remote_code=True)
        global_model = AutoModelForCausalLM.from_pretrained("microsoft/Magma-8B", trust_remote_code=True)
        
        # Use MPS (Apple Silicon) or CUDA depending on availability
        device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        global_model.to(device)
        print(f"Model loaded on {device}")
    
    return global_model, global_processor

def process_image(image_input):
    """Process the image input (either uploaded file or URL)"""
    global last_image
    
    if isinstance(image_input, str) and image_input.startswith(("http://", "https://")):
        # It's a URL
        try:
            image = Image.open(BytesIO(requests.get(image_input, stream=True).content))
        except Exception as e:
            return None, f"Error loading image from URL: {str(e)}"
    elif image_input is not None:
        # It's an uploaded image
        image = Image.fromarray(image_input)
    else:
        return None, "No image provided"
    
    # Convert to RGB (this is required for the model)
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    # Store image for later use with bounding boxes
    last_image = image.copy()
    
    return image, None

def extract_coordinates(text):
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

def draw_bounding_box(image, coordinates_data):
    """Draw a bounding box or point marker on an image"""
    if image is None or coordinates_data is None:
        return None
        
    # Make a copy to avoid modifying the original
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    
    width, height = img_copy.size
    
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
    
    return img_copy

def generate_response(image_input, system_prompt, user_prompt, chat_history, 
                      max_new_tokens=128, temperature=0.0, do_sample=False, num_beams=1):
    """Generate a response from the model based on image and text inputs"""
    global last_image
    
    # Load model if not already loaded
    model, processor = load_model()
    
    # Check if this is a new image or if we're continuing with the previous one
    is_new_image = True
    current_image = None
    
    # Process the image if it's provided
    if image_input is not None:
        current_image, error = process_image(image_input)
        if error:
            return chat_history + [[None, error]], None
    else:
        # No new image provided, check if we have previous messages with an image
        is_new_image = False
        if len(chat_history) > 0:
            # Continue with the last conversation
            pass
        else:
            # First message but no image
            return chat_history + [[user_prompt, "Please provide an image to start the conversation."]], None
    
    # Prepare conversation format
    if not chat_history:
        # First message with a new image
        convs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<image_start><image><image_end>\n{user_prompt}"},
        ]
    else:
        # Continuing conversation
        convs = [{"role": "system", "content": system_prompt}]
        
        # Add previous conversation
        for user_msg, assistant_msg in chat_history:
            convs.append({"role": "user", "content": user_msg})
            convs.append({"role": "assistant", "content": assistant_msg})
        
        # Add current user message - only include image tags if it's a new image
        if is_new_image and current_image is not None:
            convs.append({"role": "user", "content": f"<image_start><image><image_end>\n{user_prompt}"})
        else:
            convs.append({"role": "user", "content": user_prompt})
    
    # Process inputs
    prompt = processor.tokenizer.apply_chat_template(convs, tokenize=False, add_generation_prompt=True)
    
    # Only include image in the processing if it's a new image
    if is_new_image and current_image is not None:
        inputs = processor(images=current_image, texts=prompt, return_tensors="pt")
    else:
        inputs = processor(texts=prompt, return_tensors="pt")
    
    # Handle tensor shapes
    if 'pixel_values' in inputs and inputs['pixel_values'] is not None:
        inputs['pixel_values'] = inputs['pixel_values'].unsqueeze(0)
    if 'image_sizes' in inputs and inputs['image_sizes'] is not None:
        inputs['image_sizes'] = inputs['image_sizes'].unsqueeze(0)
    
    # Send to device
    device = next(model.parameters()).device
    inputs = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}
    
    # Generate response
    generation_args = {
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "do_sample": do_sample,
        "use_cache": True,
        "num_beams": num_beams,
    }
    
    with torch.inference_mode():
        generate_ids = model.generate(**inputs, **generation_args)
    
    # Decode response
    generate_ids = generate_ids[:, inputs["input_ids"].shape[-1]:]
    response = processor.decode(generate_ids[0], skip_special_tokens=True).strip()
    
    # Check for coordinates in the response
    coordinates_data = extract_coordinates(response)
    image_with_box = None
    
    if coordinates_data:
        # Draw bounding box on the image
        image_with_box = draw_bounding_box(last_image, coordinates_data)
    
    # Update chat history - this keeps the image sticky in the UI
    return chat_history + [[user_prompt, response]], image_with_box

def clear_conversation(image):
    """Clear the conversation history but keep the current image"""
    return [], image, None  # Return empty chat history but keep the image and clear the bbox image

# Define the Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Magma-8B Interactive Demo")
    gr.Markdown("Upload an image or provide an image URL and ask questions about it. The image will persist until a new one is uploaded.")
    
    with gr.Row():
        with gr.Column(scale=1):
            # Input controls
            image_input = gr.Image(label="Upload Image", type="numpy")
            image_url = gr.Textbox(label="Or enter an image URL")
            
            system_prompt = gr.Textbox(
                label="System Prompt", 
                value="You are agent that can see, talk and act.",
                lines=2
            )
            
            user_prompt = gr.Textbox(
                label="Your Question", 
                placeholder="What is in this image?",
                lines=2
            )
            
            with gr.Accordion("Advanced Options", open=False):
                max_tokens = gr.Slider(
                    minimum=16, maximum=512, value=128, step=8,
                    label="Max New Tokens"
                )
                temperature = gr.Slider(
                    minimum=0.0, maximum=1.0, value=0.0, step=0.1,
                    label="Temperature"
                )
                do_sample = gr.Checkbox(label="Do Sample", value=False)
                num_beams = gr.Slider(
                    minimum=1, maximum=5, value=1, step=1,
                    label="Number of Beams"
                )
            
            submit_btn = gr.Button("Generate Response")
            clear_btn = gr.Button("Clear Conversation")
        
        with gr.Column(scale=1):
            # Display chat history
            chatbot = gr.Chatbot(label="Conversation", height=400)
            # Display image with bounding box
            bbox_image = gr.Image(label="Image with Bounding Box", type="pil", visible=True)
    
    # Event handlers
    def use_url_as_image(url):
        if url and url.startswith(("http://", "https://")):
            try:
                # Try to load the image to verify it works
                Image.open(BytesIO(requests.get(url, stream=True).content))
                return url
            except:
                return None
        return None
    
    image_url.change(use_url_as_image, image_url, image_input)
    
    submit_btn.click(
        generate_response,
        inputs=[
            image_input, system_prompt, user_prompt, chatbot,
            max_tokens, temperature, do_sample, num_beams
        ],
        outputs=[chatbot, bbox_image]
    )
    
    clear_btn.click(
        clear_conversation,
        inputs=[image_input],
        outputs=[chatbot, image_input, bbox_image]
    )

# Launch the demo
if __name__ == "__main__":
    # Load model on startup (optional, can also load on first request)
    try:
        load_model()
    except Exception as e:
        print(f"Warning: Could not preload model: {e}")
    
    # Launch Gradio app
    demo.launch(share=True) 