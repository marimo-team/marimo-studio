import license from "@fontsource/inter/LICENSE" with { type: "text" };
import medium from "@fontsource/inter/files/inter-latin-500-normal.woff" with {
  type: "bytes",
};
import regular from "@fontsource/inter/files/inter-latin-400-normal.woff" with {
  type: "bytes",
};
import semibold from "@fontsource/inter/files/inter-latin-600-normal.woff" with {
  type: "bytes",
};

const fonts = new URL("../public/fonts/", import.meta.url);
await Deno.mkdir(fonts, { recursive: true });
await Promise.all([
  Deno.writeFile(new URL("inter-regular.woff", fonts), regular),
  Deno.writeFile(new URL("inter-medium.woff", fonts), medium),
  Deno.writeFile(new URL("inter-semibold.woff", fonts), semibold),
  Deno.writeTextFile(new URL("INTER-LICENSE.txt", fonts), license),
]);
