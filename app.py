from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
import json


# ==========================================
# SETUP
# ==========================================

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError(
        "GEMINI_API_KEY missing. Check your .env file."
    )

app = Flask(__name__)

client = genai.Client(api_key=API_KEY)


# We use fallback models.
# If one model is temporarily busy, another is tried.
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite"
]


# ==========================================
# PAGES
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/learn")
def learn():
    return render_template("learn.html")


@app.route("/quiz")
def quiz():
    return render_template("quiz.html")


@app.route("/result")
def result():
    return render_template("result.html")


# ==========================================
# LEARNING GENERATOR
# ==========================================

@app.route("/generate-learning", methods=["POST"])
def generate_learning():

    try:

        data = request.get_json()

        topic = data.get("topic", "").strip()

        if not topic:
            return jsonify({
                "error": "Please enter a topic."
            }), 400


        prompt = f"""
You are an expert AI tutor.

Create beginner-friendly learning material about:

{topic}

Use these sections:

SIMPLE EXPLANATION
KEY POINTS
REAL-LIFE EXAMPLE
IMPORTANT TERMS
QUICK SUMMARY

Make it simple, clear and useful for students.
"""


        last_error = None


        for model in MODELS:

            try:

                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )

                return jsonify({
                    "result": response.text
                })

            except Exception as e:

                print(
                    f"Learning model failed: {model}",
                    repr(e)
                )

                last_error = e


        raise last_error


    except Exception as e:

        print(
            "LEARNING ERROR:",
            repr(e)
        )

        return jsonify({
            "error": str(e)
        }), 500


# ==========================================
# QUIZ GENERATOR
# ==========================================

@app.route("/generate-quiz", methods=["POST"])
def generate_quiz():

    try:

        data = request.get_json()

        topic = data.get(
            "topic",
            ""
        ).strip()


        # Get selected number
        question_count = int(
            data.get(
                "question_count",
                10
            )
        )


        # Allowed values
        allowed_counts = [
            5, 10, 15, 20, 25,
            30, 35, 40, 45, 50
        ]


        if question_count not in allowed_counts:

            return jsonify({
                "error":
                "Please select 5, 10, 15, 20, 25, 30, 35, 40, 45 or 50 questions."
            }), 400


        if not topic:

            return jsonify({
                "error":
                "Please enter a topic."
            }), 400


        # ==================================
        # QUIZ PROMPT
        # ==================================

        prompt = f"""
Create exactly {question_count} multiple choice questions
about this topic:

{topic}

The quiz is for beginner students.

Each question MUST have:

- question
- exactly 4 options
- answer
- explanation

The answer must be a number:

0 = first option
1 = second option
2 = third option
3 = fourth option

Make questions different from each other.

Make the questions educational.

Return ONLY valid JSON.

Do not return markdown.

Do not return ```json.

Do not write anything outside the JSON.

The JSON must be an array containing exactly {question_count} objects.

Example:

[
  {{
    "question": "What is AI?",
    "options": [
      "Artificial Intelligence",
      "Automatic Internet",
      "Advanced Interface",
      "None"
    ],
    "answer": 0,
    "explanation": "AI stands for Artificial Intelligence."
  }}
]
"""


        # ==================================
        # JSON SCHEMA
        # ==================================

        quiz_schema = {
            "type": "array",

            "items": {

                "type": "object",

                "properties": {

                    "question": {
                        "type": "string"
                    },

                    "options": {

                        "type": "array",

                        "items": {
                            "type": "string"
                        }
                    },

                    "answer": {
                        "type": "integer"
                    },

                    "explanation": {
                        "type": "string"
                    }

                },

                "required": [
                    "question",
                    "options",
                    "answer",
                    "explanation"
                ]
            }
        }


        # ==================================
        # TRY MULTIPLE MODELS
        # ==================================

        last_error = None


        for model in MODELS:

            try:

                print(
                    f"Trying quiz model: {model}"
                )


                response = client.models.generate_content(

                    model=model,

                    contents=prompt,

                    config=types.GenerateContentConfig(

                        response_mime_type=
                        "application/json",

                        response_schema=
                        quiz_schema
                    )
                )


                # Parse AI response
                questions = json.loads(
                    response.text
                )


                # ==================================
                # VALIDATION
                # ==================================

                if not isinstance(
                    questions,
                    list
                ):

                    raise ValueError(
                        "AI did not return a list."
                    )


                if len(questions) != question_count:

                    raise ValueError(
                        f"AI returned "
                        f"{len(questions)} questions "
                        f"instead of "
                        f"{question_count}."
                    )


                for question in questions:

                    if "question" not in question:
                        raise ValueError(
                            "Question text missing."
                        )


                    if "options" not in question:
                        raise ValueError(
                            "Options missing."
                        )


                    if len(
                        question["options"]
                    ) != 4:

                        raise ValueError(
                            "Every question needs exactly 4 options."
                        )


                    if question["answer"] not in [
                        0, 1, 2, 3
                    ]:

                        raise ValueError(
                            "Invalid answer index."
                        )


                    if "explanation" not in question:

                        raise ValueError(
                            "Explanation missing."
                        )


                print(
                    f"Quiz generated successfully "
                    f"using {model}"
                )


                return jsonify({
                    "questions":
                    questions
                })


            except Exception as e:

                print(
                    f"Quiz model failed: {model}",
                    repr(e)
                )

                last_error = e


        # All models failed
        raise last_error


    except Exception as e:

        print(
            "QUIZ ERROR:",
            repr(e)
        )


        return jsonify({

            "error":
            "Quiz generation failed: "
            + str(e)

        }), 500


# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":

    app.run(
        debug=True
    )