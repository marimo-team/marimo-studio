/// <reference path="./marimo-studio.d.ts" />

const NOTEBOOK_LABEL = __NOTEBOOK_LABEL__;
const VIEW_HEADING = __VIEW_HEADING__;

export const App = () => (
  <div className="page">
    <header className="page-header">
      <p>{NOTEBOOK_LABEL}</p>
      <h1>{VIEW_HEADING}</h1>
    </header>
    <section className="results" aria-label="Notebook results" />
  </div>
);
