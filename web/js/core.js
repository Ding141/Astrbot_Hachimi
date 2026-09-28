import { appState } from "./state.js";

export const $ = (selector) => document.querySelector(selector);

function openDrawer(sectionId, title) {
  document.querySelectorAll(".drawer-section").forEach((section) => { section.hidden = section.id !== sectionId; });
  $("#drawer-title").textContent = title;
  $("#drawer-backdrop").hidden = false;
  $("#editor-drawer").hidden = false;
  document.body.classList.add("drawer-open");
  window.setTimeout(() => {
    const focusable = $("#editor-drawer .drawer-section:not([hidden]) input:not([type=hidden]), #editor-drawer .drawer-section:not([hidden]) textarea, #editor-drawer .drawer-section:not([hidden]) select");
    focusable?.focus();
  }, 120);
}

function closeDrawer() {
  const drawer = $("#editor-drawer");
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  $("#drawer-backdrop").hidden = true;
  document.body.classList.remove("drawer-open");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401) showLogin();
    const detail = typeof body === "object" ? body.detail : body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail || response.statusText));
  }
  return body;
}

function toast(message, kind = "success") {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show ${kind}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { node.className = "toast"; }, 3600);
}

function showLogin() {
  closeDrawer();
  $("#application").hidden = true;
  $("#login-screen").hidden = false;
}

function showApplication() {
  $("#login-screen").hidden = true;
  $("#application").hidden = false;
}

function localDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { hour12: false, timeZone: appState.settings?.timezone || "Asia/Shanghai" });
}

function localReminderInput(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  const parts = Object.fromEntries(new Intl.DateTimeFormat("sv-SE", {
    timeZone: appState.settings?.timezone || "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(parsed).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function localDate(value, time) {
  return value ? `${value}${time ? ` ${time}` : ""}` : "未设置时间";
}

function localToday() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: appState.settings?.timezone || "Asia/Shanghai" }).format(new Date());
}

function setView(name) {
  closeDrawer();
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  const labels = { todos: ["TASKS", "待办任务"], reminders: ["PLANNING", "提醒与复盘"], courses: ["TIMETABLE", "课表与日程"], history: ["ACTIVITY", "操作记录"] };
  $("#section-kicker").textContent = labels[name][0];
  $("#section-title").textContent = labels[name][1];
  document.querySelectorAll(".rail-action").forEach((button) => { button.hidden = button.dataset.actionView !== name; });
  $(".action-rail").hidden = !["todos", "courses"].includes(name);
}

async function loadSettings() {
  appState.settings = await api("/api/v1/settings");
  $("#timezone-label").textContent = appState.settings.timezone;
  const status = $("#connection-status");
  status.classList.toggle("online", appState.settings.wechat_bound);
  status.querySelector("span").textContent = appState.settings.wechat_bound ? "微信会话已绑定" : "等待微信连接";
  $("#stat-wechat").textContent = appState.settings.wechat_bound ? "已绑定" : "未连接";
  $("#reminder-timezone").textContent = appState.settings.timezone;
  const schedules = appState.settings.reminder_schedules || {};
  if (schedules.daily_brief_time) $("#daily-brief-time").value = schedules.daily_brief_time;
  if (schedules.daily_brief_enabled !== undefined) $("#daily-brief-enabled").checked = schedules.daily_brief_enabled;
  if (schedules.weekly_review_time) $("#weekly-review-time").value = schedules.weekly_review_time;
  if (schedules.weekly_review_enabled !== undefined) $("#weekly-review-enabled").checked = schedules.weekly_review_enabled;
  if (schedules.weekly_review_weekday) $("#weekly-review-weekday").value = String(schedules.weekly_review_weekday);
}
export { api, escapeHtml, toast, showLogin, showApplication, localDateTime, localReminderInput, localDate, localToday, setView, loadSettings, openDrawer, closeDrawer };
