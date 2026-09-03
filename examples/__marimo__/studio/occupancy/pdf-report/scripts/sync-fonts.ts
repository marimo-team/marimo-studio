import hankenLicense from "@fontsource/hanken-grotesk/LICENSE" with {
  type: "text",
};
import hankenMedium from "@fontsource/hanken-grotesk/files/hanken-grotesk-latin-500-normal.woff" with {
  type: "bytes",
};
import hankenRegular from "@fontsource/hanken-grotesk/files/hanken-grotesk-latin-400-normal.woff" with {
  type: "bytes",
};
import hankenSemibold from "@fontsource/hanken-grotesk/files/hanken-grotesk-latin-600-normal.woff" with {
  type: "bytes",
};
import newsreaderLicense from "@fontsource/newsreader/LICENSE" with {
  type: "text",
};
import newsreaderRegular from "@fontsource/newsreader/files/newsreader-latin-400-normal.woff" with {
  type: "bytes",
};

const fonts = new URL("../public/fonts/", import.meta.url);
await Deno.mkdir(fonts, { recursive: true });
await Promise.all([
  Deno.writeFile(new URL("hanken-grotesk-regular.woff", fonts), hankenRegular),
  Deno.writeFile(new URL("hanken-grotesk-medium.woff", fonts), hankenMedium),
  Deno.writeFile(
    new URL("hanken-grotesk-semibold.woff", fonts),
    hankenSemibold,
  ),
  Deno.writeFile(new URL("newsreader-regular.woff", fonts), newsreaderRegular),
  Deno.writeTextFile(
    new URL("HANKEN-GROTESK-LICENSE.txt", fonts),
    hankenLicense,
  ),
  Deno.writeTextFile(
    new URL("NEWSREADER-LICENSE.txt", fonts),
    newsreaderLicense,
  ),
]);
