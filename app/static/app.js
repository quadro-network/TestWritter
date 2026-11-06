(() => {
  const LS_ATTEMPT = "attempt_id";
  const state = {
    token: "",
    view: "tests",
    tests: [],
    filterTag: "",
    search: "",
    sectionFolder: null,
    attempt: null,
    idx: 0,
    selected: new Set(),
    checked: false,
    lastAnswer: null,
    finish: null,
    editor: null,
    importPreview: null,
    importError: "",
    stats: null,
  };

  const app = document.getElementById("app");

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers["X-Import-Token"] = state.token;
    const res = await fetch(`/api${path}`, { ...opts, headers });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      const detail = data?.detail;
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail || data);
      throw new Error(msg || res.statusText);
    }
    return data;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function difficultyDots(n) {
    const d = Math.max(1, Math.min(5, n || 1));
    return "●".repeat(d) + "○".repeat(Math.max(0, 3 - d));
  }

  function progressBar(pct) {
    const p = Math.max(0, Math.min(100, pct ?? 0));
    return `<div class="progress" title="${p}%"><span style="width:${p}%"></span></div>`;
  }

  function setView(view) {
    state.view = view;
    document.querySelectorAll(".nav-tabs a").forEach((a) => {
      a.classList.toggle("active", a.dataset.view === view);
    });
    render();
  }

  document.querySelector(".nav-tabs").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-view]");
    if (!a) return;
    e.preventDefault();
    setView(a.dataset.view);
  });

  async function loadTests() {
    const qs = new URLSearchParams({ size: "100", page: "1" });
    if (state.filterTag) qs.set("tag", state.filterTag);
    if (state.search) qs.set("q", state.search);
    const data = await api(`/tests?${qs}`);
    state.tests = data.items || [];
  }

  function sectionOf(t) {
    const eid = (t.external_id || "").trim();
    if (eid.includes("/")) return eid.split("/")[0];
    const skip = new Set(["book", "review", "mistakes"]);
    for (const tag of t.tags || []) {
      const s = String(tag || "").trim();
      if (!s || skip.has(s) || s.startsWith("page-") || s.startsWith("part-")) continue;
      return s;
    }
    return "";
  }

  function testCardHtml(t) {
    const best = t.best_percent;
    return `<article class="card">
      <h3>${esc(t.title)}</h3>
      <div class="tags">${(t.tags || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>
      <p class="muted">${t.question_count} вопросов${best != null ? ` · лучший ${best}%` : ""}</p>
      ${best != null ? progressBar(best) : ""}
      <div class="card-actions">
        <button data-act="run" data-id="${t.id}" data-mode="full">Пройти</button>
        <button class="secondary" data-act="run" data-id="${t.id}" data-mode="mistakes">Только ошибки</button>
        <button class="outline" data-act="edit" data-id="${t.id}">Редактировать</button>
        <button class="outline" data-act="export" data-id="${t.id}">Экспорт</button>
        <button class="contrast" data-act="del" data-id="${t.id}">Удалить</button>
      </div>
    </article>`;
  }

  function folderCardHtml(name, tests) {
    const qsum = tests.reduce((s, t) => s + (t.question_count || 0), 0);
    const bests = tests.map((t) => t.best_percent).filter((x) => x != null);
    const bestAvg = bests.length ? Math.round(bests.reduce((a, b) => a + b, 0) / bests.length) : null;
    const ids = tests.map((t) => t.id).join(",");
    return `<article class="card folder-card" data-open-folder="${esc(name)}" role="button" tabindex="0">
      <div class="folder-icon" aria-hidden="true">📁</div>
      <h3>${esc(name)}</h3>
      <p class="muted">${tests.length} тест(ов) · ${qsum} вопросов${bestAvg != null ? ` · ср. лучший ${bestAvg}%` : ""}</p>
      <p class="muted" style="font-size:0.8rem">Раздел из БД (не папка на диске)</p>
      <div class="card-actions">
        <button type="button" data-open-folder="${esc(name)}">Открыть раздел</button>
        <button type="button" class="contrast" data-del-section="${esc(name)}" data-ids="${ids}">Удалить раздел</button>
      </div>
    </article>`;
  }

  async function deleteSection(name, idsCsv) {
    const ids = String(idsCsv || "")
      .split(",")
      .map((x) => Number(x))
      .filter((x) => x > 0);
    if (!ids.length) return;
    if (
      !confirm(
        `Удалить раздел «${name}» из базы?\nТестов: ${ids.length}.\n(Папка examples/ на диске не трогается — её можно снести вручную.)`
      )
    ) {
      return;
    }
    for (const id of ids) {
      await api(`/tests/${id}`, { method: "DELETE" });
    }
    if (state.sectionFolder === name) state.sectionFolder = null;
    await loadTests();
    render();
  }

  function renderTests() {
    const tags = [...new Set(state.tests.flatMap((t) => t.tags || []))].sort();
    const folder = state.sectionFolder;

    let bodyHtml = "";
    let crumb = "";

    if (folder) {
      const inside = state.tests.filter((t) => sectionOf(t) === folder);
      const ids = inside.map((t) => t.id).join(",");
      crumb = `<nav class="breadcrumb">
        <a href="#" id="crumb-root">Тесты</a>
        <span class="muted">/</span>
        <strong>${esc(folder)}</strong>
        <button type="button" class="contrast" style="margin-left:auto" data-del-section="${esc(folder)}" data-ids="${ids}">Удалить весь раздел</button>
      </nav>`;
      bodyHtml = `<div class="cards">${inside.map(testCardHtml).join("") || "<p class='muted'>В разделе пока нет тестов.</p>"}</div>`;
    } else {
      const bySection = new Map();
      const loose = [];
      for (const t of state.tests) {
        const sec = sectionOf(t);
        if (!sec) {
          loose.push(t);
          continue;
        }
        if (!bySection.has(sec)) bySection.set(sec, []);
        bySection.get(sec).push(t);
      }
      const folders = [...bySection.entries()].sort((a, b) => a[0].localeCompare(b[0], "ru"));
      const folderCards = folders.map(([name, list]) => folderCardHtml(name, list)).join("");
      const looseCards = loose.map(testCardHtml).join("");
      bodyHtml = `
        ${folders.length ? `<h3 class="section-title">Разделы</h3><div class="cards">${folderCards}</div>` : ""}
        ${loose.length ? `<h3 class="section-title">${folders.length ? "Без раздела" : ""}</h3><div class="cards">${looseCards}</div>` : ""}
        ${!folders.length && !loose.length ? "<p class='muted'>Нет тестов. Импортируйте JSON или загрузите книгу PDF.</p>" : ""}
      `;
    }

    app.innerHTML = `
      <div class="toolbar">
        <label>Поиск<input id="search" value="${esc(state.search)}" placeholder="название…" /></label>
        <label>Тег
          <select id="tag">
            <option value="">все</option>
            ${tags.map((t) => `<option value="${esc(t)}" ${t === state.filterTag ? "selected" : ""}>${esc(t)}</option>`).join("")}
          </select>
        </label>
        <button id="refresh">Обновить</button>
        <button class="secondary" id="continue">Продолжить попытку</button>
        <button class="outline" data-view-go="editor">Новый тест</button>
      </div>
      ${crumb}
      ${bodyHtml}
    `;

    app.querySelector("#search").addEventListener("change", async (e) => {
      state.search = e.target.value.trim();
      await loadTests();
      render();
    });
    app.querySelector("#tag").addEventListener("change", async (e) => {
      state.filterTag = e.target.value;
      await loadTests();
      render();
    });
    app.querySelector("#refresh").onclick = async () => {
      await loadTests();
      render();
    };
    app.querySelector("#continue").onclick = () => continueAttempt();
    app.querySelector("[data-view-go]")?.addEventListener("click", () => {
      state.editor = emptyEditor();
      setView("editor");
    });
    app.querySelector("#crumb-root")?.addEventListener("click", (e) => {
      e.preventDefault();
      state.sectionFolder = null;
      render();
    });
    const openFolder = (name) => {
      state.sectionFolder = name;
      render();
    };
    app.querySelectorAll("[data-open-folder]").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.closest("[data-del-section]")) return;
        e.preventDefault();
        e.stopPropagation();
        openFolder(el.getAttribute("data-open-folder"));
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openFolder(el.getAttribute("data-open-folder"));
        }
      });
    });
    app.querySelectorAll("[data-del-section]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        try {
          await deleteSection(btn.getAttribute("data-del-section"), btn.getAttribute("data-ids"));
        } catch (err) {
          alert(err.message || String(err));
        }
      });
    });
    app.querySelectorAll("[data-act]").forEach((btn) => {
      btn.onclick = () => onTestAction(btn.dataset.act, Number(btn.dataset.id), btn.dataset.mode);
    });
  }

  async function onTestAction(act, id, mode) {
    if (act === "run") {
      await startAttempt({ test_id: id, mode: mode || "full", shuffle: false });
    } else if (act === "edit") {
      const t = await api(`/tests/${id}`);
      state.editor = testToEditor(t);
      setView("editor");
    } else if (act === "export") {
      const data = await api(`/tests/${id}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `test_${id}.json`;
      a.click();
    } else if (act === "del") {
      if (!confirm("Удалить тест?")) return;
      await api(`/tests/${id}`, { method: "DELETE" });
      await loadTests();
      render();
    }
  }

  async function startAttempt(body) {
    const data = await api("/attempts", { method: "POST", body: JSON.stringify(body) });
    state.attempt = data;
    state.idx = 0;
    state.selected = new Set();
    state.checked = false;
    state.lastAnswer = null;
    state.finish = null;
    localStorage.setItem(LS_ATTEMPT, String(data.attempt_id));
    state.view = "quiz";
    render();
  }

  async function continueAttempt() {
    const id = localStorage.getItem(LS_ATTEMPT);
    if (!id) {
      alert("Нет сохранённой попытки");
      return;
    }
    const data = await api(`/attempts/${id}`);
    if (data.status !== "active") {
      alert("Попытка уже завершена");
      localStorage.removeItem(LS_ATTEMPT);
      return;
    }
    state.attempt = {
      attempt_id: data.attempt_id,
      mode: data.mode,
      total: data.total,
      questions: data.questions,
    };
    const answered = new Set(Object.keys(data.answers || {}).map(Number));
    let idx = data.questions.findIndex((q) => !answered.has(q.id));
    if (idx < 0) idx = data.questions.length - 1;
    state.idx = idx;
    state.selected = new Set();
    state.checked = false;
    state.lastAnswer = null;
    state.finish = null;
    state.view = "quiz";
    render();
  }

  function currentQuestion() {
    return state.attempt?.questions?.[state.idx];
  }

  function renderQuiz() {
    const q = currentQuestion();
    if (!q) {
      app.innerHTML = `<p>Нет вопросов</p><button id="back">К тестам</button>`;
      app.querySelector("#back").onclick = () => setView("tests");
      return;
    }
    const total = state.attempt.total;
    const score = state.attempt._score || 0;
    const multi = q.type === "multiple";
    const opts = Object.entries(q.options || {});
    const ans = state.lastAnswer;

    const optionsHtml = opts
      .map(([key, text]) => {
        let cls = "option";
        if (state.checked && ans) {
          if ((ans.correct || []).includes(key)) cls += " correct";
          else if (state.selected.has(key)) cls += " wrong";
        }
        const inputType = multi ? "checkbox" : "radio";
        const checked = state.selected.has(key) ? "checked" : "";
        const disabled = state.checked ? "disabled" : "";
        return `<label class="${cls}">
          <input type="${inputType}" name="opt" value="${esc(key)}" ${checked} ${disabled} />
          <span><strong>${esc(key)}.</strong> ${esc(text)}</span>
        </label>`;
      })
      .join("");

    let feedback = "";
    if (state.checked && ans) {
      const mark = ans.is_correct ? "✅ Верно" : "❌ Неверно";
      const optExpl = Object.entries(ans.option_explanations || {})
        .filter(([k]) => state.selected.has(k) && !(ans.correct || []).includes(k))
        .map(([k, v]) => `<li><strong>${esc(k)}:</strong> ${esc(v)}</li>`)
        .join("");
      feedback = `<div class="explanation">
        <p><strong>${mark}</strong> · правильный ответ: ${(ans.correct || []).map(esc).join(", ")}</p>
        <p>💡 ${esc(ans.explanation)}</p>
        ${optExpl ? `<ul>${optExpl}</ul>` : ""}
      </div>`;
    }

    const code = q.code
      ? `<div class="code-block"><pre><code class="language-${esc(q.code.language)}">${esc(q.code.content)}</code></pre></div>`
      : "";

    app.innerHTML = `
      <div class="quiz-meta">
        <span>Вопрос ${state.idx + 1} / ${total}</span>
        <span>Счёт: ${score}</span>
      </div>
      <p class="muted">${esc(q.topic || "без темы")} · ${difficultyDots(q.difficulty)}</p>
      <h2>${esc(q.question)}</h2>
      ${code}
      <div class="options">${optionsHtml}</div>
      ${feedback}
      <div class="toolbar">
        ${
          state.checked
            ? `<button id="next">${state.idx + 1 >= total ? "Итог" : "Далее"}</button>`
            : `<button id="check">Проверить</button>`
        }
        <button class="secondary" id="abort">Завершить</button>
      </div>
    `;
    document.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));

    app.querySelectorAll('input[name="opt"]').forEach((inp) => {
      inp.addEventListener("change", () => {
        if (multi) {
          if (inp.checked) state.selected.add(inp.value);
          else state.selected.delete(inp.value);
        } else {
          state.selected = new Set([inp.value]);
          renderQuiz();
        }
      });
    });
    app.querySelector("#check")?.addEventListener("click", checkAnswer);
    app.querySelector("#next")?.addEventListener("click", nextQuestion);
    app.querySelector("#abort")?.addEventListener("click", finishAttempt);
  }

  async function checkAnswer() {
    const q = currentQuestion();
    if (!q || !state.selected.size) {
      alert("Выберите вариант");
      return;
    }
    const ans = await api(`/attempts/${state.attempt.attempt_id}/answer`, {
      method: "POST",
      body: JSON.stringify({ question_id: q.id, selected: [...state.selected] }),
    });
    state.lastAnswer = ans;
    state.checked = true;
    if (ans.is_correct) state.attempt._score = (state.attempt._score || 0) + 1;
    renderQuiz();
  }

  async function nextQuestion() {
    if (state.idx + 1 >= state.attempt.total) {
      await finishAttempt();
      return;
    }
    state.idx += 1;
    state.selected = new Set();
    state.checked = false;
    state.lastAnswer = null;
    renderQuiz();
  }

  async function finishAttempt() {
    const data = await api(`/attempts/${state.attempt.attempt_id}/finish`, { method: "POST" });
    state.finish = data;
    localStorage.removeItem(LS_ATTEMPT);
    state.view = "result";
    render();
  }

  function renderResult() {
    const f = state.finish;
    const topics = (f.by_topic || [])
      .map(
        (t) =>
          `<tr><td>${esc(t.topic)}</td><td>${t.correct}/${t.total}</td><td>${t.percent}%</td>
           <td class="bar">${"█".repeat(Math.round(t.percent / 10))}${"░".repeat(10 - Math.round(t.percent / 10))}</td></tr>`
      )
      .join("");
    const mistakes = (f.mistakes || [])
      .map(
        (m) => `<article class="card">
          <p><strong>${esc(m.question)}</strong></p>
          <p class="muted">Твой: ${(m.selected || []).join(", ") || "—"} · Верно: ${(m.correct || []).join(", ")}</p>
          <p>💡 ${esc(m.explanation)}</p>
        </article>`
      )
      .join("");

    app.innerHTML = `
      <h2>Итог</h2>
      <p class="score-big">${f.score_percent}%</p>
      <p>${f.correct_count} из ${f.total}</p>
      <table><thead><tr><th>Тема</th><th>Верно</th><th>%</th><th></th></tr></thead><tbody>${topics}</tbody></table>
      <h3>Ошибки</h3>
      <div class="cards">${mistakes || "<p class='muted'>Ошибок нет 🎉</p>"}</div>
      <div class="toolbar">
        <button id="retry">Повторить ошибки</button>
        <button id="to-review">Промпт по ошибкам → ИИ</button>
        <button class="secondary" id="to-tests">К тестам</button>
      </div>
    `;
    app.querySelector("#to-tests").onclick = async () => {
      await loadTests();
      setView("tests");
    };
    app.querySelector("#retry").onclick = async () => {
      await startAttempt({ mode: "mistakes", test_id: state.attempt?.test_id || null, shuffle: true });
    };
    app.querySelector("#to-review").onclick = () => {
      state.reviewSeed = {
        fromAttempt: true,
        finish: f,
        testId: state.attempt?.test_id || null,
      };
      setView("review");
    };
  }

  function renderImport() {
    app.innerHTML = `
      <h2>Импорт</h2>
      <p class="muted">Файлы из <code>examples/&lt;тег&gt;/*.json</code> подхватывает runner сам.
        Импорт через UI также сохраняет JSON в examples по первому тегу.</p>
      <div class="dropzone" id="drop">Перетащите .json сюда или кликните для выбора
        <input type="file" id="files" accept=".json,application/json" multiple hidden />
      </div>
      <label>Или вставьте JSON
        <textarea id="json" rows="14" placeholder='{"schema_version":1,"title":"…","questions":[…]}'></textarea>
      </label>
      <div class="toolbar">
        <button id="preview">Предпросмотр</button>
        <button id="do-import">Импортировать</button>
      </div>
      <div id="import-out"></div>
    `;
    const drop = app.querySelector("#drop");
    const fileInput = app.querySelector("#files");
    drop.onclick = () => fileInput.click();
    drop.ondragover = (e) => {
      e.preventDefault();
      drop.classList.add("drag");
    };
    drop.ondragleave = () => drop.classList.remove("drag");
    drop.ondrop = async (e) => {
      e.preventDefault();
      drop.classList.remove("drag");
      await uploadFiles(e.dataTransfer.files);
    };
    fileInput.onchange = () => uploadFiles(fileInput.files);
    app.querySelector("#preview").onclick = () => {
      try {
        const rawText = app.querySelector("#json").value.trim();
        if (!rawText) {
          state.importPreview = null;
          state.importError = "Вставь JSON в поле или перетащи файл. Пустой ввод не парсится.";
          showImportOut();
          return;
        }
        const raw = JSON.parse(rawText);
        const list = Array.isArray(raw) ? raw : [raw];
        state.importPreview = list.map((t) => ({
          title: t.title,
          n: (t.questions || []).length,
        }));
        state.importError = "";
      } catch (err) {
        state.importPreview = null;
        state.importError = String(err.message || err);
      }
      showImportOut();
    };
    app.querySelector("#do-import").onclick = async () => {
      try {
        const rawText = app.querySelector("#json").value.trim();
        if (!rawText) {
          state.importError = "Вставь JSON в поле или перетащи файл (либо положи в examples/<тег>/ — runner подхватит).";
          showImportOut();
          return;
        }
        const raw = JSON.parse(rawText);
        const res = await api("/import", { method: "POST", body: JSON.stringify(raw) });
        state.importError = "";
        const saved = (res.saved_to || []).join(", ");
        state.importPreview = (res.imported || []).map((x) => ({
          title: x.title + (saved ? ` → examples/${saved}` : ""),
          n: x.question_count,
          ok: true,
        }));
        showImportOut();
        await loadTests();
      } catch (err) {
        state.importError = String(err.message || err);
        showImportOut();
      }
    };

    function showImportOut() {
      const box = app.querySelector("#import-out");
      let html = "";
      if (state.importError) html += `<div class="error-box">${esc(state.importError)}</div>`;
      if (state.importPreview) {
        html += `<ul>${state.importPreview
          .map((p) => `<li>${esc(p.title)} — ${p.n} вопросов${p.ok ? " ✅" : ""}</li>`)
          .join("")}</ul>`;
      }
      box.innerHTML = html;
    }
  }

  async function uploadFiles(fileList) {
    const fd = new FormData();
    [...fileList].forEach((f) => fd.append("files", f));
    const headers = {};
    if (state.token) headers["X-Import-Token"] = state.token;
    const res = await fetch("/api/import/file", { method: "POST", headers, body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "upload failed");
    const box = app.querySelector("#import-out");
    box.innerHTML = `<ul>${(data.imported || [])
      .map((x) => `<li>${esc(x.title)} — ${x.question_count} ✅</li>`)
      .join("")}</ul>
      ${(data.errors || []).map((e) => `<div class="error-box">${esc(e.file)}: ${esc(e.error)}</div>`).join("")}`;
    await loadTests();
  }

  function emptyEditor() {
    return {
      id: null,
      schema_version: 1,
      external_id: "",
      title: "",
      description: "",
      tags: "",
      questions: [emptyQuestion()],
    };
  }

  function emptyQuestion() {
    return {
      type: "single",
      topic: "",
      difficulty: 1,
      question: "",
      code_language: "",
      code_content: "",
      options: [
        { key: "A", text: "", correct: true },
        { key: "B", text: "", correct: false },
      ],
      explanation: "",
    };
  }

  function testToEditor(t) {
    return {
      id: t.id,
      schema_version: 1,
      external_id: t.external_id || "",
      title: t.title,
      description: t.description || "",
      tags: (t.tags || []).join(", "),
      questions: (t.questions || []).map((q) => ({
        type: q.type,
        topic: q.topic || "",
        difficulty: q.difficulty,
        question: q.question,
        code_language: q.code?.language || "",
        code_content: q.code?.content || "",
        options: Object.entries(q.options || {}).map(([key, text]) => ({
          key,
          text,
          correct: (q.correct || []).includes(key),
        })),
        explanation: q.explanation,
        option_explanations: q.option_explanations || {},
      })),
    };
  }

  function editorToPayload(ed) {
    return {
      schema_version: 1,
      external_id: ed.external_id || null,
      title: ed.title,
      description: ed.description || null,
      tags: ed.tags
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      questions: ed.questions.map((q) => {
        const options = {};
        const correct = [];
        q.options.forEach((o) => {
          options[o.key] = o.text;
          if (o.correct) correct.push(o.key);
        });
        const item = {
          type: q.type,
          topic: q.topic || null,
          difficulty: Number(q.difficulty) || 1,
          question: q.question,
          options,
          correct,
          explanation: q.explanation,
          option_explanations: q.option_explanations || {},
        };
        if (q.code_language && q.code_content) {
          item.code = { language: q.code_language, content: q.code_content };
        }
        return item;
      }),
    };
  }

  function renderEditor() {
    if (!state.editor) state.editor = emptyEditor();
    const ed = state.editor;
    const qHtml = ed.questions
      .map((q, qi) => {
        const opts = q.options
          .map(
            (o, oi) => `<div class="toolbar">
              <input data-q="${qi}" data-o="${oi}" data-f="key" value="${esc(o.key)}" style="max-width:4rem" />
              <input data-q="${qi}" data-o="${oi}" data-f="text" value="${esc(o.text)}" placeholder="текст варианта" />
              <label><input type="checkbox" data-q="${qi}" data-o="${oi}" data-f="correct" ${o.correct ? "checked" : ""} /> верный</label>
              <button class="outline" data-rm-opt="${qi}:${oi}">×</button>
            </div>`
          )
          .join("");
        return `<div class="editor-q">
          <div class="toolbar">
            <strong>Вопрос ${qi + 1}</strong>
            <button class="outline" data-up="${qi}" ${qi === 0 ? "disabled" : ""}>↑</button>
            <button class="outline" data-down="${qi}" ${qi === ed.questions.length - 1 ? "disabled" : ""}>↓</button>
            <button class="contrast" data-rm-q="${qi}">Удалить</button>
          </div>
          <div class="toolbar">
            <label>Тип
              <select data-q="${qi}" data-f="type">
                ${["single", "multiple", "true_false"]
                  .map((t) => `<option value="${t}" ${q.type === t ? "selected" : ""}>${t}</option>`)
                  .join("")}
              </select>
            </label>
            <label>Тема<input data-q="${qi}" data-f="topic" value="${esc(q.topic)}" /></label>
            <label>Сложность<input type="number" min="1" max="5" data-q="${qi}" data-f="difficulty" value="${q.difficulty}" /></label>
          </div>
          <label>Текст<textarea data-q="${qi}" data-f="question" rows="3">${esc(q.question)}</textarea></label>
          <div class="toolbar">
            <label>Язык кода<input data-q="${qi}" data-f="code_language" value="${esc(q.code_language)}" placeholder="yaml" /></label>
          </div>
          <label>Код<textarea data-q="${qi}" data-f="code_content" rows="4">${esc(q.code_content)}</textarea></label>
          <p>Варианты</p>
          ${opts}
          <button class="outline" data-add-opt="${qi}">+ вариант</button>
          <label>Объяснение<textarea data-q="${qi}" data-f="explanation" rows="3">${esc(q.explanation)}</textarea></label>
        </div>`;
      })
      .join("");

    app.innerHTML = `
      <h2>${ed.id ? "Редактирование" : "Новый тест"}</h2>
      <label>Название<input id="title" value="${esc(ed.title)}" /></label>
      <label>external_id<input id="ext" value="${esc(ed.external_id)}" /></label>
      <label>Описание<textarea id="desc" rows="2">${esc(ed.description)}</textarea></label>
      <label>Теги (через запятую)<input id="tags" value="${esc(ed.tags)}" /></label>
      ${qHtml}
      <div class="toolbar">
        <button id="add-q">+ вопрос</button>
        <button id="save">Сохранить</button>
        <button class="secondary" id="cancel">Отмена</button>
      </div>
      <div id="ed-err"></div>
    `;

    const bindField = (el) => {
      const qi = el.dataset.q;
      const oi = el.dataset.o;
      const f = el.dataset.f;
      if (qi == null || !f) return;
      const apply = () => {
        if (oi != null) {
          if (f === "correct") ed.questions[qi].options[oi].correct = el.checked;
          else ed.questions[qi].options[oi][f] = el.value;
        } else {
          ed.questions[qi][f] = el.type === "number" ? Number(el.value) : el.value;
        }
      };
      el.addEventListener("change", apply);
      el.addEventListener("input", apply);
    };
    app.querySelectorAll("[data-f]").forEach(bindField);
    app.querySelector("#title").oninput = (e) => (ed.title = e.target.value);
    app.querySelector("#ext").oninput = (e) => (ed.external_id = e.target.value);
    app.querySelector("#desc").oninput = (e) => (ed.description = e.target.value);
    app.querySelector("#tags").oninput = (e) => (ed.tags = e.target.value);

    app.querySelector("#add-q").onclick = () => {
      ed.questions.push(emptyQuestion());
      renderEditor();
    };
    app.querySelectorAll("[data-add-opt]").forEach((b) => {
      b.onclick = () => {
        const qi = Number(b.dataset.addOpt);
        const keys = "ABCDEFGH";
        const used = new Set(ed.questions[qi].options.map((o) => o.key));
        const key = [...keys].find((k) => !used.has(k)) || `O${ed.questions[qi].options.length}`;
        ed.questions[qi].options.push({ key, text: "", correct: false });
        renderEditor();
      };
    });
    app.querySelectorAll("[data-rm-opt]").forEach((b) => {
      b.onclick = () => {
        const [qi, oi] = b.dataset.rmOpt.split(":").map(Number);
        ed.questions[qi].options.splice(oi, 1);
        renderEditor();
      };
    });
    app.querySelectorAll("[data-rm-q]").forEach((b) => {
      b.onclick = () => {
        ed.questions.splice(Number(b.dataset.rmQ), 1);
        renderEditor();
      };
    });
    app.querySelectorAll("[data-up]").forEach((b) => {
      b.onclick = () => {
        const i = Number(b.dataset.up);
        [ed.questions[i - 1], ed.questions[i]] = [ed.questions[i], ed.questions[i - 1]];
        renderEditor();
      };
    });
    app.querySelectorAll("[data-down]").forEach((b) => {
      b.onclick = () => {
        const i = Number(b.dataset.down);
        [ed.questions[i], ed.questions[i + 1]] = [ed.questions[i + 1], ed.questions[i]];
        renderEditor();
      };
    });
    app.querySelector("#cancel").onclick = () => setView("tests");
    app.querySelector("#save").onclick = async () => {
      try {
        const payload = editorToPayload(ed);
        if (ed.id) await api(`/tests/${ed.id}`, { method: "PUT", body: JSON.stringify(payload) });
        else await api("/tests", { method: "POST", body: JSON.stringify(payload) });
        await loadTests();
        setView("tests");
      } catch (err) {
        app.querySelector("#ed-err").innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
      }
    };
  }

  async function renderStats() {
    if (!state.stats) state.stats = await api("/stats");
    const s = state.stats;
    const topics = (s.topics || [])
      .map(
        (t) =>
          `<tr><td>${esc(t.topic)}</td><td>${t.correct}/${t.total}</td><td>${t.percent}%</td>
           <td class="bar">${"█".repeat(Math.round(t.percent / 10))}${"░".repeat(10 - Math.round(t.percent / 10))}</td></tr>`
      )
      .join("");
    const bad = (s.problematic_questions || [])
      .map(
        (q) =>
          `<tr><td>${esc(q.question)}</td><td>${esc(q.topic || "")}</td><td>${q.percent}% (${q.correct}/${q.total})</td></tr>`
      )
      .join("");
    const hist = (s.recent_attempts || [])
      .map(
        (a) =>
          `<tr><td>#${a.id}</td><td>${esc(a.mode)}</td><td>${a.score_percent ?? "—"}%</td><td>${esc(a.finished_at || "")}</td></tr>`
      )
      .join("");

    app.innerHTML = `
      <h2>Статистика</h2>
      <button id="reload-stats" class="outline">Обновить</button>
      <h3>По темам</h3>
      <table><thead><tr><th>Тема</th><th>Верно</th><th>%</th><th></th></tr></thead><tbody>${topics}</tbody></table>
      <h3>Проблемные вопросы</h3>
      <table><thead><tr><th>Вопрос</th><th>Тема</th><th>Успех</th></tr></thead><tbody>${bad}</tbody></table>
      <h3>История попыток</h3>
      <table><thead><tr><th>ID</th><th>Режим</th><th>%</th><th>Когда</th></tr></thead><tbody>${hist}</tbody></table>
    `;
    app.querySelector("#reload-stats").onclick = async () => {
      state.stats = await api("/stats");
      renderStats();
    };
  }

  function slugify(s) {
    return String(s || "")
      .trim()
      .toLowerCase()
      .replace(/[ё]/g, "e")
      .replace(/[^a-z0-9а-я]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .replace(/-+/g, "-") || "test";
  }

  function buildAiPrompt(f) {
    const section = (f.section || "k8s").trim();
    const fileStem = slugify(f.filename || f.title || "test");
    const types = [];
    if (f.typeSingle) types.push("single");
    if (f.typeMultiple) types.push("multiple");
    if (f.typeTf) types.push("true_false");
    const typesLine = types.length ? types.join(" / ") : "single / multiple / true_false";
    const codeLine = f.withCode
      ? `yes, languages: ${f.codeLangs || "yaml, bash, python, json"}`
      : "no (or minimal)";

    return `Create a quiz in schema_version 1 format.

## Parameters
- Section (examples folder): ${section}
- File name: ${fileStem}.json
- title: ${f.title || "…"}
- description: ${f.description || "…"}
- tags: [${[section, ...(f.tags || "").split(",").map((x) => x.trim()).filter(Boolean)]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((t) => `"${t}"`)
      .join(", ")}]
- Number of questions: ${f.count || 10}
- Difficulty (1–5): ${f.difficulty || "2–3"}
- Question types: ${typesLine}
- Code blocks: ${codeLine}
- Audience: ${f.audience || "DevOps / Linux junior–middle"}
- Topic focus: ${f.focus || "…"}
- Extra requirements: ${f.extra || "—"}

## Strict JSON rules
1. Root object: schema_version=1, external_id="${section}/${fileStem}", title, description, tags[], questions[].
2. Each question:
   - type: single | multiple | true_false
   - topic, difficulty (1–5)
   - question and explanation are non-empty
   - options: 2–8 keys (A/B/C… or true/false), non-empty texts, unique keys
   - correct: only keys from options; single and true_false have exactly 1; multiple has ≥ 1
   - code (optional): { "language": "…", "content": "…" }
   - option_explanations (optional) for the wrong options
3. Do not invent flags or APIs that do not exist. Code samples should be short and realistic.
4. Return ONLY one valid JSON object (a \`\`\`json fence is fine), ready to save as
   examples/${section}/${fileStem}.json — no surrounding commentary.`;
  }

  function renderPrompt() {
    const f = state.promptForm || {
      section: "k8s",
      filename: "",
      title: "",
      description: "",
      tags: "",
      count: 10,
      difficulty: "2-3",
      typeSingle: true,
      typeMultiple: true,
      typeTf: true,
      withCode: true,
      codeLangs: "yaml, bash, python, json",
      audience: "DevOps / Linux junior–middle",
      focus: "",
      extra: "",
    };
    state.promptForm = f;

    const preview = buildAiPrompt(f);
    app.innerHTML = `
      <h2>Промпт для ИИ</h2>
      <p class="muted">Заполни форму → скопируй промпт в чат/агента → сохрани ответ как
        <code>examples/&lt;раздел&gt;/&lt;файл&gt;.json</code>. LLM в приложение не встроен.</p>
      <div class="prompt-grid">
        <label>Раздел (папка)<input id="pf-section" value="${esc(f.section)}" placeholder="k8s" /></label>
        <label>Имя файла (без .json)<input id="pf-filename" value="${esc(f.filename)}" placeholder="networking" /></label>
        <label>Название теста<input id="pf-title" value="${esc(f.title)}" placeholder="Kubernetes: сеть" /></label>
        <label>Число вопросов<input id="pf-count" type="number" min="3" max="40" value="${esc(f.count)}" /></label>
        <label>Сложность<input id="pf-difficulty" value="${esc(f.difficulty)}" placeholder="2-3" /></label>
        <label>Доп. теги (через запятую)<input id="pf-tags" value="${esc(f.tags)}" placeholder="cni, networkpolicy" /></label>
      </div>
      <label>Описание<textarea id="pf-description" rows="2">${esc(f.description)}</textarea></label>
      <label>Фокус тем<textarea id="pf-focus" rows="3" placeholder="Service, Ingress, NetworkPolicy, DNS…">${esc(f.focus)}</textarea></label>
      <label>Аудитория<input id="pf-audience" value="${esc(f.audience)}" /></label>
      <label>Особые требования<textarea id="pf-extra" rows="2" placeholder="Больше вопросов с YAML; без устаревшего docker-shim…">${esc(f.extra)}</textarea></label>
      <fieldset>
        <legend>Типы вопросов</legend>
        <label><input type="checkbox" id="pf-single" ${f.typeSingle ? "checked" : ""} /> single</label>
        <label><input type="checkbox" id="pf-multiple" ${f.typeMultiple ? "checked" : ""} /> multiple</label>
        <label><input type="checkbox" id="pf-tf" ${f.typeTf ? "checked" : ""} /> true_false</label>
      </fieldset>
      <fieldset>
        <legend>Код в вопросах</legend>
        <label><input type="checkbox" id="pf-code" ${f.withCode ? "checked" : ""} /> включать блоки code</label>
        <label>Языки<input id="pf-langs" value="${esc(f.codeLangs)}" /></label>
      </fieldset>
      <div class="toolbar">
        <button id="pf-refresh" class="outline">Обновить предпросмотр</button>
        <button id="pf-copy">Скопировать промпт</button>
        <button id="pf-download" class="secondary">Скачать .txt</button>
      </div>
      <label>Готовый промпт
        <textarea id="pf-out" rows="22" readonly>${esc(preview)}</textarea>
      </label>
      <p class="muted">Текстовый шаблон также лежит в <code>examples/_PROMPT_TEMPLATE.md</code>.</p>
    `;

    const readForm = () => {
      state.promptForm = {
        section: app.querySelector("#pf-section").value.trim() || "k8s",
        filename: app.querySelector("#pf-filename").value.trim(),
        title: app.querySelector("#pf-title").value.trim(),
        description: app.querySelector("#pf-description").value.trim(),
        tags: app.querySelector("#pf-tags").value.trim(),
        count: Number(app.querySelector("#pf-count").value) || 10,
        difficulty: app.querySelector("#pf-difficulty").value.trim(),
        typeSingle: app.querySelector("#pf-single").checked,
        typeMultiple: app.querySelector("#pf-multiple").checked,
        typeTf: app.querySelector("#pf-tf").checked,
        withCode: app.querySelector("#pf-code").checked,
        codeLangs: app.querySelector("#pf-langs").value.trim(),
        audience: app.querySelector("#pf-audience").value.trim(),
        focus: app.querySelector("#pf-focus").value.trim(),
        extra: app.querySelector("#pf-extra").value.trim(),
      };
      return state.promptForm;
    };

    const syncOut = () => {
      app.querySelector("#pf-out").value = buildAiPrompt(readForm());
    };

    app.querySelector("#pf-refresh").onclick = () => {
      syncOut();
    };
    app.querySelectorAll("input, textarea").forEach((el) => {
      if (el.id === "pf-out") return;
      el.addEventListener("change", syncOut);
    });
    app.querySelector("#pf-copy").onclick = async () => {
      syncOut();
      const text = app.querySelector("#pf-out").value;
      try {
        await navigator.clipboard.writeText(text);
        alert("Промпт скопирован");
      } catch {
        app.querySelector("#pf-out").select();
        document.execCommand("copy");
        alert("Промпт скопирован");
      }
    };
    app.querySelector("#pf-download").onclick = () => {
      syncOut();
      const text = app.querySelector("#pf-out").value;
      const name = `${slugify(state.promptForm.section)}-${slugify(state.promptForm.filename || state.promptForm.title || "prompt")}.txt`;
      const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
    };
  }

  function buildReviewPrompt(bundle, opts) {
    const section = (opts.section || "review").trim() || "review";
    const fileStem = slugify(opts.filename || opts.title || "errors-practice");
    const count = opts.count || 10;
    const testsBlock = (bundle.tests || [])
      .map((t) => {
        const best = t.best_percent != null ? `${t.best_percent}%` : "—";
        const last = t.last_percent != null ? `${t.last_percent}%` : "—";
        return `- «${t.title}» (id=${t.test_id}, теги: ${(t.tags || []).join(", ") || "—"}) · лучший ${best}, последний ${last}, ошибок в выборке: ${t.mistake_count}`;
      })
      .join("\n");

    const topicsBlock = (bundle.topics || [])
      .map(
        (t) =>
          `- ${t.topic}: верно ${t.percent_correct}% (${t.answered - t.wrong}/${t.answered}), ошибок ${t.wrong}`
      )
      .join("\n");

    const mistakes = bundle.mistakes || [];
    const mistakesBlock = mistakes
      .map((m, i) => {
        const optsList = Object.entries(m.options || {})
          .map(([k, v]) => `    ${k}) ${v}`)
          .join("\n");
        const code = m.code
          ? `\n  code (${m.code.language}):\n\`\`\`${m.code.language}\n${m.code.content}\n\`\`\``
          : "";
        return `### Ошибка ${i + 1}
- Тест: ${m.test_title}
- Тема: ${m.topic || "—"} · тип: ${m.type} · сложность: ${m.difficulty}
- Вопрос: ${m.question}${code}
- Варианты:
${optsList}
- Ответ ученика: [${(m.selected || []).join(", ") || "—"}]
- Правильно: [${(m.correct || []).join(", ")}]
- Объяснение: ${m.explanation || "—"}`;
      })
      .join("\n\n");

    return `Ты методист по DevOps/Linux/Kubernetes. По результатам прохождения тестов оцени пробелы ученика и создай НОВЫЙ тест для работы над ошибками.

## Цель
1. Кратко (5–8 пунктов) разбери слабые темы и типичные ошибки.
2. Затем верни ОДИН JSON теста schema_version 1 для practice — новые вопросы по слабым местам (не копируй дословно старые).
3. После JSON можно коротко написать, на что обратить внимание при повторении.

## Результаты по выбранным тестам
${testsBlock || "(нет данных)"}

## Сводка по темам
${topicsBlock || "(нет ответов)"}

## Детали ошибок (${mistakes.length})
${mistakesBlock || "(ошибок нет — сделай закрепляющий тест средней сложности)"}

## Параметры нового теста
- Раздел (папка examples): ${section}
- Файл: ${fileStem}.json
- title: ${opts.title || "Работа над ошибками"}
- description: практика по слабым темам после разбора результатов
- tags: ["${section}", "review", "mistakes"]
- Число вопросов: ${count}
- Сложность: чуть выше уровня ошибок, но без ловушек на терминологию
- Типы: single / multiple / true_false (смешай)
- Блоки code: по необходимости (yaml/bash/python/json)
${opts.extra ? `- Дополнительно от ученика: ${opts.extra}` : ""}

## Строгие правила JSON
1. schema_version=1, external_id="${section}/${fileStem}", title, description, tags[], questions[].
2. Вопрос: type, topic, difficulty 1–5, question, explanation непустые.
3. options 2–8 ключей; correct только из options; single/true_false — ровно 1 correct; multiple — ≥1.
4. Не выдумывай несуществующие API/флаги.
5. Итоговый тест верни как один JSON-объект (можно в \`\`\`json), готовый к сохранению в examples/${section}/${fileStem}.json.`;
  }

  async function renderReview() {
    await loadTests();
    const rf = state.reviewForm || {
      section: "review",
      filename: "errors-practice",
      title: "Работа над ошибками",
      count: 10,
      extra: "",
      selected: new Set(),
    };
    state.reviewForm = rf;

    // seed from attempt result
    if (state.reviewSeed?.fromAttempt && state.reviewSeed.finish) {
      const finish = state.reviewSeed.finish;
      const fakeBundle = {
        tests: [
          {
            test_id: state.reviewSeed.testId,
            title: "Текущая попытка",
            tags: [],
            mistake_count: (finish.mistakes || []).length,
            best_percent: finish.score_percent,
            last_percent: finish.score_percent,
          },
        ],
        topics: (finish.by_topic || []).map((t) => ({
          topic: t.topic,
          wrong: t.total - t.correct,
          answered: t.total,
          percent_correct: t.percent,
        })),
        mistakes: (finish.mistakes || []).map((m) => ({
          test_title: "Текущая попытка",
          topic: m.topic,
          type: "—",
          difficulty: "—",
          question: m.question,
          options: m.options || {},
          selected: m.selected || [],
          correct: m.correct || [],
          explanation: m.explanation || "",
          code: null,
        })),
      };
      state.reviewBundle = fakeBundle;
      state.reviewOut = buildReviewPrompt(fakeBundle, rf);
      if (state.reviewSeed.testId) rf.selected.add(state.reviewSeed.testId);
      state.reviewSeed = null;
    }

    const rows = (state.tests || [])
      .map((t) => {
        const has = t.best_percent != null || t.last_percent != null;
        const checked = rf.selected.has(t.id) ? "checked" : "";
        const disabled = has ? "" : "disabled";
        const score =
          t.last_percent != null
            ? `последний ${t.last_percent}%${t.best_percent != null ? ` · лучший ${t.best_percent}%` : ""}`
            : "ещё не проходился";
        return `<label class="option review-pick ${has ? "" : "muted"}">
          <input type="checkbox" data-tid="${t.id}" ${checked} ${disabled} />
          <span><strong>${esc(t.title)}</strong><br/><span class="muted">${t.question_count} вопр. · ${esc(score)}</span></span>
        </label>`;
      })
      .join("");

    app.innerHTML = `
      <h2>Работа над ошибками → промпт для ИИ</h2>
      <p class="muted">Выдели пройденные тесты → сформируй промпт с ошибками и слабыми темами →
        отправь в нейросеть → сохрани новый JSON в <code>examples/&lt;раздел&gt;/</code>.</p>
      <div class="options review-list">${rows || "<p class='muted'>Нет тестов</p>"}</div>
      <div class="prompt-grid">
        <label>Раздел нового теста<input id="rv-section" value="${esc(rf.section)}" /></label>
        <label>Имя файла<input id="rv-filename" value="${esc(rf.filename)}" /></label>
        <label>Название<input id="rv-title" value="${esc(rf.title)}" /></label>
        <label>Число вопросов<input id="rv-count" type="number" min="3" max="40" value="${esc(rf.count)}" /></label>
      </div>
      <label>Комментарий для ИИ<textarea id="rv-extra" rows="2" placeholder="Больше практики с NetworkPolicy, меньше теории…">${esc(rf.extra)}</textarea></label>
      <div class="toolbar">
        <button id="rv-build">Сформировать промпт</button>
        <button id="rv-copy" class="secondary" ${state.reviewOut ? "" : "disabled"}>Скопировать</button>
        <button id="rv-download" class="outline" ${state.reviewOut ? "" : "disabled"}>Скачать .txt</button>
      </div>
      <div id="rv-meta" class="muted">${
        state.reviewBundle
          ? `Ошибок в выборке: ${state.reviewBundle.total_mistakes ?? (state.reviewBundle.mistakes || []).length}`
          : "Выбери тесты и нажми «Сформировать промпт»"
      }</div>
      <label>Промпт
        <textarea id="rv-out" rows="24" readonly>${esc(state.reviewOut || "")}</textarea>
      </label>
    `;

    app.querySelectorAll("input[data-tid]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const id = Number(inp.dataset.tid);
        if (inp.checked) rf.selected.add(id);
        else rf.selected.delete(id);
      });
    });

    const readOpts = () => {
      rf.section = app.querySelector("#rv-section").value.trim() || "review";
      rf.filename = app.querySelector("#rv-filename").value.trim();
      rf.title = app.querySelector("#rv-title").value.trim();
      rf.count = Number(app.querySelector("#rv-count").value) || 10;
      rf.extra = app.querySelector("#rv-extra").value.trim();
      return rf;
    };

    app.querySelector("#rv-build").onclick = async () => {
      const opts = readOpts();
      const ids = [...opts.selected];
      if (!ids.length && !state.reviewBundle) {
        alert("Выбери хотя бы один пройденный тест");
        return;
      }
      try {
        if (ids.length) {
          const bundle = await api("/review/bundle", {
            method: "POST",
            body: JSON.stringify({ test_ids: ids, only_mistakes: true, limit: 80 }),
          });
          state.reviewBundle = bundle;
        }
        state.reviewOut = buildReviewPrompt(state.reviewBundle, opts);
        renderReview();
      } catch (err) {
        alert(err.message || String(err));
      }
    };

    app.querySelector("#rv-copy").onclick = async () => {
      const text = app.querySelector("#rv-out").value;
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        alert("Промпт скопирован");
      } catch {
        app.querySelector("#rv-out").select();
        document.execCommand("copy");
      }
    };

    app.querySelector("#rv-download").onclick = () => {
      const text = app.querySelector("#rv-out").value;
      if (!text) return;
      const opts = readOpts();
      const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${slugify(opts.section)}-${slugify(opts.filename || "errors")}.txt`;
      a.click();
    };
  }

  function render() {
    if (state.view === "tests") renderTests();
    else if (state.view === "quiz") renderQuiz();
    else if (state.view === "result") renderResult();
    else if (state.view === "import") renderImport();
    else if (state.view === "editor") renderEditor();
    else if (state.view === "stats") renderStats();
    else if (state.view === "prompt") renderPrompt();
    else if (state.view === "review") renderReview();
    else if (state.view === "books") renderBooks();
  }

  async function renderBooks() {
    let jobs = [];
    let ollama = state._ollamaCache || null;
    try {
      const now = Date.now();
      const needOllama = !state._ollamaCache || now - (state._ollamaAt || 0) > 20000;
      const tasks = [
        api("/books"),
        fetch("/api/config").then((r) => r.json()),
      ];
      if (needOllama) tasks.splice(1, 0, api("/books/ollama"));
      const results = await Promise.all(tasks);
      jobs = results[0].items || [];
      let cfg;
      if (needOllama) {
        ollama = results[1];
        cfg = results[2];
        state._ollamaCache = ollama;
        state._ollamaAt = now;
      } else {
        cfg = results[1];
      }
      if (cfg.ollama_model) state.ollamaModel = cfg.ollama_model;
      if (cfg.ollama_base_url) state.ollamaBase = cfg.ollama_base_url;
    } catch (err) {
      app.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
      return;
    }

    if (!state.selectedBookId && jobs[0]) state.selectedBookId = jobs[0].id;
    const selectedId = state.selectedBookId;
    let detail = null;
    if (selectedId) {
      try {
        detail = await api(`/books/${selectedId}?log=1`);
      } catch {
        detail = null;
      }
    }

    const ollamaLine = ollama?.ok
      ? `✅ Ollama OK · <code>${esc(state.ollamaModel || ollama.configured || "")}</code> @ <code>${esc(state.ollamaBase || ollama.base_url || "")}</code>`
      : `❌ Ollama недоступна: ${esc(ollama?.error || "unknown")} (<code>${esc(ollama?.base_url || "")}</code>). В Docker нужен host.docker.internal или IP хоста, не 127.0.0.1`;

    const statusLabel = {
      queued: "⏳ в очереди",
      extracting: "📄 читаю PDF",
      generating: "🧠 Трудится Тестописец",
      cancelling: "⏹ останавливаю…",
      cancelled: "⏹ остановлено",
      done: "✅ готово",
      failed: "❌ ошибка",
    };
    const runningStatuses = ["queued", "extracting", "generating", "cancelling"];

    const rowActions = (j) => {
      const bits = [];
      if (["queued", "extracting", "generating"].includes(j.status)) {
        bits.push(`<button class="contrast" data-stop="${j.id}">Стоп</button>`);
      }
      if (j.status === "cancelling") {
        bits.push(`<button class="contrast" data-stop="${j.id}" data-force="1">Стоп сейчас</button>`);
        bits.push(`<button class="secondary" data-del="${j.id}" data-force="1">Удалить</button>`);
      }
      if (["done", "failed", "cancelled"].includes(j.status)) {
        bits.push(`<button class="outline" data-retry="${j.id}">Повтор</button>`);
        bits.push(`<button class="secondary" data-del="${j.id}">Удалить</button>`);
      }
      return bits.join(" ") || "—";
    };

    const rows = jobs
      .map((j) => {
        const active = j.id === selectedId ? "active-row" : "";
        const prog =
          j.page_count > 0
            ? `${j.pages_done}/${j.page_count} · ${j.tests_generated} тестов · ${j.progress_percent || 0}%`
            : statusLabel[j.status] || j.status;
        return `<tr class="${active}" data-select-job="${j.id}" style="cursor:pointer">
          <td>#${j.id}</td>
          <td>${esc(j.title)}<br/><span class="muted">${esc(j.pdf_name || "")} · <code>examples/${esc(j.slug)}/</code></span>
            ${j.current_step ? `<br/><span class="muted">${esc(j.current_step).slice(0, 120)}</span>` : ""}
          </td>
          <td>${esc(statusLabel[j.status] || j.status)}</td>
          <td>${esc(prog)}</td>
          <td class="book-actions">${rowActions(j)}</td>
        </tr>`;
      })
      .join("");

    const pct = detail?.progress_percent || 0;
    const logText = (detail?.log_lines || []).join("\n");
    const acceptBanner = state.bookAcceptBanner
      ? `<div class="ok-box">${esc(state.bookAcceptBanner)}</div>`
      : "";

    app.innerHTML = `
      <h2>Книги PDF → тесты (Тестописец / Ollama)</h2>
      <p class="${ollama?.ok ? "muted" : "error-box"}">${ollamaLine}</p>
      <ol class="muted book-steps">
        <li>Приём PDF на сервер → <code>books/job-N/source.pdf</code></li>
        <li>Очистка текста → <code>readable.md</code></li>
        <li>Фрагменты (~5 стр.) → тест ≈15 вопросов в <code>examples/&lt;книга&gt;/</code> (раздел-папка в UI)</li>
        <li>Runner импортирует JSON в БД</li>
      </ol>
      ${acceptBanner}
      <div class="dropzone" id="book-drop">Перетащите PDF или кликните
        <div id="book-file-label" class="muted" style="margin-top:0.5rem">файл не выбран</div>
        <input type="file" id="book-file" accept="application/pdf,.pdf" hidden />
      </div>
      <label>Название книги (раздел)<input id="book-title" placeholder="Kubernetes in Action" /></label>
      <div class="toolbar">
        <button id="book-upload">Загрузить и запустить</button>
        <button id="book-refresh" class="outline">Обновить</button>
        <button id="book-clear" class="secondary">Очистить историю</button>
      </div>
      <div id="book-msg" class="muted"></div>
      <table>
        <thead><tr><th>ID</th><th>Книга / текущий шаг</th><th>Статус</th><th>Прогресс</th><th>Действия</th></tr></thead>
        <tbody>${rows || "<tr><td colspan='5' class='muted'>Пока пусто</td></tr>"}</tbody>
      </table>
      ${
        detail
          ? `<h3>Задача #${detail.id}: ${esc(detail.title)}</h3>
        <p><strong>${esc(statusLabel[detail.status] || detail.status)}</strong>
          · PDF: <code>${esc(detail.pdf_name || "—")}</code>
          · тестов: <strong>${detail.tests_generated}</strong>
          · стр. ${detail.pages_done}/${detail.page_count || "?"}</p>
        <div class="progress"><span style="width:${pct}%"></span></div>
        <p class="muted">${esc(detail.current_step || "ожидание…")}</p>
        ${detail.error ? `<div class="error-box">${esc(detail.error)}</div>` : ""}
        <label>Журнал процесса (live)
          <textarea id="book-log" rows="16" readonly>${esc(logText || "Пока пусто — выбери задачу или дождись старта")}</textarea>
        </label>`
          : ""
      }
    `;

    const drop = app.querySelector("#book-drop");
    const fileInput = app.querySelector("#book-file");
    const fileLabel = app.querySelector("#book-file-label");
    const showFile = () => {
      const f = fileInput.files?.[0];
      fileLabel.textContent = f
        ? `✅ Выбран: ${f.name} (${(f.size / 1024 / 1024).toFixed(2)} МБ)`
        : "файл не выбран";
    };
    drop.onclick = () => fileInput.click();
    fileInput.onchange = showFile;
    drop.ondragover = (e) => {
      e.preventDefault();
      drop.classList.add("drag");
    };
    drop.ondragleave = () => drop.classList.remove("drag");
    drop.ondrop = (e) => {
      e.preventDefault();
      drop.classList.remove("drag");
      if (e.dataTransfer.files?.[0]) {
        fileInput.files = e.dataTransfer.files;
        showFile();
      }
    };

    app.querySelectorAll("[data-select-job]").forEach((tr) => {
      tr.onclick = (e) => {
        if (e.target.closest("button")) return;
        state.selectedBookId = Number(tr.dataset.selectJob);
        renderBooks();
      };
    });

    const upload = async () => {
      const f = fileInput.files?.[0];
      if (!f) {
        alert("Выбери PDF");
        return;
      }
      if (!ollama?.ok) {
        if (!confirm("Ollama сейчас недоступна. Всё равно загрузить PDF в очередь?")) return;
      }
      const fd = new FormData();
      fd.append("file", f);
      const title = app.querySelector("#book-title").value.trim();
      if (title) fd.append("title", title);
      const headers = {};
      if (state.token) headers["X-Import-Token"] = state.token;
      app.querySelector("#book-msg").textContent = "Загружаю PDF на сервер…";
      app.querySelector("#book-upload").disabled = true;
      try {
        const res = await fetch("/api/books/upload", { method: "POST", headers, body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
        state.selectedBookId = data.id;
        state.bookAcceptBanner = `PDF принят: ${data.upload_name || f.name} (${((data.upload_bytes || f.size) / 1024).toFixed(1)} КБ) → задача #${data.id}, раздел examples/${data.slug}/. Смотри журнал ниже.`;
        app.querySelector("#book-msg").textContent = "Принято, запускаю обработку…";
        renderBooks();
      } catch (err) {
        app.querySelector("#book-msg").innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
        app.querySelector("#book-upload").disabled = false;
      }
    };

    app.querySelector("#book-upload").onclick = upload;
    app.querySelector("#book-refresh").onclick = () => {
      state._ollamaAt = 0;
      renderBooks();
    };
    app.querySelector("#book-clear").onclick = async () => {
      if (!confirm("Остановить все задачи и очистить всю историю книг (папки books/job-N)? Примеры в examples/ не трогаем.")) {
        return;
      }
      try {
        const res = await api("/books?delete_examples=0&force=1", { method: "DELETE" });
        state.bookAcceptBanner = `Очищено записей: ${res.count || 0}`;
        state.selectedBookId = null;
        renderBooks();
      } catch (err) {
        alert(err.message || String(err));
      }
    };
    app.querySelectorAll("[data-retry]").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        state.selectedBookId = Number(btn.dataset.retry);
        await api(`/books/${btn.dataset.retry}/retry`, { method: "POST", body: "{}" });
        state.bookAcceptBanner = `Повтор задачи #${btn.dataset.retry} поставлен в очередь`;
        renderBooks();
      };
    });
    app.querySelectorAll("[data-stop]").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const id = Number(btn.dataset.stop);
        const force = btn.dataset.force === "1";
        btn.disabled = true;
        try {
          await api(`/books/${id}/cancel${force ? "?force=1" : ""}`, {
            method: "POST",
            body: "{}",
          });
          state.selectedBookId = id;
          state.bookAcceptBanner = force
            ? `Задача #${id} остановлена принудительно`
            : `Остановка задачи #${id}…`;
          renderBooks();
        } catch (err) {
          alert(err.message || String(err));
          btn.disabled = false;
        }
      };
    });
    app.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const id = Number(btn.dataset.del);
        const force = btn.dataset.force === "1" ? "&force=1" : "";
        if (!confirm(`Удалить задачу #${id} из истории и папку books/job-${id}?`)) return;
        try {
          await api(`/books/${id}?delete_examples=0${force}`, { method: "DELETE" });
          if (state.selectedBookId === id) state.selectedBookId = null;
          state.bookAcceptBanner = `Удалена задача #${id}`;
          renderBooks();
        } catch (err) {
          alert(err.message || String(err));
        }
      };
    });

    const logEl = app.querySelector("#book-log");
    if (logEl) logEl.scrollTop = logEl.scrollHeight;

    const running = jobs.some((j) => runningStatuses.includes(j.status));
    clearTimeout(state._booksTimer);
    if (running || (detail && runningStatuses.includes(detail.status))) {
      state._booksTimer = setTimeout(() => {
        if (state.view === "books") renderBooks();
      }, 4000);
    }
  }

  document.addEventListener("keydown", (e) => {
    if (state.view !== "quiz") return;
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (e.key >= "1" && e.key <= "8") {
      const q = currentQuestion();
      if (!q || state.checked) return;
      const keys = Object.keys(q.options || {});
      const key = keys[Number(e.key) - 1];
      if (!key) return;
      if (q.type === "multiple") {
        if (state.selected.has(key)) state.selected.delete(key);
        else state.selected.add(key);
      } else {
        state.selected = new Set([key]);
      }
      renderQuiz();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (state.checked) nextQuestion();
      else checkAnswer();
    }
  });

  async function init() {
    try {
      const cfg = await fetch("/api/config").then((r) => r.json());
      state.token = cfg.import_token || "";
      await loadTests();
      render();
    } catch (err) {
      app.innerHTML = `<div class="error-box">Не удалось загрузить API: ${esc(err.message)}</div>`;
    }
  }

  init();
})();
