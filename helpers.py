import cv2
import numpy as np
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from config import CONFIG

# ========= CONFIG =========
RETRY_SECONDS = CONFIG["RETRY_SECONDS"]
TARGET_HEIGHT = CONFIG["TARGET_HEIGHT"]


# ========= UTIL / LOG =========
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def open_capture(url: str):
    """Open video capture with FFmpeg backend preference."""
    backend = getattr(cv2, "CAP_FFMPEG", 0)
    cap = cv2.VideoCapture(url, backend)
    return cap


# ========= IMAGE HELPERS =========
def make_placeholder(text: str, w: int = 640, h: int = TARGET_HEIGHT):
    # Returns a basic background image. 
    # Text annotation is now handled by draw_overlay on the PIL image for better font rendering.
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (w, h), (64, 64, 64), thickness=-1)
    return canvas


def draw_overlay(pil_image, header: str, status: str, stale: bool, motion_active: bool = False, motion_alpha: float = 1.0):
    """
    Draws text overlay on a PIL Image using Calibri (if available) or default font.
    If motion_active is True, draws a thick blue border with alpha opacity.
    """
    w, h = pil_image.size
    
    # Draw Motion Border if Active
    if motion_active:
        # Create a transparent layer for the border
        overlay = Image.new('RGBA', pil_image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        alpha_int = int(255 * motion_alpha)
        border_color = (0, 0, 255, alpha_int) # Blue with Alpha
        border_width = 4
        
        # Draw rectangle on overlay
        overlay_draw.rectangle([(0,0), (w-1, h-1)], outline=border_color, width=border_width)
        
        # Composite back onto original image (converted to RGBA for composition if needed, or just alpha_composite)
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')
        
        pil_image = Image.alpha_composite(pil_image, overlay)
        
    # Re-create draw object for text (on the possibly new image object)
    draw = ImageDraw.Draw(pil_image)
    
    # Determine status text
    display_status = status
    if stale or "drop" in status.lower() or "connect" in status.lower() or "error" in status.lower():
        # Check if header is already part of text passed from placeholder logic
        if ":" in status and "reconnecting" in status:
             # Avoid double header if status is complex
             pass 
        else:
             display_status = "(Frozen, reconnecting)"

    text = f"{header} - {display_status}"
    
    # Load Calibri, fallback to default
    try:
        # Size 16 (smaller than previous large CV2 font)
        font = ImageFont.truetype("calibri.ttf", 16)
    except IOError:
        try:
             # Try Linux standard path or generic name
             font = ImageFont.truetype("LiberationSans-Regular.ttf", 16)
        except IOError:
             font = ImageFont.load_default()

    # Text Position
    x, y = 12, 12
    
    # Draw Shadow/Outline for visibility
    # Simulating outline by drawing text in black at offsets
    outline_color = "black"
    text_color = "white"
    
    # Thinner outline for smaller font
    offsets = [(-1, -1), (-1, 1), (1, -1), (1, 1)] 
    for ox, oy in offsets:
        draw.text((x + ox, y + oy), text, font=font, fill=outline_color)
        
    # Main Text
    draw.text((x, y), text, font=font, fill=text_color)
    
    return pil_image


# ========= IMAGE PROCESSING =========
def letterbox_to_size(img, out_w: int, out_h: int):
    """
    Create a black canvas (out_h, out_w) and center the image scaled-to-fit.
    """
    h, w = img.shape[:2]
    scale = min(out_w / float(w), out_h / float(h))
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)  # BLACK background
    y = (out_h - new_h) // 2
    x = (out_w - new_w) // 2
    canvas[y : y + new_h, x : x + new_w] = resized
    return canvas
