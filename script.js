const attendanceRecords = [
  { name: "Maria Santos", studentId: "STU-2026-001", date: "2026-05-04", time: "08:02 AM", status: "Present" },
  { name: "John Reyes", studentId: "STU-2026-002", date: "2026-05-04", time: "08:05 AM", status: "Present" },
  { name: "Angela Cruz", studentId: "STU-2026-003", date: "2026-05-04", time: "08:11 AM", status: "Present" },
  { name: "Mark Dela Cruz", studentId: "STU-2026-004", date: "2026-05-04", time: "08:18 AM", status: "Present" },
  { name: "Nicole Garcia", studentId: "STU-2026-005", date: "2026-05-04", time: "08:24 AM", status: "Present" }
];

function renderRecords(records = attendanceRecords) {
  const tableBody = document.querySelector("#recordsTable");
  if (!tableBody) return;

  // TODO: fetch data from database when Flask backend is connected.
  tableBody.innerHTML = records
    .map((record) => `
      <tr>
        <td>${record.name}</td>
        <td>${record.studentId}</td>
        <td>${record.date}</td>
        <td>${record.time}</td>
        <td><span class="badge success">${record.status}</span></td>
      </tr>
    `)
    .join("");
}

function renderRecentActivity() {
  const activityList = document.querySelector("#recentActivity");
  if (!activityList) return;

  activityList.innerHTML = attendanceRecords.slice(0, 3)
    .map((record) => `
      <div class="activity-item">
        <div>
          <strong>${record.name}</strong>
          <span>${record.studentId} marked present at ${record.time}</span>
        </div>
        <span class="badge success">${record.status}</span>
      </div>
    `)
    .join("");
}

function setupLogin() {
  const form = document.querySelector("#loginForm");
  if (!form) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    // TODO: connect to Flask API for real login authentication.
    window.location.href = "dashboard.html";
  });
}

function setupAttendance() {
  const startButton = document.querySelector("#startAttendance");
  const statusText = document.querySelector("#attendanceStatus");
  const log = document.querySelector("#attendanceLog");
  if (!startButton || !statusText || !log) return;

  startButton.addEventListener("click", () => {
    // TODO: connect to Flask API for live attendance processing.
    statusText.textContent = "Mock detection started...";
    log.innerHTML = `
      <div class="activity-item">
        <div>
          <strong>${attendanceRecords[0].name}</strong>
          <span>${attendanceRecords[0].studentId} detected from mock camera feed</span>
        </div>
        <span class="badge success">Present</span>
      </div>
    `;
  });
}

function setupRegisterUser() {
  const captureButton = document.querySelector("#captureFace");
  const preview = document.querySelector("#facePreview");
  const form = document.querySelector("#registerForm");
  const message = document.querySelector("#registerMessage");

  captureButton?.addEventListener("click", () => {
    // TODO: connect to Flask API for face image capture.
    preview.textContent = "Face captured";
    preview.classList.add("captured");
  });

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    // TODO: save student data through Flask API and database.
    message.textContent = "Mock user saved. Backend integration pending.";
    form.reset();
  });
}

function setupRecordsTools() {
  const searchInput = document.querySelector("#recordSearch");
  const exportButton = document.querySelector("#exportCsv");
  const exportMessage = document.querySelector("#exportMessage");

  searchInput?.addEventListener("input", () => {
    const keyword = searchInput.value.trim().toLowerCase();
    const filtered = attendanceRecords.filter((record) =>
      `${record.name} ${record.studentId} ${record.date} ${record.status}`.toLowerCase().includes(keyword)
    );
    renderRecords(filtered);
  });

  exportButton?.addEventListener("click", () => {
    // TODO: connect to Flask API for CSV export.
    exportMessage.textContent = "Export CSV is a UI-only placeholder.";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupLogin();
  setupAttendance();
  setupRegisterUser();
  setupRecordsTools();
  renderRecords();
  renderRecentActivity();
});
