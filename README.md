# Viva Simulator

A web app designed to help engineering and computer science students practice for oral viva examinations and thesis defenses. It generates subject-specific questions from lecture notes or syllabus files, reads them aloud, lets students speak their answers using voice dictation, and grades responses based on technical accuracy and keyword coverage.

---

## Why I Built This

During engineering vivas, many students know their subject well on paper but freeze up or struggle to structure their explanations when questioned by professors. Mock vivas with classmates rarely happen because everyone is busy preparing for their own exams. 

I built this project to simulate that high-pressure oral exam environment:
1. An AI examiner asks you technical questions out loud.
2. You speak your answer through your microphone instead of typing.
3. The system checks if you covered the necessary technical keywords, provided clear reasoning, and gave concrete examples.
4. Professors can also use the teacher portal to set up timed exams for their classes, generate question banks from lecture slides, and review candidate recordings.

---

## Core Architecture & Technical Choices

- **Backend (Python standard library):** Built using Python's built-in `http.server` and `sqlite3` modules. I intentionally avoided heavy frameworks like Django or Flask so the entire project can be run with zero setup on any machine having Python 3.10+.
- **Voice Recognition (Web Speech API):** Speech-to-text dictation runs entirely in the browser using native `webkitSpeechRecognition`. This eliminates the need for expensive third-party speech API keys and keeps audio processing fast and private.
- **Local & Cloud LLM Support:** Works out of the box with local models running on **Ollama** (`qwen2.5-coder:3b`, `llama3`) for 100% offline and free use, but also supports OpenAI and Google Gemini keys if cloud inference is preferred.
- **Evaluation Rubric:** Scores answers across 4 distinct dimensions:
  - Keyword Coverage (40%) — verifies that core technical terms were mentioned.
  - Concept Precision (20%) — checks for theoretical correctness.
  - Explanation Clarity (20%) — evaluates sentence flow and coherence.
  - Examples & Evidence (20%) — looks for practical applications or analogies.
- **Database:** SQLite with Write-Ahead Logging (WAL mode) enabled for safe concurrent access during multi-student exams.

---

## Project Structure

```
viva-simulator/
├── server.py              # Main HTTP server & API endpoint handlers
├── test_server.py         # Automated unit & integration test suite
├── requirements.txt       # Optional dependencies (pypdf for reading PDF notes)
├── vercel.json            # Serverless deployment configuration for Vercel
├── data/
│   └── questions.json     # Preloaded starter questions for common CS topics
└── static/                # Frontend user interfaces and client-side logic
    ├── index.html         # Project landing page
    ├── styles.css         # Global design system stylesheet
    ├── theme.js           # Theme toggle controller
    ├── toast.js           # Notification toast helper
    ├── auth.js            # Teacher session validation
    ├── student-dashboard.html # Student hub and model configuration
    ├── questions.html     # Interactive practice stage & speech recorder
    ├── teacher-login.html # Instructor authentication
    ├── teacher-dashboard.html # Assessment management & stats
    ├── teacher-builder.html # Assessment creation & question authoring
    ├── teacher-share.html # Assessment link & access token generator
    ├── teacher-results.html # Exam submission analytics & CSV export
    ├── teacher-student.html # Individual candidate response review
    ├── viva-entry.html    # Candidate exam intake & PIN entry
    ├── viva-exam.html     # Proctored viva exam room
    └── viva-complete.html # Exam submission & score breakdown
```

---

## Setup & Running Locally

### 1. Prerequisites
- Python 3.10 or newer
- (Optional) `pypdf` if you want to upload PDF lecture notes:
  ```bash
  pip install pypdf
  ```

### 2. (Optional) Run with Local AI via Ollama
If you want to use local models completely free without an API key:
```bash
ollama run qwen2.5-coder:3b
```
*(Leave Ollama running in the background on port 11434).*

### 3. Start the Web Server
```bash
python server.py
```
Open **`http://localhost:8000`** in Google Chrome or Microsoft Edge.

> **Note on Browser Compatibility:** Voice dictation requires the Web Speech API. For the best experience, use a Chromium-based browser (Chrome, Edge, Brave). Firefox and Safari support text answering and audio read-aloud, but their speech-to-text dictation may be limited.

---

## Default Instructor Credentials

To access the teacher portal locally:
- **URL:** `http://localhost:8000/teacher/login`
- **Email:** `teacher@example.com`
- **Password:** `password`

---

## Running Automated Tests

To run the unit test suite verifying database setup, authentication, rubric calculations, and exam flows:
```bash
python test_server.py
```
All 13 tests should pass.

---

## License
MIT License. Created for academic and educational learning.
