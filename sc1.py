import sys
import os
import json
import shutil
import datetime
import threading

# PyQt5 imports for UI components
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QListWidget, QTextEdit, QPushButton, QFileDialog, QLineEdit
)
from PyQt5.QtCore import Qt

# For voice recognition and text-to-speech
import speech_recognition as sr
import pyttsx3

# Import the OpenAI Python library
import openai

# ---------------------------
# ChatBot UI class definition
# ---------------------------
class ChatBotUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rumble")
        self.setGeometry(100, 100, 900, 600)
        
        # Create the central widget and overall layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # -----------------------
        # Top section layout: Knowledge & Response Section
        # -----------------------
        top_layout = QHBoxLayout()
        
        # Knowledge Section (left panel)
        self.knowledge_list = QListWidget()
        knowledge_group = QGroupBox("Knowledge")
        knowledge_layout = QVBoxLayout()
        knowledge_layout.addWidget(self.knowledge_list)
        knowledge_group.setLayout(knowledge_layout)
        top_layout.addWidget(knowledge_group, stretch=1)
        
        # Response Section (right panel)
        self.response_text = QTextEdit()
        self.response_text.setReadOnly(True)
        response_group = QGroupBox("Response")
        response_layout = QVBoxLayout()
        response_layout.addWidget(self.response_text)
        response_group.setLayout(response_layout)
        top_layout.addWidget(response_group, stretch=3)
        
        main_layout.addLayout(top_layout)
        
        # -----------------------
        # Prompt Input Area
        # -----------------------
        prompt_layout = QHBoxLayout()
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Enter your prompt here...")
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_prompt)
        prompt_layout.addWidget(self.prompt_input)
        prompt_layout.addWidget(self.send_button)
        main_layout.addLayout(prompt_layout)
        
        # -----------------------
        # Bottom section: Buttons
        # -----------------------
        button_layout = QHBoxLayout()
        
        self.upload_button = QPushButton("Upload File")
        self.upload_button.clicked.connect(self.upload_file)
        button_layout.addWidget(self.upload_button)
        
        self.instruction_button = QPushButton("Instruction")
        self.instruction_button.clicked.connect(self.upload_instruction)
        button_layout.addWidget(self.instruction_button)
        
        self.restriction_button = QPushButton("Restriction")
        self.restriction_button.clicked.connect(self.upload_restriction)
        button_layout.addWidget(self.restriction_button)
        
        # Settings button to update API key and model
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        button_layout.addWidget(self.settings_button)
        
        # New: Voice Settings button for selecting different voices
        self.voice_settings_button = QPushButton("Voice Settings")
        self.voice_settings_button.clicked.connect(self.open_voice_settings)
        button_layout.addWidget(self.voice_settings_button)
        
        main_layout.addLayout(button_layout)
        
        # -----------------------
        # Load Spark file and Knowledge files
        # -----------------------
        self.load_spark_file()
        self.load_knowledge_files()
        
        # -----------------------
        # Set OpenAI API key and default model
        # -----------------------
        # IMPORTANT: Replace this with your actual API key or update via the Settings dialog.
        openai.api_key = "YOUR_OPENAI_API_KEY_HERE"
        self.default_model = "gpt-4"  # Or "gpt-3.5-turbo", etc.
        
        # -----------------------
        # Initialize text-to-speech engine and greeting
        # -----------------------
        self.tts_engine = pyttsx3.init()
        self.setup_tts()
        self.speak("My name is Rumble, how may I help you")
        self.response_text.append("Rumble: My name is Rumble, how may I help you")
        
        # -----------------------
        # Start voice recognition listener in a separate thread
        # -----------------------
        self.voice_thread = threading.Thread(target=self.voice_listener, daemon=True)
        self.voice_thread.start()
    
    # -----------------------
    # TTS Setup: Configure default voice, rate, and volume for a more natural tone.
    # -----------------------
    def setup_tts(self):
        voices = self.tts_engine.getProperty('voices')
        natural_voice = None
        # Attempt to select a female voice (often perceived as more natural) if available
        for voice in voices:
            if 'female' in voice.name.lower():
                natural_voice = voice
                break
        # If not found, fall back to the first available voice.
        if natural_voice is None and voices:
            natural_voice = voices[0]
        if natural_voice:
            self.tts_engine.setProperty('voice', natural_voice.id)
        # Set a slightly slower rate for clarity
        self.tts_engine.setProperty('rate', 135)
        # Set volume to maximum (range is 0.0 to 1.0)
        self.tts_engine.setProperty('volume', 1.0)
    
    # -----------------------
    # Voice Settings Dialog: Allows the user to select from available voices.
    # -----------------------
    def open_voice_settings(self):
        from PyQt5.QtWidgets import QDialog, QFormLayout, QComboBox, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Voice Settings")
        form_layout = QFormLayout(dialog)
        voice_combo = QComboBox()
        voices = self.tts_engine.getProperty('voices')
        self.voice_dict = {}
        for voice in voices:
            language = voice.languages[0] if voice.languages else "N/A"
            voice_desc = f"{voice.name} ({language})"
            voice_combo.addItem(voice_desc)
            self.voice_dict[voice_desc] = voice.id
        form_layout.addRow("Select Voice:", voice_combo)
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form_layout.addRow(button_box)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        if dialog.exec_() == QDialog.Accepted:
            selected_voice_desc = voice_combo.currentText()
            selected_voice_id = self.voice_dict.get(selected_voice_desc)
            if selected_voice_id:
                self.tts_engine.setProperty('voice', selected_voice_id)
    
    # -----------------------
    # Settings Dialog
    # -----------------------
    def open_settings_dialog(self):
        from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        form_layout = QFormLayout(dialog)
        
        api_key_input = QLineEdit()
        api_key_input.setText(openai.api_key)
        form_layout.addRow("OpenAI API Key:", api_key_input)
        
        model_input = QLineEdit()
        model_input.setText(self.default_model)
        form_layout.addRow("Default Model:", model_input)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form_layout.addRow(button_box)
        
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            new_api_key = api_key_input.text().strip()
            new_model = model_input.text().strip()
            if new_api_key:
                openai.api_key = new_api_key
            if new_model:
                self.default_model = new_model
    
    # -----------------------
    # Spark file management
    # -----------------------
    def load_spark_file(self):
        """Loads the spark file that tracks bot details and actions."""
        if not os.path.exists("spark.json"):
            spark_data = {
                "creator": ["Salah Mokhayesh", "Asher Mokhayesh"],
                "creation_date": "02-07-25",
                "version": "1.0",
                "capabilities": "all",
                "actions": []
            }
            with open("spark.json", "w") as f:
                json.dump(spark_data, f, indent=4)
            self.spark_data = spark_data
        else:
            with open("spark.json", "r") as f:
                self.spark_data = json.load(f)

    def save_spark_file(self):
        """Saves the current spark data to the JSON file."""
        with open("spark.json", "w") as f:
            json.dump(self.spark_data, f, indent=4)

    def log_action(self, action, result=""):
        """Logs an action and its result (if any) to the spark file."""
        entry = {
            "action": action,
            "result": result,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.spark_data["actions"].append(entry)
        self.save_spark_file()
    
    # -----------------------
    # Button handlers
    # -----------------------
    def send_prompt(self):
        """Handles sending a prompt typed into the prompt input area."""
        prompt = self.prompt_input.text().strip()
        if prompt:
            self.response_text.append(f"User: {prompt}")
            self.process_command(prompt)
            self.prompt_input.clear()

    def upload_file(self):
        """Handles file upload and stores it in the knowledge directory."""
        filename, _ = QFileDialog.getOpenFileName(self, "Select File")
        if filename:
            base = os.path.basename(filename)
            dest = os.path.join("knowledge", base)
            try:
                shutil.copy(filename, dest)
                self.log_action(f"Uploaded file: {base}")
                self.load_knowledge_files()
                self.response_text.append(f"Uploaded file: {base}")
            except Exception as e:
                self.response_text.append(f"Error uploading file: {str(e)}")

    def upload_instruction(self):
        """Handles uploading instruction files with the correct prefix."""
        filename, _ = QFileDialog.getOpenFileName(self, "Select Instruction File")
        if filename:
            base = os.path.basename(filename)
            if not base.startswith("instruction_"):
                base = "instruction_" + base
            dest = os.path.join("knowledge", base)
            try:
                shutil.copy(filename, dest)
                self.log_action(f"Uploaded instruction file: {base}")
                self.load_knowledge_files()
                self.response_text.append(f"Uploaded instruction file: {base}")
            except Exception as e:
                self.response_text.append(f"Error uploading instruction file: {str(e)}")

    def upload_restriction(self):
        """Handles uploading restriction files."""
        filename, _ = QFileDialog.getOpenFileName(self, "Select Restriction File")
        if filename:
            base = os.path.basename(filename)
            dest = os.path.join("knowledge", base)
            try:
                shutil.copy(filename, dest)
                self.log_action(f"Uploaded restriction file: {base}")
                self.load_knowledge_files()
                self.response_text.append(f"Uploaded restriction file: {base}")
            except Exception as e:
                self.response_text.append(f"Error uploading restriction file: {str(e)}")
    
    # -----------------------
    # Load knowledge files into the list widget
    # -----------------------
    def load_knowledge_files(self):
        """Lists all files from the 'knowledge' directory into the UI."""
        knowledge_dir = "knowledge"
        if not os.path.exists(knowledge_dir):
            os.makedirs(knowledge_dir)
        self.knowledge_list.clear()
        for file in os.listdir(knowledge_dir):
            self.knowledge_list.addItem(file)
    
    # -----------------------
    # Process command using OpenAI's ChatCompletion
    # -----------------------
    def process_command(self, command):
        """
        Sends the user's command to the OpenAI API and displays the response.
        The system prompt instructs the AI to respond naturally, warmly, and engagingly.
        """
        try:
            response = openai.ChatCompletion.create(
                model=self.default_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an advanced AI assistant named Rumble. "
                            "Speak naturally with warmth, empathy, and clarity. "
                            "Ensure your responses are engaging and conversational."
                        )
                    },
                    {"role": "user", "content": command}
                ]
            )
            reply = response["choices"][0]["message"]["content"]
            self.response_text.append(f"Rumble: {reply}")
            self.speak(reply)
            self.log_action(f"Processed command: {command}", reply)
        except Exception as e:
            error_msg = f"Error processing command: {str(e)}"
            self.response_text.append(error_msg)
            self.log_action(f"Error processing command: {command}", str(e))

    # -----------------------
    # Text-to-speech function with safe encoding for latin-1
    # -----------------------
    def speak(self, text):
        """
        Uses pyttsx3 to speak the given text.
        Any characters that cannot be encoded in latin-1 are replaced.
        """
        safe_text = text.encode('latin-1', 'replace').decode('latin-1')
        self.tts_engine.say(safe_text)
        self.tts_engine.runAndWait()

    # -----------------------
    # Voice recognition listener
    # -----------------------
    def voice_listener(self):
        """
        Continuously listens for the activation phrase ("hey rumble") and then for a user command.
        Adjusts for ambient noise and uses improved thresholds to enhance recognition.
        """
        recognizer = sr.Recognizer()
        mic = sr.Microphone()
        # Adjust for ambient noise initially.
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
        # Fine-tune recognition parameters.
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        
        while True:
            try:
                with mic as source:
                    audio = recognizer.listen(source, phrase_time_limit=5)
                # Recognize and normalize the audio
                command = recognizer.recognize_google(audio).lower().strip()
                # Check if the command starts with the activation phrase
                if command.startswith("hey rumble"):
                    self.response_text.append("Activation phrase detected. Listening for command...")
                    self.speak("Yes?")
                    with mic as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        audio = recognizer.listen(source, phrase_time_limit=5)
                    user_command = recognizer.recognize_google(audio)
                    self.response_text.append(f"You said: {user_command}")
                    self.process_command(user_command)
            except sr.UnknownValueError:
                # Could not understand the audio; continue listening
                continue
            except sr.RequestError as e:
                print(f"Could not request results from Google Speech Recognition service; {e}")
            except Exception as e:
                print(f"Voice listener error: {e}")

# ---------------------------
# Main entry point
# ---------------------------
def main():
    app = QApplication(sys.argv)
    window = ChatBotUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()