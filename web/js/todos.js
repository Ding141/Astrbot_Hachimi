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
  const parentSelect = $("#todo-parent");
  appState.todos = result.items;
  const parentValue = parentSelect.value;
  parentSelect.innerHTML = `<option value="">作为独立任务</option>${result.items.filter((item) => !item.parent_id && item.status === "open").map((item) => `<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("")}`;
  if ([...parentSelect.options].some((option) => option.value === parentValue)) parentSelect.value = parentValue;
  const rows = $("#todo-rows");
  rows.innerHTML = result.items.map((item) => {
    const reminderCount = item.reminders.filter((reminder) => reminder.status !== "sent").length;
    const priorityClass = item.priority >= 4 ? "priority high" : item.priority <= 2 ? "priority low" : "priority";
    return `<tr class="${item.status === "completed" ? "completed-row" : ""}">
      <td><input class="todo-select" type="checkbox" value="${item.id}" aria-label="选择任务 ${escapeHtml(item.title)}"></td>
      <td><div class="task-title">${item.parent_id ? "↳ " : ""}${escapeHtml(item.title)}</div>${item.recurrence ? `<div class="subtle">${item.recurrence.frequency === "daily" ? "每日重复" : "每周重复"} · 本期</div>` : ""}${item.child_count ? `<div class="subtle">子任务进度 ${item.child_done}/${item.child_count}</div>` : ""}${item.notes ? `<div class="subtle">${escapeHtml(item.notes)}</div>` : ""}</td>
      <td>${escapeHtml(localDate(item.due_date, item.due_time))}</td>
      <td>${item.category ? `<span class="tag">${escapeHtml(item.category)}</span>` : "—"}</td>
      <td><span class="${priorityClass}">${item.priority}/5</span></td>
      <td>${reminderCount ? `<span class="reminder-count">◷ ${reminderCount}</span>` : "—"}</td>
      <td class="actions">${item.status === "open" ? `<button class="mini complete-action" data-id="${item.id}" title="完成">✓</button>` : ""}<button class="mini edit-action" data-id="${item.id}" title="编辑">✎</button><button class="mini danger delete-action" data-id="${item.id}" title="删除">×</button></td>
    </tr>`;
  }).join("");
  $("#todo-empty").hidden = result.items.length > 0;
  updateStats(result.items, today.items, overdue.items);
  rows.querySelectorAll(".complete-action").forEach((button) => button.addEventListener("click", () => completeTodo(button.dataset.id)));
  rows.querySelectorAll(".edit-action").forEach((button) => button.addEventListener("click", () => editTodo(Number(button.dataset.id), result.items)));
  rows.querySelectorAll(".delete-action").forEach((button) => button.addEventListener("click", () => removeTodo(button.dataset.id)));
  rows.querySelectorAll(".todo-select").forEach((checkbox) => checkbox.addEventListener("change", updateBulkDeleteState));
  $("#todo-select-visible").checked = false;
  updateBulkDeleteState();
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
  $("#todo-priority").value = "3";
  $("#todo-repeat-frequency").value = "none";
  $("#todo-repeat-options").hidden = true;
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
  $("#todo-priority").value = String(item.priority);
  $("#todo-due-date").value = item.due_date || "";
  $("#todo-due-time").value = item.due_time || "";
  $("#todo-reminders").value = item.reminders
    .filter((reminder) => ["pending", "failed", "uncertain"].includes(reminder.status))
    .map((reminder) => localReminderInput(reminder.remind_at)).join("\n");
  $("#todo-parent").value = item.parent_id ? String(item.parent_id) : "";
  $("#todo-repeat-frequency").value = item.recurrence?.frequency || "none";
  $("#todo-repeat-frequency").disabled = Boolean(item.recurrence);
  $("#todo-repeat-options").hidden = !item.recurrence;
  $("#todo-repeat-start").value = item.recurrence?.start_date || "";
  $("#todo-repeat-end").value = item.recurrence?.end_date || "";
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
  const dueDate = $("#todo-due-date").value;
  const dueTime = $("#todo-due-time").value;
  const repeat = $("#todo-repeat-frequency").value;
  if (dueTime && !dueDate && repeat === "none") {
    toast("请先选择截止日期，再填写截止时刻。", "error");
    return;
  }
  const payload = {
    title: $("#todo-title").value.trim(),
    notes: $("#todo-notes").value,
    category: $("#todo-category").value.trim(),
    priority: Number($("#todo-priority").value),
    due_date: dueDate || null,
    due_time: dueTime || null,
  };
  const reminders = $("#todo-reminders").value.split(/[\n,，;；]+/).map((value) => value.trim()).filter(Boolean);
  if (reminders.length > 10) { toast("每项任务最多设置10个提醒。", "error"); return; }
  if (!id && reminders.some((value) => !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value))) {
    toast("提醒时间请填写完整日期和时刻，例如 2026-09-28T08:00。", "error"); return;
  }
  if (id && !appState.editingTodo?.recurrence) payload.reminders = reminders.map((remind_at) => ({ remind_at }));
  if (id && appState.editingTodo?.recurrence) {
    const scope = window.prompt("这是重复任务，请输入 occurrence 只修改本期，或 series 修改整个系列：", "occurrence");
    if (!scope) return;
    if (!["occurrence", "series"].includes(scope.trim())) { toast("请输入 occurrence 或 series。", "error"); return; }
    if (scope.trim() === "series") {
      const times = $("#todo-repeat-reminder-times").value.split(/[,，;；\s]+/).filter(Boolean);
      if (times.some((value) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(value))) { toast("重复提醒时刻请使用 HH:MM 格式。", "error"); return; }
      const weekdays = [...$("#todo-repeat-weekdays").querySelectorAll("input:checked")].map((node) => Number(node.value));
      if (repeat === "weekly" && !weekdays.length) { toast("请选择每周重复的星期。", "error"); return; }
      try {
        const result = await api(`/api/v1/todo-series/${appState.editingTodo.recurrence.series_id}`, { method: "PATCH", body: JSON.stringify({
          title: payload.title, notes: payload.notes, category: payload.category, priority: payload.priority,
          frequency: repeat, weekdays: repeat === "weekly" ? weekdays : [],
          start_date: $("#todo-repeat-start").value || appState.editingTodo.recurrence.start_date || localToday(),
          end_date: $("#todo-repeat-end").value || null, due_time: dueTime || null,
          reminder_enabled: $("#todo-repeat-reminder-enabled").checked && times.length > 0,
          reminder_times: times,
        }) });
        toast(`已更新重复任务系列：${result.title}`);
        clearTodoForm();
        await loadTodos();
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    payload.reminders = reminders.map((remind_at) => ({ remind_at }));
    const path = `/api/v1/todos/${id}?scope=occurrence`;
    try {
      await api(path, { method: "PATCH", body: JSON.stringify(payload) });
      toast("本期任务已更新");
      clearTodoForm();
      await loadTodos();
    } catch (error) { toast(error.message, "error"); }
    return;
  }
  if (!id && repeat !== "none") {
    if ($("#todo-parent").value) { toast("重复任务暂不能同时设为子任务。", "error"); return; }
    const weekdays = [...$("#todo-repeat-weekdays").querySelectorAll("input:checked")].map((node) => Number(node.value));
    if (repeat === "weekly" && !weekdays.length) { toast("请选择每周重复的星期。", "error"); return; }
    const times = $("#todo-repeat-reminder-times").value.split(/[,，;；\s]+/).filter(Boolean);
    if (times.some((value) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(value))) { toast("重复提醒时刻请使用 HH:MM 格式。", "error"); return; }
    const start = $("#todo-repeat-start").value || dueDate || localToday();
    try {
      const result = await api("/api/v1/todo-series", { method: "POST", body: JSON.stringify({
        title: payload.title, notes: payload.notes, category: payload.category, priority: payload.priority,
        frequency: repeat, weekdays: repeat === "weekly" ? weekdays : [], start_date: start,
        end_date: $("#todo-repeat-end").value || null, due_time: dueTime || null,
        reminder_enabled: $("#todo-repeat-reminder-enabled").checked && times.length > 0,
        reminder_times: times,
      }) });
      toast(`已建立重复任务：${result.title}`);
      clearTodoForm();
      await loadTodos();
    } catch (error) { toast(error.message, "error"); }
    return;
  }
  if (!id && reminders.length) payload.reminders = reminders.map((remind_at) => ({ remind_at }));
  if (!id && $("#todo-parent").value) payload.parent_id = Number($("#todo-parent").value);
  let path = id ? `/api/v1/todos/${id}` : "/api/v1/todos";
  try {
    await api(path, {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    toast(id ? "任务已更新" : "任务已添加");
    clearTodoForm();
    await loadTodos();
  } catch (error) { toast(error.message, "error"); }
}

function openNewTodo() { clearTodoForm(); openDrawer("todo-editor", "新建待办"); }

export { loadTodos, updateBulkDeleteState, bulkDeleteTodos, clearTodoForm, editTodo, completeTodo, removeTodo, submitTodo, openNewTodo };
