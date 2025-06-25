import os
import time
import ffmpeg
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
import uuid
import boto3
from botocore.exceptions import ClientError
import tempfile
from dotenv import load_dotenv
import subprocess
import sys
from flask_cors import CORS
from video_processor import get_video_timestamps, time_str_to_seconds, process_video_with_query_and_extract
import atexit
import shutil

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

# Create local temporary directories
TEMP_UPLOAD_FOLDER = 'temp_uploads'
TEMP_OUTPUT_FOLDER = 'temp_outputs'
os.makedirs(TEMP_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_OUTPUT_FOLDER, exist_ok=True)

# S3 Configuration
S3_BUCKET = 'fossip-restaurants-storage'
S3_VIDEO_PREFIX = 'video_cv/'
S3_OUTPUT_PREFIX = 'video_cv/outputs/'

# Setup AWS S3 client (commented out for local development)
# s3_client = boto3.client('s3',
#                          aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
#                          aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
#                          region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# For local development, we'll use local storage instead of S3
s3_client = None

# Set up Gemini API
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.0-flash')

ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def upload_file_to_s3(file_path, object_name=None):
    """Upload a file to an S3 bucket (commented out for local development)

    :param file_path: Path to local file to upload
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """
    # For local development, just return True since we're not using S3
    if s3_client is None:
        print(f"Local mode: Skipping S3 upload for {file_path}")
        return True
    
    # Original S3 upload code (commented out)
    # if object_name is None:
    #     object_name = os.path.basename(file_path)
    # 
    # try:
    #     s3_client.upload_file(file_path, S3_BUCKET, object_name)
    #     print(f"Successfully uploaded {file_path} to s3://{S3_BUCKET}/{object_name}")
    #     return True
    # except ClientError as e:
    #     print(f"Error uploading to S3: {str(e)}")
    #     return False

def download_file_from_s3(object_name, local_path):
    """Download a file from an S3 bucket (commented out for local development)

    :param object_name: S3 object name to download
    :param local_path: Local path to save the file
    :return: True if file was downloaded, else False
    """
    # For local development, just return True since we're not using S3
    if s3_client is None:
        print(f"Local mode: Skipping S3 download for {object_name}")
        return True
    
    # Original S3 download code (commented out)
    # try:
    #     s3_client.download_file(S3_BUCKET, object_name, local_path)
    #     print(f"Successfully downloaded s3://{S3_BUCKET}/{object_name} to {local_path}")
    #     return True
    # except ClientError as e:
    #     print(f"Error downloading from S3: {str(e)}")
    #     return False

def get_s3_url(object_name):
    """Generate a presigned URL for an S3 object (modified for local development)"""
    # For local development, return a local file path
    if s3_client is None:
        local_path = os.path.join(TEMP_OUTPUT_FOLDER, os.path.basename(object_name))
        print(f"Local mode: Returning local path for {object_name}: {local_path}")
        return f"/outputs/{os.path.basename(object_name)}"
    
    # Original S3 presigned URL code (commented out)
    # try:
    #     url = s3_client.generate_presigned_url('get_object',
    #                                           Params={'Bucket': S3_BUCKET,
    #                                                  'Key': object_name},
    #                                           ExpiresIn=3600)
    #     print(f"Generated presigned URL for s3://{S3_BUCKET}/{object_name}: {url}")
    #     return url
    # except ClientError as e:
    #     print(f"Error generating presigned URL: {str(e)}")
    #     return None

def get_video_timestamps(video_path, user_query, image_path=None):
    try:
        print("Uploading video file...")
        video_file = genai.upload_file(path=video_path)

        while video_file.state.name == "PROCESSING":
            print("Waiting for AI to process the video...")
            time.sleep(10)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError("AI failed to process the video.")

        # Get video duration for better AI guidance
        video_duration = get_video_duration(video_path)
        duration_info = ""
        if video_duration:
            duration_info = f"\nVideo duration: {video_duration:.2f} seconds ({int(video_duration//60):02d}:{int(video_duration%60):02d})"

        system_prompt = (
    "You are a precise video analysis assistant.\n\n"
            "You will be given a video file and possibly an image.\n"
            "You also receive a user query about the content in the video.\n"
            "Your task is to analyze the video and identify the exact start and end timestamps "
            "in the format HH:MM:SS - HH:MM:SS where the requested action, person, or object appears.\n\n"
            "Only output two timestamps in the format HH:MM:SS - HH:MM:SS (24-hour format).\n"
            "• Do NOT provide any additional text, explanation, or description.\n"
            "• Do NOT guess. Only provide timestamps if you are confident they exist within the video's actual duration.\n"
            "• Make sure the timestamps are within the real length of the video and that the start is less than the end.\n"
            "• If the query is about identifying a person or object in the image, match it against the video.\n"
            "VERY IMPORTANT: If the requested action, person, or object does not appear in the video, "
            "output: 00:00:00 - 00:00:00\n\n"
            "Your output must strictly follow the format: HH:MM:SS - HH:MM:SS\n\n"
            f"User Query: {user_query}{duration_info}"
)


        input_parts = [video_file, system_prompt]
        if image_path:
            print(f"Including image: {image_path}")
            pil_image = Image.open(image_path)
            input_parts.insert(1, pil_image)

        response = model.generate_content(input_parts).text.strip()
        print(f"Timestamps: {response}")
        return response
    except Exception as e:
        print(f"Error getting timestamps: {str(e)}")
        return None

def get_video_duration(video_path):
    """Get video duration in seconds"""
    try:
        import json
        import subprocess
        
        # Use ffprobe to get video information
        cmd = [
            'ffprobe', 
            '-v', 'quiet', 
            '-print_format', 'json', 
            '-show_format', 
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error getting video duration: {str(e)}")
        return None

def time_to_seconds(time_str):
    """Convert HH:MM:SS format to seconds"""
    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        else:
            return int(time_str)
    except Exception as e:
        print(f"Error converting time {time_str}: {str(e)}")
        return None

def trim_video(input_path, output_path, start_time, end_time):
    try:
        # Get video duration
        video_duration = get_video_duration(input_path)
        if video_duration is None:
            print("Could not determine video duration")
            return False
        
        # Convert timestamps to seconds
        start_seconds = time_to_seconds(start_time)
        end_seconds = time_to_seconds(end_time)
        
        if start_seconds is None or end_seconds is None:
            print("Invalid timestamp format")
            return False
        
        # Validate timestamps
        if start_seconds >= end_seconds:
            print(f"Invalid timestamps: start ({start_seconds}s) >= end ({end_seconds}s)")
            return False
        
        if start_seconds >= video_duration:
            print(f"Start time ({start_seconds}s) is beyond video duration ({video_duration}s)")
            return False
        
        if end_seconds > video_duration:
            print(f"End time ({end_seconds}s) is beyond video duration ({video_duration}s), adjusting to {video_duration}s")
            end_seconds = video_duration
        
        print(f"Trimming video from {start_time} ({start_seconds}s) to {end_time} ({end_seconds}s)")
        print(f"Video duration: {video_duration}s")
        
        # Trim the video using subprocess, re-encoding to ensure playability
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-ss', start_time,
            '-to', end_time,
            '-y',  # Overwrite output file
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Verify output file was created and has content
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"Video trimmed successfully: {output_path}")
            return True
        else:
            print("Output file is empty or was not created")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr}")
        return False
    except Exception as e:
        print(f"Error trimming video: {str(e)}")
        return False

def cleanup_temp_folders():
    print("Cleaning up temp_uploads and temp_outputs folders...")
    try:
        shutil.rmtree(TEMP_UPLOAD_FOLDER, ignore_errors=True)
        shutil.rmtree(TEMP_OUTPUT_FOLDER, ignore_errors=True)
        os.makedirs(TEMP_UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(TEMP_OUTPUT_FOLDER, exist_ok=True)
    except Exception as e:
        print(f"Error cleaning up temp folders: {e}")

atexit.register(cleanup_temp_folders)

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/app')
def app_main():
    sample = request.args.get('sample')
    return render_template('index.html', sample=sample)

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        image_file = request.files.get('image')
        query = request.form.get('query', '').strip()
        
        if video_file.filename == '':
            return jsonify({'error': 'No video file selected'}), 400
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({'error': 'Invalid video file format'}), 400
        
        # Generate unique ID and filenames
        unique_id = str(uuid.uuid4())
        video_filename = f"{unique_id}_{secure_filename(video_file.filename)}"
        
        # Save files temporarily
        temp_video_path = os.path.join(TEMP_UPLOAD_FOLDER, video_filename)
        video_file.save(temp_video_path)
        
        # For local development, we don't need to upload to S3
        s3_video_key = f"{S3_VIDEO_PREFIX}{video_filename}"
        # upload_file_to_s3(temp_video_path, s3_video_key)  # Commented out for local development
        
        image_path = None
        s3_image_key = None
        if image_file and image_file.filename != '':
            if allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                image_filename = f"{unique_id}_{secure_filename(image_file.filename)}"
                temp_image_path = os.path.join(TEMP_UPLOAD_FOLDER, image_filename)
                image_file.save(temp_image_path)
                s3_image_key = f"{S3_VIDEO_PREFIX}{image_filename}"
                # upload_file_to_s3(temp_image_path, s3_image_key)  # Commented out for local development
                image_path = temp_image_path
        
        return jsonify({
            'video_path': temp_video_path,
            's3_video_key': s3_video_key,
            'image_path': image_path,
            's3_image_key': s3_image_key,
            'query': query,
            'unique_id': unique_id
        })
    
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/api/process-video', methods=['POST'])
def process_video_endpoint():
    if 'video' not in request.files:
        return jsonify({"error": "No video file provided"}), 400
    if 'query' not in request.form:
        return jsonify({"error": "No query provided"}), 400

    video_file = request.files['video']
    query = request.form['query']

    if video_file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    # Save the uploaded video file temporarily
    filename = secure_filename(video_file.filename)
    temp_video_path = os.path.join("temp_uploads", f"{uuid.uuid4()}_{filename}")
    video_file.save(temp_video_path)
    
    image_path = None
    if 'image' in request.files and request.files['image'].filename != '':
        image_file = request.files['image']
        image_filename = secure_filename(image_file.filename)
        temp_image_path = os.path.join("temp_uploads", f"{uuid.uuid4()}_{image_filename}")
        image_file.save(temp_image_path)
        image_path = temp_image_path


    try:
        # Generate a unique filename for the output
        unique_id = os.path.basename(temp_video_path).split('_')[0]
        original_name = '_'.join(os.path.basename(temp_video_path).split('_')[1:])
        output_filename = f"{unique_id}_{os.path.splitext(original_name)[0]}_trimmed.mp4"
        temp_output_path = os.path.join("temp_outputs", output_filename)

        start_time, end_time = process_video_with_query_and_extract(temp_video_path, query, temp_output_path)

        if start_time is not None and end_time is not None:
            download_url = url_for('download_file', filename=output_filename)
            
            return jsonify({
                "found": True,
                "start_time": start_time,
                "end_time": end_time,
                "download_url": download_url
            })
        else:
            return jsonify({
                "found": False,
                "message": "Could not find the requested segment in the video."
            }), 200
    
    except Exception as e:
        print(f"Error during video processing: {e}")
        return jsonify({"error": "An internal error occurred during processing."}), 500
    finally:
        # Clean up the original uploaded file
        import time
        time.sleep(0.5)  # Give the OS time to release the file handle
        if os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception as e:
                print(f"Warning: Could not delete temp file {temp_video_path}: {e}")
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                print(f"Warning: Could not delete temp image {image_path}: {e}")

@app.route('/outputs/<filename>')
def download_file(filename):
    """Serve local output files (modified for local development)"""
    # For local development, serve files directly from temp_outputs folder
    if s3_client is None:
        file_path = os.path.join(TEMP_OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'error': 'File not found'}), 404
    else:
        # Original S3 redirect code (commented out)
        # s3_key = f"{S3_OUTPUT_PREFIX}{filename}"
        # url = get_s3_url(s3_key)
        # if url:
        #     return redirect(url)
        # else:
        #     return jsonify({'error': 'Failed to generate video URL'}), 404
        return jsonify({'error': 'S3 not configured'}), 404

@app.route('/api/chat', methods=['POST'])
def chat_with_video():
    """Chat with the video using it as a knowledge source"""
    try:
        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        message = request.form.get('message')
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400
        
        if video_file.filename == '':
            return jsonify({'error': 'No video file selected'}), 400
        
        # Save the video file temporarily
        filename = secure_filename(video_file.filename)
        temp_video_path = os.path.join(TEMP_UPLOAD_FOLDER, f"{uuid.uuid4()}_{filename}")
        video_file.save(temp_video_path)
        
        try:
            # Upload video to Gemini
            print("Uploading video for chat...")
            gemini_video_file = genai.upload_file(path=temp_video_path)
            
            while gemini_video_file.state.name == "PROCESSING":
                print("Waiting for AI to process the video for chat...")
                time.sleep(10)
                gemini_video_file = genai.get_file(gemini_video_file.name)
            
            if gemini_video_file.state.name == "FAILED":
                return jsonify({'error': 'AI failed to process the video'}), 500
            
            # Create chat prompt
            chat_prompt = f"""You are the video itself. You have been uploaded as a video file and can see and understand everything that happens in the video.

The user is chatting with you as if you ARE the video. Respond to their questions and comments as if you are the video speaking to them.

User message: {message}

Respond naturally as if you are the video having a conversation with the user. Be engaging, informative, and conversational. You can describe what you see, answer questions about your content, and interact with the user as if you are the video itself."""
            
            # Generate response
            response = model.generate_content([gemini_video_file, chat_prompt])
            
            return jsonify({
                'response': response.text,
                'timestamp': time.time()
            })
            
        finally:
            # Clean up the temporary video file
            if os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except Exception as e:
                    print(f"Warning: Could not delete temp chat video {temp_video_path}: {e}")
    
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup-temp', methods=['POST'])
def cleanup_temp():
    try:
        data = request.get_json()
        temp_video_path = data.get('temp_video_path')
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)
            print(f"Temp file {temp_video_path} deleted on tab close.")
        return '', 204
    except Exception as e:
        print(f"Cleanup error: {e}")
        return '', 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
