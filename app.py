import torch
import os  # Make sure os is imported
import torchvision.transforms as T
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from PIL import Image
import io
import base64
import random
import logging

# --- Initialize Flask App ---
app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO)
# Get the directory where this script is running
# This is more robust than a hardcoded path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logging.info(f"Serving files from base directory: {BASE_DIR}")

# Allow requests from the HTML file (still good to keep for file:// access)
CORS(app)

# --- Define Augmentations ---
# We now store a dict with name, the code string (for the modal), and the transform
AUGMENTATION_REGISTRY = {
    "Rotate 90deg": {
        "name": "Rotate 90deg",
        "code": "T.RandomRotation(degrees=(90, 90))",
        "transform": lambda: T.RandomRotation(degrees=(90, 90))
    },
    "Horizontal Flip": {
        "name": "Horizontal Flip",
        "code": "T.RandomHorizontalFlip(p=1.0)",
        "transform": lambda: T.RandomHorizontalFlip(p=1.0)
    },
    "Vertical Flip": {
        "name": "Vertical Flip",
        "code": "T.RandomVerticalFlip(p=1.0)",
        "transform": lambda: T.RandomVerticalFlip(p=1.0)
    },
    "Grayscale": {
        "name": "Grayscale",
        "code": "T.RandomGrayscale(p=1.0)",
        "transform": lambda: T.RandomGrayscale(p=1.0)
    },
    "Gaussian Blur": {
        "name": "Gaussian Blur",
        "code": "T.GaussianBlur(kernel_size=(23, 23), sigma=(5.0, 5.0))",
        "transform": lambda: T.GaussianBlur(kernel_size=(23, 23), sigma=(5.0, 5.0))
    },
    "Solarize": {
        "name": "Solarize",
        "code": "T.RandomSolarize(threshold=128.0, p=1.0)",
        "transform": lambda: T.RandomSolarize(threshold=128.0, p=1.0)
    },
    "Posterize": {
        "name": "Posterize",
        "code": "T.RandomPosterize(bits=2, p=1.0)",
        "transform": lambda: T.RandomPosterize(bits=2, p=1.0)
    },
    "Invert Colors": {
        "name": "Invert Colors",
        "code": "T.RandomInvert(p=1.0)",
        "transform": lambda: T.RandomInvert(p=1.0)
    },
    "Shear": {
        "name": "Shear",
        "code": "T.RandomAffine(degrees=0, shear=30)",
        "transform": lambda: T.RandomAffine(degrees=0, shear=30)
    },
    "Jitter Colors": {
        "name": "Jitter Colors",
        "code": "T.ColorJitter(brightness=0.7, contrast=0.7, saturation=0.7, hue=0.3)",
        "transform": lambda: T.ColorJitter(brightness=0.7, contrast=0.7, saturation=0.7, hue=0.3)
    },
    "Zoom Out": {
        "name": "Zoom Out",
        "code": "T.RandomAffine(degrees=0, scale=(0.6, 0.6))",
        "transform": lambda: T.RandomAffine(degrees=0, scale=(0.6, 0.6))
    },
    "AutoContrast": {
        "name": "AutoContrast",
        "code": "T.RandomAutocontrast(p=1.0)",
        "transform": lambda: T.RandomAutocontrast(p=1.0)
    },
}
# Get all available augmentation data (list of dicts)
# This is ONLY used on the backend
ALL_AUGMENTATIONS_DATA = list(AUGMENTATION_REGISTRY.values())
# Get just the names
ALL_AUGMENTATION_NAMES = list(AUGMENTATION_REGISTRY.keys())

# --- Backend State (Simple) ---
original_pieces = []
correct_aug_names = []
# Store the full original image for the final reveal
original_full_image_b64 = None

# --- Helper Function ---
def pil_to_base64(pil_img):
    """Converts a PIL Image to a base64 encoded string."""
    img_io = io.BytesIO()
    # Ensure image is RGB for consistent saving
    if pil_img.mode != 'RGB':
        pil_img = pil_img.convert('RGB')
    pil_img.save(img_io, 'JPEG', quality=95)
    img_io.seek(0)
    return base64.b64encode(img_io.getvalue()).decode('utf-8')

# --- API Endpoints ---

# This route serves the index.html file
@app.route('/')
def index():
    # Use the dynamic BASE_DIR path
    index_path = os.path.join(BASE_DIR, 'index.html')
    if os.path.exists(index_path):
        # Serve 'index.html' from the BASE_DIR
        return send_from_directory(BASE_DIR, 'index.html')
    
    app.logger.error(f"index.html not found at {index_path}")
    # Provide a more helpful error message
    return f"Error: 'index.html' not found. Make sure 'index.html' is in the same directory as 'app.py' ({BASE_DIR})", 404


@app.route('/upload', methods=['POST'])
def upload_image():
    global original_pieces, correct_aug_names, original_full_image_b64
    
    if 'image' not in request.files:
        app.logger.warning("Upload attempt with no image file.")
        return jsonify({"error": "No image file found"}), 400

    file = request.files['image']
    try:
        img = Image.open(file.stream).convert('RGB')
    except Exception as e:
        app.logger.error(f"Invalid image file uploaded: {e}")
        return jsonify({"error": f"Invalid image file: {e}"}), 400

    # Clear previous game state
    original_pieces.clear()
    correct_aug_names.clear()

    # --- Crop to square first ---
    width, height = img.size
    min_dim = min(width, height)
    img = T.CenterCrop(min_dim)(img)
    
    # --- Store full original image ---
    original_full_image_b64 = pil_to_base64(img)

    # --- Split Image into 9 Pieces ---
    width, height = img.size # Re-get dimensions after square crop
    piece_w, piece_h = width // 3, height // 3
    if piece_w == 0 or piece_h == 0:
        app.logger.error(f"Image too small to split: {width}x{height}")
        return jsonify({"error": "Image is too small to split"}), 400
        
    # This crop ensures the image is perfectly divisible by 3
    img = T.CenterCrop((piece_h * 3, piece_w * 3))(img)
    
    augmented_base64 = []
    
    # Randomly select 9 unique augmentations for this game
    if len(ALL_AUGMENTATION_NAMES) < 9:
         app.logger.error("Not enough augmentations defined in registry.")
         return jsonify({"error": "Not enough augmentations defined"}), 500
         
    game_augs = random.sample(ALL_AUGMENTATION_NAMES, 9)

    for i in range(9):
        row, col = i // 3, i % 3
        
        # Define the box to crop
        left = col * piece_w
        top = row * piece_h
        right = (col + 1) * piece_w
        bottom = (row + 1) * piece_h
        
        box = (left, top, right, bottom)
        piece = img.crop(box)
        
        # Store the original piece
        original_pieces.append(piece)
        
        # --- Apply Augmentation ---
        aug_name = game_augs[i]
        correct_aug_names.append(aug_name)
        
        # Get the transform function from the registry and call it
        transform_func = AUGMENTATION_REGISTRY[aug_name]["transform"]()
        
        # Apply the transform
        augmented_piece = transform_func(piece)
        
        # Convert to base64 to send to frontend
        augmented_base64.append(pil_to_base64(augmented_piece))

    # --- FIX APPLIED HERE ---
    # Create a list of augmentations that is safe to send as JSON
    # It only contains the 'name' and 'code' keys, not the 'transform' function
    frontend_augs_data = [
        {"name": aug["name"], "code": aug["code"]} 
        for aug in ALL_AUGMENTATIONS_DATA
    ]

    app.logger.info("Successfully processed upload and created game.")
    return jsonify({
        "augmented_images": augmented_base64,
        "all_augmentations": frontend_augs_data, # Use the JSON-safe list
        "original_full_image": original_full_image_b64 # Send the full image
    })


@app.route('/guess', methods=['POST'])
def make_guess():
    global original_pieces, correct_aug_names

    data = request.json
    index = data.get('index')
    guess_name = data.get('guess_name') # The guess is the 'name', e.g., "Gaussian Blur"
    attempts_left = data.get('attempts_left')

    # Basic validation
    if index is None or guess_name is None or attempts_left is None:
        app.logger.warning(f"Guess attempt with missing data: {data}")
        return jsonify({"error": "Missing data: index, guess_name, or attempts_left"}), 400
    
    if not (0 <= index < len(original_pieces)):
        app.logger.warning(f"Guess attempt with invalid index: {index}")
        return jsonify({"error": "Invalid index"}), 400

    correct_name = correct_aug_names[index]
    original_piece = original_pieces[index]
    original_img_b64 = pil_to_base64(original_piece)

    if guess_name == correct_name:
        app.logger.info(f"Correct guess for index {index}: {guess_name}")
        # --- CORRECT GUESS ---
        return jsonify({
            "correct": True,
            "original_image": original_img_b64
        })
    else:
        app.logger.info(f"Wrong guess for index {index}: guessed {guess_name}, was {correct_name}")
        # --- WRONG GUESS ---
        attempts_left -= 1
        
        # Get the effect of the *wrong* augmentation
        wrong_transform_func_lookup = AUGMENTATION_REGISTRY.get(guess_name, {}).get("transform")
        
        if not wrong_transform_func_lookup:
             # Default to identity if guess_name is somehow invalid
             app.logger.warning(f"Could not find transform for guessed name: {guess_name}. Defaulting to Identity.")
             wrong_transform_func = lambda: T.RandomIdentity()
        else:
            wrong_transform_func = wrong_transform_func_lookup()

        wrong_effect_img = wrong_transform_func(original_piece)
        wrong_effect_b64 = pil_to_base64(wrong_effect_img)
        
        if attempts_left > 0:
            # Still has attempts left
            return jsonify({
                "correct": False,
                "wrong_guess_effect": wrong_effect_b64,
                "attempts_left": attempts_left
            })
        else:
            app.logger.info(f"Out of attempts for index {index}")
            # --- OUT OF ATTEMPTS ---
            return jsonify({
                "correct": False,
                "wrong_guess_effect": wrong_effect_b64,
                "attempts_left": 0,
                "correct_answer": correct_name,
                "original_image": original_img_b64 # Send original to show the final answer
            })

# --- Run the Server ---
if __name__ == '__main__':
    print("==================================================")
    print("Starting Flask server on http://127.0.0.1:5000")
    print(f"To play, open http://127.0.0.1:5000 in your browser.")
    print("Make sure 'index.html' is in the same folder as this script.")
    print("==================================================")
    # Using host='0.0.0.0' can also help if 127.0.0.1 has issues
    # But let's stick to 127.0.0.1 for simplicity first.
    app.run(debug=True, port=5000)

