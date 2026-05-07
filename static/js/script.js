const appState = {
  registerStream: null,
  attendanceStream: null,
  attendanceTimer: null,
  attendanceBusy: false,
  attendanceRunning: false,
  attendanceMarked: {},
  editingStudentId: null,
  captures: []
};

const MIN_FACE_CAPTURES = 3;
const MAX_FACE_CAPTURES = 12;
const COURSE_OPTIONS = ["BSIT-NT 3201", "BSIT-NT 3202"];
const HAAR_FACE_BOX_SCALE_X = 2.2;
const HAAR_FACE_BOX_SCALE_Y = 2.8;
const HAAR_FACE_BOX_Y_OFFSET = -0.65;

const ui = {
  emptyState: "empty-state",
  emptyStateSmall: "empty-state-sm",
  activityItem: "activity-card",
  activityTitle: "activity-title",
  activityDetail: "activity-detail",
  tableCell: "table-td",
  tableCellMuted: "table-td-muted",
  captureThumb: "capture-thumb",
  captureNumber: "capture-number"
};

function $(selector) {
  return document.querySelector(selector);
}

function todayIsoDate() {
  const now = new Date();
  const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers
  });
  const contentType = response.headers.get("Content-Type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;

  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Authentication required.");
  }
  if (!response.ok || (payload && payload.ok === false)) {
    throw new Error(payload?.message || "Request failed.");
  }
  return payload;
}

function setMessage(element, message, type = "") {
  if (!element) return;
  element.textContent = message;
  element.classList.remove("text-muted", "message-success", "message-error", "message-warning");
  element.classList.add(messageClass(type));
}

function messageClass(type) {
  if (type === "success") return "message-success";
  if (type === "error") return "message-error";
  if (type === "warning") return "message-warning";
  return "text-muted";
}

function badgeClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized.includes("present")) return "badge badge-success";
  if (normalized.includes("already") || normalized === "active") return "badge badge-info";
  if (normalized.includes("unknown")) return "badge badge-warning";
  return "badge badge-danger";
}

function systemPillClass(status) {
  const ready = status === "Ready";
  return `status-pill ${ready ? "badge-success" : "badge-warning"}`;
}

function hideCameraFallback(fallback) {
  if (!fallback) return;
  fallback.hidden = true;
  fallback.setAttribute("aria-hidden", "true");
}

function showCameraFallback(fallback, message) {
  if (!fallback) return;
  fallback.textContent = message || "Camera unavailable";
  fallback.hidden = false;
  fallback.setAttribute("aria-hidden", "false");
}

function clearFaceBox() {
  const box = $("#attendanceFaceBox");
  if (!box) return;
  box.hidden = true;
}

function drawFaceBox(detection, label = "Detected face") {
  const box = $("#attendanceFaceBox");
  const labelNode = $("#attendanceFaceBoxLabel");
  if (!box || !detection?.box || !detection?.image_size) {
    clearFaceBox();
    return;
  }

  const { x1, y1, x2, y2 } = detection.box;
  const { width, height } = detection.image_size;
  if (!width || !height || x2 <= x1 || y2 <= y1) {
    clearFaceBox();
    return;
  }

  const rawWidth = x2 - x1;
  const rawHeight = y2 - y1;

  const centerX = x1 + rawWidth / 2;
  const centerY = y1 + rawHeight / 2 + rawHeight * HAAR_FACE_BOX_Y_OFFSET;
  const expandedWidth = rawWidth * HAAR_FACE_BOX_SCALE_X;
  const expandedHeight = rawHeight * HAAR_FACE_BOX_SCALE_Y;
  const visualX1 = Math.max(0, centerX - expandedWidth / 2);
  const visualY1 = Math.max(0, centerY - expandedHeight / 2);
  const visualX2 = Math.min(width, centerX + expandedWidth / 2);
  const visualY2 = Math.min(height, centerY + expandedHeight / 2);

  const left = ((width - visualX2) / width) * 100;
  const top = (visualY1 / height) * 100;
  const boxWidth = ((visualX2 - visualX1) / width) * 100;
  const boxHeight = ((visualY2 - visualY1) / height) * 100;

  box.style.left = `${left}%`;
  box.style.top = `${top}%`;
  box.style.width = `${boxWidth}%`;
  box.style.height = `${boxHeight}%`;
  if (labelNode) {
    labelNode.textContent = label;
  }
  box.hidden = false;
}

async function startCamera(video, fallback) {
  if (!video) return null;
  hideCameraFallback(fallback);
  if (!navigator.mediaDevices?.getUserMedia) {
    showCameraFallback(fallback, "Camera access is not supported by this browser.");
    throw new Error("Camera access is not supported by this browser.");
  }
  if (video.srcObject) {
    return video.srcObject;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        width: { ideal: 960 },
        height: { ideal: 720 },
        facingMode: "user"
      }
    });
    video.srcObject = stream;
    await video.play();
    hideCameraFallback(fallback);
    return stream;
  } catch (error) {
    const message = getCameraErrorMessage(error);
    showCameraFallback(fallback, message);
    throw new Error(message);
  }
}

function getCameraErrorMessage(error) {
  const name = error?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Camera permission was blocked.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No camera device was found.";
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return "Camera is already in use by another app.";
  }
  return error?.message || "Camera unavailable.";
}

function stopCamera(stream, video) {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
  }
  if (video) {
    video.srcObject = null;
  }
}

function captureFrame(video, canvas) {
  if (!video?.videoWidth || !video?.videoHeight) {
    throw new Error("Camera is not ready yet.");
  }
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d", { willReadFrequently: false });
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.88);
}

function setupLogin() {
  const form = $("#loginForm");
  const message = $("#loginMessage");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    setMessage(message, "Signing in...");

    try {
      const payload = {
        email: form.elements.email.value.trim(),
        password: form.elements.password.value
      };
      const result = await apiFetch("/login", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      window.location.href = result.redirect || "/dashboard";
    } catch (error) {
      setMessage(message, error.message, "error");
      button.disabled = false;
    }
  });
}

function setupDashboard() {
  const dateInput = $("#dashboardDate");
  if (!dateInput) return;
  dateInput.value = dateInput.value || todayIsoDate();
  dateInput.addEventListener("change", () => loadDashboard());
}

async function loadDashboard() {
  if (!$("#totalStudents")) return;
  const dateInput = $("#dashboardDate");
  const selectedDate = dateInput?.value || todayIsoDate();

  try {
    const params = new URLSearchParams();
    params.set("date", selectedDate);
    const payload = await apiFetch(`/api/dashboard?${params.toString()}`);
    $("#totalStudents").textContent = payload.stats.total_students;
    $("#attendanceToday").textContent = payload.stats.attendance_today;
    $("#modelStatus").textContent = payload.stats.model_trained ? "Trained" : "Not trained";
    const dateLabel = $("#attendanceDateLabel");
    if (dateLabel) dateLabel.textContent = `Students marked present on ${payload.stats.attendance_date}`;
    const activityLabel = $("#recentActivityLabel");
    if (activityLabel) activityLabel.textContent = `Attendance records for ${payload.stats.attendance_date}`;

    const status = $("#systemStatus");
    status.textContent = payload.stats.system_status;
    status.className = systemPillClass(payload.stats.system_status);

    renderRecentActivity(payload.recent_activity);
  } catch (error) {
    const status = $("#systemStatus");
    status.textContent = error.message;
    status.className = systemPillClass("Needs setup");
  }
}

function renderRecentActivity(records) {
  const activityList = $("#recentActivity");
  if (!activityList) return;
  if (!records?.length) {
    activityList.innerHTML = `<div class="${ui.emptyState}">No attendance records found for this date.</div>`;
    return;
  }

  activityList.innerHTML = records
    .map((record) => `
      <div class="${ui.activityItem}">
        <div>
          <strong class="${ui.activityTitle}">${escapeHtml(record.name)}</strong>
          <span class="${ui.activityDetail}">${escapeHtml(record.student_id)} marked present at ${escapeHtml(record.time)}</span>
        </div>
        <span class="${badgeClass(record.status)}">${escapeHtml(record.status)}</span>
      </div>
    `)
    .join("");
}

async function setupRegisterUser() {
  const video = $("#registerVideo");
  const canvas = $("#registerCanvas");
  const captureButton = $("#captureFace");
  const clearButton = $("#clearCaptures");
  const form = $("#registerForm");
  const message = $("#registerMessage");
  const fallback = $("#registerCameraFallback");
  if (!video || !canvas || !form) return;

  try {
    appState.registerStream = await startCamera(video, fallback);
    setMessage(message, "Capture at least 3 face samples.");
  } catch (error) {
    setMessage(message, error.message, "error");
  }

  captureButton?.addEventListener("click", async () => {
    try {
      if (!appState.registerStream) {
        appState.registerStream = await startCamera(video, fallback);
      }
      if (appState.captures.length >= MAX_FACE_CAPTURES) {
        setMessage(message, `Maximum of ${MAX_FACE_CAPTURES} captures reached.`, "warning");
        return;
      }
      appState.captures.push(captureFrame(video, canvas));
      renderCaptures();
      setMessage(message, `${appState.captures.length} face sample${appState.captures.length === 1 ? "" : "s"} captured.`);
    } catch (error) {
      setMessage(message, error.message, "error");
    }
  });

  clearButton?.addEventListener("click", () => {
    appState.captures = [];
    renderCaptures();
    setMessage(message, "Captures cleared.");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (appState.captures.length < MIN_FACE_CAPTURES) {
      setMessage(message, `Capture at least ${MIN_FACE_CAPTURES} face samples before saving.`, "error");
      return;
    }

    const submitButton = form.querySelector("button[type='submit']");
    submitButton.disabled = true;
    setMessage(message, "Saving student and training recognition model...");

    try {
      const payload = {
        full_name: form.elements.name.value.trim(),
        course: form.elements.course.value.trim(),
        face_images: appState.captures
      };
      const result = await apiFetch("/api/students", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      form.reset();
      appState.captures = [];
      renderCaptures();
      setMessage(message, result.message, "success");
      await loadStudents();
      await loadNextStudentId();
    } catch (error) {
      setMessage(message, error.message, "error");
    } finally {
      submitButton.disabled = false;
    }
  });

  $("#studentsTable")?.addEventListener("click", handleStudentAction);

  renderCaptures();
  await loadNextStudentId();
  await loadStudents();
}

async function loadNextStudentId() {
  const studentIdInput = $("#studentId");
  if (!studentIdInput) return;

  try {
    const payload = await apiFetch("/api/students/next-id");
    studentIdInput.value = payload.student_id;
  } catch (_error) {
    studentIdInput.value = "";
  }
}

function renderCaptures() {
  const captureList = $("#captureList");
  const captureCount = $("#captureCount");
  if (captureCount) {
    captureCount.textContent = `${appState.captures.length} of ${MIN_FACE_CAPTURES} captures ready.`;
  }
  if (!captureList) return;

  if (!appState.captures.length) {
    captureList.innerHTML = `<div class="${ui.emptyStateSmall}">No captures yet.</div>`;
    return;
  }

  captureList.innerHTML = appState.captures
    .map((capture, index) => `
      <button class="${ui.captureThumb}" type="button" data-index="${index}" aria-label="Remove capture ${index + 1}">
        <img class="h-full w-full object-cover" src="${capture}" alt="">
        <span class="${ui.captureNumber}">${index + 1}</span>
      </button>
    `)
    .join("");

  captureList.querySelectorAll("[data-index]").forEach((button) => {
    button.addEventListener("click", () => {
      appState.captures.splice(Number(button.dataset.index), 1);
      renderCaptures();
    });
  });
}

async function loadStudents() {
  const table = $("#studentsTable");
  if (!table) return;

  try {
    const payload = await apiFetch("/api/students");
    if (!payload.students.length) {
      table.innerHTML = `<tr><td class="${ui.tableCellMuted}" colspan="6">No students registered yet.</td></tr>`;
      return;
    }
    table.innerHTML = payload.students
      .map((student) => renderStudentRow(student))
      .join("");
  } catch (error) {
    table.innerHTML = `<tr><td class="${ui.tableCellMuted}" colspan="6">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderStudentRow(student) {
  const isEditing = appState.editingStudentId === Number(student.id);
  if (isEditing) {
    return `
      <tr>
        <td class="${ui.tableCell}">
          <input class="form-input w-full min-w-64" id="editName-${student.id}" type="text" maxlength="100" value="${escapeHtml(student.full_name)}">
        </td>
        <td class="${ui.tableCell}">${escapeHtml(student.student_number)}</td>
        <td class="${ui.tableCell}">
          <select class="form-input w-full min-w-64" id="editCourse-${student.id}">
            ${COURSE_OPTIONS.map((course) => `<option value="${course}" ${course === student.course ? "selected" : ""}>${course}</option>`).join("")}
          </select>
        </td>
        <td class="${ui.tableCell}">${student.sample_count}</td>
        <td class="${ui.tableCell}"><span class="${badgeClass(student.is_active ? "Active" : "Inactive")}">${student.is_active ? "Active" : "Inactive"}</span></td>
        <td class="${ui.tableCell}">
          <div class="flex flex-col gap-2 sm:flex-row">
            <button class="btn btn-primary" type="button" data-action="save" data-id="${student.id}">Save</button>
            <button class="btn btn-secondary" type="button" data-action="cancel" data-id="${student.id}">Cancel</button>
          </div>
        </td>
      </tr>
    `;
  }

  return `
    <tr>
      <td class="${ui.tableCell} font-semibold text-strong">${escapeHtml(student.full_name)}</td>
      <td class="${ui.tableCell}">${escapeHtml(student.student_number)}</td>
      <td class="${ui.tableCell}">${escapeHtml(student.course)}</td>
      <td class="${ui.tableCell}">${student.sample_count}</td>
      <td class="${ui.tableCell}"><span class="${badgeClass(student.is_active ? "Active" : "Inactive")}">${student.is_active ? "Active" : "Inactive"}</span></td>
      <td class="${ui.tableCell}">
        <div class="flex flex-col gap-2 sm:flex-row">
          <button class="btn btn-secondary" type="button" data-action="edit" data-id="${student.id}">Edit</button>
          <button class="btn btn-secondary" type="button" data-action="delete" data-id="${student.id}" data-name="${escapeHtml(student.full_name)}">Delete</button>
        </div>
      </td>
    </tr>
  `;
}

async function handleStudentAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;

  const action = button.dataset.action;
  const studentId = Number(button.dataset.id);
  const message = $("#studentsMessage");

  if (action === "edit") {
    appState.editingStudentId = studentId;
    await loadStudents();
    return;
  }

  if (action === "cancel") {
    appState.editingStudentId = null;
    await loadStudents();
    setMessage(message, "");
    return;
  }

  if (action === "save") {
    const nameInput = $(`#editName-${studentId}`);
    const courseInput = $(`#editCourse-${studentId}`);
    button.disabled = true;
    setMessage(message, "Updating student...");
    try {
      const result = await apiFetch(`/api/students/${studentId}`, {
        method: "PATCH",
        body: JSON.stringify({
          full_name: nameInput?.value.trim(),
          course: courseInput?.value
        })
      });
      appState.editingStudentId = null;
      setMessage(message, result.message, "success");
      await loadStudents();
      await loadDashboard();
    } catch (error) {
      setMessage(message, error.message, "error");
      button.disabled = false;
    }
    return;
  }

  if (action === "delete") {
    const studentName = button.dataset.name || "this student";
    if (!window.confirm(`Delete ${studentName}? This also removes the student's face samples and attendance records.`)) {
      return;
    }
    button.disabled = true;
    setMessage(message, "Deleting student and updating recognition model...");
    try {
      const result = await apiFetch(`/api/students/${studentId}`, {
        method: "DELETE"
      });
      appState.editingStudentId = null;
      setMessage(message, result.message, "success");
      await loadStudents();
      await loadNextStudentId();
      await loadDashboard();
    } catch (error) {
      setMessage(message, error.message, "error");
      button.disabled = false;
    }
  }
}

function setupAttendance() {
  const startButton = $("#startAttendance");
  const statusText = $("#attendanceStatus");
  const video = $("#attendanceVideo");
  const canvas = $("#attendanceCanvas");
  const fallback = $("#attendanceCameraFallback");
  const log = $("#attendanceLog");
  if (!startButton || !statusText || !video || !canvas || !log) return;

  startButton.addEventListener("click", async () => {
    if (appState.attendanceRunning) {
      stopAttendance();
      return;
    }

    startButton.disabled = true;
    statusText.textContent = "Starting camera...";
    try {
      appState.attendanceStream = await startCamera(video, fallback);
      appState.attendanceRunning = true;
      appState.attendanceMarked = {};
      startButton.textContent = "Stop Attendance";
      startButton.disabled = false;
      statusText.textContent = "Scanning for faces...";
      await runAttendanceCheck();
      appState.attendanceTimer = window.setInterval(runAttendanceCheck, 3000);
    } catch (error) {
      statusText.textContent = error.message;
      startButton.disabled = false;
    }
  });
}

function stopAttendance() {
  const startButton = $("#startAttendance");
  const statusText = $("#attendanceStatus");
  const video = $("#attendanceVideo");
  const fallback = $("#attendanceCameraFallback");
  window.clearInterval(appState.attendanceTimer);
  appState.attendanceTimer = null;
  appState.attendanceRunning = false;
  appState.attendanceBusy = false;
  stopCamera(appState.attendanceStream, video);
  appState.attendanceStream = null;
  hideCameraFallback(fallback);
  clearFaceBox();
  if (startButton) startButton.textContent = "Start Attendance";
  if (statusText) statusText.textContent = "Attendance stopped.";
}

async function runAttendanceCheck() {
  if (appState.attendanceBusy || !appState.attendanceRunning) return;
  const video = $("#attendanceVideo");
  const canvas = $("#attendanceCanvas");
  const statusText = $("#attendanceStatus");
  appState.attendanceBusy = true;

  try {
    const image = captureFrame(video, canvas);
    const result = await apiFetch("/api/attendance/recognize", {
      method: "POST",
      body: JSON.stringify({ image })
    });

    if (result.matched) {
      const name = result.student.full_name;
      const faceLabel = `${result.student.student_id} - ${name}`;
      const attendanceKey = `${result.student.student_id}:${result.attendance?.date || ""}`;
      const alreadyShown = result.status === "Already marked" && appState.attendanceMarked[attendanceKey];
      statusText.textContent = `${result.status}: ${name}`;
      drawFaceBox(result.detection, faceLabel);
      if (!alreadyShown) {
        addAttendanceLog({
          title: name,
          detail: `${result.student.student_id} - ${result.message}`,
          badge: result.status,
          confidence: result.attendance?.confidence
        });
      }
      if (result.status === "Present" || result.status === "Already marked") {
        appState.attendanceMarked[attendanceKey] = true;
      }
      if (result.status === "Present") {
        await loadDashboard();
      }
    } else {
      statusText.textContent = result.message;
      drawFaceBox(result.detection, "Unknown face");
      addAttendanceLog({
        title: "Unknown face",
        detail: `Confidence ${result.confidence} / threshold ${result.threshold}`,
        badge: result.status
      });
    }
  } catch (error) {
    statusText.textContent = error.message;
    clearFaceBox();
    addAttendanceLog({
      title: "Detection error",
      detail: error.message,
      badge: "Error"
    });
  } finally {
    appState.attendanceBusy = false;
  }
}

function addAttendanceLog(entry) {
  const log = $("#attendanceLog");
  if (!log) return;
  if (log.children.length === 1 && log.textContent.includes("No detection attempts yet.")) {
    log.innerHTML = "";
  }
  const item = document.createElement("div");
  item.className = ui.activityItem;
  const confidence = Number.isFinite(entry.confidence) ? ` · confidence ${entry.confidence}` : "";
  item.innerHTML = `
    <div>
      <strong class="${ui.activityTitle}">${escapeHtml(entry.title)}</strong>
      <span class="${ui.activityDetail}">${escapeHtml(entry.detail)}${escapeHtml(confidence)}</span>
    </div>
    <span class="${badgeClass(entry.badge)}">${escapeHtml(entry.badge)}</span>
  `;
  log.prepend(item);
  while (log.children.length > 8) {
    log.lastElementChild.remove();
  }
}

async function loadRecords(search = "", date = "") {
  const tableBody = $("#recordsTable");
  if (!tableBody) return;

  try {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (date) params.set("date", date);
    const payload = await apiFetch(`/api/records?${params.toString()}`);
    renderRecords(payload.records);
  } catch (error) {
    tableBody.innerHTML = `<tr><td class="${ui.tableCellMuted}" colspan="7">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderRecords(records) {
  const tableBody = $("#recordsTable");
  if (!tableBody) return;
  if (!records.length) {
    tableBody.innerHTML = `<tr><td class="${ui.tableCellMuted}" colspan="7">No attendance records found.</td></tr>`;
    return;
  }

  tableBody.innerHTML = records
    .map((record) => `
      <tr>
        <td class="${ui.tableCell} font-semibold text-strong">${escapeHtml(record.name)}</td>
        <td class="${ui.tableCell}">${escapeHtml(record.student_id)}</td>
        <td class="${ui.tableCell}">${escapeHtml(record.course)}</td>
        <td class="${ui.tableCell}">${escapeHtml(record.date)}</td>
        <td class="${ui.tableCell}">${escapeHtml(record.time)}</td>
        <td class="${ui.tableCell}"><span class="${badgeClass(record.status)}">${escapeHtml(record.status)}</span></td>
        <td class="${ui.tableCell}">${escapeHtml(record.confidence)}</td>
      </tr>
    `)
    .join("");
}

function setupRecordsTools() {
  const searchInput = $("#recordSearch");
  const dateInput = $("#recordDate");
  const exportButton = $("#exportCsv");
  const exportMessage = $("#exportMessage");
  if (!searchInput && !dateInput && !exportButton) return;

  const loadFilteredRecords = () => {
    loadRecords(searchInput?.value.trim() || "", dateInput?.value || "");
  };

  let searchTimer = null;
  searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(loadFilteredRecords, 250);
  });

  dateInput?.addEventListener("change", loadFilteredRecords);

  dateInput?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      dateInput.value = "";
      loadFilteredRecords();
    }
  });

  exportButton?.addEventListener("click", () => {
    const params = new URLSearchParams();
    if (searchInput?.value.trim()) params.set("search", searchInput.value.trim());
    if (dateInput?.value) params.set("date", dateInput.value);
    setMessage(exportMessage, "Preparing CSV export...");
    window.location.href = `/api/records/export.csv?${params.toString()}`;
    window.setTimeout(() => setMessage(exportMessage, ""), 2000);
  });

  loadFilteredRecords();
}

window.addEventListener("beforeunload", () => {
  stopCamera(appState.registerStream, $("#registerVideo"));
  stopCamera(appState.attendanceStream, $("#attendanceVideo"));
});

document.addEventListener("DOMContentLoaded", () => {
  setupLogin();
  setupDashboard();
  loadDashboard();
  setupRegisterUser();
  setupAttendance();
  setupRecordsTools();
});
