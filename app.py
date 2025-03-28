import os
import json
import logging
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
# Try a different import approach for Flask-Session
try:
    from flask_session import Session
except ImportError:
    # Alternative approach if direct import fails
    from flask.ext.session import Session
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'mp3', 'wav', 'm4a', 'ogg', 'flac'}

# Session configuration
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.environ.get('SESSION_FILE_DIR', 'flask_session')
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes

# Ensure required directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)  # Ensure session directory exists

# Initialize Flask-Session
try:
    Session(app)
    logger.info("Flask-Session initialized successfully")
except Exception as e:
    logger.warning(f"Could not initialize Flask-Session: {e}")
    # Fallback to Flask's default session
    logger.info("Using Flask's default session management")

# API Keys - read only from environment variables
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    # Check if file part exists in request
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    
    # Check if user submitted an empty form
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    
    # Check if file is allowed
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Store filepath in session for processing
        session['filepath'] = filepath
        session['filename'] = filename
        
        return redirect(url_for('process_file'))
    else:
        flash('File type not allowed. Please upload an audio file (mp3, wav, m4a, ogg, flac)')
        return redirect(request.url)

@app.route('/process', methods=['GET'])
def process_file():
    filepath = session.get('filepath')
    if not filepath or not os.path.exists(filepath):
        flash('No file to process')
        return redirect(url_for('index'))
    
    # Step 1: Convert audio to text using ElevenLabs API
    transcription_result = speech_to_text(filepath)
    if not transcription_result:
        flash('Failed to transcribe audio')
        return redirect(url_for('index'))
    
    # Step 2: Process the transcription to separate speakers
    processed_transcription = process_transcription(transcription_result)
    
    # Step 3: Summarize the transcription using Gemini API
    summary = summarize_text(processed_transcription)
    
    # Store results in session
    session['transcription'] = processed_transcription
    session['summary'] = summary
    
    return redirect(url_for('results'))

@app.route('/results', methods=['GET'])
def results():
    transcription = session.get('transcription', '')
    summary = session.get('summary', '')
    filename = session.get('filename', '')
    
    return render_template('results.html', 
                          transcription=transcription, 
                          summary=summary, 
                          filename=filename)

def speech_to_text(audio_file_path):
    """Convert speech to text using ElevenLabs API"""
    try:
        logger.info(f"Starting speech to text conversion for {audio_file_path}")
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = {
            "model_id": "scribe_v1",
            "diarize": True,  # Speaker diarization
        }
        
        if not os.path.exists(audio_file_path):
            logger.error(f"Audio file not found: {audio_file_path}")
            return None
            
        with open(audio_file_path, "rb") as audio_file:
            files = {"file": audio_file}
            logger.info("Sending request to ElevenLabs API")
            response = requests.post(url, headers=headers, data=data, files=files)
        
        if response.status_code == 200:
            logger.info("Successfully converted speech to text")
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.exception(f"Exception in speech_to_text: {e}")
        return None

def process_transcription(data):
    """Process the transcription to separate speakers"""
    if not data or 'words' not in data:
        return "No transcription data available"
    
    transcription = []
    current_speaker = None
    current_text = ""
    
    for word in data["words"]:
        speaker = word["speaker_id"]
        text = word["text"]
        
        # If speaker changes, create a new line
        if speaker != current_speaker:
            if current_text:
                transcription.append(f"{current_speaker}: {current_text.strip()}")
            current_speaker = speaker
            current_text = text
        else:
            current_text += " " + text
    
    # Add the last sentence
    if current_text:
        transcription.append(f"{current_speaker}: {current_text.strip()}")
    
    return "\n".join(transcription)

def summarize_text(text):
    """Summarize text using Gemini API"""
    try:
        if not GEMINI_API_KEY:
            return "Error: GEMINI_API_KEY is not set. Please set it in .env file."
        
        prompt = "لطفاً این متن را خلاصه کن:\n\n" + text
        
        url = "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "safetySettings": [],
            "generationConfig": {}
        }
        
        response = requests.post(f"{url}?key={GEMINI_API_KEY}", json=data, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"Gemini API Error: {response.status_code} - {response.text}")
            return f"Failed to summarize text. Error: {response.status_code}"
    except Exception as e:
        print(f"Exception in summarize_text: {e}")
        return f"Failed to summarize text: {str(e)}"

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check if required directories exist
        upload_dir_exists = os.path.exists(app.config['UPLOAD_FOLDER'])
        session_dir_exists = os.path.exists(app.config['SESSION_FILE_DIR'])
        
        # Check API keys
        elevenlabs_key_set = bool(ELEVENLABS_API_KEY)
        gemini_key_set = bool(GEMINI_API_KEY)
        
        # Check Flask-Session
        session_working = False
        try:
            # Test setting a session value
            session['health_check'] = True
            session_working = session.get('health_check', False)
        except Exception as e:
            logger.error(f"Session test failed: {e}")
        
        # Return status
        return jsonify({
            'status': 'healthy',
            'environment': os.environ.get('FLASK_ENV', 'production'),
            'upload_directory': upload_dir_exists,
            'session_directory': session_dir_exists,
            'elevenlabs_api_key_set': elevenlabs_key_set,
            'gemini_api_key_set': gemini_key_set,
            'session_working': session_working,
            'version': '1.0.1'
        })
    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

@app.errorhandler(404)
def page_not_found(e):
    logger.error(f"404 error: {request.path}")
    return render_template('index.html'), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500 error: {str(e)}")
    return render_template('index.html', error="Internal server error. Please try again later."), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Starting application on port {port}")
    app.run(host='0.0.0.0', port=port) 