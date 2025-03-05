import torch
from PIL import Image
from io import BytesIO
import requests
import gradio as gr
from transformers import AutoModelForCausalLM, AutoProcessor

# Global variables to store the model and processor
global_model = None
global_processor = None

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
    
    return image, None

def generate_response(image_input, system_prompt, user_prompt, chat_history, 
                      max_new_tokens=128, temperature=0.0, do_sample=False, num_beams=1):
    """Generate a response from the model based on image and text inputs"""
    # Load model if not already loaded
    model, processor = load_model()
    
    # Process the image
    image, error = process_image(image_input)
    if error:
        return chat_history + [[None, error]]
    
    # Prepare conversation format
    if not chat_history:
        # First message
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
        
        # Add current user message
        convs.append({"role": "user", "content": f"<image_start><image><image_end>\n{user_prompt}"})
    
    # Process inputs
    prompt = processor.tokenizer.apply_chat_template(convs, tokenize=False, add_generation_prompt=True)
    inputs = processor(images=image, texts=prompt, return_tensors="pt")
    inputs['pixel_values'] = inputs['pixel_values'].unsqueeze(0)
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
    
    # Update chat history
    return chat_history + [[user_prompt, response]]

# Define the Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Magma-8B Interactive Demo")
    gr.Markdown("Upload an image or provide an image URL and ask questions about it.")
    
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
            chatbot = gr.Chatbot(label="Conversation", height=600)
    
    # Event handlers
    def use_url_as_image(url):
        return url if url.startswith(("http://", "https://")) else None
    
    image_url.change(use_url_as_image, image_url, image_input)
    
    submit_btn.click(
        generate_response,
        inputs=[
            image_input, system_prompt, user_prompt, chatbot,
            max_tokens, temperature, do_sample, num_beams
        ],
        outputs=[chatbot]
    )
    
    clear_btn.click(lambda: [], outputs=[chatbot])

# Launch the demo
if __name__ == "__main__":
    # Load model on startup (optional, can also load on first request)
    try:
        load_model()
    except Exception as e:
        print(f"Warning: Could not preload model: {e}")
    
    # Launch Gradio app
    demo.launch(share=True) 