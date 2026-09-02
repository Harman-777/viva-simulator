# Viva AI — Project Notes & Viva Defense Guide

## Project Title
**Viva AI — Intelligent Oral Examination & Academic Assessment Suite**

---

## Problem Statement
Traditional viva and oral defense preparation lacks objective, real-time feedback. Students struggle to assess whether their spoken technical explanations are precise, structured, and comprehensive. Viva AI addresses this by providing an interactive oral examination simulator with transparent 4-dimension rubric scoring, AI-driven question generation from lecture notes, voice speech-to-text dictation, and an end-to-end teacher assessment suite.

---

## Core System Architecture

1. **Python Server & WSGI Adapter**:
   - Zero framework overhead — built using the Python standard library.
   - Dual-runtime: Standalone multi-threaded `ThreadingHTTPServer` locally, WSGI adapter for Vercel serverless.

2. **Document Ingestion Engine**:
   - Parses PDF (`pypdf`), DOCX (`zipfile`/XML), Markdown, TXT, and CSV lecture notes in-memory.
   - Dynamically feeds context to the AI generation pipeline.

3. **Multi-Model AI Scoring Core**:
   - Direct integration with OpenAI (`gpt-4o-mini`), Google Gemini (`gemini-1.5-flash`), and local LLMs (`Ollama`/`LM Studio`).
   - Strict 4-point rubric: Concept Precision (20%), Explanation Clarity (20%), Evidence/Examples (20%), Keyword Coverage (40%).
   - Non-answer heuristics to filter blank/evasive answers without incurring API latency.

4. **Obsidian Aurora Design System & Oral Voice HUD**:
   - Custom design system created with Stitch MCP (`Plus Jakarta Sans`, `Inter`, `JetBrains Mono`).
   - Web Speech API integration for spoken oral responses.
   - Pomodoro Focus Suite with Web Audio API chime synthesis.

---

## Teacher Assessment & Classroom Management
- **Custom Assessment Builder**: Set duration, fixed/student-choice questions, and randomized pools.
- **PIN Access & Auto-Expiry**: Protect exam access with hashed PINs and time-based expiration.
- **Parallel Asynchronous Grading**: Batch evaluates student exam attempts concurrently via `concurrent.futures.ThreadPoolExecutor`.
- **Grade Inspection & Override**: Audit AI scoring with manual teacher mark adjustments and mandatory reasons.

---

## Common Viva Defense Questions & Answers

### Q: Why did you avoid heavy frameworks like Flask or FastAPI?
**A**: Viva AI utilizes Python's built-in `http.server` and standard library modules to eliminate external web framework dependencies, minimize cold-start latencies, and allow plug-and-play local execution while retaining full WSGI compatibility for cloud serverless deployments.

### Q: How does the system evaluate spoken oral answers?
**A**: The platform utilizes the browser's native **Web Speech API** for real-time speech recognition, transcribing verbal responses into structured text which is evaluated against technical rubrics and keyword coverage by the AI model.

### Q: How are teacher credentials and student attempts secured?
**A**: Passwords use **PBKDF2-HMAC-SHA256** with 210,000 iterations and random salts. Sessions use **HMAC-SHA256 signed tokens** in `HttpOnly` cookies, with IP-based rate limiting to prevent brute-force attacks.
