/// <reference path="./marimo-studio.d.ts" />

const NOTEBOOK_LABEL = __NOTEBOOK_LABEL_JSON__;
const VIEW_HEADING = __VIEW_HEADING_JSON__;

export const App = () => (
  <div className="page">
    <header className="page-header">
      <p>{NOTEBOOK_LABEL}</p>
      <h1>{VIEW_HEADING}</h1>
    </header>
    <section className="results" aria-label="Notebook results">
      __NOTEBOOK_CELL_HOSTS_TSX__
    </section>
  </div>
);
