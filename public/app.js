const state = {
  records: [],
  selectedRecord: null,
  loading: false,
};

const iconMap = {
  sun: "☀",
  "sun-cloud": "◐",
  cloud: "☁",
  fog: "≋",
  drizzle: "☂",
  rain: "☔",
  snow: "❄",
  storm: "⚡",
};

const els = {
  form: document.querySelector("#weather-form"),
  location: document.querySelector("#location"),
  startDate: document.querySelector("#start-date"),
  endDate: document.querySelector("#end-date"),
  notes: document.querySelector("#notes"),
  currentLocationButton: document.querySelector("#current-location-button"),
  saveButton: document.querySelector("#save-button"),
  alert: document.querySelector("#alert"),
  apiStatus: document.querySelector("#api-status"),
  lastUpdated: document.querySelector("#last-updated"),
  currentWeather: document.querySelector("#current-weather"),
  forecastGrid: document.querySelector("#forecast-grid"),
  rangeTable: document.querySelector("#range-table"),
  historyList: document.querySelector("#history-list"),
  mapFrame: document.querySelector("#map-frame"),
  mapLink: document.querySelector("#map-link"),
  editDialog: document.querySelector("#edit-dialog"),
  editForm: document.querySelector("#edit-form"),
  editId: document.querySelector("#edit-id"),
  editLocation: document.querySelector("#edit-location"),
  editStartDate: document.querySelector("#edit-start-date"),
  editEndDate: document.querySelector("#edit-end-date"),
  editNotes: document.querySelector("#edit-notes"),
  closeEdit: document.querySelector("#close-edit"),
  cancelEdit: document.querySelector("#cancel-edit"),
};

function pad(value) {
  return String(value).padStart(2, "0");
}

function toDateInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function selectedUnitSystem(scope = document) {
  return scope.querySelector("input[name='unitSystem']:checked")?.value || "imperial";
}

function setLoading(isLoading) {
  state.loading = isLoading;
  els.saveButton.disabled = isLoading;
  els.currentLocationButton.disabled = isLoading;
  els.apiStatus.textContent = isLoading ? "Loading" : "Ready";
}

function showAlert(message, type = "error") {
  els.alert.textContent = message;
  els.alert.classList.toggle("success", type === "success");
  els.alert.hidden = false;
}

function clearAlert() {
  els.alert.hidden = true;
  els.alert.textContent = "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error?.message || "Request failed.");
  }
  return data;
}

function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatDate(value) {
  if (!value) return "N/A";
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(value) {
  if (!value) return "N/A";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function weatherIcon(token) {
  return iconMap[token] || "☁";
}

function tempUnit(record) {
  return record?.current?.units?.temperature || (record?.unitSystem === "metric" ? "°C" : "°F");
}

function windUnit(record) {
  return record?.current?.units?.windSpeed || (record?.unitSystem === "metric" ? "km/h" : "mph");
}

function precipitationUnit(record) {
  return record?.current?.units?.precipitation || (record?.unitSystem === "metric" ? "mm" : "inch");
}

function renderCurrent(record) {
  if (!record) {
    els.currentWeather.className = "current-weather empty-state";
    els.currentWeather.innerHTML = `
      <div class="weather-mark" aria-hidden="true">◎</div>
      <div><p class="muted">Saved weather appears here.</p></div>
    `;
    els.lastUpdated.textContent = "No request yet";
    els.mapFrame.removeAttribute("src");
    els.mapLink.hidden = true;
    return;
  }

  const current = record.current;
  const air = record.airQuality || {};
  const aqi = air.available ? formatNumber(air.usAqi) : "N/A";
  els.currentWeather.className = "current-weather";
  els.lastUpdated.textContent = `Updated ${formatDateTime(record.updatedAt)}`;
  els.currentWeather.innerHTML = `
    <div class="weather-mark" aria-hidden="true">${weatherIcon(current.icon)}</div>
    <div>
      <p class="location-name">${record.resolvedName}</p>
      <div class="temperature-line">
        <strong>${formatNumber(current.temperature)}${tempUnit(record)}</strong>
        <span>${current.condition}</span>
      </div>
      <p class="muted">${record.startDate} to ${record.endDate}</p>
      <div class="metric-grid">
        <div class="metric"><span>Feels</span><strong>${formatNumber(current.apparentTemperature)}${tempUnit(record)}</strong></div>
        <div class="metric"><span>Humidity</span><strong>${formatNumber(current.humidity)}%</strong></div>
        <div class="metric"><span>Wind</span><strong>${formatNumber(current.windSpeed)} ${windUnit(record)}</strong></div>
        <div class="metric"><span>AQI</span><strong>${aqi}</strong></div>
        <div class="metric"><span>Rain</span><strong>${formatNumber(current.precipitation, 2)} ${precipitationUnit(record)}</strong></div>
        <div class="metric"><span>Clouds</span><strong>${formatNumber(current.cloudCover)}%</strong></div>
        <div class="metric"><span>Pressure</span><strong>${formatNumber(current.pressure)} ${current.units?.pressure || "hPa"}</strong></div>
        <div class="metric"><span>Coordinates</span><strong>${formatNumber(record.coordinates.latitude, 3)}, ${formatNumber(record.coordinates.longitude, 3)}</strong></div>
      </div>
    </div>
  `;

  if (record.map?.embedUrl) {
    els.mapFrame.src = record.map.embedUrl;
    els.mapLink.href = record.map.externalUrl;
    els.mapLink.hidden = false;
  }
}

function renderForecast(record) {
  const days = record?.forecast || [];
  if (!days.length) {
    els.forecastGrid.innerHTML = `<p class="muted">No forecast loaded.</p>`;
    return;
  }
  els.forecastGrid.innerHTML = days
    .map(
      (day) => `
        <article class="forecast-day">
          <div class="icon" aria-hidden="true">${weatherIcon(day.icon)}</div>
          <div>
            <strong>${formatDate(day.date)}</strong>
            <p class="muted">${day.condition}</p>
          </div>
          <p><strong>${formatNumber(day.temperatureMax)}${tempUnit(record)}</strong> / ${formatNumber(day.temperatureMin)}${tempUnit(record)}</p>
          <p class="muted">Rain ${formatNumber(day.precipitation, 2)} ${day.units?.precipitation || precipitationUnit(record)}</p>
          <p class="muted">UV ${formatNumber(day.uvIndexMax, 1)}</p>
        </article>
      `
    )
    .join("");
}

function renderRange(record) {
  const days = record?.rangeDaily || [];
  if (!days.length) {
    els.rangeTable.innerHTML = `<p class="muted">No date range loaded.</p>`;
    return;
  }
  els.rangeTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Condition</th>
          <th>High</th>
          <th>Low</th>
          <th>Precipitation</th>
          <th>Wind Max</th>
        </tr>
      </thead>
      <tbody>
        ${days
          .map(
            (day) => `
              <tr>
                <td>${formatDate(day.date)}</td>
                <td>${weatherIcon(day.icon)} ${day.condition}</td>
                <td>${formatNumber(day.temperatureMax)}${tempUnit(record)}</td>
                <td>${formatNumber(day.temperatureMin)}${tempUnit(record)}</td>
                <td>${formatNumber(day.precipitation, 2)} ${day.units?.precipitation || precipitationUnit(record)}</td>
                <td>${formatNumber(day.windSpeedMax)} ${day.units?.windSpeed || windUnit(record)}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderHistory() {
  if (!state.records.length) {
    els.historyList.innerHTML = `<p class="muted">No saved requests yet.</p>`;
    return;
  }

  els.historyList.innerHTML = state.records
    .map(
      (record) => `
        <article class="history-row">
          <div>
            <h3>${record.resolvedName}</h3>
            <p>${record.startDate} to ${record.endDate} · ${formatNumber(record.current.temperature)}${tempUnit(record)} · ${record.current.condition}</p>
          </div>
          <div class="row-actions">
            <button type="button" data-action="view" data-id="${record.id}" title="View">View</button>
            <button type="button" data-action="edit" data-id="${record.id}" title="Edit">Edit</button>
            <button class="danger" type="button" data-action="delete" data-id="${record.id}" title="Delete">Delete</button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderAll() {
  renderCurrent(state.selectedRecord);
  renderForecast(state.selectedRecord);
  renderRange(state.selectedRecord);
  renderHistory();
}

async function loadRecords() {
  const data = await api("/api/requests");
  state.records = data.records;
  state.selectedRecord = state.selectedRecord || state.records[0] || null;
  renderAll();
}

function formPayload() {
  return {
    location: els.location.value.trim(),
    startDate: els.startDate.value,
    endDate: els.endDate.value,
    notes: els.notes.value.trim(),
    unitSystem: selectedUnitSystem(),
  };
}

async function createFromPayload(payload) {
  setLoading(true);
  clearAlert();
  try {
    const data = await api("/api/requests", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedRecord = data.record;
    await loadRecords();
    state.selectedRecord = data.record;
    renderAll();
    showAlert("Weather request saved.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    setLoading(false);
  }
}

function currentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Current location is unavailable in this browser."));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error("Current location permission was not granted.")), {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 300000,
    });
  });
}

function openEdit(record) {
  els.editId.value = record.id;
  els.editLocation.value = record.locationQuery;
  els.editStartDate.value = record.startDate;
  els.editEndDate.value = record.endDate;
  els.editNotes.value = record.notes || "";
  document
    .querySelectorAll("input[name='editUnitSystem']")
    .forEach((input) => (input.checked = input.value === record.unitSystem));
  els.editDialog.showModal();
}

async function updateRecord() {
  const id = els.editId.value;
  const unitSystem = document.querySelector("input[name='editUnitSystem']:checked")?.value || "imperial";
  setLoading(true);
  clearAlert();
  try {
    const data = await api(`/api/requests/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        location: els.editLocation.value.trim(),
        startDate: els.editStartDate.value,
        endDate: els.editEndDate.value,
        notes: els.editNotes.value.trim(),
        unitSystem,
      }),
    });
    els.editDialog.close();
    state.selectedRecord = data.record;
    await loadRecords();
    state.selectedRecord = data.record;
    renderAll();
    showAlert("Weather request updated.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    setLoading(false);
  }
}

async function deleteRecord(id) {
  if (!confirm("Delete this saved weather request?")) return;
  setLoading(true);
  clearAlert();
  try {
    await api(`/api/requests/${id}`, { method: "DELETE" });
    state.selectedRecord = null;
    await loadRecords();
    showAlert("Weather request deleted.", "success");
  } catch (error) {
    showAlert(error.message);
  } finally {
    setLoading(false);
  }
}

function setDefaultDates() {
  const start = new Date();
  els.startDate.value = toDateInput(start);
  els.endDate.value = toDateInput(addDays(start, 4));
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  createFromPayload(formPayload());
});

els.currentLocationButton.addEventListener("click", async () => {
  setLoading(true);
  clearAlert();
  try {
    const position = await currentPosition();
    await createFromPayload({
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      startDate: els.startDate.value,
      endDate: els.endDate.value,
      notes: els.notes.value.trim(),
      unitSystem: selectedUnitSystem(),
    });
  } catch (error) {
    showAlert(error.message);
    setLoading(false);
  }
});

els.historyList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const record = state.records.find((item) => item.id === Number(button.dataset.id));
  if (!record) return;
  if (button.dataset.action === "view") {
    state.selectedRecord = record;
    renderAll();
  }
  if (button.dataset.action === "edit") {
    openEdit(record);
  }
  if (button.dataset.action === "delete") {
    deleteRecord(record.id);
  }
});

document.querySelectorAll("[data-export]").forEach((button) => {
  button.addEventListener("click", () => {
    window.location.href = `/api/export?format=${button.dataset.export}`;
  });
});

els.editForm.addEventListener("submit", (event) => {
  event.preventDefault();
  updateRecord();
});

els.closeEdit.addEventListener("click", () => els.editDialog.close());
els.cancelEdit.addEventListener("click", () => els.editDialog.close());

setDefaultDates();
loadRecords().catch((error) => showAlert(error.message));
