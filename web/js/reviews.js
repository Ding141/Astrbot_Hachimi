import { appState } from "./state.js";
import { $, api, escapeHtml, toast, localToday } from "./core.js";
import { loadTodos } from "./todos.js";
import { loadSchedule } from "./timetable.js";

function mondayOf(value) {
  const day = new Date(`${value}T12:00:00`);
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return new Intl.DateTimeFormat("sv-SE").format(day);
}

function renderReview(result) {
  appState.reviewData = result;
  $("#weekly-reflection").value = result.reflection || "";
  const completed = result.completed || [];
  const unfinished = result.unfinished || [];
  const next = result.next_week || [];
  const nextCourses = next.reduce((sum, day) => sum + day.courses.length, 0);
  const nextEvents = next.reduce((sum, day) => sum + day.events.length, 0);
  const completedHtml = completed.length ? completed.slice(0, 8).map((item) => `<li>${escapeHtml(item.title)}</li>`).join("") : "<li>暂无</li>";
  const unfinishedHtml = unfinished.length ? unfinished.slice(0, 8).map((item) => `<li>${escapeHtml(item.title)} · ${escapeHtml(item.start_date || item.due_date || "未设置时间")}${item.start_time ? ` ${escapeHtml(item.start_time)}` : ""} 至 ${escapeHtml(item.due_date || "未设置结束日期")}${item.due_time ? ` ${escapeHtml(item.due_time)}` : ""}</li>`).join("") : "<li>暂无</li>";
  $("#weekly-review-overview").innerHTML = `<strong>${escapeHtml(result.week_start)} 至 ${escapeHtml(result.week_end)}</strong><p>完成 ${completed.length} 项，未完成 ${unfinished.length} 项；下周已有 ${nextCourses} 门课和 ${nextEvents} 项个人安排。</p><div class="review-columns"><div><b>本周完成</b><ul>${completedHtml}</ul></div><div><b>本周未完成</b><ul>${unfinishedHtml}</ul></div></div>`;
  const nextMonday = new Date(`${result.week_start}T12:00:00`);
  nextMonday.setDate(nextMonday.getDate() + 7);
  const nextSunday = new Date(nextMonday);
  nextSunday.setDate(nextSunday.getDate() + 6);
  $("#weekly-plan-todo-date").min = new Intl.DateTimeFormat("sv-SE").format(nextMonday);
  $("#weekly-plan-todo-date").max = new Intl.DateTimeFormat("sv-SE").format(nextSunday);
}

async function loadWeeklyReview() {
  const selected = $("#review-week-date").value || localToday();
  const monday = mondayOf(selected);
  try {
    const result = await api(`/api/v1/weekly-reviews/${monday}`);
    renderReview(result);
  } catch (error) { toast(error.message, "error"); }
}

async function saveWeeklyReview(event) {
  event.preventDefault();
  const selected = $("#review-week-date").value || localToday();
  const monday = mondayOf(selected);
  try {
    await api(`/api/v1/weekly-reviews/${monday}`, { method: "PUT", body: JSON.stringify({ reflection: $("#weekly-reflection").value }) });
    toast("本周复盘已保存");
    await loadWeeklyReview();
  } catch (error) { toast(error.message, "error"); }
}

async function addWeeklyTodo(event) {
  event.preventDefault();
  const title = $("#weekly-plan-todo-title").value.trim();
  const dueDate = $("#weekly-plan-todo-date").value;
  if (!title) return;
  try {
    await api("/api/v1/todos", { method: "POST", body: JSON.stringify({ title, end_date: dueDate || null }) });
    $("#weekly-plan-todo-form").reset();
    toast("下周 Todo 已添加");
    await Promise.all([loadWeeklyReview(), loadTodos()]);
  } catch (error) { toast(error.message, "error"); }
}

async function addWeeklyEvent(event) {
  event.preventDefault();
  const dateValue = $("#weekly-plan-event-date").value;
  const start = Number($("#weekly-plan-event-start").value);
  const end = Number($("#weekly-plan-event-end").value);
  if (end < start) { toast("结束节次不能早于开始节次。", "error"); return; }
  try {
    const result = await api("/api/v1/schedule-events", { method: "POST", body: JSON.stringify({
      title: $("#weekly-plan-event-title").value.trim(), frequency: "once", event_date: dateValue,
      start_period: start, end_period: end,
    }) });
    $("#weekly-plan-event-form").reset();
    toast(result.conflicts?.length ? `日程已保存，发现 ${result.conflicts.length} 项时间冲突。` : "下周日程已添加");
    await Promise.all([loadWeeklyReview(), loadSchedule()]);
  } catch (error) { toast(error.message, "error"); }
}

export { loadWeeklyReview, saveWeeklyReview, addWeeklyTodo, addWeeklyEvent };
