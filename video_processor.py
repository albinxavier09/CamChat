import google.generativeai as genai
import time
import os
import cv2
import subprocess

# Configure Gemini AI
# os.environ['GOOGLE_API_KEY'] = 'AIzaSyAYNvTqJCnZ7Ihs4C4KzjF5DE9h3IeXAoY'  # REMOVE THIS LINE
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash-latest')

def generate_stream(inputs):
    start = time.time()
    for result in model.generate_content(
        inputs,
        stream=False,
        generation_config=genai.GenerationConfig(temperature=0.4)
    ):
        processed_text = result.text
        print("Gemini Output:", processed_text)
    end = time.time()
    print(f"⏱ Gemini processing took {end - start:.2f} seconds")
    return processed_text

def extract_video_segment(input_video_path, start_time, end_time, output_video_path):
    def time_to_seconds(t):
        parts = list(map(int, t.split(':')))
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:
            raise ValueError("Invalid timestamp format.")

    start_sec = time_to_seconds(start_time)
    end_sec = time_to_seconds(end_time)

    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        raise IOError("Error opening video file.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)

    if start_frame >= total_frames or end_frame > total_frames or start_frame >= end_frame:
        raise ValueError("Invalid start or end time.")

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    print("⏳ Extracting video segment...")
    extract_start = time.time()

    current_frame = start_frame
    while current_frame < end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
        current_frame += 1

    cap.release()
    out.release()
    extract_end = time.time()
    print(f" Video segment saved to {output_video_path}")
    print(f" Video extraction took {extract_end - extract_start:.2f} seconds")

def encode_to_h264(input_path, output_path):
    print("🎞️ Re-encoding video to H.264 format using ffmpeg (subprocess)...")
    start = time.time()

    command = ['ffmpeg', '-i', input_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', output_path]

    try:
        subprocess.run(command, check=True)
        end = time.time()
        print(f" H.264 encoded video saved as {output_path}")
        print(f" Encoding took {end - start:.2f} seconds")
    except subprocess.CalledProcessError as e:
        print(f" FFmpeg encoding failed: {e}")
        raise

def process_video_with_query_and_extract(video_path, user_query, output_path):
    script_start = time.time()

    print("⏫ Uploading file...")
    upload_start = time.time()
    video_file = genai.upload_file(path=video_path)
    upload_end = time.time()
    print(f"Completed upload: {video_file.uri}")
    print(f" Upload took {upload_end - upload_start:.2f} seconds")

    wait_start = time.time()
    while video_file.state.name == "PROCESSING":
        print(" Waiting for Gemini to process the video...")
        time.sleep(10)
        video_file = genai.get_file(video_file.name)
    wait_end = time.time()
    print(f" Processing wait time: {wait_end - wait_start:.2f} seconds")

    if video_file.state.name == "FAILED":
        raise ValueError("Gemini failed to process the video.")

    system_prompt = (
        "You are a precise video analysis assistant.\n\n"
        "You will be provided with a video file and a specific user query about the video content.\n"
        "Your task is to analyze the **entire video**, review its **actual content and duration**, and identify the **exact start and end timestamps** "
        "in the format HH:MM:SS - HH:MM:SS, corresponding to where the requested action or event occurs in the video.\n\n"
        "⚠ Strict Output Instructions:\n"
        "• Only output two timestamps in the format HH:MM:SS - HH:MM:SS (24-hour format).\n"
        "• Do NOT provide any additional text, explanation, or description.\n"
        "• Do NOT guess. Only provide timestamps if you are confident they exist within the video's actual duration.\n"
        "• Make sure the timestamps are within the real length of the video and that the start is less than the end.\n"
        "• If the action is not found in the video, return exactly: NONE - NONE\n\n"
        f"User Query: {user_query}"
    )

    inputs = [video_file, system_prompt]
    response = generate_stream(inputs).strip()

    try:
        if 'NONE - NONE' in response:
            return None, None

        if '-' in response:
            start_time_raw, end_time_raw = response.split('-')
            start_time = start_time_raw.strip()
            end_time = end_time_raw.strip()

            if len(start_time.split(':')) == 2:
                start_time = f"00:{start_time}"
            if len(end_time.split(':')) == 2:
                end_time = f"00:{end_time}"

            print(f" Extracted Start: {start_time}, End: {end_time}")
            
            # Create a temporary segment file
            temp_segment_path = os.path.join(os.path.dirname(output_path), f"temp_{os.path.basename(output_path)}")
            extract_video_segment(video_path, start_time, end_time, temp_segment_path)
            
            # Encode to H.264
            encode_to_h264(temp_segment_path, output_path)
            
            # Remove temporary file
            os.remove(temp_segment_path)

            start_sec = time_str_to_seconds(start_time)
            end_sec = time_str_to_seconds(end_time)

            return start_sec, end_sec
        else:
            raise ValueError("Expected '-' separator in timestamp response.")
    except Exception as e:
        raise ValueError(f"Could not extract timestamps from Gemini output: {e}")

    script_end = time.time()
    print(f" Total script execution time: {script_end - script_start:.2f} seconds")
    return None, None

def time_str_to_seconds(time_str):
    """Converts a time string in [HH:]MM:SS or SS format to seconds."""
    try:
        parts = str(time_str).strip().split(':')
        seconds = 0
        if len(parts) == 3:  # HH:MM:SS
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:  # MM:SS
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:  # SS
            seconds = int(parts[0])
        return float(seconds)
    except (ValueError, IndexError) as e:
        print(f"Error converting time string '{time_str}' to seconds: {e}")
        # Fallback for simple float conversion
        try:
            return float(time_str)
        except (ValueError, TypeError):
            return None

def get_video_timestamps(video_path: str, query: str, image_path: str = None) -> (str, str):
    """
    Analyzes the video with a multimodal model to get the start and end timestamps.
    """
    # ... existing code ...
