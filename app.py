from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from google import genai
from google.genai import types
from dotenv import load_dotenv

import os
import json
import sqlite3
from datetime import datetime, timedelta


# =========================================================
# CONFIGURATION
# =========================================================

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError(
        "GEMINI_API_KEY missing. Check your .env file."
    )

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "dev-secret-key"
)

client = genai.Client(
    api_key=API_KEY
)

DATABASE = "learning.db"


# Gemini models
# Fast model first
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash"
]


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    return conn


def now():

    return datetime.now().isoformat()


def init_db():

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_no TEXT UNIQUE NOT NULL,
            language TEXT DEFAULT 'English',
            xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            topic TEXT,
            total_questions INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            wrong_answers INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0,
            time_taken INTEGER DEFAULT 0,
            status TEXT DEFAULT 'completed',
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            attempt_id INTEGER,
            question TEXT,
            selected_answer TEXT,
            correct_answer TEXT,
            is_correct INTEGER DEFAULT 0,
            topic TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            attempt_id INTEGER,
            question TEXT,
            correct_answer TEXT,
            selected_answer TEXT,
            topic TEXT,
            mistake_count INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            topic TEXT,
            attempts INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            wrong INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0,
            mastery REAL DEFAULT 0,
            last_attempt TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            badge TEXT,
            description TEXT,
            xp INTEGER DEFAULT 0,
            earned_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            topic TEXT,
            revision_count INTEGER DEFAULT 0,
            next_revision TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            question TEXT,
            created_at TEXT
        )
    """)

    conn.commit()

    conn.close()


init_db()


# =========================================================
# HELPERS
# =========================================================

def normalize_text(text):

    if text is None:
        return ""

    return " ".join(
        str(text).strip().lower().split()
    )


def clean_json_text(text):

    if not text:
        return ""

    text = text.strip()

    if text.startswith("```json"):
        text = text[7:]

    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def calculate_mastery(accuracy):

    accuracy = float(accuracy or 0)

    if accuracy >= 90:
        return 100

    if accuracy >= 80:
        return 90

    if accuracy >= 70:
        return 75

    if accuracy >= 60:
        return 60

    if accuracy >= 50:
        return 45

    if accuracy >= 40:
        return 30

    return 15


def get_previous_questions(topic, limit=20):

    conn = get_db()

    rows = conn.execute("""
        SELECT question
        FROM quiz_questions
        WHERE LOWER(TRIM(topic))
            = LOWER(TRIM(?))
        ORDER BY id DESC
        LIMIT ?
    """, (
        topic,
        limit
    )).fetchall()

    conn.close()

    return [
        row["question"]
        for row in rows
    ]


def save_generated_questions(topic, questions):

    conn = get_db()

    existing_rows = conn.execute("""
        SELECT question
        FROM quiz_questions
        WHERE LOWER(TRIM(topic))
            = LOWER(TRIM(?))
    """, (
        topic,
    )).fetchall()

    existing = {
        normalize_text(row["question"])
        for row in existing_rows
    }

    for item in questions:

        question = str(
            item.get("question", "")
        ).strip()

        if not question:
            continue

        normalized = normalize_text(question)

        if normalized in existing:
            continue

        conn.execute("""
            INSERT INTO quiz_questions
            (topic, question, created_at)
            VALUES (?, ?, ?)
        """, (
            topic,
            question,
            now()
        ))

        existing.add(normalized)

    conn.commit()

    conn.close()


def award_achievement(
    student_id,
    badge,
    description,
    xp=0
):

    conn = get_db()

    existing = conn.execute("""
        SELECT id
        FROM achievements
        WHERE student_id = ?
        AND badge = ?
    """, (
        student_id,
        badge
    )).fetchone()

    if existing:

        conn.close()

        return False

    conn.execute("""
        INSERT INTO achievements
        (student_id, badge, description, xp, earned_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        student_id,
        badge,
        description,
        xp,
        now()
    ))

    if xp > 0:

        conn.execute("""
            UPDATE students
            SET xp = xp + ?
            WHERE id = ?
        """, (
            xp,
            student_id
        ))

    conn.commit()

    conn.close()

    return True


# =========================================================
# SPACED REVISION
# =========================================================

def calculate_next_revision(revision_count):

    intervals = {
        0: 1,
        1: 3,
        2: 7,
        3: 14
    }

    days = intervals.get(
        revision_count,
        30
    )

    return (
        datetime.now()
        + timedelta(days=days)
    ).isoformat()


def schedule_revision(student_id, topic):

    conn = get_db()

    existing = conn.execute("""
        SELECT *
        FROM revisions
        WHERE student_id = ?
        AND LOWER(TRIM(topic))
            = LOWER(TRIM(?))
    """, (
        student_id,
        topic
    )).fetchone()

    if existing:

        revision_count = int(
            existing["revision_count"] or 0
        )

        next_revision = calculate_next_revision(
            revision_count
        )

        conn.execute("""
            UPDATE revisions
            SET next_revision = ?
            WHERE id = ?
        """, (
            next_revision,
            existing["id"]
        ))

    else:

        next_revision = calculate_next_revision(0)

        conn.execute("""
            INSERT INTO revisions
            (
                student_id,
                topic,
                revision_count,
                next_revision
            )
            VALUES (?, ?, 0, ?)
        """, (
            student_id,
            topic,
            next_revision
        ))

    conn.commit()

    conn.close()


def complete_revision(student_id, topic):

    conn = get_db()

    existing = conn.execute("""
        SELECT *
        FROM revisions
        WHERE student_id = ?
        AND LOWER(TRIM(topic))
            = LOWER(TRIM(?))
    """, (
        student_id,
        topic
    )).fetchone()

    if not existing:

        conn.close()

        return False

    current_count = int(
        existing["revision_count"] or 0
    )

    new_count = current_count + 1

    next_revision = calculate_next_revision(
        new_count
    )

    conn.execute("""
        UPDATE revisions
        SET
            revision_count = ?,
            next_revision = ?
        WHERE id = ?
    """, (
        new_count,
        next_revision,
        existing["id"]
    ))

    conn.commit()

    conn.close()

    return True


# =========================================================
# HOME / PAGES
# =========================================================

@app.route("/")
def home():

    return render_template("login.html")


@app.route("/learn")
def learn():

    return render_template("learn.html")


@app.route("/quiz")
def quiz():

    return render_template("quiz.html")


@app.route("/register")
def register():

    return render_template("register.html")


@app.route("/login")
def login():

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


@app.route("/profile")
def profile():

    return render_template("profile.html")


@app.route("/mistakes")
def mistakes():

    return render_template("mistakes.html")


@app.route("/adaptive")
def adaptive():

    return render_template("adaptive.html")

@app.route("/revision")
def revision():
    return render_template("revision.html")

@app.route("/result")
def result():

    return render_template("result.html")


# =========================================================
# CREATE / REGISTER STUDENT
# =========================================================

@app.route(
    "/profile",
    methods=["POST"]
)
def create_profile():

    data = (
        request.get_json(silent=True)
        or request.form
    )

    name = str(
        data.get("name", "")
    ).strip()

    roll_no = str(
        data.get("roll_no", "")
    ).strip()

    language = str(
        data.get(
            "language",
            "English"
        )
    ).strip()

    if not name or not roll_no:

        return jsonify({
            "success": False,
            "message":
                "Name and Roll Number are required."
        }), 400

    conn = get_db()

    existing = conn.execute("""
        SELECT *
        FROM students
        WHERE roll_no = ?
    """, (
        roll_no,
    )).fetchone()

    # -----------------------------------------------------
    # EXISTING STUDENT
    # -----------------------------------------------------

    if existing:

        session["student_id"] = existing["id"]
        session["student_name"] = existing["name"]
        session["roll_no"] = existing["roll_no"]

        conn.close()

        return jsonify({
            "success": True,
            "student": dict(existing),
            "message":
                "Student already exists."
        })

    # -----------------------------------------------------
    # NEW STUDENT
    # -----------------------------------------------------

    cursor = conn.execute("""
        INSERT INTO students
        (
            name,
            roll_no,
            language,
            xp,
            streak,
            created_at
        )
        VALUES (?, ?, ?, 0, 0, ?)
    """, (
        name,
        roll_no,
        language,
        now()
    ))

    student_id = cursor.lastrowid

    student = conn.execute("""
        SELECT *
        FROM students
        WHERE id = ?
    """, (
        student_id,
    )).fetchone()

    conn.commit()

    conn.close()

    session["student_id"] = student["id"]
    session["student_name"] = student["name"]
    session["roll_no"] = student["roll_no"]

    return jsonify({
        "success": True,
        "student": dict(student),
        "message":
            "Student profile created."
    })


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/api/login",
    methods=["POST"]
)
def api_login():

    data = (
        request.get_json(silent=True)
        or {}
    )

    roll_no = str(
        data.get("roll_no", "")
    ).strip()

    if not roll_no:

        return jsonify({
            "success": False,
            "message":
                "Roll Number is required."
        }), 400

    conn = get_db()

    student = conn.execute("""
        SELECT *
        FROM students
        WHERE roll_no = ?
    """, (
        roll_no,
    )).fetchone()

    conn.close()

    if not student:

        return jsonify({
            "success": False,
            "message":
                "Student not found. Please register first."
        }), 404

    # IMPORTANT SESSION FIX

    session["student_id"] = student["id"]
    session["student_name"] = student["name"]
    session["roll_no"] = student["roll_no"]

    return jsonify({
        "success": True,
        "student": dict(student)
    })


# =========================================================
# AI LEARNING GENERATOR
# =========================================================

@app.route(
    "/generate-learning",
    methods=["POST"]
)
def generate_learning():

    data = (
        request.get_json(silent=True)
        or {}
    )

    topic = str(
        data.get("topic", "")
    ).strip()

    language = str(
        data.get(
            "language",
            "English"
        )
    ).strip()

    if not topic:

        return jsonify({
            "success": False,
            "message":
                "Please enter a topic."
        }), 400

    prompt = f"""
You are an expert educational teacher.

Create a beginner-friendly but useful learning lesson.

Topic:
{topic}

Language:
{language}

Return ONLY valid JSON.

Use exactly this structure:

{{
  "topic": "{topic}",
  "title": "Lesson title",
  "summary": "Short simple summary",
  "concepts": [
    {{
      "name": "Concept name",
      "explanation": "Simple explanation"
    }}
  ],
  "examples": [
    "Example 1",
    "Example 2"
  ],
  "key_points": [
    "Key point 1",
    "Key point 2",
    "Key point 3"
  ]
}}

Rules:

1. Give 5 to 7 important concepts.
2. Explain every important concept simply.
3. Give 3 to 5 practical examples.
4. Give 5 to 7 key points.
5. Focus on exam-important concepts.
6. Use student-friendly language.
7. Do not use markdown.
8. Return only JSON.
9. Do not wrap JSON in code fences.
"""

    last_error = None

    for model_name in MODELS:

        try:

            print(
                f"Trying learning model: {model_name}"
            )

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=(
                        types.AutomaticFunctionCallingConfig(
                            disable=True
                        )
                    )
                )
            )

            text = clean_json_text(
                response.text
            )

            if not text:

                raise ValueError(
                    "Gemini returned empty response."
                )

            result = json.loads(text)

            return jsonify({
                "success": True,
                "data": result
            })

        except Exception as e:

            last_error = str(e)

            print(
                f"Learning AI error: {model_name}"
            )

            print(last_error)

    return jsonify({
        "success": False,
        "message":
            "AI learning generation failed.",
        "error": last_error
    }), 500


# =========================================================
# AI QUIZ GENERATOR
# =========================================================

@app.route(
    "/generate-quiz",
    methods=["POST"]
)
def generate_quiz():

    data = (
        request.get_json(silent=True)
        or {}
    )

    topic = str(
        data.get("topic", "")
    ).strip()

    language = str(
        data.get(
            "language",
            "English"
        )
    ).strip()

    difficulty = str(
        data.get(
            "difficulty",
            "beginner to intermediate"
        )
    ).strip()

    try:

        count = int(
            data.get("count", 5)
        )

    except Exception:

        count = 5

    # Faster safe limit

    count = max(
        5,
        min(count, 10)
    )

    if not topic:

        return jsonify({
            "success": False,
            "message":
                "Please enter a topic."
        }), 400

    # Only 20 old questions
    # to keep prompt fast

    previous_questions = get_previous_questions(
        topic,
        limit=20
    )

    if previous_questions:

        previous_text = "\n".join(
            f"{index + 1}. {question}"
            for index, question
            in enumerate(previous_questions)
        )

    else:

        previous_text = (
            "No previous questions exist."
        )

    prompt = f"""
You are an expert exam question generator.

Create exactly {count} multiple-choice questions.

Topic:
{topic}

Language:
{language}

Difficulty:
{difficulty}

IMPORTANT RULES:

1. Generate exactly {count} questions.
2. Every question must have exactly 4 options.
3. Exactly ONE option must be correct.
4. Test understanding, not memorization only.
5. Do NOT repeat previous questions.
6. Do NOT create substantially similar questions.
7. New questions must be unique.
8. Keep questions suitable for students.
9. correct_answer must exactly match one option.
10. Every option must be complete.
11. Keep explanations short.
12. Return ONLY valid JSON.
13. No markdown.
14. No code fences.

Previous questions:

{previous_text}

Return exactly:

{{
  "topic": "{topic}",
  "difficulty": "{difficulty}",
  "questions": [
    {{
      "question": "Question text",
      "options": [
        "Option A",
        "Option B",
        "Option C",
        "Option D"
      ],
      "correct_answer": "Correct option text",
      "explanation": "Short explanation"
    }}
  ]
}}
"""

    last_error = None

    for model_name in MODELS:

        try:

            print(
                f"Trying quiz model: {model_name}"
            )

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=(
                        types.AutomaticFunctionCallingConfig(
                            disable=True
                        )
                    )
                )
            )

            text = clean_json_text(
                response.text
            )

            if not text:

                raise ValueError(
                    "Gemini returned empty response."
                )

            result = json.loads(text)

            if not isinstance(result, dict):

                raise ValueError(
                    "AI response is not an object."
                )

            questions = result.get(
                "questions",
                []
            )

            if not isinstance(
                questions,
                list
            ):

                raise ValueError(
                    "AI question list missing."
                )

            valid_questions = []

            seen_questions = set()

            previous_normalized = {
                normalize_text(question)
                for question in previous_questions
            }

            for item in questions:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                question = str(
                    item.get(
                        "question",
                        ""
                    )
                ).strip()

                options = item.get(
                    "options",
                    []
                )

                correct_answer = str(
                    item.get(
                        "correct_answer",
                        ""
                    )
                ).strip()

                explanation = str(
                    item.get(
                        "explanation",
                        ""
                    )
                ).strip()

                if not question:
                    continue

                if not isinstance(
                    options,
                    list
                ):
                    continue

                if len(options) != 4:
                    continue

                options = [
                    str(option).strip()
                    for option in options
                ]

                if any(
                    not option
                    for option in options
                ):
                    continue

                normalized_options = [
                    normalize_text(option)
                    for option in options
                ]

                if len(
                    set(normalized_options)
                ) != 4:
                    continue

                normalized_correct = normalize_text(
                    correct_answer
                )

                matched_answer = None

                for option in options:

                    if normalize_text(
                        option
                    ) == normalized_correct:

                        matched_answer = option

                        break

                if matched_answer is None:
                    continue

                correct_answer = matched_answer

                normalized_question = normalize_text(
                    question
                )

                if normalized_question in seen_questions:
                    continue

                if normalized_question in previous_normalized:
                    continue

                seen_questions.add(
                    normalized_question
                )

                valid_questions.append({
                    "question": question,
                    "options": options,
                    "correct_answer": correct_answer,
                    "explanation": (
                        explanation
                        if explanation
                        else "Review the concept carefully."
                    ),
                    "topic": topic
                })

                if len(
                    valid_questions
                ) >= count:

                    break

            if len(valid_questions) < count:

                raise ValueError(
                    f"AI generated only "
                    f"{len(valid_questions)} "
                    f"valid questions out of "
                    f"{count}."
                )

            save_generated_questions(
                topic,
                valid_questions
            )

            print(
                f"Generated {len(valid_questions)} questions."
            )

            return jsonify({
                "success": True,
                "topic": topic,
                "difficulty": difficulty,
                "questions": valid_questions
            })

        except Exception as e:

            last_error = str(e)

            print(
                f"Quiz model error: {model_name}"
            )

            print(last_error)

    return jsonify({
        "success": False,
        "message":
            "AI quiz generation failed.",
        "error": last_error
    }), 500


# =========================================================
# ADAPTIVE QUIZ
# =========================================================

@app.route(
    "/api/adaptive-quiz/<int:student_id>",
    methods=["GET"]
)
def adaptive_quiz_info(student_id):

    try:

        conn = get_db()

        rows = conn.execute("""
            SELECT
                topic,
                accuracy,
                attempts
            FROM progress
            WHERE student_id = ?
            ORDER BY accuracy ASC
        """, (
            student_id,
        )).fetchall()

        conn.close()

        progress = []

        for row in rows:

            progress.append({
                "topic": row["topic"],
                "accuracy": float(
                    row["accuracy"] or 0
                ),
                "attempts": int(
                    row["attempts"] or 0
                )
            })

        if not progress:

            return jsonify({
                "success": False,
                "message":
                    "No quiz history available yet."
            })

        weak_topics = [
            item
            for item in progress
            if item["accuracy"] < 70
        ]

        if weak_topics:

            selected = weak_topics[0]

        else:

            selected = progress[0]

        accuracy = selected["accuracy"]

        if accuracy < 40:

            difficulty = "easy"

        elif accuracy < 70:

            difficulty = "medium"

        else:

            difficulty = "hard"

        return jsonify({
            "success": True,
            "topic": selected["topic"],
            "accuracy": accuracy,
            "attempts": selected["attempts"],
            "difficulty": difficulty
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# =========================================================
# START ATTEMPT
# =========================================================

@app.route(
    "/api/attempt/start",
    methods=["POST"]
)
def start_attempt():

    data = (
        request.get_json(silent=True)
        or {}
    )

    try:

        student_id = int(
            data.get("student_id")
        )

    except Exception:

        return jsonify({
            "success": False,
            "message":
                "Invalid student ID."
        }), 400

    topic = str(
        data.get("topic", "")
    ).strip()

    try:

        total_questions = int(
            data.get(
                "total_questions",
                0
            )
        )

    except Exception:

        total_questions = 0

    if not topic:

        return jsonify({
            "success": False,
            "message":
                "Topic is required."
        }), 400

    conn = get_db()

    student = conn.execute("""
        SELECT id
        FROM students
        WHERE id = ?
    """, (
        student_id,
    )).fetchone()

    if not student:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Student not found."
        }), 404

    cursor = conn.execute("""
        INSERT INTO attempts
        (
            student_id,
            topic,
            total_questions,
            correct_answers,
            wrong_answers,
            score,
            accuracy,
            time_taken,
            status,
            created_at
        )
        VALUES (
            ?, ?, ?, 0, 0, 0, 0, 0, 'started', ?
        )
    """, (
        student_id,
        topic,
        total_questions,
        now()
    ))

    attempt_id = cursor.lastrowid

    conn.commit()

    conn.close()

    return jsonify({
        "success": True,
        "attempt_id": attempt_id
    })


# =========================================================
# SUBMIT ATTEMPT
# =========================================================

@app.route(
    "/api/attempt/submit",
    methods=["POST"]
)
def submit_attempt():

    data = (
        request.get_json(silent=True)
        or {}
    )

    try:

        attempt_id = int(
            data.get("attempt_id")
        )

        student_id = int(
            data.get("student_id")
        )

    except Exception:

        return jsonify({
            "success": False,
            "message":
                "Invalid attempt or student ID."
        }), 400

    topic = str(
        data.get("topic", "")
    ).strip()

    answers_data = data.get(
        "answers",
        []
    )

    try:

        time_taken = int(
            data.get(
                "time_taken",
                0
            )
        )

    except Exception:

        time_taken = 0

    if not isinstance(
        answers_data,
        list
    ):

        return jsonify({
            "success": False,
            "message":
                "Invalid answers."
        }), 400

    conn = get_db()

    attempt = conn.execute("""
        SELECT *
        FROM attempts
        WHERE id = ?
        AND student_id = ?
    """, (
        attempt_id,
        student_id
    )).fetchone()

    if not attempt:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Attempt not found."
        }), 404

    if attempt["status"] == "completed":

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "This attempt is already submitted."
        }), 400

    correct_count = 0

    wrong_count = 0

    review = []

    for answer in answers_data:

        if not isinstance(
            answer,
            dict
        ):
            continue

        question = str(
            answer.get(
                "question",
                ""
            )
        ).strip()

        selected_answer = str(
            answer.get(
                "selected_answer",
                ""
            )
        ).strip()

        correct_answer = str(
            answer.get(
                "correct_answer",
                ""
            )
        ).strip()

        explanation = str(
            answer.get(
                "explanation",
                ""
            )
        ).strip()

        question_topic = str(
            answer.get(
                "topic",
                topic
            )
        ).strip()

        is_correct = (
            normalize_text(
                selected_answer
            )
            ==
            normalize_text(
                correct_answer
            )
            and
            normalize_text(
                correct_answer
            ) != ""
        )

        if is_correct:

            correct_count += 1

        else:

            wrong_count += 1

        conn.execute("""
            INSERT INTO answers
            (
                student_id,
                attempt_id,
                question,
                selected_answer,
                correct_answer,
                is_correct,
                topic,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_id,
            attempt_id,
            question,
            selected_answer,
            correct_answer,
            1 if is_correct else 0,
            question_topic,
            now()
        ))

        # -------------------------------------------------
        # MISTAKE NOTEBOOK
        # -------------------------------------------------

        if not is_correct:

            existing_mistake = conn.execute("""
                SELECT *
                FROM mistakes
                WHERE student_id = ?
                AND question = ?
                AND topic = ?
            """, (
                student_id,
                question,
                question_topic
            )).fetchone()

            if existing_mistake:

                conn.execute("""
                    UPDATE mistakes
                    SET
                        mistake_count =
                            mistake_count + 1,
                        selected_answer = ?,
                        correct_answer = ?,
                        attempt_id = ?,
                        created_at = ?
                    WHERE id = ?
                """, (
                    selected_answer,
                    correct_answer,
                    attempt_id,
                    now(),
                    existing_mistake["id"]
                ))

            else:

                conn.execute("""
                    INSERT INTO mistakes
                    (
                        student_id,
                        attempt_id,
                        question,
                        correct_answer,
                        selected_answer,
                        topic,
                        mistake_count,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    student_id,
                    attempt_id,
                    question,
                    correct_answer,
                    selected_answer,
                    question_topic,
                    now()
                ))

        review.append({
            "question": question,
            "selected_answer": selected_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "explanation": explanation,
            "topic": question_topic
        })

    total = len(answers_data)

    if total > 0:

        accuracy = (
            correct_count / total
        ) * 100

    else:

        accuracy = 0

    score = correct_count

    xp_earned = correct_count * 10

    # -----------------------------------------------------
    # UPDATE ATTEMPT
    # -----------------------------------------------------

    conn.execute("""
        UPDATE attempts
        SET
            total_questions = ?,
            correct_answers = ?,
            wrong_answers = ?,
            score = ?,
            accuracy = ?,
            time_taken = ?,
            status = 'completed'
        WHERE id = ?
    """, (
        total,
        correct_count,
        wrong_count,
        score,
        accuracy,
        time_taken,
        attempt_id
    ))

    # -----------------------------------------------------
    # UPDATE XP
    # -----------------------------------------------------

    conn.execute("""
        UPDATE students
        SET xp = xp + ?
        WHERE id = ?
    """, (
        xp_earned,
        student_id
    ))

    # -----------------------------------------------------
    # UPDATE PROGRESS
    # -----------------------------------------------------

    progress_row = conn.execute("""
        SELECT *
        FROM progress
        WHERE student_id = ?
        AND LOWER(TRIM(topic))
            = LOWER(TRIM(?))
    """, (
        student_id,
        topic
    )).fetchone()

    if progress_row:

        new_attempts = (
            progress_row["attempts"] + 1
        )

        new_correct = (
            progress_row["correct"]
            + correct_count
        )

        new_wrong = (
            progress_row["wrong"]
            + wrong_count
        )

        total_answered = (
            new_correct
            + new_wrong
        )

        if total_answered > 0:

            new_accuracy = (
                new_correct
                / total_answered
            ) * 100

        else:

            new_accuracy = 0

        new_mastery = calculate_mastery(
            new_accuracy
        )

        conn.execute("""
            UPDATE progress
            SET
                attempts = ?,
                correct = ?,
                wrong = ?,
                accuracy = ?,
                mastery = ?,
                last_attempt = ?
            WHERE id = ?
        """, (
            new_attempts,
            new_correct,
            new_wrong,
            new_accuracy,
            new_mastery,
            now(),
            progress_row["id"]
        ))

    else:

        mastery = calculate_mastery(
            accuracy
        )

        conn.execute("""
            INSERT INTO progress
            (
                student_id,
                topic,
                attempts,
                correct,
                wrong,
                accuracy,
                mastery,
                last_attempt
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
        """, (
            student_id,
            topic,
            correct_count,
            wrong_count,
            accuracy,
            mastery,
            now()
        ))

    conn.commit()

    conn.close()

    # -----------------------------------------------------
    # SPACED REVISION
    # -----------------------------------------------------

    schedule_revision(
        student_id,
        topic
    )

    # -----------------------------------------------------
    # ACHIEVEMENTS
    # -----------------------------------------------------

    award_achievement(
        student_id,
        "First Quiz",
        "Completed your first quiz.",
        20
    )

    if total > 0 and correct_count == total:

        award_achievement(
            student_id,
            "Perfect Score",
            "Completed a quiz with 100% accuracy.",
            50
        )

    if total > 0 and accuracy >= 80:

        award_achievement(
            student_id,
            "High Achiever",
            "Scored 80% or higher on a quiz.",
            30
        )

    return jsonify({
        "success": True,
        "attempt_id": attempt_id,
        "total_questions": total,
        "correct_answers": correct_count,
        "wrong_answers": wrong_count,
        "score": score,
        "accuracy": round(
            accuracy,
            2
        ),
        "xp_earned": xp_earned,
        "review": review
    })


# =========================================================
# AUTO RE-TEST
# =========================================================

@app.route(
    "/api/retest-quiz/<int:attempt_id>",
    methods=["POST"]
)
def auto_retest_quiz(attempt_id):

    data = (
        request.get_json(silent=True)
        or {}
    )

    student_id = data.get(
        "student_id"
    )

    try:

        count = int(
            data.get(
                "count",
                5
            )
        )

    except Exception:

        count = 5

    count = max(
        5,
        min(count, 10)
    )

    language = str(
        data.get(
            "language",
            "English"
        )
    )

    conn = get_db()

    attempt = conn.execute("""
        SELECT *
        FROM attempts
        WHERE id = ?
    """, (
        attempt_id,
    )).fetchone()

    if not attempt:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Quiz attempt not found."
        }), 404

    wrong_answers = conn.execute("""
        SELECT *
        FROM answers
        WHERE attempt_id = ?
        AND is_correct = 0
        ORDER BY id ASC
    """, (
        attempt_id,
    )).fetchall()

    conn.close()

    if not wrong_answers:

        return jsonify({
            "success": False,
            "message":
                "No mistakes found. Auto Re-Test is not required."
        }), 400

    mistake_context = []

    for item in wrong_answers:

        mistake_context.append({
            "question": item["question"],
            "wrong_answer": item["selected_answer"],
            "correct_answer": item["correct_answer"],
            "topic": item["topic"]
        })

    prompt = f"""
You are an AI exam question generator.

Create a new practice re-test based ONLY on the concepts
the student answered incorrectly.

Topic:
{attempt["topic"]}

Language:
{language}

Number of questions:
{count}

Student mistakes:

{json.dumps(
    mistake_context,
    ensure_ascii=False
)}

IMPORTANT RULES:

1. Generate EXACTLY {count} questions.
2. Test the SAME concepts the student got wrong.
3. Do NOT copy the original questions.
4. Make questions different but conceptually related.
5. Exactly 4 options per question.
6. Only ONE option can be correct.
7. correct_answer must match one option.
8. Keep explanations short.
9. Return ONLY valid JSON.
10. No markdown.
11. No code fences.

JSON format:

[
  {{
    "question": "New question",
    "options": [
      "Option 1",
      "Option 2",
      "Option 3",
      "Option 4"
    ],
    "correct_answer": "Correct option",
    "explanation": "Short explanation",
    "topic": "{attempt["topic"]}"
  }}
]
"""

    last_error = None

    for model_name in MODELS:

        try:

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    automatic_function_calling=(
                        types.AutomaticFunctionCallingConfig(
                            disable=True
                        )
                    )
                )
            )

            text = clean_json_text(
                response.text
            )

            questions = json.loads(
                text
            )

            if not isinstance(
                questions,
                list
            ):

                raise ValueError(
                    "AI response is not a list."
                )

            valid_questions = []

            seen_questions = set()

            for q in questions:

                if not isinstance(
                    q,
                    dict
                ):
                    continue

                question = str(
                    q.get(
                        "question",
                        ""
                    )
                ).strip()

                options = q.get(
                    "options",
                    []
                )

                correct_answer = str(
                    q.get(
                        "correct_answer",
                        ""
                    )
                ).strip()

                explanation = str(
                    q.get(
                        "explanation",
                        ""
                    )
                ).strip()

                question_topic = str(
                    q.get(
                        "topic",
                        attempt["topic"]
                    )
                ).strip()

                if not question:
                    continue

                if not isinstance(
                    options,
                    list
                ):
                    continue

                if len(options) != 4:
                    continue

                options = [
                    str(option).strip()
                    for option in options
                ]

                if any(
                    not option
                    for option in options
                ):
                    continue

                normalized_options = [
                    normalize_text(option)
                    for option in options
                ]

                if len(
                    set(normalized_options)
                ) != 4:
                    continue

                normalized_correct = normalize_text(
                    correct_answer
                )

                matched_answer = None

                for option in options:

                    if normalize_text(
                        option
                    ) == normalized_correct:

                        matched_answer = option

                        break

                if matched_answer is None:
                    continue

                correct_answer = matched_answer

                normalized_question = normalize_text(
                    question
                )

                if normalized_question in seen_questions:
                    continue

                seen_questions.add(
                    normalized_question
                )

                valid_questions.append({
                    "question": question,
                    "options": options,
                    "correct_answer": correct_answer,
                    "explanation": (
                        explanation
                        if explanation
                        else "Review this concept carefully."
                    ),
                    "topic": question_topic
                })

                if len(
                    valid_questions
                ) >= count:

                    break

            if len(valid_questions) < count:

                raise ValueError(
                    f"AI generated only "
                    f"{len(valid_questions)} "
                    f"valid re-test questions."
                )

            return jsonify({
                "success": True,
                "message":
                    "AI Auto Re-Test generated successfully.",
                "attempt_id": attempt_id,
                "student_id": student_id,
                "topic": attempt["topic"],
                "questions": valid_questions
            })

        except Exception as e:

            last_error = str(e)

            print(
                f"Retest error: {model_name}"
            )

            print(last_error)

    return jsonify({
        "success": False,
        "message":
            "AI Auto Re-Test failed.",
        "error": last_error
    }), 500


# =========================================================
# GET ATTEMPT
# =========================================================

@app.route(
    "/api/attempt/<int:attempt_id>",
    methods=["GET"]
)
def get_attempt(attempt_id):

    conn = get_db()

    attempt = conn.execute("""
        SELECT *
        FROM attempts
        WHERE id = ?
    """, (
        attempt_id,
    )).fetchone()

    if not attempt:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Attempt not found."
        }), 404

    answers = conn.execute("""
        SELECT *
        FROM answers
        WHERE attempt_id = ?
        ORDER BY id ASC
    """, (
        attempt_id,
    )).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "attempt": dict(attempt),
        "answers": [
            dict(answer)
            for answer in answers
        ]
    })


# =========================================================
# STUDENT PROGRESS
# =========================================================

@app.route(
    "/api/student/<int:student_id>/progress",
    methods=["GET"]
)
def student_progress(student_id):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM progress
        WHERE student_id = ?
        ORDER BY last_attempt DESC
    """, (
        student_id,
    )).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "progress": [
            dict(row)
            for row in rows
        ]
    })


# =========================================================
# STUDENT MISTAKES
# =========================================================

@app.route(
    "/api/student/<int:student_id>/mistakes",
    methods=["GET"]
)
def student_mistakes(student_id):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM mistakes
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (
        student_id,
    )).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "mistakes": [
            dict(row)
            for row in rows
        ]
    })


# =========================================================
# STUDENT PROFILE DATA
# =========================================================

@app.route(
    "/api/student/<int:student_id>",
    methods=["GET"]
)
def student_data(student_id):

    conn = get_db()

    student = conn.execute("""
        SELECT *
        FROM students
        WHERE id = ?
    """, (
        student_id,
    )).fetchone()

    if not student:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Student not found."
        }), 404

    attempts = conn.execute("""
        SELECT *
        FROM attempts
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (
        student_id,
    )).fetchall()

    achievements = conn.execute("""
        SELECT *
        FROM achievements
        WHERE student_id = ?
        ORDER BY earned_at DESC
    """, (
        student_id,
    )).fetchall()

    progress = conn.execute("""
        SELECT *
        FROM progress
        WHERE student_id = ?
        ORDER BY accuracy ASC
    """, (
        student_id,
    )).fetchall()

    mistakes_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM mistakes
        WHERE student_id = ?
    """, (
        student_id,
    )).fetchone()

    revisions = conn.execute("""
        SELECT *
        FROM revisions
        WHERE student_id = ?
        ORDER BY next_revision ASC
    """, (
        student_id,
    )).fetchall()

    conn.close()

    return jsonify({
        "success": True,

        "student":
            dict(student),

        "attempts": [
            dict(row)
            for row in attempts
        ],

        "achievements": [
            dict(row)
            for row in achievements
        ],

        "progress": [
            dict(row)
            for row in progress
        ],

        "mistakes_count":
            int(
                mistakes_count["total"]
            ),

        "revisions": [
            dict(row)
            for row in revisions
        ]
    })

# =========================================================
# SPACED REVISION API
# =========================================================

@app.route(
    "/api/student/<int:student_id>/revisions",
    methods=["GET"]
)
def student_revisions(student_id):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM revisions
        WHERE student_id = ?
        ORDER BY next_revision ASC
    """, (
        student_id,
    )).fetchall()

    conn.close()

    current_time = datetime.now()

    revisions = []

    for row in rows:

        next_revision = row["next_revision"]

        try:
            revision_date = datetime.fromisoformat(
                next_revision
            )

            is_due = revision_date <= current_time

        except Exception:

            is_due = False

        revisions.append({
            "id": row["id"],
            "topic": row["topic"],
            "revision_count": int(
                row["revision_count"] or 0
            ),
            "next_revision": next_revision,
            "is_due": is_due
        })

    return jsonify({
        "success": True,
        "revisions": revisions
    })


@app.route(
    "/api/revision/<int:revision_id>/complete",
    methods=["POST"]
)
def revision_complete(revision_id):

    data = (
        request.get_json(silent=True)
        or {}
    )

    try:

        student_id = int(
            data.get("student_id")
        )

    except Exception:

        return jsonify({
            "success": False,
            "message": "Invalid student ID."
        }), 400

    conn = get_db()

    revision = conn.execute("""
        SELECT *
        FROM revisions
        WHERE id = ?
        AND student_id = ?
    """, (
        revision_id,
        student_id
    )).fetchone()

    conn.close()

    if not revision:

        return jsonify({
            "success": False,
            "message": "Revision not found."
        }), 404

    success = complete_revision(
        student_id,
        revision["topic"]
    )

    if not success:

        return jsonify({
            "success": False,
            "message":
                "Could not complete revision."
        }), 500

    award_achievement(
        student_id,
        "Revision Master",
        "Completed a spaced revision session.",
        10
    )

    return jsonify({
        "success": True,
        "message":
            "Revision completed successfully."
    })
# =========================================================
# LEADERBOARD
# =========================================================

@app.route(
    "/api/leaderboard",
    methods=["GET"]
)
def leaderboard():

    conn = get_db()

    rows = conn.execute("""
        SELECT
            id,
            name,
            roll_no,
            xp
        FROM students
        ORDER BY xp DESC
        LIMIT 100
    """).fetchall()

    conn.close()

    leaderboard_data = []

    for index, row in enumerate(rows):

        leaderboard_data.append({
            "rank": index + 1,
            "id": row["id"],
            "name": row["name"],
            "roll_no": row["roll_no"],
            "xp": row["xp"]
        })

    return jsonify({
        "success": True,
        "leaderboard":
            leaderboard_data
    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "app":
            "AI Learning + Quiz",
        "time": now()
    })


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def page_not_found(error):

    return jsonify({
        "success": False,
        "message":
            "Page or API endpoint not found."
    }), 404


@app.errorhandler(500)
def internal_server_error(error):

    return jsonify({
        "success": False,
        "message":
            "Internal server error."
    }), 500


# =========================================================
# RUN APP
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )