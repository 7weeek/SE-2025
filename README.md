# 📚 Exam Proctoring System

A web-based online examination platform with real-time AI-powered proctoring capabilities. The system ensures academic integrity by monitoring students during exams using face recognition, head pose detection, and audio monitoring.

## ✨ Key Features

- **User Authentication** - JWT-based secure login/registration with face recognition
- **Identity Verification** - Face matching system to verify student identity
- **Real-time Proctoring** - Continuous monitoring during exams
  - Face detection and tracking
  - Head pose detection (left/right movement)
  - Multiple person detection
  - Voice/audio monitoring
- **Exam Management** - 30+ domain-specific exams across 6 categories
- **Violation Logging** - Automatic detection and logging of suspicious activities
- **Automated Reports** - Detailed exam reports with scores and violation summaries

## 🛠️ Technology Stack

**Backend:**
- Flask 2.2.5 (Python Web Framework)
- SQLite (Database)
- OpenCV (Computer Vision)
- face_recognition (Face Recognition)
- PyJWT (Authentication)

**Frontend:**
- HTML5, CSS3, JavaScript
- WebRTC (Camera/Microphone Access)

**AI Models:**
- YuNet Face Detector (ONNX)
- Caffe DNN (Fallback)
- Haar Cascade (Final Fallback)

## 📋 Prerequisites

- Python 3.8 or higher
- Webcam and microphone (for proctoring)
- Modern web browser with WebRTC support

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/7weeek/SE-2025
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Download face detection model** (Optional - system will use fallback if not available)
   - Place `face_detection_yunet_2023mar.onnx` in `models/` directory
   - Install Dlib (Refer https://github.com/7weeek/Dlib-installer)

4. **Run the application**
   ```bash
   python next.py
   ```

5. **Access the application**
   - Open browser and navigate to `http://localhost:5000`

## 📖 Usage

### For Students

1. **Register** - Create account with photo upload
2. **Login** - Authenticate with email and password
3. **Verify Identity** - Capture photo for face verification
4. **Select Exam** - Choose from available exams (filter by domain)
5. **Take Exam** - Answer questions while being monitored
6. **View Report** - Check scores and violation logs after submission

### For Administrators

- Monitor exam sessions
- View violation logs
- Access detailed reports
- Manage exam configurations

## 🗂️ Project Structure

```
Camera/
├── next.py                 # Main Flask application
├── app.py                  # Proctoring-only Flask app
├── requirements.txt        # Python dependencies
├── users.db               # SQLite database
├── models/                # AI/ML models
├── templates/             # HTML templates
├── static/                # Static files (CSS, JS, HTML)
│   ├── CSS/              # Stylesheets
│   ├── JS/               # JavaScript files
│   └── uploads/          # User photos
├── uploads/              # Photo storage
└── encodings/            # Face encoding files
```

## 🔌 Key API Endpoints

**Authentication:**
- `POST /api/register` - User registration
- `POST /api/login` - User login
- `POST /api/verify` - Face verification

**Exams:**
- `GET /api/tests` - List available exams
- `GET /api/exam/<id>/questions` - Get exam questions
- `POST /api/session/start` - Start exam session
- `POST /api/session/end` - Submit exam and generate report

**Proctoring:**
- `POST /analyze_frame` - Analyze video frame for violations
- `POST /voice_event` - Log voice detection events

**Reports:**
- `GET /api/report/<session_id>` - Get exam report
- `GET /api/report/<session_id>/download` - Download report

## 🎯 Proctoring Features

The system monitors the following during exams:

- **Face Detection** - Ensures student is present in frame
- **Head Pose** - Detects if student looks away (left/right)
- **Multiple Persons** - Alerts if more than one person detected
- **Voice Detection** - Monitors audio for unauthorized communication
- **Violation Logging** - All violations are logged with timestamps and severity levels

## 📊 Exam Domains

The system includes 30+ exams across 6 domains:
- Programming (Python, Java, JavaScript, C++)
- Data Science (ML, Deep Learning, Big Data)
- Web Development (HTML/CSS, React, Node.js)
- Database (SQL, NoSQL, Database Design)
- Operating Systems (OS Basics, Linux)
- Software Engineering (OOP, Design Patterns, Testing)

## 🔒 Security Features

- JWT-based authentication
- Password hashing (bcrypt)
- Secure file upload validation
- Face encoding encryption
- Session-based authorization
- SQL injection prevention

## ⚙️ Configuration

Set environment variables for production:
```bash
export JWT_SECRET="your-secret-key"
export JWT_EXP_DAYS=7
```

## 📝 Notes

- First-time users must register with a clear face photo
- Use the same device/camera for registration and exam
- Ensure good lighting and clear face visibility
- System requires camera and microphone permissions

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is for educational purposes.

---

**Note:** This system is designed for academic use. Ensure compliance with privacy regulations in your region before deployment.

