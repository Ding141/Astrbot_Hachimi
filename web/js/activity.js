import { $, api, escapeHtml, toast, localDateTime } from "./core.js";

async function loadAudit() {
  try {
    const result = await api("/api/v1/audit?limit=100");
    $("#audit-rows").innerHTML = result.items.map((entry) => `<tr><td>${escapeHtml(localDateTime(entry.created_at))}</td><td>${escapeHtml(entry.actor)}</td><td>${escapeHtml(entry.resource)} #${escapeHtml(entry.resource_id)}</td><td><span class="tag">${escapeHtml(entry.action)}</span></td><td class="subtle">${escapeHtml(entry.after_json || "—")}</td></tr>`).join("");
  } catch (error) { toast(error.message, "error"); }
}

export { loadAudit };
