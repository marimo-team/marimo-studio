import { Document, Font } from "@react-pdf/renderer";
import type { DocumentProps } from "@react-pdf/renderer";
// @deno-types="npm:@types/react@19.2.10"
import type { ReactElement } from "react";

import { reportFontAssets } from "../install-report-fonts.ts";
import { EnvironmentPage } from "./EnvironmentPage.tsx";
import { ExecutivePage } from "./ExecutivePage.tsx";
import { ModelPage } from "./ModelPage.tsx";
import { typefaces } from "./theme.ts";
import type { OccupancyReportData } from "./types.ts";

Font.register({
  family: typefaces.body,
  fonts: [
    { src: reportFontAssets.regular, fontWeight: 400 },
    { src: reportFontAssets.medium, fontWeight: 500 },
    { src: reportFontAssets.semibold, fontWeight: 600 },
  ],
});
Font.registerHyphenationCallback((word) => [word]);

export const OccupancyReport = (
  { report }: { report: OccupancyReportData },
): ReactElement<DocumentProps> => (
  <Document
    title={`${report.room} Occupancy Field Report`}
    author="marimo-studio"
    subject="Building occupancy, environmental signals, and model evidence"
    keywords="occupancy, facilities, carbon dioxide, sensors, model review"
    language="en"
    pageLayout="oneColumn"
  >
    <ExecutivePage report={report} />
    <EnvironmentPage report={report} />
    <ModelPage report={report} />
  </Document>
);
