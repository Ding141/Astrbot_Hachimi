import { appState } from "./state.js";
import { $, api, escapeHtml, toast, localDate, localReminderInput, localToday, openDrawer, closeDrawer } from "./core.js";

function updateStats(items, todayItems, overdueItems) {
  $("#stat-open").textContent = items.filter((item) => item.status === "open").length;
  $("#stat-today").textContent = todayItems.length;
  $("#stat-overdue").textContent = overdueItems.length;
}

async function loadTodos() {
  const q = encodeURIComponent($("#todo-search").value.trim());
  const status = encodeURIComponent($("#todo-status").value);
  const due = encodeURIComponent($("#todo-due").value);
  const [result, today, overdue] = await Promise.all([
    api(`/api/v1/todos?q=${q}&status=${status}&due=${due}`),
    api("/api/v1/todos?status=open&due=today"),
    api("/api/v1/todos?status=open&due=overdue"),
  ]);
  appState.todos = result.items;
  if (!appState.todoAnchor) appState.todoAnchor = localToday();
  if (!$("#todo-calendar-date").value) $("#todo-calendar-date").value = appState.todoAnchor;
  const inCalendar = appState.todoView && appState.todoView !== "list";
  $("#todo-rows").closest(".table-scroll").hidden = inCalendar;
  $("#todo-empty").hidden = inCalendar || result.items.length > 0;
  $("#todo-calendar").hidden = !inCalendar;
  $("#todo-undated").hidden = !inCalendar;
  if (!inCalendar) clearTodoSelection();
  document.querySelectorAll("[data-todo-view]").forEach((button) => button.classList.toggle("active", button.dataset.todoView === (appState.todoView || "list")));
  const rows = $("#todo-rows");
  rows.innerHTML = result.items.map((item) => {
    const reminderCount = item.reminders.filter((reminder) => reminder.status !== "sent").length;
    const categoryClass = categoryCss(item.category);
    const quadrant = quadrantLabel(item);
    return `<tr class="${item.status === "completed" ? "completed-row" : ""}">
      <td><input class="todo-select" type="checkbox" value="${item.id}" aria-label="选择任务 ${escapeHtml(item.title)}"></td>
      <td><div class="task-title">${escapeHtml(item.title)}</div>${item.recurrence ? `<div class="subtle">${recurrenceLabel(item.recurrence)} · ${escapeHtml(item.recurrence.start_date)} 至 ${escapeHtml(item.recurrence.end_date || "未设结束")}</div>` : ""}${item.notes ? `<div class="subtle">${escapeHtml(item.notes)}</div>` : ""}</td>
      <td>${escapeHtml(taskTimeLabel(item))}</td>
      <td>${item.category ? `<span class="tag ${categoryClass}">${escapeHtml(item.category)}</span>` : "—"}</td>
      <td><span class="quad-pill ${quadrant.css}">${quadrant.text}</span></td>
      <td>${reminderCount ? `<span class="reminder-count">◷ ${reminderCount}</span>` : "—"}</td>
      <td class="actions">${item.status === "open" ? `<button class="mini complete-action" data-id="${item.id}" title="完成">✓</button>` : ""}<button class="mini edit-action" data-id="${item.id}" title="编辑">✎</button><button class="mini danger delete-action" data-id="${item.id}" title="删除">×</button></td>
    </tr>`;
  }).join("");
  updateStats(result.items, today.items, overdue.items);
  rows.querySelectorAll(".complete-action").forEach((button) => button.addEventListener("click", () => completeTodo(button.dataset.id)));
  rows.querySelectorAll(".edit-action").forEach((button) => button.addEventListener("click", () => editTodo(Number(button.dataset.id), result.items)));
  rows.querySelectorAll(".delete-action").forEach((button) => button.addEventListener("click", () => removeTodo(button.dataset.id)));
  rows.querySelectorAll(".todo-select").forEach((checkbox) => checkbox.addEventListener("change", updateBulkDeleteState));
  $("#todo-select-visible").checked = false;
  updateBulkDeleteState();
  if (inCalendar) await loadTodoCalendar();
}

function categoryCss(category) {
  return ({ 学习: "cat-study", 锻炼: "cat-exercise", 生活: "cat-life", 项目: "cat-project", 工作: "cat-work" })[category] || "cat-other";
}

function quadrantLabel(item) {
  if (item.important && item.urgent) return { text: "重要且紧急", css: "quad-urgent-important" };
  if (item.important) return { text: "重要不紧急", css: "quad-important" };
  if (item.urgent) return { text: "紧急不重要", css: "quad-urgent" };
  return { text: "不急不重要", css: "quad-later" };
}

function recurrenceLabel(recurrence) {
  if (recurrence.frequency === "daily") return "每日重复";
  if (recurrence.frequency === "monthly") return `每月${recurrence.month_day}日重复`;
  return `每周${(recurrence.weekdays || []).map((day) => `周${"一二三四五六日"[day - 1]}`).join("、")}重复`;
}

function taskTimeLabel(item) {
  const start = localDate(item.start_date, item.start_time);
  const end = localDate(item.end_date, item.end_time);
  if (start === "无截止日期" && end === "无截止日期") return "未安排时间";
  if (start === "无截止日期") return `至 ${end}`;
  if (end === "无截止日期") return `从 ${start}`;
  return `${start} – ${end}`;
}

function localIso(day) { return day.toISOString().slice(0, 10); }
function dateFromIso(value) { return new Date(`${value}T12:00:00Z`); }

function todoCalendarRange() {
  const anchorText = $("#todo-calendar-date").value || localToday();
  const anchor = dateFromIso(anchorText);
  if (appState.todoView === "day") return { first: anchorText, last: anchorText, anchor };
  if (appState.todoView === "week") {
    const firstDate = new Date(anchor);
    firstDate.setUTCDate(firstDate.getUTCDate() - ((firstDate.getUTCDay() + 6) % 7));
    const lastDate = new Date(firstDate);
    lastDate.setUTCDate(lastDate.getUTCDate() + 6);
    return { first: localIso(firstDate), last: localIso(lastDate), anchor };
  }
  const firstOfMonth = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), 1, 12));
  firstOfMonth.setUTCDate(firstOfMonth.getUTCDate() - ((firstOfMonth.getUTCDay() + 6) % 7));
  const last = new Date(firstOfMonth);
  last.setUTCDate(last.getUTCDate() + 41);
  return { first: localIso(firstOfMonth), last: localIso(last), anchor };
}

function filterCalendarItems(items) {
  const q = $("#todo-search").value.trim().toLocaleLowerCase();
  const status = $("#todo-status").value;
  const due = $("#todo-due").value;
  const today = localToday();
  const upcoming = new Date(dateFromIso(today)); upcoming.setUTCDate(upcoming.getUTCDate() + 7);
  const upcomingIso = localIso(upcoming);
  return items.filter((item) => {
    if (status !== "all" && item.status !== status) return false;
    if (q && !`${item.title} ${item.notes} ${item.category}`.toLocaleLowerCase().includes(q)) return false;
    const taskStart = item.start_date || item.end_date;
    const taskEnd = item.end_date || item.start_date;
    if (due === "today" && !(taskStart && taskEnd && taskStart <= today && taskEnd >= today)) return false;
    if (due === "upcoming" && !(taskEnd > today && taskStart <= upcomingIso)) return false;
    if (due === "overdue") {
      const currentTime = new Date().toLocaleTimeString("en-GB", {
        timeZone: "Asia/Shanghai",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      const deadlineDate = item.end_date || item.start_date;
      const deadlineTime = item.end_date ? item.end_time : item.start_time;
      const overdue = item.status === "open"
        && deadlineDate
        && (
          deadlineDate < today
          || (deadlineDate === today && deadlineTime && deadlineTime < currentTime)
        );
      if (!overdue) return false;
    }
    return true;
  });
}

function rangeForTodo(item) {
  return { start: item.start_date || item.end_date, end: item.end_date || item.start_date };
}

function calendarRangeLabel(item, day) {
  const { start, end } = rangeForTodo(item);
  if (!start || !end) return "未安排时间";
  if (start === end) {
    if (item.start_time && item.end_time) return `${item.start_time}–${item.end_time}`;
    return item.start_time || item.end_time || "当天";
  }
  if (day === start) return `开始${item.start_time ? ` · ${item.start_time}` : ""}`;
  if (day === end) return `结束${item.end_time ? ` · ${item.end_time}` : ""}`;
  return "持续中";
}

function renderCalendarCard(item, day) {
  const { start, end } = rangeForTodo(item);
  const rangeState = start === end ? "range-single" : day === start ? "range-start" : day === end ? "range-end" : "range-middle";
  const selected = Number(appState.selectedTodo) === Number(item.id);
  const ariaLabel = `${item.title}，${taskTimeLabel(item)}`;
  return `<article class="todo-calendar-card ${item.status === "completed" ? "completed" : ""} ${categoryCss(item.category)} ${rangeState} ${selected ? "is-selected" : ""}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="查看待办 ${escapeHtml(ariaLabel)}" data-todo-id="${item.id}" data-todo-date="${day || ""}">
    <strong class="calendar-task-title">${escapeHtml(item.title)}</strong>
    <span class="calendar-range-label">${escapeHtml(calendarRangeLabel(item, day))}</span>
  </article>`;
}

function selectTodo(todoId) {
  appState.selectedTodo = todoId;
  document.querySelectorAll(".todo-calendar-card").forEach((card) => {
    const selected = Number(card.dataset.todoId) === Number(todoId);
    card.classList.toggle("is-selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  renderSelectedTodoDetails();
}

function clearTodoSelection() {
  appState.selectedTodo = null;
  const panel = $("#todo-details");
  const workspace = $("#todo-workspace");
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
  workspace?.classList.remove("has-selected-todo");
  document.querySelectorAll(".todo-calendar-card.is-selected").forEach((card) => {
    card.classList.remove("is-selected");
    card.setAttribute("aria-pressed", "false");
  });
}

function renderSelectedTodoDetails() {
  const panel = $("#todo-details");
  const workspace = $("#todo-workspace");
  const item = appState.todos.find((entry) => Number(entry.id) === Number(appState.selectedTodo));
  if (!item) { clearTodoSelection(); return; }
  const start = item.start_date || item.end_date;
  const end = item.end_date || item.start_date;
  const reminders = (item.reminders || []).filter((reminder) => reminder.status !== "cancelled");
  const recurrence = item.recurrence ? `${recurrenceLabel(item.recurrence)} · ${item.recurrence.start_date} 至 ${item.recurrence.end_date || "未设结束"}` : "不重复";
  panel.hidden = false;
  workspace.classList.add("has-selected-todo");
  panel.innerHTML = `<header class="selected-todo-heading"><div><span class="eyebrow">待办详情</span><h3>${escapeHtml(item.title)}</h3></div><button class="selected-todo-close" type="button" aria-label="关闭待办详情">×</button></header>
    <dl class="selected-todo-facts"><div><dt>时间范围</dt><dd>${escapeHtml(start && end ? `${localDate(start, item.start_time)} – ${localDate(end, item.end_time)}` : taskTimeLabel(item))}</dd></div><div><dt>状态</dt><dd>${item.status === "completed" ? "已完成" : "未完成"}</dd></div><div><dt>重复</dt><dd>${escapeHtml(recurrence)}</dd></div><div><dt>分类</dt><dd>${escapeHtml(item.category || "未分类")}</dd></div><div><dt>优先级</dt><dd>${escapeHtml(quadrantLabel(item).text)}</dd></div><div><dt>提醒</dt><dd>${reminders.length ? reminders.map((reminder) => escapeHtml(localReminderInput(reminder.remind_at))).join("<br>") : "未设置提醒"}</dd></div>${item.notes ? `<div class="selected-todo-notes"><dt>备注</dt><dd>${escapeHtml(item.notes)}</dd></div>` : ""}</dl>
    <div class="selected-todo-actions"><button class="secondary selected-todo-edit" type="button">编辑待办</button>${item.status === "open" ? `<button class="secondary selected-todo-complete" type="button">标记完成</button>` : ""}<button class="secondary danger-button selected-todo-delete" type="button">删除待办</button></div>`;
  panel.querySelector(".selected-todo-close").addEventListener("click", clearTodoSelection);
  panel.querySelector(".selected-todo-edit").addEventListener("click", () => editTodo(item.id, appState.todos));
  panel.querySelector(".selected-todo-complete")?.addEventListener("click", () => completeTodo(item.id));
  panel.querySelector(".selected-todo-delete").addEventListener("click", () => removeTodo(item.id));
}

async function loadTodoCalendar() {
  const { first, last, anchor } = todoCalendarRange();
  appState.todoAnchor = $("#todo-calendar-date").value || localToday();
  const result = await api(`/api/v1/todos/calendar?from_date=${first}&to_date=${last}`);
  const items = filterCalendarItems(result.items);
  appState.todos = [...result.undated, ...result.items];
  const groups = new Map();
  for (const item of items) {
    const { start, end } = rangeForTodo(item);
    if (!start || !end) continue;
    const firstDay = start < first ? first : start;
    const lastDay = end > last ? last : end;
    if (lastDay < firstDay) continue;
    const cursor = dateFromIso(firstDay);
    const stop = dateFromIso(lastDay);
    while (cursor <= stop) {
      const groupDate = localIso(cursor);
      const group = groups.get(groupDate) || [];
      group.push(item);
      groups.set(groupDate, group);
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
  }
  const grid = $("#todo-calendar");
  grid.className = `todo-calendar ${appState.todoView}-view`;
  const cells = [];
  const firstDate = dateFromIso(first);
  for (let offset = 0; offset <= (dateFromIso(last) - firstDate) / 86400000; offset += 1) {
    const day = new Date(firstDate); day.setUTCDate(day.getUTCDate() + offset);
    const iso = localIso(day);
    const outside = appState.todoView === "month" && day.getMonth() !== anchor.getMonth();
    const entries = groups.get(iso) || [];
    const displayDate = day.toLocaleDateString("zh-CN", { weekday: "short", month: "numeric", day: "numeric", timeZone: "Asia/Shanghai" });
    cells.push(`<section class="todo-calendar-day ${iso === localToday() ? "is-today" : ""} ${outside ? "outside-month" : ""}"><div class="todo-calendar-date"><button type="button" data-view-date="${iso}">${displayDate}</button><span>${entries.length ? entries.length + "项" : ""}</span></div><div class="todo-calendar-items">${entries.map((item) => renderCalendarCard(item, iso)).join("") || `<span class="subtle">${appState.todoView === "day" ? "今天还没有任务" : ""}</span>`}</div></section>`);
  }
  grid.innerHTML = cells.join("");
  const undated = filterCalendarItems(result.undated);
  appState.todos = [...items, ...undated];
  $("#todo-undated").innerHTML = undated.length ? `<strong>未设置日期 · ${undated.length} 项</strong><div class="todo-calendar-items">${undated.slice(0, 20).map((item) => renderCalendarCard(item, "")).join("")}</div>` : "";
  if (appState.selectedTodo && !appState.todos.some((item) => Number(item.id) === Number(appState.selectedTodo))) clearTodoSelection();
  document.querySelectorAll(".todo-calendar-card").forEach((card) => {
    const select = () => selectTodo(Number(card.dataset.todoId));
    card.addEventListener("click", select);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
    });
  });
  renderSelectedTodoDetails();
  grid.querySelectorAll("[data-view-date]").forEach((button) => button.addEventListener("click", () => { appState.todoView = "day"; $("#todo-calendar-date").value = button.dataset.viewDate; loadTodos(); }));
}

function setTodoView(view) {
  appState.todoView = view;
  if (!appState.todoAnchor) appState.todoAnchor = localToday();
  $("#todo-calendar-date").value = appState.todoAnchor;
  loadTodos();
}

function shiftTodoCalendar(direction) {
  const date = dateFromIso($("#todo-calendar-date").value || localToday());
  if (appState.todoView === "day") date.setUTCDate(date.getUTCDate() + direction);
  else if (appState.todoView === "week") date.setUTCDate(date.getUTCDate() + direction * 7);
  else { date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + direction); }
  appState.todoAnchor = localIso(date);
  $("#todo-calendar-date").value = appState.todoAnchor;
  loadTodos();
}

function updateBulkDeleteState() {
  const selected = document.querySelectorAll(".todo-select:checked");
  $("#bulk-delete").disabled = selected.length === 0;
  $("#bulk-delete").textContent = selected.length ? `删除所选 (${selected.length})` : "删除所选";
  const all = [...document.querySelectorAll(".todo-select")];
  $("#todo-select-visible").checked = all.length > 0 && all.every((item) => item.checked);
}

async function bulkDeleteTodos() {
  const ids = [...document.querySelectorAll(".todo-select:checked")].map((item) => Number(item.value));
  if (!ids.length) return;
  if (!window.confirm(`确认删除所选的 ${ids.length} 项任务？尚未发送的关联提醒也会取消。`)) return;
  try {
    const result = await api("/api/v1/todos/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ ids, confirm: true }),
    });
    toast(`已删除 ${result.deleted_count} 项任务`);
    $("#todo-select-visible").checked = false;
    await loadTodos();
  } catch (error) { toast(error.message, "error"); }
}

function clearTodoForm() {
  $("#todo-form").reset();
  $("#todo-id").value = "";
  appState.editingTodo = null;
  $("#todo-repeat-frequency").disabled = false;
  $("#todo-category").value = "学习";
  $("#todo-quadrant").value = "1-auto";
  $("#todo-start-at").value = "";
  $("#todo-end-at").value = "";
  $("#todo-repeat-start-time").value = "";
  $("#todo-repeat-end-time").value = "";
  $("#todo-single-time-fields").hidden = false;
  $("#todo-repeat-month-day").value = "";
  $("#todo-repeat-frequency").value = "none";
  $("#todo-repeat-options").hidden = true;
  $("#todo-repeat-month-day-wrap").hidden = true;
  $("#todo-cancel-edit").hidden = true;
  closeDrawer();
}

function editTodo(id, items) {
  const item = items.find((entry) => entry.id === id);
  if (!item) return;
  appState.editingTodo = item;
  $("#todo-id").value = item.id;
  $("#todo-title").value = item.title;
  $("#todo-notes").value = item.notes;
  $("#todo-category").value = item.category;
  if (![...$("#todo-category").options].some((option) => option.value === item.category)) {
    const option = document.createElement("option"); option.value = item.category; option.textContent = item.category; $("#todo-category").append(option);
  }
  $("#todo-quadrant").value = item.urgent_override == null
    ? `${item.important ? 1 : 0}-auto`
    : `${item.important ? 1 : 0}-${item.urgent_override ? 1 : 0}`;
  $("#todo-start-at").value = item.start_date ? `${item.start_date}T${item.start_time || "00:00"}` : "";
  $("#todo-end-at").value = item.end_date ? `${item.end_date}T${item.end_time || "00:00"}` : "";
  $("#todo-reminders").value = item.reminders
    .filter((reminder) => ["pending", "failed", "uncertain"].includes(reminder.status))
    .map((reminder) => localReminderInput(reminder.remind_at)).join("\n");
  $("#todo-repeat-frequency").value = item.recurrence?.frequency || "none";
  $("#todo-repeat-frequency").disabled = !item.recurrence;
  $("#todo-repeat-options").hidden = !item.recurrence;
  $("#todo-single-time-fields").hidden = Boolean(item.recurrence);
  $("#todo-repeat-start").value = item.recurrence?.start_date || "";
  $("#todo-repeat-end").value = item.recurrence?.end_date || "";
  $("#todo-repeat-start-time").value = item.recurrence?.start_time || "";
  $("#todo-repeat-end-time").value = item.recurrence?.end_time || "";
  $("#todo-repeat-month-day").value = item.recurrence?.month_day || "";
  $("#todo-repeat-month-day-wrap").hidden = item.recurrence?.frequency !== "monthly";
  $("#todo-repeat-weekdays").hidden = item.recurrence?.frequency !== "weekly";
  $("#todo-repeat-weekdays").querySelectorAll("input").forEach((input) => {
    input.checked = (item.recurrence?.weekdays || []).includes(Number(input.value));
  });
  $("#todo-repeat-reminder-enabled").checked = item.recurrence?.reminder_enabled ?? true;
  $("#todo-repeat-reminder-times").value = (item.recurrence?.reminder_times || []).join(", ");
  $("#todo-cancel-edit").hidden = false;
  openDrawer("todo-editor", "编辑待办");
}

async function completeTodo(id) {
  try {
    await api(`/api/v1/todos/${id}/complete`, { method: "POST" });
    toast("任务已完成");
    await loadTodos();
  } catch (error) { toast(error.message, "error"); }
}

async function removeTodo(id) {
  if (!window.confirm("删除这项任务？任务会以可恢复方式标记删除，并取消尚未发送的提醒。")) return;
  try {
    const item = appState.todos?.find((entry) => String(entry.id) === String(id));
    let path = `/api/v1/todos/${id}`;
    if (item?.recurrence) {
      const scope = window.prompt("这是重复任务，请输入 occurrence 删除本期，或 series 取消未来整组：", "occurrence");
      if (!scope) return;
      if (!["occurrence", "series"].includes(scope.trim())) { toast("请输入 occurrence 或 series。", "error"); return; }
      path += `?scope=${encodeURIComponent(scope.trim())}`;
    }
    await api(path, { method: "DELETE" });
    toast("任务已删除");
    await loadTodos();
  } catch (error) { toast(error.message, "error"); }
}

async function submitTodo(event) {
  event.preventDefault();
  const id = $("#todo-id").value;
  const item = appState.editingTodo;
  const repeat = $("#todo-repeat-frequency").value;
  const [importantBit, urgentBit] = $("#todo-quadrant").value.split("-");
  const important = Boolean(importantBit);
  const urgent = urgentBit === "auto" ? null : Boolean(Number(urgentBit));
  const payload = {
    title: $("#todo-title").value.trim(), notes: $("#todo-notes").value,
    category: $("#todo-category").value.trim(), priority: item?.priority || 3,
    important, urgent,
  };
  const startAt = $("#todo-start-at").value;
  const endAt = $("#todo-end-at").value;
  if (repeat === "none") {
    const [startDate, startTime] = startAt ? startAt.split("T") : [null, null];
    const [endDate, endTime] = endAt ? endAt.split("T") : [null, null];
    Object.assign(payload, { start_date: startDate, start_time: startTime, end_date: endDate, end_time: endTime });
  }
  const reminders = $("#todo-reminders").value.split(/[\n,，;；]+/).map((value) => value.trim()).filter(Boolean);
  if (reminders.length > 10) { toast("每项任务最多设置10个提醒。", "error"); return; }
  if (!id && reminders.some((value) => !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value))) { toast("提醒时间请填写完整日期和时刻，例如 2026-09-28T08:00。", "error"); return; }
  if (id && !item?.recurrence) payload.reminders = reminders.map((remind_at) => ({ remind_at }));
  if (id && item?.recurrence) {
    const scope = window.prompt("这是重复任务：输入 occurrence 只修改本期，或 series 修改整组后续任务。", "occurrence");
    if (!scope) return;
    if (!["occurrence", "series"].includes(scope.trim())) { toast("请输入 occurrence 或 series。", "error"); return; }
    if (scope.trim() === "series") {
      const times = $("#todo-repeat-reminder-times").value.split(/[,，;；\s]+/).filter(Boolean);
      if (times.some((value) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(value))) { toast("重复提醒时刻请使用 HH:MM 格式。", "error"); return; }
      const weekdays = [...$("#todo-repeat-weekdays").querySelectorAll("input:checked")].map((node) => Number(node.value));
      const monthDay = Number($("#todo-repeat-month-day").value || item.recurrence.month_day || 0);
      if (repeat === "weekly" && !weekdays.length) { toast("请选择每周重复的星期。", "error"); return; }
      if (repeat === "monthly" && (!monthDay || monthDay > 31)) { toast("请填写每月1到31号。", "error"); return; }
      const start = $("#todo-repeat-start").value || item.recurrence.start_date;
      const end = $("#todo-repeat-end").value;
      const rulesChanged = repeat !== item.recurrence.frequency || start !== item.recurrence.start_date || end !== (item.recurrence.end_date || "") ||
        (repeat === "monthly" && monthDay !== Number(item.recurrence.month_day)) ||
        (repeat === "weekly" && JSON.stringify(weekdays) !== JSON.stringify(item.recurrence.weekdays || []));
      if (rulesChanged && !end) { toast("修改重复规则时需要设置停止日期。", "error"); return; }
      const seriesPayload = {
        title: payload.title, notes: payload.notes, category: payload.category, priority: payload.priority,
        important, urgent,
        start_time: $("#todo-repeat-start-time").value || null,
        end_time: $("#todo-repeat-end-time").value || null,
        reminder_enabled: $("#todo-repeat-reminder-enabled").checked && times.length > 0,
        reminder_times: times,
      };
      if (rulesChanged) {
        Object.assign(seriesPayload, { frequency: repeat, start_date: start, end_date: end });
        if (repeat === "weekly") seriesPayload.weekdays = weekdays;
        if (repeat === "monthly") seriesPayload.month_day = monthDay;
      }
      try {
        const result = await api(`/api/v1/todo-series/${item.recurrence.series_id}`, { method: "PATCH", body: JSON.stringify(seriesPayload) });
        toast(`已更新重复任务系列：${result.title}`); clearTodoForm(); await loadTodos();
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    payload.start_time = $("#todo-repeat-start-time").value || null;
    payload.end_time = $("#todo-repeat-end-time").value || null;
    payload.reminders = reminders.map((remind_at) => ({ remind_at }));
    try { await api(`/api/v1/todos/${id}?scope=occurrence`, { method: "PATCH", body: JSON.stringify(payload) }); toast("本期任务已更新"); clearTodoForm(); await loadTodos(); }
    catch (error) { toast(error.message, "error"); }
    return;
  }
  if (!id && repeat !== "none") {
    const end = $("#todo-repeat-end").value;
    if (!end) { toast("新建重复任务需要设置停止日期。", "error"); return; }
    const weekdays = [...$("#todo-repeat-weekdays").querySelectorAll("input:checked")].map((node) => Number(node.value));
    const monthDay = Number($("#todo-repeat-month-day").value || 0);
    if (repeat === "weekly" && !weekdays.length) { toast("请选择每周重复的星期。", "error"); return; }
    if (repeat === "monthly" && (!monthDay || monthDay > 31)) { toast("请填写每月1到31号。", "error"); return; }
    const times = $("#todo-repeat-reminder-times").value.split(/[,，;；\s]+/).filter(Boolean);
    if (times.some((value) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(value))) { toast("重复提醒时刻请使用 HH:MM 格式。", "error"); return; }
      const repeatPayload = {
        title: payload.title, notes: payload.notes, category: payload.category, priority: payload.priority,
        important, urgent, frequency: repeat, weekdays: repeat === "weekly" ? weekdays : [],
        start_date: $("#todo-repeat-start").value || localToday(), end_date: end,
        start_time: $("#todo-repeat-start-time").value || null,
        end_time: $("#todo-repeat-end-time").value || null,
        reminder_enabled: $("#todo-repeat-reminder-enabled").checked && times.length > 0,
      reminder_times: times,
    };
    if (repeat === "monthly") repeatPayload.month_day = monthDay;
    try { const result = await api("/api/v1/todo-series", { method: "POST", body: JSON.stringify(repeatPayload) }); toast(`已建立重复任务：${result.title}`); clearTodoForm(); await loadTodos(); }
    catch (error) { toast(error.message, "error"); }
    return;
  }
  if (!id && reminders.length) payload.reminders = reminders.map((remind_at) => ({ remind_at }));
  try {
    await api(id ? `/api/v1/todos/${id}` : "/api/v1/todos", { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
    toast(id ? "任务已更新" : "任务已添加"); clearTodoForm(); await loadTodos();
  } catch (error) { toast(error.message, "error"); }
}

function openNewTodo() { clearTodoForm(); openDrawer("todo-editor", "新建待办"); }

export { loadTodos, updateBulkDeleteState, bulkDeleteTodos, clearTodoForm, editTodo, completeTodo, removeTodo, submitTodo, openNewTodo, setTodoView, shiftTodoCalendar };
