(() => {
    const root = document.documentElement;
    const storage = {
        get(key, fallback) {
            try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
        },
        set(key, value) {
            try { localStorage.setItem(key, value); } catch { /* Storage can be disabled by the browser. */ }
        },
    };

    const savedTheme = storage.get("zhang-theme", "");
    const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    root.dataset.theme = savedTheme || preferredTheme;
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
        root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
        storage.set("zhang-theme", root.dataset.theme);
    });

    const toggles = [...document.querySelectorAll("[data-display-toggle]")];
    const presets = {
        hanzi: ["hanzi"],
        pinyin: ["pinyin"],
        meaning: ["meaning"],
        "hanzi-pinyin": ["hanzi", "pinyin"],
        "hanzi-pinyin-meaning": ["hanzi", "pinyin", "meaning"],
    };
    const presetSelect = document.getElementById("display-preset");
    let savedDisplay = ["hanzi", "pinyin", "meaning"];
    try {
        const parsedDisplay = JSON.parse(storage.get("lin-display", "null"));
        if (Array.isArray(parsedDisplay)) savedDisplay = parsedDisplay;
    } catch { /* Ignore malformed local preferences. */ }
    if (toggles.length) {
        toggles.forEach((toggle) => { toggle.checked = savedDisplay.includes(toggle.dataset.displayToggle); });
    }

    function applyDisplaySettings() {
        const enabled = new Set(toggles.length
            ? toggles.filter((toggle) => toggle.checked).map((toggle) => toggle.dataset.displayToggle)
            : savedDisplay);
        document.querySelectorAll(".language-line[data-language]").forEach((line) => {
            line.classList.toggle("is-hidden", !enabled.has(line.dataset.language));
        });
        if (presetSelect) {
            const selected = Object.entries(presets).find(([, values]) => values.length === enabled.size && values.every((value) => enabled.has(value)));
            presetSelect.value = selected?.[0] || "custom";
        }
        if (toggles.length) {
            savedDisplay = [...enabled];
            storage.set("zhang-display", JSON.stringify(savedDisplay));
        }
    }

    toggles.forEach((toggle) => toggle.addEventListener("change", applyDisplaySettings));
    presetSelect?.addEventListener("change", () => {
        if (!presets[presetSelect.value]) return;
        toggles.forEach((toggle) => { toggle.checked = presets[presetSelect.value].includes(toggle.dataset.displayToggle); });
        applyDisplaySettings();
    });
    applyDisplaySettings();

    const progressBar = document.querySelector(".progress-bar");

    document.querySelectorAll("[data-practice-tab]").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll("[data-practice-tab]").forEach((item) => item.classList.toggle("active", item === tab));
            document.querySelectorAll("[data-practice-pane]").forEach((pane) => {
                const active = pane.dataset.practicePane === tab.dataset.practiceTab;
                pane.classList.toggle("active", active);
                pane.hidden = !active;
            });
        });
    });

    let vocabulary = [];
    try { vocabulary = JSON.parse(document.getElementById("vocabulary-data")?.textContent || "[]"); } catch { vocabulary = []; }
    const flashcard = document.getElementById("flashcard");
    const position = document.getElementById("card-position");
    let cardIndex = 0;
    function showCard(index) {
        if (!flashcard || !vocabulary.length) return;
        cardIndex = (index + vocabulary.length) % vocabulary.length;
        const word = vocabulary[cardIndex];
        flashcard.classList.remove("flipped");
        flashcard.querySelector(".card-hanzi").textContent = word.hanzi;
        flashcard.querySelector(".card-pinyin").textContent = word.pinyin;
        flashcard.querySelector(".card-meaning").textContent = word.meaning;
        flashcard.querySelector(".card-english").textContent = word.english;
        position.textContent = `${String(cardIndex + 1).padStart(2, "0")} / ${String(vocabulary.length).padStart(2, "0")}`;
    }
    flashcard?.addEventListener("click", () => flashcard.classList.toggle("flipped"));
    document.getElementById("next-card")?.addEventListener("click", () => showCard(cardIndex + 1));
    document.getElementById("previous-card")?.addEventListener("click", () => showCard(cardIndex - 1));

    const options = document.getElementById("quiz-options");
    const quizNext = document.getElementById("quiz-next");
    let currentQuestion;
    let quizCorrect = 0;
    let answered = false;
    function startQuestion() {
        if (!options || vocabulary.length < 4) return;
        answered = false;
        currentQuestion = vocabulary[Math.floor(Math.random() * vocabulary.length)];
        document.getElementById("quiz-hanzi").textContent = currentQuestion.hanzi;
        document.getElementById("quiz-pinyin").textContent = currentQuestion.pinyin;
        document.getElementById("quiz-feedback").textContent = "";
        document.getElementById("quiz-feedback").classList.remove("incorrect");
        quizNext.hidden = true;
        const answer = currentQuestion.meaning.split(";")[0].trim();
        const distractors = vocabulary
            .filter((word) => word.hanzi !== currentQuestion.hanzi)
            .map((word) => word.meaning.split(";")[0].trim())
            .filter((meaning, index, all) => meaning !== answer && all.indexOf(meaning) === index);
        const choices = [answer, ...distractors.sort(() => Math.random() - 0.5).slice(0, 3)].sort(() => Math.random() - 0.5);
        options.replaceChildren(...choices.map((meaning) => {
            const button = document.createElement("button");
            button.className = "quiz-option";
            button.type = "button";
            button.textContent = meaning;
            button.addEventListener("click", () => submitAnswer(button, meaning === answer));
            return button;
        }));
    }

    async function submitAnswer(selected, isCorrect) {
        if (answered) return;
        answered = true;
        options.querySelectorAll("button").forEach((button) => { button.disabled = true; });
        selected.classList.add(isCorrect ? "correct" : "incorrect");
        const feedback = document.getElementById("quiz-feedback");
        if (isCorrect) {
            quizCorrect += 1;
            feedback.textContent = "Tepat sekali. Kata ini mulai melekat.";
        } else {
            feedback.textContent = `Belum tepat. Artinya: ${currentQuestion.meaning}.`;
            feedback.classList.add("incorrect");
            [...options.children].find((button) => button.textContent === currentQuestion.meaning.split(";")[0].trim())?.classList.add("correct");
        }
        document.getElementById("quiz-score").textContent = `${quizCorrect} benar`;
        quizNext.hidden = false;
        try {
            const response = await fetch("/practice/answer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    csrf_token: document.querySelector('meta[name="csrf-token"]').content,
                    hanzi: currentQuestion.hanzi,
                    correct: isCorrect,
                }),
            });
            if (!response.ok) throw new Error("Could not save the answer");
            const progress = await response.json();
            document.getElementById("total-reviews").textContent = progress.total_reviews;
            document.getElementById("accuracy-value").textContent = progress.accuracy;
            progressBar.value = progress.accuracy;
            progressBar.setAttribute("aria-label", `Akurasi kuis ${progress.accuracy} persen`);
            document.getElementById("progress-message").textContent = "Bagus! Ulangi kata yang terasa sulit agar makin melekat.";
        } catch {
            feedback.textContent += " Progress belum tersimpan; periksa koneksi lalu coba lagi.";
        }
    }

    quizNext?.addEventListener("click", startQuestion);
    startQuestion();
})();
