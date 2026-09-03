export const reportFontAssets = {
  hankenRegular: new URL("./fonts/hanken-grotesk-regular.woff", import.meta.url)
    .href,
  hankenMedium: new URL("./fonts/hanken-grotesk-medium.woff", import.meta.url)
    .href,
  hankenSemibold: new URL(
    "./fonts/hanken-grotesk-semibold.woff",
    import.meta.url,
  ).href,
  newsreaderRegular: new URL("./fonts/newsreader-regular.woff", import.meta.url)
    .href,
} as const;

const fontSheet = document.createElement("style");
fontSheet.dataset.occupancyReportFonts = "";
fontSheet.textContent = `
  @font-face {
    font-family: "Hanken Grotesk";
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url("${reportFontAssets.hankenRegular}") format("woff");
  }
  @font-face {
    font-family: "Hanken Grotesk";
    font-style: normal;
    font-weight: 500;
    font-display: swap;
    src: url("${reportFontAssets.hankenMedium}") format("woff");
  }
  @font-face {
    font-family: "Hanken Grotesk";
    font-style: normal;
    font-weight: 600;
    font-display: swap;
    src: url("${reportFontAssets.hankenSemibold}") format("woff");
  }
  @font-face {
    font-family: "Newsreader";
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url("${reportFontAssets.newsreaderRegular}") format("woff");
  }
`;
document.head.append(fontSheet);
