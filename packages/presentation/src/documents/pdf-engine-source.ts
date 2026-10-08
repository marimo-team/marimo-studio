// The pdf.js parsing engine as source text. Importing it through this module
// names its chunk after this file: the Prepared runtime's asset guard rejects
// chunk names containing "worker", which it reserves for notebook runtimes.
export { default } from "pdfjs-dist/build/pdf.worker.min.mjs?raw";
