// static/app.js
const $ = (selector) => document.querySelector(selector);

function esc(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function money(num) {
  return Number(num || 0).toLocaleString("th-TH", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const parts = isoStr.split("T")[0].split("-");
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return isoStr;
  } catch (e) {
    return isoStr;
  }
}

function statusOf(record) {
  if (record.return_date) {
    return { cls: "returned", label: "คืนแล้ว" };
  }
  if (record.is_overdue || Number(record.fine_amount) > 0) {
    return { cls: "overdue", label: "เลยกำหนด" };
  }
  return { cls: "borrowing", label: "กำลังยืม" };
}

function showMessage(type, text, opts = {}) {
  const area = $("#flash-area");
  if (!area) return;
  if (opts.clear) area.innerHTML = "";
  const box = document.createElement("div");
  box.className = `flash ${type}`;
  box.textContent = text;
  area.appendChild(box);
}

async function api(path, options = {}) {
  const baseUrl = typeof API_BASE_URL !== "undefined" ? API_BASE_URL : "";
  const url = path.startsWith("http") ? path : `${baseUrl}${path}`;
  try {
    const res = await fetch(url, options);
    const contentType = res.headers.get("content-type");
    let data;
    if (contentType && contentType.includes("application/json")) {
      data = await res.json();
    } else {
      const text = await res.text();
      data = { message: text };
    }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: { message: "ไม่สามารถเชื่อมต่อ Backend ได้: " + err.message },
    };
  }
}