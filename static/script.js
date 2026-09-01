function generateLearning() {

    let topic = document.getElementById("topic").value;

    if (topic === "") {

        alert("Please enter a topic.");

        return;
    }

    document.getElementById("learningResult").innerHTML =

        "<br><br>" +

        "<div class='card'>" +

        "<h2>" + topic + "</h2>" +

        "<p>" +
        "AI learning material for " +
        topic +
        " will appear here." +
        "</p>" +

        "<br>" +

        "<a href='/quiz' class='btn'>" +
        "Take Quiz" +
        "</a>" +

        "</div>";
}


function submitQuiz() {

    let answer =
        document.querySelector(
            'input[name="q1"]:checked'
        );

    if (!answer) {

        alert("Please select an answer.");

        return;
    }

    let score = Number(answer.value);

    document.getElementById("score").innerHTML =
        "Your Score: " + score + " / 1";

}