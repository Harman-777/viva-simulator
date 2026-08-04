const setupForm = document.querySelector("#setupForm");
const subjectSelect = document.querySelector("#subjectSelect");
const levelSelect = document.querySelector("#levelSelect");
const candidateName = document.querySelector("#candidateName");
const customSubjectInput = document.querySelector("#customSubjectInput");
const addSubjectButton = document.querySelector("#addSubjectButton");
const apiKeyInput = document.querySelector("#apiKeyInput");
const onlineModeInput = document.querySelector("#onlineModeInput");
const apiStatus = document.querySelector("#apiStatus");
const questionCounter = document.querySelector("#questionCounter");
const progressFraction = document.querySelector("#progressFraction");
const progressTrack = document.querySelector("#progressTrack");
const progressBar = document.querySelector("#progressBar");
const questionKicker = document.querySelector("#questionKicker");
const questionText = document.querySelector("#questionText");
const answerInput = document.querySelector("#answerInput");
const wordCount = document.querySelector("#wordCount");
const answerHint = document.querySelector("#answerHint");
const difficultyBadge = document.querySelector("#difficultyBadge");
const evaluateButton = document.querySelector("#evaluateButton");
const nextButton = document.querySelector("#nextButton");
const validationMessage = document.querySelector("#validationMessage");
const feedbackOutput = document.querySelector("#feedbackOutput");
const reportOutput = document.querySelector("#reportOutput");
const reportButton = document.querySelector("#reportButton");
const lastScore = document.querySelector("#lastScore");
const confidenceScore = document.querySelector("#confidenceScore");
const readinessLabel = document.querySelector("#readinessLabel");
const completedCount = document.querySelector("#completedCount");
const scoreDetail = document.querySelector("#scoreDetail");
const confidenceDetail = document.querySelector("#confidenceDetail");
const readinessDetail = document.querySelector("#readinessDetail");
const completedDetail = document.querySelector("#completedDetail");
const engineStatus = document.querySelector("#engineStatus");
const vivaNotesSection = document.querySelector("#vivaNotesSection");
const vivaNotesContent = document.querySelector("#vivaNotesContent");

let questions = [];
let currentIndex = 0;
let evaluations = [];
let currentEvaluation = null;

setupForm.addEventListener("submit", event => {
  event.preventDefault();
  startSession();
});
evaluateButton.addEventListener("click", evaluateCurrentAnswer);
nextButton.addEventListener("click", nextQuestion);
reportButton.addEventListener("click", generateReport);
addSubjectButton.addEventListener("click", addCustomSubject);
if (onlineModeInput) {
  onlineModeInput.addEventListener("change", updateApiStatus);
}
if (apiKeyInput) {
  apiKeyInput.addEventListener("input", updateApiStatus);
}
answerInput.addEventListener("input", updateWordCount);
levelSelect.addEventListener("change", updateDifficultyContext);

async function startSession() {
  const subject = subjectSelect.value;
  const level = levelSelect.value;
  const apiKey = apiKeyInput ? apiKeyInput.value.trim() : "";
  const startButton = setupForm.querySelector('button[type="submit"]');

  validationMessage.textContent = "";
  apiStatus.textContent = "Generating your question set with AI…";
  startButton.disabled = true;

  try {
    const response = await fetch("/api/generate-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, level, api_key: apiKey })
    });
    if (!response.ok) throw new Error("Question generation failed");

    const payload = await response.json();
    if (!Array.isArray(payload.questions) || payload.questions.length === 0) {
      throw new Error("No questions returned");
    }

    questions = payload.questions;
    currentIndex = 0;
    evaluations = [];
    currentEvaluation = null;
    difficultyBadge.textContent = labelForLevel(level);
    updateDifficultyContext();
    updateMetrics();
    showQuestion();

    if (engineStatus) engineStatus.textContent = "AI active";
    apiStatus.textContent = `Questions are ready for ${subject}.`;
    feedbackOutput.className = "feedback-output empty-state";
    feedbackOutput.textContent = "Your evaluation will break down what worked, what was missing, and how to give a sharper answer next time.";
    reportOutput.className = "report-output empty-state";
    reportOutput.textContent = "Complete one or more questions to create a concise professor-style readiness report.";
    reportButton.disabled = true;
  } catch (error) {
    apiStatus.textContent = "We could not create the session. Check AI configuration or server connection.";
    validationMessage.textContent = "Session could not be started. Please try again.";
  } finally {
    startButton.disabled = false;
  }
}

function addCustomSubject() {
  const value = customSubjectInput.value.trim();
  if (!value) {
    apiStatus.textContent = "Enter a subject name before adding it.";
    customSubjectInput.focus();
    return;
  }

  const exists = Array.from(subjectSelect.options).some(option => option.value.toLowerCase() === value.toLowerCase());
  if (!exists) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    subjectSelect.append(option);
  }
  subjectSelect.value = value;
  customSubjectInput.value = "";
  apiStatus.textContent = `${value} is selected. Create a session when you are ready.`;
}

function shouldUseOnline() {
  return apiKeyInput && apiKeyInput.value.trim().length > 0;
}

function updateApiStatus() {
  if (shouldUseOnline()) {
    apiStatus.textContent = "Cloud API key configured for AI evaluation.";
    if (engineStatus) engineStatus.textContent = "AI active";
  } else {
    apiStatus.textContent = "Enter an API Key or set environment AI key for evaluation.";
    if (engineStatus) engineStatus.textContent = "AI ready";
  }
}

function showQuestion() {
  const current = questions[currentIndex];
  if (!current) {
    questionCounter.textContent = "Session complete";
    progressFraction.textContent = `${evaluations.length} of ${questions.length}`;
    setProgress(questions.length, questions.length);
    questionKicker.textContent = "YOU MADE IT";
    questionText.textContent = "You have completed every question. Generate your readiness report to see where to focus next.";
    answerInput.value = "";
    answerInput.disabled = true;
    evaluateButton.disabled = true;
    nextButton.disabled = true;
    reportButton.disabled = evaluations.length === 0;
    vivaNotesSection.style.display = "none";
    updateWordCount();
    return;
  }

  questionCounter.textContent = `Question ${currentIndex + 1} of ${questions.length}`;
  progressFraction.textContent = `${currentIndex + 1} of ${questions.length}`;
  setProgress(currentIndex, questions.length);
  questionKicker.textContent = `${subjectSelect.value.toUpperCase()} · QUESTION ${String(currentIndex + 1).padStart(2, "0")}`;
  questionText.textContent = current.question;
  answerInput.value = "";
  answerInput.disabled = false;
  evaluateButton.disabled = false;
  nextButton.disabled = true;
  validationMessage.textContent = "";
  updateWordCount();

  const questionId = current.id || `${subjectSelect.value}-${levelSelect.value}-${currentIndex}`;
  const savedNote = typeof getNote === "function" ? getNote(questionId) : "";
  if (savedNote) {
    vivaNotesSection.style.display = "block";
    vivaNotesContent.textContent = savedNote;
  } else {
    vivaNotesSection.style.display = "none";
    vivaNotesContent.textContent = "No note saved for this question.";
  }
}

async function evaluateCurrentAnswer() {
  const answer = answerInput.value.trim();
  const current = questions[currentIndex];
  if (!answer) {
    validationMessage.textContent = "Write an answer before requesting feedback.";
    answerInput.focus();
    return;
  }
  if (!current || currentEvaluation) return;

  validationMessage.textContent = "Reviewing your answer…";
  evaluateButton.disabled = true;

  try {
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: subjectSelect.value,
        level: levelSelect.value,
        question: current.question,
        answer,
        expected_keywords: current.expected_keywords,
        model_answer: current.model_answer,
        api_key: shouldUseOnline() ? apiKeyInput.value.trim() : ""
      })
    });
    if (!response.ok) throw new Error("Evaluation failed");

    const result = await response.json();
    currentEvaluation = { ...result, question: current.question, answer, subject: subjectSelect.value, level: levelSelect.value };
    evaluations.push(currentEvaluation);
    renderFeedback(currentEvaluation);
    updateMetrics();
    setProgress(currentIndex + 1, questions.length);
    validationMessage.textContent = "Feedback is ready. Review it, then continue when you are ready.";
    nextButton.disabled = false;
    reportButton.disabled = false;
    if (engineStatus) engineStatus.textContent = result.engine ? `AI active (${result.engine})` : "AI active";
  } catch (error) {
    validationMessage.textContent = "We could not evaluate this answer. Please try again.";
    evaluateButton.disabled = false;
  }
}

function renderFeedback(result) {
  const strengths = Array.isArray(result.strengths) ? result.strengths : [];
  const gaps = Array.isArray(result.gaps) ? result.gaps : [];
  feedbackOutput.className = "feedback-output";
  feedbackOutput.innerHTML = `
    <article class="feedback-card">
      <h3>${escapeHtml(result.readiness)} · ${Number(result.score) || 0}% score</h3>
      <p>${escapeHtml(result.feedback || "Your response has been reviewed.")}</p>
      <p><strong>${escapeHtml(result.quality_band || "Rubric evaluated")}</strong></p>
    </article>
    <article class="feedback-card">
      <h3>What worked</h3>
      <ul>${strengths.map(item => `<li>${escapeHtml(item)}</li>`).join("") || "<li>Keep building on this answer.</li>"}</ul>
    </article>
    <article class="feedback-card">
      <h3>What to sharpen</h3>
      <ul>${gaps.map(item => `<li>${escapeHtml(item)}</li>`).join("") || "<li>No major gap detected.</li>"}</ul>
    </article>
    <article class="feedback-card">
      <h3>A stronger answer</h3>
      <p>${escapeHtml(result.model_answer || "No model answer is available for this question.")}</p>
    </article>
  `;
}

function nextQuestion() {
  currentIndex += 1;
  currentEvaluation = null;
  showQuestion();
}

async function generateReport() {
  reportButton.disabled = true;
  reportButton.textContent = "Generating report…";
  try {
    const response = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate: candidateName.value.trim() || "Student", subject: subjectSelect.value, level: levelSelect.value, evaluations })
    });
    if (!response.ok) throw new Error("Report failed");
    renderReport(await response.json());
  } catch (error) {
    reportOutput.className = "report-output empty-state";
    reportOutput.textContent = "We could not generate the report. Please try again.";
  } finally {
    reportButton.disabled = evaluations.length === 0;
    reportButton.innerHTML = "Generate readiness report <span aria-hidden=\"true\">→</span>";
  }
}

function renderReport(report) {
  const topics = Array.isArray(report.weak_topics) ? report.weak_topics : [];
  const weakTopics = topics.length
    ? topics.map(topic => `<li>${escapeHtml(topic)}</li>`).join("")
    : "<li>No weak topic detected from completed answers.</li>";
  reportOutput.className = "report-output";
  reportOutput.innerHTML = `
    <article class="report-card">
      <h3>${escapeHtml(candidateName.value.trim() || "Student")} · ${escapeHtml(subjectSelect.value)}</h3>
      <p>${escapeHtml(report.summary || "Your practice session is complete.")}</p>
    </article>
    <article class="report-card">
      <h3>Final readiness: ${escapeHtml(report.readiness || "Developing")} (${Number(report.average_score) || 0}%)</h3>
      <p>${escapeHtml(report.professor_note || "Review your feedback and focus on the recurring gaps.")}</p>
    </article>
    <article class="report-card">
      <h3>Focus next</h3>
      <ul>${weakTopics}</ul>
    </article>
  `;
}

function updateMetrics() {
  const count = evaluations.length;
  const average = count ? Math.round(evaluations.reduce((sum, item) => sum + Number(item.score || 0), 0) / count) : 0;
  const confidenceAverage = count ? Math.round(evaluations.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / count) : 0;
  const last = evaluations[count - 1];

  completedCount.textContent = count;
  lastScore.textContent = last ? `${last.score}%` : "—";
  confidenceScore.textContent = last ? `${last.confidence}%` : "—";
  readinessLabel.textContent = last ? last.readiness : "Waiting";
  scoreDetail.textContent = last ? (last.quality_band || "Latest answer") : "Waiting for your first answer";
  confidenceDetail.textContent = last ? `${confidenceAverage}% average evidence` : "Your evidence quality";
  readinessDetail.textContent = count ? readinessFromAverage(average) : "Start a practice session";
  completedDetail.textContent = questions.length ? `${count} of ${questions.length} evaluated` : "0 of 6 evaluated";
}

function updateWordCount() {
  const count = answerInput.value.trim() ? answerInput.value.trim().split(/\s+/).length : 0;
  wordCount.textContent = `${count} ${count === 1 ? "word" : "words"}`;
}

function updateDifficultyContext() {
  const level = levelSelect.value;
  difficultyBadge.textContent = labelForLevel(level);
  const guidance = {
    easy: "Keep it simple: define the concept, then give one short example.",
    medium: "Aim for a definition, how it works, and one practical example.",
    hard: "Show depth: explain the idea, tradeoffs, limitations, and a useful example."
  };
  answerHint.textContent = guidance[level] || guidance.medium;
}

function setProgress(value, total) {
  const safeTotal = total || 6;
  const percentage = Math.max(0, Math.min(100, (value / safeTotal) * 100));
  progressBar.style.width = `${percentage}%`;
  progressTrack.setAttribute("aria-valuemax", safeTotal);
  progressTrack.setAttribute("aria-valuenow", Math.min(value, safeTotal));
}

function labelForLevel(level) {
  return level ? `${level.charAt(0).toUpperCase()}${level.slice(1)}` : "Medium";
}

function readinessFromAverage(average) {
  if (average >= 85) return "Ready for a tough viva";
  if (average >= 70) return "Ready with light revision";
  if (average >= 45) return "Practise weak answers";
  return "Build the core concepts";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

updateDifficultyContext();
updateApiStatus();
updateWordCount();
