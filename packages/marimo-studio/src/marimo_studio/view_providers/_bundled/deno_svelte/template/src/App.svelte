<script lang="ts">
  const notebookLabel = __NOTEBOOK_LABEL__;
  const viewHeading = __VIEW_HEADING__;
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
    <section class="results" aria-label="Notebook results"></section>
  {/if}
</div>
