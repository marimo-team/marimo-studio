const source = document.querySelector("#briefing-data");
const button = document.querySelector("#copy-briefing");
const status = document.querySelector("#copy-status");

const sync = () => {
  button.disabled = source.marimoValue === undefined;
  status.textContent = "";
};

source.addEventListener("marimo-value-updated", sync);
source.addEventListener("marimo-value-error", sync);
sync();

button.addEventListener("click", async () => {
  const report = source.marimoValue;
  if (report === undefined) {
    return;
  }
  const briefing = [
    "Revenue at a glance",
    `Scenario: ${report.scenario}`,
    `Projected revenue: ${report.total}`,
    `Change from baseline: ${report.change}`,
    `Forecast period: ${report.through}`,
    `Updated: ${report.updated_at}`,
  ].join("\n");
  try {
    await navigator.clipboard.writeText(briefing);
    status.textContent = "Briefing copied";
  } catch {
    status.textContent = "Clipboard unavailable";
  }
});
