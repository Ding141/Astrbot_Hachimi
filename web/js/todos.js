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
    const taskDate = item.end_date || item.start_date;
    if (due === "today" && taskDate !== today) return false;
    if (due === "upcoming" && !(taskDate > today && taskDate <= upcomingIso)) return false;
    if (due === "overdue") {
      const currentTime = new Date().toLocaleTimeString("en-GB", {
        timeZone: "Asia/Shanghai",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      const deadlineTime = item.end_date ? item.end_time : item.start_time;
      const overdue = item.status === "open"
        && taskDate
        && (
          taskDate < today
          || (taskDate === today && deadlineTime && deadlineTime < currentTime)
        );
      if (!overdue) return false;
    }
    return true;
  });
}

function renderCalendarCard(item) {
  const quadrant = quadrantLabel(item);
  return `<article class="todo-calendar-card ${item.status === "completed" ? "completed" : ""} ${categoryCss(item.category)}">
    <button class="calendar-task-title" type="button" data-edit-todo="${item.id}">${escapeHtml(item.title)}</button>
    <div class="calendar-task-meta">${item.due_time ? `<span>${escapeHtml(item.due_time)}</span>` : ""}${item.category ? `<span>${escapeHtml(item.category)}</span>` : ""}<span class="quad-pill ${quadrant.css}">${quadrant.text}</span></div>
    <div class="calendar-task-meta">${escapeHtml(taskTimeLabel(item))}</div>
    <div class="calendar-task-actions">${item.status === "open" ? `<button type="button" data-complete-todo="${item.id}">完成</button>` : ""}<button type="button" data-delete-todo="${item.id}">删除</button></div>
  </article>`;
}

async function loadTodoCalendar() {
  const { first, last, anchor } = todoCalendarRange();
  appState.todoAnchor = $("#todo-calendar-date").value || localToday();
  const result = await api(`/api/v1/todos/calendar?from_date=${first}&to_date=${last}`);
  const items = filterCalendarItems(result.items);
  appState.todos = [...result.undated, ...result.items];
  const groups = new Map();
  for (const item of items) {
    const groupDate = item.start_date || item.end_date;
    if (!groupDate) continue;
    const group = groups.get(groupDate) || [];
    group.push(item);
    groups.set(groupDate, group);
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
    cells.push(`<section class="todo-calendar-day ${iso === localToday() ? "is-today" : ""} ${outside ? "outside-month" : ""}"><div class="todo-calendar-date"><button type="button" data-view-date="${iso}">${displayDate}</button><span>${entries.length ? entries.length + "项" : ""}</span></div><div class="todo-calendar-items">${entries.map(renderCalendarCard).join("") || `<span class="subtle">${appState.todoView === "day" ? "今天还没有任务" : ""}</span>`}</div></section>`);
  }
  grid.innerHTML = cells.join("");
  const undated = filterCalendarItems(result.undated);
  $("#todo-undated").innerHTML = undated.length ? `<strong>未设置日期 · ${undated.length} 项</strong><div class="todo-calendar-items">${undated.slice(0, 20).map(renderCalendarCard).join("")}</div>` : "";
  grid.querySelectorAll("[data-edit-todo]").forEach((button) => button.addEventListener("click", () => editTodo(Number(button.dataset.editTodo), appState.todos)));
  grid.querySelectorAll("[data-complete-todo]").forEach((button) => button.addEventListener("click", () => completeTodo(button.dataset.completeTodo)));
  grid.querySelectorAll("[data-delete-todo]").forEach((button) => button.addEventListener("click", () => removeTodo(button.dataset.deleteTodo)));
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
