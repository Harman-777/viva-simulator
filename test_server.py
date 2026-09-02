"""
=============================================================================
VIVA SIMULATOR — Comprehensive Automated Test Suite
Unit & Integration Testing for API Endpoints, DB Models, Auth, and Routing
=============================================================================
"""

import base64
import gc
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import server


def call_api(method: str, path: str, body: dict = None, cookie: str = None) -> tuple[int, dict]:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw_body)),
        "wsgi.input": io.BytesIO(raw_body),
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie

    captured = {}
    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    result = server.app(environ, start_response)
    status_code = int(captured["status"].split(" ")[0])
    resp_text = b"".join(result).decode("utf-8")
    try:
        data = json.loads(resp_text)
    except Exception:
        data = {"raw": resp_text}
    return status_code, data


class TestVivaSimulatorCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db_path = Path(cls.tmp_dir.name) / "test_viva.db"
        server.DATABASE_PATH = cls.db_path
        server.DATA_DIR = Path(cls.tmp_dir.name)
        server.init_database()

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        try:
            cls.tmp_dir.cleanup()
        except Exception:
            pass

    def test_01_database_init_and_seeding(self):
        with server.database() as conn:
            teachers = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
            self.assertGreaterEqual(teachers, 1)
            row = conn.execute("SELECT * FROM teachers WHERE email='teacher@example.com'").fetchone()
            self.assertIsNotNone(row)
            self.assertTrue(server.valid_password("password", row["password_hash"], row["password_salt"]))

    def test_02_password_hashing_and_verification(self):
        h, s = server.password_record("supersecret123")
        self.assertTrue(server.valid_password("supersecret123", h, s))
        self.assertFalse(server.valid_password("wrongpassword", h, s))

    def test_03_session_token_signing_and_verification(self):
        payload = {"id": 42, "email": "prof@university.edu", "display_name": "Prof Turing", "exp": 9999999999}
        token = server.sign_session_payload(payload)
        verified = server.verify_session_payload(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["id"], 42)
        self.assertEqual(verified["email"], "prof@university.edu")

        # Tampered signature
        tampered = token[:-4] + "abcd"
        self.assertIsNone(server.verify_session_payload(tampered))

    def test_04_ollama_url_normalization(self):
        self.assertEqual(
            server.normalize_ai_endpoint("http://localhost:11434"),
            "http://localhost:11434/v1/chat/completions"
        )
        self.assertEqual(
            server.normalize_ai_endpoint("http://localhost:11434/v1"),
            "http://localhost:11434/v1/chat/completions"
        )
        self.assertEqual(
            server.normalize_ai_endpoint("http://localhost:11434/v1/chat/completions"),
            "http://localhost:11434/v1/chat/completions"
        )
        self.assertEqual(
            server.normalize_ai_endpoint(""),
            server.OPENAI_ENDPOINT
        )

    def test_04b_gemini_key_detection(self):
        # AI Studio new key format: AQ.Ab8RN...
        self.assertTrue(server.is_gemini_key_or_model("AQ.Ab8RN1234567890", "", ""))
        # AI Studio standard key format: AIzaSy...
        self.assertTrue(server.is_gemini_key_or_model("AIzaSy1234567890", "", ""))
        # Gemini model name
        self.assertTrue(server.is_gemini_key_or_model("any_key_value", "", "gemini-1.5-flash"))
        # OpenAI key
        self.assertFalse(server.is_gemini_key_or_model("sk-proj-123456", "", "gpt-4o-mini"))
        # Local LLM with base_url
        self.assertFalse(server.is_gemini_key_or_model("", "http://localhost:11434", "qwen2.5-coder:3b"))

    def test_05_document_extraction(self):
        # Plain text
        raw_txt = b"Core operating system concepts: scheduling, paging, virtual memory."
        res_txt = server.extract_material("notes.txt", "text/plain", raw_txt)
        self.assertIn("virtual memory", res_txt)

        # Markdown
        raw_md = b"# Viva Notes\n- Process vs Thread\n- Deadlocks"
        res_md = server.extract_material("notes.md", "text/markdown", raw_md)
        self.assertIn("Process vs Thread", res_md)

        # Python Code
        raw_py = b"def bubble_sort(arr):\n    pass"
        res_py = server.extract_material("algo.py", "text/x-python", raw_py)
        self.assertIn("bubble_sort", res_py)

    def test_06_evaluate_answer_non_answers(self):
        # Blank or non-answer should get 0 score without calling AI
        res = server.evaluate_answer(
            question="Explain virtual memory.",
            answer="idk",
            max_marks=10.0,
            reference_answer="Virtual memory abstracts physical RAM using paging.",
            key_concepts=["paging", "virtual address", "page table"]
        )
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["correctness"], "incorrect")
        self.assertIn("dimension_scores", res)
        self.assertEqual(res["dimension_scores"]["precision"], 0.0)

    @patch("server.ask_ai")
    def test_07_evaluate_answer_rubric_scoring(self, mock_ask):
        mock_ask.return_value = {
            "score": 8.5,
            "precision_score": 1.8,
            "clarity_score": 1.7,
            "evidence_score": 1.5,
            "keywords_score": 3.5,
            "correctness": "correct",
            "confidence": "high",
            "feedback": "Strong explanation with accurate terminology.",
            "covered_concepts": ["virtual memory", "paging", "page fault"],
            "missing_concepts": [],
            "rationale": "High precision definition and clear concrete example.",
            "model_answer": "Virtual memory maps virtual to physical addresses."
        }

        res = server.evaluate_answer(
            question="Explain virtual memory.",
            answer="Virtual memory creates an illusion of large continuous memory using paging and page tables.",
            max_marks=10.0,
            api_key="test-key"
        )
        self.assertEqual(res["score"], 8.5)
        self.assertEqual(res["percentage"], 85.0)
        self.assertEqual(res["dimension_scores"]["precision"], 1.8)
        self.assertEqual(res["dimension_scores"]["keywords"], 3.5)
        self.assertEqual(res["correctness"], "correct")

    def test_08_assessment_crud_and_duplication(self):
        with server.database() as conn:
            teacher = conn.execute("SELECT * FROM teachers WHERE email='teacher@example.com'").fetchone()

            # Create assessment
            cur = conn.execute(
                """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, ai_grading_enabled, question_ordering, status, created_at, updated_at)
                   VALUES (?, 'OS Midterm', 'Operating Systems', 'Answer clearly', 25, 'fixed', 2, 2, '[]', 1, 1, 'fixed', 'published', ?, ?)""",
                (teacher["id"], server.now(), server.now())
            )
            ass_id = cur.lastrowid

            conn.execute(
                "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, 'What is paging?', 'Memory management scheme', 10, 1)",
                (ass_id,)
            )
            conn.execute(
                "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, 'What is deadlock?', 'Mutual exclusion hold wait', 10, 2)",
                (ass_id,)
            )

            # Verify questions count
            q_count = conn.execute("SELECT COUNT(*) FROM assessment_questions WHERE assessment_id = ?", (ass_id,)).fetchone()[0]
            self.assertEqual(q_count, 2)

            # Test Duplication
            cur_dup = conn.execute(
                """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, ai_grading_enabled, question_ordering, status, created_at, updated_at)
                   VALUES (?, 'OS Midterm (Copy)', 'Operating Systems', 'Answer clearly', 25, 'fixed', 2, 2, '[]', 1, 1, 'fixed', 'draft', ?, ?)""",
                (teacher["id"], server.now(), server.now())
            )
            dup_id = cur_dup.lastrowid
            questions = conn.execute("SELECT question_text, reference_answer, marks, position FROM assessment_questions WHERE assessment_id = ? ORDER BY position", (ass_id,)).fetchall()
            conn.executemany(
                "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, ?, ?, ?, ?)",
                [(dup_id, q["question_text"], q["reference_answer"], q["marks"], q["position"]) for q in questions]
            )

            dup_q_count = conn.execute("SELECT COUNT(*) FROM assessment_questions WHERE assessment_id = ?", (dup_id,)).fetchone()[0]
            self.assertEqual(dup_q_count, 2)

            # Test Delete
            conn.execute("DELETE FROM assessments WHERE id = ?", (dup_id,))
            deleted_check = conn.execute("SELECT COUNT(*) FROM assessments WHERE id = ?", (dup_id,)).fetchone()[0]
            self.assertEqual(deleted_check, 0)

    @patch("server.ask_ai")
    def test_09_full_student_exam_and_mark_override_lifecycle(self, mock_ask):
        mock_ask.return_value = {
            "score": 9.0,
            "precision_score": 1.9,
            "clarity_score": 1.8,
            "evidence_score": 1.8,
            "keywords_score": 3.5,
            "correctness": "correct",
            "confidence": "high",
            "feedback": "Flawless technical articulation.",
            "covered_concepts": ["deadlock", "resource allocation"],
            "missing_concepts": [],
            "model_answer": "Deadlock is a state where processes wait indefinitely for resources."
        }

        with server.database() as conn:
            teacher = conn.execute("SELECT * FROM teachers WHERE email='teacher@example.com'").fetchone()

            # Create assessment and share
            cur = conn.execute(
                """INSERT INTO assessments (teacher_id, title, subject, instructions, duration_minutes, question_count_mode, question_count_min, question_count_max, student_fields_json, show_results, ai_grading_enabled, question_ordering, status, created_at, updated_at)
                   VALUES (?, 'Lifecycle Exam', 'Computer Science', 'Follow instructions', 15, 'fixed', 1, 1, '[{"key":"name","label":"Name"},{"key":"roll_no","label":"Roll"}]', 1, 1, 'fixed', 'published', ?, ?)""",
                (teacher["id"], server.now(), server.now())
            )
            ass_id = cur.lastrowid
            q_cur = conn.execute(
                "INSERT INTO assessment_questions (assessment_id, question_text, reference_answer, marks, position) VALUES (?, 'Explain deadlock avoidance using Banker algorithm.', 'Safe state allocation', 10, 1)",
                (ass_id,)
            )
            q_id = q_cur.lastrowid

            share_token = "share_test_xyz"
            share_cur = conn.execute(
                "INSERT INTO share_links (assessment_id, token, is_active, created_at) VALUES (?, ?, 1, ?)",
                (ass_id, share_token, server.now())
            )
            share_id = share_cur.lastrowid

            # 1. Start student attempt
            attempt_token = "att_test_abc"
            cur_att = conn.execute(
                """INSERT INTO attempts (assessment_id, share_link_id, access_token, student_data_json, selected_question_ids_json, state, started_at)
                   VALUES (?, ?, ?, '{"name":"Ada Lovelace","roll_no":"CS101"}', ?, 'in_progress', ?)""",
                (ass_id, share_id, attempt_token, json.dumps([q_id]), server.now())
            )
            att_id = cur_att.lastrowid

            # 2. Save answer draft
            conn.execute(
                """INSERT INTO attempt_answers (attempt_id, question_id, answer_text, ai_score, final_score, evaluation_json, override_reason, evaluated_at)
                   VALUES (?, ?, 'Banker algorithm tests for safety by simulating maximum resource allocation before granting requests.', 9.0, 9.0, '{}', '', ?)""",
                (att_id, q_id, server.now())
            )

        # 3. Simulate public attempt fetch (checking remaining_seconds)
        status, data = call_api("GET", f"/api/public/attempts/{attempt_token}")
        self.assertEqual(status, 200)
        self.assertIn("remaining_seconds", data["attempt"])
        self.assertEqual(data["attempt"]["student"]["name"], "Ada Lovelace")

        # 4. Submit attempt
        status, sub_data = call_api("POST", f"/api/public/attempts/{attempt_token}/submit")
        self.assertEqual(status, 200)

        # 5. Teacher Manual Mark Override via API with session cookie
        with server.database() as conn:
            ans_row = conn.execute("SELECT id, final_score FROM attempt_answers WHERE attempt_id = ?", (att_id,)).fetchone()
            ans_id = ans_row["id"]

        session_token = server.sign_session_payload({
            "id": teacher["id"],
            "email": teacher["email"],
            "display_name": teacher["display_name"],
            "exp": 9999999999
        })
        cookie_header = f"viva_teacher_session={session_token}"

        status, over_data = call_api(
            "POST",
            f"/api/teacher/answers/{ans_id}/override",
            {"mark": 9.5, "reason": "Accurate explanation of safe state"},
            cookie=cookie_header
        )
        self.assertEqual(status, 200)

        with server.database() as conn:
            updated_ans = conn.execute("SELECT final_score, override_reason FROM attempt_answers WHERE id = ?", (ans_id,)).fetchone()
            self.assertEqual(updated_ans["final_score"], 9.5)
            self.assertEqual(updated_ans["override_reason"], "Accurate explanation of safe state")

    def test_10_ai_test_ping_endpoint(self):
        # AI test endpoint with local URL (will attempt test and return json)
        status, data = call_api("POST", "/api/ai/test", {
            "api_key": "",
            "base_url": "http://127.0.0.1:11434",
            "model_name": "test-model"
        })
        # Should be a valid HTTP response (either connected or handled connection error)
        self.assertIn(status, [200, 400, 502])

    def test_11_wsgi_app_dispatch(self):
        status, data = call_api("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "healthy")

    def test_12_fast_raw_text_and_material_ingestion(self):
        owner = "test_owner_speed_123"
        raw_notes = "Deadlock conditions: Mutual Exclusion, Hold and Wait, No Preemption, Circular Wait. Banker's Algorithm ensures safe state."

        # Test direct raw_text ingestion
        status, data = call_api("POST", "/api/library/materials", {
            "owner_key": owner,
            "file_name": "Operating_Systems_Unit3.txt",
            "raw_text": raw_notes
        })
        self.assertEqual(status, 200)
        self.assertIn("material", data)
        self.assertEqual(data["material"]["file_name"], "Operating_Systems_Unit3.txt")
        self.assertGreater(data["material"]["character_count"], 50)

        # Test listing library materials with indexed owner_key
        status, list_data = call_api("GET", f"/api/library/materials?owner_key={owner}")
        self.assertEqual(status, 200)
        self.assertEqual(len(list_data["materials"]), 1)
        self.assertEqual(list_data["materials"][0]["file_name"], "Operating_Systems_Unit3.txt")


if __name__ == "__main__":
    unittest.main()

