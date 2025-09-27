import io
import os
import tempfile
from PIL import Image, ImageDraw, ImageFont, ImageSequence, ImageEnhance
import numpy as np
import streamlit as st
import moviepy.editor as mpy

st.set_page_config(page_title="Multimedia Text Watermark Tool", layout="centered")
st.title("Multimedia Text Watermark Tool (Image / GIF / MP4)")

# Upload source file
uploaded = st.file_uploader(
    "Upload Image/GIF/Video (PNG JPG JPEG GIF MP4 MOV WEBM)",
    type=["png", "jpg", "jpeg", "gif", "mp4", "mov", "webm"]
)

# Select watermark type (Text or Image)
watermark_type = st.radio("Watermark Type", ["Text", "Image"])

# Upload font (optional)
font_file = st.file_uploader("Optional: Upload font file TTF or OTF (use default if not uploaded)", type=["ttf", "otf"])

# Create corresponding UI elements based on watermark type
text = None
wm_image_file = None

if watermark_type == "Text":
    text = st.text_area("Watermark Text (supports multiline)", value="Sample Watermark")
elif watermark_type == "Image":
    wm_image_file = st.file_uploader("Upload watermark image (PNG with transparency recommended)", type=["png", "jpg", "jpeg", "gif"], key="wm_img")

# Common settings
color = st.color_picker("Text Color", "#FFFFFF")
size = st.slider("Text Size (px)", 8, 400, 48)
scale_percent = st.slider("Image Watermark Size Percentage (relative to processed image width)", 1, 100, 10)
opacity = st.slider("Opacity", 0.0, 1.0, 0.6)
position = st.selectbox("Position", ["top-left", "top-right", "center", "bottom-left", "bottom-right"])
angle = st.slider("Rotation Angle", -180, 180, 0)
tile = st.checkbox("Tile Watermark (repeat over entire image/frame)", value=False)

# New: Tile density (smaller is denser)
tile_density = st.slider("Tile Density (smaller is denser)", 0.3, 3.0, 1.5, step=0.1)

output_format = st.selectbox("Download Format (for image/GIF)", ["JPEG", "PNG", "GIF"])

def load_font(font_file_obj, size):
    try:
        if font_file_obj:
            font_bytes = font_file_obj.read()
            return ImageFont.truetype(io.BytesIO(font_bytes), size)
        for name in ("arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def text_size(draw, text, font):
    try:
        bbox = draw.multiline_textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        lines = text.splitlines() or [""]
        widths = [draw.textsize(line, font=font)[0] for line in lines]
        heights = [draw.textsize(line, font=font)[1] for line in lines]
        return max(widths), sum(heights) + (len(lines) - 1) * int(0.2 * font.size)

def create_text_image(text, font, fill, alpha, angle):
    dummy = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    d = ImageDraw.Draw(dummy)
    w, h = text_size(d, text, font)
    text_img = Image.new("RGBA", (w + 10, h + 10), (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_img)
    rgba = tuple(int(fill.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (int(255 * alpha),)
    draw.multiline_text((5, 5), text, font=font, fill=rgba, align="left")
    if angle != 0:
        text_img = text_img.rotate(angle, expand=True)
    return text_img

def adjust_opacity(pil_img, alpha):
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    if alpha >= 0.999:
        return pil_img
    a = pil_img.split()[-1]
    a = ImageEnhance.Brightness(a).enhance(alpha)
    pil_img.putalpha(a)
    return pil_img

def create_image_watermark(wm_file, base_size, scale_percent, alpha, angle):
    wm = Image.open(wm_file).convert("RGBA")
    base_w, base_h = base_size
    target_w = max(1, int(base_w * (scale_percent / 100.0)))
    wpercent = (target_w / float(wm.width))
    target_h = int((float(wm.height) * float(wpercent)))
    wm = wm.resize((target_w, target_h), resample=Image.LANCZOS)
    wm = adjust_opacity(wm, alpha)
    if angle != 0:
        wm = wm.rotate(angle, expand=True)
    return wm

def paste_watermark_on_frame(frame_img, watermark_img, pos, tile_flag, density):
    base = frame_img.convert("RGBA")
    tw, th = watermark_img.size
    txt_layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
    if tile_flag:
        # Use density to control step; smaller density means smaller step and denser tiling
        step_x = max(1, int(max(1, tw) * density))
        step_y = max(1, int(max(1, th) * density))
        for yy in range(0, base.height, step_y):
            for xx in range(0, base.width, step_x):
                txt_layer.paste(watermark_img, (xx, yy), watermark_img)
    else:
        if pos == "top-left":
            x, y = 10, 10
        elif pos == "top-right":
            x, y = base.width - tw - 10, 10
        elif pos == "center":
            x, y = (base.width - tw) // 2, (base.height - th) // 2
        elif pos == "bottom-left":
            x, y = 10, base.height - th - 10
        else:
            x, y = base.width - tw - 10, base.height - th - 10
        txt_layer.paste(watermark_img, (x, y), watermark_img)
    out = Image.alpha_composite(base, txt_layer)
    return out

def process_static_image(img, font, wm_type, wm_image_file):
    base = img.convert("RGBA")
    if wm_type == "Text":
        text_img = create_text_image(text, font, color, opacity, angle)
        out = paste_watermark_on_frame(base, text_img, position, tile, tile_density)
        return out
    else:  # Image watermark
        wm = create_image_watermark(wm_image_file, (base.width, base.height), scale_percent, opacity, angle)
        out = paste_watermark_on_frame(base, wm, position, tile, tile_density)
        return out

def process_gif(img, font, wm_type, wm_image_file):
    frames = []
    durations = []
    for frame in ImageSequence.Iterator(img):
        frame = frame.convert("RGBA")
        if wm_type == "Text":
            text_img = create_text_image(text, font, color, opacity, angle)
            out = paste_watermark_on_frame(frame, text_img, position, tile, tile_density)
        else:
            wm = create_image_watermark(wm_image_file, (frame.width, frame.height), scale_percent, opacity, angle)
            out = paste_watermark_on_frame(frame, wm, position, tile, tile_density)
        frames.append(out)
        durations.append(frame.info.get("duration", 100))
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=durations,
        disposal=2,
        optimize=False
    )
    buf.seek(0)
    return buf

def process_video(uploaded_file, font, wm_type, wm_image_file):
    tmp_in = tempfile.NamedTemporaryFile(suffix=os.path.splitext(uploaded_file.name)[1], delete=False)
    tmp_in.write(uploaded_file.getbuffer())
    tmp_in.flush()
    tmp_in.close()
    clip = mpy.VideoFileClip(tmp_in.name)

    if wm_type == "Text":
        pil_text = create_text_image(text, font, color, opacity, angle)
        txt_np = np.array(pil_text)
        txt_clip = mpy.ImageClip(txt_np).set_duration(clip.duration)
    else:
        base_w, base_h = clip.w, clip.h
        wm = create_image_watermark(wm_image_file, (base_w, base_h), scale_percent, opacity, angle)
        if tile:
            # Use density to determine step
            tiled = Image.new("RGBA", (base_w, base_h), (255, 255, 255, 0))
            step_x = max(1, int(max(1, wm.width) * tile_density))
            step_y = max(1, int(max(1, wm.height) * tile_density))
            for yy in range(0, base_h, step_y):
                for xx in range(0, base_w, step_x):
                    tiled.paste(wm, (xx, yy), wm)
            txt_np = np.array(tiled)
            txt_clip = mpy.ImageClip(txt_np).set_duration(clip.duration)
        else:
            txt_np = np.array(wm)
            txt_clip = mpy.ImageClip(txt_np).set_duration(clip.duration)

    tw, th = txt_clip.w, txt_clip.h
    if position == "top-left":
        pos = (10, 10)
    elif position == "top-right":
        pos = (clip.w - tw - 10, 10)
    elif position == "center":
        pos = ("center", "center")
    elif position == "bottom-left":
        pos = (10, clip.h - th - 10)
    else:
        pos = (clip.w - tw - 10, clip.h - th - 10)

    txt_clip = txt_clip.set_pos(pos).set_opacity(1.0 if opacity >= 1.0 else opacity)
    final = mpy.CompositeVideoClip([clip, txt_clip])
    tmp_out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_out.close()
    final.write_videofile(tmp_out.name, codec="libx264", audio_codec="aac", verbose=False, logger=None)

    with open(tmp_out.name, "rb") as f:
        data = f.read()
    try:
        os.remove(tmp_in.name)
        os.remove(tmp_out.name)
    except Exception:
        pass
    return io.BytesIO(data)

# Main process
if uploaded:
    try:
        uploaded.seek(0)
        fmt = uploaded.name.split(".")[-1].lower()
        font = load_font(font_file, size)
        wm_file_for_image = wm_image_file if watermark_type == "Image" else None

        if fmt in ("png", "jpg", "jpeg"):
            img = Image.open(uploaded)
            out = process_static_image(img, font, watermark_type, wm_file_for_image)
            st.image(out, caption="Watermarked Preview", use_container_width=True)
            buf = io.BytesIO()
            if output_format == "JPEG":
                out.convert("RGB").save(buf, format="JPEG", quality=95)
                mime = "image/jpeg"
                filename = "watermarked.jpg"
            elif output_format == "PNG":
                out.save(buf, format="PNG")
                mime = "image/png"
                filename = "watermarked.png"
            else:
                out.save(buf, format="GIF")
                mime = "image/gif"
                filename = "watermarked.gif"
            buf.seek(0)
            st.download_button("Download Watermarked File", data=buf, file_name=filename, mime=mime)

        elif fmt == "gif":
            img = Image.open(uploaded)
            buf = process_gif(img, font, watermark_type, wm_file_for_image)
            st.image(buf, caption="Watermarked GIF Preview", use_container_width=True)
            st.download_button("Download Watermarked GIF", data=buf, file_name="watermarked.gif", mime="image/gif")

        elif fmt in ("mp4", "mov", "webm"):
            st.info("Processing video, this may take a while depending on video length and server resources...")
            buf = process_video(uploaded, font, watermark_type, wm_file_for_image)
            st.video(buf)
            buf.seek(0)
            st.download_button("Download Watermarked Video", data=buf, file_name="watermarked.mp4", mime="video/mp4")

        else:
            st.error("Unsupported file type.")
    except Exception as e:
        st.error(f"Error occurred during processing: {e}")
else:
    st.info("Please upload an image, GIF, or video to start.")
