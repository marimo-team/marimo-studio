/// <reference path="./marimo-studio.d.ts" />

const NOTEBOOK_LABEL = STARTER_NOTEBOOK_LABEL_JSON;
const VIEW_TITLE = STARTER_VIEW_TITLE_JSON;

export const App = () => (
  <div className="page">
    <header className="page-header">
      <p>{NOTEBOOK_LABEL}</p>
      <h1>{VIEW_TITLE}</h1>
    </header>
    <section className="results" aria-label="Notebook results">
      STARTER_NOTEBOOK_CELL_HOSTS_TSX
    </section>
  </div>
);
