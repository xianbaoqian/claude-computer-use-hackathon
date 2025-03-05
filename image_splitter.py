from PIL import Image

def split_image(image_path, output_prefix="split_image"):
    """
    Split an image into four equal parts and save them as separate files.
    
    Args:
        image_path (str): Path to the input image
        output_prefix (str): Prefix for the output filenames
    """
    # Open the image
    img = Image.open(image_path)
    
    # Get dimensions
    width, height = img.size
    
    # Calculate dimensions for each quadrant
    mid_x = width // 2
    mid_y = height // 2
    
    # Define the four quadrants (left, upper, right, lower)
    quadrants = [
        (0, 0, mid_x, mid_y),          # Top-left
        (mid_x, 0, width, mid_y),      # Top-right
        (0, mid_y, mid_x, height),     # Bottom-left
        (mid_x, mid_y, width, height)  # Bottom-right
    ]
    
    # Extract and save each quadrant
    for i, quad in enumerate(quadrants):
        box = quad
        region = img.crop(box)
        region.save(f"{output_prefix}_{i+1}.png")
        print(f"Saved {output_prefix}_{i+1}.png")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        input_image = sys.argv[1]
        split_image(input_image)
    else:
        print("Usage: python image_splitter.py <image_path>") 