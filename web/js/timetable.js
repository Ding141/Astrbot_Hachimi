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

async function loadSchedule() {
  const anchor = $("#schedule-date").value || localToday();
  appState.scheduleAnchor = anchor;
  try {
    const result = await api(`/api/v1/courses/week?week_start=${encodeURIComponent(anchor)}`);
    const dayMode = $("#schedule-view-mode").value === "day";
    const shownDays = dayMode ? result.days.filter((day) => day.date === anchor) : result.days;
    $("#schedule-caption").innerHTML = `<span>${escapeHtml(result.week_start)} 至 ${escapeHtml(result.week_end)}</span><strong>${escapeHtml(result.term || "未导入学期")}${result.week ? ` · 第 ${result.week} 周` : ""}</strong>`;
    const grid = $("#schedule-grid");
    grid.classList.toggle("day-mode", dayMode);
    const columns = shownDays.length || 1;
    const header = shownDays.map((day) => `<div class="timetable-date-head ${day.date === localToday() ? "is-today" : ""}"><strong>${escapeHtml(weekdayLabels[(new Date(`${day.date}T12:00:00`).getDay() + 6) % 7])}</strong><span>${escapeHtml(day.date.slice(5))}</span>${day.week ? `<small>第 ${day.week} 周</small>` : ""}</div>`).join("");
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
        return `<article class="timetable-entry course-entry" style="grid-column:${item.lane + 1};grid-row:${start}/${end + 1}"><div class="entry-time">第${start}–${end}节 · ${range}</div><strong>${escapeHtml(item.course_name)}</strong><small>${[item.location && `地点 ${item.location}`, item.teacher && `老师 ${item.teacher}`].filter(Boolean).map(escapeHtml).join(" · ") || "未填写地点和教师"}</small><button class="course-alert ${item.reminder_enabled ? "enabled" : ""}" type="button" title="${item.reminder_enabled ? "关闭课前提醒" : "开启课前提醒"}" aria-label="${item.reminder_enabled ? "关闭课前提醒" : "开启课前提醒"}" data-id="${item.id}" data-enabled="${item.reminder_enabled ? "1" : "0"}" data-lead="${item.reminder_lead_minutes || 10}">${item.reminder_enabled ? `🔔 ${item.reminder_lead_minutes || 10}分` : "＋ 提醒"}</button></article>`;
      }).join("");
      return `<section class="timetable-day-track" style="--lanes:${laneCount}">${emptySlots.join("")}${cards}</section>`;
    }).join("");
    const axis = PERIOD_TIMES.map(([start, end], index) => `<div class="period-label ${[5, 10].includes(index + 1) ? "session-break" : ""}"><strong>第${index + 1}节</strong><span>${start}</span><small>${end}</small></div>`).join("");
    grid.style.setProperty("--day-count", String(columns));
    grid.innerHTML = `<div class="timetable-head"><div class="period-head">节次</div>${header}</div><div class="timetable-body"><div class="period-axis">${axis}</div>${tracks}</div>`;
    grid.querySelectorAll(".course-alert").forEach((button) => button.addEventListener("click", () => toggleCourseAlert(button.dataset.id, button.dataset.enabled === "1", Number(button.dataset.lead))));
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

function resetScheduleEventForm(close = true) {
  $("#schedule-event-form").reset();
  $("#schedule-event-id").value = "";
  $("#schedule-event-frequency").value = "once";
  $("#schedule-event-date-wrap").hidden = false;
  $("#schedule-event-weekly").hidden = true;
  $("#schedule-event-date").required = true;
  $("#schedule-event-start-date").required = false;
  $("#schedule-event-cancel").hidden = true;
  if (close) closeDrawer();
}

function editScheduleEvent(id, days) {
  const event = days.flatMap((day) => day.events).find((item) => item.id === id);
  if (!event) return;
  $("#schedule-event-id").value = String(id);
  $("#schedule-event-title").value = event.title;
  $("#schedule-event-notes").value = event.notes || "";
  $("#schedule-event-frequency").value = event.frequency;
  $("#schedule-event-date").value = event.event_date || event.date;
  $("#schedule-event-start-date").value = event.start_date || "";
  $("#schedule-event-end-date").value = event.end_date || "";
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
    payload.start_date = $("#schedule-event-start-date").value;
    payload.end_date = $("#schedule-event-end-date").value || null;
    payload.weekdays = weekdays;
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
    courses: appState.previewCourses,
    replace_existing: $("#replace-term").checked,
  };
  if (!body.term_name || !body.week1_monday) { toast("请填写学期名称和第 1 周周一。", "error"); return; }
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

export { fillPeriodSelects, periodForClock, loadSchedule, toggleCourseAlert, openNewScheduleEvent, resetScheduleEventForm, editScheduleEvent, submitScheduleEvent, deleteScheduleEvent, previewCourseImport, invalidateCoursePreview, commitCourseImport, shiftSchedule };
