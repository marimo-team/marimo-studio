<script lang="ts">
  const notebookLabel = __NOTEBOOK_NAME_JSON__;
  const viewHeading = __VIEW_HEADING_JSON__;
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
      __NOTEBOOK_CELL_HOSTS_SVELTE__
    </section>
  {/if}
</div>
