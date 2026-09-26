export const reportFontAssets = {
  regular: new URL("./fonts/inter-regular.woff", import.meta.url)
    .href,
  medium: new URL("./fonts/inter-medium.woff", import.meta.url)
    .href,
  semibold: new URL("./fonts/inter-semibold.woff", import.meta.url)
    .href,
} as const;

const fontSheet = document.createElement("style");
fontSheet.dataset.occupancyReportFonts = "";
fontSheet.textContent = [
  [400, reportFontAssets.regular],
  [500, reportFontAssets.medium],
  [600, reportFontAssets.semibold],
].map(([weight, src]) => `
  @font-face {
    font-family: "Inter";
    font-style: normal;
    font-weight: ${weight};
    font-display: swap;
    src: url("${src}") format("woff");
  }`).join("");
document.head.append(fontSheet);
