"use strict";
const $ = id => document.getElementById(id);
const typeNames = {fact: "Утверждение автора", opinion: "Мнение", question: "Вопрос", recommendation: "Рекомендация", problem: "Проблема", solution: "Решение", excerpt: "Выдержка по словам темы"};
let currentReport = null;
let topicSynonyms = {};
let polling = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = false;
}
async function api(path, payload) {
  const options = payload === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Ошибка ${response.status}`);
  return result;
}
function topicValue() {
  const split = id => $(id).value.split(",").map(s => s.trim()).filter(Boolean);
  return {name: $("topic").value.trim(), description: $("description").value.trim(), keywords: split("keywords"), exclude_keywords: split("exclusions"), synonyms: topicSynonyms};
}
function setTopic(topic) {
  $("topic").value = topic.name || "";
  $("description").value = topic.description || "";
  $("keywords").value = (topic.keywords || []).join(", ");
  $("exclusions").value = (topic.exclude_keywords || []).join(", ");
  topicSynonyms = topic.synonyms || {};
}
async function refreshChats() {
  const chats = await api("/api/chats");
  $("chats").replaceChildren();
  if (!chats.length) $("chats").append(node("p", "empty-small", "Переписки ещё не загружены"));
  for (const chat of chats) {
    const label = node("label", "chat-row");
    const input = node("input"); input.type = "checkbox"; input.value = chat.id; input.checked = true; input.name = "chat";
    const text = node("span", "", chat.name);
    text.append(node("small", "", `${chat.messages} сообщений · ${chat.attachments || 0} вложений`));
    label.append(input, text); $("chats").append(label);
  }
  return chats;
}
async function refreshRuns() {
  const runs = await api("/api/runs");
  $("runs").replaceChildren();
  if (!runs.length) $("runs").append(node("p", "muted", "Пока нет отчётов"));
  for (const run of runs) {
    const button = node("button", "", run.request.topic.name);
    const states = {complete: "Готово", interrupted: "Прерван", with_errors: "Есть ошибки", running: "Обрабатывается"};
    button.append(node("small", "", `${states[run.status] || run.status} · ${run.request.config.backend}`));
    button.addEventListener("click", () => openReport(run.id).catch(error => notice(error.message, true)));
    $("runs").append(button);
  }
}
function displayImport(result) {
  $("import-info").textContent = JSON.stringify(result.imports, null, 2);
  const errors = result.imports.reduce((sum, r) => sum + r.errors.length, 0);
  const inserted = result.imports.reduce((sum, r) => sum + r.inserted, 0);
  const unchanged = result.imports.reduce((sum, r) => sum + r.unchanged, 0);
  notice(`Импорт завершён: ${inserted} новых, ${unchanged} без изменений, ошибок: ${errors}.` + (errors ? " Подробности — в результате импорта." : ""), errors > 0);
}
$("demo").addEventListener("click", async () => {
  $("demo").disabled = true;
  try {
    const result = await api("/api/demo", {});
    setTopic(result.topic); displayImport(result); await refreshChats();
    notice("Синтетический пример загружен. Тема и слова поиска заполнены — можно начать анализ.");
  } catch (error) { notice(error.message, true); }
  finally { $("demo").disabled = false; }
});
$("exports").addEventListener("change", async event => {
  try {
    const chosen = [...event.target.files];
    if (!chosen.length) return;
    if (chosen.length > 20 || chosen.reduce((sum, file) => sum + file.size, 0) > 24 * 1024 * 1024) throw new Error("Выберите до 20 файлов, суммарно не больше 24 MB. Для больших экспортов используйте CLI.");
    const exports = [];
    for (const file of chosen) exports.push({name: file.name, data: JSON.parse((await file.text()).replace(/^\uFEFF/, ""))});
    const result = await api("/api/import", {exports}); displayImport(result); await refreshChats();
  } catch (error) { notice(error.message, true); }
  finally { event.target.value = ""; }
});
$("backend").addEventListener("change", () => {
  const model = $("backend").value === "ollama";
  $("model-fields").hidden = !model;
  $("backend-note").textContent = model ? "Модель выделяет факты со слов автора, мнения, вопросы и решения с цитатами. Интерпретацию нужно проверять." : "Дословные выдержки по словам темы и связанным ответам. Доступно сразу.";
});
$("check-models").addEventListener("click", async () => {
  $("check-models").disabled = true;
  try {
    const result = await api("/api/models?base_url=" + encodeURIComponent($("base-url").value));
    const models = result.models || [];
    $("model-list").replaceChildren(...models.map(model => {const option = node("option"); option.value = model.name; return option;}));
    $("model-status").textContent = models.length ? "Доступны: " + models.map(model => model.name).join(", ") : "Ollama доступна, модели ещё не загружены.";
  } catch (error) { $("model-status").textContent = error.message; }
  finally { $("check-models").disabled = false; }
});
$("load-topic").addEventListener("click", () => $("topic-file").click());
$("topic-file").addEventListener("change", async event => {
  try {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 1024 * 1024) throw new Error("Файл темы слишком большой");
    const topic = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
    if (typeof topic.name !== "string" || !topic.name.trim()) throw new Error("В настройках темы нужно поле name");
    setTopic(topic); notice("Настройки темы загружены.");
  } catch (error) { notice(error.message, true); }
  finally { event.target.value = ""; }
});
$("save-topic").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(topicValue(), null, 2)], {type: "application/json"});
  const link = node("a"); link.href = URL.createObjectURL(blob); link.download = "topic.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});
$("analysis-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const chats = [...document.querySelectorAll('input[name="chat"]:checked')].map(input => input.value);
    if (!chats.length) throw new Error("Сначала загрузите и выберите переписку.");
    if (!$("topic").value.trim()) throw new Error("Введите тему анализа.");
    const payload = {topic: topicValue(), chats, since: $("since").value, until: $("until").value,
      config: {backend: $("backend").value, mode: $("mode").value, model: $("model").value.trim(), base_url: $("base-url").value.trim()}};
    await api("/api/analyze", payload); $("notice").hidden = true; await pollStatus();
  } catch (error) { notice(error.message, true); }
});
$("cancel").addEventListener("click", async () => {
  try { await api("/api/cancel", {}); $("progress-title").textContent = "Сохраняем прогресс и останавливаемся…"; }
  catch (error) { notice(error.message, true); }
});
async function pollStatus() {
  if (polling) return;
  polling = true; $("analyze").disabled = true; $("progress-panel").hidden = false;
  try {
    let state;
    do {
      state = await api("/api/status");
      $("progress").value = state.total ? state.current / state.total * 100 : 0;
      $("progress-text").textContent = state.total ? `Фрагменты: ${state.current}/${state.total} · из кэша: ${state.cached || 0} · ошибок: ${state.errors || 0}` : "Подготовка данных и модели…";
      if (state.status === "running") await new Promise(resolve => setTimeout(resolve, 700));
    } while (state.status === "running");
    if (state.status === "error") throw new Error(state.error || "Ошибка анализа");
    if (state.run_id) await openReport(state.run_id);
    if (state.status === "interrupted") notice("Анализ остановлен, прогресс сохранён. Повторите запуск с теми же настройками, чтобы продолжить.");
    else if (state.status === "with_errors") notice("Отчёт готов частично: есть ошибки обработки. Повторный запуск попробует обработать эти фрагменты снова.", true);
    await refreshRuns();
  } finally {
    polling = false; $("analyze").disabled = false; $("progress-panel").hidden = true;
    $("progress-title").textContent = "Анализируем переписку…";
  }
}
async function openReport(runId) {
  currentReport = await api("/api/report?run=" + encodeURIComponent(runId));
  const report = currentReport, s = report.statistics;
  $("empty-results").hidden = true; $("results").hidden = false;
  $("report-title").textContent = report.topic.name;
  $("downloads").replaceChildren();
  for (const format of ["html", "md", "json", "csv"]) {
    const link = node("a", "", format.toUpperCase());
    link.href = `/api/report?run=${encodeURIComponent(runId)}&format=${format}`;
    if (format === "json") link.download = "report.json";
    $("downloads").append(link);
  }
  $("stats").replaceChildren();
  for (const [value, label] of [[s.matched_messages, "сообщений по теме"], [s.findings, "находок"], [s.identified_participants, "известных авторов"], [s.coverage_percent + "%", "охват обработки"]]) {
    const card = node("div", "stat"); card.append(node("strong", "", value), node("span", "", label)); $("stats").append(card);
  }
  $("report-mode").textContent = `${report.config.mode === "overview" ? "Полный обзор" : "Быстрый поиск"} · ${report.analyzer.model || "Выдержки без модели"} · ${s.processed_fragments}/${s.fragments_total} фрагментов · из кэша ${s.cached_fragments} · ошибок ${report.errors.length}`;
  $("limitations").replaceChildren(...report.limitations.map(text => node("p", "", text)));
  for (const error of report.errors) $("limitations").append(node("p", "", error.error));
  $("type-filter").replaceChildren();
  const all = node("option", "", "Все типы"); all.value = ""; $("type-filter").append(all);
  for (const type of [...new Set(report.findings.map(f => f.type))]) {
    const option = node("option", "", typeNames[type] || type); option.value = type; $("type-filter").append(option);
  }
  renderFindings();
}
function renderFindings() {
  if (!currentReport) return;
  const chosen = currentReport.findings.filter(f => !$("type-filter").value || f.type === $("type-filter").value);
  $("finding-count").textContent = `Показано ${chosen.length} из ${currentReport.findings.length}`;
  $("findings").replaceChildren();
  if (!chosen.length) $("findings").append(node("section", "panel", "Подходящих находок нет. Проверьте тему, режим и ошибки обработки."));
  for (const finding of chosen) {
    const card = node("article", "finding");
    card.append(node("div", "finding-meta", `${typeNames[finding.type] || finding.type} / ${finding.subtopic}`));
    if (finding.type !== "excerpt") card.append(node("h3", "", finding.claim));
    for (const evidence of finding.evidence) {
      card.append(node("blockquote", "", evidence.quote));
      const link = node("button", "source-link", `${evidence.author} · ${new Date(evidence.date).toLocaleString("ru-RU", {timeZone: "Asia/Tomsk"})} · Открыть контекст ↗`);
      link.addEventListener("click", () => openSource(evidence)); card.append(link);
    }
    const review = node("div", "review"); review.append(node("span", "", "Находка полезна?"));
    for (const [verdict, label] of [["correct", "Да"], ["incorrect", "Есть ошибка"]]) {
      const button = node("button", "", label);
      button.addEventListener("click", async () => {
        try { await api("/api/feedback", {run_id: currentReport.run_id, finding_id: finding.id, verdict});
          review.replaceChildren(node("span", "saved", "Оценка сохранена")); }
        catch (error) { notice(error.message, true); }
      }); review.append(button);
    }
    card.append(review); $("findings").append(card);
  }
}
$("type-filter").addEventListener("change", renderFindings);
function openSource(evidence) {
  $("source-content").replaceChildren(node("p", "muted", "Сообщение и доступные соседи из выбранного периода. Даты показаны по времени Томска."));
  const messages = currentReport.sources.filter(m => m.chat_id === evidence.chat_id);
  const index = messages.findIndex(m => m.key === evidence.key);
  for (const message of messages.slice(Math.max(0, index - 2), index + 3)) {
    const card = node("section", "source-message" + (message.key === evidence.key ? " active" : ""));
    card.append(node("div", "meta", `${message.author} · ${message.key} · ${new Date(message.date).toLocaleString("ru-RU", {timeZone: "Asia/Tomsk"})}`));
    if (message.reply_to) card.append(node("div", "meta", `В ответ на сообщение ${message.reply_to}`));
    card.append(node("p", "", message.text || (message.attachment ? "Вложение без распознанного текста" : "Пустое сообщение")));
    $("source-content").append(card);
  }
  $("source-dialog").showModal();
}
$("close-dialog").addEventListener("click", () => $("source-dialog").close());
$("missed").addEventListener("click", async () => {
  if (!currentReport) return;
  const comment = prompt("Какая находка пропущена? Укажите ID сообщения и описание.");
  if (!comment) return;
  try { await api("/api/feedback", {run_id: currentReport.run_id, verdict: "missed", comment}); notice("Сообщение о пропуске сохранено."); }
  catch (error) { notice(error.message, true); }
});
async function init() {
  await refreshChats(); await refreshRuns();
  const status = await api("/api/status");
  if (status.status === "running") await pollStatus();
}
init().catch(error => notice(error.message, true));
