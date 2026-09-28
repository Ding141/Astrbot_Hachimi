import { appState } from "./state.js";
import { $, api, escapeHtml, toast, localToday, openDrawer, closeDrawer } from "./core.js";

const weekdayLabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const PERIOD_TIMES = [
  ["08:00", "08:45"], ["08:50", "09:35"], ["09:50", "10:35"], ["10:40", "11:25"], ["11:30", "12:15"],
  ["14:00", "14:45"], ["14:50", "15:35"], ["15:50", "16:35"], ["16:40", "17:25"], ["17:30", "18:15"],
  ["19:00", "19:45"], ["19:50", "20:35"], ["20:40", "21:25"], ["21:30", "22:15"],
];

function periodForClock(value, isEnd = false) {
  const clock = String(value || "").slice(0, 5);
  const index = PERIOD_TIMES.findIndex((range) => range[isEnd ? 1 : 0] === clock);
  return index >= 0 ? index + 1 : null;
}

function openNewScheduleEvent(dateValue = appState.scheduleAnchor || localToday(), period = null) {
  resetScheduleEventForm(false);
  $("#schedule-event-date").value = dateValue;
  $("#schedule-event-start-date").value = dateValue;
  if (period) {
    $("#schedule-event-start-period").value = String(period);
    $("#schedule-event-end-period").value = String(period);
  }
  openDrawer("schedule-event-editor", "添加个人安排");
}

function fillPeriodSelects() {
  const options = `<option value="">选择节次</option>${Array.from({ length: 14 }, (_, index) => `<option value="${index + 1}">第 ${index + 1} 节</option>`).join("")}`;
  ["#schedule-event-start-period", "#schedule-event-end-period", "#weekly-plan-event-start", "#weekly-plan-event-end"].forEach((selector) => { $(selector).innerHTML = options; });
}

function scheduleDateSpan(day) {
  return `${day.slice(5)}（${weekdayLabels[(new Date(`${day}T12:00:00`).getDay() + 6) % 7]}）`;
}

function shiftSchedule(direction) {
  const selected = new Date(`${$("#schedule-date").value || localToday()}T12:00:00`);
  selected.setDate(selected.getDate() + direction * ($("#schedule-view-mode").value === "day" ? 1 : 7));
  $("#schedule-date").value = new Intl.DateTimeFormat("sv-SE").format(selected);
  loadSchedule();
}

function selectCourse(courseId, occurrenceDate) {
  appState.selectedCourse = { id: courseId, date: occurrenceDate };
  document.querySelectorAll(".course-entry").forEach((card) => {
    const selected = Number(card.dataset.courseId) === courseId && card.dataset.courseDate === occurrenceDate;
    card.classList.toggle("is-selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  renderSelectedCourseDetails();
}

function renderSelectedCourseDetails() {
  const panel = $("#schedule-course-details");
  const workspace = $("#schedule-workspace");
  const selection = appState.selectedCourse;
  const course = selection && appState.courses.find((item) => item.id === selection.id && item.date === selection.date);
  if (!course) {
    panel.hidden = true;
    panel.innerHTML = "";
    workspace.classList.remove("has-selected-course");
    return;
  }
  const isCancelled = course.exception?.action === "cancelled";
  const weekPattern = (course.weeks || []).length
    ? `第 ${(course.weeks || []).join("、")} 周`
    : ({ odd: "单周", even: "双周", all: "每周" })[course.week_parity] || "未设置周次";
  const periodTime = course.start_time || course.end_time
    ? `${course.start_time || "未设置"}–${course.end_time || "未设置"}`
    : `第 ${course.start_period || "?"}–${course.end_period || course.start_period || "?"} 节`;
  panel.hidden = false;
  workspace.classList.add("has-selected-course");
  panel.innerHTML = `<header class="selected-course-heading"><div><span class="eyebrow">课程详情</span><h3>${escapeHtml(course.course_name)}</h3></div><button class="selected-course-close" type="button" aria-label="关闭课程详情">×</button></header>
    <dl class="selected-course-facts"><div><dt>上课日期</dt><dd>${escapeHtml(course.date)}</dd></div><div><dt>上课时间</dt><dd>${escapeHtml(periodTime)}</dd></div><div><dt>教师</dt><dd>${escapeHtml(course.teacher || "未填写")}</dd></div><div><dt>地点</dt><dd>${escapeHtml(course.location || "未填写")}</dd></div><div><dt>轮次</dt><dd>${escapeHtml(weekPattern)}${course.exception?.action === "override" ? " · 本次已调整" : ""}</dd></div><div><dt>课前提醒</dt><dd>${course.reminder_enabled ? `提前 ${Number(course.reminder_lead_minutes || 10)} 分钟` : "未开启"}</dd></div></dl>
    <div class="selected-course-actions"><button class="secondary selected-course-reminder" type="button">${course.reminder_enabled ? "调整 / 关闭提醒" : "添加课前提醒"}</button><button class="secondary selected-course-edit" type="button">编辑学期规则与轮次</button><button class="secondary selected-course-occurrence" type="button">调整本次课程</button>${isCancelled ? `<button class="secondary selected-course-restore" type="button">恢复本次上课</button>` : `<button class="secondary selected-course-cancel" type="button">本次停课</button>`}<button class="secondary danger-button selected-course-delete" type="button">删除整门课</button></div>`;
  panel.querySelector(".selected-course-close").addEventListener("click", () => {
    appState.selectedCourse = null;
    renderSelectedCourseDetails();
    document.querySelectorAll(".course-entry").forEach((card) => { card.classList.remove("is-selected"); card.setAttribute("aria-pressed", "false"); });
  });
  panel.querySelector(".selected-course-reminder").addEventListener("click", () => toggleCourseAlert(course.id, Boolean(course.reminder_enabled), Number(course.reminder_lead_minutes || 10)));
  panel.querySelector(".selected-course-edit").addEventListener("click", () => openCourseEditor(course.id));
  panel.querySelector(".selected-course-occurrence").addEventListener("click", () => openCourseOccurrenceEditor(course.id, course.date));
  panel.querySelector(".selected-course-cancel")?.addEventListener("click", () => cancelCourseOccurrenceFor(course.id, course.date));
  panel.querySelector(".selected-course-restore")?.addEventListener("click", () => restoreCourseOccurrence(course.id, course.date));
  panel.querySelector(".selected-course-delete").addEventListener("click", () => deleteCourse(course.id));
}

async function cancelCourseOccurrenceFor(courseId, day) {
  if (!window.confirm(`确认只取消「${appState.courses.find((item) => item.id === courseId && item.date === day)?.course_name || "这门课"}」在 ${day} 的上课？`)) return;
  try {
    await api(`/api/v1/courses/${courseId}/occurrences/${day}`, { method: "PUT", body: JSON.stringify({ action: "cancelled" }) });
    toast("这次课程已标记为停课。");
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

async function loadSchedule() {
  const anchor = $("#schedule-date").value || localToday();
  appState.scheduleAnchor = anchor;
  try {
    const termResult = await api("/api/v1/terms");
    appState.terms = termResult.items || [];
    appState.activeTermId = termResult.active_term_id;
    const termSelect = $("#course-term-select");
    const selected = appState.selectedTermId || "";
    termSelect.innerHTML = `<option value="">按日期自动选择</option>${appState.terms.map((term) => `<option value="${term.id}">${escapeHtml(term.name)} · ${escapeHtml(term.week1_monday)} 至 ${escapeHtml(term.end_date || "未设结束日期")}${term.end_date_inferred ? "（推算）" : ""}</option>`).join("")}`;
    termSelect.value = selected;
    const editTerm = $("#course-edit-term");
    if (editTerm) editTerm.innerHTML = appState.terms.map((term) => `<option value="${term.id}">${escapeHtml(term.name)}</option>`).join("");
    const dateTerm = appState.terms.find((term) => term.week1_monday <= anchor && (!term.end_date || term.end_date >= anchor));
    const selectedTerm = selected ? appState.terms.find((term) => String(term.id) === String(selected)) : dateTerm;
    $("#term-end-date").value = selectedTerm?.end_date || "";
    $("#term-end-date").disabled = !selectedTerm;
    $("#save-term-end").disabled = !selectedTerm;
    $("#term-end-hint").textContent = selectedTerm?.end_date_inferred ? "结束日期由第18周周日推算；请按实际校历核对。" : selectedTerm ? `正在编辑：${selectedTerm.name}` : "这一天没有对应学期";
    const termParam = selected ? `&term_id=${encodeURIComponent(selected)}` : "";
    const result = await api(`/api/v1/courses/week?week_start=${encodeURIComponent(anchor)}${termParam}`);
    appState.courses = result.days.flatMap((day) => [...day.courses, ...(day.cancelled_courses || [])].map((course) => ({ ...course, date: day.date })));
    const dayMode = $("#schedule-view-mode").value === "day";
    const shownDays = dayMode ? result.days.filter((day) => day.date === anchor) : result.days;
    $("#schedule-caption").innerHTML = `<span>${escapeHtml(result.week_start)} 至 ${escapeHtml(result.week_end)}</span><strong>${escapeHtml(result.term || "未导入学期")}${result.week ? ` · 第 ${result.week} 周` : ""}</strong>`;
    const grid = $("#schedule-grid");
    grid.classList.toggle("day-mode", dayMode);
    const columns = shownDays.length || 1;
    const header = shownDays.map((day) => `<div class="timetable-date-head ${day.date === localToday() ? "is-today" : ""}"><strong>${escapeHtml(weekdayLabels[(new Date(`${day.date}T12:00:00`).getDay() + 6) % 7])}</strong><span>${escapeHtml(day.date.slice(5))}</span>${day.week ? `<small>第 ${day.week} 周</small>` : ""}${(day.cancelled_courses || []).map((item) => `<small class="cancelled-course-note">已停课：${escapeHtml(item.course_name)} <button class="course-restore-action" type="button" data-id="${item.id}" data-date="${day.date}">恢复</button></small>`).join("")}</div>`).join("");
    const tracks = shownDays.map((day) => {
      const entries = [
        ...day.courses.map((item) => ({ ...item, kind: "course", start_period: Number(item.start_period || periodForClock(item.start_time) || 1), end_period: Number(item.end_period || periodForClock(item.end_time, true) || item.start_period || periodForClock(item.start_time) || 1) })),
        ...day.events.map((item) => ({ ...item, kind: "event", start_period: Number(item.start_period || 1), end_period: Number(item.end_period || item.start_period || 1) })),
      ].sort((a, b) => a.start_period - b.start_period || b.end_period - a.end_period);
      const laneEnds = [];
      entries.forEach((item) => {
        let lane = laneEnds.findIndex((end) => end < item.start_period);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = item.end_period;
        item.lane = lane;
      });
      const laneCount = Math.max(1, laneEnds.length);
      const occupied = Array.from({ length: laneCount }, () => new Set());
      entries.forEach((item) => { for (let period = item.start_period; period <= item.end_period; period += 1) occupied[item.lane].add(period); });
      const emptySlots = [];
      for (let lane = 0; lane < laneCount; lane += 1) {
        for (let period = 1; period <= 14; period += 1) {
          if (!occupied[lane].has(period)) emptySlots.push(`<button class="time-slot ${[6, 11].includes(period) ? "session-break" : ""}" style="grid-column:${lane + 1};grid-row:${period}" type="button" data-date="${day.date}" data-period="${period}" aria-label="${escapeHtml(day.date)} 第${period}节空闲，点击添加安排"><span>＋</span></button>`);
        }
      }
      const cards = entries.map((item) => {
        const start = Math.max(1, Math.min(14, item.start_period));
        const end = Math.max(start, Math.min(14, item.end_period));
        const range = `${PERIOD_TIMES[start - 1][0]}–${PERIOD_TIMES[end - 1][1]}`;
        if (item.kind === "event") return `<article class="timetable-entry personal-entry" style="grid-column:${item.lane + 1};grid-row:${start}/${end + 1}"><div class="entry-time">第${start}–${end}节 · ${range}</div><strong>${escapeHtml(item.title)}</strong>${item.frequency === "weekly" ? "<small>每周重复</small>" : ""}<div class="entry-actions"><button class="event-edit" type="button" data-id="${item.id}">编辑</button><button class="event-delete" type="button" data-id="${item.id}">删除</button></div></article>`;
        const cancelled = item.exception?.action === "cancelled";
        const selected = appState.selectedCourse?.id === item.id && appState.selectedCourse?.date === day.date;
        return `<article class="timetable-entry course-entry ${cancelled ? "is-cancelled" : ""} ${selected ? "is-selected" : ""}" style="grid-column:${item.lane + 1};grid-row:${start}/${end + 1}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="查看课程 ${escapeHtml(item.course_name)} 详情" data-course-id="${item.id}" data-course-date="${day.date}"><div class="entry-time">第${start}–${end}节 · ${range}</div><strong>${escapeHtml(item.course_name)}</strong><small>${[item.teacher && `老师 ${item.teacher}`, item.location && `地点 ${item.location}`].filter(Boolean).map(escapeHtml).join(" · ") || "未填写教师和地点"}</small>${cancelled ? "<small>本次停课</small>" : ""}</article>`;
      }).join("");
      return `<section class="timetable-day-track" style="--lanes:${laneCount}">${emptySlots.join("")}${cards}</section>`;
    }).join("");
    const axis = PERIOD_TIMES.map(([start, end], index) => `<div class="period-label ${[5, 10].includes(index + 1) ? "session-break" : ""}"><strong>第${index + 1}节</strong><span>${start}</span><small>${end}</small></div>`).join("");
    grid.style.setProperty("--day-count", String(columns));
    grid.innerHTML = `<div class="timetable-head"><div class="period-head">节次</div>${header}</div><div class="timetable-body"><div class="period-axis">${axis}</div>${tracks}</div>`;
    const visibleCourseKeys = new Set(shownDays.flatMap((day) => [...day.courses, ...(day.cancelled_courses || [])].map((course) => `${course.id}:${day.date}`)));
    if (appState.selectedCourse && !visibleCourseKeys.has(`${appState.selectedCourse.id}:${appState.selectedCourse.date}`)) appState.selectedCourse = null;
    grid.querySelectorAll(".course-entry").forEach((card) => {
      const select = () => selectCourse(Number(card.dataset.courseId), card.dataset.courseDate);
      card.addEventListener("click", select);
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
    });
    renderSelectedCourseDetails();
    grid.querySelectorAll(".course-restore-action").forEach((button) => button.addEventListener("click", () => restoreCourseOccurrence(Number(button.dataset.id), button.dataset.date)));
    grid.querySelectorAll(".event-edit").forEach((button) => button.addEventListener("click", () => editScheduleEvent(Number(button.dataset.id), result.days)));
    grid.querySelectorAll(".event-delete").forEach((button) => button.addEventListener("click", () => deleteScheduleEvent(button.dataset.id)));
    grid.querySelectorAll(".time-slot").forEach((button) => button.addEventListener("click", () => openNewScheduleEvent(button.dataset.date, Number(button.dataset.period))));
  } catch (error) { toast(error.message, "error"); }
}

async function toggleCourseAlert(id, enabled, currentLead = 10) {
  const payload = { reminder_enabled: !enabled };
  if (!enabled) {
    const answer = window.prompt("课前提前几分钟提醒？", String(currentLead));
    if (answer === null) return;
    const lead = Number(answer);
    if (!Number.isInteger(lead) || lead < 0 || lead > 180) { toast("提前时间请填写0到180之间的分钟数。", "error"); return; }
    payload.reminder_lead_minutes = lead;
  }
  try {
    await api(`/api/v1/courses/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
    toast(!enabled ? `已开启课前提醒，提前${payload.reminder_lead_minutes}分钟` : "课前提醒已关闭");
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

async function saveTermEndDate() {
  const selected = $("#course-term-select").value;
  const anchor = $("#schedule-date").value || localToday();
  const term = selected ? appState.terms.find((item) => String(item.id) === selected) : appState.terms.find((item) => item.week1_monday <= anchor && (!item.end_date || item.end_date >= anchor));
  if (!term) { toast("请先导入或选择一个学期。", "error"); return; }
  const endDate = $("#term-end-date").value;
  if (!endDate || endDate < term.week1_monday) { toast("学期结束日期不能早于第1周周一。", "error"); return; }
  try {
    await api(`/api/v1/terms/${term.id}`, { method: "PATCH", body: JSON.stringify({ end_date: endDate }) });
    toast("学期结束日期已保存。");
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

function compressWeeks(weeks = []) {
  const values = [...new Set(weeks)].sort((a, b) => a - b);
  if (!values.length) return "";
  const ranges = [];
  for (let index = 0; index < values.length;) {
    let end = index;
    while (end + 1 < values.length && values[end + 1] === values[end] + 1) end += 1;
    ranges.push(end === index ? String(values[index]) : `${values[index]}-${values[end]}`);
    index = end + 1;
  }
  return ranges.join(",");
}

function parseWeeks(value) {
  const result = new Set();
  for (const part of value.split(/[,，\s]+/).filter(Boolean)) {
    const match = part.match(/^(\d{1,2})(?:-(\d{1,2}))?$/);
    if (!match) throw new Error("周次请使用 1-8,10-16 这样的格式。");
    const first = Number(match[1]);
    const last = Number(match[2] || match[1]);
    if (first < 1 || last > 40 || last < first) throw new Error("周次范围需在1到40之间。");
    for (let week = first; week <= last; week += 1) result.add(week);
  }
  return [...result].sort((a, b) => a - b);
}

async function openCourseEditor(courseId = null) {
  const form = $("#course-form");
  form.reset();
  $("#course-id").value = "";
  $("#course-edit-start-period").value = "";
  $("#course-edit-end-period").value = "";
  $("#course-edit-weeks").value = "";
  $("#course-edit-parity").value = "all";
  $("#course-edit-term").disabled = Boolean(courseId);
  if (!appState.terms?.length) await loadSchedule();
  const selectedTerm = appState.selectedTermId || appState.activeTermId || appState.terms?.[0]?.id;
  $("#course-edit-term").value = String(selectedTerm || "");
  if (courseId) {
    try {
      const course = await api(`/api/v1/courses/${courseId}`);
      $("#course-id").value = course.id;
      $("#course-edit-term").value = String(course.term_id);
      $("#course-edit-name").value = course.course_name;
      $("#course-edit-weekday").value = String(course.weekday);
      $("#course-edit-parity").value = course.week_parity;
      $("#course-edit-start-period").value = course.start_period || "";
      $("#course-edit-end-period").value = course.end_period || "";
      $("#course-edit-start-time").value = course.start_time || "";
      $("#course-edit-end-time").value = course.end_time || "";
      $("#course-edit-weeks").value = compressWeeks(course.weeks);
      $("#course-edit-location").value = course.location || "";
      $("#course-edit-teacher").value = course.teacher || "";
      $("#course-edit-notes").value = course.notes || "";
    } catch (error) { toast(error.message, "error"); return; }
  }
  openDrawer("course-editor", courseId ? "编辑整学期课程" : "添加课程");
}

async function submitCourse(event) {
  event.preventDefault();
  const id = $("#course-id").value;
  const startPeriod = Number($("#course-edit-start-period").value || 0);
  const endPeriod = Number($("#course-edit-end-period").value || 0);
  const startTime = $("#course-edit-start-time").value;
  const endTime = $("#course-edit-end-time").value;
  if (Boolean(startPeriod) !== Boolean(endPeriod) || Boolean(startTime) !== Boolean(endTime)) { toast("开始和结束节次、或开始和结束时间都要成对填写。", "error"); return; }
  if (!startPeriod && !startTime) { toast("课程需要填写节次，或开始和结束时间。", "error"); return; }
  let weeks;
  try { weeks = parseWeeks($("#course-edit-weeks").value); }
  catch (error) { toast(error.message, "error"); return; }
  const payload = {
    course_name: $("#course-edit-name").value.trim(), weekday: Number($("#course-edit-weekday").value),
    weeks, week_parity: $("#course-edit-parity").value,
    location: $("#course-edit-location").value, teacher: $("#course-edit-teacher").value,
    notes: $("#course-edit-notes").value,
  };
  if (startPeriod) Object.assign(payload, { start_period: startPeriod, end_period: endPeriod });
  if (startTime) Object.assign(payload, { start_time: startTime, end_time: endTime });
  try {
    const result = await api(id ? `/api/v1/courses/${id}` : "/api/v1/courses", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(id ? payload : { ...payload, term_id: Number($("#course-edit-term").value) }),
    });
    toast(id ? `已更新「${result.course_name}」` : `已添加「${result.course_name}」`);
    closeDrawer();
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

async function deleteCourse(courseId) {
  try {
    const course = await api(`/api/v1/courses/${courseId}`);
    if (!window.confirm(`确认删除整门课程「${course.course_name}」？这会删除它在整个学期的排课。`)) return;
    await api(`/api/v1/courses/${courseId}?confirm=true`, { method: "DELETE" });
    toast(`已删除「${course.course_name}」`);
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

function openCourseOccurrenceEditor(courseId, occurrenceDate) {
  const course = (appState.courses || []).find((item) => item.id === courseId && item.date === occurrenceDate);
  if (!course) { toast("没找到这一天的课程记录，请刷新课表。", "error"); return; }
  $("#occurrence-course-id").value = courseId;
  $("#occurrence-date").value = occurrenceDate;
  $("#course-occurrence-caption").textContent = `只调整「${course.course_name}」在 ${occurrenceDate} 的本次安排。`;
  $("#occurrence-start-period").value = course.start_period || "";
  $("#occurrence-end-period").value = course.end_period || "";
  $("#occurrence-start-time").value = course.start_time || "";
  $("#occurrence-end-time").value = course.end_time || "";
  $("#occurrence-location").value = course.location || "";
  $("#occurrence-teacher").value = course.teacher || "";
  $("#occurrence-notes").value = course.notes || "";
  openDrawer("course-occurrence-editor", "调整本次课程");
}

async function submitCourseOccurrence(event) {
  event.preventDefault();
  const id = $("#occurrence-course-id").value;
  const day = $("#occurrence-date").value;
  const startPeriod = Number($("#occurrence-start-period").value || 0);
  const endPeriod = Number($("#occurrence-end-period").value || 0);
  const startTime = $("#occurrence-start-time").value;
  const endTime = $("#occurrence-end-time").value;
  if (Boolean(startPeriod) !== Boolean(endPeriod) || Boolean(startTime) !== Boolean(endTime)) { toast("开始和结束节次或时间需要成对提供。", "error"); return; }
  const payload = { action: "override", location: $("#occurrence-location").value, teacher: $("#occurrence-teacher").value, notes: $("#occurrence-notes").value };
  if (startPeriod) Object.assign(payload, { start_period: startPeriod, end_period: endPeriod });
  else if (startTime) Object.assign(payload, { start_time: startTime, end_time: endTime });
  else { toast("请提供调整后的节次，或开始和结束时间。", "error"); return; }
  try { await api(`/api/v1/courses/${id}/occurrences/${day}`, { method: "PUT", body: JSON.stringify(payload) }); toast("本次课表调整已保存。🗓️"); closeDrawer(); await loadSchedule(); }
  catch (error) { toast(error.message, "error"); }
}

async function cancelCourseOccurrence() {
  const id = $("#occurrence-course-id").value;
  const day = $("#occurrence-date").value;
  if (!window.confirm(`确认只取消课程 #${id} 在 ${day} 这一次上课？`)) return;
  try { await api(`/api/v1/courses/${id}/occurrences/${day}`, { method: "PUT", body: JSON.stringify({ action: "cancelled" }) }); toast("这次课程已标记为停课。" ); closeDrawer(); await loadSchedule(); }
  catch (error) { toast(error.message, "error"); }
}

async function restoreCourseOccurrence(courseId, day) {
  if (!window.confirm(`恢复课程 #${courseId} 在 ${day} 的原安排？`)) return;
  try { await api(`/api/v1/courses/${courseId}/occurrences/${day}`, { method: "DELETE" }); toast("已恢复这一天的原课表。"); await loadSchedule(); }
  catch (error) { toast(error.message, "error"); }
}

function resetScheduleEventForm(close = true) {
  $("#schedule-event-form").reset();
  $("#schedule-event-id").value = "";
  $("#schedule-event-frequency").value = "once";
  $("#schedule-event-date-wrap").hidden = false;
  $("#schedule-event-weekly").hidden = true;
  $("#schedule-event-date").required = true;
  $("#schedule-event-start-date").required = false;
  $("#schedule-event-cancel").hidden = true;
  $("#schedule-event-weekly").querySelector(".legacy-unbounded-note")?.remove();
  appState.editingScheduleEvent = null;
  if (close) closeDrawer();
}

function editScheduleEvent(id, days) {
  const event = days.flatMap((day) => day.events).find((item) => item.id === id);
  if (!event) return;
  appState.editingScheduleEvent = event;
  $("#schedule-event-id").value = String(id);
  $("#schedule-event-title").value = event.title;
  $("#schedule-event-notes").value = event.notes || "";
  $("#schedule-event-frequency").value = event.frequency;
  $("#schedule-event-date").value = event.event_date || event.date;
  $("#schedule-event-start-date").value = event.start_date || "";
  $("#schedule-event-end-date").value = event.end_date || "";
  const legacyNote = $("#schedule-event-weekly").querySelector(".legacy-unbounded-note");
  if (legacyNote) legacyNote.remove();
  if (event.legacy_unbounded) {
    const note = document.createElement("small"); note.className = "legacy-unbounded-note"; note.textContent = "这是旧的无限重复安排；修改重复规则前请先设置停止日期。";
    $("#schedule-event-weekly").prepend(note);
  }
  $("#schedule-event-start-period").value = event.start_period || "";
  $("#schedule-event-end-period").value = event.end_period || "";
  $("#schedule-event-weekdays").querySelectorAll("input").forEach((input) => { input.checked = (event.weekdays || []).includes(Number(input.value)); });
  $("#schedule-event-date-wrap").hidden = event.frequency === "weekly";
  $("#schedule-event-weekly").hidden = event.frequency !== "weekly";
  $("#schedule-event-date").required = event.frequency !== "weekly";
  $("#schedule-event-start-date").required = event.frequency === "weekly";
  $("#schedule-event-cancel").hidden = false;
  openDrawer("schedule-event-editor", "编辑个人安排");
}

async function submitScheduleEvent(event) {
  event.preventDefault();
  const id = $("#schedule-event-id").value;
  const frequency = $("#schedule-event-frequency").value;
  const startPeriod = Number($("#schedule-event-start-period").value);
  const endPeriod = Number($("#schedule-event-end-period").value);
  if (!startPeriod || !endPeriod || endPeriod < startPeriod) { toast("请选择有效的开始和结束节次。", "error"); return; }
  const payload = { title: $("#schedule-event-title").value.trim(), notes: $("#schedule-event-notes").value, frequency, start_period: startPeriod, end_period: endPeriod };
  if (frequency === "weekly") {
    const weekdays = [...$("#schedule-event-weekdays").querySelectorAll("input:checked")].map((input) => Number(input.value));
    if (!weekdays.length || !$("#schedule-event-start-date").value) { toast("每周安排需要开始日期和至少一个星期。", "error"); return; }
    const endDate = $("#schedule-event-end-date").value;
    const current = appState.editingScheduleEvent;
    const sameWeekdays = JSON.stringify([...weekdays].sort()) === JSON.stringify([...(current?.weekdays || [])].sort());
    const ruleChanged = !id || !current || current.frequency !== "weekly" || current.start_date !== $("#schedule-event-start-date").value ||
      current.end_date !== (endDate || null) || !sameWeekdays;
    if (ruleChanged && !endDate) { toast("新建或修改每周安排时需要设置停止日期。", "error"); return; }
    payload.start_date = $("#schedule-event-start-date").value;
    if (!id || ruleChanged) {
      payload.end_date = endDate;
      payload.weekdays = weekdays;
    }
    if (!id || ruleChanged) payload.start_date = $("#schedule-event-start-date").value;
    else { delete payload.frequency; delete payload.start_date; delete payload.end_date; delete payload.weekdays; }
  } else payload.event_date = $("#schedule-event-date").value;
  try {
    const result = await api(id ? `/api/v1/schedule-events/${id}` : "/api/v1/schedule-events", { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
    toast(result.conflicts?.length ? `安排已保存，有 ${result.conflicts.length} 项时间冲突。` : "个人安排已保存");
    resetScheduleEventForm();
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

async function deleteScheduleEvent(id) {
  if (!window.confirm("确认删除这项个人安排？")) return;
  try { await api(`/api/v1/schedule-events/${id}`, { method: "DELETE" }); toast("个人安排已删除"); await loadSchedule(); }
  catch (error) { toast(error.message, "error"); }
}

const courseFields = [
  ["course_name", "课程名称（必填）", true], ["weekday", "星期（必填）", true],
  ["start_period", "开始节次", false], ["end_period", "结束节次", false],
  ["start_time", "开始时间", false], ["end_time", "结束时间", false],
  ["weeks", "周次", false], ["week_parity", "单双周", false],
  ["location", "地点", false], ["teacher", "教师", false], ["notes", "备注", false],
];

function drawMapping(headers, suggested = {}) {
  const node = $("#course-mapping");
  node.innerHTML = courseFields.map(([field, label, required]) => `<label>${label}<select data-course-field="${field}"><option value="">${required ? "选择列（必填）" : "不导入"}</option>${headers.map((header) => `<option value="${escapeHtml(header)}" ${suggested[field] === header ? "selected" : ""}>${escapeHtml(header)}</option>`).join("")}</select></label>`).join("");
}

async function previewCourseImport() {
  const file = $("#course-file").files[0];
  if (!file) { toast("请先选择 .xlsx 文件。", "error"); return; }
  const form = new FormData();
  form.append("file", file);
  form.append("sheet_name", $("#course-sheet").value);
  form.append("header_row", $("#course-header-row").value || "1");
  try {
    let result = await api("/api/v1/courses/import/preview", { method: "POST", body: form });
    const sheet = $("#course-sheet");
    const current = sheet.value;
    sheet.innerHTML = result.sheets.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
    sheet.disabled = false;
    if (result.sheets.includes(current)) sheet.value = current;
    else sheet.value = result.sheet_name;
    if (result.needs_mapping) {
      drawMapping(result.headers, result.suggested_mapping);
      const mapping = {};
      nodeMapping().forEach((select) => { if (select.value) mapping[select.dataset.courseField] = select.value; });
      if (mapping.course_name && mapping.weekday) {
      const parseForm = new FormData();
      parseForm.append("file", file);
      parseForm.append("sheet_name", sheet.value);
      parseForm.append("header_row", $("#course-header-row").value || "1");
      parseForm.append("mapping", JSON.stringify(mapping));
      result = await api("/api/v1/courses/import/preview", { method: "POST", body: parseForm });
      } else {
        appState.previewCourses = [];
        $("#course-preview-result").hidden = false;
        $("#course-preview-result").innerHTML = `<strong>请映射课程名称和星期列</strong><p>表头：${result.headers.map(escapeHtml).join("、")}</p>`;
        $("#course-commit").disabled = true;
        return;
      }
    } else {
      $("#course-mapping").innerHTML = "";
    }
    appState.previewCourses = result.courses || [];
    const errors = (result.errors || []).map((entry) => `第 ${entry.row} 行${entry.column ? `，第${entry.column}列` : ""}：${entry.error}`).join("；");
    $("#course-preview-result").hidden = false;
    $("#course-preview-result").innerHTML = `<strong>解析到 ${appState.previewCourses.length} 条课程记录${result.format === "weekday_grid" ? "（星期列合并课表）" : ""}</strong><p>${appState.previewCourses.slice(0, 8).map((course) => `${escapeHtml(course.course_name)} · ${escapeHtml(weekdayLabels[course.weekday - 1] || `周${course.weekday}`)} · 第${escapeHtml(course.start_period)}–${escapeHtml(course.end_period)}节 · ${escapeHtml(course.location || "未填地点")}`).join("<br>") || "没有可导入的课程"}</p>${errors ? `<p class="form-error">${escapeHtml(errors)}</p>` : ""}`;
    $("#course-commit").disabled = appState.previewCourses.length === 0 || Boolean((result.errors || []).length);
    $("#replace-term-wrap").hidden = false;
  } catch (error) { toast(error.message, "error"); }
}

function nodeMapping() { return [...document.querySelectorAll("[data-course-field]")]; }

function invalidateCoursePreview() {
  appState.previewCourses = [];
  $("#course-commit").disabled = true;
  $("#course-preview-result").hidden = true;
}

async function commitCourseImport() {
  if (!appState.previewCourses.length) return;
  const body = {
    term_name: $("#term-name").value.trim(),
    week1_monday: $("#term-week1").value,
    end_date: $("#term-end").value,
    courses: appState.previewCourses,
    replace_existing: $("#replace-term").checked,
  };
  if (!body.term_name || !body.week1_monday || !body.end_date) { toast("请填写学期名称、第1周周一和学期结束日期。", "error"); return; }
  if (body.replace_existing && !window.confirm("替换该学期会删除原有课程记录，确认继续？")) return;
  try {
    const result = await api("/api/v1/courses/import/commit", { method: "POST", body: JSON.stringify(body) });
    toast(`课表已导入，共 ${result.course_count} 门课程`);
    appState.previewCourses = [];
    $("#course-commit").disabled = true;
    $("#course-preview-result").hidden = true;
    closeDrawer();
    await loadSchedule();
  } catch (error) { toast(error.message, "error"); }
}

function suggestTermEndDate() {
  const start = $("#term-week1").value;
  if (!start || $("#term-end").dataset.touched === "1") return;
  const value = new Date(`${start}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 125);
  $("#term-end").value = value.toISOString().slice(0, 10);
}

function setSelectedTerm(value) {
  appState.selectedTermId = value || null;
  if (value) {
    const term = appState.terms?.find((item) => String(item.id) === String(value));
    if (term) $("#schedule-date").value = term.week1_monday;
  } else {
    $("#schedule-date").value = localToday();
  }
  loadSchedule();
}

export { fillPeriodSelects, periodForClock, loadSchedule, toggleCourseAlert, openNewScheduleEvent, resetScheduleEventForm, editScheduleEvent, submitScheduleEvent, deleteScheduleEvent, previewCourseImport, invalidateCoursePreview, commitCourseImport, shiftSchedule, openCourseEditor, submitCourse, saveTermEndDate, setSelectedTerm, suggestTermEndDate, submitCourseOccurrence, cancelCourseOccurrence };
