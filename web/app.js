import { $, api, toast, localToday, loadSettings, showLogin, showApplication, setView, closeDrawer, openDrawer } from "/assets/core.js";
import { loadTodos, submitTodo, clearTodoForm, bulkDeleteTodos, updateBulkDeleteState, openNewTodo } from "/assets/todos.js";
import { loadReminders, submitReminder, saveReminderSchedules } from "/assets/reminders.js";
import { loadWeeklyReview, saveWeeklyReview, addWeeklyTodo, addWeeklyEvent } from "/assets/reviews.js";
import { fillPeriodSelects, loadSchedule, submitScheduleEvent, resetScheduleEventForm, shiftSchedule, previewCourseImport, commitCourseImport, invalidateCoursePreview, openNewScheduleEvent } from "/assets/timetable.js";
import { loadAudit } from "/assets/activity.js";

async function openApplication() {
  showApplication();
  await loadSettings();
  await Promise.all([loadTodos(), loadSchedule()]);
}

async function initialize() {
  setView("todos");
  fillPeriodSelects();
  const isoToday = localToday();
  $("#today-label").textContent = new Date().toLocaleDateString("zh-CN", { weekday: "long", month: "long", day: "numeric", timeZone: "Asia/Shanghai" });
  $("#schedule-date").value = isoToday;
  $("#review-week-date").value = isoToday;
  try {
    await api("/api/v1/auth/me");
    await openApplication();
  } catch { showLogin(); }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ password: $("#login-password").value }) });
    await openApplication();
  } catch (error) { $("#login-error").textContent = error.message; }
});

$("#logout").addEventListener("click", async () => { await api("/api/v1/auth/logout", { method: "POST" }); showLogin(); });
$("#todo-form").addEventListener("submit", submitTodo);
$("#todo-cancel-edit").addEventListener("click", clearTodoForm);
$("#bulk-delete").addEventListener("click", bulkDeleteTodos);
$("#todo-select-visible").addEventListener("change", (event) => { document.querySelectorAll(".todo-select").forEach((checkbox) => { checkbox.checked = event.target.checked; }); updateBulkDeleteState(); });
$("#todo-search").addEventListener("input", () => { clearTimeout(loadTodos.timer); loadTodos.timer = setTimeout(() => loadTodos().catch((error) => toast(error.message, "error")), 250); });
$("#todo-status").addEventListener("change", () => loadTodos().catch((error) => toast(error.message, "error")));
$("#todo-due").addEventListener("change", () => loadTodos().catch((error) => toast(error.message, "error")));
$("#reload-reminders").addEventListener("click", loadReminders);
$("#reminder-form").addEventListener("submit", submitReminder);
$("#reminder-schedule-form").addEventListener("submit", saveReminderSchedules);
$("#load-week-review").addEventListener("click", loadWeeklyReview);
$("#weekly-review-form").addEventListener("submit", saveWeeklyReview);
$("#weekly-plan-todo-form").addEventListener("submit", addWeeklyTodo);
$("#weekly-plan-event-form").addEventListener("submit", addWeeklyEvent);
$("#review-week-date").addEventListener("change", loadWeeklyReview);
$("#reload-audit").addEventListener("click", loadAudit);
$("#schedule-event-form").addEventListener("submit", submitScheduleEvent);
$("#schedule-event-cancel").addEventListener("click", resetScheduleEventForm);
$("#schedule-event-frequency").addEventListener("change", () => {
  const weekly = $("#schedule-event-frequency").value === "weekly";
  $("#schedule-event-date-wrap").hidden = weekly;
  $("#schedule-event-weekly").hidden = !weekly;
  $("#schedule-event-date").required = !weekly;
  $("#schedule-event-start-date").required = weekly;
});
$("#todo-repeat-frequency").addEventListener("change", () => {
  const repeated = $("#todo-repeat-frequency").value !== "none";
  $("#todo-repeat-options").hidden = !repeated;
  $("#todo-repeat-weekdays").hidden = $("#todo-repeat-frequency").value !== "weekly";
});
$("#schedule-date").addEventListener("change", loadSchedule);
$("#schedule-view-mode").addEventListener("change", loadSchedule);
$("#schedule-prev").addEventListener("click", () => shiftSchedule(-1));
$("#schedule-next").addEventListener("click", () => shiftSchedule(1));
$("#schedule-today").addEventListener("click", () => { $("#schedule-date").value = localToday(); loadSchedule(); });
$("#course-preview").addEventListener("click", previewCourseImport);
$("#course-commit").addEventListener("click", commitCourseImport);
["#course-file", "#course-sheet", "#course-header-row", "#course-mapping"].forEach((selector) => $(selector).addEventListener("change", invalidateCoursePreview));
$("#add-todo-button").addEventListener("click", openNewTodo);
$("#add-schedule-button").addEventListener("click", () => openNewScheduleEvent());
$("#import-courses-button").addEventListener("click", () => openDrawer("course-import-editor", "导入 Excel 课表"));
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", async () => {
  const name = button.dataset.view;
  setView(name);
  try {
    if (name === "todos") await loadTodos();
    if (name === "courses") await loadSchedule();
    if (name === "reminders") await Promise.all([loadReminders(), loadWeeklyReview()]);
    if (name === "history") await loadAudit();
  } catch (error) { toast(error.message, "error"); }
}));

initialize();
