(function () {
  const root = document.querySelector("[data-ingest]");
  if (!root) return;

  const statusEl = root.querySelector("[data-ingest-status]");
  const latestBtn = root.querySelector("[data-ingest-latest]");
  const form = root.querySelector("[data-ingest-history]");
  const buttons = root.querySelectorAll("button");
  let timer = null;
  let sawRunning = false;

  function setBusy(busy) {
    buttons.forEach((button) => {
      button.disabled = busy;
    });
  }

  function render(data) {
    if (!statusEl) return;
    statusEl.classList.remove("is-error", "is-ok", "is-busy");
    if (data.state === "running") {
      statusEl.classList.add("is-busy");
      statusEl.textContent = data.message || "Downloading from EDGAR…";
      setBusy(true);
      return;
    }
    setBusy(false);
    if (data.state === "error" && data.error) {
      statusEl.classList.add("is-error");
      statusEl.textContent = data.error;
      return;
    }
    if (data.state === "done" && data.message) {
      statusEl.classList.add("is-ok");
      statusEl.textContent = data.message;
    }
  }

  async function poll() {
    const response = await fetch("/ingest/status");
    const data = await response.json();
    render(data);
    if (data.state === "running") {
      sawRunning = true;
      return;
    }
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    if (sawRunning && data.state === "done") {
      window.location.reload();
    }
  }

  function watch() {
    if (timer) return;
    timer = setInterval(() => {
      poll().catch(() => {});
    }, 2000);
    poll().catch(() => {});
  }

  async function post(url, body) {
    setBusy(true);
    const options = { method: "POST", headers: { Accept: "application/json" } };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const data = await response.json();
    render(data);
    if (response.ok || response.status === 202) {
      sawRunning = true;
      watch();
    }
  }

  if (latestBtn) {
    latestBtn.addEventListener("click", () => {
      post("/ingest/latest").catch((err) => {
        render({ state: "error", error: String(err) });
        setBusy(false);
      });
    });
  }

  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      post("/ingest/history", {
        start: data.get("start"),
        end: data.get("end"),
      }).catch((err) => {
        render({ state: "error", error: String(err) });
        setBusy(false);
      });
    });
  }
})();
