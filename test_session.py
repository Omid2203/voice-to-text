"""
Test Flask-Session to verify it works correctly
"""
import os
from flask import Flask, session
from flask_session import Session

# Create a test Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'test_key'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = 'flask_session'

# Create session directory if it doesn't exist
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Initialize Flask-Session
Session(app)

# Test session functionality
with app.test_request_context():
    session['test'] = 'This is a test'
    print(f"Session value set: {session.get('test')}")
    print("Flask-Session is working correctly!")

print("Flask-Session test completed successfully.") 