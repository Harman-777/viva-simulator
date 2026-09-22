/**
 * Viva AI — Student Private Notes Vault
 * Encapsulated localStorage notes manager for questions, key takeaways, and study exports.
 */
(function (global) {
  'use strict';

  const NOTES_KEY = "viva_student_notes_vault";
  const STARRED_KEY = "viva_student_starred_questions";

  function _loadNotes() {
    try {
      return JSON.parse(localStorage.getItem(NOTES_KEY)) || {};
    } catch {
      return {};
    }
  }

  function _saveNotes(data) {
    try {
      localStorage.setItem(NOTES_KEY, JSON.stringify(data));
    } catch (e) {
      console.warn("Error saving notes:", e);
    }
  }

  function _loadStarred() {
    try {
      return JSON.parse(localStorage.getItem(STARRED_KEY)) || [];
    } catch {
      return [];
    }
  }

  function _saveStarred(arr) {
    try {
      localStorage.setItem(STARRED_KEY, JSON.stringify(arr));
    } catch (e) {
      console.warn("Error saving starred:", e);
    }
  }

  const Notes = {
    get(id) {
      const all = _loadNotes();
      return all[id] ? all[id].text : "";
    },

    getItem(id) {
      const all = _loadNotes();
      return all[id] || null;
    },

    save(id, text, topic, questionPrompt) {
      topic = topic || "General";
      const all = _loadNotes();
      const clean = (text || "").trim();
      if (clean) {
        all[id] = {
          id: id,
          text: clean,
          topic: topic,
          questionPrompt: questionPrompt || all[id]?.questionPrompt || "",
          updatedAt: new Date().toISOString()
        };
      } else {
        delete all[id];
      }
      _saveNotes(all);
    },

    delete(id) {
      const all = _loadNotes();
      delete all[id];
      _saveNotes(all);
    },

    all() {
      return _loadNotes();
    },

    list() {
      const all = _loadNotes();
      return Object.values(all).sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
    },

    has(id) {
      const all = _loadNotes();
      return Boolean(all[id] && all[id].text);
    },

    // Star / Bookmark feature
    isStarred(id) {
      return _loadStarred().includes(id);
    },

    toggleStar(id) {
      const list = _loadStarred();
      const idx = list.indexOf(id);
      if (idx >= 0) {
        list.splice(idx, 1);
      } else {
        list.push(id);
      }
      _saveStarred(list);
      return list.includes(id);
    },

    // Export notes to Markdown
    exportMarkdown() {
      const notes = this.list();
      let md = `# Viva Simulator — Personal Study Notes & Key Takeaways\nGenerated on: ${new Date().toLocaleDateString()}\n\n---\n\n`;
      if (!notes.length) {
        md += `*No notes recorded yet.*\n`;
      } else {
        notes.forEach((n, idx) => {
          md += `### ${idx + 1}. [${n.topic}] ${n.questionPrompt || 'Topic Note'}\n`;
          md += `**Last Revised:** ${new Date(n.updatedAt).toLocaleString()}\n\n`;
          md += `> ${n.text.split('\n').join('\n> ')}\n\n---\n\n`;
        });
      }
      return md;
    },

    downloadMarkdown() {
      const md = this.exportMarkdown();
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `viva-study-notes-${new Date().toISOString().slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
    }
  };

  global.StudentNotes = Notes;
})(window);
