/* notes.js — shared localStorage utility for student notes */

const NOTES_STORAGE_KEY = "viva_student_notes";

function _loadAllNotes() {
  try {
    return JSON.parse(localStorage.getItem(NOTES_STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function _persistNotes(notes) {
  localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(notes));
}

function saveNote(questionId, noteText) {
  const notes = _loadAllNotes();
  if (noteText.trim()) {
    notes[questionId] = noteText.trim();
  } else {
    delete notes[questionId];
  }
  _persistNotes(notes);
}

function getNote(questionId) {
  return _loadAllNotes()[questionId] || "";
}

function getAllNotes() {
  return _loadAllNotes();
}

function deleteNote(questionId) {
  const notes = _loadAllNotes();
  delete notes[questionId];
  _persistNotes(notes);
}

function hasNote(questionId) {
  return !!_loadAllNotes()[questionId];
}
