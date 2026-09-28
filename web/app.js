import { $, api, toast, localToday, loadSettings, showLogin, showApplication, setView, closeDrawer, openDrawer } from "/assets/core.js";
import { loadTodos, submitTodo, clearTodoForm, bulkDeleteTodos, updateBulkDeleteState, openNewTodo, setTodoView, shiftTodoCalendar } from "/assets/todos.js";
import { loadReminders, submitReminder, saveReminderSchedules } from "/assets/reminders.js";
import { loadWeeklyReview, saveWeeklyReview, addWeeklyTodo, addWeeklyEvent } from "/assets/reviews.js";
import { fillPeriodSelects, loadSchedule, submitScheduleEvent, resetScheduleEventForm, shiftSchedule, previewCourseImport, commitCourseImport, invalidateCoursePreview, openNewScheduleEvent, openCourseEditor, submitCourse, saveTermEndDate, setSelectedTerm, suggestTermEndDate, submitCourseOccurrence, cancelCourseOccurrence } from "/assets/timetable.js";
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
document.querySelectorAll("[data-todo-view]").forEach((button) => button.addEventListener("click", () => setTodoView(button.dataset.todoView)));
$("#todo-prev").addEventListener("click", () => shiftTodoCalendar(-1));
$("#todo-next").addEventListener("click", () => shiftTodoCalendar(1));
$("#todo-today").addEventListener("click", () => { $("#todo-calendar-date").value = localToday(); loadTodos(); });
$("#todo-calendar-date").addEventListener("change", loadTodos);
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
$("#course-form").addEventListener("submit", submitCourse);
$("#course-cancel-edit").addEventListener("click", closeDrawer);
$("#course-occurrence-form").addEventListener("submit", submitCourseOccurrence);
$("#occurrence-start-period").addEventListener("input", () => {
  $("#occurrence-start-time").value = "";
  $("#occurrence-end-time").value = "";
});
$("#occurrence-end-period").addEventListener("input", () => {
  $("#occurrence-start-time").value = "";
  $("#occurrence-end-time").value = "";
});
$("#occurrence-start-time").addEventListener("input", () => {
  $("#occurrence-start-period").value = "";
  $("#occurrence-end-period").value = "";
});
$("#occurrence-end-time").addEventListener("input", () => {
  $("#occurrence-start-period").value = "";
  $("#occurrence-end-period").value = "";
});
$("#course-occurrence-cancel").addEventListener("click", cancelCourseOccurrence);
$("#save-term-end").addEventListener("click", saveTermEndDate);
$("#course-term-select").addEventListener("change", (event) => setSelectedTerm(event.target.value));
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
  $("#todo-repeat-month-day-wrap").hidden = $("#todo-repeat-frequency").value !== "monthly";
});
$("#schedule-date").addEventListener("change", loadSchedule);
$("#schedule-view-mode").addEventListener("change", loadSchedule);
$("#schedule-prev").addEventListener("click", () => shiftSchedule(-1));
$("#schedule-next").addEventListener("click", () => shiftSchedule(1));
$("#schedule-today").addEventListener("click", () => { $("#schedule-date").value = localToday(); loadSchedule(); });
$("#course-preview").addEventListener("click", previewCourseImport);
$("#course-commit").addEventListener("click", commitCourseImport);
$("#term-week1").addEventListener("change", suggestTermEndDate);
$("#term-end").addEventListener("input", () => { $("#term-end").dataset.touched = "1"; });
["#course-file", "#course-sheet", "#course-header-row", "#course-mapping"].forEach((selector) => $(selector).addEventListener("change", invalidateCoursePreview));
$("#add-todo-button").addEventListener("click", openNewTodo);
$("#add-schedule-button").addEventListener("click", () => openNewScheduleEvent());
$("#add-course-button").addEventListener("click", () => openCourseEditor());
$("#import-courses-button").addEventListener("click", () => {
  $("#term-end").dataset.touched = "0";
  $("#term-end").value = "";
  openDrawer("course-import-editor", "导入 Excel 课表");
  suggestTermEndDate();
});
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
