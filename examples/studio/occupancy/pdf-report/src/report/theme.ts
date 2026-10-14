import { defaultPrimitives } from "../pdf/themes/primitives.ts";
import type { PdfcnTheme } from "../pdf/types/pdf-themes.ts";

/**
 * The Architect's Field Report palette as a pdfcn theme: white paper, deep teal
 * ink, cool gray rules, and one ember-orange signal for occupied states.
 */
export const fieldReportTheme: PdfcnTheme = {
  colors: {
    accent: "#fa4e1d",
    background: "#ffffff",
    border: "#dfe7ea",
    destructive: "#fa4e1d",
    foreground: "#102126",
    info: "#3d5761",
    muted: "#f1f7f9",
    mutedForeground: "#677b82",
    primary: "#102126",
    primaryForeground: "#ffffff",
    success: "#2f6f63",
    warning: "#c2410c",
  },
  name: "field-report",
  page: {
    orientation: "portrait",
    size: "A4",
  },
  primitives: defaultPrimitives,
  spacing: {
    componentGap: 12,
    page: {
      marginBottom: 46,
      marginLeft: 40,
      marginRight: 40,
      marginTop: 36,
    },
    paragraphGap: 8,
    sectionGap: 20,
  },
  typography: {
    body: {
      fontFamily: "Inter",
      fontSize: 9.5,
      lineHeight: 1.55,
    },
    heading: {
      fontFamily: "Inter",
      fontSize: {
        h1: 28,
        h2: 20,
        h3: 15,
        h4: 12.5,
        h5: 11,
        h6: 9.5,
      },
      fontWeight: 600,
      lineHeight: 1.2,
    },
  },
};

/** Series colors shared by the report's charts. */
export const chartColors = {
  occupied: "#fa4e1d",
  vacant: "#3d5761",
  ink: "#102126",
  soft: "#fdd9cc",
  mist: "#f1f7f9",
} as const;
