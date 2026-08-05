const copyButton = document.querySelector("[data-copy-briefing]");
const copyStatus = document.querySelector("[data-copy-status]");
const briefingSource = document.querySelector("#briefing-data");

const currentReport = () => {
  const value = briefingSource?.marimoValue;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : undefined;
};

const updateCopyState = () => {
  if (copyButton instanceof HTMLButtonElement) {
    copyButton.disabled = currentReport() === undefined;
  }
};

const currentBriefing = () => {
  const report = currentReport();
  if (!report) {
    return "";
  }
  return [
    "Revenue at a glance",
    `Scenario: ${report.scenario}`,
    `Projected revenue: ${report.total}`,
    `Change from baseline: ${report.change}`,
    `Forecast period: ${report.through}`,
    `Updated: ${report.updated_at}`,
  ].join("\n");
};

briefingSource?.addEventListener("marimo-value-updated", updateCopyState);
briefingSource?.addEventListener("marimo-value-error", updateCopyState);
updateCopyState();

document.addEventListener("click", async (event) => {
  const target =
    event.target instanceof Element
      ? event.target.closest("[data-copy-briefing]")
      : null;
  if (!(target instanceof HTMLButtonElement) || !(copyStatus instanceof HTMLElement)) {
    return;
  }
  try {
    await navigator.clipboard.writeText(currentBriefing());
    copyStatus.textContent = "Briefing copied";
  } catch {
    copyStatus.textContent = "Clipboard unavailable";
  }
});
