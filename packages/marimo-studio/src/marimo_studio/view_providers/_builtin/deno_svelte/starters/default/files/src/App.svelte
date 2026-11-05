<script lang="ts">
  const notebookLabel = STARTER_NOTEBOOK_LABEL_JSON;
  const viewHeading = STARTER_VIEW_TITLE_JSON;
  let resultsVisible = $state(true);
</script>

<div class="page">
  <header class="page-header">
    <div>
      <p>{notebookLabel}</p>
      <h1>{viewHeading}</h1>
    </div>
    <button type="button" onclick={() => (resultsVisible = !resultsVisible)}>
      {resultsVisible ? "Hide results" : "Show results"}
    </button>
  </header>

  {#if resultsVisible}
    <section class="results" aria-label="Notebook results">
      STARTER_NOTEBOOK_CELL_HOSTS_SVELTE
    </section>
  {/if}
</div>
