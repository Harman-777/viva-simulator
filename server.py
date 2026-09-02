"""
=============================================================================
VIVA SIMULATOR — Server & AI Evaluation Engine
Full-stack Python Web Server, AI Scoring Core, and Oral Exam Backend
=============================================================================
"""

from __future__ import annotations

import base64
import concurrent.futures
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

# ---------------------------------------------------------------------------
# Path & Runtime Constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path("/tmp") if os.environ.get("VERCEL") else (ROOT / "data")
DATABASE_PATH = DATA_DIR / "viva.db"
PORT = int(os.environ.get("PORT", "8000"))

OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_MATERIAL_TEXT = 60000

# ---------------------------------------------------------------------------
# Security & Rate Limiting
# ---------------------------------------------------------------------------
SESSION_SECRET = os.environ.get("SESSION_SECRET", "viva_secret_key_2026_default_secure")
_login_attempts_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
LOGIN_RATE_WINDOW = 900  # 15 minutes
LOGIN_MAX_ATTEMPTS = 5


def check_login_rate(ip: str) -> None:
    now_ts = time.monotonic()
    with _login_attempts_lock:
        attempts = _login_attempts.get(ip, [])
        attempts = [t for t in attempts if now_ts - t < LOGIN_RATE_WINDOW]
        _login_attempts[ip] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise ApiError("Too many login attempts. Please wait 15 minutes before trying again.", HTTPStatus.TOO_MANY_REQUESTS)


def record_failed_login(ip: str) -> None:
    now_ts = time.monotonic()
    with _login_attempts_lock:
        attempts = _login_attempts.setdefault(ip, [])
        attempts.append(now_ts)
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


def sign_session_payload(payload: dict) -> str:
    raw_json = json.dumps(payload, sort_keys=True)
    b64_data = base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"


def verify_session_payload(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        b64_data, sig = token.split(".", 1)
        expected_sig = hmac.new(SESSION_SECRET.encode("utf-8"), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded_b64 = b64_data + "=" * (-len(b64_data) % 4)
        raw_json = base64.urlsafe_b64decode(padded_b64.encode("ascii")).decode("utf-8")
        payload = json.loads(raw_json)
        if time.time() > payload.get("exp", 0):
            return None
        return payload
    except Exception:
        return None


def password_record(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    encoded = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000)
    return base64.b64encode(encoded).decode("ascii"), base64.b64encode(salt).decode("ascii")


def valid_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    try:
        salt = base64.b64decode(stored_salt.encode("ascii"))
        encoded = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000)
        return hmac.compare_digest(base64.b64encode(encoded).decode("ascii"), stored_hash)
    except Exception:
        return False


def clean_text(value, max_length: int = 10000) -> str:
    return str(value or "").strip()[:max_length]


def parse_json(value: str, fallback):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def normalize_ai_endpoint(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return OPENAI_ENDPOINT
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"
    return url


# ---------------------------------------------------------------------------
# Database Management
# ---------------------------------------------------------------------------
def database() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not os.environ.get("VERCEL"):
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
    return conn


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
                ai_grading_enabled INTEGER NOT NULL DEFAULT 1,
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
        # Migrations
        try:
            conn.execute("ALTER TABLE assessments ADD COLUMN question_ordering TEXT NOT NULL DEFAULT 'fixed'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE assessments ADD COLUMN ai_grading_enabled INTEGER NOT NULL DEFAULT 1")
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
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_study_materials_owner ON study_materials(owner_key)")
        except sqlite3.OperationalError:
            pass

        # Default teacher seeding if empty
        if conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0:
            pass_hash, pass_salt = password_record("password")
            conn.execute(
                "INSERT INTO teachers (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                ("teacher@example.com", "Professor", pass_hash, pass_salt, now())
            )


# ---------------------------------------------------------------------------
# Document Ingestion & Text Extractors
# ---------------------------------------------------------------------------
def extract_material(file_name: str, mime_type: str, raw: bytes) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".py", ".json", ".html", ".c", ".cpp", ".java", ".js", ".ts", ".xml", ".sql", ".sh"} or mime_type.startswith("text/"):
        return raw.decode("utf-8", errors="replace")[:MAX_MATERIAL_TEXT]
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as doc:
                root = ElementTree.fromstring(doc.read("word/document.xml"))
            texts = []
            curr_len = 0
            for t in root.itertext():
                clean_t = t.strip()
                if clean_t:
                    texts.append(clean_t)
                    curr_len += len(clean_t) + 1
                    if curr_len >= MAX_MATERIAL_TEXT:
                        break
            return " ".join(texts)
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as e:
            raise ApiError("DOCX file could not be parsed.") from e
    if suffix == ".pdf" or mime_type == "application/pdf" or raw.startswith(b"%PDF"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw))
            extracted_pages = []
            char_count = 0
            # Fast early-exit: read pages only until reaching syllabus text capacity
            for idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text.strip())
                    char_count += len(page_text)
                    if char_count >= MAX_MATERIAL_TEXT or idx >= 40:
                        break
            text = "\n\n".join(extracted_pages)
            if text.strip():
                return text[:MAX_MATERIAL_TEXT]
        except Exception:
            pass
        # Raw stream fallback for PDF extraction
        try:
            text_chunks = []
            curr_len = 0
            for stream in re.findall(b"stream[\r\n]+(.*?)[\r\n]+endstream", raw, re.DOTALL):
                try:
                    import zlib
                    decomp = zlib.decompress(stream)
                    for match in re.findall(rb"\((.*?)\)[\r\n\s]*T[jJ]", decomp):
                        decoded_chunk = match.decode("latin-1", errors="ignore").strip()
                        if decoded_chunk:
                            text_chunks.append(decoded_chunk)
                            curr_len += len(decoded_chunk) + 1
                            if curr_len >= MAX_MATERIAL_TEXT:
                                break
                    if curr_len >= MAX_MATERIAL_TEXT:
                        break
                except Exception:
                    pass
            if text_chunks:
                return " ".join(text_chunks)[:MAX_MATERIAL_TEXT]
        except Exception:
            pass
        raise ApiError("Could not extract readable text from this PDF file.")
    raise ApiError("Please upload a PDF, DOCX, TXT, Markdown, CSV, or code file.")


# ---------------------------------------------------------------------------
# AI Model Connector & Rubric Grading Engine
# ---------------------------------------------------------------------------
def decode_ai_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match_obj = re.search(r"(\{.*\})", text, re.DOTALL)
        if match_obj:
            try:
                return json.loads(match_obj.group(1))
            except Exception:
                pass
        match_arr = re.search(r"(\[.*\])", text, re.DOTALL)
        if match_arr:
            try:
                return json.loads(match_arr.group(1))
            except Exception:
                pass
        raise ApiError("AI model returned an invalid structured JSON response. Please retry.", HTTPStatus.BAD_GATEWAY)


def is_gemini_key_or_model(key: str, base_url: str, model_name: str) -> bool:
    if base_url:
        return False
    k = (key or "").strip()
    m = (model_name or "").strip().lower()
    if "gemini" in m:
        return True
    if k.startswith("AIza") or k.startswith("AQ.") or k.startswith("AQ") or k.startswith("AI"):
        return True
    if k and not k.startswith("sk-") and not k.startswith("sess-"):
        if "gpt" not in m:
            return True
    return False


def ask_ai(instruction: str, payload: dict, max_tokens: int = 2200, api_key: str = "", base_url: str = "", model_name: str = ""):
    effective_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
    if not effective_key and not base_url:
        raise ApiError("AI configuration required. Please enter an API Key (OpenAI/Gemini) or configure a Local LLM URL (Ollama/LM Studio).", HTTPStatus.SERVICE_UNAVAILABLE)

    is_gemini = is_gemini_key_or_model(effective_key, base_url, model_name)

    if is_gemini:
        gemini_model = model_name if model_name and "gemini" in model_name.lower() else "gemini-1.5-flash"
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
        endpoint = normalize_ai_endpoint(base_url)
        model = model_name if model_name else OPENAI_MODEL
        request_body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a specialized academic examiner grading oral viva exams. You only return valid JSON without markdown wrapping."
                },
                {
                    "role": "user",
                    "content": instruction + "\n\nDATA:\n" + json.dumps(payload, ensure_ascii=False)
                }
            ],
            "max_tokens": max_tokens,
        }
        if not base_url:
            request_body["response_format"] = {"type": "json_object"}

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
        timeout = 180 if base_url else 60
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))

        if is_gemini:
            text = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        else:
            text = raw["choices"][0]["message"]["content"]

        return decode_ai_json(text)
    except ApiError:
        raise
    except urllib.error.HTTPError as error:
        try:
            err_text = error.read().decode("utf-8")
            err_body = json.loads(err_text)
            msg = err_body.get("error", {}).get("message", err_text[:200])
        except Exception:
            msg = f"HTTP {error.code}: {error.reason}"
        raise ApiError(f"AI error: {msg}", HTTPStatus.BAD_GATEWAY) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ApiError(f"AI service connection failed or timed out: {str(error)}", HTTPStatus.BAD_GATEWAY) from error


def test_ai_connection(api_key: str = "", base_url: str = "", model_name: str = "") -> dict:
    start_t = time.monotonic()
    result = ask_ai(
        "Ping test. Return a JSON object with status 'ok' and a short greeting message.",
        {"ping": True},
        max_tokens=60,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name
    )
    latency_ms = int((time.monotonic() - start_t) * 1000)
    is_gem = is_gemini_key_or_model(api_key, base_url, model_name)
    engine_name = model_name or ("gemini-1.5-flash" if is_gem else ("ollama" if base_url else OPENAI_MODEL))
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "engine": engine_name,
        "message": f"Connected to {engine_name} successfully ({latency_ms}ms)"
    }


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
            "max_marks": max_marks,
            "percentage": 0.0,
            "correctness": "incorrect",
            "confidence": "high",
            "dimension_scores": {
                "precision": 0.0,
                "clarity": 0.0,
                "evidence": 0.0,
                "keywords": 0.0
            },
            "feedback": f"The response '{clean_ans}' is an invalid or uninformative answer.",
            "covered_concepts": [],
            "missing_concepts": key_concepts or [],
            "rationale": "No relevant technical content or explanation provided.",
            "model_answer": reference_answer or "Provide a clear technical explanation addressing the core question concepts.",
            "engine": f"ollama-{model_name}" if base_url else (f"custom-{model_name}" if model_name else ("gemini" if api_key.startswith("AIza") else f"openai-{OPENAI_MODEL}"))
        }

    p_max = round(max_marks * 0.20, 2)
    c_max = round(max_marks * 0.20, 2)
    e_max = round(max_marks * 0.20, 2)
    k_max = round(max_marks * 0.40, 2)

    instruction = (
        "CRITICAL EVALUATION RULES:\n"
        "- You are a strict academic examiner grading a viva oral defense answer.\n"
        "- If the student answer is completely wrong or irrelevant, award a score of 0.\n"
        "- Evaluate valid student answers strictly by core technical meaning and conceptual accuracy.\n\n"
        f"Marking Rubric Breakdown (Maximum Total Marks: {max_marks}):\n"
        f"1. Concept Precision (max {p_max} marks): Accuracy of terminology and definitions.\n"
        f"2. Explanation Clarity (max {c_max} marks): Structure, reasoning flow, and avoidance of vague words.\n"
        f"3. Evidence & Examples (max {e_max} marks): Mentioning concrete scenarios, code snippets, or facts.\n"
        f"4. Keyword/Concept Coverage (max {k_max} marks): Addressing key concepts in the reference answer/material.\n\n"
        f"Return a JSON object with exactly:\n"
        f"- score (number between 0 and {max_marks})\n"
        f"- precision_score (number between 0 and {p_max})\n"
        f"- clarity_score (number between 0 and {c_max})\n"
        f"- evidence_score (number between 0 and {e_max})\n"
        f"- keywords_score (number between 0 and {k_max})\n"
        "- correctness ('correct' | 'partially_correct' | 'incorrect')\n"
        "- confidence ('low' | 'medium' | 'high')\n"
        "- feedback (string with detailed constructive evaluation)\n"
        "- covered_concepts (array of strings)\n"
        "- missing_concepts (array of strings)\n"
        "- rationale (string with marking justification)\n"
        "- model_answer (string with ideal viva answer)"
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

    result = ask_ai(instruction, payload, max_tokens=1600, api_key=api_key, base_url=base_url, model_name=model_name)

    if not isinstance(result, dict):
        raise ApiError("AI model returned an invalid evaluation structure.")

    try:
        score = round(float(result.get("score", 0)), 2)
    except (TypeError, ValueError):
        score = 0.0

    score = max(0, min(float(max_marks), score))
    result["score"] = score
    result["max_marks"] = max_marks
    result["percentage"] = round((score / max_marks * 100), 1) if max_marks else 0

    # Sub-scores parsing
    prec = min(p_max, max(0.0, float(result.get("precision_score", score * 0.20))))
    clar = min(c_max, max(0.0, float(result.get("clarity_score", score * 0.20))))
    evid = min(e_max, max(0.0, float(result.get("evidence_score", score * 0.20))))
    keyw = min(k_max, max(0.0, float(result.get("keywords_score", score * 0.40))))

    result["dimension_scores"] = {
        "precision": round(prec, 2),
        "clarity": round(clar, 2),
        "evidence": round(evid, 2),
        "keywords": round(keyw, 2),
        "max_precision": p_max,
        "max_clarity": c_max,
        "max_evidence": e_max,
        "max_keywords": k_max,
    }

    result["correctness"] = result.get("correctness") if result.get("correctness") in {"correct", "partially_correct", "incorrect"} else ("correct" if score >= max_marks * 0.8 else ("partially_correct" if score >= max_marks * 0.5 else "incorrect"))
    result["confidence"] = result.get("confidence") if result.get("confidence") in {"low", "medium", "high"} else "medium"

    for name in ("covered_concepts", "missing_concepts"):
        values = result.get(name, [])
        result[name] = [clean_text(v, 200) for v in values[:12]] if isinstance(values, list) else []

    result["feedback"] = clean_text(result.get("feedback"), 3000)
    result["rationale"] = clean_text(result.get("rationale"), 3000)
    result["model_answer"] = clean_text(result.get("model_answer", result.get("feedback", "")), 4000)
    result["engine"] = f"ollama-{model_name}" if base_url else (f"custom-{model_name}" if model_name else ("gemini" if api_key.startswith("AIza") else f"openai-{OPENAI_MODEL}"))
    return result


def generate_practice_questions(payload: dict) -> list[dict]:
    material = clean_text(payload.get("material"), MAX_MATERIAL_TEXT)
    subject = clean_text(payload.get("subject"), 120) or "Computer Science"
    level = clean_text(payload.get("level"), 20).lower() or "medium"
    try:
        count = int(payload.get("question_count", 5))
    except (TypeError, ValueError):
        count = 5

    count = max(1, min(50, count))
    api_key = payload.get("_api_key", "")
    base_url = payload.get("_base_url", "")
    model_name = payload.get("_model_name", "")

    result = ask_ai(
        (
            f"Create exactly {count} {level}-level oral viva exam practice questions for {subject}. "
            "Return a JSON array of objects. Each object must have: question (string), reference_answer (string), key_concepts (array of 3-5 strings)."
        ),
        {"subject": subject, "study_material": material or None},
        max_tokens=min(8000, 600 + count * 240),
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
        raise ApiError("AI model returned an invalid question list structure. Please retry.")

    questions = []
    for item in result[:count]:
        q_text = clean_text(item.get("question"), 3000)
        ref = clean_text(item.get("reference_answer"), 8000)
        concepts = item.get("key_concepts") if isinstance(item.get("key_concepts"), list) else []
        if q_text:
            questions.append({
                "id": random_token(),
                "question": q_text,
                "reference_answer": ref,
                "key_concepts": [clean_text(v, 100) for v in concepts[:10] if clean_text(v, 100)]
            })

    if not questions:
        raise ApiError("Could not generate valid viva questions from AI.")
    return questions


# ---------------------------------------------------------------------------
# HTTP Handler & API Routing
# ---------------------------------------------------------------------------
class VivaHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, payload, status: int = HTTPStatus.OK, headers: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
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
            raise ApiError("Request too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            raise ApiError("Invalid JSON body.") from e
        if not isinstance(payload, dict):
            raise ApiError("JSON body must be an object.")
        return payload

    def cookies(self) -> SimpleCookie:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return cookie

    def teacher(self, conn: sqlite3.Connection) -> dict | None:
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

        if not token_str:
            return None

        # 1. Stateless verification
        payload = verify_session_payload(token_str)
        if payload:
            return {"id": payload["id"], "email": payload["email"], "display_name": payload["display_name"]}

        # 2. Database lookup fallback
        try:
            row = conn.execute(
                "SELECT t.id, t.email, t.display_name FROM teachers t JOIN teacher_sessions s ON s.teacher_id = t.id WHERE s.id = ?",
                (token_str,)
            ).fetchone()
            if row:
                return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}
        except Exception:
            pass
        return None

    def require_teacher(self, conn: sqlite3.Connection) -> dict:
        t = self.teacher(conn)
        if not t:
            raise ApiError("Teacher authentication required.", HTTPStatus.UNAUTHORIZED)
        return t

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key, X-Base-Url, X-Model-Name")
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
                self.send_json({"error": "Internal server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)
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
                self.send_json({"error": "Internal server error."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def handle_get_api(self, parsed):
        path = parsed.path
        params = parse_qs(parsed.query)
        with database() as conn:
            if path == "/api/health":
                server_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
                user_key = bool((self.headers.get("X-Api-Key") or "").strip())
                return self.send_json({"status": "healthy", "ai_configured": server_key or user_key, "model": OPENAI_MODEL})

            if path == "/api/auth/me":
                t = self.teacher(conn)
                return self.send_json({"teacher": t})

            if path == "/api/teacher/settings":
                teacher = self.require_teacher(conn)
                row = conn.execute("SELECT api_settings_json FROM teachers WHERE id = ?", (teacher["id"],)).fetchone()
                settings = parse_json(row["api_settings_json"] if row else "{}", {})
                return self.send_json({"settings": settings})

            if path == "/api/library/materials":
                owner_key = clean_text(params.get("owner_key", [""])[0], 120)
                if not owner_key:
                    return self.send_json({"materials": []})
                items = conn.execute("SELECT id, file_name, file_type, created_at, length(extracted_text) AS character_count FROM study_materials WHERE owner_key = ? ORDER BY id DESC", (owner_key,)).fetchall()
                return self.send_json({"materials": [dict(item) for item in items]})

            if path == "/api/teacher/assessments":
                teacher = self.require_teacher(conn)
                rows = conn.execute(
                    """
                    SELECT a.*, COUNT(DISTINCT at.id) AS attempt_count,
                           COUNT(DISTINCT CASE WHEN at.state = 'submitted' THEN at.id END) AS submitted_count
                    FROM assessments a LEFT JOIN attempts at ON at.assessment_id = a.id
                    WHERE a.teacher_id = ? GROUP BY a.id ORDER BY a.updated_at DESC
                    """,
                    (teacher["id"],)
                ).fetchall()
                assessments = []
                for r in rows:
                    item = dict(r)
                    item["student_fields"] = parse_json(item.pop("student_fields_json"), [])
                    item["show_results"] = bool(item["show_results"])
                    item["ai_grading_enabled"] = bool(item.get("ai_grading_enabled", 1))
                    item["share"] = self._get_share_link(conn, item["id"])
                    assessments.append(item)
                return self.send_json({"assessments": assessments})

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)", path)
            if match:
                teacher = self.require_teacher(conn)
                a = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (int(match.group(1)), teacher["id"])).fetchone()
                if not a:
                    raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)
                data = dict(a)
                data["student_fields"] = parse_json(data.pop("student_fields_json"), [])
                data["show_results"] = bool(data["show_results"])
                data["ai_grading_enabled"] = bool(data.get("ai_grading_enabled", 1))
                data["question_count"] = {"mode": data.pop("question_count_mode"), "min": data.pop("question_count_min"), "max": data.pop("question_count_max")}
                questions = conn.execute("SELECT id, question_text AS question, reference_answer, marks, position FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (data["id"],)).fetchall()
                data["questions"] = [dict(q) for q in questions]
                data["share"] = self._get_share_link(conn, data["id"])
                return self.send_json({"assessment": data})

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/results", path)
            if match:
                return self.teacher_results(conn, int(match.group(1)))

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/export-csv", path)
            if match:
                return self.export_assessment_csv(conn, int(match.group(1)))

            match = re.fullmatch(r"/api/teacher/attempts/(\d+)", path)
            if match:
                return self.teacher_attempt(conn, int(match.group(1)))

            match = re.fullmatch(r"/api/public/viva/([A-Za-z0-9_-]+)", path)
            if match:
                link = conn.execute(
                    """SELECT s.*, a.title, a.subject, a.instructions, a.duration_minutes, a.question_count_mode,
                              a.question_count_min, a.question_count_max, a.student_fields_json, a.show_results, a.ai_grading_enabled, a.status
                       FROM share_links s JOIN assessments a ON a.id = s.assessment_id WHERE s.token = ?""",
                    (match.group(1),)
                ).fetchone()
                if not link or not link["is_active"] or link["status"] != "published":
                    raise ApiError("Assessment link is inactive or unavailable.", HTTPStatus.NOT_FOUND)
                if link["expires_at"] and link["expires_at"] < now():
                    raise ApiError("This assessment link has expired.", HTTPStatus.GONE)

                return self.send_json({
                    "viva": {
                        "title": link["title"],
                        "subject": link["subject"],
                        "instructions": link["instructions"],
                        "duration_minutes": link["duration_minutes"],
                        "student_fields": parse_json(link["student_fields_json"], []),
                        "pin_required": bool(link["pin_hash"])
                    }
                })

            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)", path)
            if match:
                return self.public_attempt(conn, match.group(1))

            raise ApiError("Endpoint not found.", HTTPStatus.NOT_FOUND)

    def _get_share_link(self, conn: sqlite3.Connection, assessment_id: int):
        row = conn.execute("SELECT token, expires_at, is_active FROM share_links WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if not row:
            return None
        return {"token": row["token"], "url": f"/viva/{row['token']}", "expires_at": row["expires_at"], "is_active": bool(row["is_active"])}

    def handle_mutation_api(self, method: str, parsed, payload: dict):
        path = parsed.path
        with database() as conn:
            if method == "POST" and path in ("/api/auth/login", "/api/auth/setup"):
                client_addr = getattr(self, "client_address", None)
                client_ip = client_addr[0] if client_addr and isinstance(client_addr, (tuple, list)) else "unknown"
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
                    cur = conn.execute(
                        "INSERT INTO teachers (email, display_name, password_hash, password_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                        (email, display_name, digest, salt, now())
                    )
                    teacher = conn.execute("SELECT * FROM teachers WHERE id = ?", (cur.lastrowid,)).fetchone()
                else:
                    if not valid_password(password, teacher["password_hash"], teacher["password_salt"]):
                        record_failed_login(client_ip)
                        raise ApiError("Invalid email or password.", HTTPStatus.UNAUTHORIZED)

                clear_login_rate(client_ip)
                return self.start_teacher_session(conn, teacher)

            if method == "POST" and path == "/api/auth/logout":
                return self.send_json({"ok": True}, headers={"Set-Cookie": "viva_teacher_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})

            # AI Connectivity Test
            if method == "POST" and path == "/api/ai/test":
                api_key = clean_text(payload.get("api_key") or self.headers.get("X-Api-Key"), 200)
                base_url = clean_text(payload.get("base_url") or self.headers.get("X-Base-Url"), 300)
                model_name = clean_text(payload.get("model_name") or self.headers.get("X-Model-Name"), 100)
                res = test_ai_connection(api_key=api_key, base_url=base_url, model_name=model_name)
                return self.send_json(res)

            if method == "POST" and path == "/api/teacher/settings":
                teacher = self.require_teacher(conn)
                settings = {
                    "api_key": clean_text(payload.get("api_key"), 200),
                    "base_url": clean_text(payload.get("base_url"), 300),
                    "model_name": clean_text(payload.get("model_name"), 100)
                }
                conn.execute("UPDATE teachers SET api_settings_json = ? WHERE id = ?", (json.dumps(settings), teacher["id"]))
                conn.commit()
                return self.send_json({"saved": True, "settings": settings})

            if method == "POST" and path == "/api/teacher/generate-questions":
                teacher = self.require_teacher(conn)
                row = conn.execute("SELECT api_settings_json FROM teachers WHERE id = ?", (teacher["id"],)).fetchone()
                t_settings = parse_json(row["api_settings_json"] if row else "{}", {})

                payload["_api_key"] = clean_text(payload.get("api_key") or t_settings.get("api_key") or self.headers.get("X-Api-Key"), 200)
                payload["_base_url"] = clean_text(payload.get("base_url") or t_settings.get("base_url") or self.headers.get("X-Base-Url"), 300)
                payload["_model_name"] = clean_text(payload.get("model_name") or t_settings.get("model_name") or self.headers.get("X-Model-Name"), 100)

                return self.send_json({"questions": generate_practice_questions(payload)})

            if method == "POST" and path == "/api/generate-questions":
                subject = clean_text(payload.get("subject"), 120) or "Computer Science"
                level = clean_text(payload.get("level"), 20).lower() or "medium"
                api_key = clean_text(payload.get("api_key") or self.headers.get("X-Api-Key"), 200)
                base_url = clean_text(payload.get("base_url") or self.headers.get("X-Base-Url"), 300)
                model_name = clean_text(payload.get("model_name") or self.headers.get("X-Model-Name"), 100)

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
                            questions = subj_data[:5]
                    except Exception:
                        pass

                if not questions and (api_key or base_url or os.environ.get("OPENAI_API_KEY", "").strip()):
                    try:
                        res = ask_ai(
                            f"Create 5 {level}-level oral viva exam questions for {subject}. Return JSON array of objects with id, question, key_concepts (array of 3-5 strings), reference_answer.",
                            {"subject": subject, "level": level},
                            api_key=api_key,
                            base_url=base_url,
                            model_name=model_name
                        )
                        if isinstance(res, list):
                            questions = res
                    except Exception:
                        pass

                if not questions:
                    questions = [
                        {"id": "q-1", "question": f"Explain the core architectural definition and scope of {subject}.", "key_concepts": [subject.lower(), "principles", "architecture"], "reference_answer": f"{subject} encapsulates fundamental principles and modular implementation."},
                        {"id": "q-2", "question": f"What are the main advantages and practical use cases of {subject}?", "key_concepts": ["advantages", "efficiency", "use cases"], "reference_answer": f"{subject} provides structured efficiency and maintainability."},
                        {"id": "q-3", "question": f"Discuss common challenges or tradeoffs encountered with {subject}.", "key_concepts": ["tradeoffs", "limitations", "scalability"], "reference_answer": "Key challenges include complexity control, resource utilization, and error handling."}
                    ]
                return self.send_json({"questions": questions, "engine": "ai"})

            if method == "POST" and path == "/api/evaluate":
                question = clean_text(payload.get("question"), 3000)
                answer = clean_text(payload.get("answer"), 12000)
                expected_keywords = payload.get("expected_keywords", [])
                model_answer = clean_text(payload.get("model_answer") or payload.get("reference_answer"), 4000)
                api_key = clean_text(payload.get("api_key") or self.headers.get("X-Api-Key"), 200)
                base_url = clean_text(payload.get("base_url") or self.headers.get("X-Base-Url"), 300)
                model_name = clean_text(payload.get("model_name") or self.headers.get("X-Model-Name"), 100)

                res = evaluate_answer(question, answer, 100, reference_answer=model_answer, key_concepts=expected_keywords, api_key=api_key, base_url=base_url, model_name=model_name)
                res["strengths"] = res.get("covered_concepts") or ["Addressed key principles"]
                res["gaps"] = res.get("missing_concepts") or ["No major conceptual gaps"]
                res["readiness"] = "Excellent" if res["score"] >= 80 else ("Good" if res["score"] >= 60 else "Needs Practice")
                return self.send_json(res)

            if method == "POST" and path == "/api/library/materials":
                owner_key = clean_text(payload.get("owner_key"), 120)
                file_name = clean_text(payload.get("file_name"), 180)
                mime_type = clean_text(payload.get("mime_type"), 120)
                raw_text = payload.get("raw_text")

                if not owner_key or not file_name:
                    raise ApiError("Incomplete material payload.")

                if isinstance(raw_text, str) and raw_text.strip():
                    text = clean_text(raw_text.strip(), MAX_MATERIAL_TEXT)
                else:
                    encoded = payload.get("content_base64", "")
                    if not isinstance(encoded, str) or not encoded:
                        raise ApiError("Incomplete file upload.")
                    try:
                        clean_b64 = re.sub(r"^data:[^;]+;base64,", "", encoded).strip()
                        padded_b64 = clean_b64 + "=" * (-len(clean_b64) % 4)
                        raw = base64.b64decode(padded_b64, validate=False)
                    except Exception as e:
                        raise ApiError("Invalid base64 encoding.") from e
                    if len(raw) > MAX_UPLOAD_BYTES:
                        raise ApiError("File exceeds 8 MB upload limit.")
                    text = clean_text(extract_material(file_name, mime_type, raw), MAX_MATERIAL_TEXT)

                if len(text) < 15:
                    raise ApiError("Could not extract readable text (minimum 15 characters required).")

                cur = conn.execute("INSERT INTO study_materials (owner_key, file_name, file_type, extracted_text, created_at) VALUES (?, ?, ?, ?, ?)", (owner_key, file_name, mime_type or "text/plain", text, now()))
                return self.send_json({"material": {"id": cur.lastrowid, "file_name": file_name, "character_count": len(text)}})

            match = re.fullmatch(r"/api/library/materials/(\d+)", path)
            if method == "DELETE" and match:
                owner_key = clean_text(parse_qs(parsed.query).get("owner_key", [""])[0], 120)
                conn.execute("DELETE FROM study_materials WHERE id = ? AND owner_key = ?", (int(match.group(1)), owner_key))
                return self.send_json({"ok": True})

            if method == "POST" and path == "/api/library/generate":
                owner_key = clean_text(payload.get("owner_key"), 120)
                ids = payload.get("material_ids", [])
                if not owner_key or not isinstance(ids, list) or not ids:
                    raise ApiError("Please select uploaded materials.")
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(f"SELECT extracted_text FROM study_materials WHERE owner_key = ? AND id IN ({placeholders})", [owner_key, *ids]).fetchall()
                material_text = "\n\n".join(r["extracted_text"] for r in rows)
                payload["material"] = clean_text(material_text, MAX_MATERIAL_TEXT)
                payload["_api_key"] = clean_text(payload.get("api_key") or self.headers.get("X-Api-Key"), 200)
                payload["_base_url"] = clean_text(payload.get("base_url") or self.headers.get("X-Base-Url"), 300)
                payload["_model_name"] = clean_text(payload.get("model_name") or self.headers.get("X-Model-Name"), 100)
                return self.send_json({"questions": generate_practice_questions(payload)})

            # Teacher Assessment Management
            if method == "POST" and path == "/api/teacher/assessments":
                teacher = self.require_teacher(conn)
                return self.save_assessment(conn, teacher, payload, assessment_id=None)

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)", path)
            if method == "PUT" and match:
                teacher = self.require_teacher(conn)
                return self.save_assessment(conn, teacher, payload, assessment_id=int(match.group(1)))

            if method == "DELETE" and match:
                teacher = self.require_teacher(conn)
                ass_id = int(match.group(1))
                a = conn.execute("SELECT id FROM assessments WHERE id = ? AND teacher_id = ?", (ass_id, teacher["id"])).fetchone()
                if not a:
                    raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)
                conn.execute("DELETE FROM assessments WHERE id = ?", (ass_id,))
                conn.commit()
                return self.send_json({"deleted": True, "assessment_id": ass_id})

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/duplicate", path)
            if method == "POST" and match:
                teacher = self.require_teacher(conn)
                ass_id = int(match.group(1))
                a = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (ass_id, teacher["id"])).fetchone()
                if not a:
                    raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)
                timestamp = now()
                cur = conn.execute(
                    """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, ai_grading_enabled, question_ordering, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
                    (teacher["id"], f"{a['title']} (Copy)", a["subject"], a["instructions"], a["duration_minutes"], a["question_count_mode"], a["question_count_min"], a["question_count_max"], a["student_fields_json"], a["show_results"], a["ai_grading_enabled"], a["question_ordering"], timestamp, timestamp)
                )
                new_id = cur.lastrowid
                questions = conn.execute("SELECT question_text, reference_answer, marks, position FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (ass_id,)).fetchall()
                conn.executemany(
                    "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, ?, ?, ?, ?)",
                    [(new_id, q["question_text"], q["reference_answer"], q["marks"], q["position"]) for q in questions]
                )
                conn.commit()
                return self.send_json({"duplicated": True, "new_assessment_id": new_id}, HTTPStatus.CREATED)

            match = re.fullmatch(r"/api/teacher/assessments/(\d+)/publish", path)
            if method == "POST" and match:
                teacher = self.require_teacher(conn)
                return self.publish_assessment(conn, teacher, int(match.group(1)), payload)

            match = re.fullmatch(r"/api/teacher/answers/(\d+)/override", path)
            if method == "POST" and match:
                teacher = self.require_teacher(conn)
                return self.override_mark(conn, teacher, int(match.group(1)), payload)

            # Public Exam Student Routes
            match = re.fullmatch(r"/api/public/viva/([A-Za-z0-9_-]+)/start", path)
            if method == "POST" and match:
                return self.start_public_attempt(conn, match.group(1), payload)

            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)/answers", path)
            if method == "POST" and match:
                return self.save_public_answer(conn, match.group(1), payload)

            match = re.fullmatch(r"/api/public/attempts/([A-Za-z0-9_-]+)/submit", path)
            if method == "POST" and match:
                return self.submit_public_attempt(conn, match.group(1))

            raise ApiError("Endpoint not found.", HTTPStatus.NOT_FOUND)

    def start_teacher_session(self, conn: sqlite3.Connection, teacher: sqlite3.Row):
        exp = int(time.time()) + (14 * 86400)
        payload = {
            "id": teacher["id"],
            "email": teacher["email"],
            "display_name": teacher["display_name"],
            "exp": exp
        }
        token = sign_session_payload(payload)
        try:
            conn.execute("INSERT OR REPLACE INTO teacher_sessions (id, teacher_id, created_at) VALUES (?, ?, ?)", (token, teacher["id"], now()))
        except Exception:
            pass
        self.send_json(
            {"teacher": {"id": teacher["id"], "email": teacher["email"], "display_name": teacher["display_name"]}},
            headers={"Set-Cookie": f"viva_teacher_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=1209600"}
        )

    def save_assessment(self, conn: sqlite3.Connection, teacher: dict, payload: dict, assessment_id: int | None):
        title = clean_text(payload.get("title"), 160)
        subject = clean_text(payload.get("subject"), 120)
        instructions = clean_text(payload.get("instructions"), 4000)
        duration = max(1, min(300, int(payload.get("duration_minutes", 20))))
        mode = payload.get("question_count_mode", "fixed")
        min_q = max(1, int(payload.get("question_count_min", 1)))
        max_q = max(min_q, int(payload.get("question_count_max", 5)))
        show_results = 1 if payload.get("show_results") else 0
        ai_grading_enabled = 0 if payload.get("ai_grading_enabled") is False or payload.get("ai_grading_enabled") == 0 else 1
        ordering = payload.get("question_ordering", "fixed")
        questions = payload.get("questions", [])

        if not title or not subject:
            raise ApiError("Title and Subject are required.")
        if not questions or not isinstance(questions, list):
            raise ApiError("Add at least one question.")

        timestamp = now()
        if assessment_id:
            conn.execute(
                """UPDATE assessments SET title=?, subject=?, instructions=?, duration_minutes=?, question_count_mode=?,
                   question_count_min=?, question_count_max=?, student_fields_json=?, show_results=?, ai_grading_enabled=?, question_ordering=?, updated_at=?
                   WHERE id=? AND teacher_id=?""",
                (title, subject, instructions, duration, mode, min_q, max_q, json.dumps(payload.get("student_fields", [])), show_results, ai_grading_enabled, ordering, timestamp, assessment_id, teacher["id"])
            )
            conn.execute("DELETE FROM assessment_questions WHERE assessment_id = ?", (assessment_id,))
        else:
            cur = conn.execute(
                """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, ai_grading_enabled, question_ordering, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
                (teacher["id"], title, subject, instructions, duration, mode, min_q, max_q, json.dumps(payload.get("student_fields", [])), show_results, ai_grading_enabled, ordering, timestamp, timestamp)
            )
            assessment_id = cur.lastrowid

        conn.executemany(
            "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, ?, ?, ?, ?)",
            [(assessment_id, clean_text(q.get("question"), 3000), clean_text(q.get("reference_answer"), 8000), float(q.get("marks", 10)), idx) for idx, q in enumerate(questions, start=1)]
        )
        return self.send_json({"assessment_id": assessment_id, "saved": True})

    def publish_assessment(self, conn: sqlite3.Connection, teacher: dict, assessment_id: int, payload: dict):
        assessment = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not assessment:
            raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)

        pin = clean_text(payload.get("pin"), 32)
        pin_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest() if pin else ""
        expires_at = clean_text(payload.get("expires_at"), 40) or None
        is_active = 0 if payload.get("is_active") is False or payload.get("is_active") == 0 else 1

        existing = conn.execute("SELECT * FROM share_links WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if existing:
            token = existing["token"]
            conn.execute("UPDATE share_links SET is_active=?, expires_at=?, pin_hash=? WHERE assessment_id=?", (is_active, expires_at, pin_hash, assessment_id))
        else:
            token = random_token()
            conn.execute("INSERT INTO share_links (assessment_id, token, pin_hash, expires_at, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)", (assessment_id, token, pin_hash, expires_at, is_active, now()))

        conn.execute("UPDATE assessments SET status='published', updated_at=? WHERE id=?", (now(), assessment_id))
        return self.send_json({"share": {"token": token, "url": f"/viva/{token}", "expires_at": expires_at, "is_active": bool(is_active)}})

    def start_public_attempt(self, conn: sqlite3.Connection, share_token: str, payload: dict):
        link = conn.execute(
            """SELECT s.*, a.id AS ass_id, a.duration_minutes, a.question_ordering, a.question_count_min, a.question_count_max, a.student_fields_json, a.status
               FROM share_links s JOIN assessments a ON a.id = s.assessment_id WHERE s.token = ?""",
            (share_token,)
        ).fetchone()

        if not link or not link["is_active"] or link["status"] != "published":
            raise ApiError("Viva link unavailable.", HTTPStatus.NOT_FOUND)
        if link["expires_at"] and link["expires_at"] < now():
            raise ApiError("Viva link expired.", HTTPStatus.GONE)

        if link["pin_hash"]:
            pin_input = clean_text(payload.get("pin"), 32)
            if not hmac.compare_digest(hashlib.sha256(pin_input.encode("utf-8")).hexdigest(), link["pin_hash"]):
                raise ApiError("Incorrect PIN.", HTTPStatus.UNAUTHORIZED)

        student_data = payload.get("student_data") if isinstance(payload.get("student_data"), dict) else {}
        questions = conn.execute("SELECT id FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (link["ass_id"],)).fetchall()
        q_ids = [r["id"] for r in questions]

        if link["question_ordering"] == "shuffled":
            import random
            random.shuffle(q_ids)
        elif link["question_ordering"] == "random":
            import random
            count = min(len(q_ids), link["question_count_max"])
            q_ids = random.sample(q_ids, count)

        access_token = random_token()
        conn.execute(
            "INSERT INTO attempts (assessment_id, share_link_id, access_token, student_data_json, selected_question_ids_json, state, started_at) VALUES (?, ?, ?, ?, ?, 'in_progress', ?)",
            (link["ass_id"], link["id"], access_token, json.dumps(student_data), json.dumps(q_ids), now())
        )
        return self.send_json({"attempt_token": access_token, "exam_url": f"/viva/{share_token}/exam?attempt={access_token}"}, HTTPStatus.CREATED)

    def public_attempt(self, conn: sqlite3.Connection, attempt_token: str):
        attempt = conn.execute(
            """SELECT at.*, a.title, a.subject, a.instructions, a.duration_minutes, a.show_results, a.ai_grading_enabled
               FROM attempts at JOIN assessments a ON a.id = at.assessment_id WHERE at.access_token = ?""",
            (attempt_token,)
        ).fetchone()

        if not attempt:
            raise ApiError("Attempt not found.", HTTPStatus.NOT_FOUND)

        # Server-synced remaining time calculation
        duration_mins = attempt["duration_minutes"] or 20
        total_seconds = duration_mins * 60
        started_at_str = attempt["started_at"]
        remaining_seconds = total_seconds
        try:
            started_dt = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            elapsed = max(0.0, (now_dt - started_dt).total_seconds())
            remaining_seconds = max(0, int(total_seconds - elapsed))
        except Exception:
            pass

        q_ids = parse_json(attempt["selected_question_ids_json"], [])
        if q_ids:
            placeholders = ",".join("?" for _ in q_ids)
            questions = conn.execute(f"SELECT id, question_text AS question, marks FROM assessment_questions WHERE id IN ({placeholders})", q_ids).fetchall()
            q_map = {q["id"]: dict(q) for q in questions}
        else:
            q_map = {}

        ans_rows = conn.execute("SELECT question_id, answer_text, ai_score, final_score, evaluation_json FROM attempt_answers WHERE attempt_id = ?", (attempt["id"],)).fetchall()
        ans_map = {a["question_id"]: a for a in ans_rows}

        show_res = bool(attempt["show_results"])
        result_questions = []
        for qid in q_ids:
            q = q_map.get(qid)
            if not q:
                continue
            ans = ans_map.get(qid)
            item = {
                "id": q["id"],
                "question": q["question"],
                "marks": q["marks"],
                "answer": ans["answer_text"] if ans else "",
                "evaluated": bool(ans)
            }
            if show_res and ans:
                item["ai_score"] = ans["ai_score"]
                item["final_score"] = ans["final_score"]
                item["evaluation"] = parse_json(ans["evaluation_json"], {})
            result_questions.append(item)

        return self.send_json({
            "attempt": {
                "state": attempt["state"],
                "title": attempt["title"],
                "subject": attempt["subject"],
                "instructions": attempt["instructions"],
                "duration_minutes": attempt["duration_minutes"],
                "remaining_seconds": remaining_seconds,
                "started_at": attempt["started_at"],
                "student": parse_json(attempt["student_data_json"], {}),
                "show_results": show_res,
                "ai_grading_enabled": bool(attempt["ai_grading_enabled"]),
                "questions": result_questions
            }
        })

    def save_public_answer(self, conn: sqlite3.Connection, attempt_token: str, payload: dict):
        attempt = conn.execute("SELECT * FROM attempts WHERE access_token = ?", (attempt_token,)).fetchone()
        if not attempt or attempt["state"] != "in_progress":
            raise ApiError("Attempt not active.", HTTPStatus.CONFLICT)

        qid = int(payload.get("question_id", 0))
        answer = clean_text(payload.get("answer"), 12000)
        empty_eval = {"score": 0, "correctness": "pending", "feedback": "Pending submission."}

        conn.execute(
            """INSERT INTO attempt_answers (attempt_id, question_id, answer_text, ai_score, final_score, evaluation_json, evaluated_at)
               VALUES (?, ?, ?, 0, 0, ?, ?)
               ON CONFLICT(attempt_id, question_id) DO UPDATE SET answer_text=excluded.answer_text, evaluated_at=excluded.evaluated_at""",
            (attempt["id"], qid, answer, json.dumps(empty_eval), now())
        )
        conn.commit()
        return self.send_json({"saved": True})

    def submit_public_attempt(self, conn: sqlite3.Connection, attempt_token: str):
        attempt = conn.execute(
            """SELECT at.*, a.ai_grading_enabled, a.teacher_id, a.id AS ass_id
               FROM attempts at JOIN assessments a ON a.id = at.assessment_id WHERE at.access_token = ?""",
            (attempt_token,)
        ).fetchone()
        if not attempt:
            raise ApiError("Attempt not found.", HTTPStatus.NOT_FOUND)
        if attempt["state"] == "submitted":
            return self.send_json({"submitted": True, "result_url": f"/viva/complete?attempt={attempt_token}"})

        ai_enabled = bool(attempt["ai_grading_enabled"])

        # Answers to grade
        q_ids = parse_json(attempt["selected_question_ids_json"], [])
        for qid in q_ids:
            exists = conn.execute("SELECT id FROM attempt_answers WHERE attempt_id = ? AND question_id = ?", (attempt["id"], qid)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO attempt_answers (attempt_id, question_id, answer_text, ai_score, final_score, evaluation_json, evaluated_at) VALUES (?, ?, '', 0, 0, '{}', ?)",
                    (attempt["id"], qid, now())
                )
        conn.commit()

        if not ai_enabled:
            conn.execute("UPDATE attempts SET state='submitted', needs_review=1, submitted_at=? WHERE id=?", (now(), attempt["id"]))
            conn.commit()
            return self.send_json({"submitted": True, "result_url": f"/viva/complete?attempt={attempt_token}"})

        # Load Assessment Teacher Settings
        t_row = conn.execute("SELECT api_settings_json FROM teachers WHERE id = ?", (attempt["teacher_id"],)).fetchone()
        t_settings = parse_json(t_row["api_settings_json"], {}) if t_row else {}
        effective_key = t_settings.get("api_key", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = t_settings.get("base_url", "").strip()
        model_name = t_settings.get("model_name", "").strip()

        answers_data = conn.execute(
            """SELECT ans.id, ans.answer_text, q.question_text, q.marks, q.reference_answer
               FROM attempt_answers ans JOIN assessment_questions q ON q.id = ans.question_id
               WHERE ans.attempt_id = ?""",
            (attempt["id"],)
        ).fetchall()

        def _grade_single(ans_row):
            txt = ans_row["answer_text"].strip()
            if not txt:
                return ans_row["id"], {"score": 0, "correctness": "incorrect", "confidence": "high", "feedback": "No response submitted."}, 0

            try:
                eval_res = evaluate_answer(
                    ans_row["question_text"], txt, ans_row["marks"], ans_row["reference_answer"],
                    api_key=effective_key, base_url=base_url, model_name=model_name
                )
                needs_review = 1 if eval_res.get("confidence") == "low" else 0
                return ans_row["id"], eval_res, needs_review
            except Exception as e:
                err_res = {"score": 0, "correctness": "pending", "confidence": "low", "feedback": f"AI evaluation pending: {str(e)}"}
                return ans_row["id"], err_res, 1

        overall_review = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_grade_single, dict(a)) for a in answers_data]
            for f in concurrent.futures.as_completed(futures):
                ans_id, eval_obj, review_flag = f.result()
                if review_flag:
                    overall_review = 1
                conn.execute(
                    "UPDATE attempt_answers SET ai_score=?, final_score=?, evaluation_json=?, evaluated_at=? WHERE id=?",
                    (eval_obj.get("score", 0), eval_obj.get("score", 0), json.dumps(eval_obj), now(), ans_id)
                )

        conn.execute("UPDATE attempts SET state='submitted', needs_review=?, submitted_at=? WHERE id=?", (overall_review, now(), attempt["id"]))
        conn.commit()
        return self.send_json({"submitted": True, "result_url": f"/viva/complete?attempt={attempt_token}"})

    def teacher_results(self, conn: sqlite3.Connection, assessment_id: int):
        teacher = self.require_teacher(conn)
        a = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not a:
            raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)

        rows = conn.execute(
            """SELECT at.id, at.student_data_json, at.state, at.needs_review, at.started_at, at.submitted_at,
                      COALESCE(SUM(ans.ai_score), 0) AS ai_score, COALESCE(SUM(ans.final_score), 0) AS final_score,
                      COALESCE(SUM(q.marks), 0) AS max_marks
               FROM attempts at
               LEFT JOIN attempt_answers ans ON ans.attempt_id=at.id
               LEFT JOIN assessment_questions q ON q.id=ans.question_id
               WHERE at.assessment_id=? GROUP BY at.id ORDER BY at.submitted_at DESC, at.started_at DESC""",
            (assessment_id,)
        ).fetchall()

        students = []
        scores = []
        for r in rows:
            pct = round((r["final_score"] / r["max_marks"] * 100), 1) if r["max_marks"] else 0
            if r["state"] == "submitted":
                scores.append(pct)
            students.append({
                "attempt_id": r["id"],
                "student": parse_json(r["student_data_json"], {}),
                "state": r["state"],
                "needs_review": bool(r["needs_review"]),
                "ai_score": r["ai_score"],
                "final_score": r["final_score"],
                "max_marks": r["max_marks"],
                "percentage": pct
            })

        q_rows = conn.execute(
            """SELECT q.id, q.question_text, q.marks, COUNT(ans.id) AS response_count, COALESCE(AVG(ans.final_score), 0) AS average_score
               FROM assessment_questions q LEFT JOIN attempt_answers ans ON ans.question_id=q.id
               WHERE q.assessment_id=? GROUP BY q.id ORDER BY q.position""",
            (assessment_id,)
        ).fetchall()

        return self.send_json({
            "assessment": {"id": a["id"], "title": a["title"], "subject": a["subject"], "ai_grading_enabled": bool(a["ai_grading_enabled"])},
            "summary": {
                "students": len(rows),
                "submitted": len(scores),
                "average_percentage": round(sum(scores) / len(scores), 1) if scores else 0,
                "highest_percentage": max(scores) if scores else 0
            },
            "students": students,
            "question_performance": [{"question": qr["question_text"], "marks": qr["marks"], "average_score": round(qr["average_score"], 2)} for qr in q_rows]
        })

    def export_assessment_csv(self, conn: sqlite3.Connection, assessment_id: int):
        teacher = self.require_teacher(conn)
        a = conn.execute("SELECT * FROM assessments WHERE id = ? AND teacher_id = ?", (assessment_id, teacher["id"])).fetchone()
        if not a:
            raise ApiError("Assessment not found.", HTTPStatus.NOT_FOUND)

        rows = conn.execute(
            """SELECT at.id, at.student_data_json, at.state, at.needs_review, at.started_at, at.submitted_at,
                      COALESCE(SUM(ans.ai_score), 0) AS ai_score, COALESCE(SUM(ans.final_score), 0) AS final_score,
                      COALESCE(SUM(q.marks), 0) AS max_marks
               FROM attempts at
               LEFT JOIN attempt_answers ans ON ans.attempt_id=at.id
               LEFT JOIN assessment_questions q ON q.id=ans.question_id
               WHERE at.assessment_id=? GROUP BY at.id ORDER BY at.submitted_at DESC, at.started_at DESC""",
            (assessment_id,)
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Attempt ID", "Student Name", "Roll / ID Number", "State", "Needs Review", "Started At", "Submitted At", "AI Score", "Final Score", "Max Marks", "Percentage"])
        for r in rows:
            s_data = parse_json(r["student_data_json"], {})
            name = s_data.get("name", "Student")
            roll = s_data.get("roll_no", "")
            pct = round((r["final_score"] / r["max_marks"] * 100), 1) if r["max_marks"] else 0
            writer.writerow([r["id"], name, roll, r["state"], "Yes" if r["needs_review"] else "No", r["started_at"], r["submitted_at"] or "", r["ai_score"], r["final_score"], r["max_marks"], f"{pct}%"])

        csv_bytes = output.getvalue().encode("utf-8")
        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', a['title'])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{clean_title}_results.csv"')
        self.send_header("Content-Length", str(len(csv_bytes)))
        self.end_headers()
        self.wfile.write(csv_bytes)

    def teacher_attempt(self, conn: sqlite3.Connection, attempt_id: int):
        teacher = self.require_teacher(conn)
        attempt = conn.execute(
            "SELECT at.*, ass.title, ass.ai_grading_enabled FROM attempts at JOIN assessments ass ON ass.id=at.assessment_id WHERE at.id=? AND ass.teacher_id=?",
            (attempt_id, teacher["id"])
        ).fetchone()
        if not attempt:
            raise ApiError("Attempt not found.", HTTPStatus.NOT_FOUND)

        answers = conn.execute(
            """SELECT ans.*, q.question_text, q.reference_answer, q.marks
               FROM attempt_answers ans JOIN assessment_questions q ON q.id=ans.question_id
               WHERE ans.attempt_id=? ORDER BY q.position""",
            (attempt_id,)
        ).fetchall()

        return self.send_json({
            "attempt": {
                "id": attempt["id"],
                "title": attempt["title"],
                "ai_grading_enabled": bool(attempt["ai_grading_enabled"]),
                "student": parse_json(attempt["student_data_json"], {}),
                "state": attempt["state"],
                "started_at": attempt["started_at"],
                "submitted_at": attempt["submitted_at"],
                "answers": [
                    {
                        "answer_id": r["id"],
                        "question": r["question_text"],
                        "reference_answer": r["reference_answer"],
                        "marks": r["marks"],
                        "student_answer": r["answer_text"],
                        "ai_score": r["ai_score"],
                        "final_score": r["final_score"],
                        "override_reason": r["override_reason"],
                        "evaluation": parse_json(r["evaluation_json"], {})
                    }
                    for r in answers
                ]
            }
        })

    def override_mark(self, conn: sqlite3.Connection, teacher: dict, answer_id: int, payload: dict):
        row = conn.execute(
            """SELECT ans.*, q.marks FROM attempt_answers ans
               JOIN attempts at ON at.id=ans.attempt_id
               JOIN assessments ass ON ass.id=at.assessment_id
               JOIN assessment_questions q ON q.id=ans.question_id
               WHERE ans.id=? AND ass.teacher_id=?""",
            (answer_id, teacher["id"])
        ).fetchone()
        if not row:
            raise ApiError("Answer record not found.", HTTPStatus.NOT_FOUND)

        try:
            mark = round(float(payload.get("mark")), 2)
        except (TypeError, ValueError):
            raise ApiError("Enter a valid numeric mark.")

        reason = clean_text(payload.get("reason"), 1000)
        if not 0 <= mark <= row["marks"]:
            raise ApiError(f"Mark must be between 0 and {row['marks']}.")
        if not reason:
            raise ApiError("An audit reason is required for mark override.")

        conn.execute("UPDATE attempt_answers SET final_score=?, override_reason=? WHERE id=?", (mark, reason, answer_id))
        conn.execute("UPDATE attempts SET needs_review=0 WHERE id=?", (row["attempt_id"],))
        return self.send_json({"saved": True, "answer_id": answer_id, "final_score": mark, "override_reason": reason})

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

        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml"
        }.get(resolved.suffix.lower(), "application/octet-stream")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


init_database()


# ---------------------------------------------------------------------------
# WSGI Adapter for Serverless Deployment (Vercel)
# ---------------------------------------------------------------------------
class WSGIHandlerAdapter(VivaHandler):
    def __init__(self, environ, start_response):
        self.environ = environ
        self.start_response_cb = start_response
        self.client_address = (environ.get("REMOTE_ADDR", "127.0.0.1"), 0)
        self.path = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            self.path += "?" + environ["QUERY_STRING"]
        self.command = environ.get("REQUEST_METHOD", "GET")
        self.headers = {}
        for k, v in environ.items():
            if k.startswith("HTTP_"):
                self.headers[k[5:].replace("_", "-").title()] = v
            elif k in ("CONTENT_TYPE", "CONTENT_LENGTH"):
                self.headers[k.replace("_", "-").title()] = v
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
    print(f"Viva Simulator server running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
