# React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the React project supplied by
this starter.

## Project intent

Keep this section current with the user's audience, analytical goal, concrete
project details, aesthetic direction, interaction priorities, and approved
library or framework preferences. Preserve decisions that should guide later
agents.

## Use the supplied Studio integration

- `src/marimo-studio.d.ts` types the Studio custom elements and attributes for
  React. Keep the reference at the top of `src/App.tsx`. Extend application
  types in a separate declaration when the page introduces its own elements.
- `src/lib/use-marimo-value.ts` adapts an explicit `mo-value` host into React
  state. Keep the host in JSX so Studio can inspect and authorize its selector.

```tsx
import { useMarimoValue } from "./lib/use-marimo-value.ts";

type Row = { id: string; label: string };

const { hostRef } = useMarimoValue<Row[]>("rows");

return <span ref={hostRef} hidden mo-value="rows" />;
```

Use the supplied declarations as the type contract. A custom-element type error
indicates a missing declaration reference or an invalid attribute.

## Work within the React project

- Build with the React 19 and Deno versions pinned in `deno.json` and
  `deno.lock`.
- Keep the application entry in `src/main.tsx` and compose page components from
  `src/App.tsx` or focused modules under `src/`.
- Keep page styles in `src/style.css` or local CSS modules imported by the
  component that owns them.
- Put static files under `public/` and reference them from the page. The
  provider copies that directory into the built artifact.
- Prefer React state and browser APIs already available in the project. Add a
  dependency through the Deno import map and frozen lockfile when the page needs
  a maintained library.

Studio's React build runs type checking before bundling. Treat that build as the
acceptance boundary for declarations, imports, and packaged assets.
