import { $, api, escapeHtml, toast, localDateTime } from "./core.js";

const reminderLabels = { pending: "待发送", sending: "发送中", sent: "已发送", failed: "失败", uncertain: "结果不确定", cancelled: "已取消" };

async function loadReminders() {
  try {
    const [result, todos] = await Promise.all([
      api("/api/v1/reminders"),
      api("/api/v1/todos?status=open"),
    ]);
    const todoSelect = $("#reminder-todo");
    const currentSelection = todoSelect.value;
    todoSelect.innerHTML = `<option value="">不关联任务</option>${todos.items.map((todo) => `<option value="${todo.id}">${escapeHtml(todo.title)}</option>`).join("")}`;
    if (todos.items.some((todo) => String(todo.id) === currentSelection)) todoSelect.value = currentSelection;
    const rows = $("#reminder-rows");
    rows.innerHTML = result.items.map((item) => `<tr>
      <td><div class="task-title">${escapeHtml(item.title)}</div>${item.recipient_umo ? "" : `<div class="subtle">等待微信会话绑定</div>`}</td>
      <td>${escapeHtml(localDateTime(item.remind_at))}</td>
      <td><span class="status-pill status-${item.status}">${reminderLabels[item.status] || item.status}</span></td>
      <td>${item.attempt_count}</td>
      <td class="subtle">${escapeHtml(item.last_error || "—")}</td>
      <td class="actions">${["failed", "uncertain"].includes(item.status) ? `<button class="mini retry-action" data-id="${item.id}" title="确认并重试">↻</button>` : ""}${["pending", "failed", "uncertain"].includes(item.status) ? `<button class="mini danger cancel-reminder" data-id="${item.id}" title="取消">×</button>` : ""}</td>
    </tr>`).join("");
    $("#reminder-empty").hidden = result.items.length > 0;
    rows.querySelectorAll(".retry-action").forEach((button) => button.addEventListener("click", () => retryReminder(button.dataset.id)));
    rows.querySelectorAll(".cancel-reminder").forEach((button) => button.addEventListener("click", () => cancelReminder(button.dataset.id)));
  } catch (error) { toast(error.message, "error"); }
}

async function submitReminder(event) {
  event.preventDefault();
  const todoId = $("#reminder-todo").value;
  const todoLabel = todoId ? $("#reminder-todo").selectedOptions[0]?.textContent : "";
  const payload = {
    title: $("#reminder-title").value.trim(),
    remind_at: $("#reminder-at").value,
    ...(todoId ? { todo_id: Number(todoId) } : {}),
  };
  if (!payload.title && todoLabel) payload.title = todoLabel;
  if (!payload.title) { toast("请填写提醒内容或关联一项任务。", "error"); return; }
  try {
    await api("/api/v1/reminders", { method: "POST", body: JSON.stringify(payload) });
    $("#reminder-form").reset();
    toast("提醒已保存");
    await loadReminders();
  } catch (error) { toast(error.message, "error"); }
}

async function retryReminder(id) {
  if (!window.confirm("发送结果可能不确定。确认重试可能造成重复通知，仍要继续吗？")) return;
  try {
    await api(`/api/v1/reminders/${id}/retry`, { method: "POST", body: JSON.stringify({ confirm: true }) });
    toast("提醒已加入发送队列");
    await loadReminders();
  } catch (error) { toast(error.message, "error"); }
}

async function cancelReminder(id) {
  try {
    await api(`/api/v1/reminders/${id}`, { method: "DELETE" });
    toast("提醒已取消");
    await loadReminders();
  } catch (error) { toast(error.message, "error"); }
}

async function loadReminderSchedules() {
  try {
    const result = await api("/api/v1/settings/reminder-schedules");
    $("#daily-brief-enabled").checked = result.daily_brief_enabled;
    $("#daily-brief-time").value = result.daily_brief_time;
    $("#weekly-review-enabled").checked = result.weekly_review_enabled;
    $("#weekly-review-weekday").value = String(result.weekly_review_weekday);
    $("#weekly-review-time").value = result.weekly_review_time;
  } catch (error) { toast(error.message, "error"); }
}

async function saveReminderSchedules(event) {
  event.preventDefault();
  const payload = {
    daily_brief_enabled: $("#daily-brief-enabled").checked,
    daily_brief_time: $("#daily-brief-time").value,
    weekly_review_enabled: $("#weekly-review-enabled").checked,
    weekly_review_weekday: Number($("#weekly-review-weekday").value),
    weekly_review_time: $("#weekly-review-time").value,
  };
  try {
    await api("/api/v1/settings/reminder-schedules", { method: "PATCH", body: JSON.stringify(payload) });
    toast("自动提醒计划已保存");
    await loadReminderSchedules();
  } catch (error) { toast(error.message, "error"); }
}

export { loadReminders, submitReminder, retryReminder, cancelReminder, loadReminderSchedules, saveReminderSchedules };
