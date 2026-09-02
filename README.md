# Viva Simulator (viva-simulator)
### Intelligent AI Oral Examination & Defense Platform

Viva Simulator is a modern, lightweight, full-stack academic platform for technical oral viva examinations, thesis defenses, syllabus material ingestion, examiner voice synthesis, and multi-dimensional rubric evaluation.

---

## ⚡ Key Highlights & Features

- **Local Ollama & Cloud AI Routing**: Native zero-dependency connection to local Ollama (`qwen2.5-coder:3b`, `llama3`, `deepseek-r1`, etc.) at `http://localhost:11434` or cloud providers (OpenAI `gpt-4o-mini`, Google Gemini `gemini-1.5-flash`). Includes a **"Test Connection ⚡"** pre-flight probe.
- **Dual Voice Interaction**:
  - **🔊 AI Oral Examiner Voice Read-Aloud (TTS)**: Web Speech Synthesis for realistic oral viva questioning.
  - **🎙️ Speech-to-Text Voice Dictation (STT)**: Hands-free verbal answering with live word counting.
- **4-Dimension Rubric Assessment Visualizer**:
  1. **Concept Precision (20%)**
  2. **Explanation Clarity (20%)**
  3. **Evidence & Concrete Examples (20%)**
  4. **Keyword & Terminology Coverage (40%)**
- **Document & Syllabus Ingestion**: Ingest PDF (`pypdf` + raw stream fallback), DOCX, TXT, Markdown, CSV, and code files to generate relevant oral viva question sets.
- **Personal Study Vault & Revision Export**: Private note-taking HUD on every question, star bookmarks, and one-click **"Export Study Guide (.md)"** report generator.
- **Productivity & Focus Suite**: Pomodoro timer with Web Audio synthesized focus ambiance (Rain, Deep Brown Noise, Gentle White Noise) and live weather pill.
- **Instructor Command Center**:
  - Author timed viva assessments with custom question ordering and question banks.
  - Set PIN security codes and auto-expiration timestamps.
  - Duplicate/clone assessments and delete assessments.
  - Inspect student oral recordings and evaluations with **Manual Mark Overrides & Audit Logs**.
  - **Export Gradebook to CSV** with one click.
- **Non-Blocking Glassmorphic UI**: Obsidian Aurora 2.0 theme with light/dark toggle, unified toast notifications (`Toast.success`, `Toast.error`), and accessible confirmation modals.

---

## 🚀 Quickstart

### 1. Requirements
- Python 3.10+
- Optional: `pypdf` (for PDF document ingestion)

```bash
pip install pypdf
```

### 2. Launch Local AI with Ollama (Optional)
If running local models without API keys:
```bash
ollama run qwen2.5-coder:3b
```

### 3. Start the Server
```bash
python server.py
```
Open **`http://localhost:8000`** in your browser.

Default Teacher Login:
- **Email:** `teacher@example.com`
- **Password:** `password`

---

## 🧪 Automated Testing

Run the automated unit and end-to-end integration test suite:
```bash
python test_server.py
```
All 11 test modules verify authentication, password hashing, document parsing, Ollama endpoint normalization, rubric evaluation, public exam lifecycles, and teacher mark overrides.
