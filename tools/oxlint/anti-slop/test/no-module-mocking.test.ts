import { noModuleMockingRule } from "../rules/no-module-mocking.ts";
import { ruleTester } from "./rule-tester.ts";

const error = { messageId: "moduleMock" };

ruleTester.run("anti-slop/no-module-mocking", noModuleMockingRule, {
  valid: [
    "import { vi } from './helpers'; vi.mock('./module');",
    "const vi = { mock() {} }; vi.mock('./module');",
    "function register(jest: { mock(name: string): void }) { jest.mock('./module'); }",
    "import { vi } from 'vite-plus/test'; const callback = vi.fn();",
    "import { vi } from 'vite-plus/test'; let api = vi; api.mock('./module');",
    "import { vi } from 'vite-plus/test'; const local = { mock() {} }; const api = vi; api = local; api.mock('./module');",
    "import { vi } from 'vite-plus/test'; const local = () => {}; const mock = vi.mock; mock = local; mock('./module');",
    "const local = { mock() {} }; local.mock.call(local, './module');",
    "const first = second; const second = first; first.mock('./module');",
    "const first = second; const second = first; first('./module');",
    "const first = second; const second = first; first.vi.mock('./module');",
  ],
  invalid: [
    {
      code: "import { vi } from 'vite-plus/test'; vi.mock('./module');",
      errors: [error],
    },
    {
      code: "import { jest } from '@jest/globals'; jest.mock('./module');",
      errors: [error],
    },
    { code: "globalThis.jest.mock('./module');", errors: [error] },
    { code: "jest.mock('./module');", errors: [error] },
    {
      code: "import { vi } from 'vite-plus/test'; vi.unstable_mockModule('./module');",
      errors: [error],
    },
    {
      code: "import { vi as api } from 'vitest'; api.doMock('./module');",
      errors: [error],
    },
    {
      code: "import * as api from 'vite-plus/test'; api.vi.mock('./module');",
      errors: [error],
    },
    {
      code: "import * as source from 'vite-plus/test'; const api = source; api.vi.mock('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi?.mock('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi[`mock`]('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi['mock' as const]('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi['mock' satisfies string]('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; const api = vi; api.mock('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; const mock = vi.mock; mock('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; const { mock } = vi; mock('./module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi.mock.call(vi, './module');",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; vi.mock.apply(vi, ['./module']);",
      errors: [error],
    },
    {
      code: "import { vi } from 'vite-plus/test'; const mock = vi.mock.bind(vi); mock('./module');",
      errors: [error],
    },
  ],
});
