/**
 * Viva AI — Practice Lab & High-Speed Document Ingestion Logic
 * Handles file parsing, direct notes pasting, question generation, examiner TTS voice, and 4-dimension AI rubric grading.
 */
(function () {
  'use strict';

  const API_KEY_STORAGE = "viva_student_api_key";
  const BASE_URL_STORAGE = "viva_student_base_url";
  const MODEL_NAME_STORAGE = "viva_student_model_name";
  const OWNER_STORAGE_KEY = "viva_library_owner_key";

  let ownerKey = localStorage.getItem(OWNER_STORAGE_KEY);
  if (!ownerKey) {
    ownerKey = "owner_" + Math.random().toString(36).substring(2, 12);
    localStorage.setItem(OWNER_STORAGE_KEY, ownerKey);
  }

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

  // DOM Elements
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const uploadStatus = document.getElementById("uploadStatus");
  const materialList = document.getElementById("materialList");
  const materialCountBadge = document.getElementById("materialCountBadge");

  const tabUploadFile = document.getElementById("tabUploadFile");
  const tabPasteText = document.getElementById("tabPasteText");
  const ingestionFileView = document.getElementById("ingestionFileView");
  const ingestionPasteView = document.getElementById("ingestionPasteView");
  const pasteTitleInput = document.getElementById("pasteTitleInput");
  const pasteTextInput = document.getElementById("pasteTextInput");
  const savePastedNotesBtn = document.getElementById("savePastedNotesBtn");

  const practiceSubject = document.getElementById("practiceSubject");
  const practiceLevel = document.getElementById("practiceLevel");
  const practiceCount = document.getElementById("practiceCount");
  const customCountWrapper = document.getElementById("customCountWrapper");
  const customCountInput = document.getElementById("customCountInput");
  const generateBtn = document.getElementById("generateBtn");
  const practiceError = document.getElementById("practiceError");

  const setupPromptState = document.getElementById("setupPromptState");
  const activePracticeState = document.getElementById("activePracticeState");
  const sessionSummaryState = document.getElementById("sessionSummaryState");
  const practiceProgressBadge = document.getElementById("practiceProgressBadge");
  const practiceDifficultyBadge = document.getElementById("practiceDifficultyBadge");
  const practiceProgressBar = document.getElementById("practiceProgressBar");
  const practiceQuestionText = document.getElementById("practiceQuestionText");
  const practiceAnswer = document.getElementById("practiceAnswer");
  const practiceWordCount = document.getElementById("practiceWordCount");
  const submitAnswerBtn = document.getElementById("submitAnswerBtn");
  const nextPracticeBtn = document.getElementById("nextPracticeBtn");
  const exitPracticeBtn = document.getElementById("exitPracticeBtn");
  const readQuestionBtn = document.getElementById("readQuestionBtn");
  const starQuestionBtn = document.getElementById("starQuestionBtn");
  const evaluationStatus = document.getElementById("evaluationStatus");

  const practiceFeedback = document.getElementById("practiceFeedback");
  const feedbackReadiness = document.getElementById("feedbackReadiness");
  const feedbackScoreBadge = document.getElementById("feedbackScoreBadge");
  const feedbackExplanation = document.getElementById("feedbackExplanation");
  const feedbackCovered = document.getElementById("feedbackCovered");
  const feedbackMissing = document.getElementById("feedbackMissing");
  const feedbackModelAnswer = document.getElementById("feedbackModelAnswer");
  const rubricMetersContainer = document.getElementById("rubricMetersContainer");
  const questionNoteInput = document.getElementById("questionNoteInput");
  const noteSavedBadge = document.getElementById("noteSavedBadge");

  const summaryAvgScore = document.getElementById("summaryAvgScore");
  const summaryQCount = document.getElementById("summaryQCount");

  // State
  let uploadedMaterials = [];
  let generatedQuestions = [];
  let completedEvaluations = [];
  let currentIndex = 0;
  let noteAutosaveTimer = null;

  window.setSubject = function (subj) {
    if (practiceSubject) practiceSubject.value = subj;
  };

  window.setIngestionMode = function (mode) {
    const isFile = mode === "file";
    if (tabUploadFile) tabUploadFile.classList.toggle("active", isFile);
    if (tabPasteText) tabPasteText.classList.toggle("active", !isFile);
    if (ingestionFileView) ingestionFileView.style.display = isFile ? "block" : "none";
    if (ingestionPasteView) ingestionPasteView.style.display = isFile ? "none" : "block";
  };

  window.handleSavePastedNotes = async function () {
    const title = (pasteTitleInput.value || "").trim() || "Pasted Syllabus Notes";
    const text = (pasteTextInput.value || "").trim();

    if (!text || text.length < 15) {
      if (window.Toast) Toast.warning("Please paste at least 15 characters of notes content.");
      return;
    }

    savePastedNotesBtn.disabled = true;
    savePastedNotesBtn.textContent = "Ingesting Notes...";
    uploadStatus.textContent = "Ingesting syllabus text...";
    uploadStatus.style.color = "var(--primary)";

    try {
      const res = await fetch("/api/library/materials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner_key: ownerKey,
          file_name: title.endsWith(".txt") ? title : `${title}.txt`,
          mime_type: "text/plain",
          raw_text: text
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to save notes");

      pasteTextInput.value = "";
      uploadStatus.textContent = `✓ Ingested ${data.material.file_name} successfully!`;
      uploadStatus.style.color = "var(--success)";
      if (window.Toast) Toast.success(`Added ${data.material.file_name} (${data.material.character_count} chars)`);
      await loadLibraryMaterials();
    } catch (err) {
      uploadStatus.textContent = `Error: ${err.message}`;
      uploadStatus.style.color = "var(--danger)";
      if (window.Toast) Toast.error(err.message);
    } finally {
      savePastedNotesBtn.disabled = false;
      savePastedNotesBtn.textContent = "Save & Ingest Notes ⚡";
    }
  };

  // ----------------------------------------------------
  // Document Upload & High-Speed Ingestion
  // ----------------------------------------------------
  if (practiceCount) {
    practiceCount.addEventListener("change", () => {
      customCountWrapper.style.display = practiceCount.value === "custom" ? "block" : "none";
    });
  }

  async function loadLibraryMaterials() {
    try {
      const res = await fetch(`/api/library/materials?owner_key=${encodeURIComponent(ownerKey)}`);
      if (!res.ok) return;
      const data = await res.json();
      uploadedMaterials = data.materials || [];
      renderMaterials();
    } catch (e) {
      console.warn("Could not load library materials:", e);
    }
  }

  function renderMaterials() {
    if (!materialList) return;
    if (materialCountBadge) materialCountBadge.textContent = `${uploadedMaterials.length} file${uploadedMaterials.length === 1 ? '' : 's'}`;

    if (!uploadedMaterials.length) {
      materialList.innerHTML = '<p style="font-size: 12.5px; color: var(--text-muted); font-style: italic;">No documents uploaded yet.</p>';
      return;
    }

    materialList.innerHTML = uploadedMaterials.map(m => `
      <div class="material-item">
        <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 250px;">
          <strong style="color: var(--text-primary); font-size: 13px;">${m.file_name}</strong>
          <span style="font-size: 11px; color: var(--text-muted); display: block;">${m.character_count || 0} chars</span>
        </div>
        <button type="button" class="button button-danger button-compact" style="padding: 2px 8px; font-size: 11px;" onclick="window.deleteMaterial(${m.id})">Delete</button>
      </div>
    `).join('');
  }

  window.deleteMaterial = async function (id) {
    try {
      const res = await fetch(`/api/library/materials/${id}?owner_key=${encodeURIComponent(ownerKey)}`, {
        method: "DELETE"
      });
      if (res.ok) {
        uploadedMaterials = uploadedMaterials.filter(m => m.id !== id);
        renderMaterials();
        if (window.Toast) Toast.info("Material removed.");
      }
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  if (fileInput) {
    fileInput.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      await uploadFile(file);
      fileInput.value = "";
    });
  }

  if (dropzone) {
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", async (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        await uploadFile(e.dataTransfer.files[0]);
      }
    });
  }

  async function uploadFile(file) {
    if (file.size > 8 * 1024 * 1024) {
      uploadStatus.textContent = "File size exceeds 8 MB limit.";
      uploadStatus.style.color = "var(--danger)";
      if (window.Toast) Toast.error("File size exceeds 8 MB limit.");
      return;
    }

    uploadStatus.textContent = `⚡ Processing ${file.name}...`;
    uploadStatus.style.color = "var(--primary)";

    const isTextFile = /\.(txt|md|csv|py|json|html|c|cpp|java|js|ts|xml|sql|sh)$/i.test(file.name);

    if (isTextFile) {
      // Fast path for text files: read directly as text with 0 base64 overhead
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const res = await fetch("/api/library/materials", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              owner_key: ownerKey,
              file_name: file.name,
              mime_type: file.type || "text/plain",
              raw_text: reader.result
            })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Upload failed");

          uploadStatus.textContent = `✓ Uploaded ${file.name} successfully!`;
          uploadStatus.style.color = "var(--success)";
          if (window.Toast) Toast.success(`Uploaded ${file.name} (${data.material.character_count} chars extracted)`);
          await loadLibraryMaterials();
        } catch (err) {
          uploadStatus.textContent = `Error: ${err.message}`;
          uploadStatus.style.color = "var(--danger)";
          if (window.Toast) Toast.error(err.message);
        }
      };
      reader.readAsText(file);
    } else {
      // Binary files (PDF, DOCX)
      const reader = new FileReader();
      reader.onload = async () => {
        const base64 = reader.result.split(',')[1];
        try {
          const res = await fetch("/api/library/materials", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              owner_key: ownerKey,
              file_name: file.name,
              mime_type: file.type || "application/octet-stream",
              content_base64: base64
            })
          });

          const data = await res.json();
          if (!res.ok) {
            throw new Error(data.error || "Upload failed");
          }

          uploadStatus.textContent = `✓ Extracted ${file.name} successfully!`;
          uploadStatus.style.color = "var(--success)";
          if (window.Toast) Toast.success(`Extracted ${file.name} (${data.material.character_count} chars)`);
          await loadLibraryMaterials();
        } catch (err) {
          uploadStatus.textContent = `Error: ${err.message}`;
          uploadStatus.style.color = "var(--danger)";
          if (window.Toast) Toast.error(err.message);
        }
      };
      reader.readAsDataURL(file);
    }
  }

  // ----------------------------------------------------
  // AI Question Generation
  // ----------------------------------------------------
  if (generateBtn) {
    generateBtn.addEventListener("click", async () => {
      practiceError.textContent = "";
      const subject = practiceSubject ? practiceSubject.value.trim() : "Computer Science";
      const level = practiceLevel ? practiceLevel.value : "medium";
      let count = 5;
      if (practiceCount.value === "custom") {
        count = parseInt(customCountInput.value) || 5;
      } else {
        count = parseInt(practiceCount.value) || 5;
      }

      generateBtn.disabled = true;
      generateBtn.textContent = "Generating Viva Questions...";

      const matIds = uploadedMaterials.map(m => m.id);

      try {
        let res;
        if (matIds.length > 0) {
          res = await fetch("/api/library/generate", {
            method: "POST",
            headers: getApiHeaders(),
            body: JSON.stringify({
              owner_key: ownerKey,
              material_ids: matIds,
              subject: subject,
              level: level,
              question_count: count
            })
          });
        } else {
          res = await fetch("/api/generate-questions", {
            method: "POST",
            headers: getApiHeaders(),
            body: JSON.stringify({
              subject: subject,
              level: level,
              api_key: localStorage.getItem(API_KEY_STORAGE) || ""
            })
          });
        }

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || "Question generation failed");
        }

        generatedQuestions = data.questions || [];
        if (!generatedQuestions.length) {
          throw new Error("No questions returned from generator.");
        }

        completedEvaluations = [];
        startPracticeSession();
      } catch (err) {
        practiceError.textContent = err.message;
        if (window.Toast) Toast.error(`Generation error: ${err.message}`);
      } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = "Generate AI Viva Questions ⚡";
      }
    });
  }

  function startPracticeSession() {
    currentIndex = 0;
    setupPromptState.style.display = "none";
    sessionSummaryState.style.display = "none";
    activePracticeState.style.display = "flex";
    practiceDifficultyBadge.textContent = practiceLevel.options[practiceLevel.selectedIndex].text.split(' ')[0];
    showCurrentQuestion();
  }

  function showCurrentQuestion() {
    const q = generatedQuestions[currentIndex];
    if (!q) {
      showSessionSummary();
      return;
    }

    const total = generatedQuestions.length;
    practiceProgressBadge.textContent = `Question ${currentIndex + 1} of ${total}`;
    practiceProgressBar.style.width = `${((currentIndex + 1) / total) * 100}%`;
    practiceQuestionText.textContent = q.question;

    practiceAnswer.value = "";
    practiceAnswer.disabled = false;
    updateWordCount();

    // Star button state
    updateStarButtonState(q.id);

    // Note input state
    if (questionNoteInput) {
      questionNoteInput.value = StudentNotes.get(q.id) || "";
    }
    if (noteSavedBadge) noteSavedBadge.style.display = "none";

    submitAnswerBtn.style.display = "inline-flex";
    submitAnswerBtn.disabled = false;
    nextPracticeBtn.style.display = "none";
    practiceFeedback.style.display = "none";
    evaluationStatus.textContent = "";

    // Stop previous audio
    if (window.stopExaminerSpeech) window.stopExaminerSpeech();
  }

  function updateStarButtonState(qid) {
    if (!starQuestionBtn) return;
    const isStarred = StudentNotes.isStarred(qid);
    starQuestionBtn.textContent = isStarred ? "⭐ Starred" : "☆ Star Question";
    starQuestionBtn.style.color = isStarred ? "var(--warning)" : "var(--text-secondary)";
  }

  if (starQuestionBtn) {
    starQuestionBtn.addEventListener("click", () => {
      const q = generatedQuestions[currentIndex];
      if (!q) return;
      const starred = StudentNotes.toggleStar(q.id);
      updateStarButtonState(q.id);
      if (window.Toast) Toast.info(starred ? "⭐ Starred question for study vault" : "Removed star");
    });
  }

  if (readQuestionBtn) {
    readQuestionBtn.addEventListener("click", () => {
      const q = generatedQuestions[currentIndex];
      if (!q) return;
      readQuestionBtn.disabled = true;
      readQuestionBtn.textContent = "🔊 Reading...";
      if (window.speakExaminerQuestion) {
        window.speakExaminerQuestion(q.question, () => {
          readQuestionBtn.disabled = false;
          readQuestionBtn.textContent = "🔊 Read Aloud";
        });
      }
    });
  }

  function updateWordCount() {
    const text = (practiceAnswer.value || "").trim();
    const count = text ? text.split(/\s+/).filter(Boolean).length : 0;
    practiceWordCount.textContent = `${count} word${count === 1 ? '' : 's'}`;
  }

  if (practiceAnswer) {
    practiceAnswer.addEventListener("input", updateWordCount);
  }

  if (questionNoteInput) {
    questionNoteInput.addEventListener("input", () => {
      clearTimeout(noteAutosaveTimer);
      noteAutosaveTimer = setTimeout(() => {
        const q = generatedQuestions[currentIndex];
        if (!q) return;
        const subj = practiceSubject ? practiceSubject.value.trim() : "General";
        StudentNotes.save(q.id, questionNoteInput.value, subj, q.question);
        if (noteSavedBadge) {
          noteSavedBadge.style.display = "inline";
          setTimeout(() => { noteSavedBadge.style.display = "none"; }, 2000);
        }
      }, 800);
    });
  }

  if (exitPracticeBtn) {
    exitPracticeBtn.addEventListener("click", async () => {
      const confirmExit = await Modal.confirm("Exit Practice Session", "Are you sure you want to exit? Your progress in this question set will be cleared.");
      if (confirmExit) {
        window.location.reload();
      }
    });
  }

  // ----------------------------------------------------
  // Submit & Dynamic 4-Dimension Rubric Grading
  // ----------------------------------------------------
  if (submitAnswerBtn) {
    submitAnswerBtn.addEventListener("click", async () => {
      const answer = (practiceAnswer.value || "").trim();
      if (!answer) {
        evaluationStatus.textContent = "Please speak or type an answer before requesting AI evaluation.";
        evaluationStatus.style.color = "var(--danger)";
        if (window.Toast) Toast.warning("Please provide an answer before submitting.");
        return;
      }

      const q = generatedQuestions[currentIndex];
      submitAnswerBtn.disabled = true;
      evaluationStatus.textContent = "Examiner is grading against 4-point rubric...";
      evaluationStatus.style.color = "var(--primary)";

      try {
        const res = await fetch("/api/evaluate", {
          method: "POST",
          headers: getApiHeaders(),
          body: JSON.stringify({
            question: q.question,
            answer: answer,
            expected_keywords: q.key_concepts || q.expected_keywords || [],
            model_answer: q.reference_answer || q.model_answer || "",
            api_key: localStorage.getItem(API_KEY_STORAGE) || ""
          })
        });

        const evalData = await res.json();
        if (!res.ok) {
          throw new Error(evalData.error || "Evaluation failed");
        }

        completedEvaluations.push({
          question: q.question,
          answer: answer,
          evaluation: evalData
        });

        renderFeedback(evalData);
      } catch (err) {
        evaluationStatus.textContent = `Evaluation error: ${err.message}`;
        evaluationStatus.style.color = "var(--danger)";
        submitAnswerBtn.disabled = false;
        if (window.Toast) Toast.error(err.message);
      }
    });
  }

  function renderFeedback(data) {
    evaluationStatus.textContent = "Evaluation complete ✓";
    evaluationStatus.style.color = "var(--success)";
    submitAnswerBtn.style.display = "none";
    nextPracticeBtn.style.display = "inline-flex";
    practiceAnswer.disabled = true;

    const score = Number(data.score) || 0;
    feedbackScoreBadge.textContent = `${score} / 100`;

    if (score >= 80) {
      feedbackScoreBadge.style.color = "var(--success)";
      feedbackReadiness.textContent = "Readiness: Excellent Mastery";
    } else if (score >= 60) {
      feedbackScoreBadge.style.color = "var(--warning)";
      feedbackReadiness.textContent = "Readiness: Developing / Solid";
    } else {
      feedbackScoreBadge.style.color = "var(--danger)";
      feedbackReadiness.textContent = "Readiness: Needs Targeted Practice";
    }

    // 4-Dimension Rubric Meters
    const dim = data.dimension_scores || {
      precision: score * 0.20,
      clarity: score * 0.20,
      evidence: score * 0.20,
      keywords: score * 0.40,
      max_precision: 20,
      max_clarity: 20,
      max_evidence: 20,
      max_keywords: 40
    };

    rubricMetersContainer.innerHTML = `
      <div class="rubric-meter-card">
        <div class="rubric-meter-header">
          <span>Concept Precision (20%)</span>
          <span style="font-family: var(--font-mono); color: var(--primary);">${dim.precision} / ${dim.max_precision || 20}</span>
        </div>
        <div class="rubric-meter-track">
          <div class="rubric-meter-fill" style="width: ${(dim.precision / (dim.max_precision || 20)) * 100}%; background: var(--primary);"></div>
        </div>
      </div>

      <div class="rubric-meter-card">
        <div class="rubric-meter-header">
          <span>Explanation Clarity (20%)</span>
          <span style="font-family: var(--font-mono); color: var(--secondary);">${dim.clarity} / ${dim.max_clarity || 20}</span>
        </div>
        <div class="rubric-meter-track">
          <div class="rubric-meter-fill" style="width: ${(dim.clarity / (dim.max_clarity || 20)) * 100}%; background: var(--secondary);"></div>
        </div>
      </div>

      <div class="rubric-meter-card">
        <div class="rubric-meter-header">
          <span>Evidence &amp; Examples (20%)</span>
          <span style="font-family: var(--font-mono); color: var(--accent-cyan);">${dim.evidence} / ${dim.max_evidence || 20}</span>
        </div>
        <div class="rubric-meter-track">
          <div class="rubric-meter-fill" style="width: ${(dim.evidence / (dim.max_evidence || 20)) * 100}%; background: var(--accent-cyan);"></div>
        </div>
      </div>

      <div class="rubric-meter-card">
        <div class="rubric-meter-header">
          <span>Keyword/Concept Coverage (40%)</span>
          <span style="font-family: var(--font-mono); color: var(--success);">${dim.keywords} / ${dim.max_keywords || 40}</span>
        </div>
        <div class="rubric-meter-track">
          <div class="rubric-meter-fill" style="width: ${(dim.keywords / (dim.max_keywords || 40)) * 100}%; background: var(--success);"></div>
        </div>
      </div>
    `;

    feedbackExplanation.textContent = data.feedback || data.rationale || "No specific feedback provided.";

    const covered = data.covered_concepts || data.strengths || [];
    feedbackCovered.innerHTML = covered.length ? covered.map(c => `<span class="concept-chip concept-chip-covered">✓ ${c}</span>`).join('') : '<span style="font-size:12px; color:var(--text-muted);">None identified</span>';

    const missing = data.missing_concepts || data.gaps || [];
    feedbackMissing.innerHTML = missing.length ? missing.map(m => `<span class="concept-chip concept-chip-missing">✕ ${m}</span>`).join('') : '<span style="font-size:12px; color:var(--text-muted);">No major gaps detected</span>';

    feedbackModelAnswer.textContent = data.model_answer || "State core principles clearly with terminology precision and concrete examples.";

    practiceFeedback.style.display = "grid";
    setTimeout(() => {
      practiceFeedback.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 100);
  }

  if (nextPracticeBtn) {
    nextPracticeBtn.addEventListener("click", () => {
      currentIndex++;
      showCurrentQuestion();
    });
  }

  function showSessionSummary() {
    activePracticeState.style.display = "none";
    sessionSummaryState.style.display = "block";

    const total = completedEvaluations.length;
    const avg = total ? Math.round(completedEvaluations.reduce((acc, ev) => acc + (ev.evaluation.score || 0), 0) / total) : 0;

    summaryAvgScore.textContent = `${avg}%`;
    summaryQCount.textContent = `${total}`;
    if (window.Toast) Toast.success("Session completed! Download your study guide below.");
  }

  window.exportPracticeStudyGuide = function () {
    const subj = practiceSubject ? practiceSubject.value.trim() : "Viva Practice";
    let md = `# Viva Simulator — Practice Session Report & Study Guide\n`;
    md += `**Subject:** ${subj}\n`;
    md += `**Date:** ${new Date().toLocaleString()}\n`;
    md += `**Questions Answered:** ${completedEvaluations.length}\n\n---\n\n`;

    completedEvaluations.forEach((item, idx) => {
      const ev = item.evaluation;
      md += `## Question ${idx + 1}: ${item.question}\n`;
      md += `**Your Answer:**\n> ${item.answer.split('\n').join('\n> ')}\n\n`;
      md += `**Score:** ${ev.score} / 100 (${ev.readiness || 'Evaluated'})\n\n`;
      md += `**Examiner Feedback:**\n${ev.feedback || ev.rationale || ''}\n\n`;
      if (ev.model_answer) {
        md += `**Model Answer:**\n${ev.model_answer}\n\n`;
      }
      md += `---\n\n`;
    });

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `viva-session-${subj.toLowerCase().replace(/[^a-z0-9]/g, '-')}-${new Date().toISOString().slice(0, 10)}.md`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  };

  document.addEventListener("DOMContentLoaded", loadLibraryMaterials);
})();
