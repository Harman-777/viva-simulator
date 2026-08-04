// questions.js - Personal Study Library and AI Practice Workspace logic

// API Key & Local Model support: read from localStorage
const API_KEY_STORAGE = "viva_student_api_key";
const BASE_URL_STORAGE = "viva_student_base_url";
const MODEL_NAME_STORAGE = "viva_student_model_name";

function getApiHeaders() {
  const headers = { "Content-Type": "application/json" };
  const key = localStorage.getItem(API_KEY_STORAGE);
  const url = localStorage.getItem(BASE_URL_STORAGE);
  const model = localStorage.getItem(MODEL_NAME_STORAGE);
  if (key) headers["X-Api-Key"] = key;
  if (url) headers["X-Base-Url"] = url;
  if (model) headers["X-Model-Name"] = model;
  return headers;
}

// Ensure owner_key exists in localStorage to identify the student session privately
const OWNER_STORAGE_KEY = "viva_library_owner_key";
let ownerKey = localStorage.getItem(OWNER_STORAGE_KEY);
if (!ownerKey) {
  ownerKey = "owner_" + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
  localStorage.setItem(OWNER_STORAGE_KEY, ownerKey);
}

// Private Local Notes Storage Key
const NOTES_STORAGE_KEY = `viva_private_notes_${ownerKey}`;

// DOM Elements
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const uploadStatus = document.getElementById("uploadStatus");
const materialList = document.getElementById("materialList");
const noteText = document.getElementById("noteText");
const saveNoteBtn = document.getElementById("saveNoteBtn");
const noteSavedItems = document.getElementById("noteSavedItems");

const setupView = document.getElementById("setupView");
const practiceView = document.getElementById("practiceView");
const practiceLevel = document.getElementById("practiceLevel");
const practiceCount = document.getElementById("practiceCount");
const customCountWrapper = document.getElementById("customCountWrapper");
const customCountInput = document.getElementById("customCountInput");
const generateBtn = document.getElementById("generateBtn");
const practiceError = document.getElementById("practiceError");

const practiceProgress = document.getElementById("practiceProgress");
const practiceBadge = document.getElementById("practiceBadge");
const practiceProgressBar = document.getElementById("practiceProgressBar");
const practiceQuestionText = document.getElementById("practiceQuestionText");
const practiceAnswer = document.getElementById("practiceAnswer");
const practiceWordCount = document.getElementById("practiceWordCount");
const submitAnswerBtn = document.getElementById("submitAnswerBtn");
const nextPracticeBtn = document.getElementById("nextPracticeBtn");
const evaluationStatus = document.getElementById("evaluationStatus");
const exitPracticeBtn = document.getElementById("exitPracticeBtn");

const practiceFeedback = document.getElementById("practiceFeedback");
const feedbackScoreBadge = document.getElementById("feedbackScoreBadge");
const feedbackExplanation = document.getElementById("feedbackExplanation");
const feedbackCovered = document.getElementById("feedbackCovered");
const feedbackMissing = document.getElementById("feedbackMissing");
const feedbackModelAnswer = document.getElementById("feedbackModelAnswer");

// AI settings panel elements
const apiKeyInput = document.getElementById("apiKeyInput");
const baseUrlInput = document.getElementById("baseUrlInput");
const modelNameInput = document.getElementById("modelNameInput");
const toggleKeyBtn = document.getElementById("toggleKeyBtn");
const saveKeyBtn = document.getElementById("saveKeyBtn");
const apiDot = document.getElementById("apiDot");
const apiStatusText = document.getElementById("apiStatusText");

// State
let uploadedMaterials = [];
let generatedQuestions = [];
let currentQuestionIndex = 0;
let selectedMaterialTexts = ""; // Combined text context for evaluation

// Notes State Manager
function loadLocalNotes() {
  try {
    return JSON.parse(localStorage.getItem(NOTES_STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}
function saveLocalNotes(notes) {
  localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(notes));
}

// ----------------------------------------------------
// AI Model Settings Panel Logic
// ----------------------------------------------------
function initApiKeyPanel() {
  if (!saveKeyBtn) return;

  function sanitizeAutofill() {
    const savedKey = localStorage.getItem(API_KEY_STORAGE) || "";
    const savedUrl = localStorage.getItem(BASE_URL_STORAGE) || "";
    const savedModel = localStorage.getItem(MODEL_NAME_STORAGE) || "";

    if (apiKeyInput) {
      if (!savedKey && apiKeyInput.value) {
        apiKeyInput.value = "";
      } else if (savedKey) {
        apiKeyInput.value = savedKey;
      }
    }
    if (baseUrlInput) {
      baseUrlInput.value = savedUrl;
    }
    if (modelNameInput) {
      // Scrub browser autofilled email if user has no saved model name
      if (!savedModel && (modelNameInput.value.includes("@") || modelNameInput.value.includes("."))) {
        modelNameInput.value = "";
      } else if (savedModel) {
        modelNameInput.value = savedModel;
      } else {
        modelNameInput.value = "";
      }
    }
    updateApiKeyStatus(savedKey, savedUrl, savedModel);
  }

  sanitizeAutofill();
  setTimeout(sanitizeAutofill, 80);
  setTimeout(sanitizeAutofill, 250);
  setTimeout(sanitizeAutofill, 600);
  window.addEventListener("pageshow", sanitizeAutofill);

  if (toggleKeyBtn && apiKeyInput) {
    toggleKeyBtn.addEventListener("click", () => {
      if (apiKeyInput.type === "password") {
        apiKeyInput.type = "text";
        toggleKeyBtn.textContent = "Hide";
      } else {
        apiKeyInput.type = "password";
        toggleKeyBtn.textContent = "Show";
      }
    });
  }

  saveKeyBtn.addEventListener("click", () => {
    const key = apiKeyInput ? apiKeyInput.value.trim() : "";
    const url = baseUrlInput ? baseUrlInput.value.trim() : "";
    const model = modelNameInput ? modelNameInput.value.trim() : "";

    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);

    if (url) localStorage.setItem(BASE_URL_STORAGE, url);
    else localStorage.removeItem(BASE_URL_STORAGE);

    if (model) localStorage.setItem(MODEL_NAME_STORAGE, model);
    else localStorage.removeItem(MODEL_NAME_STORAGE);

    updateApiKeyStatus(key, url, model);
  });
}

function updateApiKeyStatus(key, url, model) {
  if (!apiDot || !apiStatusText) return;
  if (url) {
    apiDot.style.background = "var(--green)";
    apiDot.style.boxShadow = "0 0 0 3px #d9f8eb";
    apiStatusText.textContent = `Local model active: ${model || 'default'} @ ${url}`;
    apiStatusText.style.color = "var(--green)";
  } else if (key) {
    apiDot.style.background = "var(--green)";
    apiDot.style.boxShadow = "0 0 0 3px #d9f8eb";
    apiStatusText.textContent = "Cloud API key active for generation & evaluation.";
    apiStatusText.style.color = "var(--green)";
  } else {
    apiDot.style.background = "var(--muted)";
    apiDot.style.boxShadow = "0 0 0 3px #e9edf3";
    apiStatusText.textContent = "No custom AI settings configured. Add your local model or cloud key above.";
    apiStatusText.style.color = "var(--muted)";
  }
}

// ----------------------------------------------------
// Init and Materials Fetch
// ----------------------------------------------------
async function fetchMaterials() {
  // Defensive: if ownerKey is somehow empty, show friendly message
  if (!ownerKey) {
    materialList.innerHTML = `<div class="empty-state" style="min-height: 80px; padding: 16px; font-size:12px;">Session unavailable. Please refresh the page.</div>`;
    return;
  }
  try {
    const res = await fetch(`/api/library/materials?owner_key=${encodeURIComponent(ownerKey)}`, {
      headers: getApiHeaders()
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || "Server error");
    }
    const data = await res.json();
    uploadedMaterials = data.materials || [];
    renderMaterials();
  } catch (err) {
    // Show a friendlier message instead of "Could not load your uploaded files"
    materialList.innerHTML = `<div class="empty-state" style="min-height: 80px; padding: 16px; font-size:12px;">No study files found. Upload a document below to get started.</div>`;
    uploadedMaterials = [];
  }
}

function renderMaterials() {
  if (uploadedMaterials.length === 0) {
    materialList.innerHTML = `<div class="empty-state" style="min-height: 80px; padding: 16px; font-size:12px;">No study files uploaded yet. Upload a document below.</div>`;
    return;
  }

  materialList.innerHTML = uploadedMaterials.map(m => {
    const kb = (m.character_count / 1024).toFixed(1);
    const dateStr = new Date(m.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit' });
    return `
      <div class="material-item">
        <div class="material-name">
          <span>📄</span>
          <div>
            <div>${escapeHtml(m.file_name)}</div>
            <div class="material-meta">${kb} KB · ${dateStr}</div>
          </div>
        </div>
        <button class="button button-quiet button-compact" style="color:var(--red); border-color:transparent; background:transparent;" onclick="deleteMaterial(${m.id})">Delete</button>
      </div>
    `;
  }).join("");
}

async function deleteMaterial(id) {
  if (!confirm("Are you sure you want to delete this file from your study workspace?")) return;
  try {
    const res = await fetch(`/api/library/materials/${id}?owner_key=${encodeURIComponent(ownerKey)}`, {
      method: "DELETE",
      headers: getApiHeaders()
    });
    if (!res.ok) throw new Error();
    fetchMaterials();
  } catch {
    alert("Failed to delete study material.");
  }
}

// ----------------------------------------------------
// File Upload Actions
// ----------------------------------------------------
dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", handleFileSelection);

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.style.borderColor = "var(--blue)";
  dropzone.style.background = "var(--soft-blue)";
});
dropzone.addEventListener("dragleave", () => {
  dropzone.style.borderColor = "var(--line-strong)";
  dropzone.style.background = "var(--canvas)";
});
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.style.borderColor = "var(--line-strong)";
  dropzone.style.background = "var(--canvas)";
  if (e.dataTransfer.files.length > 0) {
    uploadFile(e.dataTransfer.files[0]);
  }
});

function handleFileSelection() {
  if (fileInput.files.length > 0) {
    uploadFile(fileInput.files[0]);
  }
}

function uploadFile(file) {
  const allowed = [".txt", ".md", ".pdf", ".docx"];
  const extension = "." + file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(extension)) {
    uploadStatus.textContent = "Unsupported file type. Use PDF, DOCX, TXT, or MD.";
    uploadStatus.style.color = "var(--red)";
    return;
  }

  if (file.size > 8 * 1024 * 1024) {
    uploadStatus.textContent = "File is too large. Maximum size is 8MB.";
    uploadStatus.style.color = "var(--red)";
    return;
  }

  uploadStatus.textContent = "Reading file content...";
  uploadStatus.style.color = "var(--blue)";

  const reader = new FileReader();
  reader.onload = async function () {
    const base64Content = reader.result.split(",")[1];
    uploadStatus.textContent = "Processing and extracting text on server...";

    try {
      const res = await fetch("/api/library/materials", {
        method: "POST",
        headers: getApiHeaders(),
        body: JSON.stringify({
          owner_key: ownerKey,
          file_name: file.name,
          mime_type: file.type || "application/octet-stream",
          content_base64: base64Content
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Upload failed");
      
      uploadStatus.textContent = `Successfully uploaded: ${file.name}`;
      uploadStatus.style.color = "var(--green)";
      fetchMaterials();
    } catch (err) {
      uploadStatus.textContent = err.message || "File upload failed. Ensure server connection.";
      uploadStatus.style.color = "var(--red)";
    }
  };
  reader.readAsDataURL(file);
}

// ----------------------------------------------------
// Private Notes Actions
// ----------------------------------------------------
saveNoteBtn.addEventListener("click", () => {
  const text = noteText.value.trim();
  if (!text) return;
  const notes = loadLocalNotes();
  notes.unshift({
    id: Date.now(),
    text: text,
    created_at: new Date().toISOString()
  });
  saveLocalNotes(notes);
  noteText.value = "";
  renderNotes();
});

function renderNotes() {
  const notes = loadLocalNotes();
  if (notes.length === 0) {
    noteSavedItems.innerHTML = `<p style="font-size:12px; color:var(--muted); text-align:center; padding:10px 0;">No personal notes added yet.</p>`;
    return;
  }
  noteSavedItems.innerHTML = notes.map(note => `
    <div class="note-item">
      <h4>Study Note</h4>
      <p>${escapeHtml(note.text)}</p>
      <button class="delete-note-btn" onclick="deleteNote(${note.id})">Delete</button>
    </div>
  `).join("");
}

window.deleteNote = function (id) {
  let notes = loadLocalNotes();
  notes = notes.filter(n => n.id !== id);
  saveLocalNotes(notes);
  renderNotes();
};

// ----------------------------------------------------
// Question Session Generation
// ----------------------------------------------------
practiceCount.addEventListener("change", () => {
  if (practiceCount.value === "custom") {
    customCountWrapper.style.display = "block";
  } else {
    customCountWrapper.style.display = "none";
  }
});

generateBtn.addEventListener("click", async () => {
  practiceError.textContent = "";
  if (uploadedMaterials.length === 0) {
    practiceError.textContent = "Upload at least one study material file first.";
    return;
  }

  let count = 5;
  if (practiceCount.value === "custom") {
    count = parseInt(customCountInput.value);
    if (isNaN(count) || count < 1 || count > 50) {
      practiceError.textContent = "Please enter a valid count between 1 and 50.";
      return;
    }
  } else {
    count = parseInt(practiceCount.value);
  }

  generateBtn.disabled = true;
  practiceError.textContent = "Generating questions using OpenAI...";
  practiceError.style.color = "var(--blue)";

  try {
    const res = await fetch("/api/library/generate", {
      method: "POST",
      headers: getApiHeaders(),
      body: JSON.stringify({
        owner_key: ownerKey,
        material_ids: uploadedMaterials.map(m => m.id),
        level: practiceLevel.value,
        question_count: count
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Generation failed");

    generatedQuestions = data.questions || [];
    currentQuestionIndex = 0;
    
    // Save combined texts to use as context for evaluate answers
    selectedMaterialTexts = ""; // This will be looked up/handled server side but we can also collect client side
    
    startPracticeSession();
  } catch (err) {
    practiceError.textContent = err.message || "Failed to generate questions. Is server connection active?";
    practiceError.style.color = "var(--red)";
  } finally {
    generateBtn.disabled = false;
  }
});

// ----------------------------------------------------
// Practice Work Loop
// ----------------------------------------------------
function startPracticeSession() {
  setupView.style.display = "none";
  practiceView.style.display = "flex";
  showPracticeQuestion();
}

function showPracticeQuestion() {
  const q = generatedQuestions[currentQuestionIndex];
  practiceProgress.textContent = `Question ${currentQuestionIndex + 1} of ${generatedQuestions.length}`;
  practiceBadge.textContent = labelForLevel(practiceLevel.value);
  
  const pct = (currentQuestionIndex / generatedQuestions.length) * 100;
  practiceProgressBar.style.width = pct + "%";

  practiceQuestionText.textContent = q.question;
  practiceAnswer.value = "";
  practiceAnswer.disabled = false;
  
  practiceWordCount.textContent = "0 words";
  submitAnswerBtn.disabled = false;
  submitAnswerBtn.style.display = "inline-flex";
  nextPracticeBtn.style.display = "none";
  practiceFeedback.style.display = "none";
  evaluationStatus.textContent = "";
}

practiceAnswer.addEventListener("input", () => {
  const words = practiceAnswer.value.trim().split(/\s+/).filter(w => w.length > 0).length;
  practiceWordCount.textContent = `${words} words`;
});

submitAnswerBtn.addEventListener("click", async () => {
  const answer = practiceAnswer.value.trim();
  if (!answer) {
    evaluationStatus.textContent = "Write an answer before submitting.";
    evaluationStatus.style.color = "var(--red)";
    return;
  }

  submitAnswerBtn.disabled = true;
  evaluationStatus.textContent = "Evaluating your answer using OpenAI...";
  evaluationStatus.style.color = "var(--blue)";

  const q = generatedQuestions[currentQuestionIndex];

  try {
    const res = await fetch("/api/library/evaluate", {
      method: "POST",
      headers: getApiHeaders(),
      body: JSON.stringify({
        question: q.question,
        answer: answer,
        reference_answer: q.reference_answer,
        key_concepts: q.key_concepts || [],
        material_ids: uploadedMaterials.map(m => m.id),
        owner_key: ownerKey
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Evaluation failed");

    renderFeedback(data.evaluation);
  } catch (err) {
    evaluationStatus.textContent = err.message || "Failed to connect to the evaluation API.";
    evaluationStatus.style.color = "var(--red)";
    submitAnswerBtn.disabled = false;
  }
});

function renderFeedback(evalResult) {
  evaluationStatus.textContent = "";
  practiceAnswer.disabled = true;
  submitAnswerBtn.style.display = "none";

  // Render score badge
  feedbackScoreBadge.textContent = `${evalResult.score}/100`;
  feedbackScoreBadge.className = "score-badge " + (evalResult.score >= 75 ? "badge-correct" : evalResult.score >= 40 ? "badge-partial" : "badge-incorrect");

  feedbackExplanation.textContent = evalResult.feedback || evalResult.rationale;
  
  // Render covered concepts
  const covered = evalResult.covered_concepts || [];
  feedbackCovered.innerHTML = covered.length > 0 
    ? covered.map(c => `<span class="keyword-tag" style="background:#e6f6f0; color:var(--green); border-color:#d0ecd8;">${escapeHtml(c)}</span>`).join("")
    : `<span style="font-size:12px; color:var(--muted);">No matching concepts covered.</span>`;

  // Render missing concepts
  const missing = evalResult.missing_concepts || [];
  feedbackMissing.innerHTML = missing.length > 0 
    ? missing.map(c => `<span class="keyword-tag" style="background:#feebe8; color:var(--red); border-color:#fcc8c2;">${escapeHtml(c)}</span>`).join("")
    : `<span style="font-size:12px; color:var(--muted);">None identified. Great coverage!</span>`;

  // Model answer
  feedbackModelAnswer.textContent = evalResult.model_answer || "No stronger answer suggested.";

  practiceFeedback.style.display = "grid";
  
  // Show Next or Complete button
  if (currentQuestionIndex < generatedQuestions.length - 1) {
    nextPracticeBtn.textContent = "Next Question →";
  } else {
    nextPracticeBtn.textContent = "Complete Session 🎉";
  }
  nextPracticeBtn.style.display = "inline-flex";
}

nextPracticeBtn.addEventListener("click", () => {
  if (currentQuestionIndex < generatedQuestions.length - 1) {
    currentQuestionIndex++;
    showPracticeQuestion();
  } else {
    // End of session
    alert("Practice session completed! Great job preparing.");
    exitPractice();
  }
});

exitPracticeBtn.addEventListener("click", () => {
  if (confirm("Are you sure you want to exit your active practice session? Your progress will be cleared.")) {
    exitPractice();
  }
});

function exitPractice() {
  practiceView.style.display = "none";
  setupView.style.display = "grid";
  generatedQuestions = [];
  currentQuestionIndex = 0;
}

// ----------------------------------------------------
// Utilities
// ----------------------------------------------------
function labelForLevel(level) {
  switch (level.toLowerCase()) {
    case "easy": return "Easy level";
    case "medium": return "Medium level";
    case "hard": return "Hard level";
    default: return level;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Init
initApiKeyPanel();
fetchMaterials();
renderNotes();
