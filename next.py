# app.py
import os
import sqlite3
import pickle
import json
import base64
import io
import threading
from pathlib import Path
from datetime import datetime, timedelta
from PIL import Image

from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import jwt
import face_recognition
import numpy as np
import cv2

# ----------------- CONFIG -----------------
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
ENC_DIR = BASE_DIR / "encodings"
DB_PATH = BASE_DIR / "users.db"

# create dirs
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ENC_DIR.mkdir(parents=True, exist_ok=True)

# JWT config - prefer env var in production
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    # generate ephemeral secret for local dev if not provided
    import secrets
    JWT_SECRET = secrets.token_hex(32)
    print("WARNING: JWT_SECRET not set in environment. Using a generated ephemeral secret (tokens will be invalid after restart).")
JWT_ALGORITHM = "HS256"
JWT_EXP_DAYS = int(os.environ.get("JWT_EXP_DAYS", "7"))

ALLOWED_EXT = {"png", "jpg", "jpeg"}
MAX_PHOTO_BYTES = 4 * 1024 * 1024  # 4MB

app = Flask(__name__, static_folder="static", static_url_path="/static")

# ----------------- DATABASE -----------------
def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    
    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE,
        full_name TEXT,
        student_id TEXT,
        email TEXT UNIQUE,
        phone TEXT,
        course TEXT,
        role TEXT,
        password_hash TEXT,
        photo_path TEXT,
        encoding_path TEXT,
        notes TEXT,
        created_at TEXT
    );
    """)
    
    # Exams table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_title TEXT NOT NULL,
        description TEXT,
        domain TEXT,
        difficulty TEXT,
        duration INTEGER DEFAULT 60,
        total_questions INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    );
    """)
    
    # Exam Questions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_questions (
        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        options TEXT NOT NULL,
        correct_answer INTEGER NOT NULL,
        question_order INTEGER DEFAULT 0,
        FOREIGN KEY (exam_id) REFERENCES exams(exam_id) ON DELETE CASCADE
    );
    """)
    
    # Sessions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        exam_id INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
    );
    """)
    
    # Reports table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        exam_id INTEGER NOT NULL,
        total_questions INTEGER DEFAULT 0,
        correct_answers INTEGER DEFAULT 0,
        marks REAL DEFAULT 0.0,
        percentage REAL DEFAULT 0.0,
        submitted_at TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (exam_id) REFERENCES exams(exam_id)
    );
    """)
    
    # Violation Logs table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS violation_logs (
        violation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        violation_type TEXT NOT NULL,
        violation_details TEXT,
        timestamp TEXT NOT NULL,
        severity TEXT DEFAULT 'medium',
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()

init_db()

# ----------------- POPULATE INITIAL EXAM DATA -----------------
def get_domain_questions():
    """Returns domain-specific questions for each exam"""
    return {
        # Programming Domain
        1: [  # Python Basics
            {"question": "What is the output of: print(type([]))", "options": ["<class 'list'>", "<class 'array'>", "<class 'tuple'>", "<class 'dict'>"], "answer": 0},
            {"question": "Which keyword is used to define a function in Python?", "options": ["def", "function", "define", "func"], "answer": 0},
            {"question": "What does len() function return for an empty list?", "options": ["0", "1", "None", "Error"], "answer": 0},
            {"question": "Which operator is used for exponentiation in Python?", "options": ["^", "**", "exp", "pow"], "answer": 1},
            {"question": "What is the correct way to create a dictionary?", "options": ["dict = {key: value}", "dict = [key, value]", "dict = (key, value)", "dict = key:value"], "answer": 0},
        ],
        2: [  # Python Advanced
            {"question": "What is a decorator in Python?", "options": ["A function that modifies another function", "A class method", "A built-in function", "A data type"], "answer": 0},
            {"question": "What does 'yield' keyword do in Python?", "options": ["Returns a value and pauses execution", "Stops the function", "Raises an exception", "Imports a module"], "answer": 0},
            {"question": "What is the purpose of __init__ method?", "options": ["Initialize object attributes", "Delete an object", "Import modules", "Handle errors"], "answer": 0},
            {"question": "What is a generator in Python?", "options": ["A function that returns an iterator", "A data structure", "A loop construct", "A class"], "answer": 0},
            {"question": "What does @staticmethod decorator do?", "options": ["Makes a method callable without instance", "Creates a static variable", "Imports static methods", "Defines a constant"], "answer": 0},
        ],
        3: [  # Java Fundamentals
            {"question": "What is the default value of a boolean variable in Java?", "options": ["true", "false", "null", "0"], "answer": 1},
            {"question": "Which keyword is used to inherit a class in Java?", "options": ["extends", "implements", "inherits", "super"], "answer": 0},
            {"question": "What is the size of int in Java?", "options": ["16 bits", "32 bits", "64 bits", "8 bits"], "answer": 1},
            {"question": "What is an ArrayList in Java?", "options": ["Dynamic array", "Static array", "Linked list", "Hash table"], "answer": 0},
            {"question": "Which method is used to start a thread in Java?", "options": ["start()", "run()", "begin()", "execute()"], "answer": 0},
        ],
        4: [  # JavaScript Essentials
            {"question": "What is the output of: typeof null", "options": ["null", "object", "undefined", "string"], "answer": 1},
            {"question": "What does '===' operator do in JavaScript?", "options": ["Strict equality check", "Assignment", "Type conversion", "Comparison only"], "answer": 0},
            {"question": "What is a closure in JavaScript?", "options": ["Function with access to outer scope", "A loop", "A variable", "A class"], "answer": 0},
            {"question": "What does async/await do?", "options": ["Handle asynchronous operations", "Create loops", "Define variables", "Import modules"], "answer": 0},
            {"question": "What is the arrow function syntax?", "options": ["() => {}", "function() {}", "=> function", "arrow function"], "answer": 0},
        ],
        5: [  # C++ Core Concepts
            {"question": "What is a pointer in C++?", "options": ["Variable that stores memory address", "A data type", "A function", "A class"], "answer": 0},
            {"question": "What does 'new' keyword do in C++?", "options": ["Allocates memory dynamically", "Creates a variable", "Imports library", "Defines class"], "answer": 0},
            {"question": "What is STL in C++?", "options": ["Standard Template Library", "Simple Type Library", "System Type Library", "Standard Type List"], "answer": 0},
            {"question": "What is the purpose of destructor in C++?", "options": ["Clean up resources", "Initialize object", "Create object", "Copy object"], "answer": 0},
            {"question": "What is a reference in C++?", "options": ["Alias for a variable", "Pointer", "Function", "Class"], "answer": 0},
        ],
        # Data Science Domain
        6: [  # Data Science Fundamentals
            {"question": "What is the mean of [1, 2, 3, 4, 5]?", "options": ["3", "2.5", "4", "5"], "answer": 0},
            {"question": "What is standard deviation used for?", "options": ["Measure data spread", "Find mean", "Count values", "Sort data"], "answer": 0},
            {"question": "What is EDA?", "options": ["Exploratory Data Analysis", "Error Data Analysis", "Extended Data Analysis", "Efficient Data Analysis"], "answer": 0},
            {"question": "What is correlation coefficient range?", "options": ["-1 to 1", "0 to 1", "-1 to 0", "0 to 100"], "answer": 0},
            {"question": "What is a p-value used for?", "options": ["Statistical significance", "Data cleaning", "Visualization", "Data storage"], "answer": 0},
        ],
        7: [  # Machine Learning Basics
            {"question": "What is supervised learning?", "options": ["Learning with labeled data", "Learning without data", "Unsupervised learning", "Reinforcement learning"], "answer": 0},
            {"question": "What is overfitting?", "options": ["Model performs well on training but poorly on test", "Model too simple", "Model not trained", "Model too fast"], "answer": 0},
            {"question": "What is cross-validation used for?", "options": ["Evaluate model performance", "Train model", "Test data", "Clean data"], "answer": 0},
            {"question": "What is a decision tree?", "options": ["Tree-based classification model", "Data structure", "Algorithm", "Database"], "answer": 0},
            {"question": "What is gradient descent?", "options": ["Optimization algorithm", "Data cleaning", "Visualization", "Feature selection"], "answer": 0},
        ],
        8: [  # Deep Learning
            {"question": "What is a neural network?", "options": ["Network of interconnected neurons", "Database", "Algorithm", "Data structure"], "answer": 0},
            {"question": "What is CNN used for?", "options": ["Image processing", "Text processing", "Audio processing", "Video processing"], "answer": 0},
            {"question": "What is backpropagation?", "options": ["Training algorithm for neural networks", "Data cleaning", "Feature extraction", "Model evaluation"], "answer": 0},
            {"question": "What is an activation function?", "options": ["Non-linear function in neurons", "Linear function", "Constant", "Variable"], "answer": 0},
            {"question": "What is RNN used for?", "options": ["Sequence data", "Image data", "Tabular data", "Graph data"], "answer": 0},
        ],
        9: [  # Data Visualization
            {"question": "What is Matplotlib?", "options": ["Python plotting library", "Database", "Algorithm", "Framework"], "answer": 0},
            {"question": "What is Seaborn built on?", "options": ["Matplotlib", "Pandas", "NumPy", "Scikit-learn"], "answer": 0},
            {"question": "What is a histogram used for?", "options": ["Show distribution", "Show trends", "Compare categories", "Show relationships"], "answer": 0},
            {"question": "What is Plotly?", "options": ["Interactive visualization library", "Database", "Algorithm", "Framework"], "answer": 0},
            {"question": "What is a scatter plot used for?", "options": ["Show relationship between variables", "Show distribution", "Show trends", "Compare categories"], "answer": 0},
        ],
        10: [  # Big Data Analytics
            {"question": "What is Hadoop?", "options": ["Big data processing framework", "Database", "Language", "Algorithm"], "answer": 0},
            {"question": "What is Spark?", "options": ["In-memory processing engine", "Database", "Language", "Framework"], "answer": 0},
            {"question": "What is MapReduce?", "options": ["Programming model for processing", "Database", "Algorithm", "Framework"], "answer": 0},
            {"question": "What is HDFS?", "options": ["Hadoop Distributed File System", "Database", "Algorithm", "Language"], "answer": 0},
            {"question": "What is Kafka used for?", "options": ["Stream processing", "Database", "Visualization", "Machine learning"], "answer": 0},
        ],
        # Web Development Domain
        11: [  # HTML & CSS Basics
            {"question": "What does HTML stand for?", "options": ["HyperText Markup Language", "High Text Markup Language", "Hyperlink Text Markup", "Home Tool Markup Language"], "answer": 0},
            {"question": "What is CSS used for?", "options": ["Styling web pages", "Programming logic", "Database", "Server"], "answer": 0},
            {"question": "What is Flexbox used for?", "options": ["Layout design", "Database", "Programming", "Server"], "answer": 0},
            {"question": "What is CSS Grid?", "options": ["2D layout system", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is the box model in CSS?", "options": ["Content, padding, border, margin", "Database model", "Data model", "Framework"], "answer": 0},
        ],
        12: [  # React.js Fundamentals
            {"question": "What is React?", "options": ["JavaScript library for UI", "Database", "Server", "Language"], "answer": 0},
            {"question": "What is a component in React?", "options": ["Reusable UI piece", "Database", "Function", "Variable"], "answer": 0},
            {"question": "What is useState hook used for?", "options": ["Manage state", "Fetch data", "Style component", "Import module"], "answer": 0},
            {"question": "What is JSX?", "options": ["JavaScript XML syntax", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is props in React?", "options": ["Data passed to components", "Function", "Variable", "Class"], "answer": 0},
        ],
        13: [  # Node.js & Express
            {"question": "What is Node.js?", "options": ["JavaScript runtime", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Express?", "options": ["Web framework for Node.js", "Database", "Language", "Algorithm"], "answer": 0},
            {"question": "What is middleware in Express?", "options": ["Functions that execute during request", "Database", "Route", "Template"], "answer": 0},
            {"question": "What is REST API?", "options": ["Architectural style for APIs", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is async in Node.js?", "options": ["Non-blocking operations", "Blocking operations", "Synchronous", "Sequential"], "answer": 0},
        ],
        14: [  # Full Stack Development
            {"question": "What is MERN stack?", "options": ["MongoDB, Express, React, Node.js", "MySQL, Express, React, Node", "MongoDB, Ember, React, Node", "MySQL, Ember, React, Node"], "answer": 0},
            {"question": "What is JWT used for?", "options": ["Authentication", "Database", "Styling", "Routing"], "answer": 0},
            {"question": "What is CORS?", "options": ["Cross-Origin Resource Sharing", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is deployment?", "options": ["Making app available online", "Development", "Testing", "Designing"], "answer": 0},
            {"question": "What is a full stack developer?", "options": ["Works on frontend and backend", "Only frontend", "Only backend", "Only database"], "answer": 0},
        ],
        15: [  # Web Security
            {"question": "What is XSS?", "options": ["Cross-Site Scripting", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is CSRF?", "options": ["Cross-Site Request Forgery", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is HTTPS?", "options": ["Secure HTTP", "Database", "Framework", "Protocol"], "answer": 0},
            {"question": "What is OWASP?", "options": ["Web security organization", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is SQL injection?", "options": ["Security vulnerability", "Database feature", "Framework", "Language"], "answer": 0},
        ],
        # Database Domain
        16: [  # SQL Fundamentals
            {"question": "What does SQL stand for?", "options": ["Structured Query Language", "Simple Query Language", "Standard Query Language", "System Query Language"], "answer": 0},
            {"question": "What is SELECT used for?", "options": ["Retrieve data", "Insert data", "Delete data", "Update data"], "answer": 0},
            {"question": "What is a JOIN?", "options": ["Combine rows from tables", "Delete rows", "Update rows", "Insert rows"], "answer": 0},
            {"question": "What is WHERE clause used for?", "options": ["Filter rows", "Sort rows", "Group rows", "Join rows"], "answer": 0},
            {"question": "What is GROUP BY used for?", "options": ["Group rows by column", "Sort rows", "Filter rows", "Join rows"], "answer": 0},
        ],
        17: [  # Database Design
            {"question": "What is normalization?", "options": ["Reduce data redundancy", "Increase redundancy", "Delete data", "Update data"], "answer": 0},
            {"question": "What is an ER diagram?", "options": ["Entity-Relationship diagram", "Database", "Table", "Query"], "answer": 0},
            {"question": "What is a primary key?", "options": ["Unique identifier", "Foreign key", "Index", "Constraint"], "answer": 0},
            {"question": "What is indexing used for?", "options": ["Speed up queries", "Store data", "Delete data", "Update data"], "answer": 0},
            {"question": "What is a foreign key?", "options": ["Reference to another table", "Primary key", "Index", "Constraint"], "answer": 0},
        ],
        18: [  # NoSQL Databases
            {"question": "What is MongoDB?", "options": ["NoSQL document database", "SQL database", "Framework", "Language"], "answer": 0},
            {"question": "What is Redis?", "options": ["In-memory data store", "SQL database", "Framework", "Language"], "answer": 0},
            {"question": "What is a document store?", "options": ["NoSQL database type", "SQL database", "Framework", "Language"], "answer": 0},
            {"question": "What is Cassandra?", "options": ["NoSQL database", "SQL database", "Framework", "Language"], "answer": 0},
            {"question": "What is NoSQL?", "options": ["Non-relational database", "SQL database", "Framework", "Language"], "answer": 0},
        ],
        19: [  # Database Administration
            {"question": "What is database backup?", "options": ["Copy of database", "Delete database", "Update database", "Create database"], "answer": 0},
            {"question": "What is recovery?", "options": ["Restore database", "Delete database", "Update database", "Create database"], "answer": 0},
            {"question": "What is performance tuning?", "options": ["Optimize database", "Delete data", "Update data", "Create data"], "answer": 0},
            {"question": "What is a transaction?", "options": ["Unit of work", "Database", "Table", "Query"], "answer": 0},
            {"question": "What is ACID?", "options": ["Transaction properties", "Database", "Framework", "Language"], "answer": 0},
        ],
        # Operating Systems Domain
        20: [  # Operating Systems Basics
            {"question": "What is a process?", "options": ["Program in execution", "File", "Directory", "Command"], "answer": 0},
            {"question": "What is a thread?", "options": ["Lightweight process", "File", "Directory", "Command"], "answer": 0},
            {"question": "What is scheduling?", "options": ["CPU allocation", "Memory allocation", "File management", "Process creation"], "answer": 0},
            {"question": "What is context switching?", "options": ["Switching between processes", "Creating process", "Deleting process", "Updating process"], "answer": 0},
            {"question": "What is multitasking?", "options": ["Multiple processes running", "Single process", "No processes", "Process deletion"], "answer": 0},
        ],
        21: [  # Memory Management
            {"question": "What is virtual memory?", "options": ["Memory abstraction", "Physical memory", "Cache", "Register"], "answer": 0},
            {"question": "What is paging?", "options": ["Memory management technique", "File system", "Process", "Thread"], "answer": 0},
            {"question": "What is segmentation?", "options": ["Memory division", "File division", "Process division", "Thread division"], "answer": 0},
            {"question": "What is swapping?", "options": ["Move process to disk", "Move file", "Create process", "Delete process"], "answer": 0},
            {"question": "What is fragmentation?", "options": ["Memory waste", "File waste", "Process waste", "Thread waste"], "answer": 0},
        ],
        22: [  # Linux Administration
            {"question": "What is ls command used for?", "options": ["List files", "Create file", "Delete file", "Update file"], "answer": 0},
            {"question": "What is chmod used for?", "options": ["Change permissions", "Change directory", "Create file", "Delete file"], "answer": 0},
            {"question": "What is grep used for?", "options": ["Search text", "Create file", "Delete file", "Update file"], "answer": 0},
            {"question": "What is sudo?", "options": ["Superuser do", "Command", "File", "Directory"], "answer": 0},
            {"question": "What is the root directory?", "options": ["Top-level directory", "User directory", "Temp directory", "Home directory"], "answer": 0},
        ],
        # Networking Domain
        23: [  # Computer Networks
            {"question": "What is OSI model?", "options": ["7-layer network model", "Database model", "Data model", "Framework"], "answer": 0},
            {"question": "What is TCP/IP?", "options": ["Network protocol suite", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is HTTP?", "options": ["HyperText Transfer Protocol", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is DNS?", "options": ["Domain Name System", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is IP address?", "options": ["Network identifier", "Database", "Framework", "Language"], "answer": 0},
        ],
        24: [  # Network Security
            {"question": "What is a firewall?", "options": ["Network security device", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is VPN?", "options": ["Virtual Private Network", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is encryption?", "options": ["Data protection", "Data storage", "Data deletion", "Data update"], "answer": 0},
            {"question": "What is SSL/TLS?", "options": ["Security protocol", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is DDoS?", "options": ["Distributed Denial of Service", "Database", "Framework", "Language"], "answer": 0},
        ],
        # Software Engineering Domain
        25: [  # OOP Concepts
            {"question": "What is inheritance?", "options": ["Reuse code from parent class", "Create class", "Delete class", "Update class"], "answer": 0},
            {"question": "What is polymorphism?", "options": ["Multiple forms", "Single form", "No form", "Fixed form"], "answer": 0},
            {"question": "What is encapsulation?", "options": ["Data hiding", "Data showing", "Data deleting", "Data updating"], "answer": 0},
            {"question": "What is abstraction?", "options": ["Hide implementation details", "Show details", "Delete details", "Update details"], "answer": 0},
            {"question": "What is a class?", "options": ["Blueprint for objects", "Object", "Function", "Variable"], "answer": 0},
        ],
        26: [  # Design Patterns
            {"question": "What is Singleton pattern?", "options": ["Single instance", "Multiple instances", "No instances", "Fixed instances"], "answer": 0},
            {"question": "What is Factory pattern?", "options": ["Create objects", "Delete objects", "Update objects", "Store objects"], "answer": 0},
            {"question": "What is Observer pattern?", "options": ["Notify changes", "Hide changes", "Delete changes", "Update changes"], "answer": 0},
            {"question": "What is MVC pattern?", "options": ["Model-View-Controller", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is a design pattern?", "options": ["Reusable solution", "Problem", "Solution", "Framework"], "answer": 0},
        ],
        27: [  # Software Testing
            {"question": "What is unit testing?", "options": ["Test individual components", "Test entire system", "Test database", "Test UI"], "answer": 0},
            {"question": "What is integration testing?", "options": ["Test components together", "Test individually", "Test database", "Test UI"], "answer": 0},
            {"question": "What is TDD?", "options": ["Test-Driven Development", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is regression testing?", "options": ["Test after changes", "Test before changes", "Test database", "Test UI"], "answer": 0},
            {"question": "What is a test case?", "options": ["Test scenario", "Test data", "Test result", "Test framework"], "answer": 0},
        ],
        28: [  # Agile Methodologies
            {"question": "What is Scrum?", "options": ["Agile framework", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is a sprint?", "options": ["Time-boxed iteration", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Kanban?", "options": ["Visual workflow", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is a user story?", "options": ["Feature description", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Agile?", "options": ["Iterative development", "Waterfall", "Database", "Framework"], "answer": 0},
        ],
        # Cloud Computing Domain
        29: [  # Cloud Fundamentals
            {"question": "What is AWS?", "options": ["Amazon Web Services", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Azure?", "options": ["Microsoft cloud platform", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is IaaS?", "options": ["Infrastructure as a Service", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is PaaS?", "options": ["Platform as a Service", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is SaaS?", "options": ["Software as a Service", "Database", "Framework", "Language"], "answer": 0},
        ],
        30: [  # DevOps & CI/CD
            {"question": "What is Docker?", "options": ["Containerization platform", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Kubernetes?", "options": ["Container orchestration", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is CI/CD?", "options": ["Continuous Integration/Deployment", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is Jenkins?", "options": ["CI/CD tool", "Database", "Framework", "Language"], "answer": 0},
            {"question": "What is DevOps?", "options": ["Development and Operations", "Database", "Framework", "Language"], "answer": 0},
        ],
    }

def populate_initial_exams():
    """Populate exams and questions from domain-specific questions"""
    
    conn = get_db_conn()
    cur = conn.cursor()
    
    # Check if exams already exist
    cur.execute("SELECT COUNT(*) as count FROM exams")
    count = cur.fetchone()["count"]
    
    # If exams exist, clear existing questions to repopulate with domain-specific ones
    if count > 0:
        print("Exams already exist. Clearing existing questions to repopulate with domain-specific questions...")
        # Delete all existing questions
        cur.execute("DELETE FROM exam_questions")
        # Update exam total_questions to 0 temporarily
        cur.execute("UPDATE exams SET total_questions = 0")
        conn.commit()
    
    # Define exams based on the existing test structure
    exams_data = [
        {"id": 1, "title": "Python Basics", "description": "20 MCQs — Variables, Data Types, Operators", "domain": "Programming", "difficulty": "Beginner"},
        {"id": 2, "title": "Python Advanced", "description": "25 MCQs — Decorators, Generators, Context Managers", "domain": "Programming", "difficulty": "Advanced"},
        {"id": 3, "title": "Java Fundamentals", "description": "22 MCQs — OOP, Collections, Exception Handling", "domain": "Programming", "difficulty": "Intermediate"},
        {"id": 4, "title": "JavaScript Essentials", "description": "24 MCQs — ES6+, Async/Await, Closures", "domain": "Programming", "difficulty": "Intermediate"},
        {"id": 5, "title": "C++ Core Concepts", "description": "26 MCQs — Pointers, Memory Management, STL", "domain": "Programming", "difficulty": "Advanced"},
        {"id": 6, "title": "Data Science Fundamentals", "description": "25 MCQs — Statistics, Probability, EDA", "domain": "Data Science", "difficulty": "Beginner"},
        {"id": 7, "title": "Machine Learning Basics", "description": "28 MCQs — Supervised Learning, Algorithms", "domain": "Data Science", "difficulty": "Intermediate"},
        {"id": 8, "title": "Deep Learning", "description": "30 MCQs — Neural Networks, CNN, RNN", "domain": "Data Science", "difficulty": "Advanced"},
        {"id": 9, "title": "Data Visualization", "description": "22 MCQs — Matplotlib, Seaborn, Plotly", "domain": "Data Science", "difficulty": "Intermediate"},
        {"id": 10, "title": "Big Data Analytics", "description": "27 MCQs — Hadoop, Spark, Data Processing", "domain": "Data Science", "difficulty": "Advanced"},
        {"id": 11, "title": "HTML & CSS Basics", "description": "20 MCQs — Layout, Flexbox, Grid", "domain": "Web Development", "difficulty": "Beginner"},
        {"id": 12, "title": "React.js Fundamentals", "description": "26 MCQs — Components, Hooks, State Management", "domain": "Web Development", "difficulty": "Intermediate"},
        {"id": 13, "title": "Node.js & Express", "description": "24 MCQs — REST APIs, Middleware, Async", "domain": "Web Development", "difficulty": "Intermediate"},
        {"id": 14, "title": "Full Stack Development", "description": "28 MCQs — MERN Stack, Authentication, Deployment", "domain": "Web Development", "difficulty": "Advanced"},
        {"id": 15, "title": "Web Security", "description": "25 MCQs — XSS, CSRF, OWASP, HTTPS", "domain": "Web Development", "difficulty": "Advanced"},
        {"id": 16, "title": "SQL Fundamentals", "description": "23 MCQs — Queries, Joins, Subqueries", "domain": "Database", "difficulty": "Beginner"},
        {"id": 17, "title": "Database Design", "description": "26 MCQs — Normalization, ER Diagrams, Indexing", "domain": "Database", "difficulty": "Intermediate"},
        {"id": 18, "title": "NoSQL Databases", "description": "24 MCQs — MongoDB, Redis, Document Stores", "domain": "Database", "difficulty": "Intermediate"},
        {"id": 19, "title": "Database Administration", "description": "27 MCQs — Backup, Recovery, Performance Tuning", "domain": "Database", "difficulty": "Advanced"},
        {"id": 20, "title": "Operating Systems Basics", "description": "25 MCQs — Processes, Threads, Scheduling", "domain": "Operating Systems", "difficulty": "Beginner"},
        {"id": 21, "title": "Memory Management", "description": "28 MCQs — Virtual Memory, Paging, Segmentation", "domain": "Operating Systems", "difficulty": "Advanced"},
        {"id": 22, "title": "Linux Administration", "description": "26 MCQs — Commands, File System, Permissions", "domain": "Operating Systems", "difficulty": "Intermediate"},
        {"id": 23, "title": "Computer Networks", "description": "27 MCQs — OSI Model, TCP/IP, Protocols", "domain": "Networking", "difficulty": "Intermediate"},
        {"id": 24, "title": "Network Security", "description": "25 MCQs — Firewalls, VPN, Encryption", "domain": "Networking", "difficulty": "Advanced"},
        {"id": 25, "title": "OOP Concepts", "description": "24 MCQs — Inheritance, Polymorphism, Encapsulation", "domain": "Software Engineering", "difficulty": "Intermediate"},
        {"id": 26, "title": "Design Patterns", "description": "28 MCQs — Creational, Structural, Behavioral", "domain": "Software Engineering", "difficulty": "Advanced"},
        {"id": 27, "title": "Software Testing", "description": "23 MCQs — Unit Testing, Integration, TDD", "domain": "Software Engineering", "difficulty": "Intermediate"},
        {"id": 28, "title": "Agile Methodologies", "description": "22 MCQs — Scrum, Kanban, Sprint Planning", "domain": "Software Engineering", "difficulty": "Intermediate"},
        {"id": 29, "title": "Cloud Fundamentals", "description": "26 MCQs — AWS, Azure, Cloud Services", "domain": "Cloud Computing", "difficulty": "Intermediate"},
        {"id": 30, "title": "DevOps & CI/CD", "description": "27 MCQs — Docker, Kubernetes, Jenkins", "domain": "Cloud Computing", "difficulty": "Advanced"},
    ]
    
    # Get domain-specific questions
    domain_questions = get_domain_questions()
    
    created_at = datetime.utcnow().isoformat() + "Z"
    
    # Insert or update exams and their questions
    for exam in exams_data:
        exam_id = exam["id"]
        questions = domain_questions.get(exam_id, [])
        
        # Check if exam exists
        cur.execute("SELECT exam_id FROM exams WHERE exam_id = ?", (exam_id,))
        exam_exists = cur.fetchone()
        
        if exam_exists:
            # Update existing exam
            cur.execute("""
                UPDATE exams 
                SET exam_title = ?, description = ?, domain = ?, difficulty = ?, 
                    duration = ?, total_questions = ?, is_active = ?
                WHERE exam_id = ?
            """, (
                exam["title"],
                exam["description"],
                exam["domain"],
                exam["difficulty"],
                60,  # Default duration in minutes
                len(questions),
                1,
                exam_id
            ))
        else:
            # Insert new exam
            cur.execute("""
                INSERT INTO exams (exam_id, exam_title, description, domain, difficulty, duration, total_questions, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exam_id,
                exam["title"],
                exam["description"],
                exam["domain"],
                exam["difficulty"],
                60,  # Default duration in minutes
                len(questions),
                1,
                created_at
            ))
        
        # Insert questions for this exam
        for idx, q in enumerate(questions):
            options_json = json.dumps(q.get("options", []))
            cur.execute("""
                INSERT INTO exam_questions (exam_id, question, options, correct_answer, question_order)
                VALUES (?, ?, ?, ?, ?)
            """, (
                exam_id,
                q.get("question", ""),
                options_json,
                q.get("answer", 0),
                idx
            ))
    
    conn.commit()
    conn.close()
    print("Initial exam data populated successfully with domain-specific questions!")

# Populate on startup
populate_initial_exams()

# ----------------- PROCTORING MONITORING FUNCTIONS (from app.py) -----------------
# Configuration for proctoring
YUNET_PATH = BASE_DIR / "models" / "face_detection_yunet_2023mar.onnx"
CAFFE_PROTO = BASE_DIR / "models" / "deploy.prototxt"
CAFFE_MODEL = BASE_DIR / "models" / "res10_300x300_ssd_iter_140000.caffemodel"

# Proctoring state
proctoring_state = {
    "head_pose_threshold": 0.25,
    "head_pose_alert_duration": 3.0,
    "voice_threshold": 0.08,
    "voice_alert_duration": 2.0,
    "multiple_persons_threshold": 1,
    "min_face_size": 80,
    "confidence_threshold": 0.6
}

# Detector placeholders
detector_yunet = None
net_caffe = None
face_cascade = None

def init_detectors():
    """Initialize face detection models"""
    global detector_yunet, net_caffe, face_cascade
    try:
        if YUNET_PATH.exists():
            detector_yunet = cv2.FaceDetectorYN.create(
                str(YUNET_PATH), "", (0, 0), 0.9, 0.3, 5000
            )
            print("YuNet loaded.")
        elif CAFFE_PROTO.exists() and CAFFE_MODEL.exists():
            net_caffe = cv2.dnn.readNetFromCaffe(str(CAFFE_PROTO), str(CAFFE_MODEL))
            print("Caffe DNN loaded.")
        else:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            print("Using Haar cascade fallback.")
    except Exception as e:
        print("Detector init error:", e)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

init_detectors()

def b64_to_image(base64_data):
    """Convert base64 string to OpenCV image"""
    header, encoded = base64_data.split(",", 1) if "," in base64_data else (None, base64_data)
    binary = base64.b64decode(encoded)
    image = Image.open(io.BytesIO(binary)).convert("RGB")
    return np.array(image)[:, :, ::-1]  # PIL RGB -> OpenCV BGR

def detect_faces_stable(frame):
    """Detect faces using YuNet, Caffe, or Haar cascade"""
    h, w = frame.shape[:2]
    faces = []
    landmarks = None

    # YuNet detector
    if detector_yunet is not None:
        try:
            detector_yunet.setInputSize((w, h))
            result = detector_yunet.detect(frame)
            detections = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
            if detections is not None and len(detections) > 0:
                for d in detections:
                    x, y, ww, hh = map(int, d[:4])
                    if ww >= max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)) and hh >= max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)):
                        faces.append((x, y, ww, hh))
                if detections.shape[1] >= 14:
                    try:
                        landmark_data = detections[0][4:14].reshape(5, 2)
                        landmarks = landmark_data.tolist()
                    except Exception:
                        landmarks = None
            return faces, landmarks
        except Exception as e:
            print("YuNet error:", e)

    # Caffe SSD fallback
    if net_caffe is not None:
        try:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 1.0,
                                         (300, 300), (104.0, 177.0, 123.0))
            net_caffe.setInput(blob)
            detections = net_caffe.forward()
            for i in range(0, detections.shape[2]):
                confidence = float(detections[0, 0, i, 2])
                if confidence > proctoring_state.get("confidence_threshold", 0.5):
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")
                    x = max(0, startX)
                    y = max(0, startY)
                    ww = max(0, endX - startX)
                    hh = max(0, endY - startY)
                    if ww >= max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)) and hh >= max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)):
                        faces.append((int(x), int(y), int(ww), int(hh)))
            return faces, None
        except Exception as e:
            print("Caffe error:", e)

    # Haar Cascade fallback
    if face_cascade is not None:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            haar_faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)), max(24, int(proctoring_state.get("min_face_size", 40) * 0.5)))
            )
            for (x, y, ww, hh) in haar_faces:
                faces.append((int(x), int(y), int(ww), int(hh)))
            return faces, None
        except Exception as e:
            print("Haar error:", e)

    return [], None

def estimate_head_pose_simple(landmarks, face_rect):
    """Estimate head pose from facial landmarks"""
    if landmarks is None or len(landmarks) < 3:
        return 0.0, "Center", 0.0
    try:
        x, y, w, h = face_rect
        right_eye = landmarks[0]
        left_eye = landmarks[1]
        nose = landmarks[2]
        face_center_x = x + w/2
        nose_offset = (nose[0] - face_center_x) / (w/2)
        eye_center_x = (right_eye[0] + left_eye[0])/2
        eye_offset = (eye_center_x - face_center_x) / (w/2)
        combined = (nose_offset + eye_offset) / 2
        if combined < -proctoring_state["head_pose_threshold"]:
            direction = "Right"
            severity = abs(combined)
        elif combined > proctoring_state["head_pose_threshold"]:
            direction = "Left"
            severity = abs(combined)
        else:
            direction = "Center"
            severity = 0.0
        return combined*100, direction, severity
    except Exception as e:
        return 0.0, "Center", 0.0

def log_violation(session_id, violation_type, violation_details, severity="medium"):
    """Log violation to database"""
    conn = get_db_conn()
    cur = conn.cursor()
    timestamp = datetime.utcnow().isoformat() + "Z"
    try:
        cur.execute("""
            INSERT INTO violation_logs (session_id, violation_type, violation_details, timestamp, severity)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, violation_type, violation_details, timestamp, severity))
        conn.commit()
    except Exception as e:
        print(f"Error logging violation: {e}")
    finally:
        conn.close()

# ----------------- HELPERS -----------------
def allowed_filename(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXT

def save_photo_file(file_storage, user_id):
    filename = secure_filename(file_storage.filename or f"{user_id}.jpg")
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else "jpg"
    out_name = f"{user_id}.{ext}"
    out_path = UPLOAD_DIR / out_name
    file_storage.save(out_path)
    return str(out_path)

def compute_and_save_encoding(image_path, user_id):
    # loads image from path and computes face encoding using face_recognition
    try:
        img = face_recognition.load_image_file(str(image_path))
        boxes = face_recognition.face_locations(img, model="hog")
        if len(boxes) == 0:
            return None, "no-face"
        if len(boxes) > 1:
            return None, "multiple-faces"
        encs = face_recognition.face_encodings(img, boxes)
        if len(encs) == 0:
            return None, "encoding-failed"
        encoding = encs[0]
        out_path = ENC_DIR / f"{user_id}.pkl"
        with open(out_path, "wb") as f:
            pickle.dump({"user_id": user_id, "encoding": encoding, "timestamp": datetime.utcnow().isoformat() + "Z"}, f)
        return str(out_path), None
    except Exception as e:
        return None, f"exception:{e}"

def make_jwt(payload: dict):
    exp = datetime.utcnow() + timedelta(days=JWT_EXP_DAYS)
    payload_copy = dict(payload)
    payload_copy["exp"] = exp
    token = jwt.encode(payload_copy, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # PyJWT may return bytes in older versions; ensure str
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def decode_jwt(token):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

# ----------------- AUTH HELPERS -----------------
def get_user_id_from_auth_header():
    auth = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
    if not auth or not auth.startswith("Bearer "):
        return None, "Missing or invalid Authorization header"
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except Exception as e:
        return None, "Invalid token: " + str(e)
    user_id = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    if not user_id:
        return None, "Token missing subject (sub)"
    return user_id, None

# ----------------- STATIC PAGE ROUTES -----------------
@app.route("/")
def index():
    return send_file(STATIC_DIR / "login.html")

@app.route("/register.html")
def register_html():
    return send_file(STATIC_DIR / "register.html")

@app.route("/login.html")
def login_html():
    return send_file(STATIC_DIR / "login.html")

@app.route("/home.html")
def home_html():
    return send_file(STATIC_DIR / "home.html")

@app.route("/verify.html")
def verify_html():
    return send_file(STATIC_DIR / "verify.html")

@app.route("/report.html")
def report_html():
    return send_file(STATIC_DIR / "report.html")

@app.route("/index.html")
def serve_test_index():
    return send_file("templates/index.html")


@app.route("/start_test")
def start_test():
    # Serve Part-2 main test page (index.html)
    return send_file("templates/index.html")


# ----------------- API: LIST AVAILABLE TESTS -----------------
@app.route("/api/tests", methods=["GET"])
def api_tests():
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    # Get domain filter from query parameter
    domain_filter = request.args.get("domain", "").strip().lower()

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Build query based on domain filter
    if domain_filter:
        cur.execute("""
            SELECT exam_id as id, exam_title as title, description, domain, difficulty, duration, total_questions
            FROM exams
            WHERE is_active = 1 AND LOWER(domain) = ?
            ORDER BY exam_id
        """, (domain_filter,))
    else:
        cur.execute("""
            SELECT exam_id as id, exam_title as title, description, domain, difficulty, duration, total_questions
            FROM exams
            WHERE is_active = 1
            ORDER BY exam_id
        """)
    
    rows = cur.fetchall()
    tests = [dict(row) for row in rows]
    
    # Get unique domains for filter options
    cur.execute("SELECT DISTINCT domain FROM exams WHERE is_active = 1 ORDER BY domain")
    domain_rows = cur.fetchall()
    domains = [row["domain"] for row in domain_rows]
    
    conn.close()

    return jsonify({
        "success": True,
        "tests": tests,
        "domains": domains,
        "total": len(tests)
    })



@app.route("/questions.json")
def serve_questions():
    return send_file("questions.json")

# ----------------- API: GET EXAM QUESTIONS -----------------
@app.route("/api/exam/<int:exam_id>/questions", methods=["GET"])
def get_exam_questions(exam_id):
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Verify exam exists and is active
    cur.execute("SELECT exam_id, exam_title, duration FROM exams WHERE exam_id = ? AND is_active = 1", (exam_id,))
    exam = cur.fetchone()
    if not exam:
        conn.close()
        return jsonify({"success": False, "message": "Exam not found or inactive"}), 404
    
    # Get questions for this exam
    cur.execute("""
        SELECT question_id, question, options, correct_answer, question_order
        FROM exam_questions
        WHERE exam_id = ?
        ORDER BY question_order
    """, (exam_id,))
    
    rows = cur.fetchall()
    questions = []
    for row in rows:
        options = json.loads(row["options"]) if row["options"] else []
        questions.append({
            "question_id": row["question_id"],
            "question": row["question"],
            "options": options,
            "correct_answer": row["correct_answer"],
            "question_order": row["question_order"]
        })
    
    conn.close()
    
    return jsonify({
        "success": True,
        "exam_id": exam_id,
        "exam_title": exam["exam_title"],
        "duration": exam["duration"],
        "questions": questions
    })

# ----------------- API: START EXAM SESSION -----------------
@app.route("/api/session/start", methods=["POST"])
def start_session():
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "message": "Expected JSON body."}), 400
    
    exam_id = data.get("exam_id")
    if not exam_id:
        return jsonify({"success": False, "message": "exam_id is required."}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Verify exam exists
    cur.execute("SELECT exam_id FROM exams WHERE exam_id = ? AND is_active = 1", (exam_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Exam not found or inactive"}), 404
    
    # Check if user has an active session for this exam
    cur.execute("""
        SELECT session_id FROM sessions
        WHERE user_id = ? AND exam_id = ? AND status = 'active'
    """, (user_id, exam_id))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return jsonify({
            "success": True,
            "session_id": existing["session_id"],
            "message": "Active session already exists"
        })
    
    # Create new session
    start_time = datetime.utcnow().isoformat() + "Z"
    created_at = start_time
    
    cur.execute("""
        INSERT INTO sessions (user_id, exam_id, start_time, status, created_at)
        VALUES (?, ?, ?, 'active', ?)
    """, (user_id, exam_id, start_time, created_at))
    
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "session_id": session_id,
        "start_time": start_time,
        "message": "Session started successfully"
    })

# ----------------- API: END EXAM SESSION AND CREATE REPORT -----------------
@app.route("/api/session/end", methods=["POST"])
def end_session():
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "message": "Expected JSON body."}), 400
    
    session_id = data.get("session_id")
    answers = data.get("answers", {})  # {question_id: selected_answer_index}
    
    if not session_id:
        return jsonify({"success": False, "message": "session_id is required."}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Get session details
    cur.execute("""
        SELECT session_id, user_id, exam_id, start_time
        FROM sessions
        WHERE session_id = ? AND user_id = ? AND status = 'active'
    """, (session_id, user_id))
    session = cur.fetchone()
    
    if not session:
        conn.close()
        return jsonify({"success": False, "message": "Active session not found"}), 404
    
    exam_id = session["exam_id"]
    end_time = datetime.utcnow().isoformat() + "Z"
    
    # Get correct answers for this exam
    cur.execute("""
        SELECT question_id, correct_answer
        FROM exam_questions
        WHERE exam_id = ?
    """, (exam_id,))
    
    correct_answers = {row["question_id"]: row["correct_answer"] for row in cur.fetchall()}
    
    # Calculate score
    total_questions = len(correct_answers)
    correct_count = 0
    
    for question_id, user_answer in answers.items():
        question_id = int(question_id)
        if question_id in correct_answers:
            if user_answer == correct_answers[question_id]:
                correct_count += 1
    
    marks = float(correct_count)
    percentage = (marks / total_questions * 100) if total_questions > 0 else 0.0
    
    # Update session
    cur.execute("""
        UPDATE sessions
        SET end_time = ?, status = 'completed'
        WHERE session_id = ?
    """, (end_time, session_id))
    
    # Create report
    submitted_at = end_time
    cur.execute("""
        INSERT INTO reports (session_id, user_id, exam_id, total_questions, correct_answers, marks, percentage, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (session_id, user_id, exam_id, total_questions, correct_count, marks, percentage, submitted_at))
    
    report_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "report_id": report_id,
        "session_id": session_id,
        "total_questions": total_questions,
        "correct_answers": correct_count,
        "marks": marks,
        "percentage": round(percentage, 2),
        "message": "Session ended and report created successfully"
    })

# ----------------- API: ANALYZE FRAME (Proctoring) -----------------
@app.route("/analyze_frame", methods=["POST"])
def analyze_frame():
    """Analyze video frame for proctoring violations"""
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "no image"}), 400
    
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    
    try:
        frame = b64_to_image(data["image"])
        faces, landmarks = detect_faces_stable(frame)
        head_pose = None
        
        if faces and landmarks:
            ratio, direction, severity = estimate_head_pose_simple(landmarks, faces[0])
            head_pose = {"ratio": float(ratio), "direction": direction, "severity": float(severity)}
        
        faces_out = [{"x": int(x), "y": int(y), "w": int(w_), "h": int(h_)} for (x, y, w_, h_) in faces]
        fc = len(faces_out)
        
        # Log violations
        if fc == 0:
            log_violation(session_id, "NO_FACE", "Person not present in frame", "high")
        elif fc > 1:
            log_violation(session_id, "MULTIPLE_FACES", f"Multiple persons detected ({fc} faces)", "high")
        elif head_pose and head_pose["direction"] != "Center" and head_pose["severity"] > 0.3:
            log_violation(session_id, "HEAD_POSE", f"Looking {head_pose['direction']}", "medium")
        
        return jsonify({
            "faces": faces_out,
            "face_count": fc,
            "landmarks": landmarks,
            "head_pose": head_pose
        })
    except Exception as e:
        print("analyze_frame error:", e)
        return jsonify({"error": str(e)}), 500

# ----------------- API: VOICE EVENT (Proctoring) -----------------
@app.route("/voice_event", methods=["POST"])
def voice_event():
    """Log voice violations during exam"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400
    
    session_id = data.get("session_id")
    rms = data.get("rms")
    event = data.get("event", "periodic")
    duration = data.get("duration", 0.0)
    
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    
    try:
        if event == "voice_start":
            log_violation(session_id, "VOICE_START", f"Voice detected (RMS: {rms:.4f})", "low")
        elif event == "voice_stop":
            if duration >= proctoring_state["voice_alert_duration"]:
                log_violation(session_id, "VOICE_VIOLATION", f"Voice detected for {duration:.1f}s", "medium")
        elif event == "periodic" and rms is not None and rms > proctoring_state["voice_threshold"]:
            log_violation(session_id, "VOICE_DETECTED", f"RMS {rms:.4f} over threshold", "low")
        
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- API: GET REPORT -----------------
@app.route("/api/report/<int:session_id>", methods=["GET"])
def get_report(session_id):
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Get report
    cur.execute("""
        SELECT r.report_id, r.session_id, r.user_id, r.exam_id, r.total_questions,
               r.correct_answers, r.marks, r.percentage, r.submitted_at,
               e.exam_title, e.domain, s.start_time, s.end_time
        FROM reports r
        JOIN exams e ON r.exam_id = e.exam_id
        JOIN sessions s ON r.session_id = s.session_id
        WHERE r.session_id = ? AND r.user_id = ?
    """, (session_id, user_id))
    
    report = cur.fetchone()
    
    if not report:
        conn.close()
        return jsonify({"success": False, "message": "Report not found"}), 404
    
    # Get violations
    cur.execute("""
        SELECT violation_type, violation_details, timestamp, severity
        FROM violation_logs
        WHERE session_id = ?
        ORDER BY timestamp
    """, (session_id,))
    
    violations = [dict(row) for row in cur.fetchall()]
    
    # Get question details for strengths/weaknesses
    cur.execute("""
        SELECT eq.question_id, eq.question, eq.correct_answer
        FROM exam_questions eq
        WHERE eq.exam_id = ?
        ORDER BY eq.question_order
    """, (report["exam_id"],))
    
    questions = [dict(row) for row in cur.fetchall()]
    
    # Get user answers (if stored separately, otherwise calculate from report)
    # For now, we'll analyze based on correct/incorrect counts
    total = report["total_questions"]
    correct = report["correct_answers"]
    incorrect = total - correct
    
    # Calculate strengths and weaknesses
    strengths = []
    weaknesses = []
    
    if correct > 0:
        strengths.append(f"Answered {correct} out of {total} questions correctly ({report['percentage']:.1f}%)")
    if incorrect > 0:
        weaknesses.append(f"Missed {incorrect} questions")
    
    # Analyze violations
    violation_summary = {}
    for v in violations:
        v_type = v["violation_type"]
        violation_summary[v_type] = violation_summary.get(v_type, 0) + 1
    
    conn.close()
    
    return jsonify({
        "success": True,
        "report": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "exam_id": report["exam_id"],
            "exam_title": report["exam_title"],
            "domain": report["domain"],
            "total_questions": report["total_questions"],
            "correct_answers": report["correct_answers"],
            "marks": report["marks"],
            "percentage": report["percentage"],
            "start_time": report["start_time"],
            "end_time": report["end_time"],
            "submitted_at": report["submitted_at"],
            "strengths": strengths,
            "weaknesses": weaknesses,
            "violations": violations,
            "violation_summary": violation_summary,
            "total_violations": len(violations)
        }
    })

# ----------------- API: DOWNLOAD REPORT -----------------
@app.route("/api/report/<int:session_id>/download", methods=["GET"])
def download_report(session_id):
    """Generate and download report as HTML/PDF"""
    # Support token in query parameter for download links
    token = request.args.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return jsonify({"success": False, "message": "Authentication required"}), 401
    
    try:
        payload = decode_jwt(token)
        user_id = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    except:
        return jsonify({"success": False, "message": "Invalid token"}), 401

    conn = get_db_conn()
    cur = conn.cursor()
    
    # Get report with all details
    cur.execute("""
        SELECT r.*, e.exam_title, e.domain, u.full_name, u.student_id, u.email,
               s.start_time, s.end_time
        FROM reports r
        JOIN exams e ON r.exam_id = e.exam_id
        JOIN users u ON r.user_id = u.user_id
        JOIN sessions s ON r.session_id = s.session_id
        WHERE r.session_id = ? AND r.user_id = ?
    """, (session_id, user_id))
    
    report = cur.fetchone()
    
    if not report:
        conn.close()
        return jsonify({"success": False, "message": "Report not found"}), 404
    
    # Get violations
    cur.execute("""
        SELECT violation_type, violation_details, timestamp, severity
        FROM violation_logs
        WHERE session_id = ?
        ORDER BY timestamp
    """, (session_id,))
    
    violations = [dict(row) for row in cur.fetchall()]
    conn.close()
    
    # Generate HTML report
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Exam Report - {report['exam_title']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; }}
            .score-box {{ background: #ecf0f1; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .score {{ font-size: 48px; font-weight: bold; color: #27ae60; }}
            .info-row {{ display: flex; justify-content: space-between; margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 5px; }}
            .strength {{ color: #27ae60; padding: 8px; margin: 5px 0; background: #d5f4e6; border-left: 4px solid #27ae60; }}
            .weakness {{ color: #e74c3c; padding: 8px; margin: 5px 0; background: #fadbd8; border-left: 4px solid #e74c3c; }}
            .violation {{ padding: 10px; margin: 5px 0; border-left: 4px solid #f39c12; background: #fef5e7; }}
            .violation.high {{ border-left-color: #e74c3c; background: #fadbd8; }}
            .violation.medium {{ border-left-color: #f39c12; background: #fef5e7; }}
            .violation.low {{ border-left-color: #3498db; background: #ebf5fb; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #3498db; color: white; }}
            .print-btn {{ background: #3498db; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; margin: 20px 0; }}
            .print-btn:hover {{ background: #2980b9; }}
            @media print {{
                .print-btn {{ display: none; }}
                body {{ background: white; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Exam Report</h1>
            
            <div class="info-row">
                <strong>Student Name:</strong> <span>{report['full_name']}</span>
            </div>
            <div class="info-row">
                <strong>Student ID:</strong> <span>{report['student_id'] or 'N/A'}</span>
            </div>
            <div class="info-row">
                <strong>Email:</strong> <span>{report['email']}</span>
            </div>
            <div class="info-row">
                <strong>Exam:</strong> <span>{report['exam_title']}</span>
            </div>
            <div class="info-row">
                <strong>Domain:</strong> <span>{report['domain']}</span>
            </div>
            <div class="info-row">
                <strong>Start Time:</strong> <span>{report['start_time']}</span>
            </div>
            <div class="info-row">
                <strong>End Time:</strong> <span>{report['end_time'] or 'N/A'}</span>
            </div>
            
            <div class="score-box">
                <div class="score">{report['percentage']:.1f}%</div>
                <p><strong>Marks:</strong> {report['marks']:.1f} / {report['total_questions']}</p>
                <p><strong>Correct Answers:</strong> {report['correct_answers']} / {report['total_questions']}</p>
            </div>
            
            <h2>Strengths</h2>
            <div class="strength">✓ Answered {report['correct_answers']} questions correctly</div>
            <div class="strength">✓ Achieved {report['percentage']:.1f}% score</div>
            
            <h2>Weaknesses</h2>
            <div class="weakness">✗ Missed {report['total_questions'] - report['correct_answers']} questions</div>
            <div class="weakness">✗ Need improvement in {report['domain']} domain</div>
            
            <h2>Proctoring Violations ({len(violations)})</h2>
            {"<p>No violations detected during the exam session.</p>" if len(violations) == 0 else ""}
            {"<table><tr><th>Time</th><th>Type</th><th>Details</th><th>Severity</th></tr>" + "".join([f"<tr><td>{v['timestamp']}</td><td>{v['violation_type']}</td><td>{v['violation_details']}</td><td>{v['severity']}</td></tr>" for v in violations]) + "</table>" if violations else ""}
            
            <button class="print-btn" onclick="window.print()">Print Report</button>
        </div>
    </body>
    </html>
    """
    
    return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ----------------- API: REGISTER -----------------
@app.route("/api/register", methods=["POST"])
def api_register():
    # required fields: fullName, studentId, email, role, password, photo (file)
    form = request.form
    full_name = form.get("fullName", "").strip()
    student_id = form.get("studentId", "").strip()
    email = form.get("email", "").strip().lower()
    phone = form.get("phone", "").strip()
    course = form.get("course", "").strip()
    role = form.get("role", "").strip()
    password = form.get("password", "")
    notes = form.get("notes", "")

    if not full_name or not email or not password or not role:
        return jsonify({"success": False, "message": "Missing required fields."}), 400

    if "photo" not in request.files:
        return jsonify({"success": False, "message": "Photo is required."}), 400

    photo = request.files["photo"]
    if photo.filename == "":
        return jsonify({"success": False, "message": "No photo file uploaded."}), 400

    if not allowed_filename(photo.filename):
        return jsonify({"success": False, "message": "Unsupported file type. Use jpg/png."}), 400

    # check size
    photo.stream.seek(0, os.SEEK_END)
    size = photo.stream.tell()
    photo.stream.seek(0)
    if size > MAX_PHOTO_BYTES:
        return jsonify({"success": False, "message": "Photo too large (max 4 MB)."}), 400

    # make a simple unique user_id (change to UUID if you prefer)
    user_id_base = email.split("@")[0]
    user_id = f"{user_id_base}_{int(datetime.utcnow().timestamp())}"

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Email already registered."}), 400

    try:
        photo_path = save_photo_file(photo, user_id)
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": f"Failed to save photo: {e}"}), 500

    encoding_path, err = compute_and_save_encoding(photo_path, user_id)
    if err:
        try:
            os.remove(photo_path)
        except Exception:
            pass
        conn.close()
        if err == "no-face":
            return jsonify({"success": False, "message": "No face detected in the uploaded photo."}), 400
        if err == "multiple-faces":
            return jsonify({"success": False, "message": "Multiple faces detected. Please upload a single-person photo."}), 400
        return jsonify({"success": False, "message": "Failed to compute face encoding: " + err}), 500

    password_hash = generate_password_hash(password)
    created_at = datetime.utcnow().isoformat() + "Z"

    try:
        cur.execute("""
            INSERT INTO users (user_id, full_name, student_id, email, phone, course, role, password_hash, photo_path, encoding_path, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, full_name, student_id, email, phone, course, role, password_hash, photo_path, encoding_path, notes, created_at))
        conn.commit()
    except Exception as e:
        conn.rollback()
        try:
            os.remove(photo_path)
            os.remove(encoding_path)
        except Exception:
            pass
        conn.close()
        return jsonify({"success": False, "message": "DB error: " + str(e)}), 500

    conn.close()
    return jsonify({"success": True, "message": "Registered successfully", "userId": user_id})

# ----------------- API: LOGIN -----------------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "message": "Expected JSON body."}), 400
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"success": False, "message": "Email and password required."}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, password_hash, full_name FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"success": False, "message": "Invalid credentials."}), 401


    payload = {
        "sub": row["user_id"],
        "uid": row["id"],
        "name": row["full_name"],
        "email": email
    }
    token = make_jwt(payload)
    return jsonify({"success": True, "message": "Login successful", "token": token})

# ----------------- API: VERIFY (face compare) -----------------
@app.route("/api/verify", methods=["POST"])
def api_verify():
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    if "photo" not in request.files:
        return jsonify({"success": False, "message": "No photo provided (field name must be 'photo')"}), 400

    photo = request.files["photo"]
    if photo.filename == "":
        return jsonify({"success": False, "message": "Empty photo uploaded"}), 400

    # size check
    photo.stream.seek(0, os.SEEK_END)
    size = photo.stream.tell()
    photo.stream.seek(0)
    if size > MAX_PHOTO_BYTES:
        return jsonify({"success": False, "message": "Uploaded photo too large (max 4 MB)"}), 400

    try:
        img_bytes = photo.read()
        img_array = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({"success": False, "message": "Could not decode uploaded image"}), 400

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        boxes = face_recognition.face_locations(rgb, model="hog")
        if len(boxes) == 0:
            return jsonify({"success": False, "message": "No face detected in the uploaded image"}), 400
        if len(boxes) > 1:
            return jsonify({"success": False, "message": "Multiple faces detected. Present only yourself."}), 400

        encodings = face_recognition.face_encodings(rgb, boxes)
        if not encodings:
            return jsonify({"success": False, "message": "Failed to compute face encoding from uploaded image"}), 500
        live_encoding = encodings[0]

        enc_path = ENC_DIR / f"{user_id}.pkl"
        if not enc_path.exists():
            return jsonify({"success": False, "message": "No registered encoding found for user"}), 404

        with open(enc_path, "rb") as f:
            data = pickle.load(f)
        registered_encoding = data.get("encoding")
        if registered_encoding is None:
            return jsonify({"success": False, "message": "Corrupt encoding file"}), 500

        try:
            threshold = float(request.form.get("tolerance", 0.55))
        except Exception:
            threshold = 0.55

        distance = float(face_recognition.face_distance([registered_encoding], live_encoding)[0])
        matched = bool(face_recognition.compare_faces([registered_encoding], live_encoding, tolerance=threshold)[0])

        status_code = 200 if matched else 401
        return jsonify({
            "success": matched,
            "message": "matched" if matched else "not matched",
            "distance": distance,
            "threshold": threshold
        }), status_code

    except Exception as e:
        return jsonify({"success": False, "message": "Server error during verification: " + str(e)}), 500

# ----------------- API: ME -----------------
@app.route("/api/me", methods=["GET"])
def api_me():
    user_id, err = get_user_id_from_auth_header()
    if err:
        return jsonify({"success": False, "message": err}), 401

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "message": "User not found"}), 404

    return jsonify({
        "success": True,
        "userId": row["user_id"],
        "name": row["full_name"],
        "email": row["email"],
        "role": row["role"]
    })

# ----------------- API: PHOTO (serve stored photo) -----------------
@app.route("/api/photo/<user_id>", methods=["GET"])
def get_user_photo(user_id):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT photo_path FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()    
    conn.close()
    if not row:
        return jsonify({"success": False, "message": "User not found"}), 404
    path = row["photo_path"]
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "message": "Photo not found"}), 404
    return send_file(path)

# ----------------- HEALTH -----------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

# ----------------- RUN -----------------
if __name__ == "__main__":
    print("Starting Flask server at http://127.0.0.1:5000")
    app.run(debug=True)
