from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
import zipfile
import concurrent.futures
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree
import time
import threading


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path("/tmp") if os.environ.get("VERCEL") else (ROOT / "data")
DATABASE_PATH = DATA_DIR / "viva.db"
PORT = int(os.environ.get("PORT", "8000"))
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_MATERIAL_TEXT = 60000

# ---------- Login rate-limiting ----------
_login_attempts_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}   # ip -> [timestamps]
LOGIN_RATE_WINDOW = 900     # 15 minutes
LOGIN_MAX_ATTEMPTS = 5


def check_login_rate(ip: str) -> None:
    """Raise ApiError(429) if ip exceeded login attempt limit."""
    now_ts = time.monotonic()
    with _login_attempts_lock:
        attempts = _login_attempts.get(ip, [])
        # prune old entries
        attempts = [t for t in attempts if now_ts - t < LOGIN_RATE_WINDOW]
        _login_attempts[ip] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise ApiError("Too many login attempts. Please wait 15 minutes before trying again.", HTTPStatus.TOO_MANY_REQUESTS)


def record_failed_login(ip: str) -> None:
    now_ts = time.monotonic()
    with _login_attempts_lock:
        attempts = _login_attempts.setdefault(ip, [])
        attempts.append(now_ts)
        # Periodic cleanup: remove IPs with only old entries
        stale = [k for k, v in _login_attempts.items() if all(now_ts - t >= LOGIN_RATE_WINDOW for t in v)]
        for k in stale:
            del _login_attempts[k]


def clear_login_rate(ip: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(ip, None)


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        self.message = message
        self.status = status
        super().__init__(message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def random_token() -> str:
    return secrets.token_urlsafe(24)


def database() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if not os.environ.get("VERCEL"):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
    return connection


def init_database() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with database() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                api_settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS teacher_sessions (
                id TEXT PRIMARY KEY,
                teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS study_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_key TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                extracted_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                subject TEXT NOT NULL,
                instructions TEXT NOT NULL DEFAULT '',
                duration_minutes INTEGER NOT NULL DEFAULT 20,
                question_count_mode TEXT NOT NULL DEFAULT 'fixed',
                question_count_min INTEGER NOT NULL DEFAULT 1,
                question_count_max INTEGER NOT NULL DEFAULT 1,
                student_fields_json TEXT NOT NULL,
                show_results INTEGER NOT NULL DEFAULT 0,
                question_ordering TEXT NOT NULL DEFAULT 'fixed',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assessment_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                question_text TEXT NOT NULL,
                reference_answer TEXT NOT NULL DEFAULT '',
                marks REAL NOT NULL DEFAULT 10,
                position INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS share_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL UNIQUE REFERENCES assessments(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                pin_hash TEXT NOT NULL DEFAULT '',
                expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                share_link_id INTEGER NOT NULL REFERENCES share_links(id) ON DELETE CASCADE,
                access_token TEXT NOT NULL UNIQUE,
                student_data_json TEXT NOT NULL,
                selected_question_ids_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'in_progress',
                needs_review INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                submitted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS attempt_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
                question_id INTEGER NOT NULL REFERENCES assessment_questions(id) ON DELETE CASCADE,
                answer_text TEXT NOT NULL,
                ai_score REAL NOT NULL,
                final_score REAL NOT NULL,
                evaluation_json TEXT NOT NULL,
                override_reason TEXT NOT NULL DEFAULT '',
                evaluated_at TEXT NOT NULL,
                UNIQUE(attempt_id, question_id)
            );
            """
        )
        # Migrations to add columns if database was created prior to schema expansion
        try:
            conn.execute("ALTER TABLE assessments ADD COLUMN question_ordering TEXT NOT NULL DEFAULT 'fixed'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE attempts ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE teachers ADD COLUMN api_settings_json TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass

        # Seed default teacher account if database is completely empty
        if conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0:
            pass_hash, pass_salt = password_record("password")
            conn.execute(
                "INSERT INTO teachers (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                ("teacher@example.com", "Default Teacher", pass_hash, pass_salt, now())
            )



def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def parse_json(value: str, fallback):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def password_record(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    encoded = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000)
    return base64.b64encode(encoded).decode("ascii"), base64.b64encode(salt).decode("ascii")


def valid_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    salt = base64.b64decode(stored_salt.encode("ascii"))
    encoded = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000)
    return hmac.compare_digest(base64.b64encode(encoded).decode("ascii"), stored_hash)


def clean_text(value, max_length: int = 10000) -> str:
    return str(value or "").strip()[:max_length]


def validate_questions(questions) -> list[dict]:
    if not isinstance(questions, list) or not questions:
        raise ApiError("Add at least one question before saving the viva.")
    if len(questions) > 100:
        raise ApiError("A viva can contain at most 100 questions.")

    clean_questions = []
    for index, item in enumerate(questions):
        question = clean_text(item.get("question"), 3000)
        reference_answer = clean_text(item.get("reference_answer"), 8000)
        try:
            marks = float(item.get("marks", 10))
        except (TypeError, ValueError):
            raise ApiError(f"Question {index + 1} has invalid marks.")
        if not question:
            raise ApiError(f"Question {index + 1} cannot be empty.")
        if not 0 < marks <= 100:
            raise ApiError(f"Question {index + 1} marks must be between 0 and 100.")
        clean_questions.append({"question": question, "reference_answer": reference_answer, "marks": marks})
    return clean_questions


def validate_student_fields(fields) -> list[dict]:
    defaults = [
        {"key": "name", "label": "Full name", "required": True},
        {"key": "roll_no", "label": "Roll number", "required": True},
    ]
    if fields is None:
        return defaults
    if not isinstance(fields, list) or not fields:
        raise ApiError("Student information fields are invalid.")
    if len(fields) > 8:
        raise ApiError("Use up to eight student information fields.")

    seen = set()
    result = []
    for item in fields:
        key = re.sub(r"[^a-z0-9_]", "_", clean_text(item.get("key"), 40).lower())
        label = clean_text(item.get("label"), 80)
        if not key or not label or key in seen:
            raise ApiError("Each student information field needs a unique name and label.")
        seen.add(key)
        result.append({"key": key, "label": label, "required": bool(item.get("required", True))})
    return result


def assessment_payload(payload: dict) -> dict:
    title = clean_text(payload.get("title"), 160)
    subject = clean_text(payload.get("subject"), 120)
    instructions = clean_text(payload.get("instructions"), 4000)
    if not title or not subject:
        raise ApiError("A viva needs both a title and a subject.")
    try:
        duration = int(payload.get("duration_minutes", 20))
    except (TypeError, ValueError):
        raise ApiError("Duration must be a whole number.")
    if not 1 <= duration <= 300:
        raise ApiError("Duration must be between 1 and 300 minutes.")
    mode = payload.get("question_count_mode", "fixed")
    if mode not in {"fixed", "student_select"}:
        raise ApiError("Question count mode is invalid.")
    try:
        minimum = int(payload.get("question_count_min", 1))
        maximum = int(payload.get("question_count_max", minimum))
    except (TypeError, ValueError):
        raise ApiError("Question count must be a whole number.")
    if not 1 <= minimum <= maximum <= 100:
        raise ApiError("Question count must be between 1 and 100.")
    ordering = payload.get("question_ordering", "fixed")
    if ordering not in {"fixed", "shuffled", "random"}:
        raise ApiError("Question ordering mode is invalid.")
    return {
        "title": title,
        "subject": subject,
        "instructions": instructions,
        "duration": duration,
        "mode": mode,
        "minimum": minimum,
        "maximum": maximum,
        "student_fields": validate_student_fields(payload.get("student_fields")),
        "show_results": 1 if payload.get("show_results") else 0,
        "question_ordering": ordering,
        "questions": validate_questions(payload.get("questions")),
    }


def get_openai_key(request_handler=None) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and request_handler:
        key = (request_handler.headers.get("X-Api-Key") or "").strip()
    if not key:
        raise ApiError("AI service is not configured. Add your own API key in the dashboard or ask the admin to set OPENAI_API_KEY on the server.", HTTPStatus.SERVICE_UNAVAILABLE)
    return key


def extract_openai_text(response: dict) -> str:
    try:
        return response["choices"][0]["message"]["content"]
    except KeyError:
        raise ApiError("AI service returned an unreadable response.", HTTPStatus.BAD_GATEWAY)


def decode_ai_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ApiError("AI service returned an invalid structured response. Please retry.", HTTPStatus.BAD_GATEWAY) from error


def ask_ai(instruction: str, payload: dict, max_tokens: int = 2200, api_key: str = "", base_url: str = "", model_name: str = ""):
    effective_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
    if not effective_key and not base_url:
        raise ApiError("AI service is not configured. Add your own API key in the dashboard or ask the admin to set OPENAI_API_KEY on the server.", HTTPStatus.SERVICE_UNAVAILABLE)
    
    is_gemini = effective_key.startswith("AIza") and not base_url
    
    if is_gemini:
        gemini_model = model_name if model_name else "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={effective_key}"
        request_body = {
            "contents": [{
                "parts": [{"text": instruction + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False)}]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        endpoint = base_url if base_url else OPENAI_ENDPOINT
        if base_url and not endpoint.endswith("/chat/completions"):
            endpoint = endpoint.rstrip("/") + "/chat/completions"
            
        model = model_name if model_name else OPENAI_MODEL
        request_body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an API that only returns valid JSON. Do not wrap with markdown blocks."
                },
                {
                    "role": "user",
                    "content": instruction + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False)
                }
            ],
            "max_tokens": max_tokens,
        }
        if not base_url:
            request_body["response_format"] = { "type": "json_object" }
        
        headers = {"Content-Type": "application/json"}
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"
            
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    try:
        timeout = 300 if base_url else 60
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        
        if is_gemini:
            text = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        else:
            text = extract_openai_text(raw)
            
        return decode_ai_json(text)
    except ApiError:
        raise
    except urllib.error.HTTPError as error:
        try:
            err_text = error.read().decode("utf-8")
            err_body = json.loads(err_text)
            msg = err_body.get("error", {}).get("message", err_text[:200])
        except:
            msg = f"HTTP {error.code}: {error.reason}"
        raise ApiError(f"AI error: {msg}", HTTPStatus.BAD_GATEWAY) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ApiError(f"AI service is unreachable or timed out: {str(error)}", HTTPStatus.BAD_GATEWAY) from error


def generate_practice_questions(payload: dict) -> list[dict]:
    material = clean_text(payload.get("material"), MAX_MATERIAL_TEXT)
    subject = clean_text(payload.get("subject"), 120)
    level = clean_text(payload.get("level"), 20).lower() or "medium"
    try:
        count = int(payload.get("question_count", 10))
    except (TypeError, ValueError):
        raise ApiError("Question count must be a whole number.")
    if level not in {"easy", "medium", "hard"}:
        level = "medium"
    if not 1 <= count <= 50:
        raise ApiError("Choose between 1 and 50 questions.")
    if not material:
        raise ApiError("Upload at least one study material before generating questions.")

    api_key = payload.get("_api_key", "")
    base_url = payload.get("_base_url", "")
    model_name = payload.get("_model_name", "")

    if not api_key and not base_url and not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ApiError("AI configuration required. Please enter a Cloud API Key or configure a Local AI Model URL.")

    result = ask_ai(
        (
            f"Create exactly {count} {level}-level viva practice questions using only the supplied study material. "
            "Return a JSON array. Each item must contain question, reference_answer, and key_concepts. "
            "reference_answer must be concise and key_concepts must be an array. Do not invent material not present in the source."
        ),
        {"subject": subject or "Study material", "study_material": material},
        max_tokens=min(8000, 600 + count * 180),
        api_key=api_key,
        base_url=base_url,
        model_name=model_name
    )
    if isinstance(result, dict):
        for value in result.values():
            if isinstance(value, list) and value:
                result = value
                break

    if not isinstance(result, list) or not result:
        raise ApiError("AI service returned an invalid question list. Please try again.")

    questions = []
    for item in result[:count]:
        question = clean_text(item.get("question"), 3000)
        reference = clean_text(item.get("reference_answer"), 8000)
        concepts = item.get("key_concepts") if isinstance(item.get("key_concepts"), list) else []
        if question:
            questions.append({"id": random_token(), "question": question, "reference_answer": reference, "key_concepts": [clean_text(value, 100) for value in concepts[:12] if clean_text(value, 100)]})
    if not questions:
        raise ApiError("No valid questions could be generated from the study material.")
    return questions


def evaluate_answer(question: str, answer: str, max_marks: float, reference_answer: str = "", key_concepts: list | None = None, material: str = "", api_key: str = "", base_url: str = "", model_name: str = "") -> dict:
    clean_ans = (answer or "").strip()
    if not clean_ans:
        raise ApiError("Answer cannot be empty.")
    
    clean_lower = clean_ans.lower().rstrip(".!?,")
    non_answers = {
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "none", "n/a", "na", "no", "yes", "idk", "i don't know", "i dont know",
        "dont know", "don't know", "no idea", "nothing", "skip", ".", "?", "abc", "xyz", "pass", "nil", "null"
    }
    if clean_lower in non_answers or len(clean_ans) < 2:
        return {
            "score": 0.0,
            "correctness": "incorrect",
            "confidence": "high",
            "feedback": f"The response '{clean_ans}' is an invalid or uninformative answer.",
            "covered_concepts": [],
            "missing_concepts": key_concepts or [],
            "rationale": "No relevant technical content or explanation provided.",
            "model_answer": reference_answer or "Provide a clear technical explanation addressing the core question concepts.",
            "engine": f"custom-{model_name}" if model_name else ("gemini" if api_key.startswith("AIza") else f"openai-{OPENAI_MODEL}")
        }

    effective_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
    if not effective_key and not base_url:
        raise ApiError("AI configuration required. Please enter a Cloud API Key or configure a Local AI Model URL.")

    instruction = (
        "CRITICAL EVALUATION RULES:\n"
        "- You are a strict academic examiner grading a viva exam answer.\n"
        "- If the student answer is completely wrong, irrelevant, a single number/symbol, or a refusal ('0', 'idk', 'no', 'n/a'), award a score of 0 and set correctness to 'incorrect'. DO NOT award partial credit for non-answers or single digits.\n"
        "- Evaluate valid student answers strictly by core technical meaning and conceptual accuracy.\n\n"
        "Explicit Marking Rubric:\n"
        "- Concept Precision (20%): Accuracy of terminology and definitions.\n"
        "- Explanation Clarity (20%): Structure, reasoning flow, and avoidance of vague words.\n"
        "- Evidence & Examples (20%): Mentioning concrete scenarios, code snippets, or facts from the study material.\n"
        "- Keyword/Key Concept Coverage (40%): Addressing key concepts in the reference answer/material.\n\n"
        f"Give a fair score between 0 and {max_marks}. Use the accepted answer and study material when they exist.\n"
        "Return a JSON object with exactly: score (number), correctness (correct|partially_correct|incorrect), "
        "confidence (low|medium|high), feedback (string), covered_concepts (array of strings), "
        "missing_concepts (array of strings), rationale (string), and model_answer (string representing a suggested stronger answer)."
    )
    
    payload = {
        "question": question,
        "student_answer": answer,
        "accepted_answer": reference_answer or None,
        "key_concepts": key_concepts or [],
        "maximum_marks": max_marks,
    }
    if material:
        payload["study_material"] = material

    result = ask_ai(instruction, payload, max_tokens=1500, api_key=api_key, base_url=base_url, model_name=model_name)

    if not isinstance(result, dict):
        raise ApiError("AI service returned an invalid evaluation structure.")

    try:
        score = round(float(result.get("score", 0)), 2)
    except (TypeError, ValueError):
        score = 0.0
    result["score"] = max(0, min(float(max_marks), score))
    result["correctness"] = result.get("correctness") if result.get("correctness") in {"correct", "partially_correct", "incorrect"} else "partially_correct"
    result["confidence"] = result.get("confidence") if result.get("confidence") in {"low", "medium", "high"} else "medium"
    for name in ("covered_concepts", "missing_concepts"):
        values = result.get(name, [])
        result[name] = [clean_text(value, 200) for value in values[:12]] if isinstance(values, list) else []
    result["feedback"] = clean_text(result.get("feedback"), 3000)
    result["rationale"] = clean_text(result.get("rationale"), 3000)
    result["model_answer"] = clean_text(result.get("model_answer", result.get("feedback", "")), 4000)
    result["engine"] = f"custom-{model_name}" if model_name else ("gemini" if api_key.startswith("AIza") else f"openai-{OPENAI_MODEL}")
    return result


def extract_material(file_name: str, mime_type: str, raw: bytes) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in {".txt", ".md", ".csv"} or mime_type.startswith("text/"):
        return raw.decode("utf-8", errors="replace")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as document:
                root = ElementTree.fromstring(document.read("word/document.xml"))
            return " ".join(text.strip() for text in root.itertext() if text.strip())
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise ApiError("This DOCX file could not be read.") from error
    if suffix == ".pdf" or mime_type == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ApiError("PDF support needs pypdf. Install dependencies with: py -3 -m pip install -r requirements.txt", HTTPStatus.SERVICE_UNAVAILABLE) from error
        try:
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as error:
            raise ApiError("This PDF could not be read. Try a text-based PDF or upload a DOCX/TXT file.") from error
    raise ApiError("Upload a TXT, Markdown, CSV, DOCX, or PDF study file.")


def assessment_from_row(conn: sqlite3.Connection, row: sqlite3.Row, include_questions: bool = True) -> dict:
    assessment = dict(row)
    assessment["student_fields"] = parse_json(assessment.pop("student_fields_json"), [])
    assessment["show_results"] = bool(assessment["show_results"])
    assessment["question_count"] = {"mode": assessment.pop("question_count_mode"), "min": assessment.pop("question_count_min"), "max": assessment.pop("question_count_max")}
    if include_questions:
        questions = conn.execute(
            "SELECT id, question_text, reference_answer, marks, position FROM assessment_questions WHERE assessment_id = ? ORDER BY position",
            (assessment["id"],),
        ).fetchall()
        assessment["questions"] = [
            {"id": item["id"], "question": item["question_text"], "reference_answer": item["reference_answer"], "marks": item["marks"], "position": item["position"]}
            for item in questions
        ]
    return assessment


def assessment_share(conn: sqlite3.Connection, assessment_id: int) -> dict | None:
    row = conn.execute("SELECT token, expires_at, is_active FROM share_links WHERE assessment_id = ?", (assessment_id,)).fetchone()
    if not row:
        return None
    return {"token": row["token"], "url": f"/viva/{row['token']}", "expires_at": row["expires_at"], "is_active": bool(row["is_active"])}


def get_public_link(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT s.*, a.title, a.subject, a.instructions, a.duration_minutes, a.question_count_mode,
               a.question_count_min, a.question_count_max, a.student_fields_json, a.show_results, a.question_ordering, a.status
        FROM share_links s JOIN assessments a ON a.id = s.assessment_id WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if not row or not row["is_active"] or row["status"] != "published":
        raise ApiError("This viva link is unavailable.", HTTPStatus.NOT_FOUND)
    if row["expires_at"] and row["expires_at"] < now():
        raise ApiError("This viva link has expired.", HTTPStatus.GONE)
    return row


class VivaHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("[Viva]", format % args)

    def send_json(self, payload, status: int = HTTPStatus.OK, headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, error: ApiError):
        self.send_json({"error": error.message}, error.status)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("Invalid request length.")
        if length > MAX_UPLOAD_BYTES * 2:
            raise ApiError("Request is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError("Invalid JSON request.") from error
        if not isinstance(payload, dict):
            raise ApiError("Request body must be a JSON object.")
        return payload

    def cookies(self) -> SimpleCookie:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return cookie

    def teacher(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        token_str = None
        try:
            token_obj = self.cookies().get("viva_teacher_session")
            if token_obj and token_obj.value:
                token_str = token_obj.value
        except Exception:
            pass

        # Regex fallback in case SimpleCookie failed due to third-party cookies in header
        if not token_str:
            cookie_header = self.headers.get("Cookie", "")
            match = re.search(r"(?:^|;\s*)viva_teacher_session=([^;]+)", cookie_header)
            if match:
                token_str = match.group(1)

        if not token_str:
            return None

        row = conn.execute(
            "SELECT t.*, s.created_at AS session_created_at FROM teachers t JOIN teacher_sessions s ON s.teacher_id = t.id WHERE s.id = ?",
            (token_str,),
        ).fetchone()
        if not row:
            return None

        # Server-side session expiry: reject sessions older than 14 days
        try:
            session_created = row["session_created_at"]
            session_ts = datetime.fromisoformat(session_created)
            if session_ts.tzinfo is None:
                session_ts = session_ts.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - session_ts > timedelta(days=14):
                conn.execute("DELETE FROM teacher_sessions WHERE id = ?", (token_str,))
                return None
        except Exception:
            pass
        return row

    def require_teacher(self, conn: sqlite3.Connection) -> sqlite3.Row:
        teacher = self.teacher(conn)
        if not teacher:
            raise ApiError("Please sign in as a teacher.", HTTPStatus.UNAUTHORIZED)
        return teacher

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                return self.handle_get_api(parsed)
            return self.serve_page(parsed.path)
        except ApiError as error:
            self.send_error_json(error)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception:
            try:
                self.send_json({"error": "Unexpected server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def do_POST(self):
        self.handle_mutation("POST")

    def do_PUT(self):
        self.handle_mutation("PUT")

    def do_DELETE(self):
        self.handle_mutation("DELETE")

    def handle_mutation(self, method: str):
        try:
            parsed = urlparse(self.path)
            payload = self.read_json() if method != "DELETE" or self.headers.get("Content-Length") else {}
            if not parsed.path.startswith("/api/"):
                raise ApiError("Not found.", HTTPStatus.NOT_FOUND)
            self.handle_mutation_api(method, parsed, payload)
        except ApiError as error:
            self.send_error_json(error)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception:
            try:
                self.send_json({"error": "Unexpected server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def handle_get_api(self, parsed):
        path = parsed.path
        params = parse_qs(parsed.query)
        with database() as conn:
            if path == "/api/health":
                server_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
                user_key = bool((self.headers.get("X-Api-Key") or "").strip())
                return self.send_json({"ai_configured": server_key or user_key, "model": OPENAI_MODEL, "key_source": "server" if server_key else "user" if user_key else "none"})
            if path == "/api/auth/me":
                teacher = self.teacher(conn)
                return self.send_json({"teacher": {"id": teacher["id"], "email": teacher["email"], "display_name": teacher["display_name"]} if teacher else None, "setup_required": conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0})
            if path == "/api/teacher/settings":
                teacher = self.require_teacher(conn)
                settings = parse_json(teacher["api_settings_json"], {})
                return self.send_json({"settings": settings})
            if path == "/api/library/materials":
                owner_key = clean_text(params.get("owner_key", [""])[0], 120)
                if not owner_key:
                    return self.send_json({"materials": []})
                items = conn.execute("SELECT id, file_name, file_type, created_at, length(extracted_text) AS character_count FROM study_materials WHERE owner_key = ? ORDER BY id DESC", (owner_key,)).fetchall()
                return self.send_json({"materials": [dict(item) for item in items]})

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)", path)
            if match:
                teacher = self.require_teacher(conn)
                assessment = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (int(match.group(1)), teacher["id"])).fetchone()
                if not assessment:
                    raise ApiError("Viva not found.", HTTPStatus.NOT_FOUND)
                data = assessment_from_row(conn, assessment)
                data["share"] = assessment_share(conn, data["id"])
                return self.send_json({"assessment": data})

            if path == "/api/teacher/assessments":
                teacher = self.require_teacher(conn)
                rows = conn.execute(
                    """
                    SELECT a.*, COUNT(DISTINCT at.id) AS attempt_count,
                           COUNT(DISTINCT CASE WHEN at.state = 'submitted' THEN at.id END) AS submitted_count
                    FROM assessments a LEFT JOIN attempts at ON at.assessment_id = a.id
                    WHERE a.teacher_id = ? GROUP BY a.id ORDER BY a.updated_at DESC
                    """,
                    (teacher["id"],),
                ).fetchall()
                items = []
                for row in rows:
                    item = assessment_from_row(conn, row, include_questions=False)
                    item["attempt_count"] = row["attempt_count"]
                    item["submitted_count"] = row["submitted_count"]
                    item["share"] = assessment_share(conn, item["id"])
                    items.append(item)
                return self.send_json({"assessments": items})

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/results", path)
            if match:
                return self.teacher_results(conn, int(match.group(1)))
            match = re.fullmatch(r"/api/teacher/attempts/(\d+)", path)
            if match:
                return self.teacher_attempt(conn, int(match.group(1)))
            match = re.fullmatch(r"/api/public/viva/([A-Za-z0-9_-]+)", path)
            if match:
                link = get_public_link(conn, match.group(1))
                return self.send_json({
                    "viva": {
                        "title": link["title"], "subject": link["subject"], "instructions": link["instructions"],
                        "duration_minutes": link["duration_minutes"], "question_count": {"mode": link["question_count_mode"], "min": link["question_count_min"], "max": link["question_count_max"]},
                        "student_fields": parse_json(link["student_fields_json"], []), "pin_required": bool(link["pin_hash"]),
                    }
                })
            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)", path)
            if match:
                return self.public_attempt(conn, match.group(1))
            raise ApiError("Not found.", HTTPStatus.NOT_FOUND)

    def handle_mutation_api(self, method: str, parsed, payload: dict):
        path = parsed.path
        with database() as conn:
            if method == "POST" and path in ("/api/auth/setup", "/api/auth/login"):
                client_ip = self.client_address[0] if self.client_address else "unknown"
                check_login_rate(client_ip)
                email = clean_text(payload.get("email"), 160).lower()
                password = str(payload.get("password", ""))
                display_name = clean_text(payload.get("display_name"), 80) or email.split("@")[0].capitalize()
                
                if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    raise ApiError("Please enter a valid email address.")
                if len(password) < 6:
                    raise ApiError("Password must be at least 6 characters.")
                
                teacher = conn.execute("SELECT * FROM teachers WHERE email = ?", (email,)).fetchone()
                if not teacher:
                    digest, salt = password_record(password)
                    cursor = conn.execute(
                        "INSERT INTO teachers (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                        (email, display_name, digest, salt, now())
                    )
                    teacher = conn.execute("SELECT * FROM teachers WHERE id = ?", (cursor.lastrowid,)).fetchone()
                else:
                    if not valid_password(password, teacher["password_hash"], teacher["password_salt"]):
                        record_failed_login(client_ip)
                        raise ApiError("Invalid email or password.", HTTPStatus.UNAUTHORIZED)
                
                clear_login_rate(client_ip)
                return self.start_teacher_session(conn, teacher)
            if method == "POST" and path == "/api/auth/logout":
                token_str = None
                try:
                    token_obj = self.cookies().get("viva_teacher_session")
                    if token_obj and token_obj.value:
                        token_str = token_obj.value
                except Exception:
                    pass
                if not token_str:
                    cookie_header = self.headers.get("Cookie", "")
                    match = re.search(r"(?:^|;\s*)viva_teacher_session=([^;]+)", cookie_header)
                    if match:
                        token_str = match.group(1)
                if token_str:
                    conn.execute("DELETE FROM teacher_sessions WHERE id = ?", (token_str,))
                return self.send_json({"ok": True}, headers={"Set-Cookie": "viva_teacher_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})

            if method == "POST" and path == "/api/generate-questions":
                subject = clean_text(payload.get("subject"), 120)
                level = clean_text(payload.get("level"), 20).lower() or "medium"
                api_key = clean_text(payload.get("api_key"), 200)
                
                q_json_path = DATA_DIR / "questions.json"
                questions = []
                if q_json_path.is_file():
                    try:
                        data = json.loads(q_json_path.read_text(encoding="utf-8"))
                        subj_data = data.get(subject)
                        if not subj_data:
                            for k, v in data.items():
                                if subject.lower() in k.lower():
                                    subj_data = v
                                    break
                        if subj_data:
                            questions = subj_data[:6]
                    except Exception:
                        pass
                        
                if not questions and (api_key or os.environ.get("OPENAI_API_KEY", "").strip()):
                    try:
                        res = ask_ai(
                            f"Create 5 {level}-level viva interview questions about {subject}. Return JSON array of objects with id, question, expected_keywords (array), model_answer.",
                            {"subject": subject, "level": level},
                            api_key=api_key
                        )
                        if isinstance(res, list):
                            questions = res
                    except Exception:
                        pass
                        
                if not questions:
                    questions = [
                        {"id": "q-1", "question": f"Explain the fundamental definition and scope of {subject}.", "expected_keywords": [subject.lower(), "definition", "concept"], "model_answer": f"{subject} involves core principles and applications in software and system design."},
                        {"id": "q-2", "question": f"What are the primary use cases and advantages of using {subject}?", "expected_keywords": ["advantages", "use cases", "performance"], "model_answer": f"{subject} provides structured efficiency, scalability, and modular implementation."},
                        {"id": "q-3", "question": f"Describe key limitations or challenges when implementing {subject}.", "expected_keywords": ["limitations", "challenges", "tradeoffs"], "model_answer": "Key challenges include complexity management, resource overhead, and proper error handling."}
                    ]
                return self.send_json({"questions": questions, "engine": "ai" if (api_key or os.environ.get("OPENAI_API_KEY", "").strip()) else "question-bank"})

            if method == "POST" and path == "/api/evaluate":
                question = clean_text(payload.get("question"), 3000)
                answer = clean_text(payload.get("answer"), 12000)
                expected_keywords = payload.get("expected_keywords", [])
                model_answer = clean_text(payload.get("model_answer"), 4000)
                api_key = clean_text(payload.get("api_key"), 200)
                
                res = evaluate_answer(question, answer, 100, reference_answer=model_answer, key_concepts=expected_keywords, api_key=api_key)
                res["strengths"] = res.get("covered_concepts") or ["Covered key terms"]
                res["gaps"] = res.get("missing_concepts") or ["No major gaps"]
                res["readiness"] = "Excellent" if res["score"] >= 80 else ("Good" if res["score"] >= 60 else "Needs Practice")
                res["quality_band"] = f"Rubric Score: {res['score']}%"
                return self.send_json(res)

            if method == "POST" and path == "/api/report":
                candidate = clean_text(payload.get("candidate"), 120) or "Student"
                subject = clean_text(payload.get("subject"), 120) or "General"
                evaluations = payload.get("evaluations", [])
                
                scores = [float(e.get("score", 0)) for e in evaluations if isinstance(e, dict)]
                avg_score = round(sum(scores) / len(scores), 1) if scores else 0
                readiness = "Excellent" if avg_score >= 80 else ("Good" if avg_score >= 60 else "Developing")
                
                weak_topics = []
                for e in evaluations:
                    if isinstance(e, dict) and float(e.get("score", 0)) < 60:
                        q_text = e.get("question", "")
                        if q_text:
                            weak_topics.append(q_text[:80])
                            
                return self.send_json({
                    "summary": f"Viva report generated for {candidate} in {subject}.",
                    "readiness": readiness,
                    "average_score": avg_score,
                    "professor_note": f"Candidate demonstrated {readiness.lower()} understanding. Focus on clarifying missing concepts in weaker topics.",
                    "weak_topics": weak_topics[:5] or ["None detected"]
                })

            if method == "POST" and path == "/api/teacher/settings":
                teacher = self.require_teacher(conn)
                settings = {
                    "api_key": str(payload.get("api_key", "")).strip(),
                    "base_url": str(payload.get("base_url", "")).strip(),
                    "model_name": str(payload.get("model_name", "")).strip(),
                }
                conn.execute("UPDATE teachers SET api_settings_json = ? WHERE id = ?", (json.dumps(settings), teacher["id"]))
                conn.commit()
                return self.send_json({"saved": True})
            if method == "POST" and path == "/api/library/materials":
                return self.upload_material(conn, payload)
            match = re.fullmatch(r"/api/library/materials/(\d+)", path)
            if method == "DELETE" and match:
                owner_key = clean_text(parse_qs(parsed.query).get("owner_key", [""])[0], 120)
                deleted = conn.execute("DELETE FROM study_materials WHERE id = ? AND owner_key = ?", (int(match.group(1)), owner_key)).rowcount
                if not deleted:
                    raise ApiError("Study material not found.", HTTPStatus.NOT_FOUND)
                return self.send_json({"ok": True})
            if method == "POST" and path == "/api/library/generate":
                return self.generate_library_set(conn, payload)
            if method == "POST" and path == "/api/library/evaluate":
                return self.evaluate_library_answer(payload)

            if method == "POST" and path == "/api/teacher/assessments":
                teacher = self.require_teacher(conn)
                return self.create_assessment(conn, teacher, payload)
            match = re.fullmatch(r"/api/teacher/assessments/(\d+)", path)
            if method == "PUT" and match:
                teacher = self.require_teacher(conn)
                return self.update_assessment(conn, teacher, int(match.group(1)), payload)
            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/publish", path)
            if method == "POST" and match:
                teacher = self.require_teacher(conn)
                return self.publish_assessment(conn, teacher, int(match.group(1)), payload)
            match = re.fullmatch(r"/api/teacher/answers/(\d+)/override", path)
            if method == "POST" and match:
                teacher = self.require_teacher(conn)
                return self.override_mark(conn, teacher, int(match.group(1)), payload)

            match = re.fullmatch(r"/api/public/viva/([A-Za-z0-9_-]+)/start", path)
            if method == "POST" and match:
                return self.start_public_attempt(conn, match.group(1), payload)
            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)/answers", path)
            if method == "POST" and match:
                return self.save_public_answer(conn, match.group(1), payload)
            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)/submit", path)
            if method == "POST" and match:
                return self.submit_public_attempt(conn, match.group(1))
            raise ApiError("Not found.", HTTPStatus.NOT_FOUND)

    def create_teacher_session(self, conn: sqlite3.Connection, payload: dict):
        email = clean_text(payload.get("email"), 160).lower()
        display_name = clean_text(payload.get("display_name"), 80) or email.split("@")[0]
        password = str(payload.get("password", ""))
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ApiError("Enter a valid email address.")
        if not display_name:
            raise ApiError("Enter your name.")
        if len(password) < 6:
            raise ApiError("Password must be at least 6 characters.")
        digest, salt = password_record(password)
        cursor = conn.execute("INSERT INTO teachers (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)", (email, display_name, digest, salt, now()))
        teacher = conn.execute("SELECT * FROM teachers WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self.start_teacher_session(conn, teacher)

    def start_teacher_session(self, conn: sqlite3.Connection, teacher: sqlite3.Row):
        token = random_token()
        conn.execute("INSERT INTO teacher_sessions (id, teacher_id, created_at) VALUES (?, ?, ?)", (token, teacher["id"], now()))
        self.send_json({"teacher": {"id": teacher["id"], "email": teacher["email"], "display_name": teacher["display_name"]}}, headers={"Set-Cookie": f"viva_teacher_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=1209600"})

    def upload_material(self, conn: sqlite3.Connection, payload: dict):
        owner_key = clean_text(payload.get("owner_key"), 120)
        file_name = clean_text(payload.get("file_name"), 180)
        mime_type = clean_text(payload.get("mime_type"), 120)
        encoded = payload.get("content_base64", "")
        if not owner_key or not file_name or not isinstance(encoded, str):
            raise ApiError("Study file data is incomplete.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ApiError("Study file could not be read.") from error
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise ApiError("Upload a file smaller than 8 MB.")
        text = clean_text(extract_material(file_name, mime_type, raw), MAX_MATERIAL_TEXT)
        if len(text) < 40:
            raise ApiError("We could not extract enough readable text from this file.")
        cursor = conn.execute("INSERT INTO study_materials (owner_key, file_name, file_type, extracted_text, created_at) VALUES (?, ?, ?, ?, ?)", (owner_key, file_name, mime_type or Path(file_name).suffix, text, now()))
        return self.send_json({"material": {"id": cursor.lastrowid, "file_name": file_name, "file_type": mime_type, "character_count": len(text)}})

    def generate_library_set(self, conn: sqlite3.Connection, payload: dict):
        owner_key = clean_text(payload.get("owner_key"), 120)
        ids = payload.get("material_ids", [])
        material_text = clean_text(payload.get("material"), MAX_MATERIAL_TEXT)

        if not material_text:
            if not owner_key or not isinstance(ids, list) or not ids:
                raise ApiError("Select one or more uploaded study materials or paste material text.")
            try:
                ids = [int(item) for item in ids[:12]]
            except (TypeError, ValueError) as error:
                raise ApiError("Study material selection is invalid.") from error
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(f"SELECT extracted_text FROM study_materials WHERE owner_key = ? AND id IN ({placeholders})", [owner_key, *ids]).fetchall()
            if not rows:
                raise ApiError("Selected study materials were not found.", HTTPStatus.NOT_FOUND)
            material_text = clean_text("\n\n".join(row["extracted_text"] for row in rows), MAX_MATERIAL_TEXT)

        payload["material"] = material_text
        payload["_api_key"] = (self.headers.get("X-Api-Key") or "").strip()
        payload["_base_url"] = (self.headers.get("X-Base-Url") or "").strip()
        payload["_model_name"] = (self.headers.get("X-Model-Name") or "").strip()
        return self.send_json({"questions": generate_practice_questions(payload), "engine": f"custom-model"})

    def evaluate_library_answer(self, payload: dict):
        question = clean_text(payload.get("question"), 3000)
        answer = clean_text(payload.get("answer"), 12000)
        material = clean_text(payload.get("material"), MAX_MATERIAL_TEXT)
        reference_answer = clean_text(payload.get("reference_answer"), 8000)
        key_concepts = payload.get("key_concepts", []) if isinstance(payload.get("key_concepts"), list) else []
        # Pass user-supplied AI settings through
        user_key = (self.headers.get("X-Api-Key") or "").strip()
        base_url = (self.headers.get("X-Base-Url") or "").strip()
        model_name = (self.headers.get("X-Model-Name") or "").strip()

        result = evaluate_answer(
            question=question,
            answer=answer,
            max_marks=100,
            reference_answer=reference_answer,
            key_concepts=key_concepts,
            material=material,
            api_key=user_key,
            base_url=base_url,
            model_name=model_name
        )
        return self.send_json({"evaluation": result})

    def create_assessment(self, conn: sqlite3.Connection, teacher: sqlite3.Row, payload: dict):
        data = assessment_payload(payload)
        timestamp = now()
        cursor = conn.execute(
            """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, question_ordering, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
            (teacher["id"], data["title"], data["subject"], data["instructions"], data["duration"], data["mode"], data["minimum"], data["maximum"], json.dumps(data["student_fields"]), data["show_results"], data["question_ordering"], timestamp, timestamp),
        )
        assessment_id = cursor.lastrowid
        self.store_questions(conn, assessment_id, data["questions"])
        return self.send_json({"assessment_id": assessment_id}, HTTPStatus.CREATED)

    def update_assessment(self, conn: sqlite3.Connection, teacher: sqlite3.Row, assessment_id: int, payload: dict):
        existing = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not existing:
            raise ApiError("Viva not found.", HTTPStatus.NOT_FOUND)
        data = assessment_payload(payload)
        conn.execute(
            """UPDATE assessments SET title=?, subject=?, instructions=?, duration_minutes=?, question_count_mode=?, question_count_min=?, question_count_max=?, student_fields_json=?, show_results=?, question_ordering=?, updated_at=? WHERE id=?""",
            (data["title"], data["subject"], data["instructions"], data["duration"], data["mode"], data["minimum"], data["maximum"], json.dumps(data["student_fields"]), data["show_results"], data["question_ordering"], now(), assessment_id),
        )
        conn.execute("DELETE FROM assessment_questions WHERE assessment_id = ?", (assessment_id,))
        self.store_questions(conn, assessment_id, data["questions"])
        return self.send_json({"assessment_id": assessment_id, "updated": True})

    def store_questions(self, conn: sqlite3.Connection, assessment_id: int, questions: list[dict]):
        conn.executemany("INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, ?, ?, ?, ?)", [(assessment_id, item["question"], item["reference_answer"], item["marks"], index) for index, item in enumerate(questions, start=1)])

    def publish_assessment(self, conn: sqlite3.Connection, teacher: sqlite3.Row, assessment_id: int, payload: dict):
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not assessment:
            raise ApiError("Viva not found.", HTTPStatus.NOT_FOUND)
        question_total = conn.execute("SELECT COUNT(*) FROM assessment_questions WHERE assessment_id = ?", (assessment_id,)).fetchone()[0]
        if question_total < assessment["question_count_max"]:
            raise ApiError("Add enough questions for the selected question-count setting.")
        
        expires_at = clean_text(payload.get("expires_at"), 40) or None
        pin = clean_text(payload.get("pin"), 32)
        if pin and len(pin) < 4:
            raise ApiError("Use a PIN with at least 4 characters.")
        pin_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest() if pin else ""
        
        is_active = 0 if payload.get("is_active") is False or payload.get("is_active") == 0 else 1
        regenerate = bool(payload.get("regenerate_token"))
        
        existing = conn.execute("SELECT * FROM share_links WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if existing:
            token = random_token() if regenerate else existing["token"]
            conn.execute("UPDATE share_links SET is_active=?, expires_at=?, pin_hash=?, token=? WHERE assessment_id=?", (is_active, expires_at, pin_hash, token, assessment_id))
        else:
            token = random_token()
            conn.execute("INSERT INTO share_links (assessment_id, token, pin_hash, expires_at, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)", (assessment_id, token, pin_hash, expires_at, is_active, now()))
        conn.execute("UPDATE assessments SET status='published', updated_at=? WHERE id=?", (now(), assessment_id))
        return self.send_json({"share": {"token": token, "url": f"/viva/{token}", "expires_at": expires_at, "is_active": bool(is_active)}})

    def start_public_attempt(self, conn: sqlite3.Connection, share_token: str, payload: dict):
        link = get_public_link(conn, share_token)
        if link["pin_hash"]:
            supplied = clean_text(payload.get("pin"), 32)
            if not hmac.compare_digest(hashlib.sha256(supplied.encode("utf-8")).hexdigest(), link["pin_hash"]):
                raise ApiError("The viva PIN is incorrect.", HTTPStatus.UNAUTHORIZED)
        fields = parse_json(link["student_fields_json"], [])
        student_data = payload.get("student_data") if isinstance(payload.get("student_data"), dict) else {}
        cleaned_data = {}
        for field in fields:
            value = clean_text(student_data.get(field["key"]), 200)
            if field.get("required") and not value:
                raise ApiError(f"{field['label']} is required.")
            cleaned_data[field["key"]] = value
        try:
            count = int(payload.get("question_count", link["question_count_min"]))
        except (TypeError, ValueError):
            raise ApiError("Question count is invalid.")
        if link["question_count_mode"] == "fixed":
            count = link["question_count_min"]
        if not link["question_count_min"] <= count <= link["question_count_max"]:
            raise ApiError("Choose a valid number of questions.")
        all_questions = conn.execute("SELECT id FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (link["assessment_id"],)).fetchall()
        question_ids = [row["id"] for row in all_questions]
        if len(question_ids) < count:
            raise ApiError("This viva is missing questions. Ask your teacher to update it.")
        
        # Check question ordering settings
        ordering = link["question_ordering"] if "question_ordering" in link.keys() else "fixed"
        if ordering == "shuffled":
            import random
            random.shuffle(question_ids)
            selected_ids = question_ids[:count]
        elif ordering == "random":
            import random
            selected_ids = random.sample(question_ids, count)
        else: # fixed
            selected_ids = question_ids[:count]

        access_token = random_token()
        conn.execute("INSERT INTO attempts (assessment_id, share_link_id, access_token, student_data_json, selected_question_ids_json, state, started_at) VALUES (?, ?, ?, ?, ?, 'in_progress', ?)", (link["assessment_id"], link["id"], access_token, json.dumps(cleaned_data), json.dumps(selected_ids), now()))
        return self.send_json({"attempt_token": access_token, "exam_url": f"/viva/{share_token}/exam?attempt={access_token}"}, HTTPStatus.CREATED)

    def public_attempt(self, conn: sqlite3.Connection, attempt_token: str):
        attempt = conn.execute("SELECT a.*, ass.title, ass.subject, ass.instructions, ass.duration_minutes, ass.show_results FROM attempts a JOIN assessments ass ON ass.id=a.assessment_id WHERE a.access_token=?", (attempt_token,)).fetchone()
        if not attempt:
            raise ApiError("Viva attempt not found.", HTTPStatus.NOT_FOUND)
        ids = parse_json(attempt["selected_question_ids_json"], [])
        if not ids:
            raise ApiError("This attempt has no assigned questions.")
        placeholders = ",".join("?" for _ in ids)
        questions = conn.execute(f"SELECT id, question_text, marks FROM assessment_questions WHERE id IN ({placeholders})", ids).fetchall()
        by_id = {row["id"]: row for row in questions}
        answers = {row["question_id"]: row for row in conn.execute("SELECT question_id, answer_text, ai_score, final_score, evaluation_json FROM attempt_answers WHERE attempt_id=?", (attempt["id"],)).fetchall()}
        payload_questions = []
        show_results = bool(attempt["show_results"])
        for question_id in ids:
            question = by_id.get(question_id)
            if not question:
                continue
            answer = answers.get(question_id)
            q_data = {
                "id": question["id"],
                "question": question["question_text"],
                "marks": question["marks"],
                "answer": answer["answer_text"] if answer else "",
                "evaluated": bool(answer)
            }
            if show_results and answer:
                q_data["ai_score"] = answer["ai_score"]
                q_data["final_score"] = answer["final_score"]
                q_data["evaluation"] = parse_json(answer["evaluation_json"], {})
            payload_questions.append(q_data)
        return self.send_json({"attempt": {"state": attempt["state"], "title": attempt["title"], "subject": attempt["subject"], "instructions": attempt["instructions"], "duration_minutes": attempt["duration_minutes"], "student": parse_json(attempt["student_data_json"], {}), "show_results": show_results, "questions": payload_questions}})

    def save_public_answer(self, conn: sqlite3.Connection, attempt_token: str, payload: dict):
        attempt = conn.execute("SELECT * FROM attempts WHERE access_token = ?", (attempt_token,)).fetchone()
        if not attempt or attempt["state"] != "in_progress":
            raise ApiError("This viva attempt is no longer available.", HTTPStatus.CONFLICT)
        try:
            question_id = int(payload.get("question_id"))
        except (TypeError, ValueError):
            raise ApiError("Question is invalid.")
        selected_ids = parse_json(attempt["selected_question_ids_json"], [])
        if question_id not in selected_ids:
            raise ApiError("This question is not assigned to your viva.", HTTPStatus.FORBIDDEN)
        question = conn.execute("SELECT * FROM assessment_questions WHERE id = ? AND assessment_id = ?", (question_id, attempt["assessment_id"])).fetchone()
        if not question:
            raise ApiError("Question not found.", HTTPStatus.NOT_FOUND)
        answer = clean_text(payload.get("answer"), 12000)
        result = {
            "score": 0,
            "correctness": "pending",
            "confidence": "low",
            "feedback": "Pending evaluation...",
            "covered_concepts": [],
            "missing_concepts": [],
            "rationale": "Evaluation will occur upon exam submission."
        }

        conn.execute(
            """INSERT INTO attempt_answers (attempt_id, question_id, answer_text, ai_score, final_score, evaluation_json, evaluated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(attempt_id, question_id) DO UPDATE SET answer_text=excluded.answer_text, ai_score=excluded.ai_score, final_score=excluded.final_score, evaluation_json=excluded.evaluation_json, override_reason='', evaluated_at=excluded.evaluated_at""",
            (attempt["id"], question_id, answer, 0, 0, json.dumps(result), now()),
        )
        conn.commit()
        return self.send_json({"saved": True})

    def submit_public_attempt(self, conn: sqlite3.Connection, attempt_token: str):
        attempt = conn.execute("SELECT * FROM attempts WHERE access_token = ?", (attempt_token,)).fetchone()
        if not attempt:
            raise ApiError("Viva attempt not found.", HTTPStatus.NOT_FOUND)
        if attempt["state"] == "submitted":
            return self.send_json({"submitted": True, "result_url": f"/viva/complete?attempt={attempt_token}"})
        question_ids = parse_json(attempt["selected_question_ids_json"], [])
        existing_q_ids = {row["question_id"] for row in conn.execute("SELECT question_id FROM attempt_answers WHERE attempt_id = ?", (attempt["id"],)).fetchall()}
        for qid in question_ids:
            if qid not in existing_q_ids:
                empty_res = {
                    "score": 0,
                    "correctness": "incorrect",
                    "confidence": "high",
                    "feedback": "No response was submitted for this question.",
                    "covered_concepts": [],
                    "missing_concepts": [],
                    "rationale": "Blank answer."
                }
                conn.execute(
                    "INSERT INTO attempt_answers (attempt_id, question_id, answer_text, ai_score, final_score, evaluation_json, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (attempt["id"], qid, "", 0, 0, json.dumps(empty_res), now())
                )
        conn.commit()
            
        # Retrieve the teacher who created this assessment
        teacher_row = conn.execute("SELECT t.api_settings_json FROM assessments a JOIN teachers t ON t.id = a.teacher_id WHERE a.id = ?", (attempt["assessment_id"],)).fetchone()
        teacher_settings = parse_json(teacher_row["api_settings_json"], {}) if teacher_row else {}
        
        user_key = (self.headers.get("X-Api-Key") or "").strip()
        user_base_url = (self.headers.get("X-Base-Url") or "").strip()
        user_model_name = (self.headers.get("X-Model-Name") or "").strip()

        effective_key = teacher_settings.get("api_key", "").strip() or user_key or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = teacher_settings.get("base_url", "").strip() or user_base_url
        model_name = teacher_settings.get("model_name", "").strip() or user_model_name
        
        answers_data = conn.execute(
            """SELECT a.id, a.answer_text, q.question_text, q.marks, q.reference_answer 
               FROM attempt_answers a 
               JOIN assessment_questions q ON q.id = a.question_id 
               WHERE a.attempt_id = ?""", 
            (attempt["id"],)
        ).fetchall()
        
        def _evaluate_single(ans):
            if not ans["answer_text"].strip():
                return ans["id"], {
                    "score": 0, "correctness": "incorrect", "confidence": "high",
                    "feedback": "No response was submitted for this question.",
                    "covered_concepts": [], "missing_concepts": [], "rationale": "Blank answer submitted."
                }, 0
            
            try:
                result = evaluate_answer(
                    ans["question_text"], ans["answer_text"], ans["marks"], ans["reference_answer"], 
                    api_key=effective_key, base_url=base_url, model_name=model_name
                )
                needs_review = 1 if result.get("confidence") == "low" else 0
                return ans["id"], result, needs_review
            except Exception as e:
                res = {
                    "score": 0.0, "correctness": "incorrect", "confidence": "high",
                    "feedback": f"AI evaluation error: {str(e)}",
                    "covered_concepts": [], "missing_concepts": [],
                    "rationale": "Evaluation could not be performed due to AI error.",
                    "model_answer": ans["reference_answer"] or ""
                }
                return ans["id"], res, 1

        needs_review_overall = False
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_evaluate_single, dict(ans)) for ans in answers_data]
            for future in concurrent.futures.as_completed(futures):
                ans_id, result, needs_review = future.result()
                if needs_review:
                    needs_review_overall = True
                conn.execute(
                    """UPDATE attempt_answers SET ai_score=?, final_score=?, evaluation_json=?, evaluated_at=? WHERE id=?""",
                    (result["score"], result["score"], json.dumps(result), now(), ans_id)
                )

        if needs_review_overall:
            conn.execute("UPDATE attempts SET needs_review = 1 WHERE id = ?", (attempt["id"],))
            
        conn.execute("UPDATE attempts SET state='submitted', submitted_at=? WHERE id=?", (now(), attempt["id"]))
        conn.commit()
        return self.send_json({"submitted": True, "result_url": f"/viva/complete?attempt={attempt_token}"})

    def teacher_results(self, conn: sqlite3.Connection, assessment_id: int):
        teacher = self.require_teacher(conn)
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not assessment:
            raise ApiError("Viva not found.", HTTPStatus.NOT_FOUND)
        rows = conn.execute(
            """SELECT at.id, at.student_data_json, at.state, at.needs_review, at.started_at, at.submitted_at,
                      COALESCE(SUM(ans.ai_score), 0) AS ai_score, COALESCE(SUM(ans.final_score), 0) AS final_score,
                      COALESCE(SUM(q.marks), 0) AS max_marks
               FROM attempts at
               LEFT JOIN attempt_answers ans ON ans.attempt_id=at.id
               LEFT JOIN assessment_questions q ON q.id=ans.question_id
               WHERE at.assessment_id=? GROUP BY at.id ORDER BY at.submitted_at DESC, at.started_at DESC""",
            (assessment_id,),
        ).fetchall()
        students = []
        submitted_scores = []
        for row in rows:
            score_pct = round((row["final_score"] / row["max_marks"] * 100), 1) if row["max_marks"] else 0
            if row["state"] == "submitted":
                submitted_scores.append(score_pct)
            students.append({"attempt_id": row["id"], "student": parse_json(row["student_data_json"], {}), "state": row["state"], "needs_review": bool(row["needs_review"]), "started_at": row["started_at"], "submitted_at": row["submitted_at"], "ai_score": row["ai_score"], "final_score": row["final_score"], "max_marks": row["max_marks"], "percentage": score_pct})
        question_rows = conn.execute(
            """SELECT q.id, q.question_text, q.marks, COUNT(ans.id) AS response_count,
                      COALESCE(AVG(ans.final_score), 0) AS average_score
               FROM assessment_questions q LEFT JOIN attempt_answers ans ON ans.question_id=q.id
               WHERE q.assessment_id=? GROUP BY q.id ORDER BY q.position""",
            (assessment_id,),
        ).fetchall()
        return self.send_json({"assessment": assessment_from_row(conn, assessment, include_questions=False), "summary": {"students": len(rows), "submitted": sum(1 for row in rows if row["state"] == "submitted"), "average_percentage": round(sum(submitted_scores) / len(submitted_scores), 1) if submitted_scores else 0, "highest_percentage": max(submitted_scores) if submitted_scores else 0}, "students": students, "question_performance": [{"question": row["question_text"], "marks": row["marks"], "response_count": row["response_count"], "average_score": round(row["average_score"], 2)} for row in question_rows]})

    def teacher_attempt(self, conn: sqlite3.Connection, attempt_id: int):
        teacher = self.require_teacher(conn)
        attempt = conn.execute("SELECT at.*, ass.title FROM attempts at JOIN assessments ass ON ass.id=at.assessment_id WHERE at.id=? AND ass.teacher_id=?", (attempt_id, teacher["id"])).fetchone()
        if not attempt:
            raise ApiError("Student attempt not found.", HTTPStatus.NOT_FOUND)
        answers = conn.execute(
            """SELECT ans.*, q.question_text, q.reference_answer, q.marks
               FROM attempt_answers ans JOIN assessment_questions q ON q.id=ans.question_id
               WHERE ans.attempt_id=? ORDER BY q.position""",
            (attempt_id,),
        ).fetchall()
        return self.send_json({"attempt": {"id": attempt["id"], "title": attempt["title"], "student": parse_json(attempt["student_data_json"], {}), "state": attempt["state"], "started_at": attempt["started_at"], "submitted_at": attempt["submitted_at"], "answers": [{"answer_id": row["id"], "question": row["question_text"], "reference_answer": row["reference_answer"], "marks": row["marks"], "student_answer": row["answer_text"], "ai_score": row["ai_score"], "final_score": row["final_score"], "override_reason": row["override_reason"], "evaluation": parse_json(row["evaluation_json"], {})} for row in answers]}})

    def override_mark(self, conn: sqlite3.Connection, teacher: sqlite3.Row, answer_id: int, payload: dict):
        row = conn.execute("""SELECT ans.*, q.marks FROM attempt_answers ans JOIN attempts at ON at.id=ans.attempt_id JOIN assessments ass ON ass.id=at.assessment_id JOIN assessment_questions q ON q.id=ans.question_id WHERE ans.id=? AND ass.teacher_id=?""", (answer_id, teacher["id"])).fetchone()
        if not row:
            raise ApiError("Answer not found.", HTTPStatus.NOT_FOUND)
        try:
            mark = round(float(payload.get("mark")), 2)
        except (TypeError, ValueError):
            raise ApiError("Enter a valid mark.")
        reason = clean_text(payload.get("reason"), 1000)
        if not 0 <= mark <= row["marks"]:
            raise ApiError(f"Mark must be between 0 and {row['marks']}.")
        if not reason:
            raise ApiError("Add a reason for the mark change.")
        conn.execute("UPDATE attempt_answers SET final_score=?, override_reason=? WHERE id=?", (mark, reason, answer_id))
        conn.execute("UPDATE attempts SET needs_review=0 WHERE id=?", (row["attempt_id"],))
        return self.send_json({"answer_id": answer_id, "final_score": mark, "override_reason": reason})

    def serve_page(self, path: str):
        pages = {
            "/": "index.html",
            "/student": "student-dashboard.html",
            "/questions": "questions.html",
            "/teacher/login": "teacher-login.html",
            "/teacher": "teacher-dashboard.html",
            "/teacher/vivas/new": "teacher-builder.html",
            "/teacher/vivas/edit": "teacher-builder.html",
            "/teacher/vivas/share": "teacher-share.html",
            "/teacher/vivas/results": "teacher-results.html",
            "/teacher/vivas/student": "teacher-student.html",
        }
        if re.fullmatch(r"/viva/[A-Za-z0-9_-]+", path):
            return self.serve_file(STATIC_DIR / "viva-entry.html")
        if re.fullmatch(r"/viva/[A-Za-z0-9_-]+/exam", path):
            return self.serve_file(STATIC_DIR / "viva-exam.html")
        if path == "/viva/complete":
            return self.serve_file(STATIC_DIR / "viva-complete.html")
        if path in pages:
            return self.serve_file(STATIC_DIR / pages[path])
        safe = path.lstrip("/")
        return self.serve_file(ROOT / safe)

    def serve_file(self, path: Path):
        try:
            resolved = path.resolve()
            if ROOT.resolve() not in resolved.parents or not resolved.is_file():
                raise FileNotFoundError
            content = resolved.read_bytes()
        except (OSError, FileNotFoundError):
            return self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        content_type = {
            ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml"
        }.get(resolved.suffix.lower(), "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


init_database()


class WSGIHandlerAdapter(VivaHandler):
    def __init__(self, environ, start_response):
        self.environ = environ
        self.start_response_cb = start_response
        self.path = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            self.path += "?" + environ["QUERY_STRING"]
        self.command = environ.get("REQUEST_METHOD", "GET")
        self.headers = {}
        for k, v in environ.items():
            if k.startswith("HTTP_"):
                header_name = k[5:].replace("_", "-").title()
                self.headers[header_name] = v
            elif k in ("CONTENT_TYPE", "CONTENT_LENGTH"):
                header_name = k.replace("_", "-").title()
                self.headers[header_name] = v
        self.rfile = environ.get("wsgi.input")
        self.wfile = io.BytesIO()
        self.response_status_code = 200
        self.response_status_message = "OK"
        self.response_headers = []

    def send_response(self, code, message=None):
        self.response_status_code = code
        try:
            self.response_status_message = message or HTTPStatus(code).phrase
        except ValueError:
            self.response_status_message = "OK"

    def send_header(self, keyword, value):
        self.response_headers.append((keyword, str(value)))

    def end_headers(self):
        pass

    def log_message(self, format, *args):
        pass


def app(environ, start_response):
    adapter = WSGIHandlerAdapter(environ, start_response)
    method = adapter.command.upper()
    if method == "GET":
        adapter.do_GET()
    elif method == "POST":
        adapter.do_POST()
    elif method == "PUT":
        adapter.do_PUT()
    elif method == "DELETE":
        adapter.do_DELETE()
    elif method == "OPTIONS":
        adapter.do_OPTIONS()
    else:
        adapter.send_json({"error": "Method not allowed."}, HTTPStatus.METHOD_NOT_ALLOWED)

    status_str = f"{adapter.response_status_code} {adapter.response_status_message}"
    start_response(status_str, adapter.response_headers)
    return [adapter.wfile.getvalue()]


handler = app
application = app


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), VivaHandler)
    print(f"AI Viva Simulator running at http://localhost:{PORT}")
    print("AI-only evaluation is enabled when OPENAI_API_KEY is configured.")
    server.serve_forever()


if __name__ == "__main__":
    main()

