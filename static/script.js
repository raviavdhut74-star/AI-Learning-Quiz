```javascript
async function generateLearning() {
    const topicInput = document.getElementById("topic");
    const result = document.getElementById("learningResult");

    if (!topicInput || !result) {
        return;
    }

    const topic = topicInput.value.trim();

    if (!topic) {
        alert("Please enter a topic.");
        return;
    }

    result.innerHTML =
        '<div class="card">' +
        '<h2>🧠 ' + escapeHTML(topic) + '</h2>' +
        '<p>Generating learning material...</p>' +
        '</div>';

    try {
        const response = await fetch("/generate-learning", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                topic: topic,
                language: "English"
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.message || "Failed to generate learning material."
            );
        }

        const learning = data.data;

        if (!learning || typeof learning !== "object") {
            throw new Error("Invalid learning data received.");
        }

        let html = "";

        html += '<div class="card learning-card">';

        html +=
            '<h2>🧠 ' +
            escapeHTML(
                learning.title ||
                learning.topic ||
                topic
            ) +
            '</h2>';

        // Summary
        if (learning.summary) {
            html += '<div class="learning-summary">';
            html += '<h3>📖 Summary</h3>';
            html +=
                '<p>' +
                escapeHTML(String(learning.summary)) +
                '</p>';
            html += '</div>';
        }

        // Important Concepts
        if (
            Array.isArray(learning.concepts) &&
            learning.concepts.length > 0
        ) {
            html += '<div class="important-concepts">';
            html += '<h3>🧠 Important Concepts</h3>';
            html += '<div class="concept-list">';

            learning.concepts.forEach(function (concept, index) {
                let name = "Important Concept";
                let explanation = "";

                if (
                    concept &&
                    typeof concept === "object"
                ) {
                    name =
                        concept.name ||
                        concept.title ||
                        concept.concept ||
                        "Important Concept";

                    explanation =
                        concept.explanation ||
                        concept.description ||
                        "";
                } else {
                    name = String(concept);
                }

                html += '<div class="concept-card">';

                html +=
                    '<span class="concept-number">' +
                    (index + 1) +
                    '</span>';

                html +=
                    '<h4>💡 ' +
                    escapeHTML(String(name)) +
                    '</h4>';

                if (explanation) {
                    html +=
                        '<p>' +
                        escapeHTML(String(explanation)) +
                        '</p>';
                }

                html += '</div>';
            });

            html += '</div>';
            html += '</div>';
        }

        // Examples
        if (
            Array.isArray(learning.examples) &&
            learning.examples.length > 0
        ) {
            html += '<div class="learning-examples">';
            html += '<h3>📝 Examples</h3>';
            html += '<ul>';

            learning.examples.forEach(function (example) {
                let text;

                if (
                    example &&
                    typeof example === "object"
                ) {
                    text =
                        example.text ||
                        example.example ||
                        example.description ||
                        JSON.stringify(example);
                } else {
                    text = String(example);
                }

                html +=
                    '<li>' +
                    escapeHTML(text) +
                    '</li>';
            });

            html += '</ul>';
            html += '</div>';
        }

        // Key Points
        if (
            Array.isArray(learning.key_points) &&
            learning.key_points.length > 0
        ) {
            html += '<div class="key-points">';
            html += '<h3>⭐ Key Points</h3>';
            html += '<ul>';

            learning.key_points.forEach(function (point) {
                let text;

                if (
                    point &&
                    typeof point === "object"
                ) {
                    text =
                        point.text ||
                        point.point ||
                        point.description ||
                        JSON.stringify(point);
                } else {
                    text = String(point);
                }

                html +=
                    '<li>' +
                    escapeHTML(text) +
                    '</li>';
            });

            html += '</ul>';
            html += '</div>';
        }

        // Quiz button
        html += '<div class="learning-actions">';

        html +=
            '<a href="/quiz" class="btn">' +
            '🎯 Take Quiz' +
            '</a>';

        html += '</div>';

        html += '</div>';

        result.innerHTML = html;

    } catch (error) {
        console.error("Learning error:", error);

        result.innerHTML =
            '<div class="card error-card">' +
            '<h2>❌ Error</h2>' +
            '<p>' +
            escapeHTML(error.message) +
            '</p>' +
            '<button class="btn" onclick="generateLearning()">' +
            '🔄 Try Again' +
            '</button>' +
            '</div>';
    }
}


function submitQuiz() {
    const answer = document.querySelector(
        'input[name="q1"]:checked'
    );

    if (!answer) {
        alert("Please select an answer.");
        return;
    }

    const score = Number(answer.value);

    const scoreElement =
        document.getElementById("score");

    if (scoreElement) {
        scoreElement.innerHTML =
            "Your Score: " +
            score +
            " / 1";
    }
}


function formatText(text) {
    return escapeHTML(String(text))
        .replace(/\n\n/g, "<br><br>")
        .replace(/\n/g, "<br>");
}


function escapeHTML(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
```
