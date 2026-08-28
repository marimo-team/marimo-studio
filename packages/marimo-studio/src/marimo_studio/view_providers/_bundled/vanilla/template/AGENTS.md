# HTML starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the single-document project
supplied by this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

## Use the supplied Studio integration

`index.html` defines `observeMarimoValue` inside its module script. Use it when
page JavaScript consumes a JSON-compatible notebook value. Keep the
corresponding `mo-value` host in authored HTML so Studio can inspect and
authorize its selector.

```html
<span id="rows-data" hidden mo-value="rows"></span>
```

```js
const source = document.querySelector("#rows-data");
if (source) {
  const stop = observeMarimoValue(source, {
    onValue: (rows) => renderRows(rows),
    onError: (error) => renderError(error.message),
  });
  window.addEventListener("pagehide", stop, { once: true });
}
```

## Work within the HTML project

- Keep document structure, styles, and browser behavior in `index.html`.
- Keep projection hosts inside `#app-shell`.
- Inline project-owned CSS, JavaScript, images, and fonts with the document.
  External HTTP URLs and `data:` URLs remain available.
- Use browser APIs for focused interaction. Choose the React or Svelte starter
  when the page needs a component build and a multi-file application source.

Studio publishes this file directly after validating its HTML and projection
hosts. Treat the built document as the acceptance boundary for the page.
