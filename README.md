# AI Viva Simulator

AI Viva Simulator is a Python + Web UI mini project designed for a modern 2026 classroom demo. It simulates a professor-style viva interview, evaluates student answers, gives AI-style feedback, and generates a final readiness report.

## Why This Project Is Different

This is not a simple school planner or CRUD app. It behaves like a hybrid AI assessment system:

- Interactive viva/interview simulation.
- Real AI model scoring engine (Cloud API or Local LLM).
- OpenAI / Gemini / Ollama / LM Studio integration.
- Strengths, gaps, model answer, confidence, and readiness level.
- Professor Mode final report.

## Features

- Choose subject and level.
- Add your own subject from the browser.
- Choose Easy, Medium, or Hard difficulty.
- Configure Cloud API Key or Local AI model (Ollama / LM Studio) in the UI or environment.
- Answer viva questions one by one.
- Get difficulty-aware score, confidence, feedback, strengths, gaps, and model answer.
- Generate a final report with average score, readiness, and weak topics.
- Uses a transparent rubric: keyword coverage, clarity, examples, and concept precision.
- AI evaluation mode: powered by OpenAI, Gemini, or local models.

## Technologies Used

- Python standard library only.
- HTML, CSS, and JavaScript.
- JSON question bank.
- AI model integration (OpenAI, Gemini, Ollama, LM Studio).

## How To Run

```powershell
python server.py
```

Open:

```text
http://localhost:8000
```

If Python is blocked on Windows, repair it with one of these options:

1. Install Python from https://www.python.org/downloads/ and enable **Add Python to PATH**.
2. Or open Windows Settings, search **App execution aliases**, and turn off the Microsoft Store Python aliases.
3. Restart PowerShell and run `python --version`.

## AI Model Setup

To enable AI evaluation, either paste your API key / model base URL in the web UI settings or set environment variables in PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
$env:OPENAI_MODEL="gpt-4o-mini"
python server.py
```

The in-page API key is not saved to server disk. It is sent only with the evaluation requests.

## API Routes

- `GET /` opens the web app.
- `GET /api/questions?subject=Python&level=medium` returns viva questions.
- `POST /api/generate-questions` generates questions for built-in or custom subjects.
- `POST /api/evaluate` evaluates one answer.
- `POST /api/report` creates the final professor report.

## AI Rubric Evaluation

- Keyword coverage: 40%.
- Explanation clarity and answer length: 20%.
- Example/code mention: 20%.
- Concept precision: 20%.

Readiness labels:

- Needs Practice
- Developing
- Good
- Excellent

Difficulty changes the expectation:

- Easy mode accepts shorter beginner-friendly answers.
- Medium mode expects clear explanation and example.
- Hard mode expects deeper reasoning, tradeoffs, limitations, or edge cases.

## Future Scope

- Voice-based viva using speech recognition.
- Face confidence detection using webcam.
- PDF export for report.
- Admin panel for adding custom questions.
- Real AI conversation mode with follow-up questions and adaptive difficulty.

## Conclusion

This project demonstrates an AI-era educational assessment tool using simple, explainable technology. It is suitable for a professor demo because it combines backend APIs, frontend UI, scoring logic, analytics, and optional real AI integration.
