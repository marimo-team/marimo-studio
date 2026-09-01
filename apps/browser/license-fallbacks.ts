export type LicenseFallbackProvenance = Readonly<{
  commit: string;
  path: string;
  repository: string;
  url: string;
}>;

export type LicenseFallbackFile = Readonly<{
  name: string;
  provenance: LicenseFallbackProvenance;
  sha256: string;
}>;

export type BrowserLicenseFallback = Readonly<{
  author?: string;
  files: readonly LicenseFallbackFile[];
  license: string;
}>;

const githubFile = (
  name: string,
  sha256: string,
  repository: string,
  commit: string,
  path: string,
): LicenseFallbackFile => ({
  name,
  provenance: {
    commit,
    path,
    repository: `https://github.com/${repository}`,
    url: `https://raw.githubusercontent.com/${repository}/${commit}/${path}`,
  },
  sha256,
});

const family = (
  coordinates: readonly string[],
  license: string,
  files: readonly LicenseFallbackFile[],
) =>
  coordinates.map(
    (coordinate) => [coordinate, { files, license } satisfies BrowserLicenseFallback] as const,
  );

const canonicalMit = (coordinate: string, author: string) =>
  [
    coordinate,
    {
      author,
      files: [
        githubFile(
          "SPDX-MIT.txt",
          "b05785f9f18e6716bab63424b11454513b9943a222595b70411009202fc592b5",
          "spdx/license-list-data",
          "d46e94e2c78ceede1cfc63cfa0396472d2798d4c",
          "text/MIT.txt",
        ),
      ],
      license: "MIT",
    } satisfies BrowserLicenseFallback,
  ] as const;

const fallbackEntries = [
  ...family(["@ai-sdk/provider-utils@5.0.12"], "Apache-2.0", [
    githubFile(
      "LICENSE",
      "b4f9adb7c568904834d0dd6cc98d16c390d21ca32fc17ae7a267715269bd5529",
      "vercel/ai",
      "0319ff37bbff832e8e434f2d42716ae9edf5947d",
      "LICENSE",
    ),
  ]),
  ...family(["@bufbuild/protobuf@1.10.1"], "(Apache-2.0 AND BSD-3-Clause)", [
    githubFile(
      "LICENSE",
      "6da19f017fad6716cbc9c938972ebee29957c295b8a4d51060dfb03da51d8502",
      "bufbuild/protobuf-es",
      "e31c1b139cf1e7fea2fb914f650af3c28c42ec68",
      "LICENSE",
    ),
    githubFile(
      "google-varint-BSD-3-Clause.txt",
      "2c5e86fa106ba6a35652db103b937f0a9d96887b5d718a9eb956379c2ce8c66b",
      "bufbuild/protobuf-es",
      "e31c1b139cf1e7fea2fb914f650af3c28c42ec68",
      "packages/protobuf/src/google/varint.ts",
    ),
  ]),
  ...family(["@connectrpc/connect@1.6.1", "@connectrpc/connect-web@1.6.1"], "Apache-2.0", [
    githubFile(
      "LICENSE",
      "5780f83112ef0026ca40dd55d88535f4475962a2edc90f39410bf908502d7e62",
      "connectrpc/connect-es",
      "42d78b24903d6d278eab4705cf59d157c3efe816",
      "LICENSE",
    ),
  ]),
  ...family(["@img-comparison-slider/react@8.0.2"], "MIT", [
    githubFile(
      "LICENSE",
      "7ea86ea7d6b3bf7d1368064512d24bdbe8a5c7c66dd7e0e55f608ec3c39cc2b3",
      "sneas/img-comparison-slider",
      "3178cff5bd77d83d404e1605e9c446c9af805a85",
      "LICENSE",
    ),
  ]),
  ...family(["img-comparison-slider@8.0.6"], "MIT", [
    githubFile(
      "LICENSE",
      "7ea86ea7d6b3bf7d1368064512d24bdbe8a5c7c66dd7e0e55f608ec3c39cc2b3",
      "sneas/img-comparison-slider",
      "9d04b10e03670294e11a893465f8c7062840eeac",
      "LICENSE",
    ),
  ]),
  ...family(["@marimo-team/react-slotz@0.2.0"], "MIT", [
    githubFile(
      "LICENSE",
      "ab987ab9f287819eab7f701cacd491e76ab6ee94b2abe5dc2e0afc3aa51f2b00",
      "marimo-team/react-slotz",
      "c17620e7ccad705ff9b7bc0312febbb3c9c50899",
      "LICENSE",
    ),
  ]),
  ...family(
    [
      "@radix-ui/number@1.1.1",
      "@radix-ui/react-context@1.1.2",
      "@radix-ui/react-direction@1.1.1",
      "@radix-ui/react-id@1.1.1",
      "@radix-ui/react-use-callback-ref@1.1.1",
      "@radix-ui/react-use-escape-keydown@1.1.1",
      "@radix-ui/react-use-layout-effect@1.1.1",
      "@radix-ui/react-use-previous@1.1.1",
      "@radix-ui/react-use-size@1.1.1",
    ],
    "MIT",
    [
      githubFile(
        "LICENSE",
        "0e80a2d229d2fd4fc7e8636142ec5d0ff0bc031f14c15b682e2ac01dfd5b5138",
        "radix-ui/primitives",
        "fcef0668a5c827e5a4baac405474d75680f9a4eb",
        "LICENSE",
      ),
    ],
  ),
  ...family(["@revealjs/react@0.2.1"], "MIT", [
    githubFile(
      "LICENSE",
      "b2883e4b610bfa1b4d8fff84c4d4b825cc7d553cbd9fec4777c04068a2859dc0",
      "hakimel/reveal.js",
      "8bbbcf83104b817f5882a0e04772b9f9e26b265b",
      "LICENSE",
    ),
  ]),
  ...family(
    [
      "@uiw/codemirror-extensions-basic-setup@4.25.4",
      "@uiw/react-codemirror@4.25.4",
      "react-codemirror-merge@4.25.4",
    ],
    "MIT",
    [
      githubFile(
        "LICENSE",
        "fd1f049b3bb5cbaf5143516b72dbc6805cd30cca0cda94edb37160e37662fd17",
        "uiwjs/react-codemirror",
        "da57d146014e47508b13d03739834fd50e0b3e40",
        "LICENSE",
      ),
    ],
  ),
  ...family(["@uiw/codemirror-extensions-langs@4.25.7"], "MIT", [
    githubFile(
      "LICENSE",
      "fd1f049b3bb5cbaf5143516b72dbc6805cd30cca0cda94edb37160e37662fd17",
      "uiwjs/react-codemirror",
      "d61fc4f751540d2548e03293812beae94c9fe59d",
      "LICENSE",
    ),
  ]),
  ...family(["react-easy-swipe@0.0.21"], "MIT", [
    githubFile(
      "LICENSE",
      "17e4fbc903cba1f1430c82cc0ad9f2472fd4a73e9b72168967255ebcbab1d9b7",
      "leandrowd/react-easy-swipe",
      "a620dfd858b725190dd631199c7536e519a5140f",
      "LICENSE",
    ),
  ]),
  ...family(["react-property@2.0.2"], "MIT", [
    githubFile(
      "LICENSE",
      "52412d7bc7ce4157ea628bbaacb8829e0a9cb3c58f57f99176126bc8cf2bfc85",
      "facebook/react",
      "1314299c7f70914d61d8e1cef56767f112110674",
      "LICENSE",
    ),
  ]),
  ...family(["react-remove-scroll-bar@2.3.8"], "MIT", [
    githubFile(
      "LICENSE",
      "a79aae0c0f21990d9d963bb3c5a79cdcea9a46f8523ba55c58d7fe776b6ebc84",
      "theKashey/react-remove-scroll-bar",
      "8ca9ba5ea52de03308fe8ced94f7b159a44d28ff",
      "LICENSE",
    ),
  ]),
  ...family(["rehype-katex@7.0.1"], "MIT", [
    githubFile(
      "license",
      "cb992262f361a5359e6771c28740d33c7041e15332ae8537fae40538992591a9",
      "remarkjs/remark-math",
      "88a9497e1ede93b958237c85edbf5651faeca7af",
      "license",
    ),
  ]),
  ...family(["remark-math@6.0.0"], "MIT", [
    githubFile(
      "license",
      "cb992262f361a5359e6771c28740d33c7041e15332ae8537fae40538992591a9",
      "remarkjs/remark-math",
      "d5d0660b150810a535bbb07eac6cc96a4510aa24",
      "license",
    ),
  ]),
  ...family(["toggle-selection@1.0.6"], "MIT", [
    githubFile(
      "LICENSE",
      "771e50e27b24269923639e8e0cc650e7187ffeab5726f6a6f47d9ea83865089d",
      "sudodoki/toggle-selection",
      "888650b271ee4937e2baff6a43bee744635601e3",
      "LICENSE",
    ),
  ]),
  ...family(["pyodide@314.0.0"], "MPL-2.0", [
    githubFile(
      "LICENSE",
      "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5",
      "pyodide/pyodide",
      "717db5e24fc6602393d194bdcd396554aa4fa90f",
      "LICENSE",
    ),
  ]),
  canonicalMit("string-dedent@3.0.2", "Justin Ridgewell <justin@ridgewell.name>"),
  canonicalMit("thememirror@2.0.1", "vdemedes | vadimdemedes@hey.com | https://vadimdemedes.com"),
  canonicalMit("typescript-memoize@1.1.1", "Darryl Hodgins <darrylh@darryh.ca>"),
] as const;

const fallbackMap = new Map<string, BrowserLicenseFallback>(fallbackEntries);
if (fallbackMap.size !== fallbackEntries.length) {
  throw new Error("Browser license fallback coordinates must be unique");
}

export const browserLicenseFallbacks: ReadonlyMap<string, BrowserLicenseFallback> = fallbackMap;

export const browserLicenseFallbackFor = (coordinate: string): BrowserLicenseFallback | undefined =>
  browserLicenseFallbacks.get(coordinate);
